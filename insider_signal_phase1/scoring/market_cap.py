"""
Market cap scorer.

Normalizes the insider's dollar trade size by the company's market cap.

Problem with raw dollars: a $5M sale from a JPM executive ($700B company)
is 0.0007% of the company — statistically invisible. The same $5M from
a $300M mid-cap CEO is 1.7% — they're exiting.

The normalized metric:
    trade_pct_of_mktcap = |dollar_value| / market_cap

Signal mapping:
    > 0.5%  →  1.0   (huge relative to company)
    > 0.1%  →  0.7
    > 0.01% →  0.4
    > 0.001% → 0.2
    else    →  0.0   (noise)

Direction is handled by conviction; this scorer returns [0, 1].

Requires enrich_market_context.py to have run (adds 'market_cap' column).
"""

from __future__ import annotations
from .registry import register_scorer


@register_scorer('market_cap_score', default_weight=0.15)
def score_market_cap(row: dict) -> float:
    """
    Score trade size relative to market cap.

    Returns:
        float in [0.0, 1.0] — higher = larger relative to company size
    """
    market_cap = row.get('market_cap')
    dollar_value = row.get('dollar_value')

    if market_cap is None or dollar_value is None:
        return 0.0
    try:
        market_cap = float(market_cap)
        dollar_value = abs(float(dollar_value))
    except (TypeError, ValueError):
        return 0.0

    if market_cap <= 0 or dollar_value <= 0:
        return 0.0

    pct = dollar_value / market_cap

    if pct > 0.005:    # > 0.5%
        return 1.0
    elif pct > 0.001:  # > 0.1%
        return 0.7
    elif pct > 0.0001: # > 0.01%
        return 0.4
    elif pct > 0.00001: # > 0.001%
        return 0.2
    else:
        return 0.0
