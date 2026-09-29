"""Shared data loading for the backtests.

Data lives in ../data as JSON exported from venue APIs:
  ext_<MKT>_<kind>_<interval>.json  candles  [{o,h,l,c,v?,T}]   (Extended)
  ext_<MKT>_funding*.json           funding  [{m,f,T}]          (Extended, hourly)
Run refresh_data.py on a machine with internet access to update or extend them.
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
DATA = os.path.join(os.path.dirname(__file__), "..", "data")
HOUR_MS = 3_600_000


def _load(name: str) -> list[dict]:
    with open(os.path.join(DATA, name)) as fh:
        return json.load(fh)


def candles(market: str, kind: str, interval: str = "1h", field: str = "c") -> dict[int, float]:
    """{bar open time ms: price}. kind is mark, index or trades."""
    return {x["T"]: float(x[field]) for x in _load(f"ext_{market}_{kind}_{interval}.json")}


def candle_rows(market: str, kind: str, interval: str = "1m") -> dict[int, dict]:
    return {x["T"]: {k: float(v) for k, v in x.items() if k != "T"} for x in _load(f"ext_{market}_{kind}_{interval}.json")}


def funding(market: str) -> dict[int, float]:
    """Hourly funding rate keyed by the hour (ms, floored). Positive = longs pay shorts."""
    out: dict[int, float] = {}
    for path in sorted(glob.glob(os.path.join(DATA, f"ext_{market}_funding*.json"))):
        for x in _load(os.path.basename(path)):
            out[x["T"] // HOUR_MS * HOUR_MS] = float(x["f"])
    return out


def et_ms(y: int, m: int, d: int, hh: int, mm: int = 0) -> int:
    return int(dt.datetime(y, m, d, hh, mm, tzinfo=ET).timestamp() * 1000)


def et(ts_ms: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts_ms / 1000, ET)


def price_at(series: dict[int, float], ts_ms: int, bar_ms: int = HOUR_MS) -> float | None:
    """Price at an instant = close of the bar that ends at (or just before) ts_ms."""
    t = (ts_ms // bar_ms) * bar_ms - bar_ms
    for _ in range(6):  # tolerate a few missing bars
        if t in series:
            return series[t]
        t -= bar_ms
    return None


def fmt_pct(x: float | None, digits: int = 2) -> str:
    return "n/a" if x is None else f"{x * 100:+.{digits}f}%"
