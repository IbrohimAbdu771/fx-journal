"""Trade analytics — TradeZella-style, adapted for an R-based forex/ICT journal.

Pure functions over a list of "trade" dicts. Storage-agnostic (the bot, the web
app and the tests all feed the same shape). A trade dict may contain:

    result_r:    float | None    # R-multiple result (primary metric)
    result_usd:  float | None    # $ result (optional)
    outcome:     str  | None     # Win / Loss / Breakeven / Missed / No Trade
    status:      str  | None     # Open / Closed
    session:     str  | None
    setup:       str  | None
    pair:        str  | None
    direction:   str  | None     # Long / Short
    trade_time:  datetime | None # used for ordering, streaks, daily & weekday stats

Only *counted* trades feed performance numbers: status == "Closed", outcome in
{Win, Loss, Breakeven}, and a numeric result_r. Missed / No Trade are tracked
separately (discipline), never in P&L.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

COUNTED_OUTCOMES = {"Win", "Loss", "Breakeven"}
WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


def _counted(trades: list[dict]) -> list[dict]:
    out = [
        t
        for t in trades
        if t.get("outcome") in COUNTED_OUTCOMES and isinstance(t.get("result_r"), (int, float))
    ]
    out.sort(key=lambda t: t.get("trade_time") or datetime.min)
    return out


def _r(t: dict) -> float:
    return t.get("result_r") or 0.0


def _usd(t: dict) -> float:
    return t.get("result_usd") or 0.0


# --------------------------------------------------------------------------- #
# result container
# --------------------------------------------------------------------------- #
@dataclass
class Stats:
    # counts
    total: int = 0
    wins: int = 0
    losses: int = 0
    breakeven: int = 0
    missed: int = 0
    no_trade: int = 0
    open_positions: int = 0
    # core performance
    winrate: float = 0.0            # 0..1
    total_r: float = 0.0
    net_pnl: float = 0.0            # $ over counted trades
    avg_r: float = 0.0
    expectancy: float = 0.0        # R/trade (== avg_r)
    std_r: float = 0.0             # population std of R
    sqn: float = 0.0               # System Quality Number = mean/std * sqrt(N)
    profit_factor: float | None = None
    # win/loss shape
    avg_win_r: float = 0.0
    avg_loss_r: float = 0.0
    payoff_ratio: float | None = None   # avg_win / |avg_loss|
    avg_win_usd: float = 0.0
    avg_loss_usd: float = 0.0
    largest_win_r: float = 0.0
    largest_loss_r: float = 0.0
    largest_win_usd: float = 0.0
    largest_loss_usd: float = 0.0
    # streaks
    streak: int = 0                # signed current streak
    max_win_streak: int = 0
    max_loss_streak: int = 0
    day_streak: int = 0            # signed current winning/losing-day streak
    # days
    trading_days: int = 0
    winning_days: int = 0
    losing_days: int = 0
    day_win_pct: float = 0.0
    avg_daily_r: float = 0.0
    avg_daily_pnl: float = 0.0
    # risk
    max_drawdown_r: float = 0.0
    max_drawdown_usd: float = 0.0
    recovery_factor: float | None = None
    zella_score: float = 0.0
    zella_breakdown: dict = field(default_factory=dict)
    # MAE / MFE (manual, optional) — each sub-aggregate carries its own sample size n
    mae_mfe: dict = field(default_factory=dict)
    # series & breakdowns
    equity_curve: list = field(default_factory=list)     # [{i, r_cum, usd_cum, time}]
    daily: list = field(default_factory=list)            # [{date, r, usd, trades, wins, losses}]
    r_distribution: dict = field(default_factory=dict)   # bucket -> count
    by_session: dict = field(default_factory=dict)
    by_setup: dict = field(default_factory=dict)
    by_pair: dict = field(default_factory=dict)
    by_direction: dict = field(default_factory=dict)
    by_weekday: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


# --------------------------------------------------------------------------- #
# building blocks
# --------------------------------------------------------------------------- #
def _current_streak(counted: list[dict]) -> int:
    streak = 0
    for t in reversed(counted):
        r = _r(t)
        if r > 0:
            if streak < 0:
                break
            streak += 1
        elif r < 0:
            if streak > 0:
                break
            streak -= 1
        else:
            break
    return streak


def _max_streaks(counted: list[dict]) -> tuple[int, int]:
    max_w = max_l = cur_w = cur_l = 0
    for t in counted:
        r = _r(t)
        if r > 0:
            cur_w += 1
            cur_l = 0
            max_w = max(max_w, cur_w)
        elif r < 0:
            cur_l += 1
            cur_w = 0
            max_l = max(max_l, cur_l)
        else:
            cur_w = cur_l = 0
    return max_w, max_l


def _drawdown(cumulative: list[float]) -> float:
    """Max peak-to-trough drop of a cumulative series (returns a positive number)."""
    peak = float("-inf")
    max_dd = 0.0
    for v in cumulative:
        peak = max(peak, v)
        max_dd = max(max_dd, peak - v)
    return round(max_dd, 2)


def _breakdown(counted: list[dict], key: str) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in counted:
        groups[t.get(key) or "—"].append(t)
    out = {}
    for name, rows in groups.items():
        wins = sum(1 for r in rows if _r(r) > 0)
        losses = sum(1 for r in rows if _r(r) < 0)
        decisive = wins + losses
        total_r = round(sum(_r(r) for r in rows), 2)
        out[name] = {
            "count": len(rows),
            "wins": wins,
            "losses": losses,
            "winrate": round(wins / decisive, 4) if decisive else 0.0,
            "total_r": total_r,
            "avg_r": round(total_r / len(rows), 2) if rows else 0.0,
            "total_usd": round(sum(_usd(r) for r in rows), 2),
        }
    return dict(sorted(out.items(), key=lambda kv: kv[1]["total_r"], reverse=True))


def _r_distribution(counted: list[dict]) -> dict:
    buckets = ["≤-3", "-3..-2", "-2..-1", "-1..0", "0..1", "1..2", "2..3", "≥3"]
    dist = {b: 0 for b in buckets}
    for t in counted:
        r = _r(t)
        if r <= -3:
            b = "≤-3"
        elif r < -2:
            b = "-3..-2"
        elif r < -1:
            b = "-2..-1"
        elif r < 0:
            b = "-1..0"
        elif r < 1:
            b = "0..1"
        elif r < 2:
            b = "1..2"
        elif r < 3:
            b = "2..3"
        else:
            b = "≥3"
        dist[b] += 1
    return dist


def _daily(counted: list[dict]) -> list[dict]:
    days: dict[str, dict] = {}
    for t in counted:
        dt = t.get("trade_time")
        key = dt.date().isoformat() if isinstance(dt, datetime) else "—"
        d = days.setdefault(key, {"date": key, "r": 0.0, "usd": 0.0, "trades": 0, "wins": 0, "losses": 0})
        d["r"] += _r(t)
        d["usd"] += _usd(t)
        d["trades"] += 1
        if _r(t) > 0:
            d["wins"] += 1
        elif _r(t) < 0:
            d["losses"] += 1
    for d in days.values():
        d["r"] = round(d["r"], 2)
        d["usd"] = round(d["usd"], 2)
    return [days[k] for k in sorted(days)]


def _day_streak(daily: list[dict]) -> int:
    streak = 0
    for d in reversed(daily):
        if d["r"] > 0:
            if streak < 0:
                break
            streak += 1
        elif d["r"] < 0:
            if streak > 0:
                break
            streak -= 1
        else:
            break
    return streak


# --------------------------------------------------------------------------- #
# MAE / MFE (manual excursions) — subsample-aware aggregates
# --------------------------------------------------------------------------- #
def _median(vals: list[float]) -> float | None:
    n = len(vals)
    if not n:
        return None
    s = sorted(vals)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def _agg(vals: list[float]) -> dict:
    """avg/median over a subsample; None (not 0) when the subsample is empty."""
    n = len(vals)
    return {
        "avg": round(sum(vals) / n, 2) if n else None,
        "median": round(_median(vals), 2) if n else None,
        "n": n,
    }


def _present(rows: list[dict], key: str) -> list[float]:
    """Values of `key` over rows where it is actually filled (None == not measured)."""
    return [t[key] for t in rows if isinstance(t.get(key), (int, float))]


def _mae_mfe(counted: list[dict]) -> dict:
    wins = [t for t in counted if _r(t) > 0]
    losses = [t for t in counted if _r(t) < 0]

    mae_win = _agg(_present(wins, "mae_r"))
    mae_loss = _agg(_present(losses, "mae_r"))
    mfe_win = _agg(_present(wins, "mfe_r"))
    mfe_loss = _agg(_present(losses, "mfe_r"))

    # Left on table: how much winners undershot their own max favorable excursion.
    lot_vals = [t["mfe_r"] - _r(t) for t in wins if isinstance(t.get("mfe_r"), (int, float))]
    left = {
        "avg": round(sum(lot_vals) / len(lot_vals), 2) if lot_vals else None,
        "n": len(lot_vals),
    }

    # Losers that were up >= 0.5R before the stop took them out.
    loser_mfe = _present(losses, "mfe_r")
    n_lm = len(loser_mfe)
    ge = sum(1 for v in loser_mfe if v >= 0.5)
    losers_ge = {
        "pct": round(ge / n_lm, 4) if n_lm else None,
        "count": ge,
        "n": n_lm,
    }

    has_data = bool(
        mae_win["n"] or mae_loss["n"] or mfe_win["n"] or mfe_loss["n"] or left["n"] or n_lm
    )
    return {
        "mae_win": mae_win, "mae_loss": mae_loss,
        "mfe_win": mfe_win, "mfe_loss": mfe_loss,
        "left_on_table": left, "losers_mfe_ge_05": losers_ge,
        "has_data": has_data,
    }


# --------------------------------------------------------------------------- #
# Zella-style composite score (our transparent approximation)
# --------------------------------------------------------------------------- #
def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _zella(s: Stats) -> tuple[float, dict]:
    """0–100 composite from 6 sub-scores (equal weight). Heuristic, not TZ's exact formula."""
    win = _clamp((s.winrate / 0.6) * 100)                      # 60% winrate -> 100
    pf = 100.0 if s.profit_factor is None else _clamp((s.profit_factor / 2.0) * 100)
    payoff = 100.0 if s.payoff_ratio is None else _clamp((s.payoff_ratio / 2.0) * 100)
    # drawdown relative to total profit: smaller dd vs profit -> higher score
    denom = abs(s.total_r) + s.max_drawdown_r
    dd = 100.0 if s.max_drawdown_r == 0 else _clamp((1 - s.max_drawdown_r / denom) * 100) if denom else 0.0
    rec = 100.0 if s.recovery_factor is None else _clamp((s.recovery_factor / 3.0) * 100)
    # consistency: how spread profit is across winning days (no single day dominating)
    win_days_r = [d["r"] for d in s.daily if d["r"] > 0]
    if win_days_r and sum(win_days_r) > 0:
        consistency = _clamp((1 - max(win_days_r) / sum(win_days_r)) * 100 + 20)
    else:
        consistency = 0.0
    breakdown = {
        "win_rate": round(win),
        "profit_factor": round(pf),
        "avg_win_loss": round(payoff),
        "max_drawdown": round(dd),
        "recovery_factor": round(rec),
        "consistency": round(consistency),
    }
    score = round(sum(breakdown.values()) / len(breakdown))
    return float(score), breakdown


