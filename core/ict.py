"""ICT domain helpers: session classification, RR math, controlled vocabularies.

All session math is done in the trader's timezone (America/New_York by default),
using zoneinfo so DST is handled correctly — never a fixed UTC offset.
"""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

# --- Controlled vocabularies (used by forms, parser and DB) -------------------

PAIRS = ["EURUSD", "GBPUSD", "другое"]
DIRECTIONS = ["Long", "Short"]
SESSIONS = ["Asia", "London", "NY"]
ASIA_TYPES = ["consolidation", "expansion"]
SETUPS = ["LO reversal", "NY reversal", "NY continuation", "other"]
SWEEP_REFS = ["Asia High", "Asia Low", "PDH", "PDL", "session high", "session low", "other"]
OTE_LEVELS = ["0.62", "0.705", "0.79", "OB", "FVG"]
OUTCOMES = ["Win", "Loss", "Breakeven", "Missed", "No Trade"]
STATUSES = ["Open", "Closed"]
PLAN_FOLLOWED = ["По плану", "Частичное нарушение", "Нарушение"]
EMOTIONS = ["спокоен", "FOMO", "страх", "тильт", "уверенность", "скука"]
VIOLATION_TYPES = [
    "вход вне окна",
    "вторая попытка",
    "погоня за ценой",
    "нет sweep",
    "нет MSS",
    "ранний выход",
    "передержал",
    "превышен риск",
]

# --- Session windows (NY local time) -----------------------------------------
# start, end (end exclusive). Asia wraps past midnight → handled specially.
_SESSION_WINDOWS = {
    "Asia": (time(20, 0), time(0, 0)),
    "London": (time(2, 0), time(5, 0)),
    "NY": (time(7, 0), time(10, 0)),
}

# Silver Bullet windows (NY local time)
_SB_WINDOWS = [
    (time(3, 0), time(4, 0)),   # London Open SB
    (time(10, 0), time(11, 0)),  # NY AM SB
]


def now_ny(tz_name: str = "America/New_York") -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def _in_window(t: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= t < end
    # window wraps midnight (e.g. Asia 20:00 → 00:00)
    return t >= start or t < end


def classify_session(dt: datetime, tz_name: str = "America/New_York") -> str | None:
    """Return the ICT session name for a datetime, or None if outside all windows.

    The datetime is converted to the trader's timezone first.
    """
    local = dt.astimezone(ZoneInfo(tz_name))
    t = local.timetz().replace(tzinfo=None)
    for name, (start, end) in _SESSION_WINDOWS.items():
        if _in_window(t, start, end):
            return name
    return None


def in_silver_bullet(dt: datetime, tz_name: str = "America/New_York") -> bool:
    local = dt.astimezone(ZoneInfo(tz_name))
    t = local.timetz().replace(tzinfo=None)
    return any(_in_window(t, s, e) for s, e in _SB_WINDOWS)


def compute_rr(entry: float | None, stop_loss: float | None, take_profit: float | None) -> float | None:
    """Planned risk:reward = |TP - entry| / |entry - SL|. None if not computable."""
    if entry is None or stop_loss is None or take_profit is None:
        return None
    risk = abs(entry - stop_loss)
    if risk == 0:
        return None
    reward = abs(take_profit - entry)
    return round(reward / risk, 2)
