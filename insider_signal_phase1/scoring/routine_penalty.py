"""
Routine insider penalty.

Cohen, Malloy & Pomorski (2012) — the key finding:
  Insiders who transact in the same calendar months year after year
  ("routine" insiders) have ZERO predictive power.
  Insiders who deviate from their own pattern ("opportunistic") have
  strong predictive power (+9.2% alpha over the next year).

Classification rule:
  An insider is "routine" if they have transacted in the SAME calendar
  month (±1 month buffer) in at least 3 of the past 4 years.

  This requires historical data. The column 'is_routine_insider' is set
  by enrich_routine.py (future Phase 3). Until then, this scorer checks
  the column and returns 0.0 if the data is missing.

Penalty: this is a NEGATIVE weight scorer.
  Routine insider → return +1.0 (the aggregator applies negative weight -0.20)
  Opportunistic   → return 0.0  (no penalty)
  Unknown (None)  → return 0.3  (conservative partial penalty — we don't know yet)
"""

from __future__ import annotations
from .registry import register_scorer


@register_scorer('routine_penalty', default_weight=-0.20)
def score_routine_penalty(row: dict) -> float:
    """
    Penalty for routine/scheduled insider activity (zero predictive value).

    The aggregator applies a negative weight (-0.20), so:
        return 1.0  → -0.20 contribution  (full penalty: routine)
        return 0.3  → -0.06 contribution  (partial: unknown)
        return 0.0  →  0.00 contribution  (no penalty: opportunistic)

    Returns:
        float in [0.0, 1.0]
    """
    is_routine = row.get('is_routine_insider', None)

    if is_routine is True:
        return 1.0   # routine — full penalty
    elif is_routine is False:
        return 0.0   # opportunistic — no penalty
    else:
        return 0.3   # unknown — conservative partial penalty
