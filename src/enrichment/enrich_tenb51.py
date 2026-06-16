"""
10b5-1 plan enrichment.

Detects whether each transaction was executed under a pre-scheduled 10b5-1
trading plan. Plan trades carry zero information content and receive a
penalty in the scoring layer.

Two-layer detection:
  Layer 1: <aff10b5One> XML checkbox — available in post-Dec 2022 Form 4s.
            The parsed value is already in the DataFrame as 'is_10b51_raw'
            if insider_parser_v2 extracted it. (Add this field if needed.)
  Layer 2: Footnote regex — covers pre-2023 filings where the XML tag
            didn't exist. Scans 'footnotes' column (free text from filing).

Column added:
  is_10b51_plan : bool | None
    True  = confirmed 10b5-1 plan trade
    False = confirmed NOT a plan trade
    None  = insufficient data to determine

Usage:
    from enrich_tenb51 import enrich_tenb51
    enriched_df = enrich_tenb51(transactions_df)
"""

from __future__ import annotations
import re
import pandas as pd

# Regex patterns that indicate a 10b5-1 plan in footnote text.
# Listed from strongest to weakest signal.
_PLAN_PATTERNS: list[re.Pattern] = [
    re.compile(r'10b5-1\s*plan',              re.IGNORECASE),
    re.compile(r'rule\s*10b5-1',              re.IGNORECASE),
    re.compile(r'trading\s*plan',             re.IGNORECASE),
    re.compile(r'pre-?arranged\s*plan',       re.IGNORECASE),
    re.compile(r'adopted\s*a\s*plan',         re.IGNORECASE),
    re.compile(r'pursuant\s*to\s*a\s*plan',   re.IGNORECASE),
    re.compile(r'scheduled\s*sale',           re.IGNORECASE),
    re.compile(r'automatic\s*sale',           re.IGNORECASE),
]

# Negation patterns — if found alongside a plan pattern, NOT a plan
_NEGATION_PATTERNS: list[re.Pattern] = [
    re.compile(r'not\s+pursuant\s+to',        re.IGNORECASE),
    re.compile(r'terminated\s*the\s*plan',    re.IGNORECASE),
    re.compile(r'outside\s*(of\s*)?a\s*plan', re.IGNORECASE),
]


def _detect_from_xml_flag(row: pd.Series) -> bool | None:
    """
    Layer 1: check the <aff10b5One> XML field (post-2022 filings).
    The parser stores this as 'is_10b51_raw' (1/0/None).
    Returns True/False/None.
    """
    raw = row.get('is_10b51_raw', None)
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    try:
        return bool(int(raw))
    except (TypeError, ValueError):
        return None


def _detect_from_footnotes(row: pd.Series) -> bool | None:
    """
    Layer 2: scan footnote text for plan language.
    Returns True if plan detected, False if no match, None if no footnotes.
    """
    footnotes = row.get('footnotes', None)
    if not footnotes or (isinstance(footnotes, float) and pd.isna(footnotes)):
        return None

    text = str(footnotes)

    # Check negation first — if present alongside a plan reference, it's NOT a plan
    has_plan   = any(p.search(text) for p in _PLAN_PATTERNS)
    has_negate = any(p.search(text) for p in _NEGATION_PATTERNS)

    if has_plan and not has_negate:
        return True
    if has_plan and has_negate:
        return False  # negated — explicitly NOT a plan trade
    return False      # no plan language found


def enrich_tenb51(transactions_df: pd.DataFrame) -> pd.DataFrame:
    """
    Add 'is_10b51_plan' column to transactions DataFrame.

    Priority: XML flag (Layer 1) → footnote regex (Layer 2) → None

    Args:
        transactions_df: Parsed Form 4 transactions

    Returns:
        Same DataFrame with 'is_10b51_plan' column added.
    """
    if transactions_df.empty:
        return transactions_df

    df = transactions_df.copy()
    results = []

    for _, row in df.iterrows():
        # Layer 1: XML flag (most reliable)
        flag = _detect_from_xml_flag(row)
        if flag is not None:
            results.append(flag)
            continue

        # Layer 2: footnote regex
        flag = _detect_from_footnotes(row)
        results.append(flag)  # may be True, False, or None

    df['is_10b51_plan'] = results

    confirmed_plan = sum(1 for r in results if r is True)
    confirmed_not  = sum(1 for r in results if r is False)
    unknown        = sum(1 for r in results if r is None)

    print(f"\n=== 10b5-1 ENRICHMENT ===")
    print(f"  Confirmed plan trades : {confirmed_plan}")
    print(f"  Confirmed non-plan    : {confirmed_not}")
    print(f"  Unknown (no data)     : {unknown}")

    return df
