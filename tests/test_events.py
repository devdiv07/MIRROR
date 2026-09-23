"""
Milestone 2 event tests (ADR 0001 §4.2, §10): SEC ingestion, event versions, as-of reads, backfill
coverage and the v1 -> v2 schema upgrade. Offline: HTTP is tests.support.FakeHttp over fixtures.
"""

import sqlite3

import pytest
import requests

from src.core.coverage import coverage
from src.sources import manual_events
from src.sources.sec_submissions import FILE_URL, ingest_sec
from src.store import db
from tests.support import (
    HOUR, NOW, ROOT, FakeClock, FakeHttp, cik_url, fixture, new_store, sid, us_securities,
)

T = db.utc_iso


def _ingest(conn, http, now=NOW, since=None, clock=None):
    """Responses arrive instantly at `now` (the arrival-time tests are in test_sec_hardening.py)."""
    clock = clock or FakeClock(now)
    return ingest_sec(conn, us_securities(conn), now=now, since=since, get=http,
                      sleep=clock.sleep, monotonic=clock.monotonic, utcnow=lambda: now)


def _state(conn, key, source, start, end, as_of=None):
    return coverage(conn, security_id=sid(conn, key), source=source, window_start=start,
                    window_end=end, as_of=as_of or end)


# ── C5 / C6 / C7: one fetch per CIK, events and checks per listing ───────────

def test_shared_cik_two_listings_one_fetch_events_and_checks_for_each(tmp_path):     # C7
    conn = new_store(tmp_path)
    http = FakeHttp()
    report = _ingest(conn, http)

    assert http.calls.count(cik_url('1234')) == 1
    assert report.fetches == 3 and report.status == 'ok'
    docs = conn.execute("SELECT source_doc_key FROM source_document WHERE source = 'SEC_EDGAR'").fetchall()
    assert [d[0] for d in docs] == ['0000001234-26-000031']          # the 8-K only, stored once
    events = conn.execute('SELECT security_id, doc_id, version FROM event ORDER BY security_id').fetchall()
    assert [tuple(e) for e in events] == [(sid(conn, 'US:NASDAQ:TDCA'), 1, 1), (sid(conn, 'US:NASDAQ:TDCB'), 1, 1)]
    for key in ('US:NASDAQ:TDCA', 'US:NASDAQ:TDCB'):
        assert report.checks[key] == ('ok', None)


def test_checked_with_events_lists_the_filing(tmp_path):                                 # C6
    conn = new_store(tmp_path)
    _ingest(conn, FakeHttp())
    cov = _state(conn, 'US:NASDAQ:TDCA', 'SEC_EDGAR', T(NOW - 24 * HOUR), T(NOW))
    assert cov.state == 'checked_with_events'
    (e,) = cov.events
    assert e['published_at'] == '2026-09-22T20:30:00Z' and e['published_basis'] == 'source_timestamp'
    assert e['url'] == 'https://www.sec.gov/Archives/edgar/data/1234/000000123426000031/tdc-20260922.htm'
    assert e['event_type'] == '8k_item' and '"items": "2.02,9.01"' in e['fields_json']


def test_checked_no_events(tmp_path):                                                    # C5
    conn = new_store(tmp_path)
    _ingest(conn, FakeHttp())
    cov = _state(conn, 'US:NYSE:TQC', 'SEC_EDGAR', T(NOW - 24 * HOUR), T(NOW))
    assert cov.state == 'checked_no_events' and cov.events == []


def test_filings_outside_window_or_form_are_not_stored(tmp_path):
    conn = new_store(tmp_path)
    _ingest(conn, FakeHttp())
    forms = {r[0] for r in conn.execute("SELECT json_extract(fields_json, '$.form') FROM event")}
    assert forms == {'8-K'}             # S-8 ignored; Form 4 (09-10) and 10-Qs are before the 7-day window


# ── Duplicate ingest and revisions ───────────────────────────────────────────

