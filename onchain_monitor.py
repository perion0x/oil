"""Monitor for on-chain commodity perp opportunities (oil + gold).

Tracks two trade setups:

1. Cross-venue convergence (Hyperliquid xyz vs Extended).
   Both venues reference the same underlying (and, for oil, the same futures
   contract with the same 5-day roll). When they diverge, the gap should close
   once both oracles are back on external pricing. Off-hours (weekends), each
   venue prices from its own order book, so gaps can open wide and then snap
   shut at the Sunday reopen.

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
import sys
import time
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import requests

ET = ZoneInfo("America/New_York")
HL_URL = "https://api.hyperliquid.xyz/info"
EXT_URL = "https://api.starknet.extended.exchange/api/v1/info/markets"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
UA = {"User-Agent": "Mozilla/5.0 (onchain-monitor)"}

# Taker fees (fraction of notional), base tier, as documented Sep 2026.
# HL xyz gold is excluded from growth mode, so it pays the full HIP-3 rate.
FEES = {
    "hl": {"WTI": 0.00009, "BRENT": 0.00009, "GOLD": 0.0009},
    "ext": {"WTI": 0.0001, "BRENT": 0.0001, "GOLD": 0.0001},
}

# asset -> (hyperliquid coin, extended market)
ASSETS = {
    "WTI": ("xyz:WTIOIL", "WTI-USD"),
    "BRENT": ("xyz:BRENTOIL", "XBR-USD"),
    "GOLD": ("xyz:GOLD", "XAU-USD"),
}

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

def convergence_signal(asset: str, hl: Quote, ext: Quote) -> dict:
    """Gap between HL and Extended marks, net of taker fees on both legs, in and out."""
    mid = (hl.mark + ext.mark) / 2
    gap_bps = (hl.mark - ext.mark) / mid * 1e4
    fees_bps = 2 * (FEES["hl"][asset] + FEES["ext"][asset]) * 1e4
    return {
        "gap_bps": gap_bps,
        "fees_bps": fees_bps,
        "net_bps": abs(gap_bps) - fees_bps,
        "action": "short HL / long EXT" if gap_bps > 0 else "long HL / short EXT",
    }


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
    try:
        hl = fetch_hl()
    except Exception as e:
        print(f"[warn] Hyperliquid fetch failed: {e}", file=sys.stderr)
        hl = {}
    try:
        ext = fetch_ext()
    except Exception as e:
        print(f"[warn] Extended fetch failed: {e}", file=sys.stderr)
        ext = {}

    live = externally_priced(now)
    print(f"\n=== {now:%Y-%m-%d %H:%M:%S %Z}  |  oracles {'LIVE (external)' if live else 'OFF-HOURS (book-driven)'} ===")
    print(f"{'asset':6} {'HL mark':>10} {'HL fund/h':>10} {'EXT mark':>10} {'EXT fund/h':>11} "
          f"{'gap bps':>8} {'net bps':>8}  signal")

    for asset, (hl_coin, ext_mkt) in ASSETS.items():
        h, e = hl.get(hl_coin), ext.get(ext_mkt)
        row = {"ts": now.isoformat(), "asset": asset, "live": live,
               "hl_mark": h and h.mark, "hl_funding_1h": h and h.funding_1h,
               "ext_mark": e and e.mark, "ext_funding_1h": e and e.funding_1h}
        sig = ""
        if h and e and h.mark and e.mark:
            c = convergence_signal(asset, h, e)
            row.update(c)
            if c["net_bps"] > threshold_bps:
                sig = f"<< {c['action']}  ({'converges now' if live else 'converges at reopen'})"
        print(f"{asset:6} {fmt(row['hl_mark']):>10} {fmt(row['hl_funding_1h'] and row['hl_funding_1h'] * 100, '.4f', '%'):>10} "
              f"{fmt(row['ext_mark']):>10} {fmt(row['ext_funding_1h'] and row['ext_funding_1h'] * 100, '.4f', '%'):>11} "
              f"{fmt(row.get('gap_bps'), '.1f'):>8} {fmt(row.get('net_bps'), '.1f'):>8}  {sig}")
        rows.append(row)

    print("\n--- roll capture: short HL perp / long front-month (CME or Veranta) ---")
    for asset in ROLLS:
        st = roll_state(asset, now)
        front = fetch_future(YAHOO_ROOT[asset], st.front)
        nxt = fetch_future(YAHOO_ROOT[asset], st.nxt)
        h = hl.get(ASSETS[asset][0])
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
