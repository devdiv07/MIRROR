"""
SQLite store access (ADR 0001 §6).

  connect()            open the database with WAL, busy_timeout and foreign keys, and apply schema.sql
  transaction()        BEGIN IMMEDIATE ... COMMIT, or ROLLBACK on any exception
  upsert_*()           idempotent writes: re-applying the same content changes nothing
  symbol_as_of(), security_id_for_symbol()
                       as-of readers over the symbol history
  upsert_source_document(), upsert_event_version(), events_as_of()
                       versioned documents/events and the as-of event reader (ADR §4.2)
  insert_coverage_check(), covered_intervals(), resume_point(), start_ingest_run(), finish_ingest_run()

History rules enforced here, not left to callers:
  - A security's market, exchange, currency and timezone never change under the same key.
  - Symbol periods are half-open [valid_from, valid_to). An existing period may be closed
    (valid_to set once), but never moved or reassigned to another security.
  - No two periods of one security overlap, and no (exchange, symbol) points at two
    securities at the same time.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Iterator

SCHEMA_VERSION = 3
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), 'schema.sql')
DEFAULT_DB_PATH = os.path.join('data', 'mirror.sqlite3')
BUSY_TIMEOUT_MS = 5000

_OPEN_END = '9999-12-31'


class IdentityConflict(ValueError):
    """A write would change a security's identity or rewrite symbol history."""


def connect(path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open (creating if needed) the MIRROR database and bring its schema up to date."""
    conn = sqlite3.connect(path, isolation_level=None)   # autocommit; transactions are explicit
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute(f'PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}')
    if path != ':memory:':
        conn.execute('PRAGMA journal_mode = WAL')
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    version = conn.execute('PRAGMA user_version').fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError(f"database schema v{version} is newer than this code (v{SCHEMA_VERSION})")
    if version == 1:
        _migrate_1_to_2(conn)
    with open(SCHEMA_PATH, encoding='utf-8') as f:
        conn.executescript(f.read())
    conn.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')


def _migrate_1_to_2(conn: sqlite3.Connection) -> None:
    """v2 versions events and documents (ADR §6 Milestone 2 amendment).

    v1 had no code that wrote source_document or event rows, so both tables are expected to be
    empty and are dropped for schema.sql to recreate. If they hold rows, refuse rather than guess.
    """
    for table in ('event', 'source_document'):
        n = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        if n:
            raise RuntimeError(f"cannot upgrade schema v1 -> v2: {table} has {n} rows; migrate them by hand")
    conn.execute('DROP TABLE event')
    conn.execute('DROP TABLE source_document')


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute('BEGIN IMMEDIATE')
    try:
        yield conn
    except BaseException:
        conn.execute('ROLLBACK')
        raise
    conn.execute('COMMIT')


def _iso(d: date | str | None) -> str | None:
    return d.isoformat() if isinstance(d, date) else d


def utc_iso(dt: datetime) -> str:
    """The store's timestamp format: 'YYYY-MM-DDTHH:MM:SSZ'. Fixed width, so text order = time order."""
    if dt.tzinfo is None:
        raise ValueError('timestamps must be timezone-aware')
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_utc(text: str) -> datetime:
    return datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)


