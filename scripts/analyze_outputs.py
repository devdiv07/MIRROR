import pandas as pd
import numpy as np

df = pd.read_csv('results/insider_signals_phase2.csv')

print('=== PHASE 2 OUTPUT ANALYSIS ===')
print(f'Total rows: {len(df)}')
print(f'Unique tickers: {df["ticker"].nunique()}')
print(f'Tickers: {sorted(df["ticker"].unique().tolist())}')

print('\n=== MISSING VALUES ===')
null_counts = df.isnull().sum()
missing = null_counts[null_counts > 0]
print(missing.to_string() if len(missing) > 0 else 'No missing values detected')

print('\n=== CONVICTION SIGNAL RANGE CHECK ===')
cs = df['conviction_signal']
print(f'Min:  {cs.min():.6f}')
print(f'Max:  {cs.max():.6f}')
print(f'Mean: {cs.mean():.6f}')
print(f'Median: {cs.median():.6f}')
print(f'Out of [-1.0, +1.0]: {((cs < -1.0) | (cs > 1.0)).sum()} rows  <-- should be 0')

print('\n=== SIGNAL DISTRIBUTION ===')
bins = [-1.01, -0.6, -0.3, -0.01, 0.01, 0.3, 0.6, 1.01]
labels = ['Strong Sell', 'Sell', 'Weak Sell', 'Neutral', 'Weak Buy', 'Buy', 'Strong Buy']
df['signal_bucket'] = pd.cut(cs, bins=bins, labels=labels)
print(df['signal_bucket'].value_counts().sort_index().to_string())

print('\n=== ENRICHMENT FIELD COVERAGE ===')
for col in ['pct_holdings_transacted', 'market_cap', 'avg_30d_dollar_volume', 'is_10b51_plan']:
    total = len(df)
    filled = df[col].notna().sum()
    pct = 100 * filled / total
    status = 'OK' if pct >= 80 else 'WARNING'
    print(f'[{status}] {col}: {filled}/{total} ({pct:.1f}%)')

print('\n=== FAILED ENRICHMENT ROWS (sample) ===')
failed_enrich = df[df['pct_holdings_transacted'].isna() | df['market_cap'].isna()]
print(f'Rows with any enrichment failure: {len(failed_enrich)}')
if len(failed_enrich) > 0:
    print(failed_enrich[['ticker', 'date', 'insider_name', 'pct_holdings_transacted', 'market_cap']].head(5).to_string(index=False))

print('\n=== TOP 10 BULLISH SIGNALS (BUY) ===')
top_bull = df[df['transaction_type'] == 'BUY'].nlargest(10, 'conviction_signal')
cols = ['ticker', 'date', 'insider_name', 'title', 'dollar_value', 'pct_holdings_transacted', 'conviction_signal']
print(top_bull[cols].to_string(index=False))

print('\n=== TOP 10 BEARISH SIGNALS (SELL) ===')
top_bear = df[df['transaction_type'] == 'SELL'].nsmallest(10, 'conviction_signal')
print(top_bear[cols].to_string(index=False))

print('\n=== TRANSACTION TYPE BREAKDOWN ===')
print(df['transaction_type'].value_counts().to_string())

print('\n=== 10b5-1 PLAN BREAKDOWN ===')
if '10b51' not in str(df.columns.tolist()):
    col_10b = 'is_10b51_plan'
else:
    col_10b = 'is_10b51_plan'
print(df[col_10b].value_counts().to_string())
print(f'10b5-1 trades as % of total: {100*df[col_10b].sum()/len(df):.1f}%')
# all this script in this folder is use for only temporary audit and debugging purposes, not for production use
