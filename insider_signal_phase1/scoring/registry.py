"""
Scorer registry.

Each scorer registers itself via the @register_scorer decorator.
The aggregator reads SCORER_REGISTRY + SCORING_CONFIG to compute final signals.

Why this pattern:
- Adding a new scorer = create a new file with the decorator, import in __init__.py
- Weights live in config (YAML/JSON), not in code
- assert_all_registered() catches missing-import bugs at startup
"""

from __future__ import annotations
from typing import Callable, Dict, Any

# name -> {'fn': callable, 'weight': float, 'enabled': bool}
SCORER_REGISTRY: Dict[str, Dict[str, Any]] = {}


def register_scorer(name: str, default_weight: float = 0.0) -> Callable:
    """
    Decorator that registers a scoring function in SCORER_REGISTRY.

    Args:
        name: Unique scorer name (matches key in SCORING_CONFIG)
        default_weight: Initial weight; can be overridden by config file

    Usage:
        @register_scorer('conviction_score', default_weight=0.30)
        def score_conviction(row):
            ...
    """
    def decorator(fn: Callable) -> Callable:
        if name in SCORER_REGISTRY:
            raise ValueError(
                f"Scorer '{name}' already registered by "
                f"{SCORER_REGISTRY[name]['fn'].__module__}. "
                f"Cannot also register {fn.__module__}."
            )
        SCORER_REGISTRY[name] = {
            'fn': fn,
            'weight': default_weight,
            'enabled': default_weight > 0,
        }
        return fn
    return decorator


def assert_all_registered(expected: set) -> None:
    """
    Verify all expected scorers are in the registry.

    Call this at aggregator startup to catch the case where a scorer
    file was added but not imported in scoring/__init__.py.

    Args:
        expected: Set of scorer names that MUST be present
    """
    actual = set(SCORER_REGISTRY.keys())
    missing = expected - actual
    if missing:
        raise RuntimeError(
            f"Scorers not registered (missing import in scoring/__init__.py?): "
            f"{sorted(missing)}"
        )
    extras = actual - expected
    if extras:
        # Not a fatal error — extra scorers are fine, just not weighted
        import warnings
        warnings.warn(f"Scorers registered but not in expected set: {sorted(extras)}")
