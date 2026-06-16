"""
Market context enrichment.

Adds two columns to the transactions DataFrame that scorers need:
  - market_cap          : company market cap in USD at time of scoring
  - avg_30d_dollar_volume: average daily dollar volume over last 30 trading days

Both fetched from yfinance. Cached per ticker per run to avoid
redundant API calls (10 tickers = 10 fetches max, not one per transaction).

Usage:
    from enrich_market_context import enrich_market_context
    enriched_df = enrich_market_context(transactions_df)
"""

from __future__ import annotations
import pandas as pd
import yfinance as yf
from datetime import datetime


def _fetch_market_context(ticker: str) -> dict:
    """
    Fetch market cap and 30d ADV for one ticker via yfinance.
    Returns dict with 'market_cap' and 'avg_30d_dollar_volume'.
    Both default to None on failure — scorers handle None gracefully.
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        # Market cap — yfinance key varies by data availability
        market_cap = info.get('marketCap') or info.get('market_cap')

        # 30d ADV: compute from recent price * volume history
        hist = stock.history(period='30d')
        if hist.empty:
            avg_30d_dollar_volume = None
        else:
            # Dollar volume per day = close * volume
            dollar_vol = hist['Close'] * hist['Volume']
            avg_30d_dollar_volume = float(dollar_vol.mean())

        return {
            'market_cap':            float(market_cap) if market_cap else None,
            'avg_30d_dollar_volume': avg_30d_dollar_volume,
        }

    except Exception as e:
        print(f"  ⚠ enrich_market_context: failed to fetch {ticker}: {e}")
        return {'market_cap': None, 'avg_30d_dollar_volume': None}


def enrich_market_context(transactions_df: pd.DataFrame) -> pd.DataFrame:
    """
    Add 'market_cap' and 'avg_30d_dollar_volume' columns to a transactions
    DataFrame. Values are fetched once per unique ticker and broadcast
    across all rows for that ticker.

    Args:
        transactions_df: Output of insider_parser_v2.parse_all_filings()

    Returns:
        Same DataFrame with two additional columns.
    """
    if transactions_df.empty:
        return transactions_df

    df = transactions_df.copy()

    # Initialise columns so they exist even if all fetches fail
    df['market_cap']            = None
    df['avg_30d_dollar_volume'] = None

    unique_tickers = df['ticker'].unique()
    print(f"\n=== ENRICHING MARKET CONTEXT ({len(unique_tickers)} tickers) ===\n")

    # Cache: one API call per ticker, not per row
    context_cache: dict[str, dict] = {}

    for ticker in unique_tickers:
        print(f"  Fetching market context for {ticker}...", end='', flush=True)
        ctx = _fetch_market_context(ticker)
        context_cache[ticker] = ctx

        mktcap = ctx['market_cap']
        adv    = ctx['avg_30d_dollar_volume']

        mktcap_str = f"${mktcap/1e9:.1f}B" if mktcap else "N/A"
        adv_str    = f"${adv/1e6:.1f}M/day" if adv else "N/A"
        print(f"  mkt_cap={mktcap_str}, ADV={adv_str}")

        # Broadcast to all rows for this ticker
        mask = df['ticker'] == ticker
        df.loc[mask, 'market_cap']            = ctx['market_cap']
        df.loc[mask, 'avg_30d_dollar_volume'] = ctx['avg_30d_dollar_volume']

    filled = df['market_cap'].notna().sum()
    print(f"\nMarket context filled: {filled}/{len(df)} rows")
    return df
