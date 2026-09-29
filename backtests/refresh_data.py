"""Download or extend the backtest data (run where the venue APIs are reachable).

    python refresh_data.py            # Extended: WTI, XBR, XAU, PAXG (hourly + funding)
    python refresh_data.py --hl       # also trade[XYZ] on Hyperliquid (hourly + funding)
    python refresh_data.py --days 180

Files are written to ../data in the format common.py reads.
"""

from __future__ import annotations

import argparse
import json
import os
import time

import requests

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
EXT = "https://api.starknet.extended.exchange/api/v1/info"
HL = "https://api.hyperliquid.xyz/info"
UA = {"User-Agent": "Mozilla/5.0 (oil-backtests)"}
HOUR_MS = 3_600_000
EXT_MARKETS = ("WTI-USD", "XBR-USD", "XAU-USD", "PAXG-USD")
HL_COINS = ("xyz:WTIOIL", "xyz:CL", "xyz:BRENTOIL", "xyz:GOLD")


def save(name: str, rows: list[dict]) -> None:
    rows = sorted({r["T"]: r for r in rows}.values(), key=lambda r: r["T"])
    with open(os.path.join(DATA, name), "w") as fh:
        json.dump(rows, fh)
    print(f"  {name}: {len(rows)} rows")


def ext_paged(path: str, start: int, end: int, limit: int, params: dict | None = None) -> list[dict]:
    """Extended returns the newest `limit` rows before endTime; walk backwards."""
    out: list[dict] = []
    while end > start:
        q = {"startTime": start, "endTime": end, "limit": limit, **(params or {})}
        r = requests.get(f"{EXT}/{path}", params=q, headers=UA, timeout=30)
        r.raise_for_status()
        rows = r.json().get("data") or []
        if not rows:
            break
        out += rows
        end = min(x["T"] for x in rows) - 1
        time.sleep(0.2)
    return out


def refresh_extended(start: int, end: int) -> None:
    for mkt in EXT_MARKETS:
        short = mkt.split("-")[0]
        save(f"ext_{short}_funding.json", ext_paged(f"{mkt}/funding", start, end, 1000))
        for kind in ("mark-prices", "index-prices", "trades"):
            rows = ext_paged(f"candles/{mkt}/{kind}", start, end, 1000, {"interval": "PT1H"})
            save(f"ext_{short}_{kind.split('-')[0]}_1h.json", rows)


def hl_post(body: dict):
    r = requests.post(HL, json=body, timeout=30)
    r.raise_for_status()
    return r.json()


def refresh_hyperliquid(start: int, end: int) -> None:
    for coin in HL_COINS:
        short = coin.split(":")[1]
        candles, t = [], start
        while t < end:
            rows = hl_post({"type": "candleSnapshot",
                            "req": {"coin": coin, "interval": "1h", "startTime": t, "endTime": end}})
            if not rows:
                break
            candles += [{"o": c["o"], "h": c["h"], "l": c["l"], "c": c["c"], "v": c["v"], "T": c["t"]} for c in rows]
            t = rows[-1]["t"] + HOUR_MS
            time.sleep(0.2)
        fund, t = [], start
        while t < end:
            rows = hl_post({"type": "fundingHistory", "coin": coin, "startTime": t, "endTime": end})
            if not rows:
                break
            fund += [{"f": x["fundingRate"], "T": x["time"]} for x in rows]
            t = rows[-1]["time"] + 1
            time.sleep(0.2)
        if candles:
            save(f"ext_HL_{short}_trades_1h.json", candles)
            save(f"ext_HL_{short}_funding.json", fund)
        else:
            print(f"  {coin}: no data (not listed?)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=150)
    ap.add_argument("--hl", action="store_true", help="also fetch trade[XYZ] from Hyperliquid")
    a = ap.parse_args()
    end = int(time.time() * 1000)
    start = end - a.days * 86_400_000
    os.makedirs(DATA, exist_ok=True)
    print("Extended:")
    refresh_extended(start, end)
    if a.hl:
        print("Hyperliquid (trade[XYZ]):")
        refresh_hyperliquid(start, end)
