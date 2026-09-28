# On-chain oil & gold monitor

Watches two setups on on-chain commodity perps:

1. **Cross-venue convergence (Hyperliquid `xyz` vs Extended).** For WTI, Brent and gold, both venues track the same underlying. For oil they also roll through the same 5-day window, so the two marks should converge. The monitor flags gaps that are larger than taker fees on both legs.
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
| CME/NYMEX futures (spread) | Yahoo chart API, e.g. `CLX26.NYM`, `BZZ26.NYM` (delayed; confirm on CME/ICE before trading) |

Veranta and XStable have no public market-data API wired in yet. Check their prices and rates in the app.

## Caveats

- Fees are hard-coded base-tier taker rates as of Sep 2026: Hyperliquid oil 0.009% (growth mode), Hyperliquid gold 0.09%, Extended RWA 0.01%. Update `FEES` if your tier or the venues' fees change.
- The roll schedule comes from docs.trade.xyz and ignores exchange holidays. Check the roll-schedules page each month.
- Extended's own roll table lists WTI's Oct 2026 roll as `V6 -> X6`, which looks like a typo for `X6 -> Z6`. Its WTI price currently matches Nov (X6). Confirm with Extended before relying on the two venues rolling in sync.
- Both venues restrict access from some jurisdictions.
- Nothing here is risk-free. Legs can be liquidated before prices converge, oracles can fail, and funding can move against you.
