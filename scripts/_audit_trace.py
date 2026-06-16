"""Temporary audit script to trace scorer contributions."""
import pandas as pd
import sys
sys.path.insert(0, 'insider_signal_phase1')

from scoring.aggregator import aggregate, explain, load_config
from scoring import cluster

df = pd.read_csv('results/insider_signals_phase2.csv')
cluster.set_transactions_context(df)
config = load_config('insider_signal_phase1/config/scoring.yaml')

# --- Row 0: DIMON JAMES, JPM, SELL ---
row0 = df.iloc[0].to_dict()
print("=== Row 0: DIMON JAMES, JPM SELL ===")
bd = explain(row0, config)
print("Final signal:", bd['final_signal'])
for n, d in bd['contributions'].items():
    rs = d['raw_score']
    w  = d['weight']
    c  = d['contribution']
    print(f"  {n:<25}  raw={rs:7.4f}  w={w:7.3f}  contrib={c:8.4f}")

# --- GS BUY row ---
print()
gs_buys = df[(df['ticker'] == 'GS') & (df['transaction_type'] == 'BUY')]
if not gs_buys.empty:
    row_gs = gs_buys.iloc[0].to_dict()
    print("=== GS BUY:", row_gs['insider_name'], "===")
    bd_gs = explain(row_gs, config)
    print("Final signal:", bd_gs['final_signal'])
    for n, d in bd_gs['contributions'].items():
        rs = d['raw_score']
        w  = d['weight']
        c  = d['contribution']
        print(f"  {n:<25}  raw={rs:7.4f}  w={w:7.3f}  contrib={c:8.4f}")

# --- Check cluster context for NVDA ---
print()
print("=== NVDA SELL cluster size check ===")
nvda_sells = df[(df['ticker'] == 'NVDA') & (df['transaction_type'] == 'SELL')]
print(f"NVDA SELL count: {len(nvda_sells)}")
print(f"NVDA SELL distinct insiders: {nvda_sells['insider_name'].nunique()}")
print(f"NVDA date range: {nvda_sells['date'].min()} to {nvda_sells['date'].max()}")

# --- Verify is_10b51_plan column distribution ---
print()
print("=== is_10b51_plan distribution ===")
print(df['is_10b51_plan'].value_counts(dropna=False).to_dict())

# --- Check pct_holdings_transacted ---
print()
print("=== pct_holdings_transacted ===")
print("Non-null count:", df['pct_holdings_transacted'].notna().sum())
print("Sample (first 5):", df['pct_holdings_transacted'].head(5).tolist())
