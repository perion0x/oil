"""Monitor for on-chain commodity perp opportunities (oil + gold).

Tracks two trade setups:

1. Cross-venue convergence (Hyperliquid xyz, Extended, Variational Omni).
   All three reference the same underlying (and, for oil, the same futures
   contract with the same 5th-9th business day roll). When they diverge, the gap
   should close once the oracles are back on external pricing. Off-hours
   (weekends), each venue prices from its own order book with different
   smoothing and bands, so gaps can open wide and then snap shut at the Sunday
   reopen. Edges are measured on executable prices (sell the rich venue's bid,
   buy the cheap venue's ask) net of taker fees.

2. Roll-yield capture (Hyperliquid oil perp vs a PnL-neutral front-month leg).
   trade[XYZ] rolls WTIOIL / BRENTOIL from front to next month over 5 business
   days with no price adjustment, so in backwardation the perp drifts down by
   the front-next spread. A short HL perp hedged with a long front-month leg
   (CME future, or Veranta which adjusts entry prices at roll) earns that spread,
   minus funding paid while short.

Run:  python onchain_monitor.py            (one snapshot)
      python onchain_monitor.py --loop 60  (every 60s, appends to CSV)
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import re
import sys
import time
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import requests

ET = ZoneInfo("America/New_York")
HL_URL = "https://api.hyperliquid.xyz/info"
EXT_URL = "https://api.starknet.extended.exchange/api/v1/info/markets"
VAR_URL = "https://omni-client-api.prod.ap-northeast-1.variational.io/metadata/stats"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
UA = {"User-Agent": "Mozilla/5.0 (onchain-monitor)"}
VENUES = ("hl", "ext", "var")

# Taker fees (fraction of notional), base tier, as documented Sep 2026.
# HL xyz gold is excluded from growth mode, so it pays the full HIP-3 rate.
# Variational charges no fee; its cost is the quoted spread, already in bid/ask.
FEES = {
    "hl": {"WTI": 0.00009, "BRENT": 0.00009, "GOLD": 0.0009},
    "ext": {"WTI": 0.0001, "BRENT": 0.0001, "GOLD": 0.0001},
    "var": {"WTI": 0.0, "BRENT": 0.0, "GOLD": 0.0},
}

# asset -> venue -> candidate symbols (first one found wins). trade[XYZ] has
# listed WTI as both WTIOIL and CL.
ASSETS = {
    "WTI": {"hl": ["xyz:WTIOIL", "xyz:CL"], "ext": ["WTI-USD"], "var": ["CL"]},
    "BRENT": {"hl": ["xyz:BRENTOIL"], "ext": ["XBR-USD"], "var": ["BZ"]},
    "GOLD": {"hl": ["xyz:GOLD"], "ext": ["XAU-USD"], "var": ["XAU"]},
}

# Variational bid/ask quotes may be cached for up to 600s; skip older ones.
MAX_QUOTE_AGE_S = 600

# trade[XYZ] roll schedule (docs.trade.xyz roll-schedules). Each window starts
# at 17:30 ET on the given date; weights step 20% per business day over 5 steps.
# (start date, from contract, to contract)
ROLLS = {
    "WTI": [
        ("2026-09-08", "V6", "X6"), ("2026-10-07", "X6", "Z6"), ("2026-11-06", "Z6", "F7"),
        ("2026-12-07", "F7", "G7"), ("2027-01-08", "G7", "H7"), ("2027-02-05", "H7", "J7"),
        ("2027-03-05", "J7", "K7"), ("2027-04-07", "K7", "M7"), ("2027-05-07", "M7", "N7"),
        ("2027-06-07", "N7", "Q7"), ("2027-07-08", "Q7", "U7"), ("2027-08-06", "U7", "V7"),
        ("2027-09-08", "V7", "X7"), ("2027-10-07", "X7", "Z7"), ("2027-11-05", "Z7", "F8"),
        ("2027-12-07", "F8", "G8"),
    ],
    "BRENT": [
        ("2026-09-08", "X6", "Z6"), ("2026-10-07", "Z6", "F7"), ("2026-11-06", "F7", "G7"),
        ("2026-12-07", "G7", "H7"), ("2027-01-08", "H7", "J7"), ("2027-02-05", "J7", "K7"),
        ("2027-03-05", "K7", "M7"), ("2027-04-07", "M7", "N7"), ("2027-05-07", "N7", "Q7"),
        ("2027-06-07", "Q7", "U7"), ("2027-07-08", "U7", "V7"), ("2027-08-06", "V7", "X7"),
        ("2027-09-08", "X7", "Z7"), ("2027-10-07", "Z7", "F8"), ("2027-11-05", "F8", "G8"),
        ("2027-12-07", "G8", "H8"),
    ],
}
YAHOO_ROOT = {"WTI": "CL", "BRENT": "BZ"}


@dataclass
class Quote:
    venue: str
    mark: float | None = None
    oracle: float | None = None
    bid: float | None = None
    ask: float | None = None
    funding_1h: float | None = None  # fraction per hour, positive = longs pay
    quote_age_s: float | None = None  # age of bid/ask when the venue reports it


@dataclass
class RollState:
    front: str
    nxt: str
    start: dt.datetime
    steps: list[dt.datetime] = field(default_factory=list)

    def next_weight(self, now: dt.datetime) -> float:
        """Weight on the next-month contract at `now` (0.0 before, 1.0 after)."""
        return 0.2 * sum(1 for s in self.steps if now >= s)


def _f(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- fetchers

def parse_hl(payload) -> dict[str, Quote]:
    meta, ctxs = payload
    out = {}
    for asset, ctx in zip(meta["universe"], ctxs):
        name = asset["name"] if asset["name"].startswith("xyz:") else f"xyz:{asset['name']}"
        impact = ctx.get("impactPxs") or [None, None]
        out[name] = Quote(
            "hl",
            mark=_f(ctx.get("markPx")),
            oracle=_f(ctx.get("oraclePx")),
            bid=_f(impact[0]),
            ask=_f(impact[1]),
            funding_1h=_f(ctx.get("funding")),
        )
    return out


def fetch_hl() -> dict[str, Quote]:
    r = requests.post(HL_URL, json={"type": "metaAndAssetCtxs", "dex": "xyz"}, timeout=15)
    r.raise_for_status()
    return parse_hl(r.json())


def parse_ext(payload) -> dict[str, Quote]:
    rows = payload.get("data", payload) if isinstance(payload, dict) else payload
    out = {}
    for row in rows:
        s = row.get("marketStats", row)
        out[row["name"]] = Quote(
            "ext",
            mark=_f(s.get("markPrice")),
            oracle=_f(s.get("indexPrice")),
            bid=_f(s.get("bidPrice")),
            ask=_f(s.get("askPrice")),
            funding_1h=_f(s.get("fundingRate")),
        )
    return out


def fetch_ext() -> dict[str, Quote]:
    r = requests.get(EXT_URL, headers=UA, timeout=15)
    r.raise_for_status()
    return parse_ext(r.json())

def parse_var(payload, now: dt.datetime | None = None) -> dict[str, Quote]:
    """Variational Omni /metadata/stats. Uses the $100k quote as the executable
    price; drops bid/ask older than MAX_QUOTE_AGE_S (the API caches up to 600s)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    out = {}
    for row in payload.get("listings", []):
        quotes = row.get("quotes") or {}
        q = quotes.get("size_100k") or quotes.get("size_1k") or quotes.get("base") or {}
        age = None
        if quotes.get("updated_at"):
            # Trim nanoseconds so fromisoformat accepts it.
            ts = re.sub(r"(\.\d{6})\d*", r"\1", quotes["updated_at"]).replace("Z", "+00:00")
            age = (now - dt.datetime.fromisoformat(ts)).total_seconds()
        fresh = age is not None and age <= MAX_QUOTE_AGE_S
        # funding_rate is an annualised decimal (e.g. BTC 0.037 at an 8h interval).
        rate = _f(row.get("funding_rate"))
        out[row["ticker"]] = Quote(
            "var",
            mark=_f(row.get("mark_price")),
            bid=_f(q.get("bid")) if fresh else None,
            ask=_f(q.get("ask")) if fresh else None,
            funding_1h=rate / 8760 if rate is not None else None,
            quote_age_s=age,
        )
    return out


