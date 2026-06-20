# MIRROR Layer 3 (Cognitive Dissonance Mapper) — Current State, Remaining Work & Next Steps

**Date:** June 21, 2026 | **Author:** devdiv07
**Method:** Reconciles the two June-19 HTML reports (`MIRROR_Architecture_Report.html`, `MIRROR_Future_Roadmap_Production_Plan.html`), `implementation_plan.md`, and `docs/roadmap.md` against the **live repository** (commit `bc189d8`) and the actual files in `data/` and `results/`. Where the reports and the live repo disagree, the live repo wins and the discrepancy is flagged.

> This is the deep current-state companion to the whole-project [mirror_vision_roadmap.md](mirror_vision_roadmap.md). It covers **only Layer 3** (the component being built now).

---

## 1. Honest one-paragraph read

Layer 3's **insider leg is well-engineered and the operational hardening is essentially done** — the June-19 reports' "critical TODO" list (config path, CI, defusedxml, pinned deps, CONTRIBUTING) was almost entirely closed by the June-21 commit. The real open question is no longer *"is the code clean?"* — it's *"does the signal actually predict returns?"* — and on that, a backtest **has run** but the evidence is **mixed and not yet conclusive**. The other two legs (media, options) and the dissonance "brain" remain prototype-grade and **unintegrated**: the good `src/` insider signal is still not wired into the dissonance score. Net: Layer 3 is roughly **half-complete and unvalidated**, not "almost done."

---

## 2. Layer 3 completion breakdown (honest, rough)

| Component | What exists | State | ~Done |
|---|---|---|---|
| **Leg 1 — Insider** (`src/`) | Conviction engine: 7 scorers, registry, YAML weights, 31 tests, 8,013 transactions scored | Built + partially backtested (inconclusive) + **not integrated** | ~65% |
| **Leg 2 — Media** (`legacy/news_sentiment`) | NewsAPI fetch + TextBlob polarity, free-tier (1-month history) | Original prototype, un-upgraded, un-backtested | ~25% |
| **Leg 3 — Options** (`legacy/price_signal`) | Put/call ratio + extra signals (momentum etc.) that are computed but **unused**; known bugs noted in `implementation_plan.md` | Original prototype, un-upgraded, un-backtested | ~25% |
| **Brain** (`legacy/dissonance_calculator`) | Combines 3 legs → 0–100 score with manual weights (W1=.50/W2=.30/W3=.20); runs on 10 megacaps; uses the **crude v1 insider leg** | Prototype; manual un-backtested weights | ~30% |
| **Integration** | — | `src/` engine **not wired** to the brain; universes differ (111 small/mid vs 10 megacap) | **~0%** |
| **Validation** | One preliminary bucket backtest of the **insider signal only** | Inconclusive (see §5) | ~20% |

**Takeaway:** the part that looks most finished (the insider engine) is one of three legs, and even it is unvalidated and disconnected from the product.

---

## 3. What the June-19 reports flagged that is now DONE (verified June 21)

The reports treat these as open critical/high gaps. They are **already resolved** in commit `bc189d8` — do **not** redo them:

| Report claim (June 19) | Live status (June 21, verified) |
|---|---|
| Wrong config path `insider_signal_phase1/config/scoring.yaml` (Critical latent crash) | ✅ Fixed — `run_scoring_pipeline.py:50` loads `config/scoring.yaml` |
| No CI/CD; no `.github/workflows/` | ✅ Done — `.github/workflows/ci.yml` + `security.yml` present |
| `src/`, `config/`, `tests/` not committed to git (Critical) | ✅ Committed and tracked |
| `xml.etree` XXE risk in parser | ✅ Fixed — `import defusedxml.ElementTree as ET` (line 24) |
| Dependency versions not pinned | ✅ Fixed — all pinned (`numpy==2.4.5`, `pandas==3.0.3`, …) |
| No `CONTRIBUTING.md` | ✅ Done — `contributing.md` present |
| Missing request timeouts | ✅ Done (per commit; SEC fetch timeout added) |
| Exploratory "delete this test" comment | ✅ Removed |
| Root `insider_parser.py` deprecated duplicate | ⚠️ Deleted from disk, but the **deletion is uncommitted** (working tree only) |
| Implementation-plan phase-naming conflict | ✅ Noted at top of `implementation_plan.md` |

**Conclusion:** the reports' "Phase 3 / Stage A hardening" is ~90% complete. The reports are stale on this. The remaining hardening item is just **committing the working tree** (the reorg deletions + the untracked docs).

---

## 4. What the reports MISSED or get wrong

| Issue | Reality |
|---|---|
| **"Backtest not done"** (empty `docs/backtest_results.md` implies this) | A backtest **ran** — `results/backtest_results.csv` (86 KB) + `results/backtest_summary.csv` exist. It is just undocumented and inconclusive (§5). |
| Reports describe `src/` and `legacy/` as two parallel pipelines, both "active" | True, but they bury the key fact: the **good insider signal never reaches the dissonance score**. The product still runs on the crude v1 leg. |
| Architecture report lists "111 small/mid-cap" for Phase 2 but Phase 1 brain is "10 megacap" | This **universe mismatch** is a real integration blocker, not just a footnote. |
| `README.md` | Still stale/broken: says `python run.py` (no such file; real entry is `python -m src.pipeline.run_scoring_pipeline`), claims "431 transactions / 13 tests" (actually 8,013 / 31), links to empty docs. |
| No mention | The backtester is **not a committed, reproducible script** — it produced CSVs (logic likely in `Untitled-1.ipynb`), so the results can't be re-generated cleanly. Reproducibility gap. |

