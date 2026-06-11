"""
Liquidity scorer.

Normalizes the insider's trade size by the stock's average daily dollar volume (ADV).

A $2M buy in a stock that trades $8B/day (AAPL) is 0.025% of ADV — nobody notices.
The same $2M in a stock trading $20M/day is 10% of ADV — the market will see it.

The more of the daily float an insider absorbs, the more conviction the trade signals.

    adv_pct = |dollar_value| / avg_30d_dollar_volume

Signal mapping:
    > 10%  →  1.0   (insider is moving the market — extreme conviction)
    > 1%   →  0.7
    > 0.1% →  0.4
    > 0.01% → 0.2
    else   →  0.0   (invisible in the flow)

Direction comes from conviction scorer; this returns [0, 1].

Requires enrich_market_context.py to have run (adds 'avg_30d_dollar_volume').
"""

from __future__ import annotations
from .registry import register_scorer


@register_scorer('liquidity_score', default_weight=0.10)
def score_liquidity(row: dict) -> float:
    """
    Score trade size relative to average daily volume.

    Returns:
        float in [0.0, 1.0] — higher = larger relative to daily flow
    """
    adv = row.get('avg_30d_dollar_volume')
    dollar_value = row.get('dollar_value')

    if adv is None or dollar_value is None:
        return 0.0
    try:
        adv = float(adv)
        dollar_value = abs(float(dollar_value))
    except (TypeError, ValueError):
        return 0.0

    if adv <= 0 or dollar_value <= 0:
        return 0.0

    pct = dollar_value / adv

    if pct > 0.10:    # > 10% of ADV
        return 1.0
    elif pct > 0.01:  # > 1%
        return 0.7
    elif pct > 0.001: # > 0.1%
        return 0.4
    elif pct > 0.0001: # > 0.01%
        return 0.2
    else:
        return 0.0
