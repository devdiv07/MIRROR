"""
Corporate actions entered by the owner (ADR 0001 §6, §7; Milestone 3).

data/corporate_actions.csv, columns:
    security_key, action_type, ex_date, new_per_old, cash_amount, currency, url[, published_at]

  action_type   split | bonus | dividend | rights | symbol_change
  new_per_old   split and bonus only: shares held after the action per share before. A 2-for-1
                split is 2; a bonus of a for every b held is (a+b)/b, so 1:1 is 2. Moves divide the
                previous close by the product of these on the ex_date (ADR §7).
  cash_amount, currency
                dividend only: the amount per share, e.g. 0.26,USD.
  url           the filing or exchange notice that announced it (https). It becomes a
                source_document (source MANUAL_CA), so every action used in a move has a link.
  published_at  optional: when that notice was published. Without an offset it is read in the
                security's exchange timezone and flagged tz_assumed.

The ex_date must be a session of the security's exchange. A row that repeats a recorded action
unchanged is a no-op. A row that changes a recorded action is refused (db.upsert_corporate_action):
moves computed from it must stay reproducible. An action counts in a move only as of its
first_seen_at, so a move read before the action was entered is held by the unrecorded-action guard.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from datetime import date, datetime

from src.core.calendar import CalendarNotCovered, ExchangeCalendar
from src.store import db

SOURCE = 'MANUAL_CA'
ACTION_TYPES = ('split', 'bonus', 'dividend', 'rights', 'symbol_change')
ADJUSTING = ('split', 'bonus')              # the types whose new_per_old enters k (ADR §7)
_REQUIRED = ('security_key', 'action_type', 'ex_date', 'url')


class ActionInputError(ValueError):
    """A corporate-action row is invalid; nothing from the file was stored."""


@dataclass
class ActionReport:
    rows: int = 0
    statuses: dict = field(default_factory=dict)     # (security_key, action_type, ex_date) -> inserted|unchanged


def _positive(text: str, where: str, column: str) -> float | None:
    text = (text or '').strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        raise ActionInputError(f"{where}: {column} {text!r} is not a number") from None
    if not math.isfinite(value) or value <= 0:
        raise ActionInputError(f"{where}: {column} must be a finite positive number")
    return value


def import_corporate_actions(conn, path: str, *, now: datetime,
                             calendars: dict[str, ExchangeCalendar]) -> ActionReport:
    seen_at = db.utc_iso(now)
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        missing = [c for c in _REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            raise ActionInputError(f"{path}: missing columns {missing}")
        rows = list(reader)

    report = ActionReport()
    with db.transaction(conn):
        for n, r in enumerate(rows, start=2):
            where = f"{path}:{n}"
            key = (r['security_key'] or '').strip()
            sec = conn.execute('SELECT security_id, exchange FROM security WHERE security_key = ?', (key,)).fetchone()
            if sec is None:
                raise ActionInputError(f"{where}: unknown security_key {key!r}; load the watchlist first")
            cal = calendars[sec['exchange']]

            kind = (r['action_type'] or '').strip()
            if kind not in ACTION_TYPES:
                raise ActionInputError(f"{where}: action_type must be one of {ACTION_TYPES}")
            try:
                ex = date.fromisoformat((r['ex_date'] or '').strip())
                open_that_day = cal.is_trading_day(ex)
            except ValueError:
                raise ActionInputError(f"{where}: ex_date {r['ex_date']!r} is not YYYY-MM-DD") from None
            except CalendarNotCovered as e:
                raise ActionInputError(f"{where}: {e}") from None
            if not open_that_day:
                raise ActionInputError(f"{where}: ex_date {ex} is not a {cal.code} session ({cal.closure_reason(ex)})")

            k = _positive(r.get('new_per_old'), where, 'new_per_old')
            cash = _positive(r.get('cash_amount'), where, 'cash_amount')
            currency = (r.get('currency') or '').strip().upper() or None
            if kind in ADJUSTING:
                if k is None or k == 1:
                    raise ActionInputError(f"{where}: a {kind} needs new_per_old (shares after per share before, not 1)")
            elif k is not None:
                raise ActionInputError(f"{where}: new_per_old applies only to split and bonus")
            if kind == 'dividend':
                if cash is None or currency is None or len(currency) != 3 or not currency.isalpha():
                    raise ActionInputError(f"{where}: a dividend needs cash_amount and a 3-letter currency")
            elif cash is not None or currency is not None:
                raise ActionInputError(f"{where}: cash_amount and currency apply only to dividends")

            url = (r['url'] or '').strip()
            if not url.startswith('https://'):
                raise ActionInputError(f"{where}: url must be an https link to the notice")
            published_at, tz_assumed = None, False
            if (r.get('published_at') or '').strip():
                try:
                    published = datetime.fromisoformat(r['published_at'].strip().replace(' ', 'T', 1))
                except ValueError:
                    raise ActionInputError(f"{where}: published_at {r['published_at']!r} is not an ISO time") from None
                if published.tzinfo is None:
                    published, tz_assumed = published.replace(tzinfo=cal.tz), True
                published_at = db.utc_iso(published)
                if published_at > seen_at:
                    raise ActionInputError(f"{where}: published_at {published_at} is in the future")

            content = db.sha256_json({'url': url, 'published_at': published_at, 'tz_assumed': tz_assumed})
            doc_id, _ = db.upsert_source_document(
                conn, source=SOURCE, source_doc_key=url, url=url, content_sha256=content, published_at=published_at,
                published_basis='user_entered', first_seen_at=seen_at, tz_assumed=tz_assumed)
            try:
                _, status = db.upsert_corporate_action(
                    conn, security_id=sec['security_id'], action_type=kind, ex_date=ex.isoformat(), new_per_old=k,
                    cash_amount=cash, currency=currency, doc_id=doc_id, first_seen_at=seen_at)
            except db.IdentityConflict as e:
                raise ActionInputError(f"{where}: {e}") from None
            report.statuses[(key, kind, ex.isoformat())] = status
            report.rows += 1
    return report
