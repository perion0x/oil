"""Idea 5: hold short trade[XYZ] / long Extended on the same commodity.

Both perps track the same underlying (and for oil the same contract and roll
schedule), so the price legs cancel up to the basis between the venues. What
the pair earns is the funding difference:
  - trade[XYZ] scales funding by 0.5;
  - Extended's Brent book is thin and its perp trades at a persistent discount,
    so its funding runs more negative (longs get paid more).

Reports the continuous hold (price legs, funding, fees), weekly funding
differential stability, and a small-account result.
"""

from __future__ import annotations

import collections
import statistics as st
import sys

from common import HOUR_MS, candles, et, et_ms, funding, price_at

FEES = 2 * (0.00009 + 0.0001)  # taker in and out, both venues
PAIRS = {"BRENT": ("HL_BRENTOIL", "XBR"), "WTI": ("HL_CL", "WTI"), "GOLD": ("HL_GOLD", "XAU")}


def hold(hl_name: str, ext_name: str, ext_kind: str = "trades", hl_kind: str = "trades",
         fees: float = FEES, start: int | None = None) -> dict:
    """Short `hl_name`, long `ext_name` (any two venues' files) held start -> end of data."""
    hl, ext = candles(hl_name, hl_kind), candles(ext_name, ext_kind)
    fh, fe = funding(hl_name), funding(ext_name)
    t0 = max(min(hl) + 2 * HOUR_MS, min(ext) + 2 * HOUR_MS, min(fh) + 2 * HOUR_MS, min(fe) + 2 * HOUR_MS,
             start or et_ms(2026, 6, 5, 12))
    t0 = t0 // HOUR_MS * HOUR_MS
    t1 = (min(max(ext), max(hl), max(fh), max(fe)) // HOUR_MS) * HOUR_MS - HOUR_MS
    h0, e0, h1, e1 = price_at(hl, t0), price_at(ext, t0), price_at(hl, t1), price_at(ext, t1)
    worst = 0.0
    for t in range(t0, t1, HOUR_MS):
        ht, xt = price_at(hl, t), price_at(ext, t)
        if ht and xt:
            worst = min(worst, -(ht / h0 - 1) + (xt / e0 - 1))
    price = -(h1 / h0 - 1) + (e1 / e0 - 1)
    fund = sum(fh.get(h, 0.0) - fe.get(h, 0.0) for h in range(t0 // HOUR_MS * HOUR_MS + HOUR_MS, t1, HOUR_MS))
    days = (t1 - t0) / 86_400_000
    return {"t0": et(t0), "t1": et(t1), "days": days, "price": price, "funding": fund,
            "net": price + fund - fees, "worst": worst}


def weekly(hl_name: str, ext_name: str) -> list[float]:
    fh, fe = funding(hl_name), funding(ext_name)
    wk: dict[str, float] = collections.defaultdict(float)
    for h in set(fh) & set(fe):
        wk[et(h).strftime("%G-W%V")] += fh[h] - fe[h]
    return [wk[k] for k in sorted(wk)][1:-1]  # drop partial first/last weeks


if __name__ == "__main__":
    capital = next((float(a.split("=")[1]) for a in sys.argv if a.startswith("--capital=")), 1000.0)
    lev = 3.0
    for name, (h, e) in PAIRS.items():
        for kind in ("trades", "mark"):
            r = hold(h, e, kind)
            usd = capital + r["net"] * capital / 2 * lev
            print(f"{name:5} (EXT {kind:6}) {r['t0']:%d %b}->{r['t1']:%d %b} {r['days']:.0f}d: "
                  f"price legs {r['price'] * 100:+.2f}%  funding {r['funding'] * 100:+.2f}%  net {r['net'] * 100:+.2f}% "
                  f"({r['net'] / r['days'] * 365 * 100:+.1f}%/yr)  worst interim {r['worst'] * 100:+.2f}%  "
                  f"${capital:,.0f} @{lev:.0f}x/leg -> ${usd:,.2f}")
        w = weekly(h, e)
        t = st.mean(w) / (st.stdev(w) / len(w) ** 0.5)
        print(f"      weekly funding diff: {sum(x > 0 for x in w)}/{len(w)} positive, mean {st.mean(w) * 100:+.3f}%, "
              f"sd {st.stdev(w) * 100:.3f}%, t={t:.1f}")
