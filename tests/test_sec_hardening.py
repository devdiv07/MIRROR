"""
SEC adapter hardening (Step 3 follow-up): the declared User-Agent, one rate limit for every request,
invalid responses recorded as failures, and as-of times taken when responses arrive.
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
                      sleep=clock.sleep, monotonic=clock.monotonic, utcnow=clock.now)


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
    assert _cov(conn, 'US:NYSE:TQC', T(NOW - HOUR), T(NOW), as_of=T(clock.now())).state == 'source_failed'
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
    assert _cov(conn, 'US:NYSE:TLH', T(since), T(NOW), as_of=T(clock.now())).state == 'coverage_incomplete'


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


# ── as-of times: windows end at the cutoff; first_seen_at and checked_at at arrival ─

def _with_late_8k(doc):
    """Add an 8-K to CIK 1234's recent filings, accepted 30 s after NOW (the first run's cutoff)."""
    late = {'accessionNumber': '0000001234-26-000040', 'filingDate': '2026-09-23', 'reportDate': '',
            'acceptanceDateTime': '2026-09-23T01:00:30.000Z', 'form': '8-K', 'items': '8.01',
            'primaryDocument': 'tdc-late.htm', 'primaryDocDescription': '8-K'}
    for k, v in late.items():
        doc['filings']['recent'][k].insert(0, v)
    return doc


def _events(conn, key):
    return [tuple(r) for r in conn.execute(
        'SELECT d.source_doc_key, e.published_at, e.first_seen_at, d.first_seen_at FROM event e'
        ' JOIN source_document d USING (doc_id) WHERE e.security_id = ? ORDER BY e.event_id', (sid(conn, key),))]


def test_slow_response_is_stamped_when_it_arrives_not_when_the_run_started(tmp_path):
    conn = new_store(tmp_path)
    doc = _with_late_8k(copy.deepcopy(fixture('CIK0000001234.json')))
    clock = FakeClock()
    http = FakeHttp({cik_url('1234'): [doc]}, clock=clock, latency=90.0)   # every response takes 90 s
    _ingest(conn, http, clock)
    arrived = T(NOW + timedelta(seconds=90))                             # CIK 1234 is fetched first

    # The filing is stamped at arrival; the one accepted after the cutoff waits for the next run.
    assert _events(conn, 'US:NASDAQ:TDCA') == [('0000001234-26-000031', '2026-09-22T20:30:00Z', arrived, arrived)]
    check = conn.execute('SELECT window_end, checked_at FROM coverage_check WHERE security_id = ?',
                         (sid(conn, 'US:NASDAQ:TDCA'),)).fetchone()
    assert tuple(check) == (T(NOW), arrived)
    run = conn.execute('SELECT started_at, finished_at FROM ingest_run').fetchone()
    assert tuple(run) == (T(NOW), T(NOW + timedelta(seconds=3 * 90)))

    # As of the cutoff MIRROR had nothing yet; as of the arrival it had the check and the filing.
    window = (T(NOW - 24 * HOUR), T(NOW))
    assert db.events_as_of(conn, as_of=T(NOW), security_id=sid(conn, 'US:NASDAQ:TDCA')) == []
    assert _cov(conn, 'US:NASDAQ:TDCA', *window, as_of=T(NOW)).state == 'not_checked'
    assert _cov(conn, 'US:NASDAQ:TDCA', *window, as_of=arrived).state == 'checked_with_events'

    # The next run's window starts at the first cutoff, so the late 8-K is stored then.
    later = NOW + HOUR
    clock2 = FakeClock(later)
    _ingest(conn, FakeHttp({cik_url('1234'): [doc]}, clock=clock2, latency=5.0), clock2, now=later)
    seen = T(later + timedelta(seconds=5))
    assert _events(conn, 'US:NASDAQ:TDCA')[-1] == ('0000001234-26-000040', '2026-09-23T01:00:30Z', seen, seen)
    assert len(_events(conn, 'US:NASDAQ:TDCA')) == 2                     # the first 8-K was not duplicated


def test_additional_file_filings_are_stamped_at_their_own_arrival(tmp_path):
    conn = new_store(tmp_path)
    clock = FakeClock()
    http = FakeHttp(clock=clock, latency=10.0)
    _ingest(conn, http, clock, since=NOW.replace(year=2025, month=10, day=1))
    file_url = FILE_URL.format(name='CIK0000004242-submissions-001.json')
    file_arrival = T(NOW + timedelta(seconds=10 * (http.calls.index(file_url) + 1)))
    first_seen = dict((k, s) for k, _, s, _ in _events(conn, 'US:NYSE:TLH'))
    assert first_seen['0000004242-25-000044'] == file_arrival            # from the older file
    assert first_seen['0000004242-26-000005'] < file_arrival             # from recent, which came first


def test_a_clock_behind_the_cutoff_never_stamps_before_it(tmp_path):
    conn = new_store(tmp_path)
    clock = FakeClock()
    ingest_sec(conn, us_securities(conn), now=NOW, get=FakeHttp(), sleep=clock.sleep,
               monotonic=clock.monotonic, utcnow=lambda: NOW - HOUR)
    assert {r[0] for r in conn.execute('SELECT checked_at FROM coverage_check')} == {T(NOW)}
    assert {r[0] for r in conn.execute('SELECT first_seen_at FROM event')} == {T(NOW)}


# ── gaps persist until fetched: an ordinary rerun retries them ───────────────

OLD_FILE = FILE_URL.format(name='CIK0000004242-submissions-001.json')
BACKFILL_FROM = NOW.replace(year=2025, month=10, day=1)
GAP = 'not covered: 2025-10-01T01:00:00Z..2026-01-06T05:00:00Z'        # up to recent's first day (ET)
DAY = 24 * HOUR


def _run(conn, when, since=None, routes=None):
    clock = FakeClock(when)
    http = FakeHttp(routes, clock=clock)
    return _ingest(conn, http, clock, now=when, since=since), http


def _windows(conn, key):
    return [tuple(r) for r in conn.execute(
        'SELECT window_start, window_end, status FROM coverage_check WHERE security_id = ? ORDER BY check_id',
        (sid(conn, key),))]


def test_ordinary_rerun_after_a_partial_first_backfill_retries_the_missing_period(tmp_path):
    conn = new_store(tmp_path)
    first, _ = _run(conn, NOW, since=BACKFILL_FROM, routes={OLD_FILE: [503]})
    assert first.checks['US:NYSE:TLH'][0] == 'partial'                  # TLH's first check ever

    second, http = _run(conn, NOW + DAY)                                 # an ordinary run: no --sec-since
    assert OLD_FILE in http.calls
    assert second.checks['US:NYSE:TLH'] == ('ok', None)
    assert _windows(conn, 'US:NYSE:TLH')[-1] == (T(BACKFILL_FROM), T(NOW + DAY), 'ok')
    cov = _cov(conn, 'US:NYSE:TLH', T(BACKFILL_FROM), T(NOW + DAY), as_of=T(NOW + 2 * DAY))
    assert cov.state == 'checked_with_events'
    assert '0000004242-25-000044' in [e['source_doc_key'] for e in cov.events]   # from the older file
    assert _windows(conn, 'US:NYSE:TQC')[-1][0] == T(NOW)                # no gap: resumes where it stopped


def test_gap_stays_incomplete_across_runs_until_it_is_fetched(tmp_path):
    conn = new_store(tmp_path)
    for when, since in ((NOW, BACKFILL_FROM), (NOW + DAY, None)):
        report, _ = _run(conn, when, since=since, routes={OLD_FILE: [503]})
        status, note = report.checks['US:NYSE:TLH']
        assert status == 'partial' and GAP in note and 'HTTP 503' in note

    as_of = T(NOW + DAY + HOUR)
    assert _cov(conn, 'US:NYSE:TLH', T(BACKFILL_FROM), T(NOW + DAY), as_of=as_of).state == 'coverage_incomplete'
    # The days the partial checks did cover still count as checked.
    assert _cov(conn, 'US:NYSE:TLH', T(NOW), T(NOW + DAY), as_of=as_of).state == 'checked_no_events'

    report, _ = _run(conn, NOW + 2 * DAY)
    assert report.checks['US:NYSE:TLH'] == ('ok', None)
    assert db.resume_point(conn, sid(conn, 'US:NYSE:TLH'), 'SEC_EDGAR') == T(NOW + 2 * DAY)
    assert _cov(conn, 'US:NYSE:TLH', T(BACKFILL_FROM), T(NOW + 2 * DAY),
                as_of=T(NOW + 3 * DAY)).state == 'checked_with_events'


def test_failed_first_run_is_retried_by_the_next_ordinary_run(tmp_path):
    conn = new_store(tmp_path)
    _run(conn, NOW, routes={cik_url('5678'): [503]})
    report, _ = _run(conn, NOW + DAY)
    assert report.checks['US:NYSE:TQC'] == ('ok', None)
    starts = [w[0] for w in _windows(conn, 'US:NYSE:TQC')]
    assert starts == [T(NOW - 7 * DAY)] * 2                              # the failed window is asked again


def _apple_shaped_boundary():
    """The live AAPL shape seen 2026-09-23: one file to 2015-07-25 (a Saturday), recent from
    2015-07-27 (a Monday), nothing filed in between."""
    file_name = 'CIK0000007777-submissions-001.json'
    submissions = {'cik': '7777', 'filings': {
        'recent': _columns([('0000007777-26-000009', '2026-08-04', '10-Q'),
                            ('0000007777-15-000031', '2015-07-27', '8-K')]),
        'files': [{'name': file_name, 'filingCount': 1, 'filingFrom': '1994-01-26', 'filingTo': '2015-07-25'}]}}
    older = _columns([('0000007777-15-000030', '2015-07-24', '8-K')])
    return {cik_url('7777'): [submissions], FILE_URL.format(name=file_name): [older]}, FILE_URL.format(name=file_name)


def test_days_between_the_newest_file_and_recent_are_covered_by_recent(tmp_path):
    routes, file_url = _apple_shaped_boundary()
    conn = new_store(tmp_path, MANY_WATCHLIST)
    report, http = _run(conn, NOW, since=NOW.replace(year=2015, month=1, day=1), routes=routes)
    assert report.checks['US:NYSE:TMF'] == ('ok', None)                  # was: not covered 07-26..07-28
    assert file_url in http.calls
    assert db.resume_point(conn, sid(conn, 'US:NYSE:TMF'), 'SEC_EDGAR') == T(NOW)   # nothing to retry

    # A window that starts on the Sunday between them needs only recent.
    conn = new_store(tmp_path, MANY_WATCHLIST)
    report, http = _run(conn, NOW, since=NOW.replace(year=2015, month=7, day=26, hour=12), routes=routes)
    assert report.checks['US:NYSE:TMF'] == ('ok', None) and file_url not in http.calls


def test_backfill_before_the_first_filing_is_complete(tmp_path):
    conn = new_store(tmp_path)
    report, http = _run(conn, NOW, since=NOW.replace(year=2010))
    assert OLD_FILE in http.calls
    assert report.checks['US:NYSE:TLH'] == ('ok', None)                  # the oldest file reaches back to the start


# ── store rules for covered spans ────────────────────────────────────────────

def test_spans_belong_to_partial_checks_and_are_clipped_to_the_window(tmp_path):
    conn = new_store(tmp_path)
    s = sid(conn, 'US:NYSE:TQC')
    common = dict(security_id=s, source='SEC_EDGAR', method='api', window_start=T(NOW - 10 * HOUR),
                  window_end=T(NOW), checked_at=T(NOW))
    with pytest.raises(ValueError, match="'partial'"):
        db.insert_coverage_check(conn, status='ok', covered_spans=[(T(NOW - HOUR), T(NOW))], **common)
    db.insert_coverage_check(conn, status='partial', scope_note='x', **common,
                             covered_spans=[(T(NOW - 20 * HOUR), T(NOW - 5 * HOUR)), (T(NOW + HOUR), T(NOW + 2 * HOUR))])
    assert db.covered_intervals(conn, s, 'SEC_EDGAR') == [(T(NOW - 10 * HOUR), T(NOW - 5 * HOUR))]
    assert db.resume_point(conn, s, 'SEC_EDGAR') == T(NOW - 5 * HOUR)
    assert db.covered_intervals(conn, s, 'SEC_EDGAR', as_of=T(NOW - HOUR)) == []   # recorded later


def test_v2_database_upgrades_and_its_partial_checks_cover_nothing(tmp_path):
    path = str(tmp_path / 'v2.sqlite3')
    old = db.connect(path)
    old.execute("INSERT INTO security VALUES (1,'K','US','NYSE','N','CIK','0000000001',NULL,'USD',"
                "'America/New_York',NULL,'t','t')")
    old.execute("INSERT INTO coverage_check (security_id, source, method, window_start, window_end, checked_at,"
                " status, scope_note) VALUES (1, 'SEC_EDGAR', 'api', 'A', 'B', 'B', 'partial', 'gap')")
    old.execute('DROP TABLE coverage_span')
    old.execute('PRAGMA user_version = 2')
    old.close()

    conn = db.connect(path)
    assert conn.execute('PRAGMA user_version').fetchone()[0] == db.SCHEMA_VERSION == 3
    assert conn.execute('SELECT COUNT(*) FROM coverage_span').fetchone()[0] == 0
    assert db.resume_point(conn, 1, 'SEC_EDGAR') == 'A'                  # its whole window is retried
    conn.close()
