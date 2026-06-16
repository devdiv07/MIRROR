"""
Tests for Fix 5: same-day SELL cluster discount.
Run from insider_signal_phase1/ directory.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from src.scoring.cluster import set_transactions_context, score_cluster


def _make_df(rows):
    """Helper: create a DataFrame with the columns the cluster scorer needs."""
    return pd.DataFrame(rows, columns=['ticker', 'transaction_type', 'date', 'insider_name'])


# ── Same-day SELL discount tests ──────────────────────────────────────────────

def test_same_day_sell_cluster_discounted():
    """5 insiders all selling on the same date → score < 1.00 (discounted)."""
    same_day_df = _make_df([
        {'ticker': 'JPM', 'transaction_type': 'SELL', 'date': '2026-01-10', 'insider_name': f'Insider{i}'}
        for i in range(5)
    ])
    set_transactions_context(same_day_df)
    row = {'ticker': 'JPM', 'transaction_type': 'SELL', 'date': '2026-01-10', 'insider_name': 'Insider0'}
    score = score_cluster(row)
    assert score < 1.00, f"Same-day sell cluster of 5 should be < 1.00, got {score}"
    assert abs(score - 0.50) < 1e-9, f"Expected 1.00 * 0.5 = 0.50, got {score}"
    print(f"  PASS: same-day SELL cluster of 5 discounted → score={score}")


def test_same_day_sell_cluster_of_2_not_discounted():
    """Only 2 insiders on same day → threshold not reached, no discount."""
    same_day_df = _make_df([
        {'ticker': 'JPM', 'transaction_type': 'SELL', 'date': '2026-01-10', 'insider_name': 'InsiderA'},
        {'ticker': 'JPM', 'transaction_type': 'SELL', 'date': '2026-01-10', 'insider_name': 'InsiderB'},
    ])
    set_transactions_context(same_day_df)
    row = {'ticker': 'JPM', 'transaction_type': 'SELL', 'date': '2026-01-10', 'insider_name': 'InsiderA'}
    score = score_cluster(row)
    assert score == 0.40, f"2-insider cluster should score 0.40, got {score}"
    print(f"  PASS: 2-insider same-day SELL not discounted → score={score}")


def test_multi_day_sell_cluster_not_discounted():
    """5 insiders selling across 5 different dates → full score, no discount."""
    multi_day_df = _make_df([
        {'ticker': 'JPM', 'transaction_type': 'SELL', 'date': f'2026-01-{10+i:02d}', 'insider_name': f'Insider{i}'}
        for i in range(5)
    ])
    set_transactions_context(multi_day_df)
    # Evaluate from Insider0's perspective (date 2026-01-10)
    row = {'ticker': 'JPM', 'transaction_type': 'SELL', 'date': '2026-01-10', 'insider_name': 'Insider0'}
    score = score_cluster(row)
    assert score == 1.00, f"Multi-day sell cluster of 5 should score 1.00, got {score}"
    print(f"  PASS: multi-day SELL cluster of 5 not discounted → score={score}")


def test_same_day_buy_cluster_not_discounted():
    """5 insiders buying on the same date → BUY clusters are NOT discounted."""
    same_day_df = _make_df([
        {'ticker': 'AAPL', 'transaction_type': 'BUY', 'date': '2026-01-10', 'insider_name': f'Insider{i}'}
        for i in range(5)
    ])
    set_transactions_context(same_day_df)
    row = {'ticker': 'AAPL', 'transaction_type': 'BUY', 'date': '2026-01-10', 'insider_name': 'Insider0'}
    score = score_cluster(row)
    assert score == 1.00, f"Same-day BUY cluster should NOT be discounted, got {score}"
    print(f"  PASS: same-day BUY cluster of 5 not discounted → score={score}")


def test_sell_cluster_3_insiders_same_day_discounted():
    """Exactly 3 insiders on the same day → threshold triggers 0.5x discount."""
    same_day_df = _make_df([
        {'ticker': 'TSLA', 'transaction_type': 'SELL', 'date': '2026-03-01', 'insider_name': f'Insider{i}'}
        for i in range(3)
    ])
    set_transactions_context(same_day_df)
    row = {'ticker': 'TSLA', 'transaction_type': 'SELL', 'date': '2026-03-01', 'insider_name': 'Insider0'}
    score = score_cluster(row)
    # 3 insiders → base=0.65, same_day_count=3 → 0.65 * 0.5 = 0.325
    assert abs(score - 0.325) < 1e-9, f"Expected 0.325, got {score}"
    print(f"  PASS: 3-insider same-day SELL discounted → score={score}")


if __name__ == '__main__':
    print("=" * 60)
    print("FIX 5: CLUSTER SAME-DAY SELL DISCOUNT TESTS")
    print("=" * 60)
    tests = [
        test_same_day_sell_cluster_discounted,
        test_same_day_sell_cluster_of_2_not_discounted,
        test_multi_day_sell_cluster_not_discounted,
        test_same_day_buy_cluster_not_discounted,
        test_sell_cluster_3_insiders_same_day_discounted,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print()
    print(f"Results: {passed} passed, {failed} failed")
