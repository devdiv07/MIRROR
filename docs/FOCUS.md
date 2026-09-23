# FOCUS — the one file to follow

**Open this when you sit down. One active outcome, one active task. Everything else waits.**
_Last set: 2026-09-23. It replaces the June 21, 2026 focus ("get one real IC number"); that text is in git history at `e068c91`._

---

## THE ACTIVE OUTCOME

> The owner reads **one next-morning Markdown brief** for a **real 10–20 stock India/US watchlist**. It shows:
> - **filing claims**, each with a source link and a publication time;
> - **price numbers**, each with its import, file hash and calculation trace;
> - a **coverage state** for every stock and source: checked with events found, checked with no events, not checked, source failed, or coverage incomplete;
> - for any stock that crossed its move trigger, an **adjusted daily move** and an **evidence-labelled explanation**.

Why this outcome: [PRODUCT.md](PRODUCT.md). How it is built: [adr/0001-watchlist-event-foundation.md](adr/0001-watchlist-event-foundation.md).

This outcome proves that the pipeline works on real data. It does **not** prove time saved. That is measured afterwards, and only where coverage is measurable (Step 6).

The product **does not wait for an insider IC result**. The insider score is a separate research track (see below). Its output never appears in the brief.

---

## THE SLICE (in order; the first unchecked step is the active task)

Work directly on `main` in small commits. Check CI and the named ADR cases after each milestone (ADR §13).

