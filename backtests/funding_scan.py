"""Scan every commodity x venue pair for a persistent funding differential.

For each commodity and each ordered venue pair (short A, long B), the pair
earns f_A - f_B per hour (a short receives +f, a long pays +f). Both legs
track the same underlying, so price moves cancel up to the cross-venue basis.
Weekly sums of the differential are reported with a t-stat; a pair worth
trading needs a large, steady differential, not one lucky week.

Venues (hourly funding files in ../data):
  HL  trade[XYZ] on Hyperliquid   ext_HL_<coin>_funding.json
  EXT Extended                    ext_<market>_funding*.json
  LT  Lighter                     ext_LT_<symbol>_funding.json
  AS  Aster (4h funding spread evenly over its 4 hours)  ext_AS_<symbol>_funding.json
"""

from __future__ import annotations

import collections
import itertools
import statistics as st

import sys

from common import et, et_ms, funding
from funding_pair import hold

VENUE_NAMES = {
    "BRENT":  {"HL": "HL_BRENTOIL", "EXT": "XBR", "LT": "LT_BRENT", "AS": "AS_BRENT"},
    "WTI":    {"HL": "HL_CL", "EXT": "WTI", "LT": "LT_WTI", "AS": "AS_WTI"},
    "GOLD":   {"HL": "HL_GOLD", "EXT": "XAU", "LT": "LT_XAU", "AS": "AS_XAU"},
    "SILVER": {"HL": "HL_SILVER", "EXT": "XAG", "LT": "LT_XAG", "AS": "AS_XAG"},
    "NATGAS": {"HL": "HL_NATGAS", "EXT": "XNG", "LT": "LT_NATGAS", "AS": "AS_NATGAS"},
    "COPPER": {"HL": "HL_COPPER", "EXT": "XCU", "LT": "LT_XCU", "AS": "AS_XCU"},
}
MIN_WEEKS = 3
# Taker fee per fill. Lighter standard accounts pay no fees; Aster Pro taker 0.035%.
FEE = {"HL": 0.00009, "EXT": 0.0001, "LT": 0.0, "AS": 0.00035}
# Price series used for the hold check: (file name, kind). Mark prices for the
# thin books (Extended Brent, Aster), last trades elsewhere.
PRICES = {
    "BRENT": {"HL": ("HL_BRENTOIL", "trades"), "EXT": ("XBR", "mark"), "LT": ("LT_BRENT", "trades"),
              "AS": ("AS_BRENT", "mark")},
    "WTI": {"HL": ("HL_CL", "trades"), "EXT": ("WTI", "mark"), "LT": ("LT_WTI", "trades")},
}
HOLD_PAIRS = [("BRENT", "LT", "EXT"), ("BRENT", "LT", "AS"), ("BRENT", "HL", "EXT"), ("BRENT", "HL", "AS"),
              ("BRENT", "LT", "HL"), ("WTI", "LT", "EXT"), ("WTI", "LT", "HL")]


def load(commodity: str) -> dict[str, dict[int, float]]:
    out = {}
    for venue, name in VENUE_NAMES[commodity].items():
        f = funding(name)
        if f:
            out[venue] = f
    return out


def pair_stats(fa: dict[int, float], fb: dict[int, float]) -> dict | None:
    hours = sorted(set(fa) & set(fb))
    if not hours:
        return None
    wk: dict[str, float] = collections.defaultdict(float)
    for h in hours:
        wk[et(h).strftime("%G-W%V")] += fa[h] - fb[h]
    weeks = [wk[k] for k in sorted(wk)][1:-1]  # drop partial weeks
    if len(weeks) < MIN_WEEKS:
        return None
    m, s = st.mean(weeks), st.stdev(weeks)
    return {"weeks": len(weeks), "pos": sum(w > 0 for w in weeks), "mean_wk": m, "sd_wk": s,
            "t": m / (s / len(weeks) ** 0.5) if s else 0.0, "annual": m * 52,
            "from": et(hours[0]), "to": et(hours[-1])}


def scan() -> list[dict]:
    rows = []
    for commodity in VENUE_NAMES:
        data = load(commodity)
        for a, b in itertools.permutations(data, 2):
            s = pair_stats(data[a], data[b])
            if s and s["mean_wk"] > 0:
                rows.append({"commodity": commodity, "short": a, "long": b, **s})
    return sorted(rows, key=lambda r: -r["t"])


def hold_pair(commodity: str, short: str, long: str, start: int | None = None) -> dict:
    (sn, sk), (ln, lk) = PRICES[commodity][short], PRICES[commodity][long]
    return hold(sn, ln, ext_kind=lk, hl_kind=sk, fees=2 * (FEE[short] + FEE[long]),
                start=start or et_ms(2026, 6, 29, 12))


def report_holds(capital: float = 1000.0, lev: float = 3.0) -> None:
    """Continuous hold from 29 Jun (Lighter data starts 27 Jun) to the end of the data."""
    print(f"\nhold short/long from 29 Jun; ${capital:,.0f} split across both venues, {lev:.0f}x per leg")
    for c, a, b in HOLD_PAIRS:
        r = hold_pair(c, a, b)
        usd = capital + r["net"] * capital / 2 * lev
        print(f"{c:5} short {a:3} long {b:3} {r['days']:4.0f}d: price legs {r['price'] * 100:+.2f}%  "
              f"funding {r['funding'] * 100:+.2f}%  net {r['net'] * 100:+.2f}% ({r['net'] / r['days'] * 365 * 100:+.1f}%/yr)  "
              f"worst interim {r['worst'] * 100:+.2f}%  -> ${usd:,.2f}")


if __name__ == "__main__":
    if "--hold" in sys.argv:
        report_holds()
        sys.exit()
    rows = scan()
    print(f"{'commodity':9} {'short':5} {'long':5} {'period':15} {'weeks':>5} {'pos':>5} "
          f"{'mean/wk':>8} {'sd/wk':>7} {'t':>5} {'~annual':>8}")
    for r in rows:
        print(f"{r['commodity']:9} {r['short']:5} {r['long']:5} {r['from']:%d %b}-{r['to']:%d %b}  "
              f"{r['weeks']:5d} {r['pos']:3d}/{r['weeks']:<2d} {r['mean_wk'] * 100:+7.3f}% "
              f"{r['sd_wk'] * 100:6.3f}% {r['t']:5.1f} {r['annual'] * 100:+7.1f}%")
