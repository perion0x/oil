import datetime as dt
from unittest import mock

import onchain_monitor as m

ET = m.ET

HL_PAYLOAD = [
    {"universe": [{"name": "xyz:GOLD"}, {"name": "xyz:WTIOIL"}, {"name": "xyz:BRENTOIL"}]},
    [
        {"markPx": "4130.0", "oraclePx": "4128.3", "funding": "0.000009", "impactPxs": ["4130.3", "4130.4"]},
        {"markPx": "92.752", "oraclePx": "92.804", "funding": "-0.000018", "impactPxs": ["92.74", "92.76"]},
        {"markPx": "98.185", "oraclePx": "98.180", "funding": "0.000006", "impactPxs": ["98.18", "98.19"]},
    ],
]
EXT_PAYLOAD = {"status": "OK", "data": [
    {"name": "XAU-USD", "marketStats": {"markPrice": "4138.97", "indexPrice": "4138.97", "fundingRate": "0.000029"}},
    {"name": "WTI-USD", "marketStats": {"markPrice": "92.62", "indexPrice": "92.62", "fundingRate": "-0.000037"}},
    {"name": "XBR-USD", "marketStats": {"markPrice": "97.727", "indexPrice": "97.726", "fundingRate": "-0.000005"}},
]}
VAR_PAYLOAD = {"listings": [
    {"ticker": "CL", "mark_price": "92.70", "funding_rate": "0.0876", "funding_interval_s": 14400,
     "quotes": {"updated_at": "2026-09-28T16:59:30.123456789Z",
                "size_1k": {"bid": "92.69", "ask": "92.71"},
                "size_100k": {"bid": "92.68", "ask": "92.72"}}},
    {"ticker": "BZ", "mark_price": "98.00", "funding_rate": "0",
     "quotes": {"updated_at": "2026-09-28T16:00:00Z",  # stale: an hour old
                "size_100k": {"bid": "97.9", "ask": "98.1"}}},
    {"ticker": "XAU", "mark_price": "4135.0", "funding_rate": "0",
     "quotes": {"updated_at": "2026-09-28T16:59:50Z", "size_100k": {"bid": "4134.5", "ask": "4135.5"}}},
]}
NOW_UTC = dt.datetime(2026, 9, 28, 17, 0, tzinfo=dt.timezone.utc)


def test_parse_hl_and_ext():
    hl = m.parse_hl(HL_PAYLOAD)
    assert hl["xyz:WTIOIL"].mark == 92.752 and hl["xyz:WTIOIL"].funding_1h == -0.000018
    ext = m.parse_ext(EXT_PAYLOAD)
    assert ext["XBR-USD"].mark == 97.727 and ext["XAU-USD"].oracle == 4138.97


def test_hl_names_without_prefix():
    payload = [{"universe": [{"name": "GOLD"}]}, [{"markPx": "1", "oraclePx": "1", "funding": "0"}]]
    assert "xyz:GOLD" in m.parse_hl(payload)


def test_roll_state_october_window():
    before = dt.datetime(2026, 9, 28, 12, 0, tzinfo=ET)
    st = m.roll_state("WTI", before)
    assert (st.front, st.nxt) == ("X6", "Z6")
    assert st.next_weight(before) == 0.0
    # Oct 7 (Wed) 17:30 -> 20%, Oct 8 -> 40%, Oct 9 (Fri) -> 60%, Oct 12 (Mon) -> 80%, Oct 13 -> 100%
    assert [s.date().isoformat() for s in st.steps] == [
        "2026-10-07", "2026-10-08", "2026-10-09", "2026-10-12", "2026-10-13"]
    assert abs(st.next_weight(dt.datetime(2026, 10, 10, 12, 0, tzinfo=ET)) - 0.6) < 1e-9
    assert m.roll_state("BRENT", before).front == "Z6"


def test_roll_state_moves_on_after_window():
    after = dt.datetime(2026, 10, 14, 12, 0, tzinfo=ET)
    st = m.roll_state("WTI", after)
    assert (st.front, st.nxt) == ("Z6", "F7")


def test_externally_priced_sessions():
    assert m.externally_priced(dt.datetime(2026, 9, 28, 12, 0, tzinfo=ET))       # Monday midday
    assert not m.externally_priced(dt.datetime(2026, 9, 28, 17, 30, tzinfo=ET))  # daily break
    assert not m.externally_priced(dt.datetime(2026, 10, 2, 17, 30, tzinfo=ET))  # Friday after close
    assert not m.externally_priced(dt.datetime(2026, 10, 3, 12, 0, tzinfo=ET))   # Saturday
    assert not m.externally_priced(dt.datetime(2026, 10, 4, 17, 59, tzinfo=ET))  # Sunday pre-open
    assert m.externally_priced(dt.datetime(2026, 10, 4, 18, 0, tzinfo=ET))       # Sunday reopen


