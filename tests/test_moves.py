"""
Milestone 3 moves and corporate actions (ADR 0001 §7, §10): adjusted close-to-close moves, the
unrecorded-action guard, stale prices, the volume ratio, and corporate-action import. Every number is
recomputed here from the stored rows. Offline; price series are written as MIRROR price CSVs.
"""

import io
import re
from datetime import date

import pytest

from src import cli
from src.compute.moves import (
    CALC_VERSION, compute_move, price_claim_lines, triggered,
)
from src.sources.corporate_actions import ActionInputError, import_corporate_actions
from src.sources.prices_csv import import_price_file
from src.store import db
from tests.support import CALENDARS, HOUR, NOW, WATCHLIST, FakeHttp, new_store, sid

T = db.utc_iso
KEY = 'US:NASDAQ:TDCA'
D = date(2026, 9, 22)                        # a Tuesday; previous session Monday 2026-09-21
PREV = date(2026, 9, 21)
AFTER_CLOSE = T(NOW)                         # 2026-09-23T01:00Z, after the 20:00Z close of D
NASDAQ = CALENDARS['NASDAQ']
HEADER = 'security_key,trade_date,open,high,low,close,volume,adj_close\n'
CA_HEADER = 'security_key,action_type,ex_date,new_per_old,cash_amount,currency,url,published_at\n'


def _series(tmp_path, last, *, n=25, close=100.0, volume=1_000_000, key=KEY, name='series.csv', upto=D):
    """n sessions of flat prices ending the session before `upto`, then `last` = (close, volume, adj) on it."""
    sessions = [s.day for s in NASDAQ.sessions_between(date(2026, 7, 1), upto)][-(n + 1):]
    rows = [f"{key},{d},,,,{close},{volume},\n" for d in sessions[:-1]]
    if last is not None:
        c, v, adj = (tuple(last) + (None, None))[:3]
        rows.append(f"{key},{sessions[-1]},,,,{c},{'' if v is None else v},{'' if adj is None else adj}\n")
    p = tmp_path / name
    p.write_text(HEADER + ''.join(rows), encoding='utf-8')
    return p


def _load(conn, path, now=NOW):
    return import_price_file(conn, str(path), now=now, calendars=CALENDARS)


def _actions(conn, tmp_path, rows, now=NOW, name='actions.csv'):
    p = tmp_path / name
    p.write_text(CA_HEADER + ''.join(rows), encoding='utf-8')
    return import_corporate_actions(conn, str(p), now=now, calendars=CALENDARS)


def _move(conn, day=D, as_of=AFTER_CLOSE, key=KEY):
    return compute_move(conn, sid(conn, key), day, as_of=as_of, calendars=CALENDARS)


def _stored_close(conn, day):
    return conn.execute('SELECT close_raw FROM price_bar WHERE security_id = ? AND trade_date = ?'
                        ' ORDER BY import_id DESC LIMIT 1', (sid(conn, KEY), day.isoformat())).fetchone()[0]


# ── computed move, trace and reproducibility ─────────────────────────────────

def test_move_is_recomputed_from_stored_rows(tmp_path):
    conn = new_store(tmp_path)
    _load(conn, _series(tmp_path, (108.4, 2_600_000)))
    m = _move(conn)

    assert m.status == 'computed' and m.calc_version == CALC_VERSION
    assert (m.prev_date, m.k) == (PREV.isoformat(), 1.0)
    assert m.move == _stored_close(conn, D) / _stored_close(conn, PREV) - 1          # exactly
    assert m.volume_ratio == 2_600_000 / 1_000_000
    assert set(m.bar_imports.values()) == {1} and len(m.bar_imports) == 21          # D and the 20 prior (incl. D-1)
    lines = price_claim_lines(m)
    assert lines[0] == '+8.40% adjusted close-to-close (2026-09-21 to 2026-09-22)'
    assert lines[1] == (f'trace: close 108.40 (2026-09-22) vs 100.00 (2026-09-21) ÷ k=1 · import #1'
                        f' · calc {CALC_VERSION}')
    assert 'volume 2.60× the median of the prior 20 sessions' in lines
    assert triggered(m, 5.0) and not triggered(m, 9.0) and not triggered(m, None)


def test_move_before_the_session_closed_is_refused(tmp_path):
    conn = new_store(tmp_path)
    _load(conn, _series(tmp_path, (108.4, 2_600_000)))
    with pytest.raises(ValueError, match='had not closed'):
        _move(conn, as_of='2026-09-22T19:59:59Z')


