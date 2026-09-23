"""
Store + security identity tests (ADR 0001 §6, FOCUS Step 2 / Milestone 1).

Covers the Step 2 acceptance checks:
  - loading the same 1 NSE + 1 US watchlist twice gives identical rows;
  - a symbol change adds a period and keeps history (and rows keyed on security_id) in place;
  - identity and history conflicts are rejected and rolled back.
Watchlists are small synthetic fixtures written to tmp_path; no network.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.core.calendar import load_calendars
from src.core.identity import (
    WatchlistError, isin_check_digit_ok, load_watchlist, parse_watchlist,
)
from src.store import db

ROOT = Path(__file__).resolve().parents[1]
CALENDARS = load_calendars(str(ROOT / 'config' / 'exchanges.yaml'))

T1 = datetime(2026, 9, 23, 1, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 9, 24, 1, 0, tzinfo=timezone.utc)
T3 = datetime(2026, 9, 25, 1, 0, tzinfo=timezone.utc)

IN_V1_SYMBOLS = "      - {symbol: OLDIN, valid_from: 2026-01-01}"
IN_V2_SYMBOLS = ("      - {symbol: OLDIN, valid_from: 2026-01-01, valid_to: 2026-04-01}\n"
                 "      - {symbol: NEWIN, valid_from: 2026-04-01}")


def _yaml(in_symbols=IN_V1_SYMBOLS, in_thesis='Capacity expansion', us_exchange='NASDAQ',
          include_in=True, extra=''):
    in_block = f"""
  - key: IN:NSE:TESTIN
    exchange: NSE
    name: Test India Ltd
    isin: {_valid_isin('INE000T0101')}
    symbols:
{in_symbols}
    thesis: {in_thesis}
    horizon: 2-3 years
""" if include_in else ''
    return f"""version: 1
defaults:
  move_trigger_pct: 5
