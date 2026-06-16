# Change Justification Report
## MIRROR — Phase 2 Migration: Multi-Factor Insider Conviction Engine

**Date:** 2026-06-17
**Branch:** main
**Author:** devdiv07
**Status:** Verified — 31/31 tests passing

---

## 1. Summary

This report documents the migration from MIRROR's original threshold-based insider signal system (Phase 1 / v1) to a modular, config-driven multi-factor conviction scoring engine (Phase 2). The change is justified by quantitative evidence from the existing output CSVs, a passing test suite, and architectural analysis of both systems.

---

## 2. The Problem With Phase 1

The original pipeline (`legacy/run_mirror.py` orchestrating `insider_parser.py` → `NEWS_SENTIMENT.PY` → `price_signal.py` → `dissonance_calculator.py`) used a **5-point threshold** for the insider signal:

```
net buy  > $1,000,000  → insider_signal = +0.7
net buy  > $100,000    → insider_signal = +0.3
net sell < -$1,000,000 → insider_signal = -0.7
net sell < -$100,000   → insider_signal = -0.3
else                   → insider_signal =  0.0
```

**Why this was insufficient:**

| Problem | Example | Impact |
|---|---|---|
| Dollar-blind | A $1M buy by a billionaire CEO = same signal as $1M buy by a $30M micro-cap director | False signal equivalence |
| No ownership context | No measure of what % of holdings were traded | Cannot distinguish noise from conviction |
| No 10b5-1 penalty | Pre-planned program trades scored identically to spontaneous conviction buys | Inflated bullish signals |
| No role weighting | CEO and a junior Director produce same insider_signal | Information advantage not captured |
| No cluster detection | 10 insiders buying on same day = same signal as 1 insider buying | Multi-confirmation ignored |
| 5 discrete values | Signal resolution = only 5 possible values | Loses ranking precision |
| Hardcoded thresholds | Changing $1M threshold requires Python edits | Analyst cannot tune without developer |

---

## 3. What Changed

### Architecture

**Before (Phase 1):**
```
4 root-level scripts → flat CSV pipeline → 10 ticker-level dissonance scores
```

**After (Phase 2):**
```
src/parsers/ → src/enrichment/ (3 layers) → src/scoring/ (7 scorers, registry pattern)
→ src/pipeline/ → transaction-level conviction signals
```

### Files Added (Phase 2 — all untracked, need git commit)
```
src/
  parsers/
    sec_filings_fetcher.py    — EDGAR API ingestion for 146-ticker universe
    insider_parser_v2.py      — v2 Form 4 parser (+ ownership, role flags, 10b5-1)
    universe.py               — Ticker→CIK resolver
  enrichment/
    enrich_ownership.py       — 3-strategy ownership % computation
    enrich_market_context.py  — yfinance market cap + 30d ADV per ticker
    enrich_tenb51.py          — 10b5-1 plan detection (tag + footnote regex)
  scoring/
    registry.py               — @register_scorer decorator + SCORER_REGISTRY
    aggregator.py             — YAML-driven weighted aggregation, explain()
    conviction.py             — % holdings transacted (dominant scorer)
    role.py                   — Role weight (CEO=1.0, CFO=0.90, Director=0.55)
    market_cap.py             — Trade size normalized by market cap
    liquidity.py              — Trade size vs 30-day ADV
    cluster.py                — Multi-insider confirmation scorer
    routine_penalty.py        — Seasonal/calendar trade penalty
    tenb_penalty.py           — 10b5-1 plan penalty
  pipeline/
    run_scoring_pipeline.py   — 6-stage orchestrator
config/
  scoring.yaml                — All scorer weights (tunable without code changes)
  universe_smallmid.txt       — 146-ticker small/mid-cap universe
tests/
  test_conviction.py          — 15 tests (conviction, enrichment, aggregator)
  test_cluster.py             — 5 tests (cluster same-day discount)
  test_10b51_extraction.py    — 7 tests (parser 10b5-1 + footnotes)
  test_entity_filer.py        — 4 tests (entity gate)
```

### Files Moved to Legacy (Phase 1 archived)
```
legacy/
  run_mirror.py               — Original pipeline orchestrator
  dissonance_calculator.py    — Cognitive dissonance scorer
  price_signal.py             — Options/volume signal extractor
  news_sentiment.py           — News sentiment (copy of NEWS_SENTIMENT.PY)
  insider_parser.py           — v1 Form 4 parser
```