def sha256_json(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


# ── security ─────────────────────────────────────────────────────────────────

_IMMUTABLE = ('market', 'exchange', 'currency', 'timezone')
_MUTABLE = ('name', 'company_id_type', 'company_id', 'isin')


def upsert_security(conn: sqlite3.Connection, *, security_key: str, market: str, exchange: str,
                    name: str, currency: str, timezone: str, company_id_type: str | None = None,
                    company_id: str | None = None, isin: str | None = None,
                    now: str) -> tuple[int, str]:
    """Insert or update one security by its stable key. Returns (security_id, 'inserted'|'updated'|'unchanged')."""
    values = dict(market=market, exchange=exchange, currency=currency, timezone=timezone,
                  name=name, company_id_type=company_id_type, company_id=company_id, isin=isin)
    row = conn.execute('SELECT * FROM security WHERE security_key = ?', (security_key,)).fetchone()
    if row is None:
        cur = conn.execute(
            'INSERT INTO security (security_key, market, exchange, name, company_id_type, company_id,'
            ' isin, currency, timezone, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (security_key, market, exchange, name, company_id_type, company_id, isin,
             currency, timezone, now, now))
        return cur.lastrowid, 'inserted'

    for field in _IMMUTABLE:
        if row[field] != values[field]:
            raise IdentityConflict(
                f"security {security_key!r}: {field} is {row[field]!r} in the store but {values[field]!r} "
                f"in the input. A different {field} is a different listing; give it a new key.")
    changed = {f: values[f] for f in _MUTABLE if row[f] != values[f]}
    if not changed:
        return row['security_id'], 'unchanged'
    sets = ', '.join(f'{f} = ?' for f in changed)
    conn.execute(f'UPDATE security SET {sets}, updated_at = ? WHERE security_id = ?',
                 (*changed.values(), now, row['security_id']))
    return row['security_id'], 'updated'


# ── symbol history ───────────────────────────────────────────────────────────

def upsert_symbol_period(conn: sqlite3.Connection, *, security_id: int, exchange: str, symbol: str,
                         valid_from: date | str, valid_to: date | str | None) -> str:
    """Record one symbol period. Returns 'inserted' | 'closed' | 'unchanged'."""
    vf, vt = _iso(valid_from), _iso(valid_to)
    row = conn.execute(
        'SELECT symbol_id, security_id, valid_to FROM security_symbol'
        ' WHERE exchange = ? AND symbol = ? AND valid_from = ?', (exchange, symbol, vf)).fetchone()
    if row is None:
        conn.execute('INSERT INTO security_symbol (security_id, exchange, symbol, valid_from, valid_to)'
                     ' VALUES (?,?,?,?,?)', (security_id, exchange, symbol, vf, vt))
        return 'inserted'
    if row['security_id'] != security_id:
        raise IdentityConflict(f"{exchange}:{symbol} from {vf} already belongs to security_id {row['security_id']}")
    if row['valid_to'] == vt:
        return 'unchanged'
    if row['valid_to'] is None and vt is not None:
        conn.execute('UPDATE security_symbol SET valid_to = ? WHERE symbol_id = ?', (vt, row['symbol_id']))
        return 'closed'
    raise IdentityConflict(
        f"{exchange}:{symbol} from {vf}: stored valid_to {row['valid_to']!r} cannot change to {vt!r}; "
        f"symbol history is not rewritten")


def check_symbol_invariants(conn: sqlite3.Connection) -> None:
    """Raise IdentityConflict if any two symbol periods overlap for one security or one (exchange, symbol)."""
    overlap = (f"a.valid_from < COALESCE(b.valid_to, '{_OPEN_END}')"
               f" AND b.valid_from < COALESCE(a.valid_to, '{_OPEN_END}')")
    same_security = conn.execute(
        'SELECT a.security_id, a.symbol, a.valid_from, b.symbol, b.valid_from FROM security_symbol a'
        ' JOIN security_symbol b ON a.security_id = b.security_id AND a.symbol_id < b.symbol_id'
        f' WHERE {overlap}').fetchone()
    if same_security:
        sid, s1, f1, s2, f2 = same_security
        raise IdentityConflict(
            f"security_id {sid}: symbol periods {s1} (from {f1}) and {s2} (from {f2}) overlap. "
            f"Close the old period with valid_to = the new symbol's valid_from.")
    same_symbol = conn.execute(
        'SELECT a.exchange, a.symbol, a.security_id, b.security_id FROM security_symbol a'
        ' JOIN security_symbol b ON a.exchange = b.exchange AND a.symbol = b.symbol'
        ' AND a.security_id <> b.security_id AND a.symbol_id < b.symbol_id'
        f' WHERE {overlap}').fetchone()
    if same_symbol:
        ex, sym, s1, s2 = same_symbol
        raise IdentityConflict(f"{ex}:{sym} points at security_ids {s1} and {s2} in overlapping periods")


