"""Synthetic checks that the backtest arithmetic recovers known answers."""

import datetime as dt

import common
import roll
from common import HOUR_MS, ET, et_ms


def test_price_at_uses_bar_ending_at_time():
    s = {0: 1.0, HOUR_MS: 2.0}
    assert common.price_at(s, 2 * HOUR_MS) == 2.0   # bar [1h,2h) closes at 2h
    assert common.price_at(s, 2 * HOUR_MS + 5) == 2.0
    assert common.price_at(s, HOUR_MS) == 1.0


def synthetic_roll(spread=4.0, premium_before_step=0.0, fund_rate=0.0):
    """Flat F1=100, F2=100-spread through the Sep-26 window; index blends by schedule."""
    f1, f2 = 100.0, 100.0 - spread
    steps = [et_ms(y, m, d, 17, 30) for y, m, d in roll.ROLLS["Sep-26"]]
    start = et_ms(2026, 8, 3, 0)
    end = et_ms(2026, 9, 20, 0)
    index, trades, fund = {}, {}, {}
    for t in range(start, end, HOUR_MS):
        w = 0.2 * sum(1 for s in steps if t + HOUR_MS > s)   # bar close after the step
        idx = (1 - w) * f1 + w * f2
        index[t] = idx
        near_step = any(0 <= s - (t + HOUR_MS) < 6 * HOUR_MS for s in steps)
        trades[t] = idx * (1 + (premium_before_step if near_step else 0.0))
        fund[t] = fund_rate
    return index, trades, fund


def test_roll_recovers_spread_without_funding(monkeypatch):
    index, trades, fund = synthetic_roll(spread=4.0)
    monkeypatch.setattr(roll, "candles", lambda m, k, *a: index if k == "index" else trades)
    monkeypatch.setattr(roll, "funding", lambda m: fund)
    r = next(x for x in roll.run("WTI") if x["roll"] == "Sep-26")
    assert abs(r["spread"] - 0.04) < 1e-9
    assert abs(r["net"] - (0.04 - roll.FEES)) < 1e-9


def test_roll_charges_premium_and_funding(monkeypatch):
    index, trades, fund = synthetic_roll(spread=4.0, premium_before_step=-0.008, fund_rate=-0.0002)
    monkeypatch.setattr(roll, "candles", lambda m, k, *a: index if k == "index" else trades)
    monkeypatch.setattr(roll, "funding", lambda m: fund)
    r = next(x for x in roll.run("WTI", lead_h=1) if x["roll"] == "Sep-26")
    assert abs(r["premium"] - (-0.008)) < 1e-9      # entered at a discount, exited at par
    assert r["funding"] < 0 and abs(r["funding"] - (-0.0002 * r["hours"])) < 1e-12
    assert abs(r["net"] - (r["spread"] + r["funding"] + r["premium"] - roll.FEES)) < 1e-12
