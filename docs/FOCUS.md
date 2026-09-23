# FOCUS — the one file to follow

**Open this when you sit down. One active outcome, one active task. Everything else waits.**
_Last set: 2026-09-23. It replaces the June 21, 2026 focus ("get one real IC number"); that text is in git history at `e068c91`._

---

## THE ACTIVE OUTCOME

> The owner reads **one next-morning Markdown brief** for a **real 10–20 stock India/US watchlist**. Every line in it has a source link and a timestamp. For any stock that crossed its move trigger, it gives an **adjusted daily move** and an **evidence-labelled explanation**.

Why this outcome: [PRODUCT.md](PRODUCT.md). How it is built: [adr/0001-watchlist-event-foundation.md](adr/0001-watchlist-event-foundation.md).

The product **does not wait for an insider IC result**. The insider score is a separate research track (see below). Its output never appears in the brief.

---

## THE SLICE (in order; the first unchecked step is the active task)

### Step 0 — Architecture baseline _(open as a draft PR; not merged)_
- [ ] PRODUCT.md, ADR 0001, this file, INDEX.md and README.md describe the real code state and the new direction
- **Done when:** the PR has been reviewed and merged by the owner.

### Step 1 — Store + identity + watchlist
- [ ] **First, make CI green.** It has failed at `pyflakes` on `main` since `e068c91`, so pytest never runs in CI. Separate lint-only PR, no behaviour change, and do not remove the lint step.
- [ ] `src/store/schema.sql` + `db.py` (ADR §6), `src/core/identity.py`, `config/watchlist.example.yaml`
- [ ] `src/core/calendar.py` + `config/exchanges.yaml` + holiday files, each citing its primary source
- **Done when:** loading a watchlist of 1 NSE and 1 US security twice gives identical rows, and a test proves it.

### Step 2 — Events with provenance
- [ ] `src/sources/sec_submissions.py`, which keeps `acceptanceDateTime`, tested on a recorded JSON fixture (no network in tests)
- [ ] `src/sources/manual_events.py` for owner-entered NSE disclosures
- **Done when:** re-ingesting a fixture is a no-op (duplicate test), a changed hash creates version 2, and the as-of guard (ADR case R1) passes.

### Step 3 — Prices, actions, moves
- [ ] `src/sources/prices_csv.py`, `src/sources/corporate_actions.py`, `src/compute/moves.py`
- **Done when:** ADR acceptance cases **A3** (split/bonus), **A5** (stale price) and the unrecorded-action guard pass. Every number is recomputed in tests.

### Step 4 — Timing + evidence labels
- [ ] `src/compute/timing.py`, `src/explain/evidence.py`
- **Done when:** ADR cases **A1** (pre-open result), **A2** (post-move filing), **A4** (unexplained +10%) and **R2** (market-wide move) pass.

### Step 5 — Brief + feedback
- [ ] `src/brief/render_markdown.py`, `src/cli.py` (ingest / compute / brief / feedback / thesis)
- **Done when:** ADR case **A6** (source outage visible) passes, and one manual run on the real watchlist produces a brief in which every line has a working link and timestamps. The owner records what was observed in the PR.

Steps 1–5 together are the **first implementation PR** (ADR §13). Split them if review gets heavy, but never merge a step without its tests.

### Step 6 — Pilot _(4+ weeks)_
- [ ] Use the brief daily and record feedback through the CLI
- **Done when:** the pilot measures in [PRODUCT.md](PRODUCT.md#pilot-and-measurable-feedback) have a week-1 baseline and a week-4 reading.

---

## DO NOT START (until Step 5 is merged)

- Web UI · API · Docker · PostgreSQL · queues · deployment
- NSE/BSE scraping or polling (their terms prohibit it; see ADR §4)
- Choosing or paying for a price or news vendor (ADR open questions Q1/Q2 first)
- LLM-written explanations or any LLM-produced number
- Macro, news, intraday alerts
- Layers 1, 2, 4, 5 of the original vision

## Parked research track — insider signal

This track does not run in parallel with the slice. When it resumes, it starts with the **verified defects** in [ADR §12](adr/0001-watchlist-event-foundation.md#12-separate-track-insider-signal-research-blockers): code F counted as SELL, a direction/penalty sign error, cluster look-ahead, and current market cap on historical trades. The fixes come in the order T1–T6 listed there. Only then does it move to the reproducible backtester and IC (T7). Existing scores are unvalidated and must not be relabelled as signals.

**Rules:** one active task · one branch · small commits · tests green · no new dependencies without a written reason · no claim without evidence.

---

_Lost? [INDEX.md](INDEX.md) maps every doc._
