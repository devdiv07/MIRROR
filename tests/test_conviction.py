"""
Tests for the conviction scorer and enrichment.

Run from /workspace/ with: python tests/test_conviction.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scoring.conviction import score_conviction
from src.scoring.aggregator import aggregate
from src.enrichment.enrich_ownership import enrich_ownership
import pandas as pd


def test_buy_high_conviction_non_routine():
    """A founder buying 50% of their position, non-routine: loud bullish."""
    row = {
        'transaction_type': 'BUY',
        'pct_holdings_transacted': 0.5,
        'is_routine_insider': False,
    }
    result = score_conviction(row)
    assert result == 0.5, f"Expected +0.5, got {result}"
    print(f"  PASS: buy 50% non-routine -> {result}")


def test_sell_high_conviction_non_routine():
    """An opportunistic sell of 80% of position: loud bearish."""
    row = {
        'transaction_type': 'SELL',
        'pct_holdings_transacted': 0.8,
        'is_routine_insider': False,
    }
    result = score_conviction(row)
    assert result == -0.8, f"Expected -0.8, got {result}"
    print(f"  PASS: sell 80% non-routine -> {result}")


def test_routine_sell_muted():
    """Scheduled April tax sale of 30% of position: barely registers."""
    row = {
        'transaction_type': 'SELL',
        'pct_holdings_transacted': 0.3,
        'is_routine_insider': True,
    }
    result = score_conviction(row)
    assert abs(result - (-0.09)) < 1e-9, f"Expected -0.09, got {result}"
    print(f"  PASS: routine sell 30% -> {result}")


def test_routine_buy_rare_but_muted():
    """DCA plan buying 5% of position: muted signal."""
    row = {
        'transaction_type': 'BUY',
        'pct_holdings_transacted': 0.05,
        'is_routine_insider': True,
    }
    result = score_conviction(row)
    assert abs(result - 0.015) < 1e-9, f"Expected +0.015, got {result}"
    print(f"  PASS: routine buy 5% -> {result}")


def test_null_routine_uses_conservative_default():
    """Un-enriched row (is_routine=None) gets 0.6x multiplier, not 1.0x."""
    row = {
        'transaction_type': 'BUY',
        'pct_holdings_transacted': 0.5,
        'is_routine_insider': None,  # enrichment hasn't run
    }
    result = score_conviction(row)
    assert abs(result - 0.3) < 1e-9, f"Expected +0.3, got {result}"
    print(f"  PASS: null routine + 50% buy -> {result} (0.6x multiplier)")


def test_null_pct_returns_zero():
    """Missing pct = no signal contribution."""
    row = {
        'transaction_type': 'SELL',
        'pct_holdings_transacted': None,
        'is_routine_insider': False,
    }
    result = score_conviction(row)
    assert result == 0.0, f"Expected 0.0, got {result}"
    print(f"  PASS: null pct -> 0.0")


def test_nan_pct_returns_zero():
    """pandas NaN in pct (from missing ownership data) must return 0.0, not +-0.6."""
    row = {
        'transaction_type': 'SELL',
        'pct_holdings_transacted': float('nan'),
        'is_routine_insider': False,
    }
    result = score_conviction(row)
    assert result == 0.0, f"Expected 0.0, got {result}"
    print(f"  PASS: nan pct -> 0.0")


def test_pct_clamped_above_one():
    """Edge case: insider went from 0 to positive, pct > 1 should clamp."""
    row = {
        'transaction_type': 'BUY',
        'pct_holdings_transacted': 1.5,  # impossible but defensive
        'is_routine_insider': False,
    }
    result = score_conviction(row)
    assert result == 1.0, f"Expected +1.0 (clamped), got {result}"
    print(f"  PASS: pct > 1 clamps to 1.0 -> {result}")


def test_symmetry_no_buy_sell_bias_in_conviction():
    """Same pct, one BUY one SELL, both non-routine: magnitudes match."""
    buy = {'transaction_type': 'BUY', 'pct_holdings_transacted': 0.4, 'is_routine_insider': False}
    sell = {'transaction_type': 'SELL', 'pct_holdings_transacted': 0.4, 'is_routine_insider': False}
    buy_score = score_conviction(buy)
    sell_score = score_conviction(sell)
    assert buy_score == 0.4
    assert sell_score == -0.4
    assert abs(buy_score) == abs(sell_score)
    print(f"  PASS: symmetric -> buy={buy_score}, sell={sell_score}")


def test_enrich_ownership_arithmetic_fallback():
    """shares_after = 100k, SELL 50k -> shares_before = 150k, pct = 33.3%."""
    test_data = pd.DataFrame([{
        'ticker': 'TEST', 'filing_date': '2024-01-01', 'insider_name': 'CEO',
        'transaction_type': 'SELL', 'shares': 50000,
        'shares_owned_after_transaction': 100000,
        'shares_owned_prior_to_transaction': None,
        'is_derivative': False,
    }])
    result = enrich_ownership(test_data)
    pct = result['pct_holdings_transacted'].iloc[0]
    before = result['shares_owned_before_transaction'].iloc[0]
    assert before == 150000, f"Expected 150000, got {before}"
    assert abs(pct - (50000 / 150000)) < 1e-9, f"Expected ~0.333, got {pct}"
    print(f"  PASS: arithmetic fallback -> before={before}, pct={pct:.4f}")


def test_enrich_ownership_forward_carry():
    """Multi-transaction Form 4: second tx's before = first tx's after."""
    test_data = pd.DataFrame([
        {
            'ticker': 'TEST', 'filing_date': '2024-01-01', 'insider_name': 'CEO',
            'transaction_type': 'SELL', 'shares': 10000,
            'shares_owned_after_transaction': 90000,
            'shares_owned_prior_to_transaction': None,
            'is_derivative': False,
        },
        {
            'ticker': 'TEST', 'filing_date': '2024-01-01', 'insider_name': 'CEO',
            'transaction_type': 'SELL', 'shares': 20000,
            'shares_owned_after_transaction': 70000,
            'shares_owned_prior_to_transaction': None,
            'is_derivative': False,
        },
    ])
    result = enrich_ownership(test_data)
    first = result.iloc[0]
    second = result.iloc[1]
    assert first['shares_owned_before_transaction'] == 100000
    assert abs(first['pct_holdings_transacted'] - 0.1) < 1e-9
    assert second['shares_owned_before_transaction'] == 90000, f"Got {second['shares_owned_before_transaction']}"
    assert abs(second['pct_holdings_transacted'] - (20000/90000)) < 1e-9
    print(f"  PASS: forward-carry -> tx1 before={first['shares_owned_before_transaction']}, tx2 before={second['shares_owned_before_transaction']}")


def test_enrich_ownership_class_boundary_no_carry():
    """Derivative transaction should NOT inherit non-derivative's shares_after."""
    test_data = pd.DataFrame([
        {
            'ticker': 'TEST', 'filing_date': '2024-01-01', 'insider_name': 'CEO',
            'transaction_type': 'SELL', 'shares': 10000,
            'shares_owned_after_transaction': 90000,
            'shares_owned_prior_to_transaction': None,
            'is_derivative': False,
        },
        {
            'ticker': 'TEST', 'filing_date': '2024-01-01', 'insider_name': 'CEO',
            'transaction_type': 'SELL', 'shares': 5000,
            'shares_owned_after_transaction': 5000,
            'shares_owned_prior_to_transaction': None,
            'is_derivative': True,
        },
    ])
    result = enrich_ownership(test_data)
    non_deriv_after = 90000  # shares_after of the non-derivative row
    deriv = result[result['is_derivative'].astype(bool)].iloc[0]
    # If carry was NOT blocked: deriv before = 90000 (non-deriv's shares_after)
    # If carry IS blocked: deriv before = 10000 (arithmetic: 5000 after + 5000 sold)
    assert deriv['shares_owned_before_transaction'] != non_deriv_after, (
        f"Carry was NOT blocked — deriv inherited non-deriv's shares_after ({non_deriv_after})"
    )
    assert deriv['shares_owned_before_transaction'] == 10000, f"Got {deriv['shares_owned_before_transaction']}"
    print(f"  PASS: class boundary respected -> deriv before={deriv['shares_owned_before_transaction']} (not {non_deriv_after})")


