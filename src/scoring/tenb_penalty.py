"""
10b5-1 plan penalty.

A 10b5-1 plan is a pre-scheduled trading plan an insider sets up in advance.
Once established, trades execute automatically regardless of what the insider
knows at the time of execution. These trades carry zero information content
about current insider sentiment.

Detection strategy (two-layer, as discussed in architecture):
  Layer 1: <aff10b5One> XML tag — reliable, post-Dec 2022 filings only
  Layer 2: Footnote text regex — covers older filings, fragile but necessary

The 'is_10b51_plan' column is set by enrich_tenb51.py (runs after parsing).

Penalty: NEGATIVE weight scorer.
  10b5-1 trade → return 1.0 (aggregator applies -0.25 → strong signal reduction)
  Not 10b5-1   → return 0.0 (no penalty)
  Unknown       → return 0.1 (minimal conservative penalty)

The penalty is larger than routine_penalty (-0.25 vs -0.20) because 10b5-1
trades are scheduled by definition — more certain to be noise than a merely
"routine" insider who at least chose to transact at that time.
"""

from __future__ import annotations
from .registry import register_scorer


@register_scorer('tenb_penalty', default_weight=-0.25)
def score_tenb_penalty(row: dict) -> float:
    """
    Penalty for 10b5-1 pre-scheduled plan executions.

    The aggregator applies a negative weight (-0.25), so:
        return 1.0  → -0.25 contribution  (confirmed plan trade)
        return 0.1  → -0.025 contribution (unknown)
        return 0.0  →  0.00 contribution  (confirmed NOT a plan trade)

    Returns:
        float in [0.0, 1.0]
    """
    is_10b51 = row.get('is_10b51_plan', None)

    if is_10b51 is True:
        return 1.0   # confirmed plan — full penalty
    elif is_10b51 is False:
        return 0.0   # confirmed not a plan — no penalty
    else:
        return 0.1   # unknown — minimal conservative penalty
