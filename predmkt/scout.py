"""Scout Polymarket and Kalshi for logical arbitrage across all categories.

Two kinds of mispricing in a group of outcomes where at most one can win:

  buy-all-YES  sum of YES asks < $1. Needs the outcomes to be EXHAUSTIVE
               (one of them must win); candidate lists like "Who will be the
               next Pope?" are not, so these are flagged for a manual check.
  buy-all-NO   n outcomes, at most one wins, so n NO contracts pay at least
               n-1. Cost is sum(1 - YES bid). Profit whenever the YES bids
               sum to more than $1, whether or not the list is exhaustive.

Plus nested ladders (Kalshi "above $X" strikes, "before <date>" series,
Polymarket "by <date>" events): a smaller event's bid above a larger event's
ask is an arbitrage (buy the larger YES, the smaller NO).

Fees: Kalshi taker 0.07 * p * (1 - p) per contract; Polymarket fees are read
from the market flag and, where enabled, charged at the same rough rate
(conservative). Prices are top of book; confirm depth before trading.

Usage: python scout.py poly.json [poly2.json ...] --kalshi kalshi.json [...]
       (raw API responses: gamma /events lists and Kalshi /events?with_nested_markets=true)
"""

from __future__ import annotations

import json
import re
import sys

FEE_RATE = 0.07
EXHAUSTIVE_HINTS = re.compile(r"\b(other|none|no one|nobody|neither|not held|no winner|tie|or (more|higher|above|below|less|fewer))\b|"
                              r"\b(above|below|over|under|more than|less than|at least|or more)\b", re.I)


def looks_exhaustive(titles: list[str]) -> bool:
    """A catch-all outcome ("Other", "No ...", "$100 or above") suggests the list covers every case."""
    return any(EXHAUSTIVE_HINTS.search(t) or re.match(r"(no|not|none)\b", t.strip(), re.I) for t in titles)


def fee(p: float) -> float:
    return FEE_RATE * p * (1 - p)