def test_aggregator_uses_registry():
    """Smoke test: aggregator scores a row with minimal Phase 1 config."""
    from src.scoring.registry import assert_all_registered, SCORER_REGISTRY
    assert_all_registered({'conviction_score'})
    assert 'conviction_score' in SCORER_REGISTRY

    config = {
        'conviction_score': {'weight': 0.30, 'enabled': True},
        'role_score': {'weight': 0.20, 'enabled': False},
        'market_cap_score': {'weight': 0.15, 'enabled': False},
        'cluster_score': {'weight': 0.15, 'enabled': False},
        'liquidity_score': {'weight': 0.10, 'enabled': False},
        'technical_score': {'weight': 0.10, 'enabled': False},
        'routine_penalty': {'weight': -0.20, 'enabled': False},
        'tenb_penalty': {'weight': -0.25, 'enabled': False},
    }

    row = {
        'transaction_type': 'BUY',
        'pct_holdings_transacted': 0.5,
        'is_routine_insider': False,
    }
    result = aggregate(row, config=config)
    # conviction weight 0.30, score +0.5
    # raw = 0.30 * 0.5 = 0.15
    assert abs(result - 0.15) < 1e-9, f"Expected 0.15, got {result}"
    print(f"  PASS: aggregator end-to-end -> {result}")


