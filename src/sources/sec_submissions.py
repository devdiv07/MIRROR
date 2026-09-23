"""
SEC EDGAR submissions adapter (ADR 0001 §4.1, §4.2; Milestone 2).

For each watched US listing: fetch data.sec.gov/submissions/CIK##########.json once per CIK
(listings sharing a CIK share the fetch), store 8-K, 10-Q, 10-K and Form 4 filings (and their
/A amendments) as versioned documents and per-listing events, and write one coverage_check per
listing.

Coverage of a fetch at time F (ADR §4.2, "SEC fetch coverage and backfill"):
  - filings.recent covers from 00:00 America/New_York on the day AFTER its oldest filingDate
    (filings on that day may continue in an older file) up to F; if filings.files is empty,
    recent is the complete history;
  - each additional file fetched successfully covers filingFrom 00:00 ET .. (filingTo + 1 day) 00:00 ET.
A check is 'ok' only if that union contains the whole window, otherwise 'partial' with a
scope_note naming what is missing. Additional files are fetched only when the window needs them.

HTTP (SecClient): the User-Agent comes from SEC_USER_AGENT, which must be set (there is no
built-in contact); timeout 30 s; at most 3 attempts per request, retrying 429/5xx/timeouts/
connection errors after 1 s then 2 s, no retry on other 4xx. One rate limit covers every request
of a run, including additional files and retries: at least MIN_REQUEST_INTERVAL between the
starts of any two requests (SEC's stated limit is 10 requests/second).
`acceptanceDateTime` is UTC (ADR §14 Q3), stored as published_at with basis source_timestamp.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

import requests

from src.core.coverage import covers
from src.store import db

SOURCE = 'SEC_EDGAR'
SUBMISSIONS_URL = 'https://data.sec.gov/submissions/CIK{cik}.json'
FILE_URL = 'https://data.sec.gov/submissions/{name}'
ARCHIVE_URL = 'https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{document}'
EVENT_TYPE_BY_FORM = {'8-K': '8k_item', '10-Q': 'results', '10-K': 'results', '4': 'insider_form4'}
RETRY_WAITS = (1.0, 2.0)            # 3 attempts in total
MIN_REQUEST_INTERVAL = 0.5          # seconds between request starts: at most 2/s, well under SEC's 10/s
DEFAULT_LOOKBACK = timedelta(days=7)
_ET = ZoneInfo('America/New_York')
_BEGINNING = '0001-01-01T00:00:00Z'


class FetchError(Exception):
    """A request failed after retries, or with a non-retryable status."""


class MissingUserAgent(ValueError):
    """SEC_USER_AGENT is not set, so no SEC request may be sent."""


def user_agent_from_env() -> str:
    """The declared User-Agent. SEC asks automated clients for a name and a contact email."""
    ua = os.environ.get('SEC_USER_AGENT', '').strip()
    if '@' not in ua:
        raise MissingUserAgent(
            'SEC_USER_AGENT is not set (or has no contact email). SEC asks automated clients to declare '
            'who they are; set it first, e.g. SEC_USER_AGENT="Your Name your.email@example.com". '
            'No SEC request was sent.')
    return ua


class SecClient:
    """Every SEC request of one run: the declared User-Agent, one rate limit and retries.

    The rate limit applies to each attempt, so additional files and retries are paced like
    first requests. `get`, `sleep` and `monotonic` are injectable for offline tests.
    """

    def __init__(self, user_agent: str, *, get: Callable = requests.get, sleep: Callable = time.sleep,
                 monotonic: Callable[[], float] = time.monotonic):
        self._headers = {'User-Agent': user_agent, 'Accept-Encoding': 'gzip, deflate'}
        self._get, self._sleep, self._monotonic = get, sleep, monotonic
        self._last_start: float | None = None

    def _wait_turn(self) -> None:
        if self._last_start is not None:
            delay = self._last_start + MIN_REQUEST_INTERVAL - self._monotonic()
            if delay > 0:
                self._sleep(delay)
        self._last_start = self._monotonic()

    def fetch_json(self, url: str) -> dict:
        last = ''
        for attempt in range(len(RETRY_WAITS) + 1):
            self._wait_turn()
            try:
                resp = self._get(url, headers=self._headers, timeout=30)
            except (requests.Timeout, requests.ConnectionError) as e:
                last = f'{type(e).__name__}: {e}'
            else:
                if resp.status_code == 200:
                    return resp.json()
                last = f'HTTP {resp.status_code}'
                if resp.status_code != 429 and resp.status_code < 500:
                    raise FetchError(f'{url}: {last} (not retried)')
            if attempt < len(RETRY_WAITS):
                self._sleep(RETRY_WAITS[attempt])
        raise FetchError(f'{url}: {last} after {len(RETRY_WAITS) + 1} attempts')


def _et_midnight(d: date) -> str:
    return db.utc_iso(datetime.combine(d, dtime(0, 0), tzinfo=_ET))


def _rows(columns: dict) -> list[dict]:
    """SEC's columnar arrays -> one dict per filing."""
    n = len(columns.get('accessionNumber', []))
    return [{k: v[i] for k, v in columns.items() if isinstance(v, list) and len(v) == n} for i in range(n)]


