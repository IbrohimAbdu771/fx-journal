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


def test_validate_mae_mfe_rejects_negative():
    errors, _ = service.validate_mae_mfe({"mae_r": -0.5, "mfe_r": 1.0, "outcome": "Loss"})
    assert errors and any("MAE" in e for e in errors)
    errors2, _ = service.validate_mae_mfe({"mae_r": 0.5, "mfe_r": -1.0, "outcome": "Win"})
    assert errors2 and any("MFE" in e for e in errors2)


def test_validate_mae_mfe_ok_no_flags():
    errors, anomalies = service.validate_mae_mfe(
        {"result_r": 1.8, "mae_r": 0.4, "mfe_r": 2.1, "outcome": "Win"}
    )
    assert errors == [] and anomalies == []


def test_validate_mae_gt_1_is_anomaly_not_error():
    errors, anomalies = service.validate_mae_mfe(
        {"mae_r": 1.3, "result_r": -1.0, "outcome": "Loss"}
    )
    assert errors == []
    assert anomalies and any("MAE" in a for a in anomalies)


def test_validate_winner_mfe_below_result_is_anomaly():
    errors, anomalies = service.validate_mae_mfe(
        {"result_r": 2.0, "mfe_r": 1.5, "outcome": "Win"}
    )
    assert errors == []
    assert anomalies and any("MFE" in a for a in anomalies)


def test_validate_mae_mfe_ignored_for_missed():
    errors, anomalies = service.validate_mae_mfe({"mae_r": -5, "outcome": "Missed"})
    assert errors == [] and anomalies == []


def test_enrich_drops_negative_excursion():
    data = {"pair": "EURUSD", "direction": "Long", "entry": 1.1, "stop_loss": 1.09,
            "mae_r": -0.3, "mfe_r": 1.0}
    out = service.enrich(data, datetime(2026, 7, 14, 8, 0, tzinfo=NY))
    assert out["mae_r"] is None
    assert out["mfe_r"] == 1.0
