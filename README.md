# On-chain oil & gold monitor

Watches two setups on on-chain commodity perps:

1. **Cross-venue convergence (Hyperliquid `xyz`, Extended, Variational Omni).** For WTI, Brent and gold, all three venues track the same underlying. For oil they also roll through the same 5th–9th business-day window, so their prices should converge. The monitor checks every pair of venues and flags the best gap that remains after costs. Costs are counted as follows:
   - Where a venue publishes bid/ask, entry is priced on those executable prices (sell the rich venue's bid, buy the cheap venue's ask).
   - Exit costs half of each venue's spread.
   - Taker fees apply to all four fills.
   - While the oracles follow live external prices, gaps should close within minutes.
   - At weekends each venue prices from its own order book, so gaps can open, then close when external pricing resumes on Sunday evening (Hyperliquid 6:00 pm ET, Extended 6:30 pm ET).
2. **Roll-yield capture.** trade[XYZ] rolls `WTIOIL`/`BRENTOIL` from the front to the next contract with no price adjustment. In backwardation the perp drifts down by the front-next spread. A short Hyperliquid perp hedged with a long front-month leg (a CME future, or Veranta, which adjusts entry prices at the roll) earns that spread, less the funding the short pays. The monitor shows the remaining edge, the funding cost and the break-even funding rate.

## Run

```bash
pip install -r requirements.txt
python onchain_monitor.py              # one snapshot
python onchain_monitor.py --loop 60    # every 60s, appends to monitor_log.csv
python -m pytest -q                    # tests (no network)
```

## Data sources

| Source | Endpoint |
|---|---|
| Hyperliquid xyz dex | `POST api.hyperliquid.xyz/info {"type":"metaAndAssetCtxs","dex":"xyz"}` |
| Extended | `GET api.starknet.extended.exchange/api/v1/info/markets` |
| Variational Omni | `GET omni-client-api.prod.ap-northeast-1.variational.io/metadata/stats` (quotes at $100k size; rate limit 10 req/10s per IP) |
| CME/NYMEX futures (spread) | Yahoo chart API, e.g. `CLX26.NYM`, `BZZ26.NYM` (delayed; confirm on CME/ICE before trading) |

Veranta and XStable are not wired in yet. Check their prices and rates in the app.

## Caveats

- Fees are hard-coded base-tier taker rates as of Sep 2026: Hyperliquid oil 0.009% (growth mode), Hyperliquid gold 0.09%, Extended RWA 0.01%, Variational 0% (you pay its quoted spread instead).
- Variational quotes can be cached for up to 10 minutes. The monitor ignores quotes older than that and falls back to mark prices, and flags any signal priced on marks only.
- Variational's `funding_rate` is treated as an annualised decimal, which fits its sample values. Check it against the app.
- On Hyperliquid, gold's 0.09% fee usually makes Extended vs Variational the better gold pair. Update `FEES` if your tier or the venues' fees change.
- The roll schedule comes from docs.trade.xyz and ignores exchange holidays. Check the roll-schedules page each month.
- Extended's own roll table lists WTI's Oct 2026 roll as `V6 -> X6`, which looks like a typo for `X6 -> Z6`. Its WTI price currently matches Nov (X6). Confirm with Extended before relying on the two venues rolling in sync.
- Both venues restrict access from some jurisdictions.
- Nothing here is risk-free. Legs can be liquidated before prices converge, oracles can fail, and funding can move against you.

## Backtests

`backtests/` holds backtests for the four ideas, on Extended data bundled in `data/`. Results and caveats are in [`backtests/RESULTS.md`](backtests/RESULTS.md).

```bash
cd backtests
python roll.py        # 1. oil roll capture (add --hl after refreshing HL data)
python weekend.py     # 2. weekend convergence
python mm.py          # 3. market-making fill simulation
python paxg.py        # 4. PAXG vs XAU
python refresh_data.py --hl   # extend the data and add trade[XYZ] (needs internet)
python -m pytest -q
```
