# ADR 0001 — Watchlist event foundation

| | |
|---|---|
| **Status** | Proposed (awaiting owner review) |
| **Date** | 2026-09-23 |
| **Baseline** | `main` @ `e068c917fb244ca59b459d78b78a4dd1d7f41bd6` (2026-06-21) |
| **Product brief** | [../PRODUCT.md](../PRODUCT.md) |
| **Active task** | [../FOCUS.md](../FOCUS.md) |

## Evidence labels used in this document

| Label | Meaning |
|---|---|
| **[code]** | Observed in the repository at the baseline commit (path:line given) |
| **[run]** | Observed command output on 2026-09-23 (Windows 11, Python 3.13.5, repo `.venv`) |
| **[local]** | Observed in the owner's local, git-ignored `data/` / `results/` files. **Not reproducible from a clean clone.** |
| **[src]** | Stated by an external primary source (linked) as read on 2026-09-23 |
| **[inf]** | This ADR's inference or design choice |
| **[unv]** | Unverified. Must be confirmed before anything depends on it |

---

## 1. Context

MIRROR's active goal changes from *"prove the insider signal predicts returns"* to a **personal, source-linked watchlist research assistant for India and US stocks** (see [PRODUCT.md](../PRODUCT.md)). The daily research product is **not gated on an insider information-coefficient result**.

What exists today:

- **[code]** A US-only insider (SEC Form 4) scoring pipeline in `src/`: fetcher → parser → enrichment → 7 registered scorers → CSV ([src/pipeline/run_scoring_pipeline.py](../../src/pipeline/run_scoring_pipeline.py)).
- **[code]** A legacy dissonance prototype in `legacy/` over 10 US mega-caps ([legacy/price_signal.py:8-9](../../legacy/price_signal.py)).
- **[code]** No security master, no India coverage, no database, no event model, no price-move computation, no brief.
- **[run]** `python -m pytest tests/ -v` → **31 passed, 2 warnings, exit 0**. The tests cover the insider parser, enrichment and scorers only.
- **[run]** GitHub Actions CI fails at its first step (`pyflakes`) on `main` at the baseline, so pytest does not run in CI (fixed by Milestone 0, §13).

None of the existing code produces the product. The insider code is an experimental **research track** (§12). Its known defects do not block the product slice.

## 2. Decision summary

1. Build **one vertical slice**: watchlist → dated official company event → adjusted daily move → evidence-labelled explanation → next-morning Markdown brief. It is delivered as **four milestones after a CI repair milestone**, committed directly to `main` in small commits (§13). It is tested on fixtures and then run on a real 10–20 stock India/US watchlist. A **time-saving pilot** starts only for markets whose event coverage is measurable. For India, that waits on the source investigation (§4.3); until then, manual entry is a **data-model prototype**, not evidence of time saved.
2. It is a **modular Python package inside `src/`**, driven by a CLI. Storage is a single **SQLite** file (stdlib `sqlite3`). There are no services, queues, Redis, UI or LLM in the first slice.
3. **Point-in-time provenance is part of the schema from day one.** Every fact carries event time, publication time, and MIRROR first-seen time. Derived numbers carry a calculation version.
4. **All numbers are deterministic.** An LLM, if added later, may only phrase text around numbers that were already computed. It never produces a price, return or financial figure.
5. **Sources are chosen by confirmed permission, not by availability.** US disclosures come automatically from SEC EDGAR, which documents free reuse. India disclosures start as **manual entry**. NSE's website terms prohibit systematic automated collection. Whether NSE's RSS feeds or a paid NSE data subscription permit MIRROR's use is **unresolved, not impossible**. A time-bounded source investigation (§4.3) must settle it before any India time-saving pilot. Prices come in through a **file import that records provenance** (§5.1) until a price source with confirmed permission is chosen.
6. **Explanations are labelled, never probabilistic.** There are five evidence labels (§8). "No verified explanation yet" is used **only** when coverage was complete. Otherwise the card says coverage was incomplete. No causal percentages.
7. **Coverage is explicit.** For each security, source and window, the brief shows one of four states: *checked, no events* · *not checked* · *source failed* · *coverage incomplete* (§4.4). Silence never means "nothing happened".

## 3. Module layout and data flow

```
                  (automatic)                      (manual, file-based)
  SEC EDGAR submissions API      India event CSV      price CSV     corporate-action CSV
            │                    (user-entered from    (any vendor,   (user-entered or
            │                     NSE filings)          one schema)    from filings)
            ▼                            ▼                   ▼               ▼
  ┌───────────────────────── src/sources/  (adapters: fetch/import → normalized records) ─┐
  │  sec_submissions.py      manual_events.py      prices_csv.py     corporate_actions.py │
  └───────────────────────────────────────┬────────────────────────────────────────────────┘
                                          ▼  write-once, versioned, first_seen_at stamped
                          src/store/  (schema.sql + db.py, SQLite)
                                          │  as-of reads only
                     ┌────────────────────┼─────────────────────┐
                     ▼                    ▼                     ▼
           src/compute/moves.py   src/compute/timing.py   src/explain/evidence.py
           adjusted return,       event vs session        label assignment
           abnormal volume,       window classification   (deterministic rules)
           benchmark-relative
                     └────────────────────┬─────────────────────┘
                                          ▼
                          src/brief/render_markdown.py  → briefs/YYYY-MM-DD.md
                                          ▲
                          src/cli.py  (ingest | compute | brief | feedback | thesis)
```

| Part | Status | Notes |
|---|---|---|
| `src/parsers/universe.py` ticker→CIK resolution from `data/company_tickers.json` | **Existing, reused** | **[code]** Used by the SEC adapter for US identity. `data/company_tickers.json` is tracked in git. |
| `src/parsers/sec_filings_fetcher.py` request pattern (User-Agent header, `timeout=30`, 0.5 s sleep) | **Existing, pattern reused** | **[code]** [sec_filings_fetcher.py:15-49,111](../../src/parsers/sec_filings_fetcher.py). The new adapter must keep `acceptanceDateTime`, which the current fetcher drops (it keeps `filingDate` only, line 59). |
| `defusedxml`, `requests`, `pandas` | **Existing dependencies** | No new packages. `tzdata` (needed by `zoneinfo` on Windows) is already installed as a pandas dependency **[run]**. |
| `src/core`, `src/sources`, `src/store`, `src/compute`, `src/explain`, `src/brief`, `src/cli.py` | **New** | Plain modules, stdlib + pandas. |
| `src/scoring/*`, `src/enrichment/*`, `insider_parser_v2.py`, `legacy/*` | **Experimental, not used by the product** | Research track, §12. Not imported by the product modules. |
| Macro (FRED), news, LLM wording, intraday alerts, NSE automation | **Deferred** | Section 4 gives the reasons. |

## 4. Source adapters and ingestion

### 4.1 Source feasibility (as of 2026-09-23)