def test_newest_import_visible_at_as_of_is_used(tmp_path):
    conn = new_store(tmp_path)
    _load(conn, _series(tmp_path, (108.4, 2_600_000)))
    fix = tmp_path / 'fix.csv'
    fix.write_text(HEADER + f'{KEY},{D},,,,104.0,2600000,\n', encoding='utf-8')
    _load(conn, fix, now=NOW + HOUR)
    assert round(_move(conn).move_pct, 6) == 8.4
    later = _move(conn, as_of=T(NOW + HOUR))
    assert round(later.move_pct, 6) == 4.0 and later.bar_imports[D.isoformat()] == 2
    assert [s.file_name for s in later.sources] == ['series.csv', 'fix.csv']


# ── A3: split / bonus day, and the unrecorded-action guard ───────────────────

A3_BONUS = f'{KEY},bonus,{D},2,,,https://example.com/tdc/bonus-notice,2026-09-01T16:05:00-04:00\n'


def test_a3_bonus_day_is_a_small_adjusted_move_not_minus_50(tmp_path):           # A3
    conn = new_store(tmp_path)
    _load(conn, _series(tmp_path, (101.0, 2_000_000), close=200.0))
    _actions(conn, tmp_path, [A3_BONUS])
    m = _move(conn)

    assert m.status == 'computed' and m.k == 2
    assert m.move == _stored_close(conn, D) / (_stored_close(conn, PREV) / 2) - 1
    assert round(m.move_pct, 6) == 1.0
    assert not triggered(m, 5.0)                                          # no card
    text = '\n'.join(price_claim_lines(m))
    assert '+1.00%' in text and '÷ k=2' in text
    assert not re.search(r'-\s?(49|50)[.\d]*\s?%', text)                  # no -50% anywhere
    assert m.volume_ratio == 1.0                                          # prior volumes scaled by k


def test_a3_without_the_action_row_is_held(tmp_path):                             # A3 (guard)
    conn = new_store(tmp_path)
    _load(conn, _series(tmp_path, (101.0, 2_000_000), close=200.0))
    m = _move(conn)
    assert m.status == 'held' and m.move is None and m.move_pct is None
    assert 'possible_unrecorded_corporate_action' in m.flags
    assert triggered(m, 5.0)                                              # the card is held for review
    text = '\n'.join(price_claim_lines(m))
    assert text.startswith('HELD: check corporate actions')
    assert not re.search(r'-\s?(49|50)[.\d]*\s?%', text)


def test_action_counts_only_from_when_it_was_entered(tmp_path):
    conn = new_store(tmp_path)
    _load(conn, _series(tmp_path, (101.0, 2_000_000), close=200.0))
    _actions(conn, tmp_path, [A3_BONUS], now=NOW + 3 * HOUR)
    assert _move(conn, as_of=T(NOW + HOUR)).status == 'held'              # not yet recorded then
    assert _move(conn, as_of=T(NOW + 3 * HOUR)).status == 'computed'


@pytest.mark.parametrize('prev_close, close, held', [
    (10.0, 100.0, True),        # 1-for-10 reverse split, unrecorded: +900%
    (100.0, 33.5, True),        # 3-for-1 within 2%
    (100.0, 135.0, False),      # a real +35% move: no common ratio
    (100.0, 60.0, False),       # -40%: 1.667 is not within 2% of 1.5 or 2
    (100.0, 80.0, False),       # below 30%
])
def test_guard_ratios(tmp_path, prev_close, close, held):
    conn = new_store(tmp_path)
    _load(conn, _series(tmp_path, (close, 1_000_000), close=prev_close))
    assert (_move(conn).status == 'held') is held


def test_wrongly_recorded_ratio_is_still_held(tmp_path):
    conn = new_store(tmp_path)
    _load(conn, _series(tmp_path, (33.4, 1_000_000), close=100.0))           # really 3-for-1
    _actions(conn, tmp_path, [f'{KEY},split,{D},2,,,https://example.com/split,\n'])
    m = _move(conn)
    assert m.status == 'held' and m.k == 2


# ── A5 and other no-move cases ───────────────────────────────────────────────

def test_a5_stale_price_has_no_move(tmp_path):                                    # A5
    conn = new_store(tmp_path)
    _load(conn, _series(tmp_path, None))                                   # bars end on D-1
    m = _move(conn)
    assert m.status == 'stale' and m.move is None and m.price_as_of == PREV.isoformat()
    assert price_claim_lines(m) == ['stale: price as of 2026-09-21; no move computed']
    assert not triggered(m, 0.01)


def test_no_bar_for_the_previous_session_is_not_carried_forward(tmp_path):
    conn = new_store(tmp_path)
    p = tmp_path / 'gap.csv'
    p.write_text(HEADER + f'{KEY},2026-09-18,,,,100,1,\n{KEY},{D},,,,108,1,\n', encoding='utf-8')
    _load(conn, p)
    m = _move(conn)
    assert m.status == 'no_previous_close' and m.move is None and '2026-09-21' in m.detail


