import os
import time
import requests
import xml.etree.ElementTree as ET
import pandas as pd
from datetime import datetime

# SEC requires identification in the User-Agent header
HEADER = {
    'User-Agent': os.getenv(
        'SEC_USER_AGENT',
        'MIRROR/1.0 (contact: your_email@example.com)'
    )
}

# CIK = SEC's unique company identifier — same mapping as SEC_INSIDER.PY
COMPANY_CIK_MAP = {
    'AAPL':  '0000320193',
    'MSFT':  '0000789019',
    'NVDA':  '0001045810',
    'TSLA':  '0001318605',
    'JPM':   '0000019617',
    'GS':    '0000886982',
    'META':  '0001326801',
    'GOOGL': '0001652044',
    'AMZN':  '0001018724',
    'NFLX':  '0001065280'
}

# Only open-market transactions carry a real price signal.
#   P = open-market Purchase → insider paid market price → strong bullish signal
#   S = open-market Sale
#   F = Tax withholding (shares sold to cover taxes — still real selling)
# Skipped: A (award), M (option exercise), G (gift), D (disposition), J (other)
# Skipped transactions don't reflect the insider's opinion of fair value.
BUY_CODES  = {'P'}
SELL_CODES = {'S', 'F'}


def build_filing_url(cik_str, accession_number, document_filename):
    """
    Build the EDGAR document URL for a single Form 4 filing.

    How it works:
      CIK:        '0000320193' → strip leading zeros → '320193'
      Accession:  '0001140361-26-023363' → remove dashes → '000114036126023363'
      Document:   'xslF345X06/form4.xml' → take part after last '/' → 'form4.xml'
                  (the 'xslF345X06/' prefix is an XSLT stylesheet reference, not a folder)

    Final URL format:
      https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc_filename}
    """
    numeric_cik    = str(int(cik_str))
    accession_clean = accession_number.replace('-', '')
    doc_filename   = document_filename.split('/')[-1]
    return (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{numeric_cik}/{accession_clean}/{doc_filename}"
    )


def fetch_form4_xml(url):
    """
    Fetch a Form 4 XML document from EDGAR.
    Returns the raw XML string, or None on any failure.
    """
    try:
        response = requests.get(url, headers=HEADER, timeout=10)
        if response.status_code != 200:
            return None
        return response.text
    except Exception:
        return None


def parse_form4_xml(xml_text, ticker, filing_date):
    """
    Parse a Form 4 XML document and extract open-market buy/sell transactions.

    Returns a list of dicts, one per transaction:
        ticker, date, filing_date, insider_name, title,
        transaction_type, transaction_code, shares, price, dollar_value

    dollar_value is SIGNED:
        positive  =  net buying  (cash out of insider's pocket — bullish)
        negative  =  net selling (cash into insider's pocket  — bearish)

    Key Form 4 XML tags used:
        <rptOwnerName>                        — insider's full name
        <officerTitle>                        — their role (CEO, CFO, Director, etc.)
        <nonDerivativeTransaction>            — one block per open-market trade
          <transactionDate><value>            — trade date
          <transactionCode>                   — P/S/F/A/M/G/D/J
          <transactionShares><value>          — number of shares
          <transactionPricePerShare><value>   — price paid/received
    """
    transactions = []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return transactions  # Malformed XML — skip silently

    # Insider identity — one person per Form 4
    insider_name = ''
    title        = ''
    name_el  = root.find('.//rptOwnerName')
    if name_el is not None and name_el.text:
        insider_name = name_el.text.strip()
    title_el = root.find('.//officerTitle')
    if title_el is not None and title_el.text:
        title = title_el.text.strip()

    # Each <nonDerivativeTransaction> block = one open-market trade
    for tx in root.findall('.//nonDerivativeTransaction'):

        code_el = tx.find('.//transactionCode')
        if code_el is None or not code_el.text:
            continue
        code = code_el.text.strip()

        if code not in BUY_CODES and code not in SELL_CODES:
            continue  # Skip awards, exercises, gifts — not market conviction

        # Transaction date (fall back to the filing date if field is missing)
        date_el = tx.find('.//transactionDate/value')
        tx_date = (
            date_el.text.strip()
            if date_el is not None and date_el.text
            else filing_date
        )

        # Number of shares transacted
        shares_el = tx.find('.//transactionShares/value')
        if shares_el is None or not shares_el.text:
            continue
        try:
            shares = float(shares_el.text.strip())
        except ValueError:
            continue

        # Price per share (zero means price was not reported in the filing)
        price_el = tx.find('.//transactionPricePerShare/value')
        price = 0.0
        if price_el is not None and price_el.text:
            try:
                price = float(price_el.text.strip())
            except ValueError:
                price = 0.0

        # Signed dollar value: positive = buying, negative = selling
        if code in BUY_CODES:
            tx_type     = 'BUY'
            dollar_value = shares * price
        else:
            tx_type     = 'SELL'
            dollar_value = -(shares * price)

        transactions.append({
            'ticker':           ticker,
            'date':             tx_date,
            'filing_date':      filing_date,
            'insider_name':     insider_name,
            'title':            title,
            'transaction_type': tx_type,
            'transaction_code': code,
            'shares':           shares,
            'price':            price,
            'dollar_value':     dollar_value,
        })

    return transactions