def test_second_ingest_adds_no_versions_and_extends_coverage(tmp_path):
    conn = new_store(tmp_path)
    _ingest(conn, FakeHttp())
    before = conn.execute('SELECT COUNT(*) FROM event').fetchone()[0]
    report = _ingest(conn, FakeHttp(), now=NOW + HOUR)
    assert report.records_new == 0
    assert conn.execute('SELECT COUNT(*) FROM event').fetchone()[0] == before
    starts = {r[0] for r in conn.execute(
        "SELECT window_start FROM coverage_check WHERE checked_at = ?", (T(NOW + HOUR),))}
    assert starts == {T(NOW)}                                          # each listing resumed where it stopped
    cov = _state(conn, 'US:NASDAQ:TDCA', 'SEC_EDGAR', T(NOW - 24 * HOUR), T(NOW + HOUR))
    assert cov.state == 'checked_with_events'


def test_sec_metadata_revision_is_a_new_version_read_at_two_times(tmp_path):            # V1 (SEC)
    conn = new_store(tmp_path)
    _ingest(conn, FakeHttp())
    revised = fixture('CIK0000001234.json')
    revised['filings']['recent']['items'][0] = '2.02,7.01,9.01'
    later = NOW + 2 * HOUR
    _ingest(conn, FakeHttp({cik_url('1234'): [revised]}), now=later, since=NOW - 7 * 24 * HOUR)

    rows = conn.execute("SELECT version, first_seen_at FROM event WHERE security_id = ? ORDER BY version",
                        (sid(conn, 'US:NASDAQ:TDCA'),)).fetchall()
    assert [tuple(r) for r in rows] == [(1, T(NOW)), (2, T(later))]
    assert conn.execute('SELECT MAX(version) FROM source_document').fetchone()[0] == 2
    (v_then,) = db.events_as_of(conn, as_of=T(NOW + HOUR), security_id=sid(conn, 'US:NASDAQ:TDCA'))
    (v_now,) = db.events_as_of(conn, as_of=T(later), security_id=sid(conn, 'US:NASDAQ:TDCA'))
    assert (v_then['version'], v_now['version']) == (1, 2)
    assert '7.01' in v_now['fields_json'] and '7.01' not in v_then['fields_json']


# ── A6: outage, retries ──────────────────────────────────────────────────────

def test_outage_after_three_attempts_is_recorded_not_hidden(tmp_path):                  # A6 (state)
    conn = new_store(tmp_path)
    http = FakeHttp({cik_url('1234'): [503]})
    clock = FakeClock()
    report = _ingest(conn, http, clock=clock)

    assert http.calls.count(cik_url('1234')) == 3
    assert clock.sleeps[:2] == [1.0, 2.0]                                # backoff before retries 2 and 3
    assert report.status == 'partial'                                   # other CIKs succeeded
    for key in ('US:NASDAQ:TDCA', 'US:NASDAQ:TDCB'):
        status, error = report.checks[key]
        assert status == 'failed' and 'HTTP 503 after 3 attempts' in error
        cov = _state(conn, key, 'SEC_EDGAR', T(NOW - 24 * HOUR), T(NOW))
        assert cov.state == 'source_failed' and 'last success never' in cov.detail
    run = conn.execute('SELECT status, error FROM ingest_run').fetchone()
    assert run['status'] == 'partial' and '503' in run['error']
    assert conn.execute('SELECT COUNT(*) FROM event').fetchone()[0] == 0


def test_every_source_failing_marks_the_run_failed(tmp_path):
    conn = new_store(tmp_path)
    http = FakeHttp({cik_url(c): [503] for c in ('1234', '5678', '4242')})
    assert _ingest(conn, http).status == 'failed'


def test_client_error_is_not_retried(tmp_path):
    conn = new_store(tmp_path)
    http = FakeHttp({cik_url('5678'): [404]})
    report = _ingest(conn, http)
    assert http.calls.count(cik_url('5678')) == 1
    assert report.checks['US:NYSE:TQC'][0] == 'failed' and 'not retried' in report.checks['US:NYSE:TQC'][1]


def test_connection_errors_are_retried(tmp_path):
    conn = new_store(tmp_path)
    http = FakeHttp({cik_url('5678'): [requests.ConnectionError('reset'), requests.Timeout('slow'),
                                        'CIK0000005678.json']})
    assert _ingest(conn, http).checks['US:NYSE:TQC'] == ('ok', None)