| Source | What is confirmed | Delivery | Permission status | First-slice use |
|---|---|---|---|---|
| **SEC EDGAR submissions API** (`data.sec.gov/submissions/CIK##########.json`) | No auth or API key; submissions updated with "typical processing delay of less than a second"; nightly bulk `submissions.zip` **[src]** [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces). Max 10 requests/second; declare a User-Agent **[src]** [SEC webmaster FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions). JSON exposes `acceptanceDateTime`, `filingDate`, `reportDate`, `form`, `items`, `primaryDocument` **[run]** (one request for CIK 0000320193). | JSON over HTTPS | "EDGAR public filing content are free to access and reuse" **[src]** (webmaster FAQ) | **Yes, automatic.** Forms 8-K, 10-Q, 10-K, 4 for watched CIKs. |
| **SEC Form 4 transaction codes** | P = open market or private purchase; S = open market or private sale; F = "payment of exercise price or tax liability by delivering or withholding securities…" **[src]** [SEC ownership form codes](https://www.sec.gov/edgar/searchedgar/ownershipformcodes.html) | — | — | Used to correct the insider track (§12). |
| **NSE corporate announcements / financial results / corporate actions** | Pages load (HTTP 200) **[run]**. They link RSS feeds `Online_announcements.xml`, `Financial_Results.xml`, `Corporate_action.xml` on `nsearchives.nseindia.com` **[run]**. An RSS item has `title` (company **name**, not symbol), `link` (PDF or XBRL), `description` (subject), and a `pubDate` such as `23-Sep-2026 16:29:40` **with no timezone** **[run]**. | HTML pages, RSS XML, PDF/XBRL attachments | **Unresolved for MIRROR's use. Scraping the website is excluded.**<br>• *Website terms:* "User is prohibited to conduct any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting)"; content may not be "reproduced … stored … distributed … without prior written permission of NSE" **[src]** [NSE terms of use](https://www.nseindia.com/static/nse-terms-of-use).<br>• *RSS:* NSE invites users to "subscribe to our RSS feeds" in a feed reader or "any online aggregator of your choice" **[src]** [NSE RSS feeds](https://www.nseindia.com/static/rss-feed). This does **not** establish that a custom program may poll the feeds and store their items. It also does not establish that it may not **[unv]**.<br>• *Paid route:* NSE Data & Analytics lists "Corporate Data" among its data products **[src]** [NSE Data & Analytics](https://www.nseindia.com/static/nse-data-and-analytics). NSE's Data Usage and Sharing Policy defines Market Data to include "corporate data which may be transmitted to the Subscribers". Subscribers apply by order form and sign a "Relevant Agreement" covering intended use **[src]** [NSE Data Usage and Sharing Policy](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE_DataUsageandSharingPolicy.pdf) (§6.1–6.2, definition (e)). NSE lists an [end-of-day corporate announcement subscription](https://www.nseindia.com/static/market-data/corporate-data-subscription) delivered via SFTP after 20:00 IST at an advertised domestic fee of ₹500,000 per year (page updated 11 June 2026) **[src]**. Whether an individual is eligible and whether the agreement permits MIRROR's intended storage or output remain **[unv]**.<br>• *Research provisions:* the website disclaimer restricts free research-oriented data to "individuals from accredited academic institutions, recognized research organizations and think tanks" **[src]** [NSE disclaimer](https://www.nseindia.com/static/nse-disclaimer). The policy's "Non Commercial Users" definition includes "Researchers, Students etc." with committee-approved pricing **[src]** (policy §10.2, definition (g)). Neither text establishes whether the owner is eligible **[unv]**. | **Manual entry for the prototype.** The owner enters events (URL, subject, publication time) and records a manual coverage check (§4.4). MIRROR does not poll, fetch RSS or download PDFs until §4.3 records a permission. |
| **BSE** announcements | Not checked | — | **[unv]** | Candidate in §4.3. |
| **Licensed India feed** (broker API, vendor) | Not evaluated | — | **[unv]** | Candidate in §4.3. |
| **FRED API** | Requests need an API key **[src]** [FRED API keys](https://fred.stlouisfed.org/docs/api/api_key.html). ALFRED vintages and `series/vintagedates` support point-in-time macro values **[src]** [FRED API](https://fred.stlouisfed.org/docs/api/fred/). Must display "This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis"; series may be third-party copyrighted **[src]** [FRED API terms](https://fred.stlouisfed.org/docs/api/terms_of_use.html). | JSON over HTTPS | Personal use appears allowed under the terms with attribution. Per-series copyright must still be checked **[inf]**. | **Deferred** to slice 2 (US macro). India macro sources are **[unv]**. |
| **Prices via `yfinance`** (already a dependency) | "not affiliated, endorsed, or vetted by Yahoo … intended for research and educational purposes"; "the Yahoo! finance API is intended for personal use only" **[src]** [yfinance on PyPI](https://pypi.org/project/yfinance/). Yahoo's own terms were not read **[unv]**. | Unofficial HTTP client | **Unresolved.** Possibly acceptable for a personal, non-redistributed pilot. Not acceptable for any shared output **[inf]**. | Optional producer of the price CSV on the owner's machine. MIRROR's core reads only the CSV schema, so the vendor can be swapped. |
| **NSE daily price archives** (bhavcopy) | Archive pages are linked from the NSE pages above **[run]**. File format not inspected **[unv]**. | Downloadable files | The website terms prohibit systematic automated collection **[src]**. Whether manual download plus local parsing for personal use is permitted is **[unv]**. | Candidate in §4.3 and Q2. |
| **News** | Not evaluated | — | **[unv]** | Deferred. News never counts as a "documented event" (§8). |

### 4.2 Ingestion rules (all adapters)

- **Idempotency.** Each adapter maps a record to a natural key: SEC accession number; manual event `(security, source_url, published_at)`; price import `file_sha256`, then price row `(security, trade_date, import_id)`; coverage check `(security, source, window, checked_at)`. Re-ingesting the same content is a no-op. `source_document` is unique on `(source, source_doc_key, content_sha256)`.
- **Versioning, not overwrite.** If the content hash changes for the same key (amended filing, revised bar), MIRROR inserts a **new version** and keeps the old one. Reads choose the newest version with `first_seen_at ≤ as_of`.
- **Deduplication.** `event.dedup_key = sha256(security_id | event_type | source | source_doc_key)`. An 8-K and its exhibit are one event. The same NSE announcement entered twice is one event.
- **Retries.** At most 3 attempts per HTTP request, with exponential backoff (1 s, 2 s, 4 s) on 429/5xx/timeout. No retry on 4xx other than 429. The SEC adapter keeps a global cap below 10 requests/second (it reuses the existing 0.5 s sleep) and sends the declared User-Agent.
- **Outages.** Each run writes an `ingest_run` row per source: `started_at, finished_at, status (ok | partial | failed), records_new, error`. Each per-security result writes a `coverage_check` row (§4.4). The brief header shows each source's **last successful fetch time**. A failed source is displayed as failed. It is never shown as "no events".
- **Backfill.** The SEC adapter can backfill a date range from the submissions JSON. Backfilled records get `first_seen_at` = the backfill time (the truth), and `availability_basis = 'publisher_timestamp'` (§5).
- **Freshness.** Price staleness is computed against the exchange calendar (§7). Every brief item shows its data-as-of time.

### 4.3 India source investigation (time-bounded; decides India automation)

This is a research task, not code. Its output is **ADR 0002: India disclosure and price sourcing**.

- **Questions to answer, with primary evidence (written replies or published terms):**
  1. Does NSE permit a personal, non-redistributing program to poll its RSS feeds and store item metadata and links? The answer must come from NSE in writing or from published terms that address it.
  2. NSE lists an end-of-day corporate-announcement product (SFTP, after 8:00 PM IST, ₹500,000 per year domestic; §4.1). Is an individual, non-redistributing subscriber eligible? What do its agreement terms allow MIRROR to store and display? Does it cover results and corporate actions as well as announcements?
  3. What do the BSE announcement feeds and their terms offer? This source is not yet checked.
  4. Do broker or third-party APIs the owner already has access to carry exchange announcements under terms that permit this use?
  5. What does each option cost, relative to the time manual entry costs? Measure the manual cost during the prototype.
- **Timebox:** the investigation concludes **before Milestone 4 ships** (§13). If a question is still open then, ADR 0002 records it as *unresolved*. India stays a prototype: its output keeps showing its computed coverage state (§4.4), and it is excluded from time-saving measurements.
- **Allowed outcomes:** automate via a permitted route (a new adapter milestone); keep manual entry and accept its labelled coverage; or drop India from the pilot. Scraping pages is not an allowed outcome while the current website terms stand.

### 4.4 Coverage states

A brief must never present "nothing entered" as "nothing happened". Every `(security, required source, window)` resolves to exactly one state:

| State | Rule | Brief shows |
|---|---|---|
| `checked_no_events` | A `coverage_check` with `status = ok` covers the **whole** window, and no events for the security fall in it | "Checked <source> through <time>: no new disclosures" |
| `not_checked` | No `coverage_check` overlaps the window | "**Not checked:** <source> has no check since <last time>" |
| `source_failed` | The latest check attempt covering the window has `status = failed` | "**Source failed:** <source> at <time>; last success <time>" |
| `coverage_incomplete` | Checks cover only part of the window, or a check has `status = partial` with a `scope_note` (for example "results page only") | "**Coverage incomplete:** <source> checked <from>–<to>, or <scope note>" |

- **Required sources per market:** US → `SEC_EDGAR`; India → `NSE`, via `MANUAL_NSE` until ADR 0002 says otherwise.
- **Windows:** "What changed" uses `(previous brief as_of, this brief as_of]`. A move card uses the move window from §5.
- **SEC checks** are written automatically by the adapter: `ok` after a successful fetch for that CIK, `failed` after retries are exhausted.
- **Manual NSE checks** are written only when the owner runs `python -m src.cli checked NSE <symbol> --through <time>`. Entering an event does **not** imply that the rest of the window was checked.
- **Brief grouping:** the "Nothing new" line is replaced by four groups: *Checked, no new disclosures* / *Not checked* / *Source failed* / *Coverage incomplete*. Only securities whose required sources are all `checked_no_events` appear in the first group.

## 5. Point-in-time provenance

Every fact stores these timestamps, all as UTC in storage and shown in the exchange's timezone in output:

| Field | Meaning | US example | India example |
|---|---|---|---|
| `event_time` | When the underlying thing happened | Form 4 `transactionDate`; 10-Q `reportDate` | Board meeting date; record date |
| `published_at` | When the source made it public | SEC `acceptanceDateTime` **[run]**. Whether its `Z` suffix is true UTC is **[unv]**; Milestone 2 checks it against the EDGAR filing index page. | NSE dissemination time as entered by the user. RSS `pubDate` has no timezone **[run]**, so IST is an **[inf]** assumption and the event is flagged `tz_assumed=1` |
| `published_basis` | `source_timestamp` / `source_date_only` / `user_entered` | `source_timestamp` | `user_entered` |
| `first_seen_at` | When MIRROR first stored it | ingestion clock | ingestion clock |
| `price observation` | `trade_date` + session close in exchange tz + the `price_import` it came from (§5.1) | | |
| `url`, `content_sha256`, `version` | Where it came from and exactly what was read | | |
| `calc_version` | For derived rows: `git describe` + hash of parameters used | | |

**As-of rule.** A query evaluated at time `T` sees a record only if it was knowable at `T`:

- *Live mode* (the daily brief): `first_seen_at ≤ T`.
- *Replay mode* (historical evaluation over backfilled data): `published_at ≤ T` **and** `published_basis = 'source_timestamp'`. Records with only a date, or with an assumed timezone, count as knowable at the *end* of that date in the exchange timezone, which is the conservative choice. Output from replay mode is always marked "reconstructed from publisher timestamps".
- Nothing with `first_seen_at > T` (live) or `published_at > T` (replay) may be presented as then-known. This is a test in Milestone 2 (§10, case R1).

**Catalyst timing versus a move.** Session `D` with previous session `D-1`. The window is `(close(D-1), close(D)]` in exchange time.

| Timing tag | Rule | What the card may say |
|---|---|---|
| `before_window` | `published_at ≤ close(D-1)` | "Disclosed before the move" |
| `pre_open` | `close(D-1) < published_at < open(D)` | "Disclosed before the session opened" |
| `during_session` | `open(D) ≤ published_at ≤ close(D)` | "Disclosed during the session; order relative to the price move is unknown without intraday data" |
| `after_close` | `published_at > close(D)` | "Reported after the move; it cannot have been available before it". It may still *describe* the cause, for example a company clarification |

Session open and close times come from config per exchange. The values themselves (NSE 09:15–15:30 IST, NYSE/Nasdaq 09:30–16:00 ET) are **[unv]** here. Milestone 1 cites the exchange source in the config file.

### 5.1 Claim provenance: filing claims versus price claims

The brief makes two kinds of claims, and each needs a different provenance gate. An owner-supplied price CSV usually has no URL and no publication time, so the filing gate cannot apply to it.

| Claim type | Examples | Required on every such line | If missing |
|---|---|---|---|
| **Filing claim** | "Results disclosed pre-open", an 8-K subject, a corporate-action announcement | Source link (`url`), `published_at` with its `published_basis`, `first_seen_at` | The claim is not shown as evidence. The event is listed as "incomplete record" and the coverage state for that window becomes `coverage_incomplete` |
| **Price claim** | Adjusted move, market-relative move, volume ratio, "price as of" | **Import identity:** `price_import.import_id`, the file name, and the declared vendor or `unknown`. **File hash:** `file_sha256`. **Observation time:** `imported_at`, plus the vendor's own as-of time if the file has one. **Calculation trace:** the input `price_bar` and `corporate_action` rows, and `calc_version` | The number is not shown. The card says "price data missing provenance" |

- **Unknown upstream source.** If the file does not declare an upstream vendor or URL, the card shows it explicitly: "Upstream price source: **unknown** (owner-supplied file `<name>`, sha256 `<first 12 hex>`, imported `<time>`)". A price claim from an unknown upstream source is **reproducible** (hash plus trace) but **not attributable**. The brief must say so and never imply otherwise.
- **The trace is rendered** as a compact line under the card (format only; the numbers are illustrative): "close 1,234.50 (D) vs 1,180.00 (D-1) ÷ k=1 · import #7 · calc v0.1+abc123". A reader can then recompute every number from the stored rows.

## 6. Minimum data model (SQLite)

```sql
security(
  security_id INTEGER PRIMARY KEY,
  market TEXT CHECK (market IN ('IN','US')),
  exchange TEXT NOT NULL,              -- 'NSE' | 'NYSE' | 'NASDAQ'
  company_id_type TEXT NOT NULL,       -- 'CIK' (US) | 'NSE_SYMBOL' (IN, until an issuer id is chosen)
  company_id TEXT NOT NULL,
  isin TEXT,                           -- recommended for IN, optional for US
  name TEXT NOT NULL,
  currency TEXT NOT NULL,              -- 'INR' | 'USD'
  timezone TEXT NOT NULL,              -- 'Asia/Kolkata' | 'America/New_York'
  benchmark_security_id INTEGER REFERENCES security,
  UNIQUE (company_id_type, company_id, exchange)
);
security_symbol(                       -- symbol changes: never rename in place
  security_id INTEGER REFERENCES security,
  exchange TEXT, symbol TEXT, valid_from DATE, valid_to DATE,
  UNIQUE (exchange, symbol, valid_from)
);
watchlist_item(
  item_id INTEGER PRIMARY KEY,
  security_id INTEGER UNIQUE REFERENCES security,
  thesis TEXT, horizon TEXT,           -- free text + e.g. '2-3 years'
  move_trigger_pct REAL,               -- NULL = use global setting
  added_at TEXT, updated_at TEXT, active INTEGER DEFAULT 1
);
source_document(
  doc_id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,                -- 'SEC_EDGAR' | 'MANUAL_NSE' | 'PRICE_CSV' ...
  source_doc_key TEXT NOT NULL,        -- accession no. | URL
  url TEXT, content_sha256 TEXT NOT NULL, version INTEGER NOT NULL,
  published_at TEXT, published_basis TEXT NOT NULL, tz_assumed INTEGER DEFAULT 0,
  first_seen_at TEXT NOT NULL, raw_path TEXT,
  UNIQUE (source, source_doc_key, content_sha256)
);
event(
  event_id INTEGER PRIMARY KEY,
  security_id INTEGER REFERENCES security, doc_id INTEGER REFERENCES source_document,
  event_type TEXT NOT NULL,            -- 'results' | 'board_outcome' | 'corporate_action' | '8k_item' | 'insider_form4' | 'other_disclosure'
  subject TEXT NOT NULL,               -- verbatim from source, never paraphrased
  event_time TEXT, published_at TEXT, first_seen_at TEXT NOT NULL,
  fields_json TEXT,                    -- deterministic structured fields only
  dedup_key TEXT NOT NULL UNIQUE
);
price_import(                          -- one row per imported file (§5.1)
  import_id INTEGER PRIMARY KEY,
  file_name TEXT NOT NULL, file_sha256 TEXT NOT NULL UNIQUE,
  declared_vendor TEXT NOT NULL DEFAULT 'unknown',
  declared_source_url TEXT,            -- NULL = upstream source unknown
  vendor_as_of TEXT,                   -- vendor's own timestamp if the file has one
  imported_at TEXT NOT NULL, row_count INTEGER NOT NULL
);
price_bar(
  security_id INTEGER REFERENCES security, trade_date DATE,
  import_id INTEGER NOT NULL REFERENCES price_import,
  open REAL, high REAL, low REAL, close_raw REAL NOT NULL, volume REAL,
  close_vendor_adj REAL,               -- kept only for cross-checking; never the basis of a move
  UNIQUE (security_id, trade_date, import_id)   -- newest import with imported_at ≤ as_of wins
);
coverage_check(                        -- §4.4; one row per (security, source) check attempt
  check_id INTEGER PRIMARY KEY,
  security_id INTEGER REFERENCES security,
  source TEXT NOT NULL,                -- 'SEC_EDGAR' | 'MANUAL_NSE' | ...
  method TEXT NOT NULL,                -- 'api' | 'manual'
  window_start TEXT NOT NULL, window_end TEXT NOT NULL,   -- span the check covers
  checked_at TEXT NOT NULL,
  status TEXT NOT NULL,                -- 'ok' | 'partial' | 'failed'
  scope_note TEXT, error TEXT,
  run_id INTEGER REFERENCES ingest_run
);
corporate_action(
  action_id INTEGER PRIMARY KEY, security_id INTEGER REFERENCES security,
  action_type TEXT,                    -- 'split' | 'bonus' | 'dividend' | 'symbol_change' | 'rights'
  ex_date DATE NOT NULL, new_per_old REAL, cash_amount REAL, currency TEXT,
  doc_id INTEGER REFERENCES source_document, first_seen_at TEXT NOT NULL,
  UNIQUE (security_id, action_type, ex_date)
);
explanation(
  explanation_id INTEGER PRIMARY KEY, security_id INTEGER REFERENCES security,
  session_date DATE, as_of TEXT, calc_version TEXT,
  move_pct REAL, relative_move_pct REAL, volume_ratio REAL,
  evidence_label TEXT NOT NULL, coverage_json TEXT,   -- §4.4 state per required source
  missing_json TEXT, flags_json TEXT,
  UNIQUE (security_id, session_date, as_of, calc_version)
);
explanation_evidence(
  explanation_id INTEGER REFERENCES explanation, event_id INTEGER REFERENCES event,
  timing_tag TEXT NOT NULL, role TEXT NOT NULL,   -- 'documented' | 'competing' | 'context'
  PRIMARY KEY (explanation_id, event_id)
);
feedback(
  feedback_id INTEGER PRIMARY KEY, created_at TEXT NOT NULL,
  target_type TEXT, target_id INTEGER,  -- 'event' | 'explanation' | 'watchlist_item'
  kind TEXT NOT NULL,                   -- 'relevant' | 'not_relevant' | 'wrong_attribution' | 'missed_event' | 'thesis_update'
  note TEXT, old_value TEXT, new_value TEXT
);
ingest_run(run_id INTEGER PRIMARY KEY, source TEXT, started_at TEXT, finished_at TEXT,
           status TEXT, records_new INTEGER, error TEXT);
```

India and US do **not** share one filing rulebook. `event_type` is a small common vocabulary. The market-specific detail (8-K item numbers, NSE subject line, Form 4 code) stays in `fields_json` and `subject`.

**Milestone 1 amendment (2026-09-23, as built in [src/store/schema.sql](../../src/store/schema.sql)).** Three changes to the draft above; the schema file is now the reference.
- **Stable key.** `security` is keyed by a MIRROR-assigned `security_key` (unique, never changed), not by `UNIQUE (company_id_type, company_id, exchange)`. One SEC CIK can cover several listed share classes on the same exchange: 1,449 of 7,992 CIKs in the tracked `data/company_tickers.json` map to more than one ticker, e.g. GOOGL and GOOG both map to CIK 1652044 **[run]**. So the draft key would have collided. The CIK stays as `company_id` because SEC ingestion needs it.
- **India identifier (Q6, provisional).** No issuer-level identifier is used yet. The NSE symbol lives only in `security_symbol`. The ISIN, if given, is stored as an attribute, validated for format and ISO 6166 check digit, and not used as a key. MIRROR does not rely on any external identifier staying stable across corporate actions **[inf]**. ADR 0002 may revisit this.
- **Symbol history semantics.** Periods are half-open `[valid_from, valid_to)`. `valid_from` is the first day the owner asserts the mapping, not necessarily the listing date. A period can be closed once (`valid_to` set) but never moved or reassigned. Overlaps are rejected per security and per `(exchange, symbol)`, and the whole watchlist load rolls back ([src/store/db.py](../../src/store/db.py)).
- **Also added:** `created_at`/`updated_at` on `security`, `active` on `watchlist_item` (a security dropped from the watchlist file is deactivated, not deleted), and `PRAGMA user_version = 1` as the schema version. Thesis or horizon edits from the watchlist file update the item and append a `feedback` row (`thesis_update`) with the old and new values.

**Why SQLite.** There is a single user and a single writer, and the data is small (a 20-stock watchlist). It is stdlib with no server, the whole database is one file that can be backed up or attached to a bug report, and WAL mode allows readers during a write. **[inf]**

**Concrete triggers to consider PostgreSQL** (any one):
1. A second person needs to write to the same data from another machine.
2. A scheduled ingester and an interactive writer run concurrently and `SQLITE_BUSY` errors persist after WAL + `busy_timeout`.
3. The system needs hosting as a service.

Row count alone is not a trigger.

## 7. Deterministic computation

All functions are pure, take an explicit `as_of`, and write `calc_version`. The parameters below are **product settings, not validated market thresholds**.

- **Adjusted previous-close return.** `r_D = close_raw(D) / (close_raw(D-1) / k_D) − 1`. Here `k_D` is the product of `new_per_old` for every split/bonus with `ex_date = D`. For a bonus of *a* for every *b* held, `k = (a+b)/b`. For a 2-for-1 split, `k = 2`. MIRROR computes adjustments from its own `corporate_action` rows so that every number can be reproduced. A vendor-adjusted close, if present, is a cross-check only: a mismatch beyond 0.5% sets flag `adjustment_mismatch` and shows both values.
- **Dividends.** Not adjusted in the price return (this is a price return, not a total return). If a dividend goes ex on `D`, the card says so with the amount as a competing factor.
- **Unrecorded corporate action guard.** If `|r_D| ≥ 30%` and `close(D-1)/close(D)` is within 2% of a common ratio (1.5, 2, 3, 4, 5, 10), set flag `possible_unrecorded_corporate_action`. The card is **held** as "check corporate actions" and is not presented as a real move.
- **Abnormal volume.** `volume_ratio = volume(D) / median(volume over the prior 20 sessions)`, with prior volumes multiplied by the cumulative `k` of any action in between. With fewer than 10 prior sessions the output is `insufficient_history`, not a number.
- **Benchmark-relative move.** `relative_move = r_D − r_benchmark,D`, using the configured benchmark (for example a broad index or sector index per security) and the same adjustment rules. This is labelled "market-relative", **not** "abnormal return": no factor model is claimed. The benchmark price source is under the same open question as prices (Q2).
- **Financial changes (slice 2+).** Only from structured values (SEC XBRL company facts for US **[src]** SEC EDGAR APIs; India from XBRL attachments or manual entry). YoY/QoQ are computed only when period type, unit and consolidation basis match. Otherwise the output is "not comparable". Never from PDF prose via an LLM.
- **Move trigger.** A card is produced when `|r_D| ≥ trigger`. `trigger` comes from `watchlist_item.move_trigger_pct`, else the global setting (the owner chooses it; the example config ships `5.0`). Optionally a card is also produced when `volume_ratio ≥` a configured value.
- **Calendar and edge cases.**
  - *Holiday*: the exchange holiday file (config, one per exchange, source cited) says the market was closed, so no bar is expected and nothing is flagged.
  - *Stale or missing price*: a session is expected but no bar exists. The card shows "price as of <last date>" and marks the item `stale`. No move is computed and no value is carried forward.
  - *Halted or suspended*: a session is expected, and the bar is missing or has zero volume while the benchmark traded. Flag `no_trade_possible_suspension` **[unv cause]**. No move is computed.
  - *Price bands (India)*: band data has no confirmed source **[unv]**. The first slice does not claim a band hit. Later, if a permitted band source exists, flag `at_band_limit`.
  - *Symbol change*: `security_symbol` gains a new row. The price history stays attached to `security_id`.
  - *Special sessions* (built in Milestone 1): trading on a normally closed day is a `special` session in the holiday file, for example NSE's Sunday 2026-02-01 Budget session. If its timings are not yet published (NSE Muhurat 2026-11-08), `open`/`close` are unknown and timing tags for that day must say so.
  - *Uncovered years*: [src/core/calendar.py](../../src/core/calendar.py) raises `CalendarNotCovered` for a year with no holiday list, rather than treating it as holiday-free. NSE and Nasdaq are configured for 2026 only, NYSE for 2026–2028. Each new year must be added from the exchange's publication before the pilot crosses into it.

## 8. Explanation contract

Every unusual-move card has these sections, in this order:

0. **Coverage banner** (shown first, and only when needed). **Coverage is complete** when every required source (§4.4) has an `ok` check spanning the move window. If coverage is not complete, the card opens with a banner such as "⚠ COVERAGE INCOMPLETE: NSE not checked since <time>" or "⚠ SEC EDGAR failed at <time>", **whatever the label**.
1. **Observed facts.** Adjusted move, market-relative move, volume ratio, and price provenance per §5.1: import, file hash, observation time, calculation trace, and the upstream vendor or "unknown".
2. **Evidence.** Official events for the security with their `timing_tag`, `published_at`, `first_seen_at` and a link. Subjects are quoted verbatim from the source.
3. **Evidence label.** Exactly one of:

| Label | Deterministic rule (first slice) |
|---|---|
| `documented_event` | ≥1 official event with `timing_tag ∈ {before_window, pre_open, during_session}` whose `event_type` is in the material set (results, board outcome, corporate action, 8-K item). Wording: "A documented event preceded or coincided with the move." It is **not** "caused". |
| `multiple_factors` | A `documented_event` exists **and** another competing factor applies: `|relative_move| < trigger` while `|r_D| ≥ trigger` (the stock largely moved with its benchmark), a dividend ex-date, or ≥2 material events. |
| `plausible_association` | Only non-official or ambiguous evidence, for example an event in the `other_disclosure` type, or later news. Not produced by the first slice except for `other_disclosure`. |
| `no_verified_explanation_yet` | No qualifying official event up to `as_of`, **and coverage is complete** for the move window. The card lists each source checked and the time it was checked through. |
| `no_evidence_coverage_incomplete` | No qualifying official event was found, **but** at least one required source is `not_checked`, `source_failed` or `coverage_incomplete` for the move window. Wording: "No explanation found — but <source> was not checked / failed / only partly checked for this window." It must never be rendered as, or grouped with, `no_verified_explanation_yet`. |

4. **Competing factors.** Benchmark move, dividend, corporate-action flags, stale-data flags.
5. **Thesis relevance.** Shows the saved thesis and horizon next to the evidence. In the first slice the relevance judgement is the **owner's**, recorded through `feedback` (`thesis_update`). A later automated suggestion defaults to "unresolved" and must cite the specific evidence it relies on.
6. **Missing information.** For example: "No intraday prices: order of disclosure vs move unknown"; "NSE covered only by manual entry"; "No news source connected".

An event reported after the close is shown under "Reported after the move" and never raises the label. A news article published near a move is never treated as proof of cause. No card shows a probability or confidence percentage unless a validated model produced it, and none exists.

## 9. Daily workflow and delivery

- **Cadence.** One next-morning run covers the latest completed session of each market. NSE session `D` and the US session `D`, which closes during the Indian night, are both complete before an Indian morning run **[inf]**, subject to the session times in config.
- **Run.** `python -m src.cli ingest && python -m src.cli compute && python -m src.cli brief`. The steps are: fetch SEC for watched CIKs, import `data/manual_events.csv`, `data/prices/*.csv` and `data/corporate_actions.csv`, compute, and render `briefs/YYYY-MM-DD.md`.
- **Brief layout.**
  1. Header: the as-of time and per-source freshness/failures.
  2. "What changed": new official events per watched stock since the last brief.
  3. Unusual-move cards.
  4. The four coverage groups from §4.4: *Checked, no new disclosures* · *Not checked* · *Source failed* · *Coverage incomplete*. There is no undifferentiated "Nothing new" line.
- **Manual coverage.** After reviewing NSE for a stock, the owner runs `python -m src.cli checked NSE <symbol> --through <time> [--partial --note ...]`. Until they do, that stock is shown as *Not checked* for NSE.
- **Pilot, in two parts.**
  - (a) **US utility pilot**: 10–20 stocks the owner follows, for at least 4 weeks **[inf]**, once Milestone 4 ships. SEC coverage is then measured automatically.
  - (b) **India** runs as a **data-model prototype** with manual entry. It gets counted toward time-saving only after ADR 0002 establishes a source whose coverage can be measured without relying on the owner's own entry. Manual-entry time is recorded either way (see PRODUCT.md).
- **Feedback.** `python -m src.cli feedback <target> relevant|not_relevant|wrong_attribution [--note]`, `feedback missed --symbol X --url U`, and `thesis set <symbol> --text ... --horizon ...`. All of these are appended to `feedback`, never overwritten.
- **Intraday alerts.** Not built. They would require a dependable price feed whose permission is confirmed, and none has been identified.

## 10. Release checks and acceptance

**Checks every release must pass** (automated in `tests/` unless marked manual):

- **Filing-claim provenance.** Every filing claim has `url`, `published_at` with `published_basis`, and `first_seen_at` (§5.1). A test fails on any missing value.
- **Price-claim provenance.** Every price-derived number has an `import_id`, file hash, observation time and calculation trace (§5.1). An unknown upstream source is shown as "unknown". A test fails if a price number renders without all four.
- **Number reproducibility.** Every number in the brief is recomputed from stored rows by the test suite and matches exactly.
- **Duplicate suppression.** Ingesting the same fixtures twice produces identical row counts.
- **Coverage honesty.** Every watched security appears in exactly one of the four coverage groups for each required source (§4.4). No security appears as *Checked, no new disclosures* without an `ok` check spanning the window.
- **Error and freshness visibility.** A failed source appears as failed in the brief header and in the *Source failed* group. It is never silently empty.
- **Negative cases.** A large move with no qualifying evidence produces `no_verified_explanation_yet` with complete coverage, or `no_evidence_coverage_incomplete` with the banner. It never produces a guessed cause.
- **Historical replay.** Replay at time `T` uses only records knowable at `T` under the §5 rule.
- **Separation.** Product-usefulness checks (these, plus pilot feedback in PRODUCT.md) are separate from any signal-return backtest. Passing these checks says nothing about returns.

**Acceptance matrix** (fixtures are synthetic but shaped like the real sources; no live network in tests):

| # | Milestone | Case | Fixture | Expected |
|---|---|---|---|---|
| **C1** | Milestone 2 | **Not checked** (India) | Watched NSE security; no `coverage_check` row for `MANUAL_NSE` in the window; no events | Coverage state `not_checked`. Listed under *Not checked*, **not** under *Checked, no new disclosures* |
| **C2** | Milestone 2 | **Checked, no events** (India) | Same security; `checked NSE <symbol> --through <window end>` recorded (`ok`, spans the window); no events | State `checked_no_events`. Listed under *Checked, no new disclosures* with "checked through <time>" |
| C3 | Milestone 2 | Coverage incomplete | Manual check through the middle of the window only, **or** a check with `--partial --note "results page only"` | State `coverage_incomplete`, showing the covered span or the note |
| C4 | Milestone 2 | Event entered, no check | One manual NSE event entered in the window; no `coverage_check` | The event is shown under "What changed", but NSE coverage stays `not_checked`. Entering an event does not imply a check |
| C5 | Milestone 2 | US checked, no events | SEC fixture fetch succeeds for the CIK; no new filings in the window | Automatic `ok` check. State `checked_no_events` |
| A1 | Milestone 4 | Verified pre-open result (India) | Manual NSE results event, `published_at` 08:40 IST on `D`; NSE check `ok` through `close(D)`; `+8%` move on `D`; trigger 5 | Card with `documented_event`, tag `pre_open`, verbatim subject, link; no coverage banner |
| A2 | Milestone 4 | Post-move news or filing | US 8-K with `acceptanceDateTime` after the close on `D`; SEC check `ok`; `+11%` move on `D` | Event listed under "Reported after the move". Label `no_verified_explanation_yet` |
| A3 | Milestone 3 | Split or bonus day | 1:1 bonus (`new_per_old = 2`) ex on `D`; raw close halves, adjusted move `+1%` | No card (below trigger), and no −50% anywhere. The same fixture without the action row raises `possible_unrecorded_corporate_action` and holds the card |
| A4 | Milestone 4 | Unexplained +10%, full coverage (US) | `+10%` move, benchmark `+0.3%`, no events, SEC check `ok` spanning the window | `no_verified_explanation_yet`; sources checked and their times listed; no causal wording; no banner |
| **A4b** | Milestone 4 | Unexplained +10%, **incomplete coverage** (India) | `+10%` move, no events, **no** NSE check for the window | `no_evidence_coverage_incomplete`, with the banner "⚠ COVERAGE INCOMPLETE: NSE not checked…" as the card's first line. Never `no_verified_explanation_yet` |
| A5 | Milestone 3 | Stale or missing price | Calendar expects `D`; last bar is `D-1` | Item marked `stale`, "price as of D-1", no move computed |
| A6 | Milestone 2 (state) / Milestone 4 (render) | Source outage | SEC adapter returns HTTP 503 ×3 | `ingest_run.status = failed`; `coverage_check.status = failed`; the security is listed under *Source failed*; the header shows "SEC EDGAR: failed at <time>, last success <time>"; the brief still renders |
| **P1** | Milestone 3 | Price file with unknown upstream | CSV with no vendor or URL declared | Card shows "Upstream price source: unknown (owner-supplied file …, sha256 …, imported …)" plus the calculation trace. The move is shown |
| P2 | Milestone 3 | Price number without provenance | A `price_bar` row whose `import_id` is missing or doesn't resolve (fixture forces it) | Rendering refuses the number: "price data missing provenance". The test asserts no bare number appears |
| R1 | Milestone 2 | As-of leakage guard | Event with `first_seen_at` = `D+1 09:00`; brief generated as of `D+1 08:00` | Event absent from that brief |
| R2 | Milestone 4 | Market-wide move | Stock `+6%`, benchmark `+5.5%`, results event pre-open, coverage complete | `multiple_factors` |

## 11. Alternatives considered

| Alternative | Why not now |
|---|---|
| Keep "IC first, product later" (the old FOCUS gate) | The product's value (coverage, attribution, time saved) does not depend on the insider score predicting returns. Gating on it would stall the useful part. |
| Scrape NSE pages | Prohibited by the NSE website terms **[src]**. |
| Poll NSE RSS now | Permission for a custom program to poll and store the feeds is **unresolved** (§4.1). It is not ruled out, but it is not assumed. Settled in §4.3 / ADR 0002 before any India time-saving pilot. The event model is unchanged if it is allowed. |
| Buy an NSE corporate-data subscription now | The end-of-day product and its advertised price (₹500,000 per year domestic) are **[src]** (§4.1). Individual eligibility and permitted use under the agreement are **[unv]**. This is evaluated in §4.3 against the manual-entry cost measured in the prototype. |
| Pick a price vendor now | There is no confirmed permission for any candidate **[unv]**. A file-schema adapter makes the choice reversible and keeps tests offline. |
| PostgreSQL / queue / microservices | One user, one writer, a 20-stock watchlist. No requirement needs them. See §6 triggers. |
| LLM-written explanations in slice 1 | Deterministic labels are enough to test usefulness, and an LLM adds a fabrication risk the product must guard against. It can be added later, bounded to phrasing. |
| Vendor-adjusted prices as the basis | Not reproducible or auditable. Adjustments are computed from recorded actions instead and the vendor value is used as a cross-check. |
| Extend the legacy dissonance pipeline | It uses a `now()`-relative window ([legacy/dissonance_calculator.py:59](../../legacy/dissonance_calculator.py)) and 10 hard-coded tickers, and its orchestrator calls a file not in the repo (§12). It is not a foundation. |

## 12. Separate track: insider-signal research blockers

These block **any claim about the insider score**. They do **not** block the product slice, which does not use the score. Existing scores in `results/insider_signals_phase2.csv` are **unvalidated research output** and must not be shown as product signals.

B1 and B2 were reproduced offline with the script in [Appendix A](#appendix-a--blocker-reproduction-script) **[run]**. Its cases double as the fixtures for T2 and T3 below.

| ID | Blocker | Evidence | Status |
|---|---|---|---|
| **B1** | **Direction applied after aggregation. It is worse than "a penalty can invert a sale".** `conviction_score` is already signed (negative for SELL) [conviction.py:56-59](../../src/scoring/conviction.py). `aggregate()` adds it to unsigned quality scores and signed penalties [aggregator.py:106-123](../../src/scoring/aggregator.py). The pipeline then negates the whole aggregate for SELL [run_scoring_pipeline.py:61-65](../../src/pipeline/run_scoring_pipeline.py). Effects for sells: (a) a larger fraction sold makes the final signal **less** bearish (100% → −0.120 vs 5% → −0.405); (b) 10b5-1 and routine penalties push sells **toward bullish**, not toward zero, and can flip them positive (+0.376). For buys the penalties push toward bearish, not toward zero. | **[code] + [run]**. Also **[local]**: 965 of 7,552 SELL rows in `results/insider_signals_phase2.csv` have a positive final signal. | Confirmed |
| **B2** | **Cluster look-ahead.** The window is `date ± 10 days` [cluster.py:81-89](../../src/scoring/cluster.py), so later transactions raise the score of earlier ones (0.10 → 0.65 above). It also keys on transaction date, not filing date, so co-insider trades not yet *filed* are treated as known. | **[code] + [run]** | Confirmed |
| **B3** | **Current market context on historical trades.** `enrich_market_context` fetches today's `info['marketCap']` and the last 30 days of history once per ticker and broadcasts them to every row, regardless of transaction date [enrich_market_context.py:28-42,93-96](../../src/enrichment/enrich_market_context.py). **[local]**: every ticker has exactly one `market_cap` value in the output, across trades dated 2015-11-15 to 2026-06-12. | **[code] + [local]** | Confirmed |
| **B4** | **Form 4 code F counted as SELL.** `SELL_CODES = {'S', 'F'}` [insider_parser_v2.py:51-52](../../src/parsers/insider_parser_v2.py). SEC defines F as tax/exercise-price withholding, distinct from S **[src]**. **[local]**: 3,894 of 7,552 SELL rows (52%) are code F. The same code sets are also applied to derivative-table rows (`is_derivative=True`). | **[code] + [src] + [local]** | Confirmed |
| **B5** | **Rebuilt engine does not drive the legacy brief, and universes do not overlap.** No legacy module reads `insider_signals_phase2.csv` or `conviction_signal`. The only readers are `src/pipeline` and `scripts/` **[run: grep]**. The legacy insider leg thresholds raw net dollar value over the last 30 days relative to `pd.Timestamp.now()` [dissonance_calculator.py:34-86](../../legacy/dissonance_calculator.py). **[local]**: the legacy news/price files cover 10 mega-caps and the insider file 111 small/mid-caps, with **zero** overlap. | **[code] + [local]** | Confirmed |
| B6 | Legacy orchestrator runs `SEC_INSIDER.PY` and bare `dissonance_calculator.py` [legacy/run_mirror.py:8-13](../../legacy/run_mirror.py). `SEC_INSIDER.PY` is not tracked in the repo. | **[code]** | Confirmed that the file is absent; the run itself was not attempted |
| B7 | `insider_parser_v2.py`'s `__main__` demo imports `enrich_ownership` and `scoring.aggregator` by pre-reorg paths [insider_parser_v2.py:392-393](../../src/parsers/insider_parser_v2.py). This probably raises `ModuleNotFoundError` after the CSV is written. | **[code]**; not run (needs network) | Likely |

**Follow-up tasks, in priority order.** Each is one small PR with its proving test.

1. **T1 (B4).** Treat F as its own type (for example `TAX_WITHHOLD`) and exclude it from SELL scoring. Fixture: a minimal Form 4 XML with one `F` row and one `S` row. Test: `F → not SELL`, `S → SELL`. Rerun counts are reported, not asserted.
2. **T2 (B1).** Define the semantics (magnitude is unsigned and built from unsigned quality scores; penalties *shrink* magnitude; direction is applied once) and fix the code. Fixtures: the five sale rows above. Tests: (a) monotonic, so for a SELL, raising `pct_holdings_transacted` with everything else fixed never makes the signal less bearish; (b) no sign flip, so penalties never change the sign of a SELL or BUY; (c) symmetry between a BUY and a SELL with identical features.
3. **T3 (B2).** Add an `as_of` rule to the cluster scorer: count only co-transactions **filed** at or before the scored row's filing time. Fixture: A (3/1), B (3/8), C (3/10). Test: score(A as of A's filing) = 0.10.
4. **T4 (B3).** Point-in-time market context: market cap from shares outstanding as of the filing times the close on the transaction date, and ADV from the 30 sessions before the transaction. If unavailable, return `None`, never a current value. Fixture: a fake price source keyed by date. Test: the enrichment never reads data dated after the row's date.
5. **T5.** Knowable time for any backtest is `acceptanceDateTime`/`filing_date`, not `date`. Test: a replay excludes rows filed after `T`.
6. **T6 (B6, B7).** Fix or delete dead entry points. Test: an import smoke test for each `__main__` module.
7. **T7.** Only after T1–T5: the reproducible backtester and IC from the old FOCUS (now in the research track). B5 stays documented; no rewiring into any product surface until a validated result exists.

## 13. Implementation plan: reviewable milestones

Work directly on `main` in small commits, checking CI after each milestone. Keep the existing 31 tests passing, add no packages, and make no network calls in tests. Milestones 1–4 do not change `src/scoring`, `src/enrichment`, `src/parsers/insider_parser_v2.py` or `legacy/`. Milestone 0 touches existing files for lint only, with no behavior change. Every acceptance case in §10 is a named test for the milestone shown in its column.

**Milestone 0 — CI repair (lint only).** CI has been red on `main` since `e068c91`: `pyflakes src/ tests/` fails on existing code (unused imports, f-strings without placeholders), so the pytest and pip-audit steps have never run in CI **[run: GitHub Actions runs 27905872952 and 35853057284]**.
- *Change:* remove the flagged unused imports and placeholder-free `f` prefixes, plus one unused local variable (`this_insider`, [cluster.py:71](../../src/scoring/cluster.py)). Removing that variable does not change any score. The package's `src/scoring/__init__.py` imports trigger `@register_scorer`; **keep those imports** and expose the names in `__all__`. The test imports `src.scoring.aggregator`, which already initializes that package; its duplicate scorer imports may be removed. Pyflakes 4.0.0 ignores `# noqa` but treats names in `__all__` as used **[run: pyflakes 4.0.0 in a scratch venv]**. `pyflakes src/ tests/` reports 44 findings at the baseline **[run]**.
- *Must not:* remove or skip the pyflakes step, or change any scoring output.
- *Pass:* CI green on `main`, **including the pytest and pip-audit steps actually running**, with results recorded in the milestone notes. If `pip-audit --strict` then fails, report it and fix it in a follow-up commit; do not disable it.
- *Finding when pip-audit first ran (2026-09-23):* `pip-audit --strict` failed on **PYSEC-2026-3740** (CVE-2026-81726, GHSA-8mgp-746c-j5xp) in `nltk 3.10.3`. `textblob` pulls it in, and no fixed release exists **[run]**. `textblob` is imported only by `legacy/news_sentiment.py` and the root `NEWS_SENTIMENT.PY` **[code]**. *Resolution:* `textblob` moved from `requirements.txt` to a new `requirements-legacy.txt`, so the CI and security-scan environments no longer install `nltk`. The audit is not suppressed. After the split, a fresh venv with CI's install command passed pyflakes, pytest (31 passed) and `pip-audit --strict` ("No known vulnerabilities found") **[run]**. Running legacy code now needs `pip install -r requirements-legacy.txt`, which still carries the advisory.

**Milestone 1 — Store, identity, calendar config.**
- *Files:* `src/store/schema.sql` (all §6 tables), `src/store/db.py` (WAL, `busy_timeout`, idempotent upserts, as-of readers), `src/core/identity.py`, `src/core/calendar.py`, `config/watchlist.example.yaml`, `config/exchanges.yaml` and `config/holidays/{NSE,NYSE,NASDAQ}.csv` (each citing its primary source, which closes Q4), `tests/test_store_identity.py`, `tests/test_calendar.py`.
- *Pass:* loading a 1 NSE + 1 US watchlist twice gives identical rows; a symbol change adds a `security_symbol` row without moving history; the calendar returns expected sessions for fixture dates, with holidays excluded.

**Milestone 2 — Event foundation and coverage.**
- *Files:* `src/sources/sec_submissions.py` (keeps `acceptanceDateTime`; retries; writes `ingest_run` and `coverage_check`), `src/sources/manual_events.py`, `src/core/coverage.py` (§4.4 states), a `src/cli.py` with `ingest`, `checked` and `events` (a plain-text listing of events and coverage states; no Markdown brief yet), `tests/fixtures/sec/*.json`, `tests/fixtures/manual_events.csv`, `tests/test_events.py`, `tests/test_coverage.py`, `tests/test_asof.py`.
- *Cases:* **C1–C5**, **R1**, A6 (state part), duplicate and versioning tests. Q3 (the `acceptanceDateTime` timezone) is checked against an EDGAR filing index page and recorded in the fixture's README.
- *Pass:* the cases above pass, and `python -m src.cli events --as-of …` against fixtures prints each security with its coverage state.

**Milestone 3 — Prices, corporate actions, moves.**
- *Files:* `src/sources/prices_csv.py` (writes `price_import` with a file hash), `src/sources/corporate_actions.py`, `src/compute/moves.py`, `tests/fixtures/prices/*.csv`, `tests/test_moves.py`, `tests/test_price_provenance.py`.
- *Cases:* **A3**, **A5**, **P1**, **P2**, and the unrecorded-action guard.
- *Pass:* every computed number is recomputed in tests from stored rows, and every result carries its `import_id` and `calc_version`.

**Milestone 4 — Timing, evidence labels, brief, feedback.**
- *Files:* `src/compute/timing.py`, `src/explain/evidence.py`, `src/brief/render_markdown.py`, the `compute`, `brief`, `feedback` and `thesis` CLI commands, `tests/test_timing.py`, `tests/test_evidence.py`, `tests/test_brief_render.py`.
- *Cases:* **A1**, **A2**, **A4**, **A4b**, **R2**, A6 (render part), and a golden-file test of a full brief built from fixtures.
- *Pass:* the cases and golden test pass. One manual run on the owner's real watchlist renders a brief. The run notes record what was observed: counts per coverage group, any provenance failures, and the upstream price source shown. This demonstrates that the pipeline works on real data. **It is not evidence of time saved.**

**After Milestone 4:** the US utility pilot can start (§9). India stays a prototype until ADR 0002 (§4.3), which must be concluded, even if as "unresolved", before Milestone 4 ships.

## 14. Open questions

| # | Question | Blocks | Resolved in |
|---|---|---|---|
| Q1 | Which India disclosure route is permitted for MIRROR's use: NSE RSS polling (needs written confirmation), an NSE Data & Analytics corporate-data subscription, BSE, a broker API, or none? What does each cost? | Any India time-saving pilot; India automation | §4.3 → ADR 0002, before Milestone 4 ships |
| Q2 | Which daily price source (India and US, including benchmarks) has terms that permit this use? | Naming an upstream source in cards (until then it shows as "unknown"); any shared output | Before the US pilot, if possible; otherwise cards say "unknown" |
| Q3 | Is SEC `acceptanceDateTime` with `Z` actually UTC? | Exact timing tags for US events near session boundaries | Milestone 2 |
| Q4 | Exchange session times and holiday lists: which primary sources? | `calendar.py` config | **Resolved in Milestone 1:** NSE market-timings page and circulars NSE/CMTR/71775, 72260, 72349; NYSE hours-calendars page; Nasdaq holiday pages. All cited in [config/exchanges.yaml](../../config/exchanges.yaml) |
| Q5 | India macro sources (RBI, MOSPI) and their terms | Macro in slice 2 | Later |
| Q6 | Which issuer identifier to use for India (ISIN vs exchange symbol vs company registration number)? | Robust symbol-change handling in India | **Provisional (Milestone 1):** MIRROR `security_key` plus NSE symbol history; ISIN as a validated attribute, not a key (§6 amendment). Revisit in ADR 0002 |

## 15. Consequences

- The event and move foundation can be built and tested without waiting on the insider IC. A **time-saving** claim waits for measurable coverage.
- India coverage starts **manual and explicitly labelled**: *not checked* until the owner records a check, and never counted as time saved while it relies on manual entry. Automating India is an open sourcing decision with a deadline, not a settled impossibility.
- Price numbers are always reproducible (hash plus trace). They are attributable to an upstream source only when that source is declared.
- The insider work continues only as a clearly labelled research track with a concrete fix list. Its outputs are not product features.
- Earlier planning documents remain in the repository as dated research direction; see [../INDEX.md](../INDEX.md).

---

## Appendix A — blocker reproduction script

Save the script as `repro_blockers.py` anywhere and run `PYTHONPATH=. python path/to/repro_blockers.py` from the repo root at the baseline commit. It needs no network access and no local data.

```python
"""Reproduce candidate insider-signal blockers against the current code, without network."""
import warnings; warnings.simplefilter("ignore")
import pandas as pd
from src.scoring.aggregator import aggregate, explain, load_config
from src.scoring import cluster

cfg = load_config('config/scoring.yaml')

def final(row):
    # Same expression as src/pipeline/run_scoring_pipeline.py:61-65
    m = aggregate(row, cfg)
    return m, (m if row['transaction_type'] == 'BUY' else -m)

cluster.set_transactions_context(pd.DataFrame())  # isolate: cluster -> 0.10 baseline

base = dict(ticker='XYZ', date='2024-03-01', insider_name='A', title='Chief Executive Officer',
            market_cap=1e9, avg_30d_dollar_volume=1e7, is_company=False)

print("B1: direction applied after aggregate()")
cases = {
  'SELL 50% of holdings, 10b5-1 plan, routine': dict(transaction_type='SELL', pct_holdings_transacted=0.5, dollar_value=-5e6, is_10b51_plan=True,  is_routine_insider=True),
  'SELL 50% of holdings, opportunistic':        dict(transaction_type='SELL', pct_holdings_transacted=0.5, dollar_value=-5e6, is_10b51_plan=False, is_routine_insider=False),
  'SELL 100% of holdings, opportunistic':       dict(transaction_type='SELL', pct_holdings_transacted=1.0, dollar_value=-5e6, is_10b51_plan=False, is_routine_insider=False),
  'SELL 5% of holdings, opportunistic':         dict(transaction_type='SELL', pct_holdings_transacted=0.05, dollar_value=-5e6, is_10b51_plan=False, is_routine_insider=False),
  'SELL tiny, plan+routine, mega-cap context':  dict(transaction_type='SELL', pct_holdings_transacted=0.01, dollar_value=-1e3, is_10b51_plan=True, is_routine_insider=True, title='', market_cap=1e12, avg_30d_dollar_volume=1e10),
  'BUY 50% of holdings, 10b5-1 plan, routine':  dict(transaction_type='BUY',  pct_holdings_transacted=0.5, dollar_value=5e6,  is_10b51_plan=True,  is_routine_insider=True),
}
for name, extra in cases.items():
    r = {**base, **extra}
    m, f = final(r)
    c = explain(r, cfg)['contributions']
    print(f"  {name:45s} aggregate={m:+.3f} final={f:+.3f}  conviction_contrib={c['conviction_score']['contribution']:+.3f}")

print("\nB2: cluster window uses transactions AFTER the scored one")
ctx = pd.DataFrame([
    dict(ticker='XYZ', transaction_type='BUY', date='2024-03-01', insider_name='A'),
    dict(ticker='XYZ', transaction_type='BUY', date='2024-03-08', insider_name='B'),
    dict(ticker='XYZ', transaction_type='BUY', date='2024-03-10', insider_name='C'),
])
cluster.set_transactions_context(ctx)
print("  score for A on 2024-03-01 with B,C trading 7-9 days later:", cluster.score_cluster(dict(ticker='XYZ', transaction_type='BUY', date='2024-03-01', insider_name='A')))
cluster.set_transactions_context(ctx.iloc[:1])
print("  score for A with only information up to 2024-03-01:        ", cluster.score_cluster(dict(ticker='XYZ', transaction_type='BUY', date='2024-03-01', insider_name='A')))
```

Output on 2026-09-23 (Python 3.13.5, repo `.venv`):

```
B1: direction applied after aggregate()
  SELL 50% of holdings, 10b5-1 plan, routine    aggregate=-0.075 final=+0.075  conviction_contrib=-0.045
  SELL 50% of holdings, opportunistic           aggregate=+0.270 final=-0.270  conviction_contrib=-0.150
  SELL 100% of holdings, opportunistic          aggregate=+0.120 final=-0.120  conviction_contrib=-0.300
  SELL 5% of holdings, opportunistic            aggregate=+0.405 final=-0.405  conviction_contrib=-0.015
  SELL tiny, plan+routine, mega-cap context     aggregate=-0.376 final=+0.376  conviction_contrib=-0.001
  BUY 50% of holdings, 10b5-1 plan, routine     aggregate=+0.015 final=+0.015  conviction_contrib=+0.045

B2: cluster window uses transactions AFTER the scored one
  score for A on 2024-03-01 with B,C trading 7-9 days later: 0.65
  score for A with only information up to 2024-03-01:         0.1
```
