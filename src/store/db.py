"""
SQLite store access (ADR 0001 §6).

  connect()            open the database with WAL, busy_timeout and foreign keys, and apply schema.sql
  transaction()        BEGIN IMMEDIATE ... COMMIT, or ROLLBACK on any exception
  upsert_*()           idempotent writes: re-applying the same content changes nothing
  symbol_as_of(), security_id_for_symbol()
                       as-of readers over the symbol history

History rules enforced here, not left to callers:
  - A security's market, exchange, currency and timezone never change under the same key.
  - Symbol periods are half-open [valid_from, valid_to). An existing period may be closed
    (valid_to set once), but never moved or reassigned to another security.
  - No two periods of one security overlap, and no (exchange, symbol) points at two
    securities at the same time.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date
from typing import Iterator

SCHEMA_VERSION = 1
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
    with open(SCHEMA_PATH, encoding='utf-8') as f:
        conn.executescript(f.read())
    conn.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')


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