def symbol_as_of(conn: sqlite3.Connection, security_id: int, on: date | str) -> str | None:
    """The security's symbol on day `on`, or None if no period covers it."""
    row = conn.execute(
        'SELECT symbol FROM security_symbol WHERE security_id = ? AND valid_from <= ?'
        ' AND (valid_to IS NULL OR valid_to > ?)', (security_id, _iso(on), _iso(on))).fetchone()
    return row['symbol'] if row else None


def security_id_for_symbol(conn: sqlite3.Connection, exchange: str, symbol: str,
                           on: date | str) -> int | None:
    """Which security `exchange:symbol` referred to on day `on`, or None."""
    row = conn.execute(
        'SELECT security_id FROM security_symbol WHERE exchange = ? AND symbol = ? AND valid_from <= ?'
        ' AND (valid_to IS NULL OR valid_to > ?)', (exchange, symbol, _iso(on), _iso(on))).fetchone()
    return row['security_id'] if row else None


# ── watchlist items ──────────────────────────────────────────────────────────

def upsert_watchlist_item(conn: sqlite3.Connection, *, security_id: int, thesis: str | None,
                          horizon: str | None, move_trigger_pct: float | None, now: str) -> str:
    """Insert, reactivate or update one watchlist item. Returns 'inserted'|'updated'|'unchanged'.

    A thesis or horizon change is appended to `feedback` (kind 'thesis_update') with the old and
    new values, so the history of the owner's reasoning is kept even though the item holds the
    current text.
    """
    row = conn.execute('SELECT * FROM watchlist_item WHERE security_id = ?', (security_id,)).fetchone()
    if row is None:
        conn.execute('INSERT INTO watchlist_item (security_id, thesis, horizon, move_trigger_pct,'
                     ' active, added_at, updated_at) VALUES (?,?,?,?,1,?,?)',
                     (security_id, thesis, horizon, move_trigger_pct, now, now))
        return 'inserted'

    thesis_changed = (row['thesis'], row['horizon']) != (thesis, horizon)
    other_changed = row['move_trigger_pct'] != move_trigger_pct or row['active'] != 1
    if not (thesis_changed or other_changed):
        return 'unchanged'
    if thesis_changed:
        conn.execute(
            'INSERT INTO feedback (created_at, target_type, target_id, kind, old_value, new_value)'
            " VALUES (?, 'watchlist_item', ?, 'thesis_update', ?, ?)",
            (now, row['item_id'],
             json.dumps({'thesis': row['thesis'], 'horizon': row['horizon']}),
             json.dumps({'thesis': thesis, 'horizon': horizon})))
    conn.execute('UPDATE watchlist_item SET thesis = ?, horizon = ?, move_trigger_pct = ?, active = 1,'
                 ' updated_at = ? WHERE item_id = ?',
                 (thesis, horizon, move_trigger_pct, now, row['item_id']))
    return 'updated'


def deactivate_items_except(conn: sqlite3.Connection, keep_security_ids: set[int], now: str) -> list[str]:
    """Mark active items not in keep_security_ids inactive (rows are kept). Returns their security keys."""
    rows = conn.execute('SELECT w.item_id, w.security_id, s.security_key FROM watchlist_item w'
                        ' JOIN security s USING (security_id) WHERE w.active = 1').fetchall()
    gone = [r for r in rows if r['security_id'] not in keep_security_ids]
    for r in gone:
        conn.execute('UPDATE watchlist_item SET active = 0, updated_at = ? WHERE item_id = ?',
                     (now, r['item_id']))
    return sorted(r['security_key'] for r in gone)


# ── versioned documents and events (ADR §4.2) ────────────────────────────────