---

## 4. Evidence

### 4A. Test Results (31/31 Passing)

```
pytest tests/ -v

31 passed, 2 warnings in 1.44s
```

**Tests cover:**
- Conviction scorer: 9 unit tests (edge cases: NaN, None, clamp >1.0, symmetry)
- Enrichment: 3 tests (arithmetic fallback, forward-carry, derivative class boundary)
- Aggregator: 3 tests (registry wiring, clamp, individual scorer overflow guard)
- Cluster scorer: 5 tests (same-day discount, threshold behavior, BUY vs SELL)
- 10b5-1 extraction: 7 tests (raw tag, footnote regex, end-to-end enrichment)
- Entity filer gate: 4 tests (parser tagging, aggregator hard-gate)

**Warning (not a bug):**
- `technical_score` is enabled in YAML but no scorer is registered yet — intentional, documented as "disabled pending backtesting."

### 4B. Bug Found and Fixed During Verification

**File:** `src/parsers/insider_parser_v2.py` — `_extract_owner_flags()`

**Bug:** The `is_company` flag was computed entirely via name keyword heuristics, with an incorrect XPath (`'.//reportingOwner/reportingOwnerId/rptOwnerName'` — extra `/reportingOwnerId/` node does not exist in actual EDGAR XML). The code comment falsely stated "EDGAR Form 4 has no explicit `<isCompany>` element" — in fact, `<isCompany>1</isCompany>` is explicitly present inside `<reportingOwnerType>` in all modern Form 4 filings.

**Impact:** Entity filers (Goldman Sachs Group Inc, index funds, ESPP trusts) would have been scored instead of gated to 0.0. This is a correctness bug — institutional non-discretionary trades would pollute the conviction signals.

**Fix:** Read `<reportingOwnerType/isCompany>` directly as the primary detection method; name heuristics retained as fallback for older filings pre-dating the tag.

```python
# Before (broken)
owner_name = (root.findtext('.//reportingOwner/reportingOwnerId/rptOwnerName') or '').upper()
name_words = set(owner_name.replace(',', ' ').replace('.', ' ').split())
flags['is_company'] = bool(name_words & _ENTITY_KEYWORDS)

# After (correct)
is_company_el = root.find('.//reportingOwner/reportingOwnerType/isCompany')
if is_company_el is not None and is_company_el.text:
    flags['is_company'] = is_company_el.text.strip() in ('1', 'true', 'yes')
else:
    # Fallback: name heuristics for older filings
    owner_name = (root.findtext('.//rptOwnerName') or '').upper()
    ...
```

### 4C. Output Comparison

| Metric | Phase 1 Output (`dissonance_scores.csv`) | Phase 2 Output (`insider_signals_phase2.csv`) |
|---|---|---|
| Rows | 10 (one per ticker) | 8,013 (one per transaction) |
| Tickers covered | 10 (megacaps only) | 111 (small/mid-cap universe) |
| Signal range | {−0.7, −0.3, 0, +0.3, +0.7} (5 values) | [−0.488, +0.644] (continuous) |
| Signal resolution | Discrete, 5 levels | Float with 6 decimal places |
| Out of [−1.0, +1.0] | N/A | 0 violations |
| 10b5-1 trades detected | 0 (not tracked) | 1,533 (19.1% of all transactions) |
| Enrichment failures | N/A | 43 rows (0.5%) — `pct_holdings_transacted` = None |
| Missing title field | N/A | 1,332 rows (16.6%) — expected, Form 4 often omits title |
| Market cap coverage | 0% (not tracked) | 100% |

### 4D. Signal Distribution (Phase 2)

```
Strong Sell  (< −0.6):   0 transactions
Sell         (−0.6–−0.3): 531 transactions
Weak Sell    (−0.3–0):   5,972 transactions
Neutral      (~0):        154 transactions
Weak Buy     (0–+0.3):   1,250 transactions
Buy          (+0.3–+0.6): 105 transactions
Strong Buy   (> +0.6):     1 transaction
```

**Observation:** The mean signal is −0.14 (net bearish). This reflects the dataset composition — small/mid-cap insiders currently show more selling than buying activity. The signal is well-distributed, not degenerate.

### 4E. Top 10 Bullish Signals

