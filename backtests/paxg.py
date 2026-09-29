"""Idea 4 backtest: PAXG perp vs XAU perp on Extended (same venue, 0.01% taker).

PAXG-USD tracks the PAXG token (24/7, crypto venues); XAU-USD tracks spot
gold (external oracle in market hours, order-book pricing on weekends). The
ratio PAXG/XAU therefore carries (a) the token's premium/discount to spot and
(b) weekend staleness of the XAU perp.

A. Mean reversion: trade the ratio back to its rolling mean. Entry when the
   z-score over a trailing window passes a threshold, exit when it crosses
   back through zero or after a max hold. Parameters are chosen on the first
   half of the sample and reported out of sample on the second half.
B. Weekend catch-up: at Sun 17:00 ET, if PAXG has moved more than XAU since
   Friday's close, go long the laggard / short the leader and close 2h after
   the reopen.

Signals use mark prices (fair value). Hourly last-trade closes on a thin
PAXG book bounce between bid and ask, which makes naive mean reversion look
like a money machine; fills are therefore taken one bar after the signal and
charged an assumed half-spread per fill on top of 4 x 0.01% taker fees, plus
the hourly funding of both legs where the data has it.
"""

from __future__ import annotations

import datetime as dt
import statistics as st

from common import HOUR_MS, candles, et, et_ms, funding, price_at

FEE = 4 * 0.0001
HALF_SPREAD = {"XAU": 0.0001, "PAXG": 0.0004}  # assumed; PAXG book is ~$0.5M/day
SLIPPAGE = 2 * (HALF_SPREAD["XAU"] + HALF_SPREAD["PAXG"])  # 4 fills


def aligned(kind: str = "mark"):
    x, p = candles("XAU", kind), candles("PAXG", kind)
    ts = sorted(set(x) & set(p))
    return ts, x, p


def funding_cost(side: int, t0: int, t1: int, fx: dict, fp: dict) -> float:
    """side=+1: long PAXG / short XAU. Longs pay +f, shorts receive +f."""
    c = 0.0
    for h in range(t0 // HOUR_MS * HOUR_MS + HOUR_MS, t1 + 1, HOUR_MS):
        c += side * (-fp.get(h, 0.0) + fx.get(h, 0.0))
    return c


def mean_reversion(ts, x, p, window: int, z_in: float, max_hold: int, fx, fp, start=0, end=None):
    lr = [p[t] / x[t] - 1 for t in ts]
    end = end or len(ts)
    trades, i = [], max(window, start)
    while i < end - 1:
        hist = lr[i - window:i]
        mu, sd = st.mean(hist), st.pstdev(hist)
        if sd == 0:
            i += 1
            continue
        z = (lr[i] - mu) / sd
        if abs(z) < z_in:
            i += 1
            continue
        side = -1 if z > 0 else 1  # PAXG rich -> short PAXG / long XAU
        j = i + 1
        while j < min(end - 2, i + max_hold) and (lr[j] - mu) * (lr[i] - mu) > 0:
            j += 1
        a, b = i + 1, j + 1  # fill one bar after the signal, on entry and exit
        gross = side * (lr[b] - lr[a])
        f = funding_cost(side, ts[a], ts[b], fx, fp)
        trades.append({"t": et(ts[a]), "hold_h": b - a, "gross": gross, "funding": f,
                       "net": gross + f - FEE - SLIPPAGE})
        i = b + 1
    return trades


def summarize(trades) -> str:
    if not trades:
        return "no trades"
    net = [t["net"] for t in trades]
    return (f"{len(trades):3d} trades  avg {st.mean(net) * 1e4:+6.1f}bp  total {sum(net) * 100:+6.2f}%  "
            f"win {sum(n > 0 for n in net)}/{len(net)}  avg hold {st.mean(t['hold_h'] for t in trades):.0f}h")


def weekend_catchup(ts, x, p) -> list[dict]:
    out = []
    fridays = sorted({et(t).date() for t in ts if et(t).weekday() == 4})
    for fri in fridays:
        sun = fri + dt.timedelta(days=2)
        t_fri, t_sig, t_exit = (et_ms(fri.year, fri.month, fri.day, 17),
                                et_ms(sun.year, sun.month, sun.day, 17),
                                et_ms(sun.year, sun.month, sun.day, 20))
        vals = [price_at(s, t) for s in (x, p) for t in (t_fri, t_sig, t_exit)]
        if None in vals:
            continue
        x0, x1, x2, p0, p1, p2 = vals
        signal = (p1 / p0 - 1) - (x1 / x0 - 1)
        if abs(signal) < 0.001:
            continue
        side = 1 if signal > 0 else -1  # PAXG moved up more -> long XAU / short PAXG
        pnl = side * ((x2 / x1 - 1) - (p2 / p1 - 1)) - FEE - SLIPPAGE
        out.append({"friday": fri, "signal": signal, "net": pnl})
    return out


def run(kind: str) -> None:
    ts, x, p = aligned(kind)
    fx, fp = funding("XAU"), funding("PAXG")
    lr = [p[t] / x[t] - 1 for t in ts]
    print(f"PAXG/XAU ({kind} prices, {et(ts[0]):%d %b} - {et(ts[-1]):%d %b}, {len(ts)}h): "
          f"mean {st.mean(lr) * 1e4:+.1f}bp, sd {st.pstdev(lr) * 1e4:.1f}bp, "
          f"range {min(lr) * 1e4:+.0f} to {max(lr) * 1e4:+.0f}bp")

    half = len(ts) // 2
    grid = [(w, z, h) for w in (24, 72, 168) for z in (1.5, 2.0, 2.5) for h in (24, 72)]
    scored = []
    for w, z, h in grid:
        tr = mean_reversion(ts, x, p, w, z, h, fx, fp, end=half)
        if len(tr) >= 5:
            scored.append((sum(t["net"] for t in tr), (w, z, h)))
    scored.sort(reverse=True)
    print("\nA. mean reversion (params picked in-sample on the first half):")
    for _, (w, z, h) in scored[:3]:
        ins = mean_reversion(ts, x, p, w, z, h, fx, fp, end=half)
        oos = mean_reversion(ts, x, p, w, z, h, fx, fp, start=half)
        print(f"   window {w:3d}h z>{z} max hold {h}h")
        print(f"      in-sample     {summarize(ins)}")
        print(f"      out-of-sample {summarize(oos)}")

    print("\nB. weekend catch-up (signal at Sun 17:00 ET, exit Sun 20:00 ET):")
    wk = weekend_catchup(ts, x, p)
    print(f"   {summarize([dict(t, hold_h=3) for t in wk])}")
    for t in wk:
        print(f"      {t['friday']}  PAXG-XAU weekend move {t['signal'] * 100:+.2f}%  net {t['net'] * 100:+.2f}%")


if __name__ == "__main__":
    print(f"costs per round trip: fees {FEE * 1e4:.0f}bp + assumed spread {SLIPPAGE * 1e4:.0f}bp\n")
    run("mark")
    print("\n--- same test on last-trade prices (inflated by bid/ask bounce; for comparison only) ---")
    run("trades")