# --------------------------------------------------------------------------- #
# main entry point
# --------------------------------------------------------------------------- #
def compute_stats(trades: list[dict]) -> Stats:
    counted = _counted(trades)
    s = Stats()
    s.open_positions = sum(1 for t in trades if t.get("status") == "Open")
    s.missed = sum(1 for t in trades if t.get("outcome") == "Missed")
    s.no_trade = sum(1 for t in trades if t.get("outcome") == "No Trade")

    s.total = len(counted)
    s.mae_mfe = _mae_mfe(counted)
    if not counted:
        s.zella_score, s.zella_breakdown = _zella(s)
        return s

    r_vals = [_r(t) for t in counted]
    usd_vals = [_usd(t) for t in counted]
    wins = [t for t in counted if _r(t) > 0]
    losses = [t for t in counted if _r(t) < 0]

    s.wins = len(wins)
    s.losses = len(losses)
    s.breakeven = sum(1 for t in counted if _r(t) == 0)
    decisive = s.wins + s.losses
    s.winrate = round(s.wins / decisive, 4) if decisive else 0.0

    s.total_r = round(sum(r_vals), 2)
    s.net_pnl = round(sum(usd_vals), 2)
    mean_r = sum(r_vals) / s.total
    s.avg_r = round(mean_r, 2)
    s.expectancy = s.avg_r

    # dispersion & System Quality Number (Van Tharp): mean/std * sqrt(N)
    if s.total > 1:
        variance = sum((r - mean_r) ** 2 for r in r_vals) / s.total
        std = variance ** 0.5
        s.std_r = round(std, 2)
        if std > 0:
            s.sqn = round((mean_r / std) * (s.total ** 0.5), 2)

    gross_win = sum(r for r in r_vals if r > 0)
    gross_loss = -sum(r for r in r_vals if r < 0)
    if gross_loss > 0:
        s.profit_factor = round(gross_win / gross_loss, 2)
    elif gross_win > 0:
        s.profit_factor = None  # no losses -> "infinite"
    else:
        s.profit_factor = 0.0

    s.avg_win_r = round(sum(_r(t) for t in wins) / len(wins), 2) if wins else 0.0
    s.avg_loss_r = round(sum(_r(t) for t in losses) / len(losses), 2) if losses else 0.0
    s.avg_win_usd = round(sum(_usd(t) for t in wins) / len(wins), 2) if wins else 0.0
    s.avg_loss_usd = round(sum(_usd(t) for t in losses) / len(losses), 2) if losses else 0.0
    if s.avg_loss_r != 0:
        s.payoff_ratio = round(s.avg_win_r / abs(s.avg_loss_r), 2)
    elif s.avg_win_r > 0:
        s.payoff_ratio = None

    s.largest_win_r = round(max(r_vals), 2)
    s.largest_loss_r = round(min(r_vals), 2)
    s.largest_win_usd = round(max(usd_vals), 2) if usd_vals else 0.0
    s.largest_loss_usd = round(min(usd_vals), 2) if usd_vals else 0.0

    s.streak = _current_streak(counted)
    s.max_win_streak, s.max_loss_streak = _max_streaks(counted)

    # equity curve (cumulative)
    r_cum = usd_cum = 0.0
    for i, t in enumerate(counted, start=1):
        r_cum += _r(t)
        usd_cum += _usd(t)
        dt = t.get("trade_time")
        s.equity_curve.append(
            {
                "i": i,
                "r_cum": round(r_cum, 2),
                "usd_cum": round(usd_cum, 2),
                "time": dt.isoformat() if isinstance(dt, datetime) else None,
            }
        )
    s.max_drawdown_r = _drawdown([p["r_cum"] for p in s.equity_curve])
    s.max_drawdown_usd = _drawdown([p["usd_cum"] for p in s.equity_curve])
    if s.max_drawdown_r > 0:
        s.recovery_factor = round(s.total_r / s.max_drawdown_r, 2) if s.total_r > 0 else 0.0
    elif s.total_r > 0:
        s.recovery_factor = None

    # daily
    s.daily = _daily(counted)
    s.trading_days = len(s.daily)
    s.winning_days = sum(1 for d in s.daily if d["r"] > 0)
    s.losing_days = sum(1 for d in s.daily if d["r"] < 0)
    decisive_days = s.winning_days + s.losing_days
    s.day_win_pct = round(s.winning_days / decisive_days, 4) if decisive_days else 0.0
    s.avg_daily_r = round(s.total_r / s.trading_days, 2) if s.trading_days else 0.0
    s.avg_daily_pnl = round(s.net_pnl / s.trading_days, 2) if s.trading_days else 0.0
    s.day_streak = _day_streak(s.daily)

    # breakdowns
    s.r_distribution = _r_distribution(counted)
    s.by_session = _breakdown(counted, "session")
    s.by_setup = _breakdown(counted, "setup")
    s.by_pair = _breakdown(counted, "pair")
    s.by_direction = _breakdown(counted, "direction")

    weekday_groups: dict[str, list[dict]] = defaultdict(list)
    for t in counted:
        dt = t.get("trade_time")
        if isinstance(dt, datetime):
            weekday_groups[WEEKDAYS[dt.weekday()]].append(t)
    by_wd = {}
    for name in WEEKDAYS:
        rows = weekday_groups.get(name)
        if rows:
            wins_wd = sum(1 for r in rows if _r(r) > 0)
            dec = wins_wd + sum(1 for r in rows if _r(r) < 0)
            by_wd[name] = {
                "count": len(rows),
                "winrate": round(wins_wd / dec, 4) if dec else 0.0,
                "total_r": round(sum(_r(r) for r in rows), 2),
            }
    s.by_weekday = by_wd

    s.zella_score, s.zella_breakdown = _zella(s)
    return s


