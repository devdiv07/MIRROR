-- MIRROR store schema, version 1 (ADR 0001 §6, amended in Milestone 1; see ADR §6 "Milestone 1 amendment").
--
-- Conventions
--   * Timestamps are ISO-8601 UTC text, e.g. '2026-09-23T07:00:00Z'. Dates are 'YYYY-MM-DD'.
--   * History is never rewritten in place: symbol changes add rows; thesis edits are logged in feedback.
--   * Every statement is idempotent (IF NOT EXISTS), so init_schema() can run on every connect.

-- One listed line (share class) on one exchange. `security_key` is the MIRROR-assigned stable
-- identity: it never changes when the ticker, ISIN or name changes. External identifiers are
-- attributes, not keys, because none of them is a safe listing-level key for both markets
-- (e.g. one SEC CIK can cover several listed share classes).
CREATE TABLE IF NOT EXISTS security (
  security_id            INTEGER PRIMARY KEY,
  security_key           TEXT NOT NULL UNIQUE,
  market                 TEXT NOT NULL CHECK (market IN ('IN', 'US')),
  exchange               TEXT NOT NULL,                  -- 'NSE' | 'NYSE' | 'NASDAQ'
  name                   TEXT NOT NULL,
  company_id_type        TEXT,                           -- 'CIK' for US; NULL for IN until ADR 0002 (Q6)
  company_id             TEXT,
  isin                   TEXT,
  currency               TEXT NOT NULL,
  timezone               TEXT NOT NULL,
  benchmark_security_id  INTEGER REFERENCES security (security_id),
  created_at             TEXT NOT NULL,
  updated_at             TEXT NOT NULL,
  CHECK ((company_id_type IS NULL) = (company_id IS NULL))
);

-- Symbol history. Periods are half-open: [valid_from, valid_to); valid_to NULL = still current.
-- Non-overlap per security and per (exchange, symbol) is enforced by src/store/db.py.
CREATE TABLE IF NOT EXISTS security_symbol (
  symbol_id    INTEGER PRIMARY KEY,
  security_id  INTEGER NOT NULL REFERENCES security (security_id),
  exchange     TEXT NOT NULL,
  symbol       TEXT NOT NULL,
  valid_from   TEXT NOT NULL,
  valid_to     TEXT,
  UNIQUE (exchange, symbol, valid_from),
  CHECK (valid_to IS NULL OR valid_to > valid_from)
);
CREATE INDEX IF NOT EXISTS ix_security_symbol_security ON security_symbol (security_id, valid_from);

