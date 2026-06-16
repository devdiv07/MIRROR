"""
Cluster scorer.

When multiple insiders buy the same stock within a short window, the signal
compounds. The probability that N insiders independently decided to buy for
personal reasons while collectively aware of negative information approaches zero.

Lakonishok & Lee (2001) found cluster buying has ~2x predictive accuracy
of single-insider buying.

This scorer operates at the transaction level. It looks at ALL transactions
in the input DataFrame to determine if the current transaction is part of a
cluster. The score reflects the cluster size at the time of each transaction.

    cluster_size = # distinct insiders transacting in same direction
                   for the same ticker within CLUSTER_WINDOW_DAYS

Signal mapping:
    5+ insiders  →  1.0
    4 insiders   →  0.85
    3 insiders   →  0.65
    2 insiders   →  0.40
    1 insider    →  0.10   (baseline — no cluster bonus)

Direction still comes from conviction; this scorer returns [0, 1].

NOTE: This scorer requires the full transactions DataFrame to be passed
alongside the row. The aggregator calls score_cluster(row) but the
function needs the full df context. We solve this with a module-level
state pattern: call set_transactions_context(df) once before scoring.
"""

from __future__ import annotations
import pandas as pd
from .registry import register_scorer

CLUSTER_WINDOW_DAYS = 10  # transactions within this window count as a cluster

_transactions_df: pd.DataFrame | None = None


def set_transactions_context(df: pd.DataFrame) -> None:
    """
    Call this once before running aggregate() on a DataFrame.
    The cluster scorer uses this context to count co-transactors.

    Args:
        df: Full enriched transactions DataFrame
    """
    global _transactions_df
    _transactions_df = df.copy()
    if 'date' in _transactions_df.columns:
        _transactions_df['date'] = pd.to_datetime(_transactions_df['date'], errors='coerce')


@register_scorer('cluster_score', default_weight=0.15)
def score_cluster(row: dict) -> float:
    """
    Score how many distinct insiders transacted in the same direction
    for this ticker within CLUSTER_WINDOW_DAYS of this transaction.

    Returns:
        float in [0.0, 1.0] — higher = larger insider cluster
    """
    if _transactions_df is None or _transactions_df.empty:
        return 0.10  # no context = assume solo transaction, baseline

    ticker = row.get('ticker')
    tx_type = row.get('transaction_type')
    tx_date = row.get('date')
    this_insider = row.get('insider_name', '')

    if not ticker or not tx_type or not tx_date:
        return 0.10

    try:
        tx_date = pd.Timestamp(tx_date)
    except Exception:
        return 0.10

    window_start = tx_date - pd.Timedelta(days=CLUSTER_WINDOW_DAYS)
    window_end   = tx_date + pd.Timedelta(days=CLUSTER_WINDOW_DAYS)

    mask = (
        (_transactions_df['ticker'] == ticker) &
        (_transactions_df['transaction_type'] == tx_type) &
        (_transactions_df['date'] >= window_start) &
        (_transactions_df['date'] <= window_end)
    )

    # Count DISTINCT insiders (not transactions — one insider filing multiple
    # sells on consecutive days shouldn't multiply the cluster count)
    cluster_insiders = _transactions_df.loc[mask, 'insider_name'].nunique()

    # Map cluster size to base score
    if cluster_insiders >= 5:
        base_score = 1.00
    elif cluster_insiders == 4:
        base_score = 0.85
    elif cluster_insiders == 3:
        base_score = 0.65
    elif cluster_insiders == 2:
        base_score = 0.40
    else:
        base_score = 0.10  # solo — no cluster bonus

    # Same-day SELL coordination discount.
    # 3+ distinct insiders all selling on the exact same date is a strong
    # signal of a scheduled event (RSU cliff-vesting, blackout-window release,
    # 10b5-1 plan execution) rather than organic conviction.
    # BUY clusters are NOT discounted — coordinated same-day buying is unusual
    # enough to retain its full signal (Lakonishok & Lee 2001).
    if tx_type == 'SELL':
        same_day_mask = (
            (_transactions_df['ticker'] == ticker) &
            (_transactions_df['transaction_type'] == 'SELL') &
            (_transactions_df['date'] == tx_date)
        )
        same_day_count = _transactions_df.loc[same_day_mask, 'insider_name'].nunique()
        if same_day_count >= 3:
            base_score = base_score * 0.5  # scheduled event discount

    return base_score
