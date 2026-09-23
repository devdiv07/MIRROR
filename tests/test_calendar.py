"""
Exchange calendar tests (ADR 0001 §7, FOCUS Step 2).

Logic tests use a small synthetic config written to tmp_path. The last group
checks a few dates in the real config/exchanges.yaml against the primary
sources cited there, so an accidental edit to those files is caught.
"""

from datetime import date, datetime, time, timezone
from pathlib import Path

import pytest

from src.core.calendar import (
    CalendarConfigError, CalendarNotCovered, load_calendars,
)

ROOT = Path(__file__).resolve().parents[1]
REAL_CONFIG = ROOT / 'config' / 'exchanges.yaml'

UTC = timezone.utc

_EXCHANGES = """
exchanges:
  TSTUS:
    market: US
    timezone: America/New_York
    currency: USD
    regular_session: {open: "09:30", close: "16:00"}
    weekend: [Sat, Sun]
    holidays_file: TSTUS.csv
    years_covered: [2026]
    sources: [{what: test, url: https://example.test/us}]
  TSTIN:
    market: IN
    timezone: Asia/Kolkata
    currency: INR
    regular_session: {open: "09:15", close: "15:30"}
    weekend: [Sat, Sun]
    holidays_file: TSTIN.csv
    years_covered: [2026]
    sources: [{what: test, url: https://example.test/in}]
"""

_US_ROWS = """date,status,open,close,description,source
2026-07-03,closed,,,Independence Day (observed),https://example.test/us
2026-11-27,early_close,,13:00,Day after Thanksgiving,https://example.test/us
"""

_IN_ROWS = """date,status,open,close,description,source
2026-01-26,closed,,,Republic Day,https://example.test/in
2026-02-01,special,09:15,15:30,Sunday budget session,https://example.test/in
2026-11-08,special,,,Muhurat - timings not notified,https://example.test/in
"""


def _write_config(tmp_path, us_rows=_US_ROWS, in_rows=_IN_ROWS, exchanges=_EXCHANGES):
    (tmp_path / 'exchanges.yaml').write_text(exchanges, encoding='utf-8')
    (tmp_path / 'TSTUS.csv').write_text(us_rows, encoding='utf-8')
    (tmp_path / 'TSTIN.csv').write_text(in_rows, encoding='utf-8')
    return str(tmp_path / 'exchanges.yaml')


@pytest.fixture
def cals(tmp_path):
    return load_calendars(_write_config(tmp_path))


# ── Logic ────────────────────────────────────────────────────────────────────

def test_weekend_is_closed(cals):
    assert cals['TSTUS'].session(date(2026, 7, 4)) is None          # Saturday
    assert cals['TSTUS'].closure_reason(date(2026, 7, 5)) == 'weekend'


def test_holiday_is_closed_with_reason(cals):
    us = cals['TSTUS']
    assert us.session(date(2026, 7, 3)) is None
    assert us.closure_reason(date(2026, 7, 3)) == 'Independence Day (observed)'
    assert us.closure_reason(date(2026, 7, 2)) is None


def test_regular_session_times_and_utc_conversion_across_dst(cals):
    us = cals['TSTUS']
    winter = us.session(date(2026, 1, 15))
    summer = us.session(date(2026, 7, 15))
    assert winter.kind == summer.kind == 'regular'
    assert winter.close_utc() == datetime(2026, 1, 15, 21, 0, tzinfo=UTC)   # EST, UTC-5
    assert summer.close_utc() == datetime(2026, 7, 15, 20, 0, tzinfo=UTC)   # EDT, UTC-4
    assert summer.open_utc() == datetime(2026, 7, 15, 13, 30, tzinfo=UTC)


def test_india_session_in_utc(cals):
    s = cals['TSTIN'].session(date(2026, 1, 27))
    assert s.open_utc() == datetime(2026, 1, 27, 3, 45, tzinfo=UTC)   # 09:15 IST
    assert s.close_utc() == datetime(2026, 1, 27, 10, 0, tzinfo=UTC)  # 15:30 IST


def test_early_close_keeps_regular_open(cals):
    s = cals['TSTUS'].session(date(2026, 11, 27))
    assert s.kind == 'early_close'
    assert s.open_local == time(9, 30) and s.close_local == time(13, 0)
    assert s.close_utc() == datetime(2026, 11, 27, 18, 0, tzinfo=UTC)


def test_special_weekend_session_with_times(cals):
    s = cals['TSTIN'].session(date(2026, 2, 1))   # a Sunday
    assert s is not None and s.kind == 'special' and s.times_known
    assert s.close_local == time(15, 30)


