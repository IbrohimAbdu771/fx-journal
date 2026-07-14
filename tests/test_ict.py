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


def test_dst_boundaries_wall_clock():
    # Sessions are anchored to NY wall-clock, so the same local time classifies
    # the same in summer (EDT) and winter (EST). US DST 2026: Mar 8 – Nov 1.
    assert ict.classify_session(datetime(2026, 7, 15, 2, 30, tzinfo=NY)) == "London"   # EDT
    assert ict.classify_session(datetime(2026, 1, 15, 2, 30, tzinfo=NY)) == "London"   # EST
    assert ict.in_silver_bullet(datetime(2026, 7, 15, 3, 30, tzinfo=NY)) is True
    assert ict.in_silver_bullet(datetime(2026, 1, 15, 3, 30, tzinfo=NY)) is True


def test_dst_utc_instant_maps_to_ny():
    UTC = ZoneInfo("UTC")
    # London open 02:00 NY: 06:00 UTC in EDT, 07:00 UTC in EST
    assert ict.classify_session(datetime(2026, 7, 15, 6, 0, tzinfo=UTC)) == "London"
    assert ict.classify_session(datetime(2026, 1, 15, 7, 0, tzinfo=UTC)) == "London"
    # NY open 07:00 NY: 11:00 UTC in EDT, 12:00 UTC in EST
    assert ict.classify_session(datetime(2026, 7, 15, 11, 0, tzinfo=UTC)) == "NY"
    assert ict.classify_session(datetime(2026, 1, 15, 12, 0, tzinfo=UTC)) == "NY"


def test_session_edges_inclusive_exclusive():
    assert ict.classify_session(datetime(2026, 7, 15, 2, 0, tzinfo=NY)) == "London"  # start inclusive
    assert ict.classify_session(datetime(2026, 7, 15, 5, 0, tzinfo=NY)) is None      # end exclusive
    # around the spring-forward night (Mar 8 2026) — 01:30 is still Asia, 02:30... actually
    # 02:00–02:59 does not exist locally on spring-forward; guard both real neighbours:
    assert ict.classify_session(datetime(2026, 3, 8, 3, 30, tzinfo=NY)) == "London"
