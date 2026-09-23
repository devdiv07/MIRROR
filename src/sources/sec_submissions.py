"""
SEC EDGAR submissions adapter (ADR 0001 §4.1, §4.2; Milestone 2).

For each watched US listing: fetch data.sec.gov/submissions/CIK##########.json once per CIK
(listings sharing a CIK share the fetch), store 8-K, 10-Q, 10-K and Form 4 filings (and their
/A amendments) as versioned documents and per-listing events, and write one coverage_check per
listing.

Times. A run has one cutoff F, taken before any request: every window ends at F, and only filings
published at or before F are stored, so a filing accepted while a response is in flight waits for
the next run. first_seen_at is when the response holding the filing arrived, and checked_at is when
the listing's check was recorded, both from the `utcnow` clock and never earlier than F. A slow
response therefore never makes a filing look known before MIRROR had it.

Coverage of a fetch with cutoff F (ADR §4.2, "SEC fetch coverage and backfill"):
  - filings.recent covers from 00:00 America/New_York on the day AFTER its oldest filingDate
    (filings on that day may continue in an older file) up to F; if filings.files is empty,
    recent is the complete history;
  - each additional file fetched successfully covers filingFrom 00:00 ET .. (filingTo + 1 day) 00:00 ET,
    and the oldest file covers from the beginning (recent + files is the whole EDGAR history).
A check is 'ok' only if that union contains the whole window, otherwise 'partial' with a
scope_note naming what is missing and the covered spans saved in coverage_span. The gap stays
incomplete, and the next ordinary run starts at it (db.resume_point) until it is fetched.
Additional files are fetched only when the window needs them.

Responses are validated before use (_parse_submissions, _filing_rows). Invalid JSON is retried like
a 5xx; a response of the wrong shape is an InvalidResponse. Either way the request counts as failed:
a bad submissions JSON fails the listing's check, a bad additional file leaves its period missing.

HTTP (SecClient): the User-Agent comes from SEC_USER_AGENT, which must be set (there is no
built-in contact); timeout 30 s; at most 3 attempts per request, retrying 429/5xx/timeouts/
connection errors after 1 s then 2 s, no retry on other 4xx. One rate limit covers every request
of a run, including additional files and retries: at least MIN_REQUEST_INTERVAL between the
starts of any two requests (SEC's stated limit is 10 requests/second).
`acceptanceDateTime` is UTC (ADR §14 Q3), stored as published_at with basis source_timestamp.
"""

from __future__ import annotations

import os
import re
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


class InvalidResponse(FetchError):
    """A 200 response whose JSON is not the shape this adapter relies on."""


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
                    try:
                        return resp.json()
                    except ValueError as e:              # truncated or non-JSON body: retried
                        last = f'invalid JSON ({e})'
                else:
                    last = f'HTTP {resp.status_code}'
                    if resp.status_code != 429 and resp.status_code < 500:
                        raise FetchError(f'{url}: {last} (not retried)')
            if attempt < len(RETRY_WAITS):
                self._sleep(RETRY_WAITS[attempt])
        raise FetchError(f'{url}: {last} after {len(RETRY_WAITS) + 1} attempts')


def _et_midnight(d: date) -> str:
    return db.utc_iso(datetime.combine(d, dtime(0, 0), tzinfo=_ET))


_REQUIRED_COLUMNS = ('accessionNumber', 'filingDate', 'form')
_OPTIONAL_COLUMNS = ('acceptanceDateTime', 'reportDate', 'items', 'primaryDocument', 'primaryDocDescription')
_ACCESSION = re.compile(r'\d{10}-\d{2}-\d{6}')
_ACCEPTANCE = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z')      # UTC (ADR §14 Q3)
_FILE_NAME = re.compile(r'CIK\d{10}-submissions-\d{3}\.json')
_DOCUMENT = re.compile(r'\w[\w.-]*(/\w[\w.-]*)?', re.ASCII)              # e.g. xslF345X05/doc4.xml


