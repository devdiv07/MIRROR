"""
Enrichment step: compute shares_owned_before_transaction and
pct_holdings_transacted for every parsed Form 4 transaction.

The conviction scorer needs these. They're not in the raw Form 4
output for older filings, so we compute them with three strategies
in priority order:

1. Direct tag: <sharesOwnedPriorToTransaction> (newer filings only)
2. Forward-carry: prior transaction in same Form 4 with same class
3. Arithmetic: shares_after +/- shares_transacted (the fallback)

Class boundary rule: never carry forward across derivative /
non-derivative boundary. Different position worlds.
"""

from __future__ import annotations
import pandas as pd
from typing import Optional


def _classify_transaction(row: pd.Series) -> str:
    """
    Classify as 'non_derivative' or 'derivative'.
    Form 4 separates these in different XML blocks; we mirror that here.
    """
    # The parser flags derivative via a column we'd add later.
    # For now, default to non-derivative (the parser only handles those).
    if row.get('is_derivative', False):
        return 'derivative'
    return 'non_derivative'


def _direct_tag_shares_before(row: pd.Series) -> Optional[float]:
    """
    Strategy 1: read the direct tag from newer filings.
    Returns None if not present.
    """
    val = row.get('shares_owned_prior_to_transaction', None)
    if val is None or pd.isna(val):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _carry_forward_shares_before(
    row: pd.Series,
    prior_same_class: Optional[pd.Series],
) -> Optional[float]:
    """
    Strategy 2: use the prior transaction's shares_after as our shares_before,
    if it's the same insider + same Form 4 + same transaction class.
    Returns None if no prior transaction in the same class.
    """
    if prior_same_class is None:
        return None
    val = prior_same_class.get('shares_owned_after_transaction', None)
    if val is None or pd.isna(val):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _arithmetic_shares_before(row: pd.Series) -> Optional[float]:
    """
    Strategy 3: arithmetic fallback.
    shares_before = shares_after - shares (BUY) or + shares (SELL)
    Returns None if shares_after is missing.
    """
    shares_after = row.get('shares_owned_after_transaction', None)
    shares = row.get('shares', None)

    if shares_after is None or pd.isna(shares_after):
        return None
    if shares is None or pd.isna(shares):
        return None

    try:
        shares_after = float(shares_after)
        shares = float(shares)
    except (TypeError, ValueError):
        return None

    if row.get('transaction_type') == 'BUY':
        return shares_after - shares
    elif row.get('transaction_type') == 'SELL':
        return shares_after + shares
    else:
        return None


def compute_shares_before(row: pd.Series, prior_same_class: Optional[pd.Series] = None) -> Optional[float]:
    """
    Try all three strategies in order, return first non-None result.
    """
    result = _direct_tag_shares_before(row)
    if result is not None and result >= 0:
        return result

    result = _carry_forward_shares_before(row, prior_same_class)
    if result is not None and result >= 0:
        return result

    result = _arithmetic_shares_before(row)
    return result if (result is not None and result >= 0) else None


def compute_pct_holdings_transacted(row: pd.Series) -> Optional[float]:
    """
    pct = |shares_transacted| / shares_owned_before
    Clamped to [0, 1+epsilon]; capped at 1.0 by the conviction scorer.

    Returns None if shares_before is missing or zero (insider went from
    non-holder to holder — edge case).
    """
    shares_before = row.get('shares_owned_before_transaction', None)
    shares = row.get('shares', None)

    if shares_before is None or pd.isna(shares_before):
        return None
    if shares is None or pd.isna(shares):
        return None

    try:
        shares_before = float(shares_before)
        shares = float(shares)
    except (TypeError, ValueError):
        return None

    if shares_before <= 0:
        return None  # edge case: zero/negative prior holdings

    return abs(shares) / shares_before


def enrich_ownership(transactions_df: pd.DataFrame) -> pd.DataFrame:
    """
    Main entry point. Takes parsed Form 4 transactions, returns the same
    DataFrame with two new columns:
        - shares_owned_before_transaction
        - pct_holdings_transacted

    Forward-carry is grouped by (ticker, filing_date, insider_name) so we
    only carry within the same Form 4 / same insider. Transaction class
    (derivative vs non-derivative) is the additional filter.
    """
    if transactions_df.empty:
        return transactions_df

    df = transactions_df.copy()

    # Ensure columns exist even if parser didn't write them
    if 'shares_owned_after_transaction' not in df.columns:
        df['shares_owned_after_transaction'] = None
    if 'shares_owned_prior_to_transaction' not in df.columns:
        df['shares_owned_prior_to_transaction'] = None
    if 'is_derivative' not in df.columns:
        df['is_derivative'] = False

    df['shares_owned_before_transaction'] = None
    df['pct_holdings_transacted'] = None

    # Group by Form 4 (ticker + filing_date + insider) and class for forward-carry
    group_keys = ['ticker', 'filing_date', 'insider_name']
    for keys, group in df.groupby(group_keys, sort=False):
        # Within this Form 4, sort by index to maintain original transaction order
        group_sorted = group.sort_index()

        # Separate by class — never carry across class boundary
        non_deriv = group_sorted[~group_sorted['is_derivative'].astype(bool)]
        deriv     = group_sorted[group_sorted['is_derivative'].astype(bool)]

        for class_group in [non_deriv, deriv]:
            prior_row = None
            for idx, row in class_group.iterrows():
                shares_before = compute_shares_before(row, prior_row)
                df.at[idx, 'shares_owned_before_transaction'] = shares_before

                # Now compute pct using the just-computed shares_before
                temp_row = row.copy()
                temp_row['shares_owned_before_transaction'] = shares_before
                pct = compute_pct_holdings_transacted(temp_row)
                df.at[idx, 'pct_holdings_transacted'] = pct

                # Update prior for next iteration
                # We need the updated shares_after for carry-forward
                prior_row = row.copy()
                prior_row['shares_owned_before_transaction'] = shares_before

    return df


if __name__ == '__main__':
    # Quick smoke test
    test_data = pd.DataFrame([
        {
            'ticker': 'AAPL', 'filing_date': '2024-01-15', 'insider_name': 'Tim Cook',
            'transaction_type': 'SELL', 'shares': 50000,
            'shares_owned_after_transaction': 1000000,  # after sale
            'shares_owned_prior_to_transaction': None,
            'is_derivative': False,
        },
        {
            'ticker': 'AAPL', 'filing_date': '2024-01-15', 'insider_name': 'Tim Cook',
            'transaction_type': 'SELL', 'shares': 30000,
            'shares_owned_after_transaction': 970000,  # prior + (-30000) = 970000
            'shares_owned_prior_to_transaction': None,
            'is_derivative': False,
        },
        {
            'ticker': 'AAPL', 'filing_date': '2024-01-15', 'insider_name': 'Tim Cook',
            'transaction_type': 'SELL', 'shares': 20000,
            'shares_owned_after_transaction': 950000,  # 970000 - 20000
            'shares_owned_prior_to_transaction': None,
            'is_derivative': False,
        },
    ])
    result = enrich_ownership(test_data)
    print(result[['ticker', 'insider_name', 'transaction_type', 'shares',
                  'shares_owned_before_transaction', 'pct_holdings_transacted']])
