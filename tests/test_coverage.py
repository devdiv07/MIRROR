"""
Coverage-state tests (ADR 0001 §4.4; cases C1-C4, precedence) and the Milestone 2 CLI
(`ingest`, `checked`, `events`) run end to end on offline fixtures.
"""

import io

import pytest

from src import cli
from src.core.coverage import coverage, covers
from src.sources import manual_events
from src.store import db
from tests.support import HOUR, NOW, WATCHLIST, FakeHttp, new_store, sid

T = db.utc_iso
IN_KEY = 'IN:NSE:TESTIN'
W_START, W_END = NOW - 24 * HOUR, NOW            # the window under test: (W_START, W_END]


def _nse(conn, start=W_START, end=W_END, as_of=None):
    return coverage(conn, security_id=sid(conn, IN_KEY), source='MANUAL_NSE', window_start=T(start),
                    window_end=T(end), as_of=T(as_of or end))


def _check(conn, *, start, through, now, partial=False, note=None):
    return manual_events.record_manual_check(conn, security_key=IN_KEY, start=start, through=through,
                                             now=now, partial=partial, note=note)


def _event(conn, tmp_path, published_at, now):
    p = tmp_path / 'm.csv'
    p.write_text('security_key,url,subject,published_at,event_type\n'
                 f'{IN_KEY},https://nsearchives.example/r.pdf,Financial Results,{published_at},results\n',
                 encoding='utf-8')
    manual_events.import_manual_events(conn, str(p), now=now)


# ── C1-C4 ────────────────────────────────────────────────────────────────────

def test_c1_not_checked(tmp_path):
    cov = _nse(new_store(tmp_path))
    assert cov.state == 'not_checked' and cov.detail == 'never checked'


def test_c2_checked_no_events(tmp_path):
    conn = new_store(tmp_path)
    _check(conn, start=W_START - HOUR, through=W_END, now=W_END)
    cov = _nse(conn)
    assert cov.state == 'checked_no_events'
    assert cov.detail == f'checked through {T(W_END)}: no new disclosures'


def test_checked_with_events(tmp_path):
    conn = new_store(tmp_path)
    _event(conn, tmp_path, '2026-09-22T20:00:00+05:30', now=W_END - HOUR)
    _check(conn, start=W_START, through=W_END, now=W_END)
    cov = _nse(conn)
    assert cov.state == 'checked_with_events' and len(cov.events) == 1


def test_c3_check_through_mid_window_is_incomplete(tmp_path):
    conn = new_store(tmp_path)
    _check(conn, start=W_START, through=W_START + 6 * HOUR, now=W_END)
    cov = _nse(conn)
    assert cov.state == 'coverage_incomplete' and T(W_START + 6 * HOUR) in cov.detail


def test_c3_partial_check_with_note_is_incomplete(tmp_path):
    conn = new_store(tmp_path)
    _check(conn, start=W_START, through=W_END, now=W_END, partial=True, note='results page only')
    cov = _nse(conn)
    assert cov.state == 'coverage_incomplete' and 'results page only' in cov.detail


def test_c4_entering_an_event_is_not_a_check(tmp_path):
    conn = new_store(tmp_path)
    _event(conn, tmp_path, '2026-09-22T20:00:00+05:30', now=W_END)
    cov = _nse(conn)
    assert cov.state == 'not_checked'
    assert [e['subject'] for e in cov.events] == ['Financial Results']      # still listed


# ── Precedence and as-of ─────────────────────────────────────────────────────

def _raw_check(conn, status, start, end, checked_at, error=None):
    db.insert_coverage_check(conn, security_id=sid(conn, IN_KEY), source='MANUAL_NSE', method='manual',
                             window_start=T(start), window_end=T(end), checked_at=T(checked_at),
                             status=status, error=error)


def test_later_failure_does_not_erase_complete_coverage(tmp_path):
    conn = new_store(tmp_path)
    _raw_check(conn, 'ok', W_START, W_END, W_END)
    _raw_check(conn, 'failed', W_START, W_END, W_END, error='timeout')
    assert _nse(conn).state == 'checked_no_events'


def test_failed_latest_attempt_without_full_coverage(tmp_path):
    conn = new_store(tmp_path)
    _raw_check(conn, 'ok', W_START, W_START + HOUR, W_START + HOUR)
    _raw_check(conn, 'failed', W_START, W_END, W_END, error='HTTP 503')
    cov = _nse(conn)
    assert cov.state == 'source_failed' and 'HTTP 503' in cov.detail and T(W_START + HOUR) in cov.detail


def test_partial_after_failure_is_incomplete_not_failed(tmp_path):
    conn = new_store(tmp_path)
    _raw_check(conn, 'failed', W_START, W_END, W_END - HOUR, error='x')
    _raw_check(conn, 'partial', W_START, W_END, W_END)
    assert _nse(conn).state == 'coverage_incomplete'


def test_checks_recorded_after_as_of_do_not_count(tmp_path):
    conn = new_store(tmp_path)
    _check(conn, start=W_START, through=W_END, now=W_END + HOUR)                # recorded later
    assert _nse(conn, as_of=W_END).state == 'not_checked'
    assert _nse(conn, as_of=W_END + HOUR).state == 'checked_no_events'


