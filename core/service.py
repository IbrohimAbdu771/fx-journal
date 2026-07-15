"""Business logic shared by the bot and the web app: enrich a raw trade dict.

Pure functions — no DB, no network. Given the fields a user (or Claude) supplied
plus the trade time, fill in the derived fields: planned RR, ICT session,
Silver-Bullet flag, auto title, and the Open/Closed status.
"""
from __future__ import annotations

from datetime import datetime

from . import ict

CLOSED_OUTCOMES = {"Win", "Loss", "Breakeven"}
# fields a caller may set on a trade
EDITABLE_FIELDS = [
    "pair", "direction", "entry", "stop_loss", "take_profit", "lot", "risk_pct",
    "result_r", "result_usd", "mae_r", "mfe_r", "outcome", "status", "mode",
    "session", "sb_window", "asia_type", "setup", "sweep_reference", "ote_level",
    "mss_confirmed", "news_blackout",
    "plan_followed", "violation_type", "emotion", "notes", "raw_message",
]


def build_name(pair: str | None, direction: str | None, trade_time: datetime) -> str:
    parts = []
    if pair:
        parts.append(pair)
    if direction:
        parts.append(direction.upper())
    parts.append(trade_time.strftime("%d.%m"))
    return " ".join(parts)


def enrich(data: dict, trade_time: datetime, tz: str = "America/New_York") -> dict:
    """Return a copy of `data` with derived fields filled in.

    - rr_planned computed from entry/SL/TP (unless already provided)
    - session / sb_window derived from trade_time when absent
    - name auto-generated
    - status inferred (Closed if a result/outcome is present)
    """
    out = dict(data)

    if out.get("rr_planned") is None:
        out["rr_planned"] = ict.compute_rr(
            out.get("entry"), out.get("stop_loss"), out.get("take_profit")
        )

    if not out.get("session"):
        out["session"] = ict.classify_session(trade_time, tz)
    if out.get("sb_window") is None:
        out["sb_window"] = ict.in_silver_bullet(trade_time, tz)

    # status inference
    if not out.get("status"):
        has_result = out.get("result_r") is not None or out.get("result_usd") is not None
        is_closed_outcome = out.get("outcome") in CLOSED_OUTCOMES
        out["status"] = "Closed" if (has_result or is_closed_outcome) else "Open"

    out["name"] = out.get("name") or build_name(out.get("pair"), out.get("direction"), trade_time)
    if out.get("violation_type") is None:
        out["violation_type"] = []

    # MAE/MFE are non-negative modules; a negative here means "not measured".
    # (The web layer rejects negatives up front; this guards every other path.)
    for key in ("mae_r", "mfe_r"):
        v = out.get(key)
        if isinstance(v, (int, float)) and v < 0:
            out[key] = None
    return out


def missing_critical(data: dict) -> list[str]:
    """Critical fields for a NEW trade: pair, direction, entry, stop."""
    critical = {"pair": "пара", "direction": "направление", "entry": "вход", "stop_loss": "стоп"}
    return [label for field, label in critical.items() if data.get(field) in (None, "")]


# outcomes for which MAE/MFE make no sense (never entered the market)
_NO_EXCURSION_OUTCOMES = {"Missed", "No Trade"}


def validate_mae_mfe(data: dict) -> tuple[list[str], list[str]]:
    """Validate the optional MAE/MFE fields on a trade dict.

    Returns ``(errors, anomalies)``:
    - errors  — hard failures (negative MAE/MFE); callers should reject.
    - anomalies — soft flags worth surfacing but not blocking:
      * a winner whose MFE is below its own result (mfe_r < result_r);
      * MAE beyond the stop (mae_r > 1.0), i.e. slippage / manual exit past SL.

    For Missed / No Trade outcomes the fields are ignored (empty result).
    """
    errors: list[str] = []
    anomalies: list[str] = []
    if data.get("outcome") in _NO_EXCURSION_OUTCOMES:
        return errors, anomalies

    mae = data.get("mae_r")
    mfe = data.get("mfe_r")

    if isinstance(mae, (int, float)) and mae < 0:
        errors.append("MAE не может быть отрицательным (это модуль хода против позиции).")
    if isinstance(mfe, (int, float)) and mfe < 0:
        errors.append("MFE не может быть отрицательным (это модуль хода в пользу позиции).")
    if errors:
        return errors, anomalies

    result_r = data.get("result_r")
    if (
        isinstance(mfe, (int, float))
        and isinstance(result_r, (int, float))
        and result_r > 0
        and mfe < result_r
    ):
        anomalies.append(
            f"MFE {mfe:g}R меньше зафиксированного результата {result_r:g}R — проверь значения."
        )
    if isinstance(mae, (int, float)) and mae > 1.0:
        anomalies.append(
            f"MAE {mae:g}R > 1R — цена уходила за стоп (проскальзывание/ручное закрытие)."
        )
    return errors, anomalies
