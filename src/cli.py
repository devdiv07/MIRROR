"""
MIRROR command line (Milestone 2).

  python -m src.cli ingest   [--watchlist config/watchlist.yaml] [--manual-events data/manual_events.csv]
                             [--sec-since 2026-09-01T00:00:00Z]
      Load the watchlist, fetch SEC filings for active US listings, import manual NSE events.

  python -m src.cli checked NSE <SYMBOL> --through <time> [--from <time>] [--partial --note "..."]
      Record that you reviewed NSE for SYMBOL up to --through.

  python -m src.cli events [--since <time>] [--as-of <time>]
      Plain-text listing: per active security, the coverage state of each required source for
      the window (since, as-of] and the events visible as of --as-of.

Times: ISO 8601. Without an offset they are read as Asia/Kolkata (the owner's clock).
All commands take --db (default data/mirror.sqlite3).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Callable

import requests

from src.core.calendar import DEFAULT_CONFIG_PATH, load_calendars
from src.core.coverage import security_coverage
from src.core.identity import load_watchlist, parse_watchlist
from src.sources import manual_events, sec_submissions
from src.store import db

DEFAULT_WATCHLIST = os.path.join('config', 'watchlist.yaml')
DEFAULT_MANUAL_EVENTS = os.path.join('data', 'manual_events.csv')

_LABEL = {
    'checked_with_events': 'Checked, new disclosures below',
    'checked_no_events': 'Checked, no new disclosures',
    'not_checked': 'NOT CHECKED',
    'source_failed': 'SOURCE FAILED',
    'coverage_incomplete': 'COVERAGE INCOMPLETE',
}


def _time(text: str) -> datetime:
    dt, _ = manual_events.parse_local_time(text, 'time')
    return dt


def _active_securities(conn, market: str | None = None):
    sql = ('SELECT s.* FROM security s JOIN watchlist_item w USING (security_id) WHERE w.active = 1'
           + (' AND s.market = ?' if market else '') + ' ORDER BY s.security_key')
    return conn.execute(sql, (market,) if market else ()).fetchall()


def cmd_ingest(args, conn, now: datetime, out, http_get: Callable, utcnow: Callable) -> int:
    calendars = load_calendars(args.exchanges)
    report = load_watchlist(conn, parse_watchlist(args.watchlist, calendars), now=now)
    changed = {k: v for k, v in report.securities.items() if v != 'unchanged'}
    print(f"watchlist: {len(report.securities)} securities ({len(changed)} changed), "
          f"deactivated: {report.deactivated or 'none'}", file=out)

    us = _active_securities(conn, 'US')
    if us:
        sec = sec_submissions.ingest_sec(conn, us, now=now, get=http_get, utcnow=utcnow,
                                         since=_time(args.sec_since) if args.sec_since else None)
        print(f"SEC EDGAR: run {sec.run_id} {sec.status}; {sec.fetches} CIK fetch(es); "
              f"{sec.records_new} new event version(s)", file=out)
        for key, (status, note) in sorted(sec.checks.items()):
            print(f"  {key}: {status}" + (f" — {note}" if note else ''), file=out)

    if os.path.exists(args.manual_events):
        man = manual_events.import_manual_events(conn, args.manual_events, now=now)
        new = sum(s != 'unchanged' for s in man.statuses.values())
        print(f"manual NSE events: {man.rows} row(s), {new} new version(s)", file=out)
    else:
        print(f"manual NSE events: {args.manual_events} not found (nothing imported)", file=out)
    return 0


def cmd_checked(args, conn, now: datetime, out, http_get: Callable, utcnow: Callable) -> int:
    if args.exchange != 'NSE':
        print('only NSE is checked manually; SEC checks are recorded by `ingest`', file=sys.stderr)
        return 2
    through = _time(args.through)
    sid = db.security_id_for_symbol(conn, 'NSE', args.symbol.upper(), through.date().isoformat())
    if sid is None:
        print(f"NSE:{args.symbol} is not a known symbol on {through.date()}", file=sys.stderr)
        return 2
    key = conn.execute('SELECT security_key FROM security WHERE security_id = ?', (sid,)).fetchone()[0]
    manual_events.record_manual_check(conn, security_key=key, through=through, now=now,
                                      start=_time(args.from_) if args.from_ else None,
                                      partial=args.partial, note=args.note)
    print(f"recorded {'partial' if args.partial else 'ok'} NSE check for {key} through {db.utc_iso(through)}",
          file=out)
    return 0


def cmd_events(args, conn, now: datetime, out, http_get: Callable, utcnow: Callable) -> int:
    as_of = db.utc_iso(_time(args.as_of)) if args.as_of else db.utc_iso(now)
    since = db.utc_iso(_time(args.since)) if args.since else db.utc_iso(db.parse_utc(as_of) - timedelta(days=1))
    print(f"MIRROR events as of {as_of}, window ({since}, {as_of}]", file=out)
    for s in _active_securities(conn):
        print(f"\n{s['security_key']}  {s['name']}", file=out)
        for cov in security_coverage(conn, security_id=s['security_id'], market=s['market'],
                                     window_start=since, window_end=as_of, as_of=as_of):
            print(f"  [{cov.source}] {_LABEL[cov.state]} — {cov.detail}", file=out)
            for e in cov.events:
                flag = ' (time zone assumed IST)' if e['tz_assumed'] else ''
                print(f"    {e['published_at']}{flag}  {e['event_type']}  \"{e['subject']}\"  v{e['version']}"
                      f"  {e['url']}", file=out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='python -m src.cli', description='MIRROR watchlist research tools')
    p.add_argument('--db', default=db.DEFAULT_DB_PATH)
    sub = p.add_subparsers(dest='command', required=True)

    ing = sub.add_parser('ingest', help='load watchlist, fetch SEC, import manual NSE events')
    ing.add_argument('--watchlist', default=DEFAULT_WATCHLIST)
    ing.add_argument('--exchanges', default=DEFAULT_CONFIG_PATH)
    ing.add_argument('--manual-events', default=DEFAULT_MANUAL_EVENTS)
    ing.add_argument('--sec-since', help='backfill SEC from this time instead of resuming')
    ing.set_defaults(func=cmd_ingest)

    chk = sub.add_parser('checked', help='record a manual NSE review')
    chk.add_argument('exchange')
    chk.add_argument('symbol')
    chk.add_argument('--through', required=True)
    chk.add_argument('--from', dest='from_')
    chk.add_argument('--partial', action='store_true')
    chk.add_argument('--note')
    chk.set_defaults(func=cmd_checked)

    ev = sub.add_parser('events', help='list coverage states and events')
    ev.add_argument('--since')
    ev.add_argument('--as-of')
    ev.set_defaults(func=cmd_events)
    return p


def main(argv: list[str] | None = None, *, now: datetime | None = None, out=None,
         http_get: Callable = requests.get, utcnow: Callable[[], datetime] | None = None) -> int:
    """`now` is the command's cutoff; `utcnow` is the clock for arrival times. Tests that pass a
    fixed `now` get a clock frozen at it unless they pass their own."""
    args = build_parser().parse_args(argv)
    if utcnow is None:
        utcnow = (lambda: now) if now else (lambda: datetime.now(timezone.utc))
    now = now or utcnow()
    out = out or sys.stdout
    if args.db != ':memory:':
        os.makedirs(os.path.dirname(args.db) or '.', exist_ok=True)
    conn = db.connect(args.db)
    try:
        return args.func(args, conn, now, out, http_get, utcnow)
    except (manual_events.ManualInputError, db.IdentityConflict, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    finally:
        conn.close()


if __name__ == '__main__':
    sys.exit(main())
