"""
insider_parser_v2.py

Updated Form 4 parser that extracts everything v1 does PLUS the
ownership fields needed by the conviction scorer:

  - shares_owned_after_transaction   (from <sharesOwnedFollowingTransaction>)
  - shares_owned_prior_to_transaction (from <sharesOwnedPriorToTransaction>, if present)
  - is_derivative                     (whether this is a derivative transaction)
  - is_director / is_officer / is_ten_pct_owner / is_other
                                    (insider role flags, for the role scorer)

The transaction-level output is the foundation for the conviction
scorer — without these fields, we can't compute pct_holdings_transacted.

Usage:
  Same as v1, but the resulting DataFrame has extra columns that
  feed into enrich_ownership.py.
"""

import os
import time
import requests
import defusedxml.ElementTree as ET
import pandas as pd
from datetime import datetime

from src.parsers.universe import resolve_universe

HEADER = {
    'User-Agent': os.getenv(
        'SEC_USER_AGENT',
        'MIRROR/1.0 (contact: raghavdharwal07@gmail.com)'
    )
}

# Legacy fallback — used only when running against the old 10-ticker mega-cap CSV.
_LEGACY_CIK_MAP = {
    'AAPL':  '0000320193',
    'MSFT':  '0000789019',
    'NVDA':  '0001045810',
    'TSLA':  '0001318605',
    'JPM':   '0000019617',
    'GS':    '0000886982',
    'META':  '0001326801',
    'GOOGL': '0001652044',
    'AMZN':  '0001018724',
    'NFLX':  '0001065280',
}

BUY_CODES  = {'P'}
SELL_CODES = {'S', 'F'}


def _safe_float(elem) -> float:
    """Extract a float from an XML element, returning 0.0 on any failure."""
    if elem is None or not elem.text:
        return 0.0
    try:
        return float(elem.text.strip())
    except (ValueError, AttributeError):
        return 0.0


def _safe_text(elem) -> str:
    """Extract text from an XML element, returning '' on any failure."""
    if elem is None or not elem.text:
        return ''
    return elem.text.strip()


def build_filing_url(cik_str, accession_number, document_filename):
    numeric_cik    = str(int(cik_str))
    accession_clean = accession_number.replace('-', '')
    doc_filename   = document_filename.split('/')[-1]
    return (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{numeric_cik}/{accession_clean}/{doc_filename}"
    )


def fetch_form4_xml(url):
    try:
        response = requests.get(url, headers=HEADER, timeout=10)
        if response.status_code != 200:
            return None
        return response.text
    except Exception:
        return None


def _extract_owner_flags(root):
    """
    Extract insider role flags from the Form 4 owner block.

    Returns dict with: is_director, is_officer, is_ten_pct_owner, is_other,
    and is_company (True when the reporting owner is an entity, not a person).
    Entity filers (ESPP trusts, 401k plans, index funds) are non-discretionary
    and must be excluded from signal scoring via the aggregator gate.
    """
    flags = {
        'is_director':      False,
        'is_officer':       False,
        'is_ten_pct_owner': False,
        'is_other':         False,
        'is_company':       False,
    }

    # Primary: read <isCompany> from <reportingOwnerType> (present in all modern Form 4s).
    is_company_el = root.find('.//reportingOwner/reportingOwnerType/isCompany')
    if is_company_el is not None and is_company_el.text:
        flags['is_company'] = is_company_el.text.strip() in ('1', 'true', 'yes')
    else:
        # Fallback: detect entity filers via name keyword heuristics for older filings.
        _ENTITY_KEYWORDS = frozenset({
            'INC', 'INC.', 'LLC', 'LLC.', 'LP', 'L.P.', 'LLP', 'L.L.P.',
            'CORP', 'CORP.', 'CORPORATION', 'GROUP', 'FUND', 'TRUST',
            'PARTNERS', 'PARTNERSHIP', 'HOLDINGS', 'COMPANY', 'CO', 'CO.',
            'LTD', 'LTD.', 'PLC', 'BANK', 'CAPITAL', 'ASSOCIATION',
            'FOUNDATION', 'VENTURES', 'ADVISORS', 'MANAGEMENT',
        })
        owner_name = (root.findtext('.//rptOwnerName') or '').upper()
        name_words = set(owner_name.replace(',', ' ').replace('.', ' ').split())
        flags['is_company'] = bool(name_words & _ENTITY_KEYWORDS)

    # <rptOwnerRelationship> block contains the role flags as direct child elements
    relationship = root.find('.//reportingOwner/reportingOwnerRelationship')
    if relationship is None:
        return flags

    tag_map = {'is_director': 'isDirector', 'is_officer': 'isOfficer', 'is_ten_pct_owner': 'isTenPercentOwner', 'is_other': 'isOther'}
    for py_key, xml_tag in tag_map.items():
        el = relationship.find(xml_tag)
        if el is not None and el.text:
            val = el.text.strip().lower()
            flags[py_key] = val in ('1', 'true', 'yes')

    return flags


