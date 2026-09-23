"""
Daily price CSV import (ADR 0001 §5.1, §6; Milestone 3).

One file -> one price_import row (file name, sha256 of the exact bytes, declared upstream, import
time) and its price_bar rows. The same bytes imported again change nothing. A corrected file has a
different hash, so it becomes a new import, and readers take, per (security, day), the bar from the
newest import visible as of their time (db.price_bars_as_of). Nothing is edited in place.

File format (MIRROR's own schema; convert a vendor export into it):

    # vendor: <who produced the numbers>          optional; absent = 'unknown'
    # source_url: https://...                     optional; absent = no upstream link
    # as_of: 2026-09-23T21:00:00Z                 optional; the vendor's own timestamp, with offset
    security_key,trade_date,open,high,low,close,volume,adj_close
    US:NASDAQ:AAPL,2026-09-22,...

The declarations sit inside the file, so the file hash covers them. Required columns: security_key,
trade_date, close. The others may be empty. close is the raw (unadjusted) close; adj_close is kept
only to cross-check MIRROR's own adjustment (ADR §7).

A file is imported whole or not at all. Rejected: an unknown security, a day the exchange was
closed or whose calendar year is not configured, a session that has not closed yet, a repeated
(security, day), non-positive or non-finite prices, negative volume, and inconsistent OHLC.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from src.core.calendar import CalendarNotCovered, ExchangeCalendar
from src.store import db

DECLARATIONS = ('vendor', 'source_url', 'as_of')
REQUIRED = ('security_key', 'trade_date', 'close')
OPTIONAL = ('open', 'high', 'low', 'volume', 'adj_close')


class PriceInputError(ValueError):
    """A price file is malformed or inconsistent; nothing from it was stored."""


@dataclass
class PriceImport:
    import_id: int
    status: str                 # 'inserted' | 'unchanged' (the same bytes were imported before)
    file_name: str
    file_sha256: str
    rows: int


def _number(text: str | None, where: str, column: str, *, positive: bool) -> float | None:
    text = (text or '').strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        raise PriceInputError(f"{where}: {column} {text!r} is not a number") from None
    if not math.isfinite(value) or (value <= 0 if positive else value < 0):
        raise PriceInputError(f"{where}: {column} must be a finite {'positive' if positive else 'non-negative'}"
                              f" number, got {text!r}")
    return value


def _split(raw: bytes, path: str) -> tuple[dict, list[str]]:
    """Leading '# key: value' declarations, then the CSV lines."""
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise PriceInputError(f"{path}: not UTF-8 text") from None
    lines = text.splitlines()
    declared, n = {}, 0
    while n < len(lines) and lines[n].lstrip().startswith('#'):
        key, sep, value = lines[n].lstrip()[1:].partition(':')
        key = key.strip().lower()
        if not sep or key not in DECLARATIONS:
            raise PriceInputError(f"{path}:{n + 1}: declarations are '# key: value' with key one of {DECLARATIONS}")
        if key in declared:
            raise PriceInputError(f"{path}:{n + 1}: {key} declared twice")
        declared[key] = value.strip()
        n += 1
    return declared, lines[n:]


def _session_closed_by(cal: ExchangeCalendar, day: date, now: datetime, where: str) -> None:
    try:
        session = cal.session(day)
    except CalendarNotCovered as e:
        raise PriceInputError(f"{where}: {e}") from None
    if session is None:
        raise PriceInputError(f"{where}: {cal.code} was closed on {day} ({cal.closure_reason(day)})")
    closed_at = session.close_utc() or datetime.combine(day + timedelta(days=1), time(0), tzinfo=cal.tz)
    if closed_at > now:
        raise PriceInputError(f"{where}: the {cal.code} session of {day} had not closed at import time")


def import_price_file(conn, path: str, *, now: datetime, calendars: dict[str, ExchangeCalendar]) -> PriceImport:
    with open(path, 'rb') as f:
        raw = f.read()
    sha = hashlib.sha256(raw).hexdigest()
    name = os.path.basename(path)
    existing = conn.execute('SELECT import_id, row_count FROM price_import WHERE file_sha256 = ?', (sha,)).fetchone()
    if existing is not None:
        return PriceImport(existing['import_id'], 'unchanged', name, sha, existing['row_count'])

    declared, lines = _split(raw, path)
    url = declared.get('source_url') or None
    if url is not None and not url.startswith('https://'):
        raise PriceInputError(f"{path}: source_url must be an https link")
    vendor_as_of = None
    if declared.get('as_of'):
        try:
            as_of = datetime.fromisoformat(declared['as_of'])
        except ValueError:
            raise PriceInputError(f"{path}: as_of {declared['as_of']!r} is not an ISO time") from None
        if as_of.tzinfo is None:
            raise PriceInputError(f"{path}: as_of needs a UTC offset, e.g. 2026-09-23T21:00:00Z")
        vendor_as_of = db.utc_iso(as_of)

    reader = csv.DictReader(io.StringIO('\n'.join(lines)))
    missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
    if missing:
        raise PriceInputError(f"{path}: missing columns {missing}")
    bars, seen = [], set()
    securities: dict[str, tuple[int, ExchangeCalendar]] = {}
    for n, r in enumerate(reader, start=2 + len(declared)):
        where = f"{path}:{n}"
        key = (r['security_key'] or '').strip()
        if key not in securities:
            row = conn.execute('SELECT security_id, exchange FROM security WHERE security_key = ?', (key,)).fetchone()
            if row is None:
                raise PriceInputError(f"{where}: unknown security_key {key!r}; load the watchlist first")
            securities[key] = (row['security_id'], calendars[row['exchange']])
        sid, cal = securities[key]
        try:
            day = date.fromisoformat((r['trade_date'] or '').strip())
        except ValueError:
            raise PriceInputError(f"{where}: trade_date {r['trade_date']!r} is not YYYY-MM-DD") from None
        if (key, day) in seen:
            raise PriceInputError(f"{where}: a second row for {key} on {day}")
        seen.add((key, day))
        _session_closed_by(cal, day, now, where)

        close = _number(r['close'], where, 'close', positive=True)
        if close is None:
            raise PriceInputError(f"{where}: close is required")
        o, h, lo = (_number(r.get(c), where, c, positive=True) for c in ('open', 'high', 'low'))
        known = [v for v in (o, close) if v is not None]
        if (h is not None and h < max(known)) or (lo is not None and lo > min(known)) \
                or (h is not None and lo is not None and lo > h):
            raise PriceInputError(f"{where}: open/high/low/close are inconsistent")
        bars.append((sid, day.isoformat(), o, h, lo, close, _number(r.get('volume'), where, 'volume', positive=False),
                     _number(r.get('adj_close'), where, 'adj_close', positive=True)))
    if not bars:
        raise PriceInputError(f"{path}: no price rows")

    with db.transaction(conn):
        import_id = db.insert_price_import(
            conn, file_name=name, file_sha256=sha, declared_vendor=declared.get('vendor') or 'unknown',
            declared_source_url=url, vendor_as_of=vendor_as_of, imported_at=db.utc_iso(now), row_count=len(bars))
        conn.executemany(
            'INSERT INTO price_bar (security_id, trade_date, import_id, open, high, low, close_raw, volume,'
            ' close_vendor_adj) VALUES (?,?,?,?,?,?,?,?,?)',
            [(sid, d, import_id, o, h, lo, c, v, adj) for sid, d, o, h, lo, c, v, adj in bars])
    return PriceImport(import_id, 'inserted', name, sha, len(bars))
