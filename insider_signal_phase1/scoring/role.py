"""
Role scorer.

An insider's information advantage is directly tied to their position.
A CEO knows everything. A director knows board-level decisions only.
A 10% shareholder who is NOT an officer may know nothing internal at all.

Scoring uses the title string + boolean role flags (is_officer, is_director, etc.)
parsed from Form 4 <reportingOwnerRelationship>.

Returns a multiplier in [0.0, 1.0]. The aggregator applies the configured weight.
Higher = more informative insider.

Sources:
  Seyhun (1998) "Investment Intelligence from Insider Trading"
  Lakonishok & Lee (2001) "Are Insider Trades Informative?"
"""

from __future__ import annotations
from .registry import register_scorer

# Title substring → role weight mapping.
# Matched in priority order (first match wins).
# Lower-case for case-insensitive matching.
_TITLE_WEIGHTS: list[tuple[str, float]] = [
    ('chief executive',    1.00),
    ('ceo',                1.00),
    ('president',          0.90),
    ('chief financial',    0.90),
    ('cfo',                0.90),
    ('chief operating',    0.85),
    ('coo',                0.85),
    ('chief technology',   0.80),
    ('cto',                0.80),
    ('chief revenue',      0.80),
    ('chief product',      0.80),
    ('chief marketing',    0.75),
    ('cmo',                0.75),
    ('chief legal',        0.75),
    ('general counsel',    0.75),
    ('executive vice',     0.75),
    ('evp',                0.75),
    ('senior vice',        0.70),
    ('svp',                0.70),
    ('vice president',     0.65),
    ('vp',                 0.65),
    ('director',           0.55),
    ('chairman',           0.70),
    ('founder',            0.95),   # founders have full conviction stake
    ('co-founder',         0.95),
]


def _role_weight_from_title(title: str) -> float | None:
    """Match the insider's title string against the priority list. Returns None on no match."""
    lower = title.lower()
    for substring, weight in _TITLE_WEIGHTS:
        if substring in lower:
            return weight
    return None


def _role_weight_from_flags(row: dict) -> float:
    """
    Fallback when title is missing or unrecognised.
    Uses the boolean flags from <reportingOwnerRelationship>.
    """
    if row.get('is_officer', False):
        return 0.70  # officer but unknown rank
    if row.get('is_director', False):
        return 0.55  # board-level only
    if row.get('is_ten_pct_owner', False):
        return 0.40  # passive institutional holder or activist — unknown intent
    return 0.30      # other / unknown


@register_scorer('role_score', default_weight=0.20)
def score_role(row: dict) -> float:
    """
    Score the informativeness of the insider based on their role.

    Returns:
        float in [0.0, 1.0]  — higher = more informative insider
        Always positive: role is a quality multiplier, not a direction signal.
        The conviction scorer provides direction.
    """
    title = row.get('title', '') or ''
    weight = _role_weight_from_title(title)
    if weight is None:
        weight = _role_weight_from_flags(row)
    return weight