# ── B1: backfill is only complete when every needed file was fetched ─────────

def test_daily_window_inside_recent_does_not_fetch_older_file(tmp_path):
    conn = new_store(tmp_path)
    http = FakeHttp()
    report = _ingest(conn, http)
    assert FILE_URL.format(name='CIK0000004242-submissions-001.json') not in http.calls
    assert report.checks['US:NYSE:TLH'] == ('ok', None)


def test_backfill_missing_older_file_is_partial_then_ok_once_fetched(tmp_path):         # B1
    conn = new_store(tmp_path)
    since = NOW.replace(year=2025, month=10, day=1)
    file_url = FILE_URL.format(name='CIK0000004242-submissions-001.json')

    # (a) the additional file cannot be fetched -> partial, and the gap is named
    report = _ingest(conn, FakeHttp({file_url: [503]}), since=since)
    status, note = report.checks['US:NYSE:TLH']
    assert status == 'partial'
    assert 'CIK0000004242-submissions-001.json' in note and 'not covered: 2025-10-01T01:00:00Z..' in note
    window = (T(since), T(NOW))
    assert _state(conn, 'US:NYSE:TLH', 'SEC_EDGAR', *window).state == 'coverage_incomplete'
    assert report.checks['US:NYSE:TQC'] == ('ok', None)                  # files == [] -> recent is complete

    # (b) the same backfill with the file served -> ok, and the older 10-Q is stored
    later = NOW + HOUR
    report = _ingest(conn, FakeHttp(), now=later, since=since)
    assert report.checks['US:NYSE:TLH'] == ('ok', None)
    cov = _state(conn, 'US:NYSE:TLH', 'SEC_EDGAR', T(since), T(later))
    assert cov.state == 'checked_with_events'
    assert [e['source_doc_key'] for e in cov.events] == ['0000004242-25-000044', '0000004242-26-000001',
                                                         '0000004242-26-000005']
    # As of (a), MIRROR could not honestly have called that window checked.
    assert _state(conn, 'US:NYSE:TLH', 'SEC_EDGAR', *window, as_of=T(NOW)).state == 'coverage_incomplete'


# ── V1 / R1: manual event versions read at two times ─────────────────────────

def _manual_csv(tmp_path, published_at, subject='Outcome of Board Meeting', url='https://nsearchives.example/a.pdf'):
    p = tmp_path / 'manual_events.csv'
    p.write_text('security_key,url,subject,published_at,event_type\n'
                 f'IN:NSE:TESTIN,{url},{subject},{published_at},board_outcome\n', encoding='utf-8')
    return str(p)


def test_manual_revision_read_at_two_times(tmp_path):                                   # V1
    conn = new_store(tmp_path)
    t1, t2 = NOW, NOW + 3 * HOUR
    first = manual_events.import_manual_events(conn, _manual_csv(tmp_path, '2026-09-22T16:05:00+05:30'), now=t1)
    corrected = _manual_csv(tmp_path, '2026-09-22T15:05:00+05:30')
    second = manual_events.import_manual_events(conn, corrected, now=t2)
    assert list(first.statuses.values()) == ['inserted'] and list(second.statuses.values()) == ['new_version']

    rows = conn.execute('SELECT dedup_key, version, published_at FROM event ORDER BY version').fetchall()
    assert rows[0]['dedup_key'] == rows[1]['dedup_key'] and [r['version'] for r in rows] == [1, 2]

    def at(t):
        return [(e['version'], e['published_at']) for e in db.events_as_of(conn, as_of=T(t))]

    assert at(t1) == [(1, '2026-09-22T10:35:00Z')]
    assert at(t2 - HOUR) == [(1, '2026-09-22T10:35:00Z')]
    assert at(t2) == [(2, '2026-09-22T09:35:00Z')]
    assert list(manual_events.import_manual_events(conn, corrected, now=t2 + HOUR).statuses.values()) == ['unchanged']


