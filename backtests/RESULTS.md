# Backtest results (data to 28 Sep 2026)

Data: Extended's public API (hourly Jun–Sep 2026, minute data 22–28 Sep) and
trade[XYZ] on Hyperliquid (hourly candles and funding, May–Sep 2026; WTI is
`xyz:CL`). Roll spreads are estimated from Extended's index, which references
the same contracts on the same schedule as trade[XYZ].

| Idea | Verdict on Extended data | Why |
|---|---|---|
| 1. Oil roll capture | **No reliable edge. Real contract prices, 8 WTI rolls: +0.18% avg, t-stat 0.5, worst −2.0%, and one near-liquidation at 3x** | Funding plus the perp's pre-step discount price the roll in; big spreads come with big funding |
| 2. Weekend convergence | **Brent small positive (+0.2%/weekend), WTI ~0, gold no** | Both venues price 86–93% of oil's weekend move; both price only 14–20% of gold's, so neither leads |
| 3. Market making | **No edge in a rough 1-minute simulation** | Adverse selection ≈ the quoted spread; needs forward paper-trading at real speed |
| **5. Brent venue-funding pair** (`funding_pair.py`) | **Best result: short trade[XYZ] / long Extended Brent earned +3.0–3.3% net over 115 days (~10%/yr on notional), 16 of 17 weeks positive (t=4.0)** | Extended's thin Brent book trades at a persistent discount, so its longs are paid more than trade[XYZ]'s shorts pay (trade[XYZ] halves funding) |
| 4. PAXG vs XAU | **Loses after realistic costs** | Fair-value spread sd ≈ 12bp < ~14bp round-trip cost; apparent profits on trade prices were bid/ask bounce |

## Update: real contract prices (Pyth), 8 WTI rolls, $1,000 account (`roll_direct.py`)

Both legs use real prices:
- **Short:** trade[XYZ] `xyz:CL`, hourly since 5 Mar and 4-hourly before that
  (Hyperliquid keeps only its last 5000 hourly candles).
- **Hedge:** the front-month WTI contract from Pyth Pro, which is what Veranta
  holds.
- **Also included:** HL funding and all costs.

The roll schedule was checked against the weights implied by prices. Apr–Sep
match the 5-step schedule exactly; Feb/Mar are noisy because the spread was
small. The Pyth trial key had no access to Brent contracts.

| Roll | Real spread in / out | Perp | Hedge | Funding | Net (Veranta hedge, docs fees) | Net (CME hedge) |
|---|---|---|---|---|---|---|
| Feb-26 | 0.33 / 0.25% | +0.89% | −0.95% | +0.09% | −0.14% | −0.07% |
| Mar-26 | 3.65 / 1.30% | −5.22% | +6.52% | +0.36% | +1.48% | +1.52% |
| Apr-26 | 7.24 / 2.97% | +7.78% | −5.97% | −3.65% | **−2.02%** | −1.81% |
| May-26 | 4.23 / 4.38% | −1.34% | +4.82% | −2.50% | +0.80% | +0.86% |
| Jun-26 | 2.69 / 1.65% | +5.72% | −4.61% | −0.94% | −0.02% | +0.12% |
| Jul-26 | 0.34 / 0.98% | −6.91% | +7.83% | +0.07% | +0.82% | +0.84% |
| Aug-26 | 1.32 / 1.05% | −4.84% | +5.57% | −0.81% | −0.26% | −0.19% |
| Sep-26 | 3.11 / 4.75% | −4.82% | +8.90% | −3.11% | +0.80% | +0.95% |

| Veranta hedge | n | Mean per roll | SD | t-stat | Worst |
|---|---|---|---|---|---|
| All rolls | 8 | +0.18% | 1.07% | 0.48 | −2.02% |
| Entry spread > 2% | 5 | +0.21% | 1.35% | 0.35 | −2.02% |

**Verdict: no statistically meaningful edge.** A large spread at entry doesn't
help. In April the spread was 7.2%, but funding (−3.65%) and the spread
collapsing to 3% before exit made it the worst roll. The earlier "4/4 positive"
came from the spread estimate, not from the market.

**Tail risk:** in the March roll oil spiked, and at 3x the losing leg's
drawdown reached **79% of its margin** (53% at 2x). That's close to
liquidation, and hourly bars can hide sharper spikes. The legs are on
different venues and can't share margin. A liquidated leg turns a hedged
trade into a naked position.

**$1,000 account** ($500 per venue, rolls with entry spread > 2%, compounding,
Feb–Sep):

| Hedge | 2x per leg | 3x per leg |
|---|---|---|
| Veranta, docs fees | $1,010.12 (+1.0%) | $1,014.93 (+1.5%) |
| Veranta, API fees | $1,005.09 (+0.5%) | $1,007.36 (+0.7%) |
| CME | $1,016.13 (+1.6%) | $1,024.02 (+2.4%) |

