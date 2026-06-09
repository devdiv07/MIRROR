import requests
import pandas as pd
import time
import os
from datetime import datetime, timedelta

# Only collect filings from the last 90 days.
# EDGAR returns the full history (sometimes 1000s of filings) with no
# built-in limit — this cutoff keeps the dataset small and relevant.
FILING_LOOKBACK_DAYS = 90

HEADER = {
    'User-Agent': os.getenv(
        'SEC_USER_AGENT',
        'MIRROR/1.0 (contact: your_email@example.com)'
    )
}

# ============================================
# CIK = SEC's unique ID for each company
# This is how SEC identifies companies
# ============================================
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

def get_company_filings(ticker, cik):
    """
    Hit SEC EDGAR API and get all recent filings
    for one company.
    
    Form 4 = Insider bought or sold stock
    Form 4 is what we want.
    """
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        response = requests.get(url, headers=HEADER)
        # If SEC blocks us, stop and show error
        if response.status_code != 200:
            print(f"ERROR: SEC returned {response.status_code} for {ticker}")
            return []
        data = response.json()
        # Extract filings 
        filings = data['filings']['recent']
        #pull out filings we need
        forms = filings['form']
        dates = filings['filingDate']
        documents = filings['primaryDocument']
        accession = filings['accessionNumber']
        # Filter: only keep Form 4 filings within the lookback window.
        # Without this, EDGAR returns the full history (1000s of filings).
        cutoff = (datetime.now() - timedelta(days=FILING_LOOKBACK_DAYS)).strftime('%Y-%m-%d')
        results = []
        for i, form in enumerate(forms):
            if form == '4' and dates[i] >= cutoff:
                results.append({
                    'ticker': ticker,
                    'filing_date': dates[i],
                    'document': documents[i],
                    'accession': accession[i],
                    'form_type': form
                })
        return results
    except Exception as e:
        print(f"ERROR: Failed to get filings for {ticker}: {e}")
        return []

def collect_all_insider_filings():
    """
    Loop through every company in our list.
    Collect all Form 4 filings.
    Save to CSV.
    """
    print("=" * 50)
    print("MIRROR-SEC-INSIDER-Filing Collector")
    print(f"Started {datetime.now().strftime('%y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    all_filings = []
    for ticker, cik in COMPANY_CIK_MAP.items():
        print(f"\nfetching filings for {ticker}...")

        filings = get_company_filings(ticker, cik)
        count = len(filings)
        all_filings.extend(filings)
        print(f"found {count} form 4 filing")
        # IMPORTANT: Wait 0.5 seconds between requests
        # SEC will block you if you hit them too fast
        time.sleep(0.5)

    #convert to DataFrame and save
    df = pd.DataFrame(all_filings)

    if df.empty:
        print("No filings found. Exiting.")
        return df
    #sort by date newest first
    df = df.sort_values('filing_date', ascending=False)

    #save to CSV
    os.makedirs('data', exist_ok=True)
    df.to_csv('data/insider_filings.csv', index=False)

    print("\n" + "=" * 50)
    print(f"total filings collected: {len(df)}")
    print(f"Saved to: data/insider_filings.csv")
    print("=" * 50)

    return df
def analyze_insider_activity(df):
    """
    Quick analysis of what we collected.
    How many filings per company?
    What is the date range?
    """
    
    if df.empty:
        print("No data to analyze.")
        return
    
    print("\n=== INSIDER ACTIVITY SUMMARY ===\n")

    # count filing per company
    summary = df.groupby('ticker').agg(#THIS LINE SAYS THAT WE ARE GROUPING THE DATAFRAME (df) BY THE 'ticker' COLUMN AND THEN APPLYING AGGREGATION FUNCTIONS TO CALCULATE SUMMARY STATISTICS FOR EACH GROUP. THE AGGREGATION FUNCTIONS SPECIFIED IN THE DICTIONARY PASSED TO THE AGG() METHOD INCLUDE:
        total_filings=('form_type', 'count'),
        latest_filing=('filing_date', 'max'),
        earliest_filing=('filing_date', 'min')
    ).reset_index()

    print(summary.to_string(index=False))#THIS LINE PRINTS THE SUMMARY DATAFRAME IN A STRING FORMAT WITHOUT INCLUDING THE INDEX. THE to_string() METHOD CONVERTS THE DataFrame INTO A STRING REPRESENTATION, AND THE index=False PARAMETER ENSURES THAT THE INDEX COLUMN IS NOT DISPLAYED IN THE OUTPUT.
    
    print(f"\nDate range: {df['filing_date'].min()} to {df['filing_date'].max()}")#THIS MEANS THAT WE ARE PRINTING THE DATE RANGE OF THE FILINGS IN THE DATAFRAME (df) BY CALCULATING THE MINIMUM AND MAXIMUM VALUES IN THE 'filing_date' COLUMN. THE min() FUNCTION RETURNS THE EARLIEST DATE, WHILE THE max() FUNCTION RETURNS THE LATEST DATE. THE RESULTING DATE RANGE IS THEN PRINTED TO THE CONSOLE.
    print(f"Total unique companies: {df['ticker'].nunique()}")


# ============================================
# RUN EVERYTHING
# ============================================
if __name__ == "__main__":
    df = collect_all_insider_filings()
    analyze_insider_activity(df)

    print("\nDone. Open data/insider_filings.csv to see raw data.")
