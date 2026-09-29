"""Idea 1b: same-schedule pair through the roll window.

trade[XYZ] and Extended roll oil on the same 5 steps, so a short on one and a
long on the other cancels both the oil price move and the roll drift. What is
left is the difference in how each venue charges for the roll:
  - funding: trade[XYZ] scales funding by 0.5, Extended does not;
  - the perp's discount to the index at entry/exit on each venue.

PnL (short trade[XYZ] / long Extended), per unit notional:
    -(HL exit/entry - 1) + (EXT exit/entry - 1)
    + sum HL funding (short receives +f) - sum EXT funding (long pays +f)
    - taker fees on 4 fills
Both legs use hourly last-trade prices, so this also carries bid/ask noise.
"""

from __future__ import annotations

import statistics as st

from common import HOUR_MS, candles, et_ms, fmt_pct, funding, price_at
from roll import ROLLS

FEES = 2 * (0.00009 + 0.0001)
PAIRS = {"WTI": ("HL_CL", "WTI"), "BRENT": ("HL_BRENTOIL", "XBR")}


def run(lead_h: int = 1, exit_hour: int = 20, reverse: bool = False) -> list[dict]:
    rows = []
    for name, (hl_name, ext_name) in PAIRS.items():
        hl, ext = candles(hl_name, "trades"), candles(ext_name, "trades")
        fh, fe = funding(hl_name), funding(ext_name)
        for label, days in ROLLS.items():
            (y0, m0, d0), (y1, m1, d1) = days[0], days[-1]
            t0 = et_ms(y0, m0, d0, 17) - lead_h * HOUR_MS
            t1 = et_ms(y1, m1, d1, exit_hour)
            px = [price_at(s, t) for s in (hl, ext) for t in (t0, t1)]
            if None in px:
                continue
            h0, h1, e0, e1 = px
            hours = range(t0 // HOUR_MS * HOUR_MS + HOUR_MS, t1, HOUR_MS)
            f_hl, f_ext = sum(fh.get(h, 0.0) for h in hours), sum(fe.get(h, 0.0) for h in hours)
            price = -(h1 / h0 - 1) + (e1 / e0 - 1)
            fund = f_hl - f_ext
            sign = -1 if reverse else 1
            rows.append({"mkt": name, "roll": label, "price": sign * price, "f_hl": f_hl, "f_ext": f_ext,
                         "funding": sign * fund, "net": sign * (price + fund) - FEES})
    return rows


if __name__ == "__main__":
    for lead in (1, 24):
        rows = run(lead)
        print(f"\n=== short trade[XYZ] / long Extended through the roll, entry {lead}h before first step ===")
        print(f"{'mkt':6} {'roll':7} {'price legs':>10} {'HL fund':>8} {'EXT fund':>9} {'fund net':>9} {'fees':>6} {'net':>7}")
        for r in rows:
            print(f"{r['mkt']:6} {r['roll']:7} {fmt_pct(r['price']):>10} {fmt_pct(r['f_hl']):>8} "
                  f"{fmt_pct(r['f_ext']):>9} {fmt_pct(r['funding']):>9} {fmt_pct(-FEES):>6} {fmt_pct(r['net']):>7}")
        n = [r["net"] for r in rows]
        print(f"avg {fmt_pct(st.mean(n))}  sd {st.stdev(n) * 100:.2f}%  positive {sum(x > 0 for x in n)}/{len(n)}  "
              f"t={st.mean(n) / (st.stdev(n) / len(n) ** 0.5):.2f}")