Path at 3x (Veranta, docs fees):
Mar +$22 → Apr −$31 → May +$12 → Jun −$0 → Sep +$12.

**Brent weekend trade, $1,000** ($500 per venue, 3x, 17 weekends):

| Extended leg priced on | Gap > 0.2% | Gap > 0.5% |
|---|---|---|
| last trade | 10 trades → $1,035.22 (+3.5%), worst +$1.23 | 2 → $1,014.24 |
| mark | 17 trades → $1,059.63 (+6.0%), worst −$7.51 | 12 → $1,011.36, worst −$16.04 |

Neither price series is exactly executable. Expect the truth to sit between
the two until the live monitor's bid/ask log confirms it.

## 1. Oil roll capture (`roll.py`, estimate-based; superseded for WTI by the section above)

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

## 5. Venue-funding pair: short trade[XYZ] / long Extended (`funding_pair.py`, `roll_pair.py`)

Found while widening the search. Every major venue (trade[XYZ], Extended,
Variational, Lighter, OKX, Binance, Bybit) now rolls oil on the same
5th–9th business day blend, so there is no roll-timing mismatch left between
them (see loris.tools/rwa/roll-calendar). What does differ is **funding**:
- **trade[XYZ]** multiplies funding by 0.5.
- **Extended's Brent book is thin** (~$1M open interest), and its perp trades
  at a persistent discount, so its funding stays more negative.

Holding a short on trade[XYZ] and a long on Extended on the same commodity
cancels the price (both track the same contract and roll) and collects the
difference.

| Commodity | Hold | Price legs | Funding | Net (after 4 taker fills) | Weekly funding diff |
|---|---|---|---|---|---|
| **Brent** | 5 Jun → 28 Sep | −0.16% (last trade) / −0.37% (mark) | **+3.45%** | **+3.25% / +3.04%** | **16/17 weeks positive, mean +0.21%/wk, t = 4.0** |
| WTI | 5 Jun → 28 Sep | −0.18% / −0.56% | +0.70% | +0.49% / +0.11% | 11/17, t = 0.8 |
| Gold | 7 Jul → 28 Sep | +0.09% / +0.06% | +0.41% | +0.46% / +0.43% | 7/11, t = 1.7 |

- **Brent is the first result here that is statistically meaningful.**
  $1,000 split across the venues at 3x per leg ($1,500 notional each) went to
  **$1,045.54–$1,048.72** in ~4 months, about **13–15% a year on capital**.
- **Price risk is small but not zero.** The worst interim loss on the price
  legs was −1.4% to −1.9% of notional, from basis swings between venues. Each
  leg still carries the full Brent move against its own venue's margin: a 10%
  Brent move is ~30% of one leg's margin at 3x, and the margins can't be
  netted.
- **Roll windows only** (`roll_pair.py`): Brent +0.07/+0.32/+0.41/+0.52% per
  roll (Jun–Sep). About half the year's differential comes from outside roll
  windows, so a continuous hold is simpler.

What would end it:
- **Market makers deepen Extended's Brent book.** The discount and the funding
  gap would shrink.
- **Either venue changes its funding formula.**
- **Size:** Extended caps oil positions at $1M, and the book is thin. Fine
  at $1–10k, not at fund scale.
- **Venue risk** on both platforms.

This is a funding trade, which you wanted to avoid because rates move. The
difference here is a structural cause (the funding multiplier and the thin
book), and 16/17 positive weeks. Watch the weekly differential and exit if
it turns negative for 2–3 weeks.

Also checked:
- **Natural gas and copper on trade[XYZ]:** $7.7M and $12M open interest. The
  roll trade can't be hedged there: no on-chain venue holds the front natgas
  contract, and the Pyth trial key lacks NG contracts.
- **Offline or empty markets:** trade[XYZ] wheat, corn, TTF, uranium and
  aluminium show zero open interest.

## 6. Cross-venue funding scan: Lighter and Aster added (`funding_scan.py`)

Every commodity × venue pair with hourly funding on trade[XYZ] (HL),
Extended (EXT), Lighter (LT) and Aster (AS, 4h funding spread over its 4
hours). "Short A / long B" earns f_A − f_B.

Sign check: Lighter's daily-average premium to HL correlates positively with
the funding difference (+0.26), consistent with "direction: long = longs pay".

Ranked by t-stat of weekly sums (`python funding_scan.py`):

