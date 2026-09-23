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

None of the existing code produces the product. The insider code is an experimental **research track** (§12). Its known defects do not block the product slice.

## 2. Decision summary

1. Build **one vertical slice**: watchlist → dated official company event → adjusted daily move → evidence-labelled explanation → next-morning Markdown brief. It runs on a real 10–20 stock India/US watchlist.
2. It is a **modular Python package inside `src/`**, driven by a CLI. Storage is a single **SQLite** file (stdlib `sqlite3`). There are no services, queues, Redis, UI or LLM in the first slice.
3. **Point-in-time provenance is part of the schema from day one.** Every fact carries event time, publication time, and MIRROR first-seen time. Derived numbers carry a calculation version.
4. **All numbers are deterministic.** An LLM, if added later, may only phrase text around numbers that were already computed. It never produces a price, return or financial figure.
5. **Sources are chosen by confirmed permission, not by availability.** US disclosures come automatically from SEC EDGAR, which documents free reuse. India disclosures come in as **manual import** in the first slice, because NSE's terms prohibit automated collection (§4). Prices come in through a **vendor-agnostic file import** until a price source with confirmed permission is chosen.
6. **Explanations are labelled, never probabilistic.** Four evidence labels (§8). Every card includes the case "no verified explanation yet". No causal percentages.

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
| **NSE corporate announcements / financial results / corporate actions** | Pages load (HTTP 200) **[run]**. They link RSS feeds `Online_announcements.xml`, `Financial_Results.xml`, `Corporate_action.xml` on `nsearchives.nseindia.com` **[run]**. An RSS item has `title` (company **name**, not symbol), `link` (PDF or XBRL), `description` (subject), and a `pubDate` such as `23-Sep-2026 16:29:40` **with no timezone** **[run]**. | HTML pages, RSS XML, PDF/XBRL attachments | **Not permitted for automation.** NSE terms: "User is prohibited to conduct any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting)". Content may not be "reproduced … stored … distributed … without prior written permission of NSE" **[src]** [NSE terms of use](https://www.nseindia.com/static/nse-terms-of-use). The free research-data carve-out is "restricted to individuals from accredited academic institutions, recognized research organizations and think tanks" **[src]** [NSE disclaimer](https://www.nseindia.com/static/nse-disclaimer). | **Manual only.** The owner reads NSE and enters the event (URL, subject, publication time) into `data/manual_events.csv`. No polling, no RSS fetch, no PDF download by MIRROR. |
| **BSE** announcements | Not checked | — | **[unv]** | Not used. |
| **Licensed India feed** (broker API, vendor) | Not evaluated | — | **[unv]** | Open question Q1. |
| **FRED API** | Requests need an API key **[src]** [FRED API keys](https://fred.stlouisfed.org/docs/api/api_key.html). ALFRED vintages and `series/vintagedates` support point-in-time macro values **[src]** [FRED API](https://fred.stlouisfed.org/docs/api/fred/). Must display "This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis"; series may be third-party copyrighted **[src]** [FRED API terms](https://fred.stlouisfed.org/docs/api/terms_of_use.html). | JSON over HTTPS | Personal use appears allowed under the terms with attribution. Per-series copyright must still be checked **[inf]**. | **Deferred** to slice 2 (US macro). India macro sources are **[unv]**. |
| **Prices via `yfinance`** (already a dependency) | "not affiliated, endorsed, or vetted by Yahoo … intended for research and educational purposes"; "the Yahoo! finance API is intended for personal use only" **[src]** [yfinance on PyPI](https://pypi.org/project/yfinance/). Yahoo's own terms were not read **[unv]**. | Unofficial HTTP client | **Unresolved.** Possibly acceptable for a personal, non-redistributed pilot. Not acceptable for any shared output **[inf]**. | Optional producer of the price CSV on the owner's machine. MIRROR's core reads only the CSV schema, so the vendor can be swapped. |
| **NSE daily price archives** (bhavcopy) | Archive pages are linked from the NSE pages above **[run]**. File format not inspected **[unv]**. | Downloadable files | NSE terms allow no automated collection **[src]**. Whether manual download plus local parsing for personal use is permitted is **[unv]**. | Not used until Q1/Q2 are answered. |
| **News** | Not evaluated | — | **[unv]** | Deferred. News never counts as a "documented event" (§8). |

### 4.2 Ingestion rules (all adapters)

- **Idempotency.** Each adapter maps a record to a natural key: SEC accession number; manual event `(security, source_url, published_at)`; price `(security, trade_date, vendor)`. Re-ingesting the same content is a no-op. `source_document` is unique on `(source, source_doc_key, content_sha256)`.
- **Versioning, not overwrite.** If the content hash changes for the same key (amended filing, revised bar), MIRROR inserts a **new version** and keeps the old one. Reads choose the newest version with `first_seen_at ≤ as_of`.
- **Deduplication.** `event.dedup_key = sha256(security_id | event_type | source | source_doc_key)`. An 8-K and its exhibit are one event. The same NSE announcement entered twice is one event.
- **Retries.** At most 3 attempts per HTTP request, with exponential backoff (1 s, 2 s, 4 s) on 429/5xx/timeout. No retry on 4xx other than 429. The SEC adapter keeps a global cap below 10 requests/second (it reuses the existing 0.5 s sleep) and sends the declared User-Agent.
- **Outages.** Each run writes an `ingest_run` row per source: `started_at, finished_at, status (ok | partial | failed), records_new, error`. The brief header shows each source's **last successful fetch time**. A failed source is displayed as failed. It is never shown as "no events".
- **Backfill.** The SEC adapter can backfill a date range from the submissions JSON. Backfilled records get `first_seen_at` = the backfill time (the truth), and `availability_basis = 'publisher_timestamp'` (§5).
- **Freshness.** Price staleness is computed against the exchange calendar (§7). Every brief item shows its data-as-of time.

## 5. Point-in-time provenance

Every fact stores these timestamps, all as UTC in storage and shown in the exchange's timezone in output:

| Field | Meaning | US example | India example |
|---|---|---|---|
| `event_time` | When the underlying thing happened | Form 4 `transactionDate`; 10-Q `reportDate` | Board meeting date; record date |
| `published_at` | When the source made it public | SEC `acceptanceDateTime` **[run]**. Whether its `Z` suffix is true UTC is **[unv]**; the first PR checks it against the EDGAR filing index page. | NSE dissemination time as entered by the user. RSS `pubDate` has no timezone **[run]**, so IST is an **[inf]** assumption and the event is flagged `tz_assumed=1` |
| `published_basis` | `source_timestamp` / `source_date_only` / `user_entered` | `source_timestamp` | `user_entered` |
| `first_seen_at` | When MIRROR first stored it | ingestion clock | ingestion clock |
| `price observation` | `trade_date` + session close in exchange tz + `vendor` + `retrieved_at` | | |
| `url`, `content_sha256`, `version` | Where it came from and exactly what was read | | |
| `calc_version` | For derived rows: `git describe` + hash of parameters used | | |

**As-of rule.** A query evaluated at time `T` sees a record only if it was knowable at `T`:

- *Live mode* (the daily brief): `first_seen_at ≤ T`.
- *Replay mode* (historical evaluation over backfilled data): `published_at ≤ T` **and** `published_basis = 'source_timestamp'`. Records with only a date, or with an assumed timezone, count as knowable at the *end* of that date in the exchange timezone, which is the conservative choice. Output from replay mode is always marked "reconstructed from publisher timestamps".
- Nothing with `first_seen_at > T` (live) or `published_at > T` (replay) may be presented as then-known. This is a test in the first PR (§10, case R1).

**Catalyst timing versus a move.** Session `D` with previous session `D-1`. The window is `(close(D-1), close(D)]` in exchange time.

| Timing tag | Rule | What the card may say |
|---|---|---|
| `before_window` | `published_at ≤ close(D-1)` | "Disclosed before the move" |
| `pre_open` | `close(D-1) < published_at < open(D)` | "Disclosed before the session opened" |
| `during_session` | `open(D) ≤ published_at ≤ close(D)` | "Disclosed during the session; order relative to the price move is unknown without intraday data" |
| `after_close` | `published_at > close(D)` | "Reported after the move; it cannot have been available before it". It may still *describe* the cause, for example a company clarification |

Session open and close times come from config per exchange. The values themselves (NSE 09:15–15:30 IST, NYSE/Nasdaq 09:30–16:00 ET) are **[unv]** here. The first PR cites the exchange source in the config file.

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
price_bar(
  security_id INTEGER REFERENCES security, trade_date DATE, vendor TEXT,
  open REAL, high REAL, low REAL, close_raw REAL NOT NULL, volume REAL,
  close_vendor_adj REAL,               -- kept only for cross-checking; never the basis of a move
  retrieved_at TEXT NOT NULL,
  UNIQUE (security_id, trade_date, vendor, retrieved_at)
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
  evidence_label TEXT NOT NULL, missing_json TEXT, flags_json TEXT,
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

## 8. Explanation contract

Every unusual-move card has these sections, in this order:

1. **Observed facts.** Adjusted move, market-relative move, volume ratio, price source and time. Each number shows how it was computed, and every number traces to `price_bar`/`corporate_action` rows.
2. **Evidence.** Official events for the security with their `timing_tag`, `published_at`, `first_seen_at` and a link. Subjects are quoted verbatim from the source.
3. **Evidence label.** Exactly one of:

| Label | Deterministic rule (first slice) |
|---|---|
| `documented_event` | ≥1 official event with `timing_tag ∈ {before_window, pre_open, during_session}` whose `event_type` is in the material set (results, board outcome, corporate action, 8-K item). Wording: "A documented event preceded or coincided with the move." It is **not** "caused". |
| `multiple_factors` | A `documented_event` exists **and** another competing factor applies: `|relative_move| < trigger` while `|r_D| ≥ trigger` (the stock largely moved with its benchmark), a dividend ex-date, or ≥2 material events. |
| `plausible_association` | Only non-official or ambiguous evidence, for example an event in the `other_disclosure` type, or later news. Not produced by the first slice except for `other_disclosure`. |
| `no_verified_explanation_yet` | No qualifying official event in the covered sources up to `as_of`. The card lists which sources were checked and their freshness, including failures. |

4. **Competing factors.** Benchmark move, dividend, corporate-action flags, stale-data flags.
5. **Thesis relevance.** Shows the saved thesis and horizon next to the evidence. In the first slice the relevance judgement is the **owner's**, recorded through `feedback` (`thesis_update`). A later automated suggestion defaults to "unresolved" and must cite the specific evidence it relies on.
6. **Missing information.** For example: "No intraday prices: order of disclosure vs move unknown"; "NSE covered only by manual entry"; "No news source connected".

An event reported after the close is shown under "Reported after the move" and never raises the label. A news article published near a move is never treated as proof of cause. No card shows a probability or confidence percentage unless a validated model produced it, and none exists.

## 9. Daily workflow and delivery

- **Cadence.** One next-morning run covers the latest completed session of each market. NSE session `D` and the US session `D`, which closes during the Indian night, are both complete before an Indian morning run **[inf]**, subject to the session times in config.
- **Run.** `python -m src.cli ingest && python -m src.cli compute && python -m src.cli brief`. The steps are: fetch SEC for watched CIKs, import `data/manual_events.csv`, `data/prices/*.csv` and `data/corporate_actions.csv`, compute, and render `briefs/YYYY-MM-DD.md`.
- **Brief layout.** Header with the as-of time and per-source freshness/failures. Then "What changed" (new official events per watched stock since the last brief). Then unusual-move cards. Then "Nothing new" stocks as one line.
- **Pilot.** 10–20 stocks the owner actually follows, mixing NSE and US listings, for at least 4 weeks **[inf]**.
- **Feedback.** `python -m src.cli feedback <target> relevant|not_relevant|wrong_attribution [--note]`, `feedback missed --symbol X --url U`, and `thesis set <symbol> --text ... --horizon ...`. All of these are appended to `feedback`, never overwritten.
- **Intraday alerts.** Not built. They would require a dependable price feed whose permission is confirmed, and none has been identified.

## 10. Release checks and acceptance

**Checks every release must pass** (automated in `tests/` unless marked manual):

- **Citation integrity.** Every event and card line has a URL, `published_at` (or explicit `user_entered`) and `first_seen_at`. A test fails on any missing value.
- **Number reproducibility.** Every number in the brief is recomputed from stored rows by the test suite and matches exactly.
- **Duplicate suppression.** Ingesting the same fixtures twice produces identical row counts.
- **Error and freshness visibility.** A failed source appears as failed in the brief header. It is never silently empty.
- **Negative cases.** A large move with no qualifying evidence produces `no_verified_explanation_yet`, never a guessed cause.
- **Historical replay.** Replay at time `T` uses only records knowable at `T` under the §5 rule.
- **Separation.** Product-usefulness checks (these, plus pilot feedback in PRODUCT.md) are separate from any signal-return backtest. Passing these checks says nothing about returns.

**Acceptance matrix** (fixtures are synthetic but shaped like the real sources; no live network in tests):

| # | Case | Fixture | Expected |
|---|---|---|---|
| A1 | Verified pre-open result (India) | Manual NSE results event, `published_at` 08:40 IST on `D`; `+8%` move on `D`; trigger 5 | Card with `documented_event`, tag `pre_open`, verbatim subject, link |
| A2 | Post-move news or filing | US 8-K with `acceptanceDateTime` after the close on `D`; `+11%` move on `D` | Event listed under "Reported after the move"; label `no_verified_explanation_yet` |
| A3 | Split or bonus day | 1:1 bonus (`new_per_old = 2`) ex on `D`; raw close halves, adjusted move `+1%` | No card (below trigger); no −50% anywhere. The same fixture without the action row raises `possible_unrecorded_corporate_action` and holds the card |
| A4 | Unexplained +10% | `+10%` move, benchmark `+0.3%`, no events | `no_verified_explanation_yet`; sources checked and their freshness listed; no causal wording |
| A5 | Stale or missing price | Calendar expects `D`; last bar is `D-1` | Item marked `stale`, "price as of D-1", no move computed |
| A6 | Source outage | SEC adapter returns HTTP 503 ×3 | `ingest_run.status = failed`; brief header shows "SEC EDGAR: failed at <time>, last success <time>"; the brief still renders |
| R1 | As-of leakage guard | Event with `first_seen_at` = `D+1 09:00`; brief generated as of `D+1 08:00` | Event absent from that brief |
| R2 | Market-wide move | Stock `+6%`, benchmark `+5.5%`, results event pre-open | `multiple_factors` |

## 11. Alternatives considered

| Alternative | Why not now |
|---|---|
| Keep "IC first, product later" (the old FOCUS gate) | The product's value (coverage, attribution, time saved) does not depend on the insider score predicting returns. Gating on it would stall the useful part. |
| Scrape or poll NSE pages or RSS | Prohibited by NSE terms **[src]**. Manual entry is slower but permitted for personal reading, and the event model does not change when a licensed feed arrives. |
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

## 13. First implementation PR proposal

**Title:** `feat: watchlist event foundation — SEC + manual NSE events, adjusted daily move, Markdown brief`

**In scope (bounded):**

```
src/core/identity.py        Security, market config, symbol lookup
src/core/calendar.py        sessions + holiday files → expected sessions, open/close in exchange tz
src/store/schema.sql        §6 tables
src/store/db.py             connect (WAL, busy_timeout), idempotent upserts, as-of readers
src/sources/sec_submissions.py   fetch + normalize (8-K/10-Q/10-K/4), keeps acceptanceDateTime
src/sources/manual_events.py     read data/manual_events.csv
src/sources/prices_csv.py        read data/prices/*.csv (one documented schema)
src/sources/corporate_actions.py read data/corporate_actions.csv
src/compute/moves.py        adjusted return, volume ratio, relative move, flags
src/compute/timing.py       timing tags (§5)
src/explain/evidence.py     label rules (§8)
src/brief/render_markdown.py
src/cli.py
config/watchlist.example.yaml, config/exchanges.yaml, config/holidays/{NSE,NYSE}.csv (sources cited)
tests/fixtures/…            SEC submissions JSON sample, manual events, prices, actions
tests/test_moves.py, test_timing.py, test_evidence.py, test_ingest_idempotency.py,
tests/test_asof.py, test_brief_render.py
```

**Out of scope:** any change to `src/scoring`, `src/enrichment`, `src/parsers/insider_parser_v2.py` or `legacy/`; new packages; UI; LLM; FRED; news; NSE automation; a price vendor choice; deployment.

**Pass/fail:**
- `python -m pytest tests/ -v` passes: the existing 31 plus the new tests, with no network access (the SEC adapter is tested against a recorded JSON fixture).
- Acceptance matrix A1–A6, R1, R2 are each a named test and pass.
- One manual run on the owner's real watchlist produces `briefs/<date>.md` in which every line has a working source link and timestamps. This is a manual check, recorded in the PR description with what was observed.
- `pyflakes src/ tests/` is clean (CI already runs it).

## 14. Open questions

| # | Question | Blocks |
|---|---|---|
| Q1 | Which India disclosure source permits automated personal use: a licensed NSE/BSE product, a broker API, or none? | Automating India events (not the first slice) |
| Q2 | Which daily price source (India and US, including benchmarks) has terms that permit this use? | Moving beyond owner-supplied CSVs; any shared output |
| Q3 | Is SEC `acceptanceDateTime` with `Z` actually UTC? | Exact timing tags for US events near session boundaries |
| Q4 | Exchange session times and holiday lists: which primary sources? | `calendar.py` config (first PR must cite them) |
| Q5 | India macro sources (RBI, MOSPI) and their terms | Macro in slice 2 |
| Q6 | Which issuer identifier to use for India (ISIN vs exchange symbol vs company registration number)? | Robust symbol-change handling in India |

## 15. Consequences

- The product can be tested for usefulness within weeks, without waiting on the insider IC.
- India coverage starts **manual**. That is slower for the owner, but it is honest about permissions and keeps the data model ready for a licensed feed.
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
