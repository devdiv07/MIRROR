# Run note: first live SEC ingest (Step 3 hardening)

**When:** 2026-09-23, 18:43–18:45 UTC. **Code:** `440c2c0` for runs 1–4; run 5 used the boundary fix, committed unchanged as `91eac7d`.
**Watchlist:** a temporary one-entry watchlist (`US:NASDAQ:AAPL`, CIK 320193), kept outside the repository with its scratch databases. No personal watchlist was used.
**Contact:** `SEC_USER_AGENT` was loaded from the local, git-ignored `.env` into the process. Its value was never printed or logged.
**Traffic:** 22 SEC requests in total: 6 by `ingest`, 1 to read Apple's file list, and 15 link and index checks. Each was at least 0.5 s after the previous one.

## What was run and what came back

| # | Database | Command | Result |
|---|---|---|---|
| 1 | A | `ingest --sec-since 2026-06-01T00:00:00Z` | `ok`. 1 submissions fetch and 12 events (9 Form 4, 2 8-K incl. one 8-K/A, 1 10-Q). Cutoff 18:43:09Z; `checked_at` and `first_seen_at` 18:43:10Z |
| 2 | A | `ingest` (ordinary) | `ok`. Window started at run 1's cutoff (18:43:09Z). 0 new versions |
| 3 | A | `ingest --sec-since 2026-06-01T00:00:00Z` again | `ok`. All 12 filings were seen again: **0 new versions**, 12 events, 12 documents, 12 distinct dedup keys, max version 1 |
| 4 | B | `ingest --sec-since 2010-01-01T00:00:00Z` | 2 requests (submissions + `CIK0000320193-submissions-001.json`). 1,188 events (959 Form 4, 161 8-K, 68 10-Q/10-K) in 1.8 s. **`partial`: not covered 2015-07-26T04:00Z..2015-07-28T04:00Z.** This was a defect; see below |
| check | A | 12 filing URLs fetched | **12/12 returned HTTP 200** with a document body (Form 4 renderings under `xslF345X0n/`, 8-K, 10-Q) |
| check | A | EDGAR filing-index "Accepted" time vs stored `published_at` for a Form 4, an 8-K and the 10-Q | **3/3 match** (e.g. 10-Q accepted 2026-07-31 06:01:02 ET = stored 10:01:02Z) |
| 5 | B | `ingest` (ordinary, after the fix) | Resumed at the gap (2015-07-26T04:00Z) and came back `ok`. The older file was not needed and not fetched. 0 new versions. `resume_point` is now that run's cutoff |

The as-of checks behaved as specified. As of run 4's `checked_at`, the window (2015-07-20, 2015-08-01] was `coverage_incomplete`. As of run 5's, it was `checked_with_events` (6 events). The whole window (2010-01-01, 18:45:09Z] was `checked_with_events` with 1,188 events. In every database: `first_seen_at ≥` the run cutoff and `≥ published_at`, `checked_at ≥ window_end`, every event was `source_timestamp`, and every URL was under `/Archives/edgar/data/320193/`.

## Defect found and fixed

Apple's submissions JSON lists one older file covering 1994-01-26..**2015-07-25**, and `recent` starts at **2015-07-27** (1,000 filings). The rule "recent covers from the day after its oldest `filingDate`" left 2015-07-26..27 (ET) uncovered, although no filing can exist there outside `recent`. Before this step's fixes, the gap would have been skipped silently. After `440c2c0`, every ordinary run would have restarted at it and re-fetched the 1,249-filing file for ever. `91eac7d` fixes this: `recent` covers from the day after the **earlier** of its oldest `filingDate` and the newest file's `filingTo`. It has a test built on the same boundary.

## Observed, not changed

- `events` without `--as-of` ends its window at "now", which is always a few seconds after the last SEC cutoff. So right after an ingest it shows SEC as **coverage incomplete** ("checked only … to <cutoff>"). This is honest but noisy. The Step 5 brief should end each window at the last cutoff, or say how old the SEC data is, rather than inherit this default.
- The CLI resolves `config/exchanges.yaml` relative to the working directory, so it must be run from the repository root (or be given `--exchanges`).
- The same contact email is still hard-coded as a fallback in the parked insider parsers (`src/parsers/`), and it remains in git history.