def upsert_source_document(conn: sqlite3.Connection, *, source: str, source_doc_key: str, url: str | None,
                           content_sha256: str, published_at: str | None, published_basis: str,
                           first_seen_at: str, tz_assumed: bool = False,
                           raw_path: str | None = None) -> tuple[int, str]:
    """Record a document version. Returns (doc_id, 'inserted' | 'new_version' | 'unchanged').

    Compared with the latest version only: equal content is a no-op, anything else is version n+1.
    """
    latest = conn.execute(
        'SELECT doc_id, version, content_sha256 FROM source_document WHERE source = ? AND source_doc_key = ?'
        ' ORDER BY version DESC LIMIT 1', (source, source_doc_key)).fetchone()
    if latest is not None and latest['content_sha256'] == content_sha256:
        return latest['doc_id'], 'unchanged'
    version = 1 if latest is None else latest['version'] + 1
    cur = conn.execute(
        'INSERT INTO source_document (source, source_doc_key, url, content_sha256, version, published_at,'
        ' published_basis, tz_assumed, first_seen_at, raw_path) VALUES (?,?,?,?,?,?,?,?,?,?)',
        (source, source_doc_key, url, content_sha256, version, published_at, published_basis,
         int(tz_assumed), first_seen_at, raw_path))
    return cur.lastrowid, 'inserted' if version == 1 else 'new_version'


def event_dedup_key(security_id: int, source: str, source_doc_key: str) -> str:
    return hashlib.sha256(f'{security_id}|{source}|{source_doc_key}'.encode()).hexdigest()


def upsert_event_version(conn: sqlite3.Connection, *, security_id: int, source: str, source_doc_key: str,
                         doc_id: int, event_type: str, subject: str, event_time: str | None,
                         published_at: str | None, first_seen_at: str,
                         fields: dict | None = None) -> tuple[int, str]:
    """Record one version of a logical event. Returns (event_id, 'inserted' | 'new_version' | 'unchanged')."""
    fields = fields or {}
    content = sha256_json({'event_type': event_type, 'subject': subject, 'event_time': event_time,
                           'published_at': published_at, 'fields': fields})
    key = event_dedup_key(security_id, source, source_doc_key)
    latest = conn.execute('SELECT event_id, version, content_sha256 FROM event WHERE dedup_key = ?'
                          ' ORDER BY version DESC LIMIT 1', (key,)).fetchone()
    if latest is not None and latest['content_sha256'] == content:
        return latest['event_id'], 'unchanged'
    version = 1 if latest is None else latest['version'] + 1
    cur = conn.execute(
        'INSERT INTO event (security_id, doc_id, dedup_key, version, content_sha256, event_type, subject,'
        ' event_time, published_at, first_seen_at, fields_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
        (security_id, doc_id, key, version, content, event_type, subject, event_time, published_at,
         first_seen_at, json.dumps(fields, sort_keys=True)))
    return cur.lastrowid, 'inserted' if version == 1 else 'new_version'


def events_as_of(conn: sqlite3.Connection, *, as_of: str, security_id: int | None = None,
                 source: str | None = None, published_after: str | None = None,
                 published_through: str | None = None) -> list[sqlite3.Row]:
    """Events visible at `as_of`: per logical event, the highest version with first_seen_at <= as_of.

    Optional filters: security, source, and published_at in (published_after, published_through].
    Rows include the document's source, url, published_basis and tz_assumed.
    """
    sql = ['SELECT e.*, d.source, d.source_doc_key, d.url, d.published_basis, d.tz_assumed',
           'FROM event e JOIN source_document d ON d.doc_id = e.doc_id',
           'WHERE e.first_seen_at <= :as_of',
           'AND e.version = (SELECT MAX(e2.version) FROM event e2',
           '                 WHERE e2.dedup_key = e.dedup_key AND e2.first_seen_at <= :as_of)']
    params = {'as_of': as_of}
    if security_id is not None:
        sql.append('AND e.security_id = :sid')
        params['sid'] = security_id
    if source is not None:
        sql.append('AND d.source = :source')
        params['source'] = source
    if published_after is not None:
        sql.append('AND e.published_at > :after')
        params['after'] = published_after
    if published_through is not None:
        sql.append('AND e.published_at <= :through')
        params['through'] = published_through
    sql.append('ORDER BY e.published_at, e.event_id')
    return conn.execute(' '.join(sql), params).fetchall()


# ── coverage checks and ingest runs ──────────────────────────────────────────

