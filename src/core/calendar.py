"""
Exchange trading calendar.

Answers "was exchange X open on day D, and when did its regular session open and
close?" from config/exchanges.yaml plus one holiday CSV per exchange. Every
configured value cites a primary source (see the YAML).

Design rules (ADR 0001 §5, §7):
  - Coverage is explicit. A day in a year the config does not cover raises
    CalendarNotCovered; the calendar never assumes "no holidays".
  - Only the regular session is modelled. Holiday rows are 'closed',
    'early_close' (regular open, earlier close) or 'special' (a session on a
    normally closed day, e.g. NSE's Sunday Budget session). A special session
    whose timings are not yet published has open/close = None.
  - Times are exchange-local wall-clock times; open_utc()/close_utc() convert
    with zoneinfo, so DST is handled for America/New_York.

Usage:
    from src.core.calendar import load_calendars
    cals = load_calendars()
    cals['NYSE'].session(date(2026, 11, 27)).close_utc()   # early close, 18:00 UTC
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import yaml

DEFAULT_CONFIG_PATH = os.path.join('config', 'exchanges.yaml')

_WEEKDAYS = {'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3, 'Fri': 4, 'Sat': 5, 'Sun': 6}
_STATUSES = {'closed', 'early_close', 'special'}


class CalendarNotCovered(LookupError):
    """The requested day falls in a year the exchange's holiday list does not cover."""


class CalendarConfigError(ValueError):
    """exchanges.yaml or a holiday CSV is malformed or inconsistent."""


@dataclass(frozen=True)
class Session:
    exchange: str
    day: date
    kind: str                     # 'regular' | 'early_close' | 'special'
    open_local: time | None       # None only for a special session with unpublished times
    close_local: time | None
    tz: ZoneInfo
    description: str = ''
    source: str = ''

    @property
    def times_known(self) -> bool:
        return self.open_local is not None and self.close_local is not None

    def open_utc(self) -> datetime | None:
        return _to_utc(self.day, self.open_local, self.tz)

    def close_utc(self) -> datetime | None:
        return _to_utc(self.day, self.close_local, self.tz)


@dataclass(frozen=True)
class _HolidayRow:
    status: str
    open_local: time | None
    close_local: time | None
    description: str
    source: str


class ExchangeCalendar:
    """Trading calendar for one exchange. Build it with load_calendars()."""

    def __init__(self, code: str, market: str, tz: ZoneInfo, currency: str,
                 regular_open: time, regular_close: time, weekend: set[int],
                 years_covered: set[int], rows: dict[date, _HolidayRow]):
        self.code = code
        self.market = market
        self.tz = tz
        self.currency = currency
        self.regular_open = regular_open
        self.regular_close = regular_close
        self.weekend = weekend
        self.years_covered = years_covered
        self._rows = rows

    def _check_covered(self, day: date) -> None:
        if day.year not in self.years_covered:
            raise CalendarNotCovered(
                f"{self.code} holidays are not configured for {day.year} "
                f"(covered: {sorted(self.years_covered)}). Add them from the "
                f"exchange's own publication to config/holidays/ and cite the source."
            )

    def session(self, day: date) -> Session | None:
        """The regular session on `day`, or None if the exchange was closed."""
        self._check_covered(day)
        row = self._rows.get(day)
        if row is not None:
            if row.status == 'closed':
                return None
            if row.status == 'early_close':
                return Session(self.code, day, 'early_close', self.regular_open,
                               row.close_local, self.tz, row.description, row.source)
            return Session(self.code, day, 'special', row.open_local,
                           row.close_local, self.tz, row.description, row.source)
        if day.weekday() in self.weekend:
            return None
        return Session(self.code, day, 'regular', self.regular_open,
                       self.regular_close, self.tz)

    def is_trading_day(self, day: date) -> bool:
        return self.session(day) is not None

    def closure_reason(self, day: date) -> str | None:
        """Why the exchange was closed on `day` ('weekend' or the holiday name); None if open."""
        if self.session(day) is not None:
            return None
        row = self._rows.get(day)
        return row.description if row is not None else 'weekend'

    def sessions_between(self, start: date, end: date) -> list[Session]:
        """All sessions with start <= day <= end, in order."""
        out = []
        day = start
        while day <= end:
            s = self.session(day)
            if s is not None:
                out.append(s)
            day += timedelta(days=1)
        return out

    def previous_session(self, day: date) -> Session:
        """The last session strictly before `day`. Raises CalendarNotCovered past the covered years."""
        probe = day - timedelta(days=1)
        while True:
            s = self.session(probe)
            if s is not None:
                return s
            probe -= timedelta(days=1)