def f(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def group_edges(asks: list[float], bids: list[float], fee_on: bool = True) -> dict:
    """Per-set edge for buy-all-YES and buy-all-NO, after fees."""
    n = len(asks)
    yes_cost = sum(asks) + (sum(fee(a) for a in asks) if fee_on else 0)
    no_cost = sum(1 - b for b in bids) + (sum(fee(1 - b) for b in bids) if fee_on else 0)
    return {"buy_yes": 1 - yes_cost, "buy_no": (n - 1) - no_cost,
            "sum_ask": sum(asks), "sum_bid": sum(bids), "n": n}


def ladder_violations(rows: list[tuple[str, float, float]], fee_on: bool = True) -> list[dict]:
    """rows ordered smallest event first: (label, bid, ask). Arb if bid_i > ask_j, j > i."""
    out = []
    for i, (li, bi, _) in enumerate(rows):
        for lj, _, aj in rows[i + 1:]:
            edge = bi - aj - ((fee(aj) + fee(1 - bi)) if fee_on else 0)
            if edge > 0:
                out.append({"buy_yes": lj, "buy_no": li, "edge": edge})
    return out


# ------------------------------------------------------------------ Polymarket

def poly_groups(events: list[dict]) -> list[dict]:
    out = []
    for e in events:
        ms = [m for m in e.get("markets", []) if m.get("active", True) and not m.get("closed")]
        if not e.get("negRisk") or len(ms) < 2:
            continue
        asks = [f(m.get("bestAsk")) for m in ms]
        bids = [f(m.get("bestBid")) or 0.0 for m in ms]
        if None in asks:
            continue
        fee_on = any(m.get("feesEnabled") for m in ms)
        g = group_edges(asks, bids, fee_on)
        titles = [m.get("groupItemTitle") or "" for m in ms]
        g.update(venue="Polymarket", id=e.get("slug"), title=e.get("title"), end=str(e.get("endDate"))[:10],
                 exhaustive_hint=looks_exhaustive(titles) and not e.get("negRiskAugmented"),
                 augmented=bool(e.get("negRiskAugmented")),
                 liquidity=sum(f(m.get("liquidityNum")) or 0 for m in ms))
        out.append(g)
    return out


def poly_date_ladders(events: list[dict]) -> list[dict]:
    months = "January February March April May June July August September October November December".split()
    out = []
    for e in events:
        ms = [m for m in e.get("markets", []) if not m.get("closed") and m.get("groupItemTitle")]
        if e.get("negRisk") or len(ms) < 2 or not re.search(r"\bby\b", e.get("title") or ""):
            continue
        if not all(re.match("(%s) \\d{1,2}" % "|".join(months), m["groupItemTitle"]) for m in ms):
            continue
        rows = [(m["groupItemTitle"], f(m.get("bestBid")) or 0.0, f(m.get("bestAsk")) or 1.0)
                for m in sorted(ms, key=lambda m: m.get("endDate") or "")]
        for v in ladder_violations(rows, any(m.get("feesEnabled") for m in ms)):
            out.append({"venue": "Polymarket", "id": e.get("slug"), "title": e.get("title"), **v})
    return out


# ---------------------------------------------------------------------- Kalshi

def kalshi_groups(events: list[dict]) -> list[dict]:
    out = []
    for e in events:
        ms = [m for m in e.get("markets", []) if m.get("status") == "active"]
        if not e.get("mutually_exclusive") or len(ms) < 2:
            continue
        asks = [f(m.get("yes_ask_dollars")) for m in ms]
        bids = [f(m.get("yes_bid_dollars")) or 0.0 for m in ms]
        if None in asks or any(a <= 0 for a in asks):
            continue
        g = group_edges(asks, bids)
        subs = [(m.get("yes_sub_title") or "") + " " + (m.get("strike_type") or "") for m in ms]
        g.update(venue="Kalshi", id=e.get("event_ticker"), title=e.get("title"),
                 end=str(max((m.get("close_time") or "") for m in ms))[:10],
                 exhaustive_hint=looks_exhaustive(subs) or any("between" in x for x in subs), augmented=False,
                 liquidity=None, min_ask_size=min(f(m.get("yes_ask_size_fp")) or 0 for m in ms),
                 min_bid_size=min(f(m.get("yes_bid_size_fp")) or 0 for m in ms))
        out.append(g)
    return out


def kalshi_ladders(events: list[dict]) -> list[dict]:
    """'greater' strikes: higher strike is the smaller event. 'less': lower strike is smaller.
    Date strikes ('before <date>'): earlier date is smaller."""
    out = []
    for e in events:
        ms = [m for m in e.get("markets", []) if m.get("status") == "active"]
        row = lambda m: (m["ticker"], f(m.get("yes_bid_dollars")) or 0.0, f(m.get("yes_ask_dollars")) or 1.0)
        sides = []
        g = [m for m in ms if m.get("strike_type") == "greater" and f(m.get("floor_strike")) is not None]
        sides.append(sorted(g, key=lambda m: -f(m["floor_strike"])))
        l = [m for m in ms if m.get("strike_type") == "less" and f(m.get("cap_strike")) is not None]
        sides.append(sorted(l, key=lambda m: f(m["cap_strike"])))
        d = [m for m in ms if m.get("strike_type") == "custom" and (m.get("custom_strike") or {}).get("date")]
        sides.append(sorted(d, key=lambda m: m.get("close_time") or ""))
        for side in sides:
            if len(side) > 1:
                for v in ladder_violations([row(m) for m in side]):
                    out.append({"venue": "Kalshi", "id": e.get("event_ticker"), "title": e.get("title"), **v})
    return out


# ------------------------------------------------------------------------ main

def load(paths: list[str], key: str) -> list[dict]:
    out, seen = [], set()
    for p in paths:
        d = json.load(open(p))
        if isinstance(d, dict) and "rawHtml" in d:  # web-fetch wrapper
            d = json.loads(d["rawHtml"])
        items = d if isinstance(d, list) else d.get(key, [])
        for x in items:
            k = x.get("id") or x.get("event_ticker")
            if k not in seen:
                seen.add(k)
                out.append(x)
    return out


def report(poly: list[dict], kalshi: list[dict], min_edge: float = 0.0) -> None:
    groups = poly_groups(poly) + kalshi_groups(kalshi)
    print(f"{len(poly)} Polymarket events, {len(kalshi)} Kalshi events, {len(groups)} one-winner groups\n")
    print("buy-all-NO (valid if at most one outcome can win):")
    for g in sorted((g for g in groups if g["buy_no"] > min_edge), key=lambda g: -g["buy_no"]):
        print(f"  {g['buy_no']:+.3f}/set  {g['venue']:10} {str(g['id'])[:45]:45} n={g['n']:2} sumBid={g['sum_bid']:.3f}  {str(g['title'])[:60]}")
    print("\nbuy-all-YES (valid only if the list is exhaustive):")
    for g in sorted((g for g in groups if g["buy_yes"] > min_edge), key=lambda g: -g["buy_yes"]):
        tag = "likely exhaustive" if g["exhaustive_hint"] else ("placeholder outcomes" if g["augmented"] else "CHECK: may not be exhaustive")
        print(f"  {g['buy_yes']:+.3f}/set  {g['venue']:10} {str(g['id'])[:45]:45} n={g['n']:2} sumAsk={g['sum_ask']:.3f}  [{tag}]  {str(g['title'])[:50]}")
    print("\nladder violations:")
    for v in poly_date_ladders(poly) + kalshi_ladders(kalshi):
        print(f"  {v['edge']:+.3f}  {v['venue']:10} {str(v['id'])[:40]:40} buy YES {v['buy_yes']} + NO {v['buy_no']}  {str(v['title'])[:40]}")


if __name__ == "__main__":
    args = sys.argv[1:]
    k = args.index("--kalshi") if "--kalshi" in args else len(args)
    report(load(args[:k], "events"), load(args[k + 1:], "events"))
