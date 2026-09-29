"""Idea 2 backtest: weekend convergence between venues.

Two-venue version (needs a second venue's hourly prices, e.g. Hyperliquid via
refresh_data.py --hl): during the off-hours window (Fri 17:00 -> Sun 18:00 ET)
open short-rich / long-cheap the first hour the gap exceeds a threshold, close
one hour after the Sunday reopen when both venues snap back to the same
external price. PnL = gap at entry - gap at exit - fees.

Single-venue diagnostic (what the bundled data supports): how far one venue's
weekend trade price sits from where the market actually reopens. A
cross-venue gap is the difference of two such errors, so this bounds how big
the opportunity can get, but it is not itself a tradeable PnL.
"""

from __future__ import annotations

import datetime as dt
import statistics as st

from common import HOUR_MS, candles, et, et_ms, price_at

FEE_ROUND_TRIP = 2 * (0.0001 + 0.00009)  # Extended + trade[XYZ] oil taker, in and out


def weekends(series: dict[int, float]) -> list[dt.date]:
    """Fridays that have data on both sides of the weekend."""
    fridays = sorted({et(t).date() for t in series if et(t).weekday() == 4})
    out = []
    for f in fridays:
        sun = f + dt.timedelta(days=2)
        if price_at(series, et_ms(f.year, f.month, f.day, 16)) and \
           price_at(series, et_ms(sun.year, sun.month, sun.day, 20)):
            out.append(f)
    return out


def diagnostic(market: str) -> list[dict]:
    trades, index = candles(market, "trades"), candles(market, "index")
    rows = []
    for fri in weekends(index):
        sat, sun = fri + dt.timedelta(days=1), fri + dt.timedelta(days=2)
        close = price_at(index, et_ms(fri.year, fri.month, fri.day, 17))
        reopen = price_at(index, et_ms(sun.year, sun.month, sun.day, 20))  # 1-2h after reopen
        sat_px = price_at(trades, et_ms(sat.year, sat.month, sat.day, 12))
        sun_px = price_at(trades, et_ms(sun.year, sun.month, sun.day, 17))
        if None in (close, reopen, sat_px, sun_px):
            continue
        rows.append({
            "friday": fri, "gap": reopen / close - 1,
            "err_sat": sat_px / reopen - 1, "err_sun": sun_px / reopen - 1,
            # share of the weekend gap the venue had already priced by Sunday 17:00
            "priced": (sun_px / close - 1) / (reopen / close - 1) if abs(reopen / close - 1) > 0.002 else None,
        })
    return rows


def pair_backtest(a: dict[int, float], b: dict[int, float], threshold: float) -> list[dict]:
    """Two venues' hourly prices on the same underlying -> per-weekend trade PnL."""
    trades = []
    for fri in weekends(a):
        sun = fri + dt.timedelta(days=2)
        start = et_ms(fri.year, fri.month, fri.day, 17)
        reopen = et_ms(sun.year, sun.month, sun.day, 18)
        for t in range(start, reopen, HOUR_MS):
            pa, pb = price_at(a, t), price_at(b, t)
            if not (pa and pb) or abs(pa / pb - 1) < threshold:
                continue
            xa, xb = price_at(a, reopen + HOUR_MS), price_at(b, reopen + HOUR_MS)
            gap_in, gap_out = pa / pb - 1, xa / xb - 1
            sign = 1 if gap_in > 0 else -1  # short the rich venue
            trades.append({"friday": fri, "entry": et(t), "gap_in": gap_in, "gap_out": gap_out,
                           "pnl": sign * (gap_in - gap_out) - FEE_ROUND_TRIP})
            break
    return trades


def report_diagnostic(market: str) -> None:
    rows = diagnostic(market)
    if not rows:
        return
    ab = lambda k: [abs(r[k]) for r in rows]
    priced = [r["priced"] for r in rows if r["priced"] is not None]
    print(f"{market}: {len(rows)} weekends | Fri->reopen move: median {st.median(ab('gap')) * 100:.2f}%, "
          f"max {max(ab('gap')) * 100:.2f}%")
    print(f"      venue weekend price vs reopen: Sat noon median {st.median(ab('err_sat')) * 100:.2f}% "
          f"(max {max(ab('err_sat')) * 100:.2f}%), Sun 17:00 median {st.median(ab('err_sun')) * 100:.2f}% "
          f"(max {max(ab('err_sun')) * 100:.2f}%)")
    if priced:
        print(f"      share of the reopen gap already priced by Sun 17:00 (weekends with >0.2% gap): "
              f"median {st.median(priced) * 100:.0f}%")


if __name__ == "__main__":
    print("Single-venue diagnostic on Extended (Fri 17:00 ET close -> Sun reopen):")
    for m in ("WTI", "XBR", "XAU"):
        report_diagnostic(m)
    try:
        hl = candles("HL_WTIOIL", "trades")
    except FileNotFoundError:
        print("\nNo Hyperliquid data in ../data; run refresh_data.py --hl locally for the two-venue backtest.")
    else:
        for thr in (0.001, 0.002, 0.005):
            t = pair_backtest(hl, candles("WTI", "trades"), thr)
            if t:
                print(f"\nHL vs EXT WTI, gap > {thr * 100:.1f}%: {len(t)} trades, "
                      f"avg {st.mean(x['pnl'] for x in t) * 100:+.2f}%, "
                      f"win {sum(x['pnl'] > 0 for x in t)}/{len(t)}")