def test_a_b_a_change_is_three_versions(tmp_path):
    conn = new_store(tmp_path)
    for i, subject in enumerate(['A', 'B', 'A']):
        manual_events.import_manual_events(conn, _manual_csv(tmp_path, '2026-09-22 15:00', subject), now=NOW + i * HOUR)
    assert [r[0] for r in conn.execute('SELECT subject FROM event ORDER BY version')] == ['A', 'B', 'A']
    assert [r[0] for r in conn.execute('SELECT version FROM source_document ORDER BY version')] == [1, 2, 3]


def test_as_of_guard_hides_events_first_seen_later(tmp_path):                           # R1
    conn = new_store(tmp_path)
    seen = NOW.replace(hour=9) + 24 * HOUR                                # D+1 09:00
    manual_events.import_manual_events(conn, _manual_csv(tmp_path, '2026-09-23 18:00'), now=seen)
    assert db.events_as_of(conn, as_of=T(seen - HOUR)) == []              # brief as of D+1 08:00
    assert len(db.events_as_of(conn, as_of=T(seen))) == 1


def test_naive_time_is_read_as_ist_and_flagged(tmp_path):
    conn = new_store(tmp_path)
    manual_events.import_manual_events(conn, _manual_csv(tmp_path, '2026-09-22 16:05'), now=NOW)
    (e,) = db.events_as_of(conn, as_of=T(NOW))
    assert e['published_at'] == '2026-09-22T10:35:00Z' and e['tz_assumed'] == 1 and e['published_basis'] == 'user_entered'


@pytest.mark.parametrize('row, message', [
    ('US:NASDAQ:TDCA,https://x.example/1,Subj,2026-09-22 10:00,results', 'not NSE'),
    ('IN:NSE:NOPE,https://x.example/1,Subj,2026-09-22 10:00,results', 'unknown security_key'),
    ('IN:NSE:TESTIN,http://x.example/1,Subj,2026-09-22 10:00,results', 'https'),
    ('IN:NSE:TESTIN,https://x.example/1,Subj,2026-09-30 10:00,results', 'future'),
    ('IN:NSE:TESTIN,https://x.example/1,Subj,2026-09-22 10:00,rumour', 'event_type'),
])
def test_invalid_manual_row_aborts_whole_import(tmp_path, row, message):
    conn = new_store(tmp_path)
    p = tmp_path / 'm.csv'
    p.write_text('security_key,url,subject,published_at,event_type\n'
                 'IN:NSE:TESTIN,https://x.example/ok,Fine,2026-09-22 10:00,results\n' + row + '\n', encoding='utf-8')
    with pytest.raises(manual_events.ManualInputError, match=message):
        manual_events.import_manual_events(conn, str(p), now=NOW)
    assert conn.execute('SELECT COUNT(*) FROM event').fetchone()[0] == 0     # the valid row was rolled back too
    assert conn.execute('SELECT status FROM ingest_run').fetchone()[0] == 'failed'


# ── schema v1 -> v2 ──────────────────────────────────────────────────────────

def _v1_database(path):
    conn = sqlite3.connect(path)
    conn.executescript((ROOT / 'tests' / 'fixtures' / 'schema_v1.sql').read_text(encoding='utf-8'))
    conn.execute('PRAGMA user_version = 1')
    return conn


def test_empty_v1_database_is_upgraded(tmp_path):
    path = str(tmp_path / 'v1.sqlite3')
    _v1_database(path).close()
    conn = db.connect(path)
    assert conn.execute('PRAGMA user_version').fetchone()[0] == 2
    cols = {r['name'] for r in conn.execute('PRAGMA table_info(event)')}
    assert {'version', 'content_sha256', 'dedup_key'} <= cols


def test_v1_database_with_events_is_refused(tmp_path):
    path = str(tmp_path / 'v1.sqlite3')
    old = _v1_database(path)
    old.execute("INSERT INTO security VALUES (1,'K','US','NYSE','N',NULL,NULL,NULL,'USD','America/New_York',NULL,'t','t')")
    old.execute("INSERT INTO event (security_id, event_type, subject, first_seen_at, dedup_key)"
                " VALUES (1, 'results', 's', 't', 'k')")
    old.commit()
    old.close()
    with pytest.raises(RuntimeError, match='migrate them by hand'):
        db.connect(path)

