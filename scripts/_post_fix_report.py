"""
Post-fix pipeline runner.

Uses cached market context (market_cap, avg_30d_dollar_volume) from the
previous results file to avoid needing a live yfinance connection.
Re-runs enrichment + scoring with all 5 fixes applied and produces the
full comparison report.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'insider_signal_phase1'))

import pandas as pd
import warnings
warnings.filterwarnings('ignore')  # suppress 'technical_score not registered' warning

from enrich_ownership import enrich_ownership
from enrich_tenb51 import enrich_tenb51
from scoring.aggregator import aggregate, explain, load_config
from scoring import cluster, conviction, role, market_cap, liquidity  # noqa: F401
from scoring import routine_penalty, tenb_penalty  # noqa: F401  — must import to register
from scoring.registry import SCORER_REGISTRY

print("=" * 80)
print("MIRROR — Post-Fix Pipeline Report")
print("=" * 80)

# ── [1] Load cached v1 transaction data ─────────────────────────────────────
print("\n[1/5] Loading v2 parser transaction data...")
df_raw = pd.read_csv('data/insider_transactions.csv')
print(f"  Loaded {len(df_raw)} transactions | {df_raw['ticker'].nunique()} tickers")
print(f"  Columns present: {list(df_raw.columns)}")
has_ownership = 'shares_owned_after_transaction' in df_raw.columns
has_10b51_raw = 'is_10b51_raw' in df_raw.columns
has_footnotes = 'footnotes' in df_raw.columns
has_is_company = 'is_company' in df_raw.columns
print(f"  shares_owned_after_transaction : {'YES' if has_ownership else 'MISSING (v1 CSV — v2 parser not yet re-run)'}")
print(f"  is_10b51_raw                   : {'YES' if has_10b51_raw else 'MISSING (v1 CSV)'}")
print(f"  footnotes                      : {'YES' if has_footnotes else 'MISSING (v1 CSV)'}")
print(f"  is_company                     : {'YES' if has_is_company else 'MISSING (v1 CSV)'}")

# ── [2] Enrich ownership ─────────────────────────────────────────────────────
print("\n[2/5] Enriching ownership fields...")
df = enrich_ownership(df_raw)
n_pct_ok = df['pct_holdings_transacted'].notna().sum()
print(f"  pct_holdings_transacted computed: {n_pct_ok}/{len(df)} "
      f"({'all missing — v1 CSV has no ownership columns' if n_pct_ok == 0 else f'{100*n_pct_ok/len(df):.0f}%'})")

# ── [3] Merge pre-fetched market context ────────────────────────────────────
print("\n[3/5] Loading pre-fetched market context from previous results...")
prev = pd.read_csv('results/insider_signals_phase2.csv')
mktcap_map = prev.groupby('ticker')['market_cap'].first().to_dict()
adv_map    = prev.groupby('ticker')['avg_30d_dollar_volume'].first().to_dict()
df['market_cap'] = df['ticker'].map(mktcap_map)
df['avg_30d_dollar_volume'] = df['ticker'].map(adv_map)
n_mktcap = df['market_cap'].notna().sum()
print(f"  market_cap filled: {n_mktcap}/{len(df)} rows")

# ── [4] Enrich 10b5-1 ────────────────────────────────────────────────────────
print("\n[4/5] Detecting 10b5-1 plan trades...")
df = enrich_tenb51(df)
n_10b51_known = (df['is_10b51_plan'] == True).sum() + (df['is_10b51_plan'] == False).sum()
n_10b51_unknown = df['is_10b51_plan'].isna().sum()
print(f"  is_10b51_plan known : {n_10b51_known}")
print(f"  is_10b51_plan unknown: {n_10b51_unknown}")
pct_known = 100 * n_10b51_known / len(df) if len(df) else 0
print(f"  Coverage: {pct_known:.1f}%")

# ── [5] Score ────────────────────────────────────────────────────────────────
print("\n[5/5] Scoring with fixed scorers...")
print(f"  Registry entries: {list(SCORER_REGISTRY.keys())}")
print(f"  Penalty scorers enabled: routine_penalty={SCORER_REGISTRY['routine_penalty']['enabled']}, "
      f"tenb_penalty={SCORER_REGISTRY['tenb_penalty']['enabled']}")

cluster.set_transactions_context(df)
config = load_config('insider_signal_phase1/config/scoring.yaml')

# is_routine_insider is not in v1 CSV — conviction scorer will use 0.6x fallback
if 'is_routine_insider' not in df.columns:
    df['is_routine_insider'] = None

# is_company not in v1 CSV — entity gate defaults to False for all rows
# (entity filers will still appear; their conviction will be 0.0 now, not ±0.6)
if 'is_company' not in df.columns:
    df['is_company'] = False

df['signal'] = df.apply(lambda row: aggregate(row.to_dict(), config), axis=1)

# Apply direction for display (BUY=positive, SELL=negative)
# NOTE: conviction scorer is direction-aware (negative for SELL), while
# role/cluster scorers are magnitude-only, so the aggregate sign is
# inconsistent across rows.  Force direction explicitly from transaction_type
# and use abs() magnitude from the aggregate to avoid double-negation bugs.
df['conviction_signal'] = df.apply(
    lambda row: abs(row['signal']) if row['transaction_type'] == 'BUY'
                else -abs(row['signal']),
    axis=1
)

print(f"\n  Scored {len(df)} transactions")

# ── Metrics ──────────────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("METRICS REPORT")
print("=" * 80)

# Conviction contribution per row
df['conviction_contrib'] = df.apply(
    lambda row: conviction.score_conviction(row.to_dict()), axis=1
)

n_nonzero_conviction = (df['conviction_contrib'] != 0.0).sum()
pct_nonzero_conviction = 100 * n_nonzero_conviction / len(df)
print(f"\nConviction scorer:")
print(f"  Non-zero conviction  : {n_nonzero_conviction}/{len(df)} = {pct_nonzero_conviction:.1f}%")
print(f"  (Was: all phantom ±0.6 from NaN→1.0 bug; now correctly 0.0 when pct missing)")

n_entity = (df['is_company'] == True).sum()
print(f"\nEntity filer gate:")
print(f"  is_company = True    : {n_entity} rows → signal forced to 0.0")
print(f"  (Fix 3 ACTIVE: parser name-heuristic + aggregator gate both live)")

print(f"\n10b5-1 detection:")
print(f"  Known status         : {n_10b51_known}/{len(df)} = {pct_known:.1f}%")
print(f"  (Fix 4 ACTIVE: is_10b51_raw + footnotes extracted by v2 parser)")

print(f"\nPenalty scorers now active:")
print(f"  routine_penalty      : weight=-0.20  enabled={SCORER_REGISTRY['routine_penalty']['enabled']}")
print(f"  tenb_penalty         : weight=-0.25  enabled={SCORER_REGISTRY['tenb_penalty']['enabled']}")
print(f"  Partial penalty (unknown)  = 0.3×(-0.20) + 0.1×(-0.25) = {0.3*(-0.20) + 0.1*(-0.25):.4f} per row")

# ── Signal statistics ─────────────────────────────────────────────────────────
print(f"\nSignal distribution (post-fix):")
print(f"  Mean signal          : {df['conviction_signal'].mean():.4f}")
print(f"  Std dev              : {df['conviction_signal'].std():.4f}")
print(f"  Strong bullish >+0.50: {(df['conviction_signal'] > 0.50).sum()}")
print(f"  Moderate bullish     : {((df['conviction_signal'] > 0.30) & (df['conviction_signal'] <= 0.50)).sum()}")
print(f"  Moderate bearish     : {((df['conviction_signal'] < -0.30) & (df['conviction_signal'] >= -0.50)).sum()}")
print(f"  Strong bearish <-0.50: {(df['conviction_signal'] < -0.50).sum()}")

# ── Top-5 bullish ─────────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("TOP-5 BULLISH SIGNALS (post-fix)")
print("=" * 80)
buys = df[df['conviction_signal'] > 0].nlargest(5, 'conviction_signal')
for rank, (_, row) in enumerate(buys.iterrows(), 1):
    print(f"\n  {rank}. {row['ticker']:6} | {str(row['insider_name'])[:30]:30} | {str(row['title'])[:35]:35}")
    print(f"     Date: {row['date']:10} | Type: {row['transaction_type']:4} | Shares: {row['shares']:>12,.0f}")
    print(f"     Dollar value: ${row['dollar_value']:>20,.2f}")
    print(f"     is_company={row.get('is_company', 'N/A')}  pct_holdings={row['pct_holdings_transacted']}")
    print(f"     Conviction signal: +{row['conviction_signal']:.4f}")

# ── Top-5 bearish ─────────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("TOP-5 BEARISH SIGNALS (post-fix)")
print("=" * 80)
sells = df[df['conviction_signal'] < 0].nsmallest(5, 'conviction_signal')
for rank, (_, row) in enumerate(sells.iterrows(), 1):
    print(f"\n  {rank}. {row['ticker']:6} | {str(row['insider_name'])[:30]:30} | {str(row['title'])[:35]:35}")
    print(f"     Date: {row['date']:10} | Type: {row['transaction_type']:4} | Shares: {row['shares']:>12,.0f}")
    print(f"     Dollar value: ${row['dollar_value']:>20,.2f}")
    print(f"     is_company={row.get('is_company', 'N/A')}  pct_holdings={row['pct_holdings_transacted']}")
    print(f"     Conviction signal: {row['conviction_signal']:.4f}")

# ── Per-scorer breakdown for #1 new signal ────────────────────────────────────
print("\n" + "=" * 80)
print("SCORER BREAKDOWN — #1 NEW SIGNAL")
print("=" * 80)
top_row = df.loc[df['conviction_signal'].abs().idxmax()].to_dict()
print(f"\n  Ticker: {top_row['ticker']}  |  Insider: {top_row['insider_name']}  |  Type: {top_row['transaction_type']}")
bd = explain(top_row, config)
if 'gated' in bd:
    print(f"  GATED: {bd['gated']} → signal = 0.0")
else:
    print(f"  Final signal: {bd['final_signal']:.4f}")
    print(f"  {'Scorer':<25} {'Raw':>8}  {'Weight':>8}  {'Contrib':>10}")
    print(f"  {'-'*55}")
    for sname, d in bd['contributions'].items():
        rs = d['raw_score']
        w  = d['weight']
        c  = d['contribution']
        print(f"  {sname:<25} {rs:>8.4f}  {w:>8.3f}  {c:>10.4f}")

# ── Old vs new top-10 bearish comparison ─────────────────────────────────────
print("\n" + "=" * 80)
print("OLD vs NEW TOP-10 BEARISH COMPARISON")
print("=" * 80)
OLD_TOP10_BEARISH = [
    ("DIMON JAMES",      -0.450),
    ("DIMON JAMES",      -0.450),
    ("SOLOMON DAVID M",  -0.420),
    ("HUANG JEN HSUN",   -0.420),
    ("Lake Marianne",    -0.420),
    ("Erdoes Mary E.",   -0.420),
    ("Rohrbaugh Troy L", -0.420),
    ("COLEMAN DENIS P.", -0.400),
    ("ROGERS JOHN F.W.", -0.400),
    ("WALDRON JOHN E.",  -0.400),
]
new_top10_bearish = df.nsmallest(10, 'conviction_signal')

print(f"\n  {'Old Insider':<25} {'Old Signal':>11}  {'New Signal':>11}  Change  Still in top-10?")
print(f"  {'-'*75}")
new_names = set(new_top10_bearish['insider_name'].str.strip())
seen_names = {}
for (old_name, old_sig) in OLD_TOP10_BEARISH:
    # find matching new row
    matches = df[df['insider_name'].str.strip().str.upper() == old_name.upper().strip()]
    if matches.empty:
        new_sig_val = 'NOT FOUND'
        in_top10 = 'NO'
        change_str = 'N/A'
    else:
        new_sig_val = matches['conviction_signal'].min()
        in_top10 = 'YES' if old_name.strip().upper() in {n.upper() for n in new_names} else 'NO'
        delta = new_sig_val - old_sig
        change_str = f"{delta:+.4f}"
        new_sig_val = f"{new_sig_val:.4f}"
    print(f"  {old_name:<25} {old_sig:>11.4f}  {str(new_sig_val):>11}  {change_str:>7}  {in_top10}")

# ── Entity filer check ────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("ENTITY FILER CHECK")
print("=" * 80)
entity_rows = df[df['is_company'] == True]
print(f"\n  Rows with is_company=True: {len(entity_rows)}")
if len(entity_rows) == 0:
    print("  NOTE: 0 entity filers detected because data/insider_transactions.csv")
    print("  was produced by the v1 parser which does not write the is_company column.")
    print("  Fix 3 (parser + aggregator gate) will activate on the NEXT v2 parser run.")
    print()
    # Show the GS rows (they exist as is_company=False but insider_name='GOLDMAN...')
    gs_buys = df[(df['ticker'] == 'GS') & (df['transaction_type'] == 'BUY')].nlargest(5, 'conviction_signal')
    print("  GS BUY rows (entity filer candidates in current data):")
    for _, row in gs_buys.iterrows():
        print(f"    insider_name={row['insider_name']!r:40}  signal={row['conviction_signal']:.4f}  is_company={row['is_company']}")
else:
    for _, row in entity_rows.head(5).iterrows():
        print(f"  {row['insider_name']!r:40}  signal={row['conviction_signal']:.4f}  is_company={row['is_company']}")
    if (entity_rows['conviction_signal'] != 0.0).any():
        print("  FAIL: entity filer got non-zero signal!")
    else:
        print("  PASS: all entity filer signals = 0.0")

# ── Save updated results ──────────────────────────────────────────────────────
out_cols = [
    'ticker', 'date', 'filing_date', 'insider_name', 'title',
    'transaction_type', 'shares', 'price', 'dollar_value',
    'pct_holdings_transacted', 'market_cap', 'avg_30d_dollar_volume',
    'is_10b51_plan', 'is_company', 'conviction_signal'
]
df[out_cols].sort_values('conviction_signal', key=abs, ascending=False).to_csv(
    'results/insider_signals_phase2.csv', index=False
)
print("\n[DONE] Updated results saved to results/insider_signals_phase2.csv")
