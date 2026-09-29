"""Scan oil and shipping prediction markets (Polymarket, Kalshi) for arbitrage.

Checks, each on executable prices (best bid/ask, or walked order books):

1. Full set: in a Polymarket negRisk event exactly one outcome pays $1, so if
   the asks of all outcomes sum to less than $1, buying one of each locks in
   the difference.
2. Ladders: nested markets must be ordered. "X by Oct 31" contains "X by
   Sep 30"; "WTI hits up $110" contains "hits up $120"; "hits down $80" contains
   "hits down $70". If the smaller event's bid is above the larger one's ask,
   buy the larger YES and the smaller NO: the pair pays at least $1.
3. Cross-venue (Hormuz): Kalshi's "7-day average transit calls ABOVE 60 before
   D" implies Polymarket's "AT OR ABOVE 60 by D-1". Buying Polymarket YES and
   Kalshi NO is an arbitrage when Kalshi's bid > Polymarket's ask. The reverse
   trade is only near-arbitrage: it loses if the average peaks at exactly 60.

Usage:
    python scan.py              live (needs gamma-api.polymarket.com,
                                clob.polymarket.com, api.elections.kalshi.com)
    python scan.py --offline    the 2026-09-29 snapshots in this folder
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
KEYWORDS = ("oil", "crude", "wti", "brent", "hormuz", "bab-el-mandeb", "tanker", "shipping", "opec", "red sea")
KALSHI_HORMUZ = "KXHORMUZNORM"
MONTHS = ("January February March April May June July August September October November December").split()


def get(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": "oil-scan/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def kalshi_fee(p: float) -> float:
    """Kalshi taker fee per contract (0.07 * p * (1 - p), before cent rounding)."""
    return 0.07 * p * (1 - p)


def fnum(x) -> float | None:
    return float(x) if x not in (None, "") else None


# ---------------------------------------------------------------- 1. full set

def walk(levels: list[tuple[float, float]], n: float) -> float | None:
    """Cost of buying n contracts up an ask ladder sorted best first."""
    cost, need = 0.0, n
    for p, s in levels:
        q = min(need, s)
        cost, need = cost + q * p, need - q
        if need <= 1e-9:
            return cost
    return None


def full_set(books: dict[str, list[tuple[float, float]]], step: float = 5.0) -> dict | None:
    """Best (size, cost, profit) for buying one of every outcome, walking each book."""
    best, n = None, step
    while True:
        costs = [walk(lv, n) for lv in books.values()]
        if None in costs:
            break
        profit = n - sum(costs)
        if profit <= 0:
            break
        if best is None or profit > best["profit"]:
            best = {"sets": n, "cost": sum(costs), "profit": profit}
        n += step
    return best


def screen_full_sets(events: list[dict]) -> list[dict]:
    """Top-of-book screen: negRisk events whose best asks sum to under $1."""
    out = []
    for e in events:
        ms = [m for m in e["markets"] if not m.get("closed")]
        if not e.get("negRisk") or len(ms) < 2:
            continue
        asks = [fnum(m.get("bestAsk")) for m in ms]
        if None in asks:
            continue
        if sum(asks) < 1:
            out.append({"slug": e["slug"], "sum_ask": sum(asks), "end": e.get("endDate"),
                        "outcomes": {m["groupItemTitle"]: json.loads(m["clobTokenIds"])[0] for m in ms}})
    return out


def clob_asks(token_id: str) -> list[tuple[float, float]]:
    book = get(f"https://clob.polymarket.com/book?token_id={token_id}")
    return sorted((float(a["price"]), float(a["size"])) for a in book["asks"])


# ------------------------------------------------------------------ 2. ladders

def _date_key(title: str) -> dt.date | None:
    m = re.match(r"(%s) (\d{1,2})" % "|".join(MONTHS), title or "")
    return dt.date(2026, MONTHS.index(m.group(1)) + 1, int(m.group(2))) if m else None


def date_ladder(e: dict) -> list[tuple[str, float, float]] | None:
    """'X by <date>' markets as (label, bid, ask), earliest (smallest event) first."""
    ms = [m for m in e["markets"] if not m.get("closed") and m.get("groupItemTitle")]
    # Only "by <date>" events are nested; "on <date>" markets are not.
    if (e.get("negRisk") or len(ms) < 2 or not re.search(r"\bby\b", e.get("title") or "")
            or not all(_date_key(m["groupItemTitle"]) for m in ms)):
        return None
    return [(m["groupItemTitle"], fnum(m.get("bestBid")) or 0.0, fnum(m.get("bestAsk")) or 1.0)
            for m in sorted(ms, key=lambda m: m.get("endDate") or "")]


def hit_ladders(e: dict) -> list[list[tuple[str, float, float]]]:
    """'WTI hits up/down $K' markets, each side ordered smallest event first."""
    ms = [m for m in e["markets"] if not m.get("closed") and (m.get("groupItemTitle") or " ")[0] in "↑↓"]
    row = lambda m: (m["groupItemTitle"], fnum(m.get("bestBid")) or 0.0, fnum(m.get("bestAsk")) or 1.0)
    strike = lambda m: float(m["groupItemTitle"].split("$")[1].replace(",", ""))
    up = sorted((m for m in ms if m["groupItemTitle"][0] == "↑"), key=strike, reverse=True)  # $150 smallest
    down = sorted((m for m in ms if m["groupItemTitle"][0] == "↓"), key=strike)  # $20 smallest
    return [[row(m) for m in side] for side in (up, down) if len(side) > 1]


def ladder_violations(rows: list[tuple[str, float, float]]) -> list[dict]:
    """Smaller event i, larger event j > i: arb if bid_i > ask_j."""
    out = []
    for i, (li, bi, _) in enumerate(rows):
        for lj, _, aj in rows[i + 1:]:
            if bi > aj:
                out.append({"buy_yes": lj, "buy_no": li, "cost": aj + (1 - bi), "edge": bi - aj})
    return out


# ------------------------------------------------------------- 3. cross-venue

def hormuz_poly_cumulative(events: list[dict]) -> dict[dt.date, tuple[float, float, str]]:
    """Polymarket P(normal by date) as (bid, ask, source), from the 'by <date>'
    markets and from cumulative sums of the month-by-month negRisk event."""
    out: dict[dt.date, tuple[float, float, str]] = {}
    for e in events:
        slug = e["slug"]
        if slug.startswith("strait-of-hormuz-traffic-returns-to-normal-by-"):
            m = [x for x in e["markets"] if not x.get("closed")]
            d = re.search(r"by-([a-z]+)-(\d+)", slug)
            if m and d:
                date = dt.date(2026, MONTHS.index(d.group(1).capitalize()) + 1, int(d.group(2)))
                out[date] = (fnum(m[0].get("bestBid")) or 0.0, fnum(m[0].get("bestAsk")) or 1.0, "by-date market")
        if slug.startswith("which-month-will-strait-of-hormuz"):
            months = {x["groupItemTitle"]: x for x in e["markets"] if not x.get("closed")}
            bid = ask = 0.0
            for i, name in enumerate(MONTHS[7:], start=8):  # August onwards
                if name not in months:
                    continue
                bid += fnum(months[name].get("bestBid")) or 0.0
                ask += fnum(months[name].get("bestAsk")) or 1.0
                last = (dt.date(2026, i + 1, 1) if i < 12 else dt.date(2027, 1, 1)) - dt.timedelta(days=1)
                out.setdefault(last, (bid, ask, "sum of month buckets"))
    return out


def cross_hormuz(poly: dict[dt.date, tuple[float, float, str]], kalshi: list[dict]) -> list[dict]:
    out = []
    for k in kalshi:
        date = dt.date.fromisoformat(k["before"]) - dt.timedelta(days=1)
        if date not in poly:
            continue
        pb, pa, src = poly[date]
        kb, ka = k["yes_bid"], k["yes_ask"]
        # Strict: Kalshi YES implies Polymarket YES. Buy Poly YES, buy Kalshi NO.
        strict = kb - pa - kalshi_fee(kb)
        # Near: buy Kalshi YES, buy Poly NO. Loses only if the average peaks at exactly 60.
        near = pb - ka - kalshi_fee(ka)
        out.append({"date": date, "kalshi": (kb, ka), "poly": (pb, pa), "src": src,
                    "strict_edge": strict, "near_edge": near, "kalshi_ask_size": k.get("yes_ask_size")})
    return out


# ------------------------------------------------------------------- loading

def load_live() -> tuple[list[dict], list[dict]]:
    seen, events = set(), []
    for kw in KEYWORDS:
        q = urllib.parse.urlencode({"q": kw, "limit_per_type": 50, "events_status": "active"})
        for e in get(f"https://gamma-api.polymarket.com/public-search?{q}").get("events", []):
            if e["id"] not in seen and not e.get("closed"):
                seen.add(e["id"])
                events.append(e)
    ks = get(f"https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker={KALSHI_HORMUZ}&status=open&limit=200")
    kalshi = [{"ticker": m["ticker"], "before": re.search(r"before (\w+ \d+, \d{4})", m["title"]) and
               dt.datetime.strptime(re.search(r"before (\w+ \d+, \d{4})", m["title"]).group(1), "%B %d, %Y").date().isoformat(),
               "yes_bid": float(m["yes_bid_dollars"]), "yes_ask": float(m["yes_ask_dollars"]),
               "yes_ask_size": float(m.get("yes_ask_size_fp") or 0)} for m in ks["markets"]]
    return events, [k for k in kalshi if k["before"]]


def load_offline() -> tuple[list[dict], list[dict]]:
    events = json.load(open(os.path.join(HERE, "polymarket_oil_20260929.json")))["events"]
    kalshi = json.load(open(os.path.join(HERE, "kalshi_hormuz_20260929.json")))["markets"]
    return events, kalshi


def main(offline: bool) -> None:
    events, kalshi = load_offline() if offline else load_live()
    print(f"{len(events)} Polymarket events, {len(kalshi)} Kalshi Hormuz markets\n")

    print("1. Full sets (negRisk, sum of best asks < $1)")
    for c in screen_full_sets(events):
        print(f"   {c['slug'][:70]}: sum of asks {c['sum_ask']:.3f} (resolves by {str(c['end'])[:10]})")
        if offline:
            books = json.load(open(os.path.join(HERE, "hormuz_book_20260929.json")))
            books.pop("_note")
        else:
            books = {name: clob_asks(tok) for name, tok in c["outcomes"].items()}
        best = full_set(books)
        if best:
            print(f"      depth: best at {best['sets']:.0f} sets, cost ${best['cost']:,.2f}, "
                  f"profit ${best['profit']:,.2f} ({best['profit'] / best['cost'] * 100:.2f}%)")

    print("\n2. Ladder violations (smaller event bid > larger event ask)")
    found = False
    for e in events:
        for rows in [date_ladder(e)] + hit_ladders(e):
            for v in ladder_violations(rows or []):
                found = True
                print(f"   {e['slug'][:50]}: buy YES {v['buy_yes']} + NO {v['buy_no']} for {v['cost']:.3f}, edge {v['edge']:.3f}")
    if not found:
        print("   none")

    print("\n3. Hormuz, Kalshi vs Polymarket (edges after Kalshi fee; Polymarket fee 0 on these)")
    for r in cross_hormuz(hormuz_poly_cumulative(events), kalshi):
        print(f"   by {r['date']}: Kalshi {r['kalshi'][0]:.3f}/{r['kalshi'][1]:.3f}  Polymarket {r['poly'][0]:.3f}/{r['poly'][1]:.3f} "
              f"({r['src']})  strict {r['strict_edge']:+.3f}  near (exact-60 risk) {r['near_edge']:+.3f}")


if __name__ == "__main__":
    main("--offline" in sys.argv)
