from datetime import datetime
from zoneinfo import ZoneInfo

from core import ict

NY = ZoneInfo("America/New_York")


def at(h, m=0):
    return datetime(2026, 7, 14, h, m, tzinfo=NY)


def test_sessions():
    assert ict.classify_session(at(8)) == "NY"
    assert ict.classify_session(at(3)) == "London"
    assert ict.classify_session(at(21)) == "Asia"
    assert ict.classify_session(at(23, 30)) == "Asia"   # wraps midnight
    assert ict.classify_session(at(12)) is None


def test_silver_bullet():
    assert ict.in_silver_bullet(at(3, 30)) is True      # LO SB 03-04
    assert ict.in_silver_bullet(at(10, 30)) is True     # NY AM SB 10-11
    assert ict.in_silver_bullet(at(9, 0)) is False


def test_compute_rr():
    assert ict.compute_rr(1.1000, 1.0950, 1.1100) == 2.0
    assert ict.compute_rr(1.1000, 1.1000, 1.1100) is None   # zero risk
    assert ict.compute_rr(None, 1.0, 1.1) is None


def test_tz_conversion_from_utc():
    utc = datetime(2026, 7, 14, 12, 0, tzinfo=ZoneInfo("UTC"))  # 08:00 EDT
    assert ict.classify_session(utc) == "NY"