def _published(filing: dict) -> tuple[str, str]:
    acc = filing.get('acceptanceDateTime')
    if acc:
        dt = datetime.strptime(acc[:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
        return db.utc_iso(dt), 'source_timestamp'
    # Date only: knowable by the end of that day in New York (ADR §5, conservative).
    end = datetime.combine(date.fromisoformat(filing['filingDate']) + timedelta(days=1), dtime(0, 0), tzinfo=_ET)
    return db.utc_iso(end - timedelta(seconds=1)), 'source_date_only'


@dataclass
class _CikFetch:
    filings: list[dict] = field(default_factory=list)
    covered: list[tuple[str, str]] = field(default_factory=list)   # closed intervals
    missing: list[str] = field(default_factory=list)               # human-readable gaps
    error: str | None = None


def _fetch_cik(client: SecClient, cik: str, earliest_start: str, fetched_at: str) -> _CikFetch:
    out = _CikFetch()
    try:
        doc = client.fetch_json(SUBMISSIONS_URL.format(cik=cik))
    except FetchError as e:
        out.error = str(e)
        return out
    filings = doc.get('filings', {})
    recent = _rows(filings.get('recent', {}))
    files = filings.get('files', []) or []
    out.filings.extend(recent)
    if not files:
        out.covered.append((_BEGINNING, fetched_at))
        return out
    oldest = min((date.fromisoformat(f['filingDate']) for f in recent), default=None)
    recent_from = _et_midnight(oldest + timedelta(days=1)) if oldest else fetched_at
    out.covered.append((recent_from, fetched_at))
    if earliest_start >= recent_from:
        return out
    for f in files:
        lo = _et_midnight(date.fromisoformat(f['filingFrom']))
        hi = _et_midnight(date.fromisoformat(f['filingTo']) + timedelta(days=1))
        if hi <= earliest_start or lo >= recent_from:
            continue                                 # not needed for this window
        try:
            extra = client.fetch_json(FILE_URL.format(name=f['name']))
        except FetchError as e:
            out.missing.append(f"{f['filingFrom']}..{f['filingTo']} in {f['name']} not fetched ({e})")
            continue
        out.filings.extend(_rows(extra))
        out.covered.append((lo, hi))
    return out


def _gap_note(covered: list[tuple[str, str]], start: str, end: str) -> str:
    gaps, reach = [], start
    for lo, hi in sorted(covered):
        if lo > reach:
            gaps.append(f'{reach}..{min(lo, end)}')
        reach = max(reach, hi)
        if reach >= end:
            break
    if reach < end:
        gaps.append(f'{reach}..{end}')
    return 'not covered: ' + ', '.join(gaps)


@dataclass
class SecReport:
    run_id: int
    status: str
    fetches: int
    records_new: int
    checks: dict = field(default_factory=dict)      # security_key -> (status, scope_note or error)


def ingest_sec(conn, securities: list, *, now: datetime, since: datetime | None = None,
               get: Callable = requests.get, sleep: Callable = time.sleep,
               monotonic: Callable[[], float] = time.monotonic) -> SecReport:
    """Fetch and store SEC filings for US securities (rows with security_id, security_key, company_id).

    Each listing's window starts at `since` if given (backfill), else where its last ok/partial
    SEC check ended, else now - DEFAULT_LOOKBACK; it ends at `now`, the fetch time.
    Raises MissingUserAgent, before any request or store write, if SEC_USER_AGENT is not set.
    """
    client = SecClient(user_agent_from_env(), get=get, sleep=sleep, monotonic=monotonic)
    fetched_at = db.utc_iso(now)
    run_id = db.start_ingest_run(conn, SOURCE, fetched_at)
    by_cik: dict[str, list] = {}
    for s in securities:
        by_cik.setdefault(s['company_id'], []).append(s)

    report = SecReport(run_id, 'ok', 0, 0)
    statuses = []
    for cik, group in sorted(by_cik.items()):
        starts = {}
        for s in group:
            resume = db.last_covered_through(conn, s['security_id'], SOURCE)
            start = db.utc_iso(since) if since else (resume or db.utc_iso(now - DEFAULT_LOOKBACK))
            starts[s['security_id']] = min(start, fetched_at)
        fetch = _fetch_cik(client, cik, min(starts.values()), fetched_at)
        report.fetches += 1
        with db.transaction(conn):
            _record_cik(conn, group, starts, fetch, fetched_at, run_id, report, statuses)

    if statuses and all(s == 'failed' for s in statuses):
        report.status = 'failed'
    elif any(s != 'ok' for s in statuses):
        report.status = 'partial'
    errors = sorted({v[1] for v in report.checks.values() if v[0] == 'failed'})
    db.finish_ingest_run(conn, run_id, finished_at=fetched_at, status=report.status,
                         records_new=report.records_new, error='; '.join(errors) or None)
    return report


def _record_cik(conn, group, starts, fetch: _CikFetch, fetched_at: str, run_id: int,
                report: SecReport, statuses: list) -> None:
    """One coverage_check per listing of this CIK, plus its filings; runs inside one transaction."""
    for s in group:
        sid, start = s['security_id'], starts[s['security_id']]
        if fetch.error:
            status, note, error = 'failed', None, fetch.error
        elif covers(fetch.covered, start, fetched_at):
            status, note, error = 'ok', None, None
        else:
            status, error = 'partial', None
            note = '; '.join([_gap_note(fetch.covered, start, fetched_at)] + fetch.missing)
        db.insert_coverage_check(conn, security_id=sid, source=SOURCE, method='api', window_start=start,
                                 window_end=fetched_at, checked_at=fetched_at, status=status,
                                 scope_note=note, error=error, run_id=run_id)
        report.checks[s['security_key']] = (status, note or error)
        statuses.append(status)
        if not fetch.error:
            report.records_new += _store_filings(conn, s, fetch.filings, start, fetched_at)


def _store_filings(conn, security, filings: list[dict], start: str, fetched_at: str) -> int:
    new = 0
    cik_int = int(security['company_id'])
    for f in filings:
        form = f.get('form', '')
        base = form[:-2] if form.endswith('/A') else form
        if base not in EVENT_TYPE_BY_FORM:
            continue
        published_at, basis = _published(f)
        if not (start < published_at <= fetched_at):
            continue
        accession = f['accessionNumber']
        document = f.get('primaryDocument') or f'{accession}-index.htm'
        url = ARCHIVE_URL.format(cik=cik_int, accession_nodash=accession.replace('-', ''), document=document)
        fields = {k: f.get(k) for k in ('form', 'items', 'filingDate', 'reportDate', 'primaryDocument',
                                         'primaryDocDescription', 'acceptanceDateTime')}
        fields.update(accessionNumber=accession, cik=security['company_id'])
        doc_id, _ = db.upsert_source_document(
            conn, source=SOURCE, source_doc_key=accession, url=url, content_sha256=db.sha256_json(fields),
            published_at=published_at, published_basis=basis, first_seen_at=fetched_at)
        _, status = db.upsert_event_version(
            conn, security_id=security['security_id'], source=SOURCE, source_doc_key=accession, doc_id=doc_id,
            event_type=EVENT_TYPE_BY_FORM[base], subject=f.get('primaryDocDescription') or form,
            event_time=f.get('reportDate') or None, published_at=published_at, first_seen_at=fetched_at,
            fields=fields)
        new += status != 'unchanged'
    return new