securities:{in_block}
  - key: US:NASDAQ:TESTUS
    exchange: {us_exchange}
    name: Test US Inc
    cik: 1234
    symbols:
      - {{symbol: TSTU, valid_from: 2026-01-01}}
    move_trigger_pct: 8
{extra}"""


def _valid_isin(first11: str) -> str:
    """Complete a synthetic 11-character prefix with its ISO 6166 check digit."""
    return next(first11 + d for d in '0123456789' if isin_check_digit_ok(first11 + d))


def _typo(isin: str) -> str:
    """Same ISIN with a wrong check digit."""
    return isin[:-1] + str((int(isin[-1]) + 1) % 10)


def _write(tmp_path, text, name='watchlist.yaml'):
    p = tmp_path / name
    p.write_text(text, encoding='utf-8')
    return str(p)


def _load(conn, tmp_path, text, now, name='watchlist.yaml'):
    return load_watchlist(conn, parse_watchlist(_write(tmp_path, text, name), CALENDARS), now=now)


def _dump(conn):
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    return {t: [tuple(r) for r in conn.execute(f'SELECT * FROM {t} ORDER BY rowid')] for t in tables}


def _sid(conn, key):
    return conn.execute('SELECT security_id FROM security WHERE security_key = ?', (key,)).fetchone()[0]


@pytest.fixture
def conn():
    c = db.connect(':memory:')
    yield c
    c.close()


# ── Schema and connection ────────────────────────────────────────────────────

def test_schema_has_every_adr_table(conn):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert tables == {
        'security', 'security_symbol', 'watchlist_item', 'source_document', 'event',
        'price_import', 'price_bar', 'coverage_check', 'corporate_action', 'explanation',
        'explanation_evidence', 'feedback', 'ingest_run',
    }


def test_file_connection_settings_and_idempotent_schema(tmp_path):
    path = str(tmp_path / 'mirror.sqlite3')
    c = db.connect(path)
    assert c.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
    assert c.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    assert c.execute('PRAGMA busy_timeout').fetchone()[0] == db.BUSY_TIMEOUT_MS
    assert c.execute('PRAGMA user_version').fetchone()[0] == db.SCHEMA_VERSION
    _load(c, tmp_path, _yaml(), T1)
    before = _dump(c)
    c.close()
    c = db.connect(path)            # re-applies schema.sql on an existing database
    assert _dump(c) == before
    c.close()


def test_foreign_keys_are_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO security_symbol (security_id, exchange, symbol, valid_from)"
                     " VALUES (999, 'NSE', 'X', '2026-01-01')")


# ── Acceptance: duplicate load ───────────────────────────────────────────────

def test_duplicate_watchlist_load_gives_identical_rows(conn, tmp_path):
    first = _load(conn, tmp_path, _yaml(), T1)
    assert first.securities == {'IN:NSE:TESTIN': 'inserted', 'US:NASDAQ:TESTUS': 'inserted'}
    snapshot = _dump(conn)

    second = _load(conn, tmp_path, _yaml(), T2)      # later clock, same content
    assert not second.changed
    assert _dump(conn) == snapshot                   # same ids, values and timestamps

    row = conn.execute("SELECT * FROM security WHERE security_key = 'US:NASDAQ:TESTUS'").fetchone()
    assert (row['market'], row['currency'], row['timezone']) == ('US', 'USD', 'America/New_York')
    assert (row['company_id_type'], row['company_id']) == ('CIK', '0000001234')
    india = conn.execute("SELECT * FROM security WHERE security_key = 'IN:NSE:TESTIN'").fetchone()
    assert (india['currency'], india['timezone'], india['company_id']) == ('INR', 'Asia/Kolkata', None)


# ── Acceptance: symbol change preserves history ──────────────────────────────

def test_symbol_change_preserves_history(conn, tmp_path):
    _load(conn, tmp_path, _yaml(), T1)
    sid = _sid(conn, 'IN:NSE:TESTIN')

    # A price row recorded under the old symbol, keyed (as all history is) on security_id.
    conn.execute("INSERT INTO price_import (file_name, file_sha256, imported_at, row_count)"
                 " VALUES ('fixture.csv', 'abc123', '2026-03-03T00:00:00Z', 1)")
    conn.execute("INSERT INTO price_bar (security_id, trade_date, import_id, close_raw)"
                 " VALUES (?, '2026-03-02', 1, 100.0)", (sid,))

    report = _load(conn, tmp_path, _yaml(in_symbols=IN_V2_SYMBOLS), T2)
    assert report.securities['IN:NSE:TESTIN'] == 'unchanged'
    assert report.symbols['IN:NSE:TESTIN'] == ['closed', 'inserted']

    assert _sid(conn, 'IN:NSE:TESTIN') == sid
    periods = [tuple(r) for r in conn.execute(
        'SELECT symbol, valid_from, valid_to FROM security_symbol WHERE security_id = ? ORDER BY valid_from',
        (sid,))]
    assert periods == [('OLDIN', '2026-01-01', '2026-04-01'), ('NEWIN', '2026-04-01', None)]

    assert db.symbol_as_of(conn, sid, '2026-03-31') == 'OLDIN'
    assert db.symbol_as_of(conn, sid, '2026-04-01') == 'NEWIN'
    assert db.symbol_as_of(conn, sid, '2025-12-31') is None
    assert db.security_id_for_symbol(conn, 'NSE', 'OLDIN', '2026-03-02') == sid
    assert db.security_id_for_symbol(conn, 'NSE', 'OLDIN', '2026-04-02') is None
    assert db.security_id_for_symbol(conn, 'NSE', 'NEWIN', '2026-04-02') == sid
    assert conn.execute('SELECT security_id FROM price_bar').fetchone()[0] == sid

    snapshot = _dump(conn)
    assert not _load(conn, tmp_path, _yaml(in_symbols=IN_V2_SYMBOLS), T3).changed
    assert _dump(conn) == snapshot


# ── Conflicts are rejected and rolled back ───────────────────────────────────

def test_new_symbol_without_closing_old_is_rejected_and_rolled_back(conn, tmp_path):
    _load(conn, tmp_path, _yaml(), T1)
    snapshot = _dump(conn)
    # The file forgets the old period, so the store still has OLDIN open-ended.
    only_new = "      - {symbol: NEWIN, valid_from: 2026-04-01}"
    with pytest.raises(db.IdentityConflict, match='overlap'):
        _load(conn, tmp_path, _yaml(in_symbols=only_new), T2)
    assert _dump(conn) == snapshot


def test_symbol_history_is_not_rewritten(conn, tmp_path):
    _load(conn, tmp_path, _yaml(in_symbols=IN_V2_SYMBOLS), T1)
    moved = IN_V2_SYMBOLS.replace('valid_to: 2026-04-01', 'valid_to: 2026-05-01').replace(
        '{symbol: NEWIN, valid_from: 2026-04-01}', '{symbol: NEWIN, valid_from: 2026-05-01}')
    with pytest.raises(db.IdentityConflict, match='not rewritten'):
        _load(conn, tmp_path, _yaml(in_symbols=moved), T2)


def test_one_symbol_cannot_point_at_two_securities(conn, tmp_path):
    clash = """  - key: US:NASDAQ:OTHER
    exchange: NASDAQ
    name: Other Inc
    cik: 99
    symbols:
      - {symbol: TSTU, valid_from: 2026-06-01}
