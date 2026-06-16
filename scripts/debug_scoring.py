#!/usr/bin/env python3
import pandas as pd
import sys
sys.path.insert(0, 'insider_signal_phase1')

from enrich_ownership import enrich_ownership
from enrich_market_context import enrich_market_context  
from enrich_tenb51 import enrich_tenb51
from scoring.aggregator import aggregate, explain, load_config
from scoring import cluster

# Test first transaction
df = pd.read_csv('data/insider_transactions.csv').head(1)
print('Original row:')
for col in ['ticker', 'insider_name', 'title', 'transaction_type', 'shares', 'dollar_value']:
    print(f'  {col}: {df.iloc[0][col]}')

df = enrich_ownership(df)
print('\nAfter ownership enrichment:')
print(f'  pct_holdings_transacted: {df.iloc[0]["pct_holdings_transacted"]}')
print(f'  shares_owned_before_transaction: {df.iloc[0]["shares_owned_before_transaction"]}')

df = enrich_market_context(df)
print('\nAfter market context:')
print(f'  market_cap: {df.iloc[0]["market_cap"]}')

df = enrich_tenb51(df)
print('\nAfter 10b5-1 detection:')
print(f'  is_10b51_plan: {df.iloc[0]["is_10b51_plan"]}')

cluster.set_transactions_context(df)
config = load_config('insider_signal_phase1/config/scoring.yaml')

print('\nFinal aggregated signal:')
breakdown = explain(df.iloc[0].to_dict(), config)
print(f'  conviction_signal: {breakdown["final_signal"]}')
print(f'\n  Contributions:')
for name, details in breakdown['contributions'].items():
    print(f'    {name:20} raw={details["raw_score"]:6.3f} × weight={details["weight"]:6.2f} = {details["contribution"]:6.3f}')