def test_market_closed_and_uncovered_calendar(tmp_path):
    conn = new_store(tmp_path)
    assert _move(conn, day=date(2026, 9, 7)).status == 'market_closed'      # Labor Day
    assert _move(conn, day=date(2026, 9, 19)).status == 'market_closed'     # Saturday
    m = _move(conn, day=date(2026, 1, 2), as_of='2026-01-03T00:00:00Z')     # previous session is in 2025
    assert m.status == 'calendar_not_covered' and '2025' in m.detail


def test_zero_volume_is_a_possible_suspension(tmp_path):
    conn = new_store(tmp_path)
    _load(conn, _series(tmp_path, (100.0, 0)))
    m = _move(conn)
    assert m.status == 'no_trade' and m.move is None and 'no_trade_possible_suspension' in m.flags


def test_volume_ratio_needs_ten_prior_sessions(tmp_path):
    conn = new_store(tmp_path)
    _load(conn, _series(tmp_path, (108.4, 2_600_000), n=9))
    m = _move(conn)
    assert m.status == 'computed' and m.volume_ratio is None and m.volume_note == 'insufficient_history'
    assert 'volume ratio: insufficient history' in price_claim_lines(m)


def test_missing_volume_on_the_session(tmp_path):
    conn = new_store(tmp_path)
    _load(conn, _series(tmp_path, (108.4, None)))
    assert _move(conn).volume_note == 'no_volume'


# ── flags ────────────────────────────────────────────────────────────────────

def test_vendor_adjusted_close_is_a_cross_check_only(tmp_path):
    conn = new_store(tmp_path)
    path = _series(tmp_path, (108.4, 1_000_000, 104.0))
    text = path.read_text(encoding='utf-8').replace(f'{KEY},{PREV},,,,100.0,1000000,\n',
                                                    f'{KEY},{PREV},,,,100.0,1000000,100.0\n')
    path.write_text(text, encoding='utf-8')
    _load(conn, path)
    m = _move(conn)
    assert round(m.move_pct, 6) == 8.4 and round(m.vendor_move * 100, 6) == 4.0   # the raw basis is kept
    assert 'adjustment_mismatch' in m.flags


def test_dividend_ex_date_is_a_competing_factor(tmp_path):
    conn = new_store(tmp_path)
    _load(conn, _series(tmp_path, (108.4, 1_000_000)))
    _actions(conn, tmp_path, [f'{KEY},dividend,{D},,0.26,usd,https://example.com/div,\n'])
    m = _move(conn)
    assert m.k == 1 and 'dividend_ex_date 0.26 USD' in m.flags
    assert 'flag: dividend_ex_date 0.26 USD' in price_claim_lines(m)


# ── corporate-action import ──────────────────────────────────────────────────

def test_action_import_is_idempotent_and_linked(tmp_path):
    conn = new_store(tmp_path)
    first = _actions(conn, tmp_path, [A3_BONUS])
    again = _actions(conn, tmp_path, [A3_BONUS], now=NOW + HOUR)
    assert list(first.statuses.values()) == ['inserted'] and list(again.statuses.values()) == ['unchanged']
    row = conn.execute('SELECT a.*, d.url, d.published_at FROM corporate_action a JOIN source_document d'
                       ' USING (doc_id)').fetchone()
    assert (row['new_per_old'], row['first_seen_at']) == (2.0, T(NOW))
    assert row['url'] == 'https://example.com/tdc/bonus-notice' and row['published_at'] == '2026-09-01T20:05:00Z'


def test_published_at_without_offset_uses_the_exchange_timezone(tmp_path):
    conn = new_store(tmp_path)
    _actions(conn, tmp_path, [f'{KEY},split,{D},2,,,https://example.com/s,2026-09-01 16:05\n'])
    doc = conn.execute('SELECT published_at, tz_assumed FROM source_document').fetchone()
    assert tuple(doc) == ('2026-09-01T20:05:00Z', 1)                       # New York, EDT


def test_changing_a_recorded_action_is_refused(tmp_path):
    conn = new_store(tmp_path)
    _actions(conn, tmp_path, [A3_BONUS])
    with pytest.raises(ActionInputError, match='not rewritten'):
        _actions(conn, tmp_path, [A3_BONUS.replace(',bonus,2026-09-22,2,', ',bonus,2026-09-22,3,')])
    assert conn.execute('SELECT new_per_old FROM corporate_action').fetchone()[0] == 2


