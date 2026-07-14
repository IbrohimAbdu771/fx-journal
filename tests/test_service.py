from datetime import datetime
from zoneinfo import ZoneInfo

from core import service

NY = ZoneInfo("America/New_York")


def test_enrich_computes_rr_session_name():
    data = {"pair": "EURUSD", "direction": "Long", "entry": 1.1000,
            "stop_loss": 1.0950, "take_profit": 1.1100}
    tt = datetime(2026, 7, 14, 8, 0, tzinfo=NY)  # NY session
    out = service.enrich(data, tt)
    assert out["rr_planned"] == 2.0
    assert out["session"] == "NY"
    assert out["sb_window"] is False
    assert out["status"] == "Open"
    assert out["name"] == "EURUSD LONG 14.07"


def test_enrich_status_closed_when_result():
    data = {"pair": "GBPUSD", "direction": "Short", "result_r": 1.8, "outcome": "Win"}
    out = service.enrich(data, datetime(2026, 7, 14, 10, 30, tzinfo=NY))
    assert out["status"] == "Closed"
    assert out["sb_window"] is True   # NY AM Silver Bullet window


def test_missing_critical():
    assert service.missing_critical({"pair": "EURUSD", "direction": "Long"}) == ["вход", "стоп"]
    full = {"pair": "EURUSD", "direction": "Long", "entry": 1.1, "stop_loss": 1.09}
    assert service.missing_critical(full) == []
