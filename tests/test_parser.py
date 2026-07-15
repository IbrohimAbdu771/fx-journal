"""Tests for parsing Claude's tool output (no network)."""
from bot.parser import TOOL, TRADE_FIELDS, _validate


def test_tool_schema_shape():
    assert TOOL["name"] == "record_trade"
    props = TOOL["input_schema"]["properties"]
    assert "intent" in props
    assert TOOL["input_schema"]["required"] == ["intent"]
    # every trade field is present in the schema
    for f in TRADE_FIELDS:
        assert f in props


def test_validate_full_new_trade():
    raw = {
        "intent": "new_trade",
        "pair": "EURUSD", "direction": "Long",
        "entry": 1.1000, "stop_loss": 1.0950, "take_profit": 1.1100,
        "lot": 0.5, "risk_pct": 1.0,
        "session": "NY", "sb_window": True, "setup": "NY reversal",
        "sweep_reference": "PDL", "ote_level": "0.705", "mss_confirmed": True,
        "emotion": "спокоен", "plan_followed": "По плану",
        "violation_type": ["погоня за ценой", "мусор"],
        "notes": "  clean setup  ",
    }
    out = _validate(raw)
    assert out["intent"] == "new_trade"
    assert out["pair"] == "EURUSD"
    assert out["entry"] == 1.1000
    assert out["sb_window"] is True
    assert out["mss_confirmed"] is True
    assert out["violation_type"] == ["погоня за ценой"]   # invalid dropped
    assert out["notes"] == "clean setup"


def test_validate_rejects_bad_enums_and_types():
    raw = {
        "intent": "weird",
        "pair": "XAUUSD",            # not allowed
        "direction": "sideways",     # not allowed
        "entry": "1.10",             # string -> None
        "sb_window": "yes",          # non-bool -> None
        "outcome": "Jackpot",        # not allowed
    }
    out = _validate(raw)
    assert out["intent"] == "other"  # unknown intent -> other
    assert out["pair"] is None
    assert out["direction"] is None
    assert out["entry"] is None
    assert out["sb_window"] is None
    assert out["outcome"] is None


def test_validate_close_trade():
    raw = {"intent": "close_trade", "pair": "GBPUSD", "result_r": 1.8, "outcome": "Win"}
    out = _validate(raw)
    assert out["intent"] == "close_trade"
    assert out["result_r"] == 1.8
    assert out["outcome"] == "Win"
    assert out["violation_type"] == []


def test_validate_extracts_mae_mfe():
    raw = {"intent": "close_trade", "pair": "EURUSD", "result_r": 1.8,
           "mae_r": 0.4, "mfe_r": 2.1, "outcome": "Win"}
    out = _validate(raw)
    assert out["mae_r"] == 0.4
    assert out["mfe_r"] == 2.1


def test_validate_mae_mfe_absent_is_none_not_zero():
    out = _validate({"intent": "close_trade", "result_r": -1.0, "outcome": "Loss"})
    assert out["mae_r"] is None
    assert out["mfe_r"] is None