def test_special_session_with_unpublished_times(cals):
    s = cals['TSTIN'].session(date(2026, 11, 8))  # a Sunday
    assert s is not None and s.kind == 'special'
    assert not s.times_known
    assert s.open_utc() is None and s.close_utc() is None


def test_uncovered_year_raises_instead_of_assuming_open(cals):
    with pytest.raises(CalendarNotCovered):
        cals['TSTUS'].session(date(2027, 1, 4))
    with pytest.raises(CalendarNotCovered):
        cals['TSTUS'].previous_session(date(2026, 1, 1))   # walks back into 2025


def test_previous_session_skips_weekend_and_holiday(cals):
    # Monday 2026-07-06: Sunday, Saturday and holiday Friday 07-03 are skipped.
    assert cals['TSTUS'].previous_session(date(2026, 7, 6)).day == date(2026, 7, 2)


def test_sessions_between_counts_special_and_skips_closed(cals):
    days = [s.day for s in cals['TSTIN'].sessions_between(date(2026, 1, 24), date(2026, 2, 2))]
    assert date(2026, 1, 26) not in days            # holiday
    assert date(2026, 1, 25) not in days            # Sunday
    assert date(2026, 2, 1) in days                 # special Sunday session
    assert days == sorted(days)


# ── Config validation ────────────────────────────────────────────────────────

@pytest.mark.parametrize('bad_row, message', [
    ('2026-07-04,closed,,,Saturday holiday,https://example.test/us', 'weekend'),
    ('2027-01-01,closed,,,Out of range,https://example.test/us', 'years_covered'),
    ('2026-07-06,closed,,,No source,', 'source'),
    ('2026-07-06,early_close,,17:00,After regular close,https://example.test/us', 'inside the regular session'),
    ('2026-07-06,special,10:00,12:00,Weekday special,https://example.test/us', 'normal weekday'),
    ('2026-07-06,shut,,,Unknown status,https://example.test/us', 'status'),
])
def test_invalid_holiday_rows_are_rejected(tmp_path, bad_row, message):
    rows = _US_ROWS + bad_row + '\n'
    with pytest.raises(CalendarConfigError, match=message):
        load_calendars(_write_config(tmp_path, us_rows=rows))


def test_duplicate_holiday_date_rejected(tmp_path):
    rows = _US_ROWS + '2026-07-03,closed,,,Again,https://example.test/us\n'
    with pytest.raises(CalendarConfigError, match='duplicate'):
        load_calendars(_write_config(tmp_path, us_rows=rows))


def test_exchange_without_https_source_rejected(tmp_path):
    exchanges = _EXCHANGES.replace('url: https://example.test/us', 'url: not-a-url')
    with pytest.raises(CalendarConfigError, match='source'):
        load_calendars(_write_config(tmp_path, exchanges=exchanges))


# ── Real config: spot checks against the cited primary sources ───────────────

@pytest.fixture(scope='module')
def real():
    return load_calendars(str(REAL_CONFIG))


def test_real_config_loads_all_exchanges(real):
    assert set(real) == {'NSE', 'NYSE', 'NASDAQ'}
    assert real['NSE'].tz.key == 'Asia/Kolkata'
    assert real['NYSE'].tz.key == real['NASDAQ'].tz.key == 'America/New_York'


def test_real_nse_2026(real):
    nse = real['NSE']
    assert nse.closure_reason(date(2026, 1, 26)) == 'Republic Day'                       # NSE/CMTR/71775
    assert nse.closure_reason(date(2026, 1, 15)).startswith('Municipal Corporation')     # NSE/CMTR/72260
    budget = nse.session(date(2026, 2, 1))                                               # NSE/CMTR/72349
    assert budget.kind == 'special' and budget.close_local == time(15, 30)
    assert not nse.session(date(2026, 11, 8)).times_known                                # Muhurat, times TBA
    assert nse.session(date(2026, 1, 27)).kind == 'regular'
    assert len([d for d, r in nse._rows.items() if r.status == 'closed']) == 16          # 15 + 1 added


def test_real_us_2026(real):
    for code in ('NYSE', 'NASDAQ'):
        cal = real[code]
        assert cal.session(date(2026, 7, 3)) is None                                     # Independence Day observed
        assert cal.session(date(2026, 11, 27)).close_utc() == datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
        assert cal.session(date(2026, 12, 24)).kind == 'early_close'
        assert cal.session(date(2026, 12, 25)) is None


def test_real_coverage_differs_by_exchange(real):
    assert real['NYSE'].session(date(2027, 3, 26)) is None                               # Good Friday 2027
    with pytest.raises(CalendarNotCovered):
        real['NASDAQ'].session(date(2027, 3, 26))                                        # Nasdaq lists 2026 only
    with pytest.raises(CalendarNotCovered):
        real['NSE'].session(date(2027, 1, 26))