| Ticker | Date | Insider | Title | Dollar Value | % Holdings | Signal |
|---|---|---|---|---|---|---|
| GO | 2026-03-19 | Potter Jason J. N. | President and CEO | $1.69M | 99.2% | +0.644 |
| SFNC | 2025-07-23 | MAKRIS GEORGE JR | Chairman & CEO | $325K | 128.2% | +0.570 |
| GO | 2025-02-28 | Ragatz Erik D. | — | $2.02M | 452.1% | +0.555 |
| GO | 2026-03-09 | Lindberg Eric J. Jr. | — | $1.64M | 163.0% | +0.555 |
| SFNC | 2025-07-23 | Hobbs Charles Daniel | EVP & CFO | $100K | 112.2% | +0.520 |

### 4F. Top 10 Bearish Signals

| Ticker | Date | Insider | Title | Dollar Value | % Holdings | Signal |
|---|---|---|---|---|---|---|
| CHEF | 2026-03-03 | Pappas Christopher | President and CEO | −$6.0M | 3.8% | −0.488 |
| SANM | 2026-05-06 | SOLA JURE | Chairman & CEO | −$27.1M | 8.8% | −0.479 |
| MEDP | 2025-11-19 | Troendle August J. | CEO | −$14.1M | 2.7% | −0.468 |

---

## 5. Security Checks

| Check | Result |
|---|---|
| `.env` in `.gitignore` | ✅ Yes — `.env` and `*.env` are gitignored |
| `data/*.csv` in `.gitignore` | ✅ Yes — large data files excluded |
| `results/*.csv` in `.gitignore` | ✅ Yes — output files excluded |
| API keys committed | ✅ No — only `.env.example` with placeholder values |
| Real API key in `.env` | ⚠️ Present locally, never committed — rotate if shared |

---

## 6. Risks and Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| `src/`, `config/`, `tests/` not yet in git | **Critical** | Commit immediately (see Section 7) |
| `technical_score` enabled in YAML but unregistered | Low | Aggregator emits `UserWarning`, not error; documented in YAML comments |
| 43 rows with missing `pct_holdings_transacted` | Low | Conviction scorer returns 0.0 for None; no crash |
| 1,332 rows with missing `title` field | Low | Role scorer uses `is_officer`/`is_director` flags as fallback |
| 121 rows with missing `is_10b51_plan` | Low | Penalty scorer skips None rows (no penalty applied) |
| yfinance market data staleness | Medium | Pipeline caches per run; add run timestamp to CSV |
| `insider_parser.py` at root level is v1 duplicate | Low | Mark as deprecated; delete in Phase 3 cleanup |

---

## 7. Recommended Git Commit

```
git add src/ config/ tests/ scripts/ docs/ legacy/ data/company_tickers.json
git commit -m "Phase 2: multi-factor insider conviction engine with enrichment, scoring registry, and tests

- Replace 5-point threshold signal with 7-scorer conviction engine (continuous [-1.0,+1.0])
- Add 3 enrichment layers: ownership%, market cap+ADV, 10b5-1 plan detection
- Implement @register_scorer registry pattern; weights configurable via config/scoring.yaml
- Score 8013 transactions across 111 small/mid-cap tickers (vs 10 megacaps in Phase 1)
- Fix is_company detection in insider_parser_v2: read <isCompany> XML tag directly
  (was: broken name heuristic with wrong XPath; now: tag-first + name fallback)
- Fix test import paths (scoring.* → src.scoring.*, insider_parser_v2 → src.parsers.*)
- Add 31 pytest tests: conviction, cluster, 10b5-1 extraction, entity filer gate
- Archive Phase 1 pipeline to legacy/; NEWS_SENTIMENT.PY + dissonance model preserved

Test results: 31/31 passed
Output: results/insider_signals_phase2.csv (8013 rows, 0 range violations)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## 8. What to Test Next

| Test | How | Expected |
|---|---|---|
| Entity filer gate in production data | Filter `insider_signals_phase2.csv` for known ETF/fund tickers | Signal = 0.0 or not present |
| 10b5-1 penalty effect | Compare mean signal for `is_10b51_plan=True` vs `False` rows | `True` rows should have lower magnitude |
| Backtest validation | Cross `insider_signals_phase2.csv` with `results/backtest_prices_smallmid.csv` | High conviction signals show better forward returns |
| Phase 1 dissonance model | Run `legacy/run_mirror.py` end-to-end after path fix | `results/dissonance_scores.csv` regenerated |
| Pipeline re-run | `python src/pipeline/run_scoring_pipeline.py` with fresh SEC data | Same output shape, updated signals |
