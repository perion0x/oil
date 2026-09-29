# Oil and shipping prediction markets: arbitrage scan (snapshot 29 Sep 2026)

`python scan.py --offline` reproduces everything below from the snapshots in
this folder. `python scan.py` runs live (needs Polymarket and Kalshi API access).

## What is listed

| Venue | Oil | Shipping |
|---|---|---|
| Polymarket | WTI "hit ↑/↓ $K" by week and month (resolves on Pyth CLL); WTI daily close; crude all-time high by date (CME front-month daily high); US crude reserves; Venezuelan output; Saudi East-West pipeline | Hormuz traffic back to normal by date, and by month (IMF PortWatch 7-day avg ≥ 60); Bab el-Mandeb closed by date (avg ≤ 10); ship counts; Houthi attacks and seizures; Hormuz fees |
| Kalshi | WTI max/min settle to Sep 30 and Dec 31 (ICE settles); WTI daily, weekly, hourly, 15-min; "when will WTI hit"; Brent weekly and monthly (Pyth); heating oil; natgas; US gasoline | Hormuz traffic normal before date (PortWatch avg **> 60**); Hormuz max daily traffic |

## Findings

**1. Full-set arbitrage on Polymarket: real but tiny.**
- **The market:** "Which month will Hormuz traffic return to normal?" is a
  negRisk event, so exactly one of its 6 outcomes (Aug, Sep, Oct, Nov, Dec,
  "No return in 2026") pays $1.
- **The prices:** the best asks sum to $0.977.
- **Depth:** walking the order books, the best trade is ~265 sets for
  **$262.60 → $265.00, profit $2.40 (0.9%)**. It pays out at resolution, as
  late as 1 Feb 2027.
- **Why it is small:** the September and November books hold only 5–7
  contracts at the best price. There are no trading fees on these markets.
- **Remaining risk:** only resolution risk (UMA oracle, PortWatch data revisions).

**2. Ladders are consistent.**
- **What was checked:** every "by date" ladder, and the WTI up/down strike
  ladders for September, the week of 28 Sep and October. Each was checked for
  a smaller event bid above a larger event's ask.
- **Result:** no violations.

**3. Kalshi vs Polymarket, Hormuz: near-arbitrage only.**
- **Why the pair is linked:** both venues resolve on the same IMF PortWatch
  7-day average. Kalshi needs it **above** 60 and Polymarket **at or above**
  60, so Kalshi YES implies Polymarket YES.
- **The strict direction** (Kalshi bid > Polymarket ask) is negative on every date.
- **The best reverse trade** is buy Kalshi YES "before 1 Dec" at 0.10 and buy
  Polymarket NO "by 30 Nov" at 0.88. That is **+1.4% after Kalshi's fee**, on
  ~1,500 contracts at Kalshi's ask.
- **How it can lose:** the average peaks at exactly 60.0 and never goes
  higher, or the two venues read different PortWatch revisions. That makes it
  a small, bounded bet, not an arbitrage.

**4. WTI ladder vs perp volatility: fairly priced.**
- **Implied volatility:** Polymarket's October WTI ladder (resolves on Pyth
  CLL, the same WTI feed family the perps use) implies **42–57% volatility**
  across the $75–$130 strikes.
- **Realized volatility:** trade[XYZ] `xyz:CL` has realized **46–57%** (7–90
  days, hourly and daily).
- **The tails trade rich:** ↑$140–150 imply 55–63% and ↓$60 or below 56–100%+.
  That is consistent with pricing in war and supply-shock jumps, not a
  mispricing you can lock in.
- **Why no hedge:** a touch binary cannot be hedged statically with a perp, so
  any trade here is a volatility view, not an arbitrage.
- **Roll caveat:** CLL rolls contracts. In steep backwardation, a roll day
  mechanically moves the index and can trigger ↓ touches. Read the CLL roll
  rules before trading these around 7–13 Oct.

## Takeaway

- **These books are efficient** at the level retail can trade. Logical
  mispricings appear, but they are worth dollars, not thousands.
- **What gives an edge:** watching continuously (they appear after news, when
  one leg of a set reprices before the others) and knowing each market's
  resolution rules exactly. The Kalshi ">60" vs Polymarket "≥60" wording is
  the kind of detail that decides whether a trade is an arbitrage.
- **What is worth more to a commodity desk:** these markets as live, tradable
  probabilities on physical-supply events (Hormuz normalisation ~19–21% by
  year-end, Bab el-Mandeb closure 17–18%), set against what oil futures
  spreads and freight rates are pricing.
