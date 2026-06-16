#!/usr/bin/env python3
"""
MIRROR - Phase 2 Scoring Pipeline
Runs enrichment and scoring on cached transaction data
"""
import pandas as pd
import sys
import os
from datetime import datetime

from src.enrichment.enrich_ownership import enrich_ownership
from src.enrichment.enrich_market_context import enrich_market_context
from src.enrichment.enrich_tenb51 import enrich_tenb51
from src.scoring.aggregator import aggregate, explain, load_config, SCORER_REGISTRY
from src.scoring import cluster  # triggers @register_scorer decorators

def main():
    print("=" * 80)
    print("MIRROR - Phase 2 Insider Signal Pipeline")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    # Load cached transaction data
    print("\n[1/6] Loading cached transaction data...")
    df = pd.read_csv('data/insider_transactions.csv')
    print(f"  Loaded {len(df)} transactions across {df['ticker'].nunique()} tickers")

    # Enrich ownership context
    print("\n[2/6] Enriching ownership fields...")
    df = enrich_ownership(df)
    print(f"  Added: shares_owned_before, pct_holdings_transacted")

    # Enrich market context (market cap, ADV)
    print("\n[3/6] Enriching market context (market cap, 30d ADV)...")
    df = enrich_market_context(df)
    print(f"  Added: market_cap, avg_30d_dollar_volume")

    # Enrich 10b5-1 plan detection
    print("\n[4/6] Detecting 10b5-1 plan trades...")
    df = enrich_tenb51(df)
    print(f"  Added: is_10b51_plan")

    # Set up cluster context for batch scoring
    print("\n[5/6] Setting cluster context...")
    cluster.set_transactions_context(df)
    print(f"  Cluster detector ready")

    # Load config and score
    print("\n[6/6] Scoring transactions...")
    config = load_config('insider_signal_phase1/config/scoring.yaml')
    print(f"  Loaded {len(config)} scorers from config")
    enabled = [s for s, c in config.items() if c['enabled']]
    print(f"  Enabled scorers: {', '.join(enabled)}")

    # Apply aggregator to each row
    df['signal_magnitude'] = df.apply(lambda row: aggregate(row, config), axis=1)

    # Apply transaction direction: negate magnitude for SELL transactions
    # This represents: positive magnitude = more important signal
    # + direction (BUY = +, SELL = -) indicates the signal type
    df['conviction_signal'] = df.apply(
        lambda row: row['signal_magnitude'] if row['transaction_type'] == 'BUY' 
                   else -row['signal_magnitude'],
        axis=1
    )

    print(f"\n  Scored {len(df)} transactions")

    # Display top signals
    print("\n" + "=" * 80)
    print("TOP INSIDER SIGNALS (by conviction)")
    print("=" * 80)

    # Sort by abs conviction (descending)
    df['abs_signal'] = df['conviction_signal'].abs()
    df_sorted = df.sort_values('abs_signal', ascending=False)

    # Show top 15 BUYs and SELLs
    buys = df_sorted[df_sorted['conviction_signal'] > 0].head(10)
    sells = df_sorted[df_sorted['conviction_signal'] < 0].head(10)

    print("\n--- TOP BULLISH SIGNALS (Insider Buying) ---")
    for idx, (i, row) in enumerate(buys.iterrows(), 1):
        print(f"\n{idx}. {row['ticker']:6} | {row['insider_name']:30} | {row['title']:40}")
        print(f"   Date: {row['date']:10} | Transaction: {row['transaction_type']:4} | Shares: {row['shares']:15,.0f}")
        print(f"   Dollar Value: ${row['dollar_value']:20,.2f}")
        print(f"   Conviction Signal: +{row['conviction_signal']:.3f}")

        # Show detailed breakdown
        breakdown = explain(row, config)
        print(f"   Breakdown:")
        for scorer_name, details in breakdown['contributions'].items():
            if details['raw_score'] != 0:
                print(f"      {scorer_name:20} raw={details['raw_score']:6.3f} × weight={details['weight']:6.2f} = {details['contribution']:6.3f}")

    print("\n--- TOP BEARISH SIGNALS (Insider Selling) ---")
    for idx, (i, row) in enumerate(sells.iterrows(), 1):
        print(f"\n{idx}. {row['ticker']:6} | {row['insider_name']:30} | {row['title']:40}")
        print(f"   Date: {row['date']:10} | Transaction: {row['transaction_type']:4} | Shares: {row['shares']:15,.0f}")
        print(f"   Dollar Value: ${row['dollar_value']:20,.2f}")
        print(f"   Conviction Signal: {row['conviction_signal']:.3f}")

        # Show detailed breakdown
        breakdown = explain(row, config)
        print(f"   Breakdown:")
        for scorer_name, details in breakdown['contributions'].items():
            if details['raw_score'] != 0:
                print(f"      {scorer_name:20} raw={details['raw_score']:6.3f} × weight={details['weight']:6.2f} = {details['contribution']:6.3f}")

    # Save detailed results
    output_file = 'results/insider_signals_phase2.csv'
    df_output = df[[
        'ticker', 'date', 'filing_date', 'insider_name', 'title',
        'transaction_type', 'shares', 'price', 'dollar_value',
        'pct_holdings_transacted', 'market_cap', 'avg_30d_dollar_volume',
        'is_10b51_plan', 'conviction_signal'
    ]].copy()
    df_output = df_output.sort_values('conviction_signal', key=abs, ascending=False)
    df_output.to_csv(output_file, index=False)
    print(f"\n[DONE] Detailed results saved to {output_file}")

    # Summary stats
    print("\n" + "=" * 80)
    print("SUMMARY STATISTICS")
    print("=" * 80)
    print(f"Total transactions scored: {len(df)}")
    print(f"Strong bullish signals (>+0.50): {len(df[df['conviction_signal'] > 0.50])}")
    print(f"Moderate bullish signals (0.30-0.50): {len(df[(df['conviction_signal'] > 0.30) & (df['conviction_signal'] <= 0.50)])}")
    print(f"Moderate bearish signals (-0.50 to -0.30): {len(df[(df['conviction_signal'] < -0.30) & (df['conviction_signal'] >= -0.50)])}")
    print(f"Strong bearish signals (<-0.50): {len(df[df['conviction_signal'] < -0.50])}")
    print(f"Mean conviction signal: {df['conviction_signal'].mean():.3f}")
    print(f"Std dev: {df['conviction_signal'].std():.3f}")

    print("\n" + "=" * 80)
    print(f"Pipeline complete! {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

if __name__ == "__main__":
    main()
