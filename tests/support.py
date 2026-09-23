"""Shared helpers for the Milestone 2 tests: an offline HTTP fake and a small watchlist."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from src.core.calendar import load_calendars
from src.core.identity import load_watchlist, parse_watchlist
from src.sources.sec_submissions import FILE_URL, SUBMISSIONS_URL
from src.store import db

ROOT = Path(__file__).resolve().parents[1]
SEC_FIXTURES = ROOT / 'tests' / 'fixtures' / 'sec'
CALENDARS = load_calendars(str(ROOT / 'config' / 'exchanges.yaml'))

NOW = datetime(2026, 9, 23, 1, 0, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
TEST_USER_AGENT = 'MIRROR-tests tests@example.invalid'     # set for every test by tests/conftest.py

WATCHLIST = """version: 1
securities:
  - key: IN:NSE:TESTIN
    exchange: NSE
    name: Test India Ltd
    symbols:
      - {symbol: TSTIN, valid_from: 2026-01-01}
  - key: US:NASDAQ:TDCA
    exchange: NASDAQ
    name: Test Dual Class Inc (Class A)
    cik: 1234
    symbols:
      - {symbol: TDCA, valid_from: 2026-01-01}
  - key: US:NASDAQ:TDCB
    exchange: NASDAQ
    name: Test Dual Class Inc (Class B)
    cik: 1234
    symbols:
      - {symbol: TDCB, valid_from: 2026-01-01}
  - key: US:NYSE:TQC
    exchange: NYSE
    name: Test Quiet Corp
    cik: 5678
    symbols:
      - {symbol: TQC, valid_from: 2026-01-01}
  - key: US:NYSE:TLH
    exchange: NYSE
    name: Test Long History Co
    cik: 4242
    symbols:
      - {symbol: TLH, valid_from: 2026-01-01}
"""


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, BadJson):
            raise requests.exceptions.JSONDecodeError('Expecting value', self._payload.body, 0)
        return self._payload


class BadJson:
    """A FakeHttp outcome: HTTP 200 whose body is not JSON (e.g. an HTML error page or a truncation)."""

    def __init__(self, body='<html>Request Rate Threshold Exceeded</html>'):
        self.body = body


class FakeClock:
    """Offline time. monotonic() is seconds since `start`; sleep() advances it; now() is the wall clock."""

    def __init__(self, start=NOW):
        self.start, self.t, self.sleeps = start, 0.0, []

    def monotonic(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds

    def now(self):
        return self.start + timedelta(seconds=self.t)


class FakeHttp:
    """requests.get stand-in. A route is a list of outcomes consumed in order (the last repeats):
    an int status, a fixture file name (served with 200), a dict payload, or an exception instance.

    With a FakeClock, each request's start time is recorded in `starts`, and the clock advances by
    `latency` seconds while the request is "in flight"."""

    def __init__(self, overrides=None, clock=None, latency=0.0):
        self.routes = {}
        for path in SEC_FIXTURES.glob('CIK*.json'):
            name = path.name
            if '-submissions-' in name:
                url = FILE_URL.format(name=name)
            else:
                url = SUBMISSIONS_URL.format(cik=name[3:13])
            self.routes[url] = [name]
        self.routes.update(overrides or {})
        self.calls, self.starts = [], []
        self.clock, self.latency = clock, latency

    def __call__(self, url, headers=None, timeout=None):
        assert headers and headers.get('User-Agent') == TEST_USER_AGENT and timeout
        self.calls.append(url)
        if self.clock is not None:
            self.starts.append(self.clock.t)
            self.clock.t += self.latency
        outcomes = self.routes.get(url, [404])
        outcome = outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, int):
            return FakeResponse(outcome)
        if not isinstance(outcome, str):                 # a payload: dict, list, BadJson, ...
            return FakeResponse(200, outcome)
        return FakeResponse(200, json.loads((SEC_FIXTURES / outcome).read_text(encoding='utf-8')))


def cik_url(cik: str) -> str:
    return SUBMISSIONS_URL.format(cik=cik.zfill(10))


def fixture(name: str) -> dict:
    return json.loads((SEC_FIXTURES / name).read_text(encoding='utf-8'))


def new_store(tmp_path, watchlist: str = WATCHLIST, now=NOW):
    conn = db.connect(':memory:')
    path = tmp_path / 'watchlist.yaml'
    path.write_text(watchlist, encoding='utf-8')
    load_watchlist(conn, parse_watchlist(str(path), CALENDARS), now=now)
    return conn


def us_securities(conn):
    return conn.execute("SELECT * FROM security WHERE market = 'US' ORDER BY security_key").fetchall()


def sid(conn, key):
    return conn.execute('SELECT security_id FROM security WHERE security_key = ?', (key,)).fetchone()[0]


def no_sleep(_seconds):
    pass