def _extract_ownership(elem):
    """
    Extract sharesOwnedFollowingTransaction and sharesOwnedPriorToTransaction
    from a transaction element.

    Returns (shares_after, shares_before) — either can be None if not present.
    """
    shares_after = None
    shares_before = None

    after_el = elem.find('.//sharesOwnedFollowingTransaction/value')
    if after_el is not None and after_el.text:
        try:
            shares_after = float(after_el.text.strip())
        except ValueError:
            pass

    before_el = elem.find('.//sharesOwnedPriorToTransaction/value')
    if before_el is not None and before_el.text:
        try:
            shares_before = float(before_el.text.strip())
        except ValueError:
            pass

    return shares_after, shares_before


def parse_form4_xml(xml_text, ticker, filing_date):
    """
    Parse a Form 4 XML and extract transaction-level data.

    Returns a list of dicts with the v1 fields PLUS:
      - shares_owned_after_transaction
      - shares_owned_prior_to_transaction (newer filings only)
      - is_derivative
      - is_director, is_officer, is_ten_pct_owner, is_other
    """
    transactions = []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return transactions

    insider_name = _safe_text(root.find('.//rptOwnerName'))
    title        = _safe_text(root.find('.//officerTitle'))
    owner_flags  = _extract_owner_flags(root)

    # 10b5-1 plan flag: root-level tag, present post-Dec 2022.
    # Value: '1' = confirmed plan trade, '0' = not a plan trade, absent = unknown.
    aff_el = root.find('aff10b5One')
    is_10b51_raw = None
    if aff_el is not None and aff_el.text:
        try:
            is_10b51_raw = int(aff_el.text.strip())
        except (ValueError, AttributeError):
            is_10b51_raw = None

    # Footnote text: concatenate all <footnote> elements in the filing.
    # These carry free-text plan language for pre-2023 filings where
    # <aff10b5One> didn't exist. enrich_tenb51.py regex-scans this text.
    footnote_texts = [
        f.text.strip()
        for f in root.findall('.//footnote')
        if f.text and f.text.strip()
    ]
    footnotes = ' | '.join(footnote_texts) if footnote_texts else None

    # Non-derivative transactions (common stock)
    for tx in root.findall('.//nonDerivativeTransaction'):
        tx_list = _parse_transaction_block(
            tx, ticker, filing_date, insider_name, title,
            owner_flags, is_derivative=False,
            is_10b51_raw=is_10b51_raw, footnotes=footnotes,
        )
        transactions.extend(tx_list)

    # Derivative transactions (options, RSUs, etc.)
    # We still skip the *buy* side of derivatives (M, X, etc.) but
    # we record the *ownership* of derivatives for downstream scoring
    if False:  # Disabled by default; enable if you want derivative coverage
        for tx in root.findall('.//derivativeTransaction'):
            tx_list = _parse_transaction_block(
                tx, ticker, filing_date, insider_name, title,
                owner_flags, is_derivative=True,
                is_10b51_raw=is_10b51_raw, footnotes=footnotes,
            )
            transactions.extend(tx_list)

    return transactions


def _parse_transaction_block(
    tx, ticker, filing_date, insider_name, title,
    owner_flags, is_derivative,
    is_10b51_raw=None, footnotes=None,
):
    """Parse a single transaction element (non-deriv or deriv)."""
    transactions = []

    code_el = tx.find('.//transactionCode')
    if code_el is None or not code_el.text:
        return transactions
    code = code_el.text.strip()

    if code not in BUY_CODES and code not in SELL_CODES:
        return transactions  # Skip awards, exercises, gifts, etc.

    # Transaction date
    date_el = tx.find('.//transactionDate/value')
    tx_date = (
        date_el.text.strip()
        if date_el is not None and date_el.text
        else filing_date
    )

    # Shares
    shares_el = tx.find('.//transactionShares/value')
    if shares_el is None or not shares_el.text:
        return transactions
    try:
        shares = float(shares_el.text.strip())
    except ValueError:
        return transactions

    # Price
    price = _safe_float(tx.find('.//transactionPricePerShare/value'))

    # Ownership (the key new fields for conviction scoring)
    shares_after, shares_before = _extract_ownership(tx)

    # Signed dollar value
    if code in BUY_CODES:
        tx_type      = 'BUY'
        dollar_value = shares * price
    else:
        tx_type      = 'SELL'
        dollar_value = -(shares * price)

    transactions.append({
        'ticker':                          ticker,
        'date':                            tx_date,
        'filing_date':                     filing_date,
        'insider_name':                    insider_name,
        'title':                           title,
        'transaction_type':                tx_type,
        'transaction_code':                code,
        'shares':                          shares,
        'price':                           price,
        'dollar_value':                    dollar_value,
        # NEW for v2
        'shares_owned_after_transaction':  shares_after,
        'shares_owned_prior_to_transaction': shares_before,
        'is_derivative':                   is_derivative,
        'is_director':                     owner_flags['is_director'],
        'is_officer':                      owner_flags['is_officer'],
        'is_ten_pct_owner':                owner_flags['is_ten_pct_owner'],
        'is_other':                        owner_flags['is_other'],
        'is_company':                      owner_flags['is_company'],
        # 10b5-1 detection fields (consumed by enrich_tenb51.py)
        'is_10b51_raw':                    is_10b51_raw,
        'footnotes':                       footnotes,
    })

    return transactions


