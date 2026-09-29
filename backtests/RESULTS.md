# Backtest results (data to 28 Sep 2026)

All data is Extended's public API (hourly Jun–Sep 2026, minute data 22–28 Sep).
Hyperliquid/trade[XYZ] could not be reached from the build environment; rerun
with `python refresh_data.py --hl && python roll.py --hl` to test it.

| Idea | Verdict on Extended data | Why |
|---|---|---|
| 1. Oil roll capture | **Breakeven on average; WTI in steep-backwardation months looked positive** | Funding plus the perp's pre-step discount absorbed 40–100% of the roll spread |
| 2. Weekend convergence | **Oil: little left to converge. Gold: needs a second venue to test** | Extended oil prices in ~86–89% of the weekend move by Sun 17:00 ET; Extended gold only ~14% |
| 3. Market making | **No edge in a rough 1-minute simulation** | Adverse selection ≈ the quoted spread; needs forward paper-trading at real speed |
| 4. PAXG vs XAU | **Loses after realistic costs** | Fair-value spread sd ≈ 12bp < ~14bp round-trip cost; apparent profits on trade prices were bid/ask bounce |

## 1. Oil roll capture (`roll.py`)

Short the perp through trade[XYZ]'s / Extended's 5-step roll, long the front
month. Net = spread at exit + funding received + (premium at entry − at exit) − fees.
The front–next spread is estimated from the five index steps (±noise shown).

| Roll | WTI spread | WTI net (1h / 24h / 72h entry) | Brent spread | Brent net (1h / 24h / 72h) |
|---|---|---|---|---|
| Jun-26 | +0.2% ±1.6 | −0.9 / −0.9 / n/a | −0.6% ±1.2 | −2.0 / −1.9 / n/a |
| Jul-26 | −0.1% ±1.6 | −0.1 / −0.0 / −0.0 | +0.8% ±1.2 | +0.1 / +0.1 / +0.1 |
| Aug-26 | +2.5% ±1.6 | **+1.4 / +1.3 / +1.5** | +3.3% ±1.2 | +0.9 / +0.5 / +0.6 |
| Sep-26 | +5.1% ±1.6 | **+1.3 / +1.1 / +1.0** | +5.2% ±1.2 | +0.3 / +0.0 / −0.1 |

What the data shows:
- **The market prices the roll in.** In each roll the perp trades 0.5–0.75%
  below the index before each daily step. Funding then ramps to −0.05% to −0.1%
  per hour into 17:00 ET and resets after the step. Shorts pay for the drift
  they capture.
- **Brent was fully arbitraged.** Funding took 60–100% of the spread.
- **WTI left roughly 1–1.5% per roll in August and September**, when the curve
  was steeply backwardated. That's 2 good rolls out of 4, inside a noise band of
  ±1.6% per roll, so it's suggestive, not proven.
- **Entry timing matters less than expected.** Entering 1h early pays the
  pre-step discount. Entering 24–72h early mostly swaps that for extra funding.

Next check: the same test on trade[XYZ] (funding multiplier 0.5, a different
book). If WTI there keeps more than about 1% per roll after funding, idea 1 is
real at size.

## 2. Weekend convergence (`weekend.py`)

17 weekends. The table shows each venue's weekend price vs where the market
reopened (median absolute gap).

| | Fri close → reopen move | Sat noon vs reopen | Sun 17:00 vs reopen | Share priced by Sun 17:00 |
|---|---|---|---|---|
| WTI | 1.60% | 1.21% | 0.41% | 86% |
| Brent | 1.27% | 1.02% | 0.64% | 89% |
| Gold | 0.44% | 0.57% | 0.47% | **14%** |

- **Oil:** Extended's weekend oil price is informative. Any cross-venue gap has
  to come from the *other* venue lagging. The two-venue backtest
  (`pair_backtest`) is ready for HL data.
- **Gold:** Extended's weekend gold barely moves, so it reopens near a stale
  Friday price. If trade[XYZ] GOLD prices the weekend well (it is the main
  weekend venue), short or long Extended XAU against HL GOLD on Sunday afternoon
  is the candidate trade. The first test to run once HL data is available.

## 3. Market making (`mm.py`)

Quote Extended WTI at fair ± h, hedge on trade[XYZ] one minute later (5.8 days).

| Half-spread | Fills | Avg edge per fill | PnL/day (20% of volume, $10k clip) |
|---|---|---|---|
| 2bp | 4115 | −1.2bp | −$239 |
| 5bp | 3207 | +0.7bp | −$80 |
| 10bp | 1702 | +2.1bp | −$48 |
| 20bp | 336 | −0.5bp | −$90 |

There's no edge at one-minute resolution. The hedge delay and 1-minute bars
overstate adverse selection for a real bot, so the only honest test is paper
trading.

## 4. PAXG vs XAU on Extended (`paxg.py`)

On mark prices: mean −16.5bp, standard deviation 12.3bp. Mean reversion
(parameters picked in-sample, tested out-of-sample) and the weekend catch-up
**both lose** after 4bp of fees plus an assumed 10bp of spread. On last-trade
prices the same rules showed 57/57 winners, which is bid/ask bounce on a thin
book, not an edge. Don't trade it.
