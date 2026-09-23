"""
SEC adapter hardening (Step 3 follow-up): the declared User-Agent, one rate limit for every request,
and invalid responses recorded as failures.
Offline: HTTP is tests.support.FakeHttp; time is tests.support.FakeClock.
"""

import copy
import io
from datetime import date, timedelta

import pytest

from src import cli
from src.core.coverage import coverage
from src.sources import sec_submissions
from src.sources.sec_submissions import (
    _DOCUMENT, FILE_URL, MIN_REQUEST_INTERVAL, MissingUserAgent, ingest_sec,
)
from src.store import db
from tests.support import (
    HOUR, NOW, BadJson, FakeClock, FakeHttp, cik_url, fixture, new_store, sid, us_securities,
)

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


# ── invalid responses are recorded failures, never complete coverage ────────

def _cov(conn, key, start, end, as_of=None):
    return coverage(conn, security_id=sid(conn, key), source='SEC_EDGAR', window_start=start,
                    window_end=end, as_of=as_of or end)


def test_malformed_json_on_submissions_is_a_recorded_failure(tmp_path):
    conn = new_store(tmp_path)
    clock = FakeClock()
    http = FakeHttp({cik_url('5678'): [BadJson()]}, clock=clock)
    report = _ingest(conn, http, clock)

    assert http.calls.count(cik_url('5678')) == 3                        # retried like a 5xx
    status, error = report.checks['US:NYSE:TQC']
    assert status == 'failed' and 'invalid JSON' in error and 'after 3 attempts' in error
    assert _cov(conn, 'US:NYSE:TQC', T(NOW - HOUR), T(NOW)).state == 'source_failed'
    run = conn.execute('SELECT status, finished_at, error FROM ingest_run').fetchone()
    assert run['status'] == 'partial' and run['finished_at'] and 'invalid JSON' in run['error']
    assert report.checks['US:NASDAQ:TDCA'][0] == 'ok'                    # other CIKs unaffected


def test_malformed_json_once_then_valid_is_ok(tmp_path):
    conn = new_store(tmp_path)
    clock = FakeClock()
    http = FakeHttp({cik_url('5678'): [BadJson('{"cik": "56'), 'CIK0000005678.json']}, clock=clock)
    assert _ingest(conn, http, clock).checks['US:NYSE:TQC'] == ('ok', None)


def test_malformed_json_in_an_additional_file_leaves_its_period_incomplete(tmp_path):
    conn = new_store(tmp_path)
    since = NOW.replace(year=2025, month=10, day=1)
    clock = FakeClock()
    http = FakeHttp({FILE_URL.format(name='CIK0000004242-submissions-001.json'): [BadJson()]}, clock=clock)
    report = _ingest(conn, http, clock, since=since)

    status, note = report.checks['US:NYSE:TLH']
    assert status == 'partial' and 'invalid JSON' in note and 'not covered: 2025-10-01T01:00:00Z..' in note
    assert _cov(conn, 'US:NYSE:TLH', T(since), T(NOW)).state == 'coverage_incomplete'


_DELETE = object()


def _mutate(path, value):
    def apply(doc):
        target = doc
        for k in path[:-1]:
            target = target[k]
        if value is _DELETE:
            del target[path[-1]]
        else:
            target[path[-1]] = value
        return doc
    return apply


INVALID_SHAPES = {
    'not an object': lambda d: ['filings'],
    'no filings': _mutate(('filings',), _DELETE),
    'recent missing a column': _mutate(('filings', 'recent', 'filingDate'), _DELETE),
    'column length mismatch': _mutate(('filings', 'recent', 'form'), ['10-Q']),
    'bad filing date': _mutate(('filings', 'recent', 'filingDate'), ['2026-08-04', '05/01/2026']),
    'acceptance without zone': _mutate(('filings', 'recent', 'acceptanceDateTime'),
                                       ['2026-08-04T20:00:00', '2026-01-05T21:15:00.000Z']),
    'bad accession number': _mutate(('filings', 'recent', 'accessionNumber'), ['../x', '0000004242-26-000001']),
    'number where text expected': _mutate(('filings', 'recent', 'form'), [10, '8-K']),
    'files not a list': _mutate(('filings', 'files'), {'name': 'x'}),
    'file name outside the API': _mutate(('filings', 'files'), [
        {'name': '../../Archives/x.json', 'filingFrom': '2025-06-01', 'filingTo': '2026-01-05'}]),
    'file without dates': _mutate(('filings', 'files'), [{'name': 'CIK0000004242-submissions-001.json'}]),
    'another company': _mutate(('cik',), '9999'),
}


