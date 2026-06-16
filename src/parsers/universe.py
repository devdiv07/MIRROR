"""
universe.py — resolve a list of tickers to SEC CIKs.

Replaces the hardcoded 10-ticker COMPANY_CIK_MAP. SEC publishes a single
file mapping every filer's ticker -> CIK, so we can point the pipeline at
any curated universe (small/mid-caps, where insider *buying* actually
carries signal) without hand-maintaining CIKs.

Source: https://www.sec.gov/files/company_tickers.json  (~10k filers)
"""

import os
import json
import time
import requests

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
CACHE_PATH = os.path.join("data", "company_tickers.json")

HEADER = {
    'User-Agent': os.getenv(
        'SEC_USER_AGENT',
        'MIRROR/1.0 (contact: raghavdharwal07@gmail.com)'
    )
}


def _load_ticker_cik_index(refresh=False):
    """
    Return {TICKER: 'zero-padded-10-digit-CIK'} for every SEC filer.

    Cached to data/company_tickers.json so we hit SEC only once.
    """
    if not refresh and os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, 'r') as f:
            raw = json.load(f)
    else:
        resp = requests.get(COMPANY_TICKERS_URL, headers=HEADER, timeout=30)
        resp.raise_for_status()
        raw = resp.json()
        os.makedirs('data', exist_ok=True)
        with open(CACHE_PATH, 'w') as f:
            json.dump(raw, f)
        time.sleep(0.2)

    # raw is {"0": {"cik_str": int, "ticker": str, "title": str}, ...}
    index = {}
    for record in raw.values():
        ticker = record['ticker'].upper()
        cik = str(record['cik_str']).zfill(10)
        index[ticker] = cik
    return index


def resolve_universe(tickers, refresh=False):
    """
    Map a list of tickers to {ticker: cik}, dropping any that SEC doesn't know.

    Returns (cik_map, unresolved_list).
    """
    index = _load_ticker_cik_index(refresh=refresh)
    cik_map = {}
    unresolved = []
    for t in tickers:
        t = t.strip().upper()
        if not t:
            continue
        cik = index.get(t)
        if cik:
            cik_map[t] = cik
        else:
            unresolved.append(t)
    return cik_map, unresolved


def load_universe_tickers(path=os.path.join("config", "universe_smallmid.txt")):
    """
    Load the curated ticker list. One ticker per line; '#' starts a comment.
    """
    tickers = []
    with open(path, 'r') as f:
        for line in f:
            line = line.split('#', 1)[0].strip()
            if line:
                tickers.append(line.upper())
    return tickers


if __name__ == "__main__":
    tickers = load_universe_tickers()
    cik_map, unresolved = resolve_universe(tickers)
    print(f"requested : {len(tickers)}")
    print(f"resolved  : {len(cik_map)}")
    print(f"unresolved: {len(unresolved)}  {unresolved}")
