from datetime import datetime
from zoneinfo import ZoneInfo

from core.stats import compute_stats, format_stats

NY = ZoneInfo("America/New_York")


def _t(r, usd, session="NY", setup="NY reversal", pair="EURUSD", direction="Long", day=1, outcome=None):
    if outcome is None:
        outcome = "Win" if r > 0 else "Loss" if r < 0 else "Breakeven"
    return {
        "result_r": r, "result_usd": usd, "outcome": outcome, "status": "Closed",
        "session": session, "setup": setup, "pair": pair, "direction": direction,
        "trade_time": datetime(2026, 7, day, 8, 0, tzinfo=NY),
    }


def sample():
    return [
        _t(2.0, 200, day=1),
        _t(-1.0, -100, day=1),
        _t(1.0, 100, day=2, setup="LO reversal"),
        _t(-1.0, -100, day=3),
        _t(3.0, 300, day=4),
        {"status": "Open", "outcome": None, "result_r": None, "pair": "GBPUSD",
         "trade_time": datetime(2026, 7, 5, 8, 0, tzinfo=NY)},
        {"status": "Closed", "outcome": "Missed", "result_r": None,
         "trade_time": datetime(2026, 7, 5, 9, 0, tzinfo=NY)},
    ]


def test_core_counts_and_winrate():
    s = compute_stats(sample())
    assert s.total == 5
    assert s.wins == 3 and s.losses == 2 and s.breakeven == 0
    assert s.winrate == 0.6
    assert s.open_positions == 1
    assert s.missed == 1


def test_r_and_expectancy():
    s = compute_stats(sample())
    assert s.total_r == 4.0            # 2 -1 +1 -1 +3
    assert s.net_pnl == 400.0
    assert s.expectancy == 0.8         # 4 / 5
    assert s.avg_r == 0.8


def test_profit_factor_and_payoff():
    s = compute_stats(sample())
    # gross win 6R, gross loss 2R
    assert s.profit_factor == 3.0
    assert s.avg_win_r == 2.0          # (2+1+3)/3
    assert s.avg_loss_r == -1.0
    assert s.payoff_ratio == 2.0


def test_streaks_and_drawdown():
    s = compute_stats(sample())
    assert s.streak == 1               # last trade was a win
    assert s.max_win_streak == 1       # wins never chain 2 in a row here
    assert s.max_loss_streak == 1
    # equity: 2,1,2,1,4 -> max peak-to-trough drop = 1
    assert s.max_drawdown_r == 1.0
    assert s.recovery_factor == 4.0    # total_r / dd


def test_largest_and_days():
    s = compute_stats(sample())
    assert s.largest_win_r == 3.0
    assert s.largest_loss_r == -1.0
    assert s.trading_days == 4
    assert s.winning_days >= 2


def test_breakdowns_and_zella():
    s = compute_stats(sample())
    assert "NY reversal" in s.by_setup
    assert s.by_setup["NY reversal"]["count"] == 4
    assert "EURUSD" in s.by_pair
    assert 0 <= s.zella_score <= 100
    assert set(s.zella_breakdown) == {
        "win_rate", "profit_factor", "avg_win_loss", "max_drawdown",
        "recovery_factor", "consistency",
    }


def test_empty():
    s = compute_stats([])
    assert s.total == 0
    assert s.total_r == 0.0
    assert s.profit_factor is None or s.profit_factor == 0.0
    assert "Zella" in format_stats(s)


def test_no_losses_profit_factor_infinite():
    trades = [_t(1.0, 100, day=1), _t(2.0, 200, day=2)]
    s = compute_stats(trades)
    assert s.profit_factor is None     # rendered as ∞
    assert "∞" in format_stats(s)
