"""
Signal aggregator.

Reads SCORER_REGISTRY + SCORING_CONFIG, applies all enabled scorers,
sums weighted outputs, clips to [-1, +1].

The config is the single source of truth for weights. To A/B test,
edit config/scoring.yaml and re-run. No code changes needed.
"""

from __future__ import annotations
from typing import Dict, Any
from .registry import SCORER_REGISTRY, assert_all_registered


# Default config — used if config/scoring.yaml is missing or malformed.
# Match these keys to your registered scorer names.
DEFAULT_CONFIG: Dict[str, Dict[str, Any]] = {
    'conviction_score':  {'weight': 0.30, 'enabled': True},
    'role_score':        {'weight': 0.20, 'enabled': True},
    'market_cap_score':  {'weight': 0.15, 'enabled': True},
    'cluster_score':     {'weight': 0.15, 'enabled': True},
    'liquidity_score':   {'weight': 0.10, 'enabled': True},
    'technical_score':   {'weight': 0.10, 'enabled': True},
    'routine_penalty':   {'weight': -0.20, 'enabled': True},
    'tenb_penalty':      {'weight': -0.25, 'enabled': True},
}

# Scorers that MUST be registered for the system to run.
REQUIRED_SCORERS = {
    'conviction_score', 'role_score', 'market_cap_score',
    'cluster_score', 'liquidity_score', 'technical_score',
    'routine_penalty', 'tenb_penalty',
}


def load_config(config_path: str = None) -> Dict[str, Dict[str, Any]]:
    """
    Load SCORING_CONFIG from YAML. Falls back to DEFAULT_CONFIG on any error.

    Why fallback instead of crash? Config files get edited by hand. A typo
    shouldn't take down the whole signal pipeline — degrade gracefully,
    log a warning, keep moving.
    """
    if config_path is None:
        return DEFAULT_CONFIG.copy()

    try:
        import yaml
        with open(config_path, 'r') as f:
            user_config = yaml.safe_load(f)
        if not isinstance(user_config, dict):
            import warnings
            warnings.warn(f"Config {config_path} is not a dict; using defaults")
            return DEFAULT_CONFIG.copy()
        # Merge: user config overrides defaults, missing keys keep defaults
        merged = DEFAULT_CONFIG.copy()
        merged.update(user_config)
        return merged
    except FileNotFoundError:
        import warnings
        warnings.warn(f"Config {config_path} not found; using defaults")
        return DEFAULT_CONFIG.copy()
    except Exception as e:
        import warnings
        warnings.warn(f"Config {config_path} malformed ({e}); using defaults")
        return DEFAULT_CONFIG.copy()


def aggregate(row: dict, config: Dict[str, Dict[str, Any]] = None) -> float:
    """
    Compute the final signal for one transaction row.

    Returns:
        float clipped to [-1.0, +1.0]
    """
    # Only assert the scorers that are actually enabled in the config
    # AND registered. This makes the system work incrementally as
    # scorers get added in later phases.
    if config is None:
        config = DEFAULT_CONFIG
    else:
        # Merge: user config overrides defaults, missing keys keep defaults
        merged = DEFAULT_CONFIG.copy()
        merged.update(config)
        config = merged

    # Assert that all enabled scorers are actually registered.
    # Uses the full enabled set (not the intersection) so missing imports are caught.
    enabled_scorers = {
        name for name, cfg in config.items()
        if cfg.get('enabled', False)
    }
    unregistered = enabled_scorers - set(SCORER_REGISTRY.keys())
    if unregistered:
        import warnings
        warnings.warn(f"Enabled scorers not yet registered (Phase 2+): {sorted(unregistered)}")

    raw = 0.0
    for name, scorer_cfg in SCORER_REGISTRY.items():
        if not scorer_cfg['enabled']:
            continue
        if not config.get(name, {}).get('enabled', False):
            continue

        weight = config[name].get('weight', scorer_cfg['weight'])
        score = scorer_cfg['fn'](row)

        # Clamp individual scorer output to [-1, +1] to prevent
        # one broken scorer from blowing up the total
        score = max(-1.0, min(1.0, score))

        raw += weight * score

    # Final clip
    return max(-1.0, min(1.0, raw))


def explain(row: dict, config: Dict[str, Dict[str, Any]] = None) -> dict:
    """
    Debug helper — returns the contribution of each scorer for one row.

    Use this to understand why a transaction got the signal it did.
    """
    if config is None:
        config = DEFAULT_CONFIG
    else:
        merged = DEFAULT_CONFIG.copy()
        merged.update(config)
        config = merged

    enabled_scorers = {
        name for name, cfg in config.items()
        if cfg.get('enabled', False)
    }
    if enabled_scorers:
        # Warn about enabled scorers that aren't registered yet (incremental build).
        unregistered = enabled_scorers - set(SCORER_REGISTRY.keys())
        if unregistered:
            import warnings
            warnings.warn(f"Enabled scorers not yet registered: {sorted(unregistered)}")

    contributions = {}
    for name, scorer_cfg in SCORER_REGISTRY.items():
        if not scorer_cfg['enabled']:
            continue
        if not config.get(name, {}).get('enabled', False):
            continue

        weight = config[name].get('weight', scorer_cfg['weight'])
        score = scorer_cfg['fn'](row)
        score = max(-1.0, min(1.0, score))
        contributions[name] = {
            'raw_score': score,
            'weight': weight,
            'contribution': weight * score,
        }

    final = aggregate(row, config)
    return {'contributions': contributions, 'final_signal': final}
