"""
Scoring package.

EXPLICIT IMPORTS — order matters here. Each scorer file must be imported
so its @register_scorer decorator runs. If you add a new scorer file,
add an import line below.

The assert_all_registered() call in aggregator.py will catch any that
slip through, but importing explicitly makes the dependency obvious.
"""

from .registry import SCORER_REGISTRY, register_scorer, assert_all_registered
from . import conviction
from . import role
from . import market_cap
from . import liquidity
from . import cluster
from . import routine_penalty
from . import tenb_penalty
from . import aggregator

# Future scorer imports go here, e.g.:
# from . import technical