def _iso_date(value, where: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise InvalidResponse(f'{where}: {value!r} is not a YYYY-MM-DD date') from None


def _filing_rows(columns, where: str) -> list[dict]:
    """SEC's columnar arrays -> one dict per filing, or InvalidResponse if any column or value is off.

    One bad row rejects the whole response: MIRROR does not record coverage from a document it
    could only partly read.
    """
    if not isinstance(columns, dict):
        raise InvalidResponse(f'{where}: filings are not an object')
    missing = [k for k in _REQUIRED_COLUMNS if not isinstance(columns.get(k), list)]
    if missing:
        raise InvalidResponse(f"{where}: missing column(s) {', '.join(missing)}")
    n = len(columns['accessionNumber'])
    present = [k for k in _REQUIRED_COLUMNS + _OPTIONAL_COLUMNS if columns.get(k) is not None]
    for k in present:
        if not isinstance(columns[k], list) or len(columns[k]) != n:
            size = len(columns[k]) if isinstance(columns[k], list) else type(columns[k]).__name__
            raise InvalidResponse(f'{where}: column {k} has {size} values, expected {n}')
    rows = [{k: columns[k][i] for k in present} for i in range(n)]
    for r in rows:
        acc = r['accessionNumber']
        if not all(isinstance(v, str) for v in r.values()):
            raise InvalidResponse(f'{where}: non-text value in filing {acc!r}')
        if not _ACCESSION.fullmatch(acc):
            raise InvalidResponse(f'{where}: bad accession number {acc!r}')
        _iso_date(r['filingDate'], where)
        if r.get('acceptanceDateTime') and not _ACCEPTANCE.fullmatch(r['acceptanceDateTime']):
            raise InvalidResponse(f"{where}: acceptanceDateTime {r['acceptanceDateTime']!r} is not UTC ISO 8601")
    return rows


def _parse_submissions(doc, cik: str) -> tuple[list[dict], list[dict]]:
    """Validate a submissions JSON. Returns (recent filings, additional-file entries)."""
    where = f'CIK{cik} submissions'
    if not isinstance(doc, dict) or not isinstance(doc.get('filings'), dict):
        raise InvalidResponse(f'{where}: no filings object')
    if 'cik' in doc and str(doc['cik']).lstrip('0') != cik.lstrip('0'):
        raise InvalidResponse(f"{where}: response is for CIK {doc['cik']!r}")
    recent = _filing_rows(doc['filings'].get('recent'), f'{where} recent')
    files = doc['filings'].get('files') or []
    if not isinstance(files, list):
        raise InvalidResponse(f'{where}: files is not a list')
    for f in files:
        if not isinstance(f, dict) or not _FILE_NAME.fullmatch(str(f.get('name'))):
            raise InvalidResponse(f'{where}: bad additional-file entry {f!r}')
        if _iso_date(f.get('filingFrom'), where) > _iso_date(f.get('filingTo'), where):
            raise InvalidResponse(f"{where}: {f['name']} has filingFrom after filingTo")
    return recent, files


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
    filings: list[tuple[str, dict]] = field(default_factory=list)  # (received_at, filing)
    covered: list[tuple[str, str]] = field(default_factory=list)   # closed intervals
    missing: list[str] = field(default_factory=list)               # human-readable gaps
    error: str | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _fetch_cik(client: SecClient, cik: str, earliest_start: str, cutoff: str,
               received: Callable[[], str]) -> _CikFetch:
    out = _CikFetch()
    try:
        recent, files = _parse_submissions(client.fetch_json(SUBMISSIONS_URL.format(cik=cik)), cik)
    except FetchError as e:
        out.error = str(e)
        return out
    at = received()
    out.filings.extend((at, f) for f in recent)
    if not files:
        out.covered.append((_BEGINNING, cutoff))
        return out
    oldest = min((date.fromisoformat(f['filingDate']) for f in recent), default=None)
    recent_from = _et_midnight(oldest + timedelta(days=1)) if oldest else cutoff
    out.covered.append((recent_from, cutoff))
    if earliest_start >= recent_from:
        return out
    first_from = min(f['filingFrom'] for f in files)
    for f in files:
        # recent + all files is the company's whole EDGAR history, so the oldest file reaches back
        # to the beginning (as recent does when there are no files).
        lo = _BEGINNING if f['filingFrom'] == first_from else _et_midnight(date.fromisoformat(f['filingFrom']))
        hi = _et_midnight(date.fromisoformat(f['filingTo']) + timedelta(days=1))
        if hi <= earliest_start or lo >= recent_from:
            continue                                 # not needed for this window
        try:
            extra = _filing_rows(client.fetch_json(FILE_URL.format(name=f['name'])), f['name'])
        except FetchError as e:
            out.missing.append(f"{f['filingFrom']}..{f['filingTo']} in {f['name']} not fetched ({e})")
            continue
        at = received()
        out.filings.extend((at, row) for row in extra)
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
               monotonic: Callable[[], float] = time.monotonic,
               utcnow: Callable[[], datetime] = _utcnow) -> SecReport:
    """Fetch and store SEC filings for US securities (rows with security_id, security_key, company_id).

    `now` is the run's cutoff, taken before any request: every window ends there. Each listing's
    window starts at `since` if given (backfill), else at db.resume_point (the earliest period its
    SEC checks have not covered, so a partial backfill or a failed run is retried by the next
    ordinary run), else now - DEFAULT_LOOKBACK. first_seen_at and checked_at come from `utcnow`
    as responses arrive.
    Raises MissingUserAgent, before any request or store write, if SEC_USER_AGENT is not set.
    """
    client = SecClient(user_agent_from_env(), get=get, sleep=sleep, monotonic=monotonic)
    cutoff = db.utc_iso(now)

    def received() -> str:
        return max(db.utc_iso(utcnow()), cutoff)    # a clock step backwards never predates the cutoff

    run_id = db.start_ingest_run(conn, SOURCE, cutoff)
    by_cik: dict[str, list] = {}
    for s in securities:
        by_cik.setdefault(s['company_id'], []).append(s)

    report = SecReport(run_id, 'ok', 0, 0)
    statuses = []
    try:
        for cik, group in sorted(by_cik.items()):
            starts = {}
            for s in group:
                resume = db.resume_point(conn, s['security_id'], SOURCE)
                start = db.utc_iso(since) if since else (resume or db.utc_iso(now - DEFAULT_LOOKBACK))
                starts[s['security_id']] = min(start, cutoff)
            fetch = _fetch_cik(client, cik, min(starts.values()), cutoff, received)
            report.fetches += 1
            with db.transaction(conn):
                _record_cik(conn, group, starts, fetch, cutoff, received(), run_id, report, statuses)
    except BaseException as e:
        # Never leave a run open. CIKs already committed stay recorded; the rest were not checked.
        db.finish_ingest_run(conn, run_id, finished_at=received(), status='failed',
                             records_new=report.records_new, error=f'aborted: {type(e).__name__}: {e}')
        raise

    if statuses and all(s == 'failed' for s in statuses):
        report.status = 'failed'
    elif any(s != 'ok' for s in statuses):
        report.status = 'partial'
    errors = sorted({v[1] for v in report.checks.values() if v[0] == 'failed'})
    db.finish_ingest_run(conn, run_id, finished_at=received(), status=report.status,
                         records_new=report.records_new, error='; '.join(errors) or None)
    return report


