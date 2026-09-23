"""
Coverage states (ADR 0001 §4.4).

For one (security, source, window) evaluated as of time T, exactly one state:

  checked_with_events   coverage is complete (ok check windows plus the covered spans of partial
                        checks contain the whole window), and >=1 visible event from the source
                        has published_at in the window
  checked_no_events     coverage is complete, and no such event exists
  source_failed         not fully covered, and the latest overlapping attempt failed
  coverage_incomplete   not fully covered, latest attempt did not fail, some ok/partial check overlaps
  not_checked           no check overlaps the window

Only checks with checked_at <= T and event versions with first_seen_at <= T count, so the
answer is what MIRROR could honestly have said at T. Complete coverage is decided first:
a later failed retry does not erase an earlier complete check. A partial check counts only for
the spans it recorded (coverage_span); the rest of its window stays a gap.

Windows are (start, end] in 'YYYY-MM-DDTHH:MM:SSZ' text (fixed width, so string order is
time order). A check covers [window_start, window_end].
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from src.store import db

CHECKED_WITH_EVENTS = 'checked_with_events'
CHECKED_NO_EVENTS = 'checked_no_events'
SOURCE_FAILED = 'source_failed'
COVERAGE_INCOMPLETE = 'coverage_incomplete'
NOT_CHECKED = 'not_checked'
STATES = (CHECKED_WITH_EVENTS, CHECKED_NO_EVENTS, SOURCE_FAILED, COVERAGE_INCOMPLETE, NOT_CHECKED)

# Sources a market needs before a security can be called "checked" (ADR §4.4).
REQUIRED_SOURCES = {'US': ('SEC_EDGAR',), 'IN': ('MANUAL_NSE',)}


@dataclass
class Coverage:
    security_id: int
    source: str
    window_start: str
    window_end: str
    state: str
    detail: str
    events: list = field(default_factory=list)       # visible event rows in the window


def covers(intervals: list[tuple[str, str]], start: str, end: str) -> bool:
    """True if the union of closed intervals contains [start, end]."""
    reach = start
    for lo, hi in sorted(intervals):
        if lo > reach:
            break
        if hi > reach:
            reach = hi
        if reach >= end:
            return True
    return reach >= end


def coverage(conn: sqlite3.Connection, *, security_id: int, source: str, window_start: str,
             window_end: str, as_of: str) -> Coverage:
    if window_end <= window_start:
        raise ValueError('window_end must be after window_start')
    if window_end > as_of:
        raise ValueError('a window cannot end after the as-of time')

    checks = conn.execute(
        'SELECT * FROM coverage_check WHERE security_id = ? AND source = ? AND checked_at <= ?'
        ' AND window_start <= ? AND window_end >= ? ORDER BY checked_at, check_id',
        (security_id, source, as_of, window_end, window_start)).fetchall()
    events = db.events_as_of(conn, as_of=as_of, security_id=security_id, source=source,
                             published_after=window_start, published_through=window_end)
    result = Coverage(security_id, source, window_start, window_end, NOT_CHECKED, '', list(events))

    covered = db.covered_intervals(conn, security_id, source, as_of=as_of)    # ok windows + partial spans
    if covers(covered, window_start, window_end):
        through = max(hi for _, hi in covered)
        n = len(events)
        if n:
            result.state = CHECKED_WITH_EVENTS
            result.detail = f"checked through {through}: {n} new disclosure{'s' if n > 1 else ''}"
        else:
            result.state = CHECKED_NO_EVENTS
            result.detail = f"checked through {through}: no new disclosures"
        return result

    if not checks:
        last = conn.execute("SELECT MAX(window_end) FROM coverage_check WHERE security_id = ? AND source = ?"
                            " AND status = 'ok' AND checked_at <= ?", (security_id, source, as_of)).fetchone()[0]
        result.detail = f"no check since {last}" if last else 'never checked'
        return result

    latest = checks[-1]
    if latest['status'] == 'failed':
        last_ok = conn.execute("SELECT MAX(checked_at) FROM coverage_check WHERE security_id = ? AND source = ?"
                               " AND status = 'ok' AND checked_at <= ?", (security_id, source, as_of)).fetchone()[0]
        result.state = SOURCE_FAILED
        result.detail = (f"failed at {latest['checked_at']} ({latest['error'] or 'no error text'}); "
                         f"last success {last_ok or 'never'}")
        return result

    result.state = COVERAGE_INCOMPLETE
    spans = [f"{c['window_start']}–{c['window_end']}"
             + (f" ({c['status']}: {c['scope_note']})" if c['scope_note'] else f" ({c['status']})")
             for c in checks if c['status'] in ('ok', 'partial')]
    result.detail = 'checked only ' + '; '.join(spans)
    return result


def security_coverage(conn: sqlite3.Connection, *, security_id: int, market: str, window_start: str,
                      window_end: str, as_of: str) -> list[Coverage]:
    """Coverage for every source the security's market requires."""
    return [coverage(conn, security_id=security_id, source=src, window_start=window_start,
                     window_end=window_end, as_of=as_of)
            for src in REQUIRED_SOURCES[market]]