def insert_coverage_check(conn: sqlite3.Connection, *, security_id: int, source: str, method: str,
                          window_start: str, window_end: str, checked_at: str, status: str,
                          scope_note: str | None = None, error: str | None = None,
                          run_id: int | None = None,
                          covered_spans: list[tuple[str, str]] | None = None) -> int:
    """Record one check. `covered_spans` (partial checks only) are the parts of the window it covered."""
    spans = [(max(lo, window_start), min(hi, window_end)) for lo, hi in covered_spans or []]
    spans = [(lo, hi) for lo, hi in spans if hi > lo]
    if spans and status != 'partial':
        raise ValueError(f"covered spans belong to a 'partial' check, not {status!r}")
    cur = conn.execute(
        'INSERT INTO coverage_check (security_id, source, method, window_start, window_end, checked_at,'
        ' status, scope_note, error, run_id) VALUES (?,?,?,?,?,?,?,?,?,?)',
        (security_id, source, method, window_start, window_end, checked_at, status, scope_note, error, run_id))
    conn.executemany('INSERT INTO coverage_span (check_id, covered_from, covered_to) VALUES (?,?,?)',
                     [(cur.lastrowid, lo, hi) for lo, hi in spans])
    return cur.lastrowid


def covered_intervals(conn: sqlite3.Connection, security_id: int, source: str,
                      as_of: str | None = None) -> list[tuple[str, str]]:
    """What (security, source) checks have covered: whole windows of ok checks plus the spans of
    partial checks, counting only checks with checked_at <= as_of when as_of is given."""
    when = ' AND c.checked_at <= :as_of' if as_of else ''
    params = {'sid': security_id, 'source': source, 'as_of': as_of}
    ok = conn.execute('SELECT c.window_start, c.window_end FROM coverage_check c WHERE c.security_id = :sid'
                      f" AND c.source = :source AND c.status = 'ok'{when}", params).fetchall()
    spans = conn.execute('SELECT s.covered_from, s.covered_to FROM coverage_span s JOIN coverage_check c'
                         ' USING (check_id) WHERE c.security_id = :sid AND c.source = :source'
                         f" AND c.status = 'partial'{when}", params).fetchall()
    return sorted((lo, hi) for lo, hi in ok + spans)


def resume_point(conn: sqlite3.Connection, security_id: int, source: str) -> str | None:
    """Where the next automatic check must start so that no gap is skipped, or None if never checked.

    Walking forward from the earliest window any check (ok, partial or failed) was asked to cover,
    this is the first moment that no ok window or partial span covers. With no gaps it is the end
    of the latest coverage; after a partial backfill or a failed run it is the start of the gap.
    """
    first = conn.execute('SELECT MIN(window_start) FROM coverage_check WHERE security_id = ? AND source = ?',
                         (security_id, source)).fetchone()[0]
    if first is None:
        return None
    reach = first
    for lo, hi in covered_intervals(conn, security_id, source):
        if lo > reach:
            break
        reach = max(reach, hi)
    return reach


def last_covered_through(conn: sqlite3.Connection, security_id: int, source: str) -> str | None:
    """End of the latest ok/partial check for (security, source): where the next *manual* check
    resumes. A manual partial check is limited by scope, not time, and the owner chose to go on."""
    row = conn.execute("SELECT MAX(window_end) FROM coverage_check WHERE security_id = ? AND source = ?"
                       " AND status IN ('ok', 'partial')", (security_id, source)).fetchone()
    return row[0]


def start_ingest_run(conn: sqlite3.Connection, source: str, started_at: str) -> int:
    return conn.execute('INSERT INTO ingest_run (source, started_at) VALUES (?, ?)',
                        (source, started_at)).lastrowid


def finish_ingest_run(conn: sqlite3.Connection, run_id: int, *, finished_at: str, status: str,
                      records_new: int, error: str | None = None) -> None:
    conn.execute('UPDATE ingest_run SET finished_at = ?, status = ?, records_new = ?, error = ? WHERE run_id = ?',
                 (finished_at, status, records_new, error, run_id))