def _record_cik(conn, group, starts, fetch: _CikFetch, cutoff: str, checked_at: str, run_id: int,
                report: SecReport, statuses: list) -> None:
    """One coverage_check per listing of this CIK, plus its filings; runs inside one transaction."""
    for s in group:
        sid, start = s['security_id'], starts[s['security_id']]
        if fetch.error:
            status, note, error = 'failed', None, fetch.error
        elif covers(fetch.covered, start, cutoff):
            status, note, error = 'ok', None, None
        else:
            status, error = 'partial', None
            note = '; '.join([_gap_note(fetch.covered, start, cutoff)] + fetch.missing)
        db.insert_coverage_check(conn, security_id=sid, source=SOURCE, method='api', window_start=start,
                                 window_end=cutoff, checked_at=checked_at, status=status,
                                 scope_note=note, error=error, run_id=run_id,
                                 covered_spans=fetch.covered if status == 'partial' else None)
        report.checks[s['security_key']] = (status, note or error)
        statuses.append(status)
        if not fetch.error:
            report.records_new += _store_filings(conn, s, fetch.filings, start, cutoff)


def _store_filings(conn, security, filings: list[tuple[str, dict]], start: str, cutoff: str) -> int:
    new = 0
    cik_int = int(security['company_id'])
    for received_at, f in filings:
        form = f.get('form', '')
        base = form[:-2] if form.endswith('/A') else form
        if base not in EVENT_TYPE_BY_FORM:
            continue
        published_at, basis = _published(f)
        if not (start < published_at <= cutoff):
            continue                                 # after the cutoff: the next run's window
        accession = f['accessionNumber']
        document = f.get('primaryDocument') or ''
        if not _DOCUMENT.fullmatch(document):
            document = f'{accession}-index.htm'          # the filing index always exists
        url = ARCHIVE_URL.format(cik=cik_int, accession_nodash=accession.replace('-', ''), document=document)
        fields = {k: f.get(k) for k in ('form', 'items', 'filingDate', 'reportDate', 'primaryDocument',
                                         'primaryDocDescription', 'acceptanceDateTime')}
        fields.update(accessionNumber=accession, cik=security['company_id'])
        doc_id, _ = db.upsert_source_document(
            conn, source=SOURCE, source_doc_key=accession, url=url, content_sha256=db.sha256_json(fields),
            published_at=published_at, published_basis=basis, first_seen_at=received_at)
        _, status = db.upsert_event_version(
            conn, security_id=security['security_id'], source=SOURCE, source_doc_key=accession, doc_id=doc_id,
            event_type=EVENT_TYPE_BY_FORM[base], subject=f.get('primaryDocDescription') or form,
            event_time=f.get('reportDate') or None, published_at=published_at, first_seen_at=received_at,
            fields=fields)
        new += status != 'unchanged'
    return new
