"""Idea 1, direct version: both legs priced from real data (WTI only).

Short leg:  trade[XYZ] xyz:CL hourly trade prices + hourly funding.
Hedge leg:  the front-month WTI contract from Pyth (per-contract history), i.e.
            what Veranta (which prices off Pyth) or CME would hold.
No spread estimate is needed: PnL = -perp return + front-month return
+ funding received - fees - hedge holding cost.

Also simulates a small account: capital split evenly between the two venues,
each leg at `leverage` x its venue's margin, compounding only through rolls
whose front-next spread at entry exceeds MIN_SPREAD (observable beforehand).

Needs data/ext_PYTH_WTI<contract>_trades_1h.json (fetch with refresh_data.py
--pyth, which needs a Pyth Pro key in PYTH_API_KEY).
"""

from __future__ import annotations

import statistics as st
import sys

from common import HOUR_MS, candles, et_ms, fmt_pct, funding, price_at
from roll import HEDGES, MIN_SPREAD, PERP_FEE, ROLLS

# trade[XYZ] WTI roll: (front, next) contract codes per window.
WTI_CONTRACTS = {"Jun-26": ("N6", "Q6"), "Jul-26": ("Q6", "U6"),
                 "Aug-26": ("U6", "V6"), "Sep-26": ("V6", "X6")}


def run(lead_h: int = 1, hedge: str = "veranta") -> list[dict]:
    perp, fund = candles("HL_CL", "trades"), funding("HL_CL")
    hg = HEDGES[hedge]
    rows = []
    for label, days in ROLLS.items():
        f1c, f2c = WTI_CONTRACTS[label]
        try:
            f1, f2 = candles(f"PYTH_WTI{f1c}", "trades"), candles(f"PYTH_WTI{f2c}", "trades")
        except FileNotFoundError:
            continue
        (y0, m0, d0), (y1, m1, d1) = days[0], days[-1]
        t0 = et_ms(y0, m0, d0, 17) - lead_h * HOUR_MS
        t1 = et_ms(y1, m1, d1, hg["exit_hour"])
        p0, p1, a0, a1, b0, b1 = (price_at(perp, t0), price_at(perp, t1), price_at(f1, t0),
                                  price_at(f1, t1), price_at(f2, t0), price_at(f2, t1))
        if None in (p0, p1, a0, a1, b0, b1):
            continue
        hours = range(t0 // HOUR_MS * HOUR_MS + HOUR_MS, t1, HOUR_MS)
        fund_recv = sum(fund.get(h, 0.0) for h in hours)
        perp_ret, hedge_ret = -(p1 / p0 - 1), a1 / a0 - 1
        costs = 2 * PERP_FEE["hl"] + hg["cost"] + hg["hold_h"] * len(hours)
        # Worst mark-to-market of each leg during the hold (for margin/liquidation).
        path = range(t0, t1 + 1, HOUR_MS)
        short_worst = min(-(price_at(perp, t) / p0 - 1) for t in path if price_at(perp, t))
        long_worst = min(price_at(f1, t) / a0 - 1 for t in path if price_at(f1, t))
        rows.append({
            "roll": label, "contracts": f"{f1c}->{f2c}",
            "spread_in": (a0 - b0) / a0, "spread_out": (a1 - b1) / a0,
            "perp": perp_ret, "hedge": hedge_ret, "funding": fund_recv, "costs": costs,
            "net": perp_ret + hedge_ret + fund_recv - costs,
            "short_worst": short_worst, "long_worst": long_worst,
        })
    return rows


def simulate(rows: list[dict], capital: float = 1000.0, leverage: float = 3.0) -> dict:
    """Capital split 50/50 between venues; each leg notional = leverage x its half."""
    equity, log = capital, []
    for r in rows:
        if r["spread_in"] <= MIN_SPREAD:
            log.append((r["roll"], "skip (spread %.1f%%)" % (r["spread_in"] * 100), equity))
            continue
        notional = equity / 2 * leverage
        pnl = notional * r["net"]
        # Each leg's worst drawdown as a share of that leg's margin (equity / 2).
        dd = max(-r["short_worst"], -r["long_worst"]) * leverage
        equity += pnl
        log.append((r["roll"], f"notional ${notional:,.0f}/leg  pnl ${pnl:+,.2f}  "
                               f"worst leg drawdown {dd:.0%} of its margin", equity))
    return {"final": equity, "log": log}


def report(rows: list[dict], hedge: str) -> None:
    print(f"hedge: {HEDGES[hedge]['label']}")
    print(f"{'roll':7} {'contracts':9} {'spread in/out':>15} {'perp':>8} {'hedge':>8} {'funding':>8} "
          f"{'costs':>7} {'net':>7}")
    for r in rows:
        print(f"{r['roll']:7} {r['contracts']:9} {r['spread_in'] * 100:+6.2f}/{r['spread_out'] * 100:+5.2f}% "
              f"{fmt_pct(r['perp']):>8} {fmt_pct(r['hedge']):>8} {fmt_pct(r['funding']):>8} "
              f"{fmt_pct(-r['costs']):>7} {fmt_pct(r['net']):>7}")
    good = [r["net"] for r in rows if r["spread_in"] > MIN_SPREAD]
    if good:
        print(f"rolls with entry spread > {MIN_SPREAD:.0%}: avg {fmt_pct(st.mean(good))}, "
              f"positive {sum(n > 0 for n in good)}/{len(good)}")


if __name__ == "__main__":
    capital = next((float(a.split("=")[1]) for a in sys.argv if a.startswith("--capital=")), 1000.0)
    for hedge in ("veranta", "veranta_api", "cme"):
        rows = run(1, hedge)
        print()
        report(rows, hedge)
        for lev in (2, 3):
            sim = simulate(rows, capital, lev)
            print(f"  ${capital:,.0f} account, {lev}x per leg:")
            for roll, msg, eq in sim["log"]:
                print(f"    {roll}: {msg}  -> equity ${eq:,.2f}")
            print(f"    final ${sim['final']:,.2f} ({(sim['final'] / capital - 1) * 100:+.2f}%)")