CREATE TABLE IF NOT EXISTS watchlist_item (
  item_id           INTEGER PRIMARY KEY,
  security_id       INTEGER NOT NULL UNIQUE REFERENCES security (security_id),
  thesis            TEXT,
  horizon           TEXT,
  move_trigger_pct  REAL CHECK (move_trigger_pct IS NULL OR move_trigger_pct > 0),
  active            INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
  added_at          TEXT NOT NULL,
  updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingest_run (
  run_id       INTEGER PRIMARY KEY,
  source       TEXT NOT NULL,
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  status       TEXT CHECK (status IN ('ok', 'partial', 'failed')),
  records_new  INTEGER,
  error        TEXT
);

CREATE TABLE IF NOT EXISTS source_document (
  doc_id           INTEGER PRIMARY KEY,
  source           TEXT NOT NULL,                        -- 'SEC_EDGAR' | 'MANUAL_NSE' | ...
  source_doc_key   TEXT NOT NULL,                        -- accession no. | URL
  url              TEXT,
  content_sha256   TEXT NOT NULL,
  version          INTEGER NOT NULL,
  published_at     TEXT,
  published_basis  TEXT NOT NULL CHECK (published_basis IN ('source_timestamp', 'source_date_only', 'user_entered')),
  tz_assumed       INTEGER NOT NULL DEFAULT 0 CHECK (tz_assumed IN (0, 1)),
  first_seen_at    TEXT NOT NULL,
  raw_path         TEXT,
  UNIQUE (source, source_doc_key, content_sha256),
  UNIQUE (source, source_doc_key, version)
);

CREATE TABLE IF NOT EXISTS event (
  event_id       INTEGER PRIMARY KEY,
  security_id    INTEGER NOT NULL REFERENCES security (security_id),
  doc_id         INTEGER REFERENCES source_document (doc_id),
  event_type     TEXT NOT NULL,                          -- 'results' | 'board_outcome' | 'corporate_action' | '8k_item' | 'insider_form4' | 'other_disclosure'
  subject        TEXT NOT NULL,                          -- verbatim from source
  event_time     TEXT,
  published_at   TEXT,
  first_seen_at  TEXT NOT NULL,
  fields_json    TEXT,
  dedup_key      TEXT NOT NULL UNIQUE
);

-- One row per imported price file (ADR §5.1): provenance for every price claim.
CREATE TABLE IF NOT EXISTS price_import (
  import_id            INTEGER PRIMARY KEY,
  file_name            TEXT NOT NULL,
  file_sha256          TEXT NOT NULL UNIQUE,
  declared_vendor      TEXT NOT NULL DEFAULT 'unknown',
  declared_source_url  TEXT,                             -- NULL = upstream source unknown
  vendor_as_of         TEXT,
  imported_at          TEXT NOT NULL,
  row_count            INTEGER NOT NULL
);

-- Bars stay attached to security_id, so a symbol change never moves price history.
CREATE TABLE IF NOT EXISTS price_bar (
  security_id       INTEGER NOT NULL REFERENCES security (security_id),
  trade_date        TEXT NOT NULL,
  import_id         INTEGER NOT NULL REFERENCES price_import (import_id),
  open              REAL,
  high              REAL,
  low               REAL,
  close_raw         REAL NOT NULL,
  volume            REAL,
  close_vendor_adj  REAL,                                -- cross-check only; never the basis of a move
  UNIQUE (security_id, trade_date, import_id)
);

CREATE TABLE IF NOT EXISTS coverage_check (
  check_id      INTEGER PRIMARY KEY,
  security_id   INTEGER NOT NULL REFERENCES security (security_id),
  source        TEXT NOT NULL,                           -- 'SEC_EDGAR' | 'MANUAL_NSE' | ...
  method        TEXT NOT NULL CHECK (method IN ('api', 'manual')),
  window_start  TEXT NOT NULL,
  window_end    TEXT NOT NULL,
  checked_at    TEXT NOT NULL,
  status        TEXT NOT NULL CHECK (status IN ('ok', 'partial', 'failed')),
  scope_note    TEXT,
  error         TEXT,
  run_id        INTEGER REFERENCES ingest_run (run_id),
  CHECK (window_end >= window_start)
);

CREATE TABLE IF NOT EXISTS corporate_action (
  action_id      INTEGER PRIMARY KEY,
  security_id    INTEGER NOT NULL REFERENCES security (security_id),
  action_type    TEXT NOT NULL CHECK (action_type IN ('split', 'bonus', 'dividend', 'symbol_change', 'rights')),
  ex_date        TEXT NOT NULL,
  new_per_old    REAL,
  cash_amount    REAL,
  currency       TEXT,
  doc_id         INTEGER REFERENCES source_document (doc_id),
  first_seen_at  TEXT NOT NULL,
  UNIQUE (security_id, action_type, ex_date)
);

CREATE TABLE IF NOT EXISTS explanation (
  explanation_id     INTEGER PRIMARY KEY,
  security_id        INTEGER NOT NULL REFERENCES security (security_id),
  session_date       TEXT NOT NULL,
  as_of              TEXT NOT NULL,
  calc_version       TEXT NOT NULL,
  move_pct           REAL,
  relative_move_pct  REAL,
  volume_ratio       REAL,
  evidence_label     TEXT NOT NULL CHECK (evidence_label IN (
                       'documented_event', 'multiple_factors', 'plausible_association',
                       'no_verified_explanation_yet', 'no_evidence_coverage_incomplete')),
  coverage_json      TEXT,
  missing_json       TEXT,
  flags_json         TEXT,
  UNIQUE (security_id, session_date, as_of, calc_version)
);

CREATE TABLE IF NOT EXISTS explanation_evidence (
  explanation_id  INTEGER NOT NULL REFERENCES explanation (explanation_id),
  event_id        INTEGER NOT NULL REFERENCES event (event_id),
  timing_tag      TEXT NOT NULL CHECK (timing_tag IN ('before_window', 'pre_open', 'during_session', 'after_close')),
  role            TEXT NOT NULL CHECK (role IN ('documented', 'competing', 'context')),
  PRIMARY KEY (explanation_id, event_id)
);

CREATE TABLE IF NOT EXISTS feedback (
  feedback_id  INTEGER PRIMARY KEY,
  created_at   TEXT NOT NULL,
  target_type  TEXT CHECK (target_type IN ('event', 'explanation', 'watchlist_item')),
  target_id    INTEGER,
  kind         TEXT NOT NULL CHECK (kind IN ('relevant', 'not_relevant', 'wrong_attribution', 'missed_event', 'thesis_update')),
  note         TEXT,
  old_value    TEXT,
  new_value    TEXT
);
