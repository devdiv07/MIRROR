# FOCUS — the one file to follow

**Open this when you sit down. Ignore every other doc until the gate.**
_Last set: June 21, 2026_

---

## THE GOAL (until further notice)

> Prove — or disprove — that the insider conviction signal predicts forward returns.
> **Get one real IC number.** Everything right now serves this.

---

## THE PATH (in order — don't skip, don't add)

### Step 0 — Clean baseline _(today, ~1 hr)_
- [ ] Commit the working tree (reorg deletions + untracked docs)
- [ ] Fix README (run command = `python -m src.pipeline.run_scoring_pipeline`; real 8,013 / 31 numbers)
- **Done when:** `git status` clean + README accurate. Never touch again.

### Step 1 — Reproducible backtester _(the real work)_
- [ ] Extract backtest from `Untitled-1.ipynb` → committed `src/backtest/backtester.py`
- [ ] Compute Spearman **IC** per horizon (5d, 20d) + hit rate
- [ ] Collapse duplicate ticker-date rows so n is honest
- [ ] Write the honest result into `docs/backtest_results.md`
- **Done when:** `python -m src.backtest.backtester` prints an IC number.

### Step 2 — Buy-side data
- [ ] Expand universe / lookback to get enough insider **buys**
- [ ] Re-run the backtester
- **Done when:** backtest has real buy AND sell buckets.

---

## 🛑 THE GATE — this is "until what"

Read the IC. Make one decision:

- **IC > 0.05, holds on both sides** → signal is real → reconnect insider leg → dissonance brain, continue the vision roadmap.
- **IC ≈ 0 / one-sided / contradictory** → not proven → diagnose the moderate-bucket inversion, re-tune, re-run. **Do not proceed.**

The path stops here until you have a verdict.

---

## IGNORE until the gate (anti-roaming)

- API · dashboard · database · Docker · optimizer
- Layers 1, 2, 4, 5 · the Daily Brief
- Rebuilding media / options legs
- Writing more planning docs (planning is done)
- Re-doing hardening (already done)

**Rules:** one branch · small commits · tests green · no new deps without a reason.

---

_Lost? [INDEX.md](INDEX.md) maps every doc. Reference (don't live in these): [layer3_current_state.md](layer3_current_state.md) for the why · [mirror_vision_roadmap.md](mirror_vision_roadmap.md) for the whole-project map._