def parse_all_filings(filings_csv_path='data/insider_filings.csv'):
    print("=" * 60)
    print("MIRROR - Form 4 Transaction Parser v2")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    try:
        filings_df = pd.read_csv(filings_csv_path)
    except FileNotFoundError:
        print(f"ERROR: {filings_csv_path} not found.")
        return pd.DataFrame()

    total            = len(filings_df)
    all_transactions = []
    error_count      = 0

    # Resolve CIKs for every ticker in this CSV in one shot. Merge the
    # legacy mega-cap map so old test CSVs still work without hitting SEC.
    unique_tickers = filings_df['ticker'].unique().tolist()
    cik_map, _ = resolve_universe(unique_tickers)
    cik_map = {**_LEGACY_CIK_MAP, **cik_map}  # live map wins on conflicts

    for idx, row in filings_df.iterrows():
        ticker      = row['ticker']
        filing_date = row['filing_date']
        accession   = row['accession']
        document    = row['document']

        cik = cik_map.get(ticker)
        if not cik:
            continue

        url      = build_filing_url(cik, accession, document)
        xml_text = fetch_form4_xml(url)

        if xml_text is None:
            error_count += 1
            buy_count  = 0
            sell_count = 0
        else:
            tx_list    = parse_form4_xml(xml_text, ticker, filing_date)
            buy_count  = sum(1 for t in tx_list if t['transaction_type'] == 'BUY')
            sell_count = sum(1 for t in tx_list if t['transaction_type'] == 'SELL')
            all_transactions.extend(tx_list)

        doc_label = document.split('/')[-1]
        print(
            f"[{idx+1:3}/{total}] {ticker:6} {filing_date}  "
            f"{buy_count}B / {sell_count}S  {doc_label}"
        )

        time.sleep(0.15)

    df = pd.DataFrame(all_transactions)

    if df.empty:
        print("\nNo open-market transactions found.")
        return df

    df = df.sort_values('date', ascending=False).reset_index(drop=True)

    os.makedirs('data', exist_ok=True)
    df.to_csv('data/insider_transactions.csv', index=False)

    buy_total  = (df['transaction_type'] == 'BUY').sum()
    sell_total = (df['transaction_type'] == 'SELL').sum()
    with_ownership = df['shares_owned_after_transaction'].notna().sum()

    print("\n" + "=" * 60)
    print(f"Filings processed       : {total}")
    print(f"Fetch errors            : {error_count}")
    print(f"Transactions saved      : {len(df)}  ({buy_total} BUY, {sell_total} SELL)")
    print(f"With ownership data     : {with_ownership} ({100*with_ownership/len(df):.0f}%)")
    print(f"Saved to                : data/insider_transactions.csv")
    print("=" * 60)

    return df


if __name__ == "__main__":
    df = parse_all_filings()

    if not df.empty:
        # Phase 1 demo: enrich -> score -> show top signals
        from enrich_ownership import enrich_ownership
        from scoring.aggregator import aggregate, load_config

        print("\n=== ENRICHING OWNERSHIP DATA ===\n")
        enriched = enrich_ownership(df)
        print(f"Computed pct_holdings_transacted for "
              f"{enriched['pct_holdings_transacted'].notna().sum()} transactions")

        print("\n=== LOADING SCORING CONFIG ===\n")
        config = load_config('config/scoring.yaml')
        print(f"Enabled scorers: {[k for k, v in config.items() if v.get('enabled')]}")

        print("\n=== SCORING (conviction-only Phase 1) ===\n")
        # Phase 1: only conviction is registered, so we need a minimal config
        # that doesn't try to require missing scorers
        minimal_config = {
            'conviction_score': config.get('conviction_score', {'weight': 0.30, 'enabled': True}),
        }
        enriched['conviction_signal'] = enriched.apply(
            lambda row: aggregate(row.to_dict(), config=minimal_config), axis=1
        )

        # Show top signals
        top = enriched.nlargest(10, 'conviction_signal')[
            ['ticker', 'date', 'insider_name', 'title', 'transaction_type',
             'shares', 'shares_owned_after_transaction', 'pct_holdings_transacted',
             'conviction_signal']
        ]
        print(top.to_string(index=False))