"""
    with pytest.raises(db.IdentityConflict):
        _load(conn, tmp_path, _yaml(extra=clash), T1)
    assert conn.execute('SELECT COUNT(*) FROM security').fetchone()[0] == 0


def test_exchange_change_under_same_key_is_rejected(conn, tmp_path):
    _load(conn, tmp_path, _yaml(), T1)
    with pytest.raises(db.IdentityConflict, match='exchange'):
        _load(conn, tmp_path, _yaml(us_exchange='NYSE'), T2)


# ── Thesis history and deactivation ──────────────────────────────────────────

def test_thesis_edit_is_logged_once(conn, tmp_path):
    _load(conn, tmp_path, _yaml(), T1)
    report = _load(conn, tmp_path, _yaml(in_thesis='Margin recovery'), T2)
    assert report.items['IN:NSE:TESTIN'] == 'updated'
    item = conn.execute('SELECT * FROM watchlist_item WHERE security_id = ?',
                        (_sid(conn, 'IN:NSE:TESTIN'),)).fetchone()
    assert item['thesis'] == 'Margin recovery' and item['updated_at'] == '2026-09-24T01:00:00Z'
    fb = conn.execute('SELECT * FROM feedback').fetchall()
    assert len(fb) == 1 and fb[0]['kind'] == 'thesis_update' and fb[0]['target_id'] == item['item_id']
    assert json.loads(fb[0]['old_value'])['thesis'] == 'Capacity expansion'
    assert json.loads(fb[0]['new_value'])['thesis'] == 'Margin recovery'

    _load(conn, tmp_path, _yaml(in_thesis='Margin recovery'), T3)
    assert conn.execute('SELECT COUNT(*) FROM feedback').fetchone()[0] == 1


def test_dropped_security_is_deactivated_not_deleted(conn, tmp_path):
    _load(conn, tmp_path, _yaml(), T1)
    report = _load(conn, tmp_path, _yaml(include_in=False), T2)
    assert report.deactivated == ['IN:NSE:TESTIN']
    sid = _sid(conn, 'IN:NSE:TESTIN')
    assert conn.execute('SELECT active FROM watchlist_item WHERE security_id = ?', (sid,)).fetchone()[0] == 0
    assert db.symbol_as_of(conn, sid, '2026-02-01') == 'OLDIN'

    _load(conn, tmp_path, _yaml(), T3)
    assert conn.execute('SELECT active FROM watchlist_item WHERE security_id = ?', (sid,)).fetchone()[0] == 1


# ── Parsing and validation ───────────────────────────────────────────────────

@pytest.mark.parametrize('mutate, message', [
    (lambda y: y.replace('    cik: 1234\n', ''), "need 'cik'"),
    (lambda y: y.replace('    exchange: NSE\n', '    exchange: NSE\n    cik: 5\n'), 'only applies to US'),
    (lambda y: y.replace('exchange: NASDAQ', 'exchange: LSE'), 'not in config/exchanges.yaml'),
    (lambda y: y.replace(_valid_isin('INE000T0101'), _typo(_valid_isin('INE000T0101'))), 'check digit'),
    (lambda y: y.replace(_valid_isin('INE000T0101'), 'US0378331005'), "start with 'IN'"),
    (lambda y: y.replace('key: US:NASDAQ:TESTUS', 'key: IN:NSE:TESTIN'), 'duplicate key'),
    (lambda y: y.replace('key: US:NASDAQ:TESTUS', 'key: us:nasdaq:testus'), 'upper-case'),
    (lambda y: y.replace('{symbol: TSTU, valid_from: 2026-01-01}',
                         '{symbol: TSTU, valid_from: 2026-01-01, valid_to: 2025-12-01}'), 'after valid_from'),
    (lambda y: y.replace('move_trigger_pct: 8', 'move_trigger_pct: 0'), 'positive'),
    (lambda y: y.replace('version: 1', 'version: 2'), 'version'),
])
def test_invalid_watchlists_are_rejected(tmp_path, mutate, message):
    with pytest.raises(WatchlistError, match=message):
        parse_watchlist(_write(tmp_path, mutate(_yaml())), CALENDARS)


def test_overlapping_periods_in_one_file_are_rejected(tmp_path):
    both_open = ("      - {symbol: OLDIN, valid_from: 2026-01-01}\n"
                 "      - {symbol: NEWIN, valid_from: 2026-04-01}")
    with pytest.raises(WatchlistError, match='overlap'):
        parse_watchlist(_write(tmp_path, _yaml(in_symbols=both_open)), CALENDARS)


def test_isin_check_digit_iso_example():
    assert isin_check_digit_ok('US0378331005')        # worked example in ISO 6166 references
    assert not isin_check_digit_ok('US0378331006')


def test_example_watchlist_parses_and_loads(conn):
    wl = parse_watchlist(str(ROOT / 'config' / 'watchlist.example.yaml'), CALENDARS)
    assert {s.exchange for s in wl.securities} == {'NSE', 'NYSE'}
    assert wl.default_move_trigger_pct == 5.0
    assert load_watchlist(conn, wl, now=T1).changed