def _to_utc(day: date, t: time | None, tz: ZoneInfo) -> datetime | None:
    if t is None:
        return None
    return datetime.combine(day, t, tzinfo=tz).astimezone(ZoneInfo('UTC'))


def _parse_time(value: str, where: str) -> time:
    try:
        return datetime.strptime(value.strip(), '%H:%M').time()
    except (ValueError, AttributeError) as e:
        raise CalendarConfigError(f"{where}: expected HH:MM, got {value!r}") from e


def _load_rows(path: str, weekend: set[int], years: set[int],
               regular_open: time, regular_close: time) -> dict[date, _HolidayRow]:
    rows: dict[date, _HolidayRow] = {}
    with open(path, newline='', encoding='utf-8') as f:
        for n, rec in enumerate(csv.DictReader(f), start=2):
            where = f"{path}:{n}"
            try:
                day = date.fromisoformat(rec['date'].strip())
            except (ValueError, KeyError, AttributeError) as e:
                raise CalendarConfigError(f"{where}: bad date {rec.get('date')!r}") from e
            status = (rec.get('status') or '').strip()
            description = (rec.get('description') or '').strip()
            source = (rec.get('source') or '').strip()
            if status not in _STATUSES:
                raise CalendarConfigError(f"{where}: status must be one of {sorted(_STATUSES)}")
            if not description or not source.startswith('https://'):
                raise CalendarConfigError(f"{where}: every row needs a description and an https source")
            if day in rows:
                raise CalendarConfigError(f"{where}: duplicate date {day}")
            if day.year not in years:
                raise CalendarConfigError(f"{where}: {day} is outside years_covered {sorted(years)}")
            is_weekend = day.weekday() in weekend
            if status in ('closed', 'early_close') and is_weekend:
                raise CalendarConfigError(f"{where}: {status} row on a weekend day {day}")
            if status == 'special' and not is_weekend:
                raise CalendarConfigError(f"{where}: special session on a normal weekday {day}")

            open_raw = (rec.get('open') or '').strip()
            close_raw = (rec.get('close') or '').strip()
            open_t = _parse_time(open_raw, where) if open_raw else None
            close_t = _parse_time(close_raw, where) if close_raw else None
            if status == 'closed' and (open_t or close_t):
                raise CalendarConfigError(f"{where}: closed rows take no times")
            if status == 'early_close':
                if open_t is not None or close_t is None:
                    raise CalendarConfigError(f"{where}: early_close needs only a close time")
                if not (regular_open < close_t < regular_close):
                    raise CalendarConfigError(f"{where}: early close {close_t} not inside the regular session")
            if status == 'special' and (open_t is None) != (close_t is None):
                raise CalendarConfigError(f"{where}: special session needs both times or neither")
            if open_t is not None and close_t is not None and not open_t < close_t:
                raise CalendarConfigError(f"{where}: open must be before close")
            rows[day] = _HolidayRow(status, open_t, close_t, description, source)
    return rows


def load_calendars(config_path: str = DEFAULT_CONFIG_PATH) -> dict[str, ExchangeCalendar]:
    """Load and validate every exchange in config_path. Holiday files resolve relative to it."""
    with open(config_path, encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict) or not isinstance(cfg.get('exchanges'), dict):
        raise CalendarConfigError(f"{config_path}: expected a top-level 'exchanges' mapping")

    base = os.path.dirname(config_path)
    calendars: dict[str, ExchangeCalendar] = {}
    for code, ex in cfg['exchanges'].items():
        where = f"{config_path}: {code}"
        try:
            tz = ZoneInfo(ex['timezone'])
            session = ex['regular_session']
            regular_open = _parse_time(session['open'], where)
            regular_close = _parse_time(session['close'], where)
            weekend = {_WEEKDAYS[d] for d in ex['weekend']}
            years = {int(y) for y in ex['years_covered']}
            holidays_path = os.path.join(base, ex['holidays_file'])
            market, currency = ex['market'], ex['currency']
            sources = ex['sources']
        except (KeyError, TypeError) as e:
            raise CalendarConfigError(f"{where}: missing or malformed field ({e})") from e
        if not sources or not all(str(s.get('url', '')).startswith('https://') for s in sources):
            raise CalendarConfigError(f"{where}: at least one https source is required")
        if not regular_open < regular_close:
            raise CalendarConfigError(f"{where}: regular session open must be before close")
        rows = _load_rows(holidays_path, weekend, years, regular_open, regular_close)
        calendars[code] = ExchangeCalendar(code, market, tz, currency, regular_open,
                                           regular_close, weekend, years, rows)
    return calendars
