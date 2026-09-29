"""Idea 1 backtest: roll capture on an oil perp that blends front -> next month.

Trade: short the perp from just before the first roll step to just after the
last, hedged with a long front-month future (CME, or a PnL-neutral venue).

With the perp tracking index = (1-w) F1 + w F2 and the hedge tracking F1, the
hedged PnL over the window is

    (F1 - F2) at exit  +  funding received by the short
      + (perp premium to index at entry - premium at exit)  -  fees

(the short receives funding when the rate is positive, pays when negative).
The premium term matters: the order book prices each step in ahead of time,
so the perp trades below the index before a step and back at it afterwards.
Entries are tested at several lead times before the first step.

The front-next spread is not in the data (expired contracts are not on free
feeds), so it is estimated from the index itself: each daily step moves the
weight by 20%, so the index jumps by -0.2 x spread at each step. Summing the
five step moves, net of the average move over the same clock window on
non-roll weekdays, gives the spread and a noise band.

Venue here is Extended, which uses the same 5-step, 5th-9th business day
schedule as trade[XYZ]. Re-run with Hyperliquid data (refresh_data.py --hl)
to test trade[XYZ] itself.
"""

from __future__ import annotations

import statistics as st

from common import HOUR_MS, candles, et, et_ms, fmt_pct, funding, price_at

# Roll step dates (weights change around 17:30 ET each day). Verified against
# the published Extended / trade[XYZ] schedules, incl. the Jul 3 and Sep 7 holidays.
ROLLS = {
    "Jun-26": [(2026, 6, 5), (2026, 6, 8), (2026, 6, 9), (2026, 6, 10), (2026, 6, 11)],
    "Jul-26": [(2026, 7, 8), (2026, 7, 9), (2026, 7, 10), (2026, 7, 13), (2026, 7, 14)],
    "Aug-26": [(2026, 8, 7), (2026, 8, 10), (2026, 8, 11), (2026, 8, 12), (2026, 8, 13)],
    "Sep-26": [(2026, 9, 8), (2026, 9, 9), (2026, 9, 10), (2026, 9, 11), (2026, 9, 14)],
}
CONTRACTS = {
    "WTI": {"Jun-26": "N6->Q6", "Jul-26": "Q6->U6", "Aug-26": "U6->V6", "Sep-26": "V6->X6"},
    "XBR": {"Jun-26": "Q6->U6", "Jul-26": "U6->V6", "Aug-26": "V6->X6", "Sep-26": "X6->Z6"},
}
STEP_FROM, STEP_TO = 17, 19   # measure each step from 17:00 to 19:00 ET
ENTRY_LEADS_H = (1, 24, 72)   # enter this many hours before the first step
FEES = 2 * 0.0001 + 2 * 0.0002  # perp taker in/out (Extended) + ~2bp per side for the CME leg


def step_windows(days):
    return [(et_ms(y, m, d, STEP_FROM), et_ms(y, m, d, STEP_TO)) for y, m, d in days]


def baseline(index: dict[int, float], roll_days: set) -> tuple[float, float]:
    """Mean and sd of the same 17:00->19:00 ET relative move on non-roll weekdays."""
    moves, seen = [], set()
    for t in index:
        d = et(t)
        key = (d.year, d.month, d.day)
        if key in seen or d.weekday() >= 4 or key in roll_days:  # Mon-Thu only: Friday's window hits the weekend close
            continue
        seen.add(key)
        a = price_at(index, et_ms(*key, STEP_FROM))
        b = price_at(index, et_ms(*key, STEP_TO))
        if a and b:
            moves.append(b / a - 1)
    return st.mean(moves), st.pstdev(moves)


HL_NAMES = {"WTI": ("HL_WTIOIL", "HL_CL"), "XBR": ("HL_BRENTOIL",)}


def perp_data(market: str, venue: str):
    """Trade prices and funding of the perp being shorted. The index (spread
    estimate) always comes from Extended, which references the same contracts."""
    if venue == "ext":
        return candles(market, "trades"), funding(market)
    for name in HL_NAMES[market]:
        try:
            return candles(name, "trades"), funding(name)
        except FileNotFoundError:
            continue
    raise FileNotFoundError(f"no Hyperliquid data for {market}; run refresh_data.py --hl")