def test_aggregator_clip_to_one():
    """Single high-conviction buy with max pct: should give 0.30."""
    config = {
        'conviction_score': {'weight': 0.30, 'enabled': True},
        'role_score': {'weight': 0.20, 'enabled': False},
        'market_cap_score': {'weight': 0.15, 'enabled': False},
        'cluster_score': {'weight': 0.15, 'enabled': False},
        'liquidity_score': {'weight': 0.10, 'enabled': False},
        'technical_score': {'weight': 0.10, 'enabled': False},
        'routine_penalty': {'weight': -0.20, 'enabled': False},
        'tenb_penalty': {'weight': -0.25, 'enabled': False},
    }

    row = {
        'transaction_type': 'BUY',
        'pct_holdings_transacted': 1.0,  # max conviction
        'is_routine_insider': False,
    }
    result = aggregate(row, config=config)
    # weight 0.30, score 1.0 -> raw = 0.30
    assert abs(result - 0.30) < 1e-9, f"Expected 0.30, got {result}"
    assert result <= 1.0
    print(f"  PASS: clip respected -> {result}")


def test_aggregator_clamps_individual_scorer_output():
    """A scorer returning >1.0 should be clamped, not allowed to dominate."""
    from src.scoring.registry import register_scorer, SCORER_REGISTRY

    @register_scorer('test_blowup_score', default_weight=0.0)
    def blowup_scorer(_row):
        return 5.0  # way out of range; unused arg is intentional

    try:
        SCORER_REGISTRY['test_blowup_score']['weight'] = 0.5
        SCORER_REGISTRY['test_blowup_score']['enabled'] = True

        config = {
            'conviction_score':  {'weight': 0.30, 'enabled': True},
            'test_blowup_score': {'weight': 0.50, 'enabled': True},
            'role_score': {'weight': 0.20, 'enabled': False},
            'market_cap_score': {'weight': 0.15, 'enabled': False},
            'cluster_score': {'weight': 0.15, 'enabled': False},
            'liquidity_score': {'weight': 0.10, 'enabled': False},
            'technical_score': {'weight': 0.10, 'enabled': False},
            'routine_penalty': {'weight': -0.20, 'enabled': False},
            'tenb_penalty': {'weight': -0.25, 'enabled': False},
        }

        row = {
            'transaction_type': 'BUY',
            'pct_holdings_transacted': 0.5,
            'is_routine_insider': False,
        }
        result = aggregate(row, config=config)
        # Without clamping: 0.30*0.5 + 0.50*5.0 = 2.65
        # With clamping:    0.30*0.5 + 0.50*1.0 = 0.65, then final clip = 0.65
        assert result <= 1.0, f"Expected <= 1.0, got {result}"
        assert abs(result - 0.65) < 1e-9, f"Expected 0.65, got {result}"
        print(f"  PASS: individual scorer clamp -> {result} (would have been 2.65)")
    finally:
        del SCORER_REGISTRY['test_blowup_score']


if __name__ == '__main__':
    print("=" * 60)
    print("CONVICTION SCORER TESTS")
    print("=" * 60)
    tests = [
        test_buy_high_conviction_non_routine,
        test_sell_high_conviction_non_routine,
        test_routine_sell_muted,
        test_routine_buy_rare_but_muted,
        test_null_routine_uses_conservative_default,
        test_null_pct_returns_zero,
        test_nan_pct_returns_zero,
        test_pct_clamped_above_one,
        test_symmetry_no_buy_sell_bias_in_conviction,
        test_enrich_ownership_arithmetic_fallback,
        test_enrich_ownership_forward_carry,
        test_enrich_ownership_class_boundary_no_carry,
        test_aggregator_uses_registry,
        test_aggregator_clip_to_one,
        test_aggregator_clamps_individual_scorer_output,
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
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)