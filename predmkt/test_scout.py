import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import scout  # noqa: E402


def test_group_edges_signs():
    g = scout.group_edges([0.3, 0.3, 0.3], [0.2, 0.2, 0.2], fee_on=False)
    assert abs(g["buy_yes"] - 0.1) < 1e-9 and abs(g["buy_no"] - (2 - 2.4)) < 1e-9
    g = scout.group_edges([0.5, 0.6], [0.55, 0.58], fee_on=False)  # bids sum 1.13
    assert abs(g["buy_no"] - 0.13) < 1e-9 and g["buy_yes"] < 0
    assert scout.group_edges([0.5, 0.6], [0.55, 0.58])["buy_no"] < 0.13  # fees reduce it


def test_looks_exhaustive():
    assert scout.looks_exhaustive(["August", "No Return to Normal Traffic in 2026"])
    assert scout.looks_exhaustive(["$100 or above", "$90-99"])
    assert not scout.looks_exhaustive(["Cardinal A", "Cardinal B"])


def test_kalshi_groups_and_ladders():
    ev = {"event_ticker": "E", "title": "t", "mutually_exclusive": True, "markets": [
        {"status": "active", "yes_ask_dollars": "0.40", "yes_bid_dollars": "0.60", "yes_sub_title": "A", "ticker": "a"},
        {"status": "active", "yes_ask_dollars": "0.50", "yes_bid_dollars": "0.55", "yes_sub_title": "B", "ticker": "b"}]}
    g = scout.kalshi_groups([ev])[0]
    assert g["buy_no"] > 0 and not g["exhaustive_hint"]
    lad = {"event_ticker": "L", "title": "max", "markets": [
        {"status": "active", "strike_type": "greater", "floor_strike": 100, "yes_bid_dollars": "0.30", "yes_ask_dollars": "0.32", "ticker": "T100"},
        {"status": "active", "strike_type": "greater", "floor_strike": 110, "yes_bid_dollars": "0.40", "yes_ask_dollars": "0.45", "ticker": "T110"}]}
    v = scout.kalshi_ladders([lad])
    assert len(v) == 1 and v[0]["buy_yes"] == "T100" and v[0]["buy_no"] == "T110"