def run(market: str, lead_h: int = 1, venue: str = "ext") -> list[dict]:
    index = candles(market, "index")
    trades, fund = perp_data(market, venue)
    roll_days = {d for days in ROLLS.values() for d in days}
    mu, sd = baseline(index, roll_days)
    rows = []
    for label, days in ROLLS.items():
        win = step_windows(days)
        if price_at(index, win[0][0]) is None:
            continue
        # Step moves in price terms (net of the usual drift), as a fraction of the
        # index at the first step, so they add up to the spread rather than compound.
        base = price_at(index, win[0][0])
        step_moves = [(price_at(index, b) - price_at(index, a) * (1 + mu)) / base for a, b in win]
        spread = -sum(step_moves)                     # fraction of price
        noise = sd * len(win) ** 0.5
        entry, exit_ = win[0][0] - lead_h * HOUR_MS, win[-1][1]
        if None in (price_at(trades, entry), price_at(index, entry)):
            continue  # entry falls before the data starts
        prem = lambda t: price_at(trades, t) / price_at(index, t) - 1
        prem_in, prem_out = prem(entry), prem(exit_)
        hours = range(entry // HOUR_MS * HOUR_MS + HOUR_MS, exit_, HOUR_MS)
        f = [fund[h] for h in hours if h in fund]
        fund_recv = sum(f)                            # short receives +f
        # Funding paid in the 24h before each step vs what that step delivers.
        per_step = []
        for (a, _), mv in zip(win, step_moves):
            pre = [fund.get(h, 0.0) for h in range(a - 24 * HOUR_MS, a, HOUR_MS)]
            per_step.append((-mv, sum(pre)))
        rows.append({
            "market": market if venue == "ext" else f"{market}@HL", "roll": label, "contracts": CONTRACTS[market][label], "lead_h": lead_h,
            "spread": spread, "noise": noise, "funding": fund_recv, "premium": prem_in - prem_out,
            "funding_hours": len(f), "hours": len(hours),
            "net": spread + fund_recv + prem_in - prem_out - FEES, "per_step": per_step,
        })
    return rows


def report(rows: list[dict], per_step: bool = True) -> None:
    print(f"{'mkt':6} {'roll':7} {'contracts':9} {'spread est':>18} {'funding':>9} "
          f"{'premium':>8} {'fees':>7} {'net':>8}")
    for r in rows:
        gap = "" if r["funding_hours"] == r["hours"] else f"  ({r['funding_hours']}/{r['hours']}h funding data)"
        print(f"{r['market']:6} {r['roll']:7} {r['contracts']:9} "
              f"{fmt_pct(r['spread']):>8} +/-{r['noise'] * 100:.2f}% "
              f"{fmt_pct(r['funding']):>9} {fmt_pct(r['premium']):>8} {fmt_pct(-FEES):>7} "
              f"{fmt_pct(r['net']):>8}{gap}")
    nets = [r["net"] for r in rows]
    print(f"average net per roll: {fmt_pct(st.mean(nets))}   positive in {sum(n > 0 for n in nets)}/{len(nets)}")
    if per_step:
        print("\nper-step view (index step gain / funding paid in the 24h before it):")
        for r in rows:
            cells = "  ".join(f"{g * 100:+.2f}/{f * 100:+.2f}" for g, f in r["per_step"])
            print(f"  {r['market']} {r['roll']}: {cells}")


if __name__ == "__main__":
    import sys
    venue = "hl" if "--hl" in sys.argv else "ext"
    print(f"perp venue: {'trade[XYZ] on Hyperliquid' if venue == 'hl' else 'Extended'}")
    try:
        for i, lead in enumerate(ENTRY_LEADS_H):
            print(f"\n=== short perp + long front month, entry {lead}h before first step, exit after last step ===")
            report(run("WTI", lead, venue) + run("XBR", lead, venue), per_step=(i == len(ENTRY_LEADS_H) - 1))
    except FileNotFoundError as e:
        sys.exit(str(e))
