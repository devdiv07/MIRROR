"""
Milestone 3 price provenance (ADR 0001 §5.1, §10): price CSV import, file hashes, declared upstream,
newest-import-wins as-of reads, and rejection of bad files. Offline; fixtures in tests/fixtures/prices.
"""

import hashlib
import re

import pytest

from src.sources.prices_csv import PriceInputError, import_price_file
from src.store import db
from tests.support import CALENDARS, HOUR, NOW, ROOT, new_store, sid

T = db.utc_iso
PRICES = ROOT / 'tests' / 'fixtures' / 'prices'
HEADER = 'security_key,trade_date,open,high,low,close,volume,adj_close\n'


def _import(conn, path, now=NOW):
    return import_price_file(conn, str(path), now=now, calendars=CALENDARS)


def _write(tmp_path, text, name='prices.csv'):
    p = tmp_path / name
    p.write_text(text, encoding='utf-8')
    return p


def test_unknown_upstream_file_is_recorded_with_its_hash(tmp_path):                   # P1 (import)
    conn = new_store(tmp_path)
    path = PRICES / 'us_unknown_upstream.csv'
    result = _import(conn, path)

    assert result.status == 'inserted' and result.rows == 4
    imp = conn.execute('SELECT * FROM price_import').fetchone()
    assert imp['file_name'] == 'us_unknown_upstream.csv'
    assert imp['file_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert (imp['declared_vendor'], imp['declared_source_url'], imp['vendor_as_of']) == ('unknown', None, None)
    assert (imp['imported_at'], imp['row_count']) == (T(NOW), 4)
    bar = conn.execute("SELECT * FROM price_bar WHERE security_id = ? AND trade_date = '2026-09-22'",
                       (sid(conn, 'US:NASDAQ:TDCA'),)).fetchone()
    assert (bar['close_raw'], bar['volume'], bar['close_vendor_adj'], bar['import_id']) == (108.4, 2600000, None, 1)


def test_declared_vendor_link_and_as_of_are_kept(tmp_path):
    conn = new_store(tmp_path)
    _import(conn, PRICES / 'us_declared_vendor.csv')
    imp = conn.execute('SELECT * FROM price_import').fetchone()
    assert imp['declared_vendor'] == 'Example Data Co end-of-day export (synthetic)'
    assert imp['declared_source_url'] == 'https://data.example.com/eod/TDCA'
    assert imp['vendor_as_of'] == '2026-09-23T02:15:00Z'                 # -04:00 converted to UTC


def test_same_file_twice_changes_nothing(tmp_path):
    conn = new_store(tmp_path)
    first = _import(conn, PRICES / 'us_unknown_upstream.csv')
    again = _import(conn, PRICES / 'us_unknown_upstream.csv', now=NOW + HOUR)
    assert again.status == 'unchanged' and again.import_id == first.import_id
    assert conn.execute('SELECT COUNT(*) FROM price_import').fetchone()[0] == 1
    assert conn.execute('SELECT COUNT(*) FROM price_bar').fetchone()[0] == 4


def test_corrected_file_is_a_new_import_and_reads_are_as_of(tmp_path):
    conn = new_store(tmp_path)
    _import(conn, PRICES / 'us_unknown_upstream.csv')
    corrected = _write(tmp_path, HEADER + 'US:NASDAQ:TDCA,2026-09-22,100.50,110.40,100.10,108.45,2600000,\n',
                       'corrected.csv')
    later = NOW + 2 * HOUR
    _import(conn, corrected, now=later)

    tdca = sid(conn, 'US:NASDAQ:TDCA')
    then = db.price_bars_as_of(conn, tdca, T(NOW + HOUR))
    now = db.price_bars_as_of(conn, tdca, T(later))
    assert then['2026-09-22']['close_raw'] == 108.40 and then['2026-09-22']['import_id'] == 1
    assert now['2026-09-22']['close_raw'] == 108.45 and now['2026-09-22']['file_name'] == 'corrected.csv'
    assert now['2026-09-21']['import_id'] == 1                           # untouched days keep their import
    assert db.price_bars_as_of(conn, tdca, T(NOW - HOUR)) == {}          # nothing was imported yet
    assert list(db.price_bars_as_of(conn, tdca, T(later), through='2026-09-21')) == ['2026-09-21']


BAD_FILES = {
    'unknown security': (HEADER + 'US:NYSE:NOPE,2026-09-22,,,,10,,\n', 'unknown security_key'),
    'weekend': (HEADER + 'US:NYSE:TQC,2026-09-19,,,,10,,\n', 'closed on 2026-09-19 (weekend)'),
    'holiday': (HEADER + 'US:NYSE:TQC,2026-09-07,,,,10,,\n', 'closed on 2026-09-07 (Labor Day)'),
    'uncovered year': (HEADER + 'US:NASDAQ:TDCA,2025-09-22,,,,10,,\n', 'not configured for 2025'),
    'session not closed': (HEADER + 'US:NYSE:TQC,2026-09-23,,,,10,,\n', 'had not closed'),
    'repeated day': (HEADER + 'US:NYSE:TQC,2026-09-22,,,,10,,\n' * 2, 'a second row'),
    'zero close': (HEADER + 'US:NYSE:TQC,2026-09-22,,,,0,,\n', 'finite positive'),
    'nan close': (HEADER + 'US:NYSE:TQC,2026-09-22,,,,nan,,\n', 'finite positive'),
    'infinite close': (HEADER + 'US:NYSE:TQC,2026-09-22,,,,inf,,\n', 'finite positive'),
    'missing close': (HEADER + 'US:NYSE:TQC,2026-09-22,1,1,1,,5,\n', 'close is required'),
    'negative volume': (HEADER + 'US:NYSE:TQC,2026-09-22,,,,10,-5,\n', 'finite non-negative'),
    'high below close': (HEADER + 'US:NYSE:TQC,2026-09-22,10,10.5,9,11,,\n', 'inconsistent'),
    'low above open': (HEADER + 'US:NYSE:TQC,2026-09-22,10,12,10.5,11,,\n', 'inconsistent'),
    'bad date': (HEADER + 'US:NYSE:TQC,22/09/2026,,,,10,,\n', 'not YYYY-MM-DD'),
    'no close column': ('security_key,trade_date,price\nUS:NYSE:TQC,2026-09-22,10\n', "missing columns ['close']"),
    'unknown declaration': ('# provider: x\n' + HEADER + 'US:NYSE:TQC,2026-09-22,,,,10,,\n', 'declarations are'),
    'insecure link': ('# source_url: http://x.example\n' + HEADER + 'US:NYSE:TQC,2026-09-22,,,,10,,\n', 'https'),
    'as_of without offset': ('# as_of: 2026-09-22T22:00\n' + HEADER + 'US:NYSE:TQC,2026-09-22,,,,10,,\n', 'offset'),
    'no rows': (HEADER, 'no price rows'),
}


@pytest.mark.parametrize('case', sorted(BAD_FILES))
def test_bad_file_is_rejected_whole(tmp_path, case):
    text, message = BAD_FILES[case]
    conn = new_store(tmp_path)
    good_first = 'US:NYSE:TQC,2026-09-21,,,,10,,\n'                      # a valid row before the bad one
    if text.startswith(HEADER) and text != HEADER:
        text = HEADER + good_first + text[len(HEADER):]
    with pytest.raises(PriceInputError, match=re.escape(message)):
        _import(conn, _write(tmp_path, text))
    assert conn.execute('SELECT COUNT(*) FROM price_import').fetchone()[0] == 0
    assert conn.execute('SELECT COUNT(*) FROM price_bar').fetchone()[0] == 0


def test_line_numbers_count_the_declarations(tmp_path):
    conn = new_store(tmp_path)
    text = '# vendor: x\n' + HEADER + 'US:NYSE:TQC,2026-09-21,,,,10,,\nUS:NYSE:TQC,2026-09-22,,,,-1,,\n'
    with pytest.raises(PriceInputError, match=r'prices\.csv:4: close'):
        _import(conn, _write(tmp_path, text))