@pytest.mark.parametrize('case', sorted(INVALID_SHAPES))
def test_invalid_submissions_shape_is_a_recorded_failure(tmp_path, case):
    conn = new_store(tmp_path)
    clock = FakeClock()
    doc = INVALID_SHAPES[case](copy.deepcopy(fixture('CIK0000004242.json')))
    http = FakeHttp({cik_url('4242'): [doc]}, clock=clock)
    report = _ingest(conn, http, clock, since=NOW.replace(year=2025, month=10, day=1))

    status, error = report.checks['US:NYSE:TLH']
    assert status == 'failed' and 'CIK0000004242 submissions' in error
    assert http.calls.count(cik_url('4242')) == 1                        # a shape error is not retried
    assert FILE_URL.format(name='CIK0000004242-submissions-001.json') not in http.calls
    assert conn.execute('SELECT COUNT(*) FROM event WHERE security_id = ?',
                        (sid(conn, 'US:NYSE:TLH'),)).fetchone()[0] == 0
    assert conn.execute('SELECT finished_at FROM ingest_run').fetchone()[0] is not None


def test_invalid_additional_file_shape_leaves_its_period_incomplete(tmp_path):
    conn = new_store(tmp_path)
    older = fixture('CIK0000004242-submissions-001.json')
    older['filingDate'] = older['filingDate'][:-1]                       # one value short
    clock = FakeClock()
    http = FakeHttp({FILE_URL.format(name='CIK0000004242-submissions-001.json'): [older]}, clock=clock)
    report = _ingest(conn, http, clock, since=NOW.replace(year=2025, month=10, day=1))
    status, note = report.checks['US:NYSE:TLH']
    assert status == 'partial' and 'column filingDate has' in note


def test_unusual_primary_document_links_to_the_filing_index(tmp_path):
    conn = new_store(tmp_path)
    doc = copy.deepcopy(fixture('CIK0000001234.json'))
    doc['filings']['recent']['primaryDocument'] = ['../../evil.htm' for _ in doc['filings']['recent']['form']]
    clock = FakeClock()
    _ingest(conn, FakeHttp({cik_url('1234'): [doc]}, clock=clock), clock)
    urls = [r[0] for r in conn.execute('SELECT url FROM source_document')]
    assert urls and all(u.endswith('-index.htm') and '..' not in u for u in urls)


def test_real_primary_document_shapes_are_kept():
    assert _DOCUMENT.fullmatch('xslF345X05/wk-form4_1758650400.xml')     # Form 4 rendering path
    assert _DOCUMENT.fullmatch('aapl-20260627.htm')
    assert not _DOCUMENT.fullmatch('../x.htm') and not _DOCUMENT.fullmatch('a/../../b')


def test_unexpected_error_mid_run_still_closes_the_run(tmp_path, monkeypatch):
    conn = new_store(tmp_path)
    real, calls = sec_submissions._record_cik, []

    def fail_on_second_cik(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError('disk full')
        return real(*args, **kwargs)

    monkeypatch.setattr(sec_submissions, '_record_cik', fail_on_second_cik)
    clock = FakeClock()
    with pytest.raises(RuntimeError):
        _ingest(conn, FakeHttp(clock=clock), clock)
    run = conn.execute('SELECT status, finished_at, error FROM ingest_run').fetchone()
    assert run['status'] == 'failed' and run['finished_at'] and 'disk full' in run['error']