---

## 5. The backtest, read honestly (the crux)

The backtest scored insider **sell** transactions and measured **market-excess** forward returns (5/20/60/180-day), bucketed by signal strength, split by 10b5-1 plan vs opportunistic. Summary (`results/backtest_summary.csv`):

| Group | Bucket | n | 5d mean | 5d hit | 5d p | 20d mean | 20d hit | 20d p |
|---|---|---|---|---|---|---|---|---|
| All | Strong Sell | 7 | **−3.8%** | 100% | <0.001 | −3.3% | 43% | 0.30 |
| All | Moderate Sell | 152 | +0.0% | 49% | 0.92 | **+4.4%** | 30% | <0.001 |
| All | Weak Sell | 63 | −2.1% | 79% | <0.001 | −4.4% | 84% | <0.001 |
| Opportunistic | Weak Sell | 40 | **−3.1%** | 92% | <0.001 | −4.1% | 82% | <0.001 |
| 10b5-1 plan | Weak Sell | 23 | −0.5% | 57% | **0.34** | −5.1% | 92% | <0.001 |

**What's encouraging:**
- Direction is right for strong/weak sells — negative signal → negative excess return.
- The cleanest result: at 5 days, **opportunistic** weak sells fall −3.1% (p<0.001) while **plan** weak sells move −0.5% (p=0.34, insignificant). That is exactly the thesis — pre-planned trades carry less information. The 10b5-1 penalty is doing real work.

**What undercuts validation (the honest part):**
1. **Samples are tiny and non-independent.** "Strong Sell n=7" is mostly the *same* GOOGL/Pichai ticker-date repeated across several transaction lines — effective independent events ≈ 2. A p-value of 0.0005 on that is not real evidence.
2. **The largest bucket fails.** Moderate Sell (n=152) shows **zero** 5d edge and **inverts** at 20d (+4.4%, sells followed by gains, p<0.001). The signal→return relationship is **not monotonic**.
3. **Zero buy-side data.** Every bucket is a *sell*. The bullish half of the signal is **completely untested** because this universe/period is almost all selling.
4. **No IC, no walk-forward, no deflated Sharpe.** The project's own bar (`roadmap.md`: out-of-sample IC > 0.05, deflated Sharpe > 0.3) was **not measured**. This is a bucket analysis, not the institutional validation the plan calls for.

**Verdict:** a genuine *sign of life* (especially the plan-vs-opportunistic split), but **not validation**. Layer 3's signal does **not yet clear the Stage-0 gate**.

---

## 6. Remaining work to finish Layer 3 (to a validated, integrated product)

In dependency order:

1. **Make the backtester reproducible.** Extract it from the notebook into a committed `backtester.py`; compute proper **IC (Spearman)** per horizon, handle non-independent ticker-date clustering, and emit the metrics in `roadmap.md`'s gate table. Write the honest findings into the empty `docs/backtest_results.md`.
2. **Get buy-side coverage.** Expand universe/lookback so there are enough insider **buys** to test the bullish side. Half the signal is currently unfalsifiable.
3. **Diagnose the moderate-bucket inversion.** Find out why mid-strength sells have no/negative edge (scoring miscalibration? mid-strength sells are just liquidity-driven noise?).
4. **Reconnect Leg 1 → brain.** Replace `legacy` `calculate_insider_signals()` with the `src/` conviction signal; resolve the 111-small/mid vs 10-megacap **universe mismatch**.
5. **Rebuild Legs 2 & 3** (media, options) to `src/` standard and backtest each, before trusting any integrated score.
6. **Backtest the *integrated dissonance score*** — not just the insider leg. That is the actual Layer 3 product.

---

## 7. Next steps (prioritized, concrete)

| # | Action | Size | Why |
|---|---|---|---|
| 1 | Commit the working tree (reorg deletions + untracked docs) | S | One clean baseline; ends the "files are climbing" confusion |
| 2 | Fix `README.md` (run command, 8,013/31 stats, dead doc links) | S | First thing anyone hits; currently wrong |
| 3 | **Reproducible `backtester.py` with IC + small-n handling; fill `docs/backtest_results.md` honestly** | M | Highest value — this is the Stage-0 gate |
| 4 | Expand data for buy-side coverage; re-run | M | Makes the bullish half testable |
| 5 | Diagnose moderate-bucket inversion | M | Decides if the signal is real or needs rework |
| 6 | Reconnect insider leg → dissonance brain (resolve universe) | M | Turns a leg into the product |

Items 1–2 are housekeeping you can do today. Item 3 is the real work and the gate for everything in the [vision roadmap](mirror_vision_roadmap.md).

---

## 8. Bottom line

The June-19 reports describe a system that needed operational hardening. That hardening is **done**. The honest current state is different and more important: **Layer 3's insider engine is built but unvalidated and disconnected, and the one backtest that exists is encouraging but inconclusive.** The next milestone is not a feature — it is **a real, reproducible IC-based backtest with buy-side data**. Until the insider signal clears that gate, do not integrate the legs, do not rebuild the other legs at scale, and do not start Layers 1/2/4/5.