# --------------------------------------------------------------------------- #
# Telegram text rendering
# --------------------------------------------------------------------------- #
def format_stats(s: Stats, title: str = "📊 Статистика") -> str:
    pf = "∞" if s.profit_factor is None else f"{s.profit_factor}"
    payoff = "∞" if s.payoff_ratio is None else f"{s.payoff_ratio}"
    rec = "∞" if s.recovery_factor is None else f"{s.recovery_factor}"
    streak_txt = "—"
    if s.streak > 0:
        streak_txt = f"{s.streak} ✅ подряд"
    elif s.streak < 0:
        streak_txt = f"{abs(s.streak)} ❌ подряд"

    lines = [
        title,
        "",
        f"Zella Score: {s.zella_score:.0f}/100",
        f"Сделок: {s.total}  |  ✅ {s.wins}  ❌ {s.losses}  ➖ {s.breakeven}",
        f"Winrate: {s.winrate * 100:.0f}%   Day win: {s.day_win_pct * 100:.0f}%",
        f"Total R: {s.total_r:+.2f}R   Net P&L: {s.net_pnl:+.2f}$",
        f"Expectancy: {s.expectancy:+.2f}R   Profit factor: {pf}   Payoff: {payoff}",
        f"Avg win/loss: {s.avg_win_r:+.2f}R / {s.avg_loss_r:+.2f}R",
        f"Max DD: {s.max_drawdown_r:.2f}R   Recovery: {rec}",
        f"SQN: {s.sqn}   Std R: {s.std_r}R",
        f"Серия: {streak_txt}   (max {s.max_win_streak}✅ / {s.max_loss_streak}❌)",
    ]
    if s.missed or s.no_trade or s.open_positions:
        lines.append(f"Открытых: {s.open_positions}   Missed: {s.missed}   No Trade: {s.no_trade}")
    if s.by_session:
        lines.append("\nПо сессиям:")
        for name, d in s.by_session.items():
            lines.append(f"  {name}: {d['count']} сд, WR {d['winrate'] * 100:.0f}%, {d['total_r']:+.2f}R")
    if s.by_setup:
        lines.append("\nПо сетапам:")
        for name, d in s.by_setup.items():
            lines.append(f"  {name}: {d['count']} сд, WR {d['winrate'] * 100:.0f}%, {d['total_r']:+.2f}R")
    return "\n".join(lines)