def test_parse_var_quotes_and_staleness():
    v = m.parse_var(VAR_PAYLOAD, now=NOW_UTC)
    assert (v["CL"].bid, v["CL"].ask) == (92.68, 92.72)  # $100k quote preferred
    assert abs(v["CL"].funding_1h - 0.0876 / 8760) < 1e-15
    assert v["BZ"].bid is None and v["BZ"].mark == 98.0  # stale quote dropped
    assert v["BZ"].quote_age_s == 3600


def test_pair_signal_on_quotes():
    rich = m.Quote("hl", mark=100.10, bid=100.09, ask=100.11)
    cheap = m.Quote("var", mark=100.00, bid=99.98, ask=100.02)
    s = m.pair_signal("WTI", rich, cheap)
    assert s["priced_on"] == "quotes" and s["pair"] == "short HL / long VAR"
    # entry 100.09 - 100.02 = 0.07; exit 0.01 + 0.02 = 0.03; fees 2 x 0.9bp
    assert abs(s["net_bps"] - (0.04 / 100.05 * 1e4 - 1.8)) < 1e-9


def test_pair_signal_falls_back_to_marks():
    s = m.pair_signal("WTI", m.Quote("hl", mark=100.10), m.Quote("ext", mark=100.00))
    assert s["priced_on"] == "marks"
    assert abs(s["fees_bps"] - 3.8) < 1e-9  # 2 x (0.9 + 1.0) bps


def test_best_pair_picks_direction():
    quotes = {"hl": m.Quote("hl", mark=100.0), "ext": m.Quote("ext", mark=100.5),
              "var": m.Quote("var", mark=99.8)}
    assert m.best_pair("WTI", quotes)["pair"] == "short EXT / long VAR"


def test_pick_falls_back_to_alternate_symbol():
    books = {"hl": {"xyz:CL": m.Quote("hl", mark=93.0)}}
    assert m.pick("WTI", "hl", books).mark == 93.0
    assert m.pick("BRENT", "hl", books) is None


def test_roll_signal_before_window():
    now = dt.datetime(2026, 9, 28, 12, 0, tzinfo=ET)
    st = m.roll_state("WTI", now)
    r = m.roll_signal(st, now, front_px=92.41, next_px=88.71, hl_funding_1h=-0.000018)
    assert abs(r["spread"] - 3.70) < 1e-9
    assert abs(r["edge_pct"] - 3.70 / 92.41 * 100) < 1e-9
    # short pays negative funding for every hour until roll completes
    assert r["funding_cost_pct"] > 0 and r["net_pct"] < r["edge_pct"]
    assert r["breakeven_funding_1h_pct"] < 0


def test_roll_signal_without_prices():
    now = dt.datetime(2026, 9, 28, 12, 0, tzinfo=ET)
    r = m.roll_signal(m.roll_state("BRENT", now), now, None, None, None)
    assert "spread" not in r and r["front"] == "Z6"


def test_snapshot_end_to_end(capsys):
    def resp(payload):
        return mock.Mock(json=lambda: payload, raise_for_status=lambda: None)

    def fake_get(url, **kw):
        return resp(VAR_PAYLOAD if url == m.VAR_URL else EXT_PAYLOAD)

    futures = {("CL", "X6"): 92.41, ("CL", "Z6"): 88.71, ("BZ", "Z6"): 98.63, ("BZ", "F7"): 94.88}
    real_parse_var = m.parse_var
    with mock.patch.object(m.requests, "post", return_value=resp(HL_PAYLOAD)), \
         mock.patch.object(m.requests, "get", side_effect=fake_get), \
         mock.patch.object(m, "parse_var", lambda p: real_parse_var(p, now=NOW_UTC)), \
         mock.patch.object(m, "fetch_future", side_effect=lambda r, c: futures[(r, c)]):
        rows = m.snapshot(now=dt.datetime(2026, 9, 28, 13, 0, tzinfo=ET))
    out = capsys.readouterr().out
    assert "X6->Z6" in out and "Z6->F7" in out
    wti = next(r for r in rows if r["asset"] == "WTI")
    assert wti["var_mark"] == 92.70 and wti["pair"]
    assert any(r["asset"] == "WTI_ROLL" and "net_pct" in r for r in rows)