def test_contiguous_manual_checks_cover_the_window(tmp_path):
    conn = new_store(tmp_path)
    _check(conn, start=W_START, through=W_START + 10 * HOUR, now=W_START + 10 * HOUR)
    manual_events.record_manual_check(conn, security_key=IN_KEY, through=W_END, now=W_END)  # resumes
    assert _nse(conn).state == 'checked_no_events'


@pytest.mark.parametrize('kwargs, message', [
    (dict(start=None, through=W_END, now=W_END), 'needs --from'),
    (dict(start=W_START, through=W_END + HOUR, now=W_END), 'after now'),
    (dict(start=W_END, through=W_START, now=W_END), 'must be after'),
    (dict(start=W_START, through=W_END, now=W_END, partial=True), 'needs --note'),
])
def test_invalid_manual_checks_are_rejected(tmp_path, kwargs, message):
    conn = new_store(tmp_path)
    with pytest.raises(manual_events.ManualInputError, match=message):
        manual_events.record_manual_check(conn, security_key=IN_KEY, **kwargs)


def test_manual_check_on_us_security_rejected(tmp_path):
    conn = new_store(tmp_path)
    with pytest.raises(manual_events.ManualInputError, match='not NSE'):
        manual_events.record_manual_check(conn, security_key='US:NYSE:TQC', start=W_START, through=W_END, now=W_END)


def test_covers_handles_gaps_and_touching_intervals():
    a, b, c, d = '2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z', '2026-01-03T00:00:00Z', '2026-01-04T00:00:00Z'
    assert covers([(a, b), (b, d)], a, d)
    assert not covers([(a, b), (c, d)], a, d)
    assert not covers([], a, b)
    assert covers([(a, d)], b, c)


# ── CLI end to end ───────────────────────────────────────────────────────────

def test_cli_ingest_checked_events(tmp_path):
    (tmp_path / 'watchlist.yaml').write_text(WATCHLIST, encoding='utf-8')
    (tmp_path / 'manual.csv').write_text(
        'security_key,url,subject,published_at,event_type\n'
        'IN:NSE:TESTIN,https://nsearchives.example/o.pdf,Outcome of Board Meeting,2026-09-22 16:05,board_outcome\n',
        encoding='utf-8')
    dbp = str(tmp_path / 'mirror.sqlite3')

    def run(*argv, now=NOW):
        out = io.StringIO()
        code = cli.main(['--db', dbp, *argv], now=now, out=out, http_get=FakeHttp())
        return code, out.getvalue()

    code, text = run('ingest', '--watchlist', str(tmp_path / 'watchlist.yaml'),
                     '--manual-events', str(tmp_path / 'manual.csv'))
    assert code == 0 and 'SEC EDGAR: run 1 ok; 3 CIK fetch(es)' in text and 'manual NSE events: 1 row(s)' in text

    code, text = run('events', '--since', '2026-09-22T00:00:00Z', '--as-of', '2026-09-23T01:00:00Z')
    assert code == 0
    assert '[MANUAL_NSE] NOT CHECKED' in text                       # C4 through the CLI
    assert '(time zone assumed IST)' in text and 'Outcome of Board Meeting' in text
    assert '[SEC_EDGAR] Checked, new disclosures below' in text     # TDCA and TDCB
    assert text.count('0000001234-26-000031') == 0                  # the listing shows URLs, not accession ids
    assert text.count('tdc-20260922.htm') == 2                      # one event per listing (shared CIK)
    assert '[SEC_EDGAR] Checked, no new disclosures' in text        # TQC

    code, text = run('checked', 'NSE', 'TSTIN', '--from', '2026-09-22T00:00:00Z',
                     '--through', '2026-09-23T07:30:00+05:30', now=NOW + HOUR)       # = 02:00Z
    assert code == 0 and 'recorded ok NSE check for IN:NSE:TESTIN' in text
    code, text = run('events', '--since', '2026-09-22T00:00:00Z', '--as-of', '2026-09-23T02:00:00Z')
    assert '[MANUAL_NSE] Checked, new disclosures below' in text    # the board outcome is in the window
    # SEC was last fetched at 01:00Z, so a window ending 02:00Z is honestly incomplete for it.
    assert '[SEC_EDGAR] COVERAGE INCOMPLETE' in text and '[SEC_EDGAR] Checked' not in text


def test_cli_rejects_unknown_symbol(tmp_path, capsys):
    (tmp_path / 'w.yaml').write_text(WATCHLIST, encoding='utf-8')
    dbp = str(tmp_path / 'mirror.sqlite3')
    cli.main(['--db', dbp, 'ingest', '--watchlist', str(tmp_path / 'w.yaml'), '--manual-events', 'none.csv'],
             now=NOW, out=io.StringIO(), http_get=FakeHttp())
    code = cli.main(['--db', dbp, 'checked', 'NSE', 'NOPE', '--through', '2026-09-23T06:00:00+05:30'],
                    now=NOW, out=io.StringIO())
    assert code == 2 and 'not a known symbol' in capsys.readouterr().err
