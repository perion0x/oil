"""Idea 3 estimate: quote Extended WTI (0% maker) around fair value, hedge on
the deep venue (trade[XYZ], 0.009% taker).

This is a rough fill simulation on 1-minute candles, not a real market-making
backtest (no order book or queue data is public). Each live-hours minute:
  - fair = Extended index close of the previous minute (an oracle of CME);
  - we rest a bid at fair*(1-h) and an ask at fair*(1+h);
  - a side fills if that minute's trade low/high reaches it, for a size equal
    to CAPTURE of the minute's traded volume, capped at CLIP_USD;
  - the fill is hedged one minute later at the then-fair price, paying the
    hedge venue's taker fee.
PnL per fill = quoted edge - adverse move over the next minute - hedge fee.
The volume share we'd really win is unknown, so treat the dollar figures as
an order of magnitude and the per-fill edge (bp) as the main signal.
"""

from __future__ import annotations

import statistics as st

from common import candle_rows, candles, et

HEDGE_FEE = 0.00009
CAPTURE = 0.2
CLIP_USD = 10_000
MIN_MS = 60_000


def live(ts: int) -> bool:
    d = et(ts)
    if d.weekday() == 5 or (d.weekday() == 6 and d.hour < 18) or (d.weekday() == 4 and d.hour >= 17):
        return False
    return d.hour != 17  # daily break


def simulate(h: float, trades: dict, index: dict[int, float]) -> dict:
    fills, pnl, notional = [], 0.0, 0.0
    for t, bar in trades.items():
        fair, nxt = index.get(t - MIN_MS), index.get(t + MIN_MS)
        if not (fair and nxt and bar["v"] > 0 and live(t)):
            continue
        size = min(CAPTURE * bar["v"] * bar["c"], CLIP_USD)
        bid, ask = fair * (1 - h), fair * (1 + h)
        if bar["l"] <= bid:
            edge = nxt / bid - 1 - HEDGE_FEE
            fills.append(edge); pnl += edge * size; notional += size
        if bar["h"] >= ask:
            edge = ask / nxt - 1 - HEDGE_FEE
            fills.append(edge); pnl += edge * size; notional += size
    return {"h": h, "fills": len(fills), "avg_bp": st.mean(fills) * 1e4 if fills else 0.0,
            "win": sum(f > 0 for f in fills), "pnl": pnl, "notional": notional}


if __name__ == "__main__":
    trades = candle_rows("WTI", "trades", "1m")
    index = candles("WTI", "index", "1m")
    days = (max(trades) - min(trades)) / 86_400_000
    print(f"Extended WTI, {len(trades)} minutes ({days:.1f} days, {et(min(trades)):%d %b} - {et(max(trades)):%d %b}), "
          f"capture {CAPTURE:.0%} of volume, clip ${CLIP_USD:,}")
    print(f"{'half-spread':>11} {'fills':>6} {'avg edge':>9} {'win':>9} {'PnL/day':>9} {'volume/day':>11}")
    for h in (0.0002, 0.0005, 0.001, 0.002, 0.003):
        r = simulate(h, trades, index)
        print(f"{h * 1e4:9.0f}bp {r['fills']:6d} {r['avg_bp']:+8.1f}bp "
              f"{r['win']:4d}/{r['fills']:<4d} ${r['pnl'] / days:8,.0f} ${r['notional'] / days:10,.0f}")
