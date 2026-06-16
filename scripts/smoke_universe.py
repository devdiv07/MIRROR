"""
smoke_universe.py — does the small/mid-cap universe actually contain
open-market insider BUYS (code P)? That is the whole premise. Runs on a
small subset, fetches + parses Form 4s in memory, tallies codes. Writes
nothing to the canonical data/ CSVs.
"""
import sys, os, time
from collections import Counter
sys.path.insert(0, os.path.abspath('.'))

from src.parsers.universe import load_universe_tickers, resolve_universe
from src.parsers.sec_filings_fetcher import get_company_filings
from src.parsers.insider_parser_v2 import build_filing_url, fetch_form4_xml, parse_form4_xml

SUBSET = ['CROX', 'MGY', 'AEIS', 'CATY', 'NOG']
SMOKE_LOOKBACK_DAYS = 60  # short window — just validate P codes exist

cik_map, _ = resolve_universe(SUBSET)
print(f"Smoke universe: {len(cik_map)} tickers\n")

code_counter = Counter()
buys_by_ticker = Counter()
total_tx = 0

import src.parsers.sec_filings_fetcher as _ff
_orig = _ff.FILING_LOOKBACK_DAYS
_ff.FILING_LOOKBACK_DAYS = SMOKE_LOOKBACK_DAYS

for ticker, cik in cik_map.items():
    filings = get_company_filings(ticker, cik)
    tx_count = 0
    for f in filings:
        url = build_filing_url(cik, f['accession'], f['document'])
        xml = fetch_form4_xml(url)
        if not xml:
            continue
        txs = parse_form4_xml(xml, ticker, f['filing_date'])
        for t in txs:
            code_counter[t['transaction_code']] += 1
            tx_count += 1
            total_tx += 1
            if t['transaction_code'] == 'P':
                buys_by_ticker[ticker] += 1
        time.sleep(0.12)
    print(f"  {ticker:6} {len(filings):3} filings -> {tx_count:3} tx  "
          f"({buys_by_ticker[ticker]} open-market buys)")

print("\n" + "=" * 50)
print("TRANSACTION CODE DISTRIBUTION")
for code, n in code_counter.most_common():
    label = {'P': 'open-market BUY', 'S': 'open-market sell',
             'F': 'tax withholding'}.get(code, 'other')
    print(f"  {code}: {n:5}  ({label})")
print(f"\nTotal transactions : {total_tx}")
print(f"Open-market BUYS    : {code_counter['P']}")
print(f"Tickers with buys   : {len(buys_by_ticker)}/{len(cik_map)}")
print("=" * 50)