def fetch_var() -> dict[str, Quote]:
    r = requests.get(VAR_URL, headers=UA, timeout=15)
    r.raise_for_status()
    return parse_var(r.json())


def fetch_future(root: str, contract: str) -> float | None:
    """Last price of a futures contract from Yahoo, e.g. CL + X6 -> CLX26.NYM."""
    symbol = f"{root}{contract[0]}2{contract[1]}.NYM"
    try:
        r = requests.get(YAHOO_URL.format(symbol=symbol), headers=UA, timeout=15)
        r.raise_for_status()
        return _f(r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"])
    except Exception:
        return None


# ---------------------------------------------------------------- schedule logic

def business_days_from(start: dt.date, n: int) -> list[dt.date]:
    days, d = [], start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += dt.timedelta(days=1)
    return days


def roll_state(asset: str, now: dt.datetime) -> RollState:
    """The roll window that is in progress, or the next one if none is."""
    for start, front, nxt in ROLLS[asset]:
        day0 = dt.date.fromisoformat(start)
        steps = [dt.datetime.combine(d, dt.time(17, 30), ET) for d in business_days_from(day0, 5)]
        if now < steps[-1]:
            return RollState(front, nxt, steps[0], steps)
    raise ValueError(f"roll schedule for {asset} exhausted; extend ROLLS")


def externally_priced(now: dt.datetime) -> bool:
    """True when oracles follow live CME/spot prices (Sun 18:00 - Fri 17:00 ET,
    minus the 17:00-18:00 daily break). Off-hours, perps price from their own books."""
    now = now.astimezone(ET)
    wd, t = now.weekday(), now.time()
    if wd == 5:  # Saturday
        return False
    if wd == 6:  # Sunday
        return t >= dt.time(18, 0)
    if wd == 4 and t >= dt.time(17, 0):  # Friday after close
        return False
    return not (dt.time(17, 0) <= t < dt.time(18, 0))


# ---------------------------------------------------------------- signals

def pick(asset: str, venue: str, books: dict[str, dict[str, Quote]]) -> Quote | None:
    for sym in ASSETS[asset][venue]:
        q = books.get(venue, {}).get(sym)
        if q and q.mark:
            return q
    return None


def pair_signal(asset: str, rich: Quote, cheap: Quote) -> dict:
    """Edge of short `rich` / long `cheap`, in bps of mid.

    Entry is priced on executable quotes (sell rich's bid, buy cheap's ask) when
    both venues give them, else on marks. Exit assumes the two converge, costing
    half of each venue's spread plus taker fees on all four fills."""
    mid = (rich.mark + cheap.mark) / 2
    executable = None not in (rich.bid, rich.ask, cheap.bid, cheap.ask)
    if executable:
        entry = rich.bid - cheap.ask
        exit_cost = (rich.ask - rich.bid) / 2 + (cheap.ask - cheap.bid) / 2
    else:
        entry, exit_cost = rich.mark - cheap.mark, 0.0
    fees_bps = 2 * (FEES[rich.venue][asset] + FEES[cheap.venue][asset]) * 1e4
    return {
        "pair": f"short {rich.venue.upper()} / long {cheap.venue.upper()}",
        "gap_bps": (rich.mark - cheap.mark) / mid * 1e4,
        "entry_bps": entry / mid * 1e4,
        "exit_cost_bps": exit_cost / mid * 1e4,
        "fees_bps": fees_bps,
        "net_bps": (entry - exit_cost) / mid * 1e4 - fees_bps,
        "priced_on": "quotes" if executable else "marks",
    }


def best_pair(asset: str, quotes: dict[str, Quote]) -> dict | None:
    """Best net edge over every ordered venue pair."""
    best = None
    for a in quotes:
        for b in quotes:
            if a != b:
                sig = pair_signal(asset, quotes[a], quotes[b])
                if best is None or sig["net_bps"] > best["net_bps"]:
                    best = sig
    return best


def roll_signal(state: RollState, now: dt.datetime, front_px: float | None,
                next_px: float | None, hl_funding_1h: float | None) -> dict:
    """Edge of short-HL / long-front-month through the remaining roll."""
    out = {"front": state.front, "next": state.nxt, "next_weight": state.next_weight(now),
           "starts": state.start.strftime("%Y-%m-%d %H:%M ET")}
    if front_px is None or next_px is None:
        return out
    spread = front_px - next_px
    remaining = 1.0 - out["next_weight"]
    hours_left = max((state.steps[-1] - now).total_seconds() / 3600, 0.0)
    # Short pays funding when the rate is negative.
    funding_cost = -(hl_funding_1h or 0.0) * hours_left
    edge = remaining * spread / front_px
    out.update({
        "spread": spread,
        "spread_pct": spread / front_px * 100,
        "edge_pct": edge * 100,
        "hours_left": hours_left,
        "funding_cost_pct": funding_cost * 100,
        "net_pct": (edge - funding_cost) * 100,
        "breakeven_funding_1h_pct": -(edge / hours_left) * 100 if hours_left else None,
    })
    return out


# ---------------------------------------------------------------- output

def fmt(x, spec=".3f", suffix=""):
    return "n/a" if x is None else f"{x:{spec}}{suffix}"


def snapshot(now: dt.datetime | None = None, threshold_bps: float = 5.0) -> list[dict]:
    now = now or dt.datetime.now(ET)
    rows = []
    books: dict[str, dict[str, Quote]] = {}
    for venue, fetch, label in (("hl", fetch_hl, "Hyperliquid"), ("ext", fetch_ext, "Extended"),
                                ("var", fetch_var, "Variational")):
        try:
            books[venue] = fetch()
        except Exception as e:
            print(f"[warn] {label} fetch failed: {e}", file=sys.stderr)
            books[venue] = {}

    live = externally_priced(now)
    print(f"\n=== {now:%Y-%m-%d %H:%M:%S %Z}  |  oracles {'LIVE (external)' if live else 'OFF-HOURS (book-driven)'} ===")
    print(f"{'asset':6} {'HL mark':>10} {'EXT mark':>10} {'VAR mark':>10}  {'best pair':24} "
          f"{'gap':>6} {'net bps':>8}  signal")

    for asset in ASSETS:
        quotes = {v: q for v in VENUES if (q := pick(asset, v, books))}
        row = {"ts": now.isoformat(), "asset": asset, "live": live}
        for v in VENUES:
            q = quotes.get(v)
            row[f"{v}_mark"] = q and q.mark
            row[f"{v}_funding_1h"] = q and q.funding_1h
        best = best_pair(asset, quotes) if len(quotes) >= 2 else None
        sig = ""
        if best:
            row.update(best)
            if best["net_bps"] > threshold_bps:
                sig = f"<< {'converges now' if live else 'converges at reopen'}"
                if best["priced_on"] == "marks":
                    sig += " (marks only, check book)"
        print(f"{asset:6} {fmt(row['hl_mark']):>10} {fmt(row['ext_mark']):>10} {fmt(row['var_mark']):>10}  "
              f"{(best or {}).get('pair', 'n/a'):24} {fmt(row.get('gap_bps'), '.1f'):>6} "
              f"{fmt(row.get('net_bps'), '.1f'):>8}  {sig}")
        rows.append(row)

    print("\nfunding per hour:", "  ".join(
        f"{r['asset']} " + "/".join(fmt(r[f'{v}_funding_1h'] and r[f'{v}_funding_1h'] * 100, '.4f', '%') for v in VENUES)
        for r in rows), "(HL/EXT/VAR)")

    print("\n--- roll capture: short HL perp / long front-month (CME or Veranta) ---")
    for asset in ROLLS:
        st = roll_state(asset, now)
        front = fetch_future(YAHOO_ROOT[asset], st.front)
        nxt = fetch_future(YAHOO_ROOT[asset], st.nxt)
        h = pick(asset, "hl", books)
        r = roll_signal(st, now, front, nxt, h and h.funding_1h)
        print(f"{asset:6} {r['front']}->{r['next']} starts {r['starts']}, next-month weight {r['next_weight']:.0%}")
        if "spread" in r:
            print(f"       front {front:.2f} next {nxt:.2f}  spread {r['spread']:+.2f} ({r['spread_pct']:+.2f}%)  "
                  f"remaining edge {r['edge_pct']:+.2f}%  funding cost {r['funding_cost_pct']:+.2f}% "
                  f"over {r['hours_left']:.0f}h  => net {r['net_pct']:+.2f}%")
            if r["breakeven_funding_1h_pct"] is not None:
                print(f"       edge is gone if HL funding reaches {r['breakeven_funding_1h_pct']:+.4f}%/h")
        else:
            print("       futures prices unavailable (Yahoo); pass them in manually or check CME")
        rows.append({"ts": now.isoformat(), "asset": f"{asset}_ROLL", **r})
    return rows


def append_csv(rows: list[dict], path: str) -> None:
    keys = sorted({k for r in rows for k in r})
    new = not os.path.exists(path)
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--loop", type=int, default=0, help="poll every N seconds (0 = run once)")
    p.add_argument("--csv", default="monitor_log.csv", help="CSV log path when looping")
    p.add_argument("--threshold", type=float, default=5.0, help="net bps needed to flag a gap")
    a = p.parse_args()
    while True:
        rows = snapshot(threshold_bps=a.threshold)
        if a.loop <= 0:
            break
        append_csv(rows, a.csv)
        time.sleep(a.loop)


if __name__ == "__main__":
    main()
