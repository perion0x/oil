import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import scan  # noqa: E402


def mk(title, bid, ask, end="2026-10-01", closed=False):
    return {"groupItemTitle": title, "bestBid": bid, "bestAsk": ask, "endDate": end, "closed": closed}


def test_walk_and_full_set():
    assert scan.walk([(0.1, 5), (0.2, 5)], 7) == 0.1 * 5 + 0.2 * 2
    assert scan.walk([(0.1, 5)], 6) is None
    books = {"a": [(0.40, 10), (0.50, 100)], "b": [(0.50, 10), (0.60, 100)]}
    best = scan.full_set(books, step=5)
    assert best["sets"] == 10 and abs(best["profit"] - 1.0) < 1e-9  # 10 sets at 0.90
    assert scan.full_set({"a": [(0.5, 10)], "b": [(0.5, 10)]}) is None  # no profit at 1.00


def test_screen_full_sets_needs_negrisk():
    ms = [dict(mk("A", "0.4", "0.45"), clobTokenIds='["1"]'), dict(mk("B", "0.5", "0.5"), clobTokenIds='["2"]')]
    assert scan.screen_full_sets([{"slug": "x", "negRisk": True, "markets": ms}])[0]["sum_ask"] == 0.95
    assert scan.screen_full_sets([{"slug": "x", "negRisk": False, "markets": ms}]) == []


def test_date_ladder_only_for_by_events():
    ms = [mk("October 31", "0.10", "0.12", "2026-11-01"), mk("September 30", "0.20", "0.22", "2026-10-01")]
    rows = scan.date_ladder({"title": "X happens by...?", "markets": ms})
    assert [r[0] for r in rows] == ["September 30", "October 31"]
    v = scan.ladder_violations(rows)
    assert len(v) == 1 and v[0]["buy_yes"] == "October 31" and abs(v[0]["edge"] - 0.08) < 1e-9
    assert scan.date_ladder({"title": "X happens on...?", "markets": ms}) is None


def test_hit_ladders_ordering():
    ms = [mk("↑ $100", "0.30", "0.32"), mk("↑ $110", "0.35", "0.36"), mk("↓ $80", "0.40", "0.41"),
          mk("↓ $70", "0.20", "0.22"), mk(None, None, None)]
    up, down = scan.hit_ladders({"markets": ms})
    assert [r[0] for r in up] == ["↑ $110", "↑ $100"] and [r[0] for r in down] == ["↓ $70", "↓ $80"]
    assert scan.ladder_violations(up)[0]["buy_yes"] == "↑ $100"  # $110 bid 0.35 > $100 ask 0.32
    assert scan.ladder_violations(down) == []


def test_cross_hormuz_directions():
    poly = {dt.date(2026, 11, 30): (0.12, 0.13, "by-date market")}
    k = [{"before": "2026-12-01", "yes_bid": 0.09, "yes_ask": 0.10}]
    r = scan.cross_hormuz(poly, k)[0]
    assert r["strict_edge"] < 0
    assert abs(r["near_edge"] - (0.12 - 0.10 - scan.kalshi_fee(0.10))) < 1e-12
    r = scan.cross_hormuz(poly, [{"before": "2026-12-01", "yes_bid": 0.16, "yes_ask": 0.17}])[0]
    assert r["strict_edge"] > 0  # Kalshi bid above Polymarket ask


def test_offline_snapshot_runs(capsys):
    scan.main(offline=True)
    out = capsys.readouterr().out
    assert "which-month-will-strait-of-hormuz" in out and "profit $2.40" in out
