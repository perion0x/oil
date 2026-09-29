# Backtest results (data to 28 Sep 2026)

Data: Extended's public API (hourly Jun–Sep 2026, minute data 22–28 Sep) and
trade[XYZ] on Hyperliquid (hourly candles and funding, May–Sep 2026; WTI is
`xyz:CL`). Roll spreads are estimated from Extended's index, which references
the same contracts on the same schedule as trade[XYZ].

| Idea | Verdict on Extended data | Why |
|---|---|---|
| 1. Oil roll capture | **Positive only when the curve is steeply backwardated: ~+0.8% to +1.4% per roll on trade[XYZ] (4/4 in Aug–Sep)**; loses when the spread is small | Funding plus the perp's pre-step discount absorb most, not all, of the spread |
| 2. Weekend convergence | **Brent small positive (+0.2%/weekend), WTI ~0, gold no** | Both venues price 86–93% of oil's weekend move; both price only 14–20% of gold's, so neither leads |
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

### Same test with trade[XYZ] as the short (`python roll.py --hl`)

| Roll | Spread est. | WTI net (1h / 24h / 72h entry) | Brent net (1h / 24h / 72h) |
|---|---|---|---|
| Jun-26 | ~0% | −1.3 / −1.4 / n/a | −1.9 / −1.7 / n/a |
| Jul-26 | ~0–1% | −0.2 / −0.1 / +0.0 | +0.4 / +0.4 / +0.6 |
| Aug-26 | 2.5–3.3% | **+1.3 / +1.2 / +1.3** | **+1.3 / +1.0 / +1.1** |
| Sep-26 | ~5% | **+1.3 / +1.4 / +1.3** | **+0.8 / +0.9 / +0.9** |

- **trade[XYZ] keeps more of the spread than Extended**, especially on Brent,
  where Extended kept ~0–0.9% vs trade[XYZ]'s 0.8–1.3%.
- **Rule that falls out:** trade the roll only when the front–next spread is
  above ~2% (visible on CME/ICE before the window). Then all 4 trades were
  positive, averaging **~+1.2% of hedged notional per roll**. Below that the
  funding and discount win, and it loses.
- **Oct-26 qualifies:** WTI X6–Z6 ≈ $3.70 (4.0%), Brent Z6–F7 ≈ $3.75 (3.8%).
  Window 7 Oct 17:30 ET → 13 Oct.
### Perps-only version: hedge on Veranta instead of CME (`python roll.py --hl --hedge=veranta`)

Veranta (ex-Avantis) prices the front contract off Pyth until expiry, then
rolls with an entry-price adjustment, so it still holds the November contract
while trade[XYZ] rolls to December. It is closed 18:00–20:00 ET daily, so both
legs close at 20:00 ET on the last day. It has no public price history, so it
is modelled from its published parameters:
- **Hedge price:** equal to the front-month contract, per its Pyth feed.
- **Fees:** docs say zero commission on commodities in growth mode, with a
  0.06% spread paid in and out. The API shows a 0.10% open fee on top, so both
  cases are run.
- **Holding cost:** 0.0002853% per hour for a long, about 2.5%/yr.

Rolls with a spread > 2% only (Aug + Sep, WTI + Brent), 1h entry:

| Hedge leg | Costs per round trip (both legs) | Avg net per roll | Positive |
|---|---|---|---|
| CME micro WTI | ~0.06% | +1.17% | 4/4 |
| Veranta, docs fees | ~0.18% | **+1.04%** | 4/4 |
| Veranta, API fees | ~0.28% | **+0.94%** | 4/4 |

Per roll with Veranta (docs fees): WTI Aug +1.21%, WTI Sep +1.16%,
Brent Aug +1.20%, Brent Sep +0.58%. Rolls with a small spread (Jun/Jul) lose
0.3–2.1%, so the filter matters even more with Veranta's higher costs.

The perps-only version rests on two assumptions the data can't check:
- **Veranta fills near its Pyth price.**
- **Its pool accepts the size.** WTI open interest there was ~$51K.

Treat it as a small-size strategy until live fills confirm both.

- **Caveat:** that's 4 profitable observations, in 2 months, from 2 correlated
  markets. The spread estimate carries ±1.2–1.6% noise per roll. Size small
  and log every fill.

## 2. Weekend convergence (`weekend.py`)

17 weekends. The table shows each venue's weekend price vs where the market
reopened (median absolute gap).

| | Fri close → reopen move | Sat noon vs reopen | Sun 17:00 vs reopen | Share priced by Sun 17:00 |
|---|---|---|---|---|
| WTI | 1.60% | 1.21% | 0.41% | 86% |
| Brent | 1.27% | 1.02% | 0.64% | 89% |
| Gold | 0.44% | 0.57% | 0.47% | **14%** |

trade[XYZ] priced 93% (WTI), 91% (Brent) and 20% (gold) of the weekend move
by Sunday 17:00. That's close to Extended, so neither venue leads the other.

Two-venue backtest. The signal is the weekend gap, the fill comes one hour
later, the exit is Sunday 19:00 ET, and fees are included:

| Market | Extended priced on | Gap > 0.2% | Gap > 0.5% | Gap > 1% |
|---|---|---|---|---|
| WTI | last trade | 3 wknds, +0.06% avg | none | none |
| WTI | mark | 17, −0.01% | 10, +0.11% | 3, −0.08% |
| Brent | last trade | **10, +0.23%, 10/10 win** | 2, +0.47% | 1, −0.01% |
| Brent | mark | **17, +0.23%, 13/17** | 12, +0.06% | 5, +0.40% |
| Gold | either | 1–3, −0.1% | none | none |

- **Gold is dead.** Neither venue prices the weekend, and trade[XYZ]'s 0.09%
  gold fee kills any gap.
- **Brent is the only candidate**, at about +0.2% per weekend on small size
  (Extended caps oil positions at $1M, and its Brent book is thin). Hourly
  last-trade and mark prices are both imperfect stand-ins for executable
  prices, so confirm with the live monitor's bid/ask log before trading it.

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