| Commodity | Short / long | Period | Weeks positive | Mean/wk | ~Annual | t |
|---|---|---|---|---|---|---|
| Brent | HL / AS | 20 May–29 Sep | 17/18 | +0.15% | +7.7% | 4.8 |
| Brent | LT / AS | 27 Jun–28 Sep | 13/13 | +0.32% | +16.4% | 4.3 |
| Brent | HL / EXT | 26 May–28 Sep | 16/17 | +0.21% | +10.7% | 4.0 |
| Brent | LT / EXT | 27 Jun–28 Sep | 12/13 | +0.37% | +19.0% | 3.2 |
| WTI | LT / EXT | 27 Jun–28 Sep | 12/13 | +0.25% | +13.0% | 2.9 |
| WTI | LT / HL | 27 Jun–28 Sep | 12/13 | +0.21% | +10.7% | 2.3 |

Gold, silver and natgas: nothing with t > 2 (gold HL/EXT +1.8%/yr, t = 1.7).

### Continuous hold with real prices on both legs (`python funding_scan.py --hold`)

The table assumes short/long from 29 Jun to 28–29 Sep (91 days), 4 taker fills,
and $1,000 split across the two venues at 3x per leg ($1,500 notional each).

| Pair | Price legs | Funding | Net | Per year | Worst interim | $1,000 → |
|---|---|---|---|---|---|---|
| Brent short LT / long EXT | +0.04% | +4.75% | **+4.76%** | +19.1% | −1.95% | **$1,071.45** |
| Brent short LT / long AS | +0.25% | +4.10% | +4.28% | +17.1% | −1.36% | $1,064.19 |
| WTI short LT / long EXT | +0.01% | +3.28% | +3.27% | +13.1% | −0.86% | $1,049.00 |
| WTI short LT / long HL | +0.18% | +2.66% | +2.83% | +11.3% | −0.16% | $1,042.43 |
| Brent short LT / long HL | +0.11% | +2.02% | +2.11% | +8.5% | −0.31% | $1,031.71 |
| Brent short HL / long EXT | −0.08% | +2.73% | +2.61% | +10.5% | −1.99% | $1,039.20 |
| Brent short HL / long AS | +0.07% | +2.09% | +2.07% | +8.3% | −1.45% | $1,031.11 |

Fees per fill: Lighter 0% (standard account), HL 0.009%, Extended 0.01%,
Aster 0.035%.
- **Prices:** Extended and Aster legs use mark prices, since Aster's Brent
  book has no trade in 38% of hours. The HL and Lighter legs use last trades.
- **Lighter (liquid):** $0.2–0.8M traded per hour, so it is easy to fill.
- **Aster:** spread ~5 bps, and a $1,500 order fits in the top 2–3 levels,
  costing ~0.1% extra per round trip, which the table does not include.
- **Price risk:** the price legs cancel well. The worst interim basis loss is
  under 2% of notional on every pair, and under 0.35% for LT/HL.

### The catch: the Lighter edge is a regime, not a constant

Funding difference by month:

| Pair | Jun (from 27th) | Jul | Aug | Sep |
|---|---|---|---|---|
| Brent LT / EXT | +0.09% | +0.69% | +1.91% | +2.08% |
| Brent LT / HL | −0.02% | −0.08% | +1.40% | +0.70% |
| WTI LT / EXT | +0.11% | +0.47% | +1.08% | +1.63% |
| WTI LT / HL | +0.02% | +0.13% | +0.82% | +1.68% |
| Brent HL / EXT (reference) | +0.89% | +0.75% | +0.51% | +1.39% |

- **July:** all oil perps had near-zero funding, and short Lighter earned
  nothing against HL.
- **Aug–Sep:** oil perps traded at a discount and funding went strongly
  negative (Brent: HL −58%/yr, Extended −77%/yr in Sep). Lighter's went less
  negative (−50%/yr), and that gap is the whole Lighter edge. So short Lighter
  pays well only while funding is deeply negative. If the market flips back
  to flat or positive funding, expect it to shrink to ~0.
- **HL / EXT Brent (section 5) is the steadiest:** positive every month since
  May, because its cause (trade[XYZ]'s 0.5 multiplier plus Extended's thin,
  discounted book) does not depend on the funding regime.

A practical way to run it:
- **Core leg:** long Extended Brent, which receives the most negative funding.
- **Short side:** switch between trade[XYZ] and Lighter, whichever currently
  has the higher (less negative) funding, re-checked weekly. Switching the
  short leg costs ~0.02% per switch.
- **Exit:** if the chosen pair's weekly differential is negative 2–3 weeks
  running.

Data limits:
- Lighter funding is only available from 27 Jun.
- Aster WTI/XAG funding stops early (6 Sep / 14 Sep).
- Aster gold (XAUUSD) returned no history.
- Copper was not scanned on Lighter or Aster.
