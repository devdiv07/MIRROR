"""
Conviction scorer.

Measures how much of the insider's personal position this trade represents.

Key insight: an insider selling 50% of their holdings is a louder statement
than an insider selling $5M of Apple. The dollar amount is meaningless
without context of the insider's wealth.

Symmetric design (1.0x both directions):
- The buy/sell asymmetry emerges from routine_penalty + tenb_penalty
  hitting the sell side harder in practice. No magic number needed.

Null handling:
- is_routine_insider is None (enrichment hasn't run) -> multiplier 0.6
  Prevents un-enriched data from producing false high-confidence signals.
"""

from __future__ import annotations
from .registry import register_scorer


@register_scorer('conviction_score', default_weight=0.30)
def score_conviction(row: dict) -> float:
    """
    Score a single transaction by insider conviction.

    Returns:
        float in range [-1.0, +1.0]
        Positive = bullish, negative = bearish, magnitude = strength
    """
    pct = row.get('pct_holdings_transacted')

    # If conviction wasn't computed (e.g., missing sharesOwnedAfter),
    # return 0.0 — a null feature contributes nothing.
    if pct is None:
        return 0.0

    # Clamp to [0, 1] — pct > 1 means insider went from 0 to positive,
    # or some other edge case. Cap at 1.0 to prevent runaway signals.
    pct = max(0.0, min(1.0, float(pct)))

    # Routine multiplier (None = unknown -> conservative 0.6)
    is_routine = row.get('is_routine_insider', None)
    if is_routine is True:
        multiplier = 0.3
    elif is_routine is False:
        multiplier = 1.0
    else:  # None — enrichment hasn't run
        multiplier = 0.6

    # Symmetric: direction comes from transaction_type, magnitude from pct
    if row.get('transaction_type') == 'BUY':
        return +pct * multiplier
    elif row.get('transaction_type') == 'SELL':
        return -pct * multiplier
    else:
        return 0.0  # unknown type — neutral