### Step 0 — make CI green _(done 2026-09-23)_
- [x] Fix the 44 existing pyflakes findings without changing behaviour. Keep the scorer-registration imports (list them in `__all__`; pyflakes ignores `# noqa`). Do not remove or skip the lint step.
- **Done when:** CI on `main` is green **and** its pytest and pip-audit steps actually ran, with their results recorded here.
- **Result:** lint fixes in `589eaed`. The first `pip-audit --strict` run then failed on PYSEC-2026-3740 in `nltk` (via `textblob`; no fixed release). `0f95961` moved `textblob` to `requirements-legacy.txt` (ADR §13, Milestone 0). CI on `63cf01e` ([run 35858038008](https://github.com/devdiv07/MIRROR/actions/runs/35858038008)): pyflakes clean · pytest **31 passed** · pip-audit **"No known vulnerabilities found"**. The weekly *Security Scan* workflow, which GitHub had disabled for inactivity, was re-enabled on 2026-09-23; its manual run [35859075728](https://github.com/devdiv07/MIRROR/actions/runs/35859075728) on `adcd9f2` passed both jobs (pip-audit clean; gitleaks: no leaks).

### Step 1 — put the architecture baseline on `main` _(done 2026-09-23)_
- [x] Commit PRODUCT.md, this focus file, INDEX.md, the ADR and README directly to `main`; close the superseded draft PR.
- **Done when:** the docs are on `main`, the draft PR is closed, and CI is green.
- **Result:** docs in `63cf01e`; draft PR #1 closed as superseded; CI green on that commit.

### Step 2 — store: store, identity, calendar config _(done 2026-09-23)_
- [x] `src/store/schema.sql` + `db.py` (ADR §6, including `price_import` and `coverage_check`), `src/core/identity.py`, `src/core/calendar.py`, `config/watchlist.example.yaml`, `config/exchanges.yaml`, holiday files that cite their primary sources
- **Done when:** loading a 1 NSE + 1 US watchlist twice gives identical rows, symbol-change and calendar tests pass, and CI is green.
- **Result:** `f8cc7e6` (calendar), `5ba71d7` (store + identity), `d3898bc` (ADR §6 amendment; Q4 resolved, Q6 provisional). CI on `d3898bc` ([run 35860281919](https://github.com/devdiv07/MIRROR/actions/runs/35860281919)): pyflakes clean · pytest **77 passed** (31 existing + 46 new) · pip-audit clean. Deviation from the ADR draft: securities are keyed by a MIRROR `security_key` because one CIK can cover several share classes (ADR §6 amendment). Calendar coverage: NSE and Nasdaq 2026 only, NYSE 2026–2028. Before 2027, add NSE's and Nasdaq's 2027 lists from their publications.

### Step 3 — events: event foundation and coverage _(done 2026-09-23)_
- [x] SEC submissions adapter (keeps `acceptanceDateTime`; fixture-tested, no network), manual NSE events, the `checked` CLI command, the coverage states, and a plain-text `events` listing
- **Done when:** ADR cases **C1** (not checked) and **C2** (checked, no events) pass, along with C3–C7 (incl. checked-with-events and a shared-CIK/two-listing fixture), **V1** (event revision read at two times), **B1** (backfill only `ok` when every needed SEC file was fetched), **R1** (as-of guard), A6 (failure state), and the duplicate-ingest tests.
- **Result:** contracts fixed first in `7cf134d` (fifth state `checked_with_events`; event versions with an as-of rule; SEC backfill coverage). `e2e2771` rejects NaN/infinite move triggers. `1917d63` is schema v2 (versioned events/documents). `9493792` adds the SEC adapter, manual NSE events, coverage states and the CLI. `bce14c2` updates the docs. CI on `bce14c2` ([run 35863687190](https://github.com/devdiv07/MIRROR/actions/runs/35863687190)): pyflakes clean · pytest **122 passed** · pip-audit clean. All tests are offline. The adapter has not yet been run against live SEC data; the first real `ingest` on the owner's watchlist is the next manual check.

### Step 4 — prices: prices, corporate actions, moves _(ACTIVE)_
- [ ] Price CSV import with `price_import` provenance, corporate actions, `src/compute/moves.py`
- **Done when:** ADR cases **A3** (split/bonus), **A5** (stale price), **P1** (unknown upstream shown as unknown), **P2** (no bare numbers) and the unrecorded-action guard pass.

### Step 5 — brief: timing, evidence labels, brief, feedback
- [ ] `timing.py`, `evidence.py`, `render_markdown.py`, and the `compute`, `brief`, `feedback` and `thesis` CLI commands
- [ ] **Gate before shipping:** ADR 0002 (India sourcing, ADR §4.3) is written, even if its answer is "unresolved". The NSE correspondence can run during Steps 2–4, because it is mostly waiting on replies.
- **Done when:** ADR cases **A1**, **A2**, **A4**, **A4b** (unexplained move with incomplete coverage shows the banner), **R2** and A6 (render) pass. A golden brief test passes. One manual run on the real watchlist is recorded in the run notes: counts per coverage group, provenance failures, and the upstream price source shown.

### Step 6 — Pilot _(4+ weeks)_
- [ ] **US:** use the brief daily and record feedback and time spent through the CLI
- [ ] **India:** keep running it as a prototype. It joins the time-saving measurement only after ADR 0002 establishes a route whose coverage is measurable without relying on the owner's own entry.
- **Done when:** the pilot measures in [PRODUCT.md](PRODUCT.md#pilot-and-measurable-feedback) have a week-1 baseline and a week-4 reading. Report them as measured. No time saving is claimed without them.

---

## DO NOT START (until Step 5 is complete)

- Web UI · API · Docker · PostgreSQL · queues · deployment
- Scraping NSE/BSE pages. Polling NSE RSS or buying a feed only after ADR 0002 records permission and cost.
- Choosing or paying for a price or news vendor (ADR open questions Q1/Q2 first)
- LLM-written explanations or any LLM-produced number
- Macro, news, intraday alerts
- Layers 1, 2, 4, 5 of the original vision

## Parked research track — insider signal

This track does not run in parallel with the slice. When it resumes, it starts with the **verified defects** in [ADR §12](adr/0001-watchlist-event-foundation.md#12-separate-track-insider-signal-research-blockers): code F counted as SELL, a direction/penalty sign error, cluster look-ahead, and current market cap on historical trades. The fixes come in the order T1–T6 listed there. Only then does it move to the reproducible backtester and IC (T7). Existing scores are unvalidated and must not be relabelled as signals.

**Rules:** one active task · small commits on `main` · check CI after every milestone · no new dependencies without a written reason · no claim without evidence.

---

_Lost? [INDEX.md](INDEX.md) maps every doc._
