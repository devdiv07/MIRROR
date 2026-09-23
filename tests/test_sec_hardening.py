"""
SEC adapter hardening (Step 3 follow-up): the declared User-Agent and one rate limit for every request.
Offline: HTTP is tests.support.FakeHttp; time is tests.support.FakeClock.
"""

import io
from datetime import date, timedelta

import pytest

from src import cli
from src.sources.sec_submissions import FILE_URL, MIN_REQUEST_INTERVAL, MissingUserAgent, ingest_sec
from src.store import db
from tests.support import NOW, FakeClock, FakeHttp, cik_url, new_store, us_securities

T = db.utc_iso

MANY_WATCHLIST = """version: 1
securities:
  - key: US:NYSE:TMF
    exchange: NYSE
    name: Test Many Files Co
    cik: 7777
    symbols:
      - {symbol: TMF, valid_from: 2026-01-01}
"""


def _ingest(conn, http, clock, now=NOW, since=None):
    return ingest_sec(conn, us_securities(conn), now=now, since=since, get=http,
                      sleep=clock.sleep, monotonic=clock.monotonic)


def _columns(filings):
    """[(accession, filing_date, form)] -> SEC's columnar layout."""
    return {
        'accessionNumber': [a for a, _, _ in filings],
        'filingDate': [d for _, d, _ in filings],
        'reportDate': ['' for _ in filings],
        'acceptanceDateTime': [f'{d}T20:00:00.000Z' for _, d, _ in filings],
        'form': [f for _, _, f in filings],
        'items': ['8.01' if f == '8-K' else '' for _, _, f in filings],
        'primaryDocument': [f'doc-{a}.htm' for a, _, _ in filings],
        'primaryDocDescription': [f for _, _, f in filings],
    }


def many_file_company(n_files: int):
    """CIK 7777: `recent` from 2026-01-05, and n_files contiguous older files back to 2025-01-01,
    each holding one 8-K. Returns (routes for FakeHttp, list of file URLs, since)."""
    first, last = date(2025, 1, 1), date(2026, 1, 5)
    step = (last - first).days // n_files
    starts = [first + timedelta(days=step * k) for k in range(n_files)] + [last + timedelta(days=1)]
    files, routes = [], {}
    for k in range(n_files):
        lo, hi = starts[k], starts[k + 1] - timedelta(days=1)
        name = f'CIK0000007777-submissions-{k + 1:03d}.json'
        files.append({'name': name, 'filingCount': 1, 'filingFrom': lo.isoformat(), 'filingTo': hi.isoformat()})
        routes[FILE_URL.format(name=name)] = [_columns([(f'0000007777-25-{k + 1:06d}', (lo + timedelta(days=1)).isoformat(), '8-K')])]
    submissions = {'cik': '7777', 'name': 'TEST MANY FILES CO', 'filings': {
        'recent': _columns([('0000007777-26-000009', '2026-08-04', '10-Q'),
                            ('0000007777-26-000001', '2026-01-05', '8-K')]),
        'files': files[::-1]}}                       # SEC lists the newest file first
    routes[cik_url('7777')] = [submissions]
    return routes, [FILE_URL.format(name=f['name']) for f in files], NOW.replace(year=2025, month=1, day=1, hour=6)


def _gaps(starts):
    return [b - a for a, b in zip(starts, starts[1:])]


# ── User-Agent ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize('value', [None, '', '   ', 'MIRROR research tool'])
def test_ingest_refuses_to_start_without_a_declared_contact(tmp_path, monkeypatch, value):
    if value is None:
        monkeypatch.delenv('SEC_USER_AGENT')
    else:
        monkeypatch.setenv('SEC_USER_AGENT', value)
    conn = new_store(tmp_path)
    http = FakeHttp()
    with pytest.raises(MissingUserAgent, match='SEC_USER_AGENT'):
        _ingest(conn, http, FakeClock())
    assert http.calls == []                                              # nothing was sent
    assert conn.execute('SELECT COUNT(*) FROM ingest_run').fetchone()[0] == 0
    assert conn.execute('SELECT COUNT(*) FROM coverage_check').fetchone()[0] == 0   # not a source failure


def test_cli_ingest_without_user_agent_exits_with_a_clear_message(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv('SEC_USER_AGENT')
    (tmp_path / 'w.yaml').write_text(MANY_WATCHLIST, encoding='utf-8')
    http = FakeHttp()
    code = cli.main(['--db', str(tmp_path / 'm.sqlite3'), 'ingest', '--watchlist', str(tmp_path / 'w.yaml'),
                     '--manual-events', 'none.csv'], now=NOW, out=io.StringIO(), http_get=http)
    assert code == 2 and http.calls == []
    assert 'SEC_USER_AGENT is not set' in capsys.readouterr().err


# ── one rate limit for every request ─────────────────────────────────────────

def test_many_file_backfill_paces_every_request_including_retries(tmp_path):
    routes, file_urls, since = many_file_company(6)
    routes[file_urls[2]] = [503, 429] + routes[file_urls[2]]           # two retries on one file
    conn = new_store(tmp_path, MANY_WATCHLIST)
    clock = FakeClock()
    http = FakeHttp(routes, clock=clock)

    report = _ingest(conn, http, clock, since=since)

    assert report.checks['US:NYSE:TMF'] == ('ok', None)
    assert len(http.calls) == 1 + 6 + 2
    assert sorted(set(http.calls[1:])) == sorted(file_urls)
    assert min(_gaps(http.starts)) >= MIN_REQUEST_INTERVAL
    n_events = conn.execute('SELECT COUNT(*) FROM event').fetchone()[0]
    assert n_events == 6 + 2                                             # one 8-K per file + recent


def test_rate_limit_spans_companies_and_fast_responses(tmp_path):
    conn = new_store(tmp_path)                                           # three CIKs, instant responses
    clock = FakeClock()
    http = FakeHttp(clock=clock)
    _ingest(conn, http, clock)
    assert len(http.starts) == 3
    assert min(_gaps(http.starts)) >= MIN_REQUEST_INTERVAL


def test_slow_responses_are_not_delayed_further(tmp_path):
    conn = new_store(tmp_path)
    clock = FakeClock()
    http = FakeHttp(clock=clock, latency=2.0)                            # each request takes 2 s
    _ingest(conn, http, clock)
    assert clock.sleeps == []                                            # the interval had already passed