def parse_all_filings(filings_csv_path='data/insider_filings.csv'):
    """
    Main entry point. Loads insider_filings.csv, fetches + parses each
    Form 4 XML from EDGAR, and saves transaction-level data to
    data/insider_transactions.csv.

    This replaces the filing-count proxy in SEC_INSIDER.PY with actual
    buy/sell dollar volumes that reflect insider conviction.
    """
    print("=" * 60)
    print("MIRROR - Form 4 Transaction Parser")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    try:
        filings_df = pd.read_csv(filings_csv_path)
    except FileNotFoundError:
        print(f"ERROR: {filings_csv_path} not found. Run SEC_INSIDER.PY first.")
        return pd.DataFrame()

    total            = len(filings_df)
    all_transactions = []
    error_count      = 0

    for idx, row in filings_df.iterrows():
        ticker      = row['ticker']
        filing_date = row['filing_date']
        accession   = row['accession']
        document    = row['document']

        cik = COMPANY_CIK_MAP.get(ticker)
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

        time.sleep(0.15)  # SEC rate limit — stay well under 10 req/sec

    df = pd.DataFrame(all_transactions)

    if df.empty:
        print("\nNo open-market transactions found in these filings.")
        return df

    df = df.sort_values('date', ascending=False).reset_index(drop=True)

    os.makedirs('data', exist_ok=True)
    df.to_csv('data/insider_transactions.csv', index=False)

    buy_total  = (df['transaction_type'] == 'BUY').sum()
    sell_total = (df['transaction_type'] == 'SELL').sum()

    print("\n" + "=" * 60)
    print(f"Filings processed : {total}")
    print(f"Fetch errors      : {error_count}")
    print(f"Transactions saved: {len(df)}  ({buy_total} BUY, {sell_total} SELL)")
    print(f"Saved to          : data/insider_transactions.csv")
    print("=" * 60)

    return df


def net_insider_signal_per_ticker(transactions_df, days=30):
    """
    Aggregate net buy/sell dollar volume over the last N days per ticker.

    Returns a dict:  {ticker: (signal_float, note_str)}

    Signal scale (identical thresholds used by dissonance_calculator.py):
      net buying  > +$1M   →  +0.7   strong buy signal
      net buying  > +$100K →  +0.3   mild buy signal
      net selling < -$1M   →  -0.7   heavy sell signal
      net selling < -$100K →  -0.3   mild sell signal
      otherwise            →   0.0   neutral
    """
    if transactions_df.empty:
        return {}

    df = transactions_df.copy()
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=days)
    recent = df[df['date'] > cutoff]

    result = {}
    for ticker, group in recent.groupby('ticker'):
        net_dollars = group['dollar_value'].sum()
        buy_count   = (group['transaction_type'] == 'BUY').sum()
        sell_count  = (group['transaction_type'] == 'SELL').sum()

        if net_dollars > 1_000_000:
            signal = 0.7
        elif net_dollars > 100_000:
            signal = 0.3
        elif net_dollars < -1_000_000:
            signal = -0.7
        elif net_dollars < -100_000:
            signal = -0.3
        else:
            signal = 0.0

        result[ticker] = (signal, f"Net: ${net_dollars:+,.0f} ({buy_count}B/{sell_count}S)")

    return result


if __name__ == "__main__":
    df = parse_all_filings()

    if not df.empty:
        print("\n=== NET INSIDER ACTIVITY (last 30 days) ===\n")
        signals = net_insider_signal_per_ticker(df, days=30)
        if signals:
            for ticker, (signal, note) in sorted(signals.items()):
                direction = "↑ BUY" if signal > 0 else ("↓ SELL" if signal < 0 else "─ NEUTRAL")
                print(f"  {ticker:6}  signal={signal:+.1f}  {direction:10}  {note}")
        else:
            print("  No open-market transactions in the last 30 days.")