BAD_ACTIONS = {
    'unknown security': ('US:NYSE:NOPE,split,2026-09-22,2,,,https://x.example/a,\n', 'unknown security_key'),
    'unknown type': (f'{KEY},merger,2026-09-22,2,,,https://x.example/a,\n', 'action_type must be'),
    'split without ratio': (f'{KEY},split,2026-09-22,,,,https://x.example/a,\n', 'needs new_per_old'),
    'split ratio of one': (f'{KEY},split,2026-09-22,1,,,https://x.example/a,\n', 'needs new_per_old'),
    'negative ratio': (f'{KEY},split,2026-09-22,-2,,,https://x.example/a,\n', 'finite positive'),
    'ratio on a dividend': (f'{KEY},dividend,2026-09-22,2,0.2,USD,https://x.example/a,\n', 'only to split and bonus'),
    'dividend without currency': (f'{KEY},dividend,2026-09-22,,0.2,,https://x.example/a,\n', '3-letter currency'),
    'cash on a split': (f'{KEY},split,2026-09-22,2,0.2,USD,https://x.example/a,\n', 'only to dividends'),
    'weekend ex date': (f'{KEY},split,2026-09-19,2,,,https://x.example/a,\n', 'not a NASDAQ session'),
    'uncovered year': (f'{KEY},split,2025-09-22,2,,,https://x.example/a,\n', 'not configured for 2025'),
    'insecure link': (f'{KEY},split,2026-09-22,2,,,http://x.example/a,\n', 'https link'),
    'future notice': (f'{KEY},split,2026-09-22,2,,,https://x.example/a,2026-09-30T00:00:00Z\n', 'in the future'),
}


@pytest.mark.parametrize('case', sorted(BAD_ACTIONS))
def test_bad_action_file_is_rejected_whole(tmp_path, case):
    row, message = BAD_ACTIONS[case]
    conn = new_store(tmp_path)
    ok = f'{KEY},dividend,2026-09-21,,0.1,USD,https://x.example/ok,\n'
    with pytest.raises(ActionInputError, match=re.escape(message)):
        _actions(conn, tmp_path, [ok, row])
    assert conn.execute('SELECT COUNT(*) FROM corporate_action').fetchone()[0] == 0
    assert conn.execute('SELECT COUNT(*) FROM source_document').fetchone()[0] == 0


# ── CLI: ingest imports prices and actions; `moves` shows them ───────────────

def test_cli_ingest_then_moves(tmp_path):
    (tmp_path / 'w.yaml').write_text(WATCHLIST, encoding='utf-8')
    prices = tmp_path / 'prices'
    prices.mkdir()
    _series(prices, (101.0, 2_000_000), close=200.0, name='tdca.csv')
    (tmp_path / 'ca.csv').write_text(CA_HEADER + A3_BONUS, encoding='utf-8')
    dbp = str(tmp_path / 'm.sqlite3')

    def run(*argv):
        out = io.StringIO()
        code = cli.main(['--db', dbp, *argv], now=NOW, out=out, http_get=FakeHttp())
        return code, out.getvalue()

    ingest = ('ingest', '--watchlist', str(tmp_path / 'w.yaml'), '--prices-dir', str(prices),
              '--corporate-actions', str(tmp_path / 'ca.csv'))
    code, text = run(*ingest)
    assert code == 0 and 'corporate actions: 1 row(s), 1 new' in text
    assert re.search(r'prices: tdca\.csv inserted \(import #1, 26 bars, sha256 [0-9a-f]{12}\)', text)
    code, text = run(*ingest)
    assert 'prices: tdca.csv unchanged (import #1' in text and 'corporate actions: 1 row(s), 0 new' in text

    code, text = run('moves', '--date', '2026-09-22', '--as-of', '2026-09-23T01:00:00Z')
    assert code == 0
    block = text.split('US:NASDAQ:TDCA')[1].split('\nUS:')[0]
    assert '[computed; no card, no trigger set]' in block and '+1.00% adjusted close-to-close' in block
    assert 'Upstream price source: unknown (owner-supplied file tdca.csv' in block
    assert 'US:NYSE:TQC' in text and 'stale: no price data' in text          # no prices imported for it
    assert 'US:NASDAQ:TDCB' in text

    code, text = run('moves', '--date', '2026-09-22', '--as-of', '2026-09-22T12:00:00Z')
    assert 'had not closed as of 2026-09-22T12:00:00Z' in text


def test_calc_version_changes_with_parameters():
    from src.compute import moves
    assert CALC_VERSION.startswith('moves/1+') and len(CALC_VERSION) == len('moves/1+') + 8
    assert db.sha256_json(dict(moves.PARAMS, guard_tolerance=0.03))[:8] != CALC_VERSION[-8:]
