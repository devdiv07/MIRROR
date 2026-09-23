"""
Manual NSE events and manual coverage checks (ADR 0001 §4.1, §4.4; Milestone 2).

NSE disclosures are entered by the owner, because NSE's website terms prohibit automated
collection and no permitted feed has been chosen yet (ADR §4.3). Two separate records:

  import_manual_events()  data/manual_events.csv -> versioned documents + events.
                          Entering an event does NOT mark the stock as checked (case C4).
  record_manual_check()   "I reviewed NSE for SYMBOL through time T" -> one coverage_check.

CSV columns: security_key, url, subject, published_at, event_type[, event_time]
  - url is the NSE announcement or attachment link and identifies the logical event, so a
    corrected row with the same url becomes version n+1 (ADR §4.2), never a second event.
  - published_at is the dissemination time as shown by NSE. With an offset
    ('2026-03-02T08:40:00+05:30') it is exact; without one ('2026-03-02 08:40') it is read as
    Asia/Kolkata and stored with tz_assumed = 1.
  - subject is copied verbatim from NSE.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from src.store import db

SOURCE = 'MANUAL_NSE'
EXCHANGE = 'NSE'
EVENT_TYPES = ('results', 'board_outcome', 'corporate_action', 'other_disclosure')
_IST = ZoneInfo('Asia/Kolkata')
_REQUIRED = ('security_key', 'url', 'subject', 'published_at', 'event_type')


class ManualInputError(ValueError):
    """A manual event row or check request is invalid."""


def parse_local_time(text: str, where: str) -> tuple[datetime, bool]:
    """Parse an ISO time. Returns (aware datetime, tz_assumed). No offset means Asia/Kolkata."""
    try:
        dt = datetime.fromisoformat(text.strip().replace(' ', 'T', 1))
    except ValueError as e:
        raise ManualInputError(f"{where}: expected an ISO time like 2026-03-02T08:40:00+05:30, got {text!r}") from e
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_IST), True
    return dt, False


def _nse_security(conn, key: str, where: str):
    row = conn.execute('SELECT security_id, exchange FROM security WHERE security_key = ?', (key,)).fetchone()
    if row is None:
        raise ManualInputError(f"{where}: unknown security_key {key!r}; load the watchlist first")
    if row['exchange'] != EXCHANGE:
        raise ManualInputError(f"{where}: {key} is on {row['exchange']}, not NSE")
    return row['security_id']


@dataclass
class ManualReport:
    run_id: int
    rows: int = 0
    statuses: dict = field(default_factory=dict)    # url -> inserted|new_version|unchanged


def import_manual_events(conn, path: str, *, now: datetime) -> ManualReport:
    """Import every row of the CSV in one transaction; an invalid row aborts the whole import."""
    seen_at = db.utc_iso(now)
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        missing = [c for c in _REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            raise ManualInputError(f"{path}: missing columns {missing}")
        rows = list(reader)

    run_id = db.start_ingest_run(conn, SOURCE, seen_at)
    report = ManualReport(run_id)
    try:
        with db.transaction(conn):
            for n, r in enumerate(rows, start=2):
                where = f"{path}:{n}"
                sid = _nse_security(conn, r['security_key'].strip(), where)
                url = r['url'].strip()
                if not url.startswith('https://'):
                    raise ManualInputError(f"{where}: url must be an https link to the NSE disclosure")
                subject = r['subject'].strip()
                if not subject:
                    raise ManualInputError(f"{where}: subject is required (copy it verbatim from NSE)")
                event_type = r['event_type'].strip()
                if event_type not in EVENT_TYPES:
                    raise ManualInputError(f"{where}: event_type must be one of {EVENT_TYPES}")
                published, tz_assumed = parse_local_time(r['published_at'], where)
                published_at = db.utc_iso(published)
                if published_at > seen_at:
                    raise ManualInputError(f"{where}: published_at {published_at} is in the future")
                event_time = (r.get('event_time') or '').strip() or None
                fields = {'tz_assumed': tz_assumed}
                content = db.sha256_json({'url': url, 'subject': subject, 'event_type': event_type,
                                          'published_at': published_at, 'event_time': event_time,
                                          'tz_assumed': tz_assumed})
                doc_id, _ = db.upsert_source_document(
                    conn, source=SOURCE, source_doc_key=url, url=url, content_sha256=content,
                    published_at=published_at, published_basis='user_entered', first_seen_at=seen_at,
                    tz_assumed=tz_assumed)
                _, status = db.upsert_event_version(
                    conn, security_id=sid, source=SOURCE, source_doc_key=url, doc_id=doc_id,
                    event_type=event_type, subject=subject, event_time=event_time,
                    published_at=published_at, first_seen_at=seen_at, fields=fields)
                report.statuses[url] = status
                report.rows += 1
    except Exception as e:
        db.finish_ingest_run(conn, run_id, finished_at=seen_at, status='failed', records_new=0, error=str(e))
        raise
    new = sum(s != 'unchanged' for s in report.statuses.values())
    db.finish_ingest_run(conn, run_id, finished_at=seen_at, status='ok', records_new=new)
    return report


def record_manual_check(conn, *, security_key: str, through: datetime, now: datetime,
                        start: datetime | None = None, partial: bool = False,
                        note: str | None = None) -> int:
    """Record that the owner reviewed NSE for this security up to `through`.

    The window starts at `start`, or where the previous manual check ended. A first check needs
    an explicit start, because "checked" must say from when.
    """
    where = f"checked {security_key}"
    sid = _nse_security(conn, security_key, where)
    checked_at = db.utc_iso(now)
    end = db.utc_iso(through)
    if end > checked_at:
        raise ManualInputError(f"{where}: cannot record a check through {end}, which is after now ({checked_at})")
    begin = db.utc_iso(start) if start else db.last_covered_through(conn, sid, SOURCE)
    if begin is None:
        raise ManualInputError(f"{where}: first manual check needs --from (when your review started)")
    if end <= begin:
        raise ManualInputError(f"{where}: --through {end} must be after the window start {begin}")
    if partial and not (note or '').strip():
        raise ManualInputError(f"{where}: a partial check needs --note saying what was covered")
    with db.transaction(conn):
        return db.insert_coverage_check(
            conn, security_id=sid, source=SOURCE, method='manual', window_start=begin, window_end=end,
            checked_at=checked_at, status='partial' if partial else 'ok', scope_note=(note or None))
