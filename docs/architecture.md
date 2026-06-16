# MIRROR — System Architecture

**Version:** Phase 2 (June 2026)
**Stack:** Python 3.13, pandas, yfinance, TextBlob, SEC EDGAR API, NewsAPI

---

## Overview

MIRROR is a quantitative insider signal research platform. It operates two independent pipelines:

1. **Original Pipeline (v1)** — cognitive dissonance model: measures contradiction between insider activity, news sentiment, and options market positioning across 10 megacap tickers.
2. **Phase 2 Pipeline** — multi-factor insider conviction scoring across 111 small/mid-cap tickers, with enrichment layers, a scorer registry, and YAML-driven weights.

---

## A. High-Level Architecture

```mermaid
flowchart TD
    DEV([Developer / Researcher])

    subgraph EXT["External Data Sources"]
        SEC[SEC EDGAR API\nForm 4 Filings]
        NAPI[NewsAPI\nFinancial Headlines]
        YF[Yahoo Finance\nyfinance]
    end

    subgraph V1["Original Pipeline — v1 Dissonance Model"]
        S1[insider_parser.py\nStage 1: Insider Signal]
        S2[NEWS_SENTIMENT.PY\nStage 2: News Sentiment]
        S3[legacy/price_signal.py\nStage 3: Options Signal]
        S4[legacy/dissonance_calculator.py\nStage 4: Dissonance Score]
        ORCH[legacy/run_mirror.py\nOrchestrator]
    end

    subgraph V2["Phase 2 Pipeline — Conviction Engine"]
        P_FETCH[sec_filings_fetcher.py\nEDAGR Ingestion]
        P_PARSE[insider_parser_v2.py\nForm 4 Parser]
        P_OWN[enrich_ownership.py\nOwnership Enrichment]
        P_MKT[enrich_market_context.py\nMarket Cap + ADV]
        P_10B[enrich_tenb51.py\n10b5-1 Detection]
        P_AGG[aggregator.py\n7-Scorer Aggregation]
        P_PIPE[run_scoring_pipeline.py\nOrchestrator]
    end

    subgraph DATA["Flat File Storage"]
        IT[(insider_transactions.csv)]
        NS[(news_sentiment_summary.csv)]
        PS[(price_signals.csv)]
        DS[(dissonance_scores.csv)]
        IS2[(insider_signals_phase2.csv)]
    end

    subgraph CFG["Configuration"]
        ENV[.env — API keys]
        YAML[config/scoring.yaml\nScorer weights]
        UNI[config/universe_smallmid.txt\n146 tickers]
    end

    DEV --> ORCH & P_PIPE
    SEC --> S1 & P_FETCH
    NAPI --> S2
    YF --> S3 & P_MKT
    ENV --> S2 & P_FETCH
    YAML --> P_AGG
    UNI --> P_FETCH

    ORCH --> S1 & S2 & S3
    S1 --> IT
    S2 --> NS
    S3 --> PS
    IT & NS & PS --> S4
    S4 --> DS

    P_FETCH --> P_PARSE --> IT
    IT --> P_OWN --> P_MKT --> P_10B --> P_PIPE
    P_PIPE --> P_AGG --> IS2

    DS & IS2 --> DEV
```

---

## B. Original Pipeline — Request Lifecycle

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant Orch as run_mirror.py
    participant S1 as insider_parser.py
    participant EDGAR as SEC EDGAR
    participant S2 as NEWS_SENTIMENT.PY
    participant NAPI as NewsAPI
    participant S3 as price_signal.py
    participant YF as Yahoo Finance
    participant S4 as dissonance_calculator.py
    participant CSV as CSV Storage

    Dev->>Orch: python legacy/run_mirror.py
    Orch->>S1: Stage 1
    S1->>EDGAR: GET /submissions/CIK{}.json
    EDGAR-->>S1: Form 4 filing list
    S1->>EDGAR: GET Form 4 XML per filing
    EDGAR-->>S1: XML transaction data
    S1->>CSV: insider_transactions.csv
    S1-->>Orch: insider_signal per ticker

    Orch->>S2: Stage 2
    S2->>NAPI: GET /everything?q=(TICKER OR name)...
    NAPI-->>S2: JSON articles
    S2->>S2: 4-layer filter + TextBlob sentiment
    S2->>CSV: news_sentiment_summary.csv
    S2-->>Orch: media_signal per ticker

    Orch->>S3: Stage 3
    S3->>YF: OHLCV + options chain (6 months)
    YF-->>S3: price + put/call ratio
    S3->>S3: compute 5 signals
    S3->>CSV: price_signals.csv
    S3-->>Orch: options_signal per ticker

    Orch->>S4: Stage 4
    S4->>CSV: read all 3 signal CSVs
    S4->>S4: C1x0.5 + C2x0.3 + C3x0.2 = dissonance
    S4->>CSV: dissonance_scores.csv
    S4-->>Dev: ranked ticker risk levels
```

---

## C. Phase 2 Pipeline — Data Flow

```mermaid
flowchart LR
    subgraph INGEST["Ingestion"]
        A[SEC EDGAR API] --> B[sec_filings_fetcher.py]
        B --> C[insider_filings.csv]
        C --> D[insider_parser_v2.py]
        D --> E[insider_transactions.csv\n8013 rows / 111 tickers]
    end

    subgraph ENRICH["Enrichment Layers"]
        E --> F[enrich_ownership.py\nshares_before -> pct_holdings_transacted]
        F --> G[enrich_market_context.py\nmarket_cap + avg_30d_dollar_volume]
        G --> H[enrich_tenb51.py\nis_10b51_plan flag]
        H --> I[cluster context\ncluster_count per ticker/window]
    end

    subgraph SCORE["Scoring — 7 Registered Scorers"]
        I --> J1[conviction.py x 0.30\n% holdings transacted]
        I --> J2[role.py x 0.20\nCEO=1.0 CFO=0.90 Dir=0.55]
        I --> J3[market_cap.py x 0.15\ntrade size vs company size]
        I --> J4[cluster.py x 0.15\nmulti-insider confirmation]
        I --> J5[liquidity.py x 0.10\ntrade vs 30d ADV]
        I --> J6[routine_penalty.py x -0.20\nseasonal calendar pattern]
        I --> J7[tenb_penalty.py x -0.25\npre-planned 10b5-1 trade]
    end

    subgraph AGG["Aggregation"]
        J1 & J2 & J3 & J4 & J5 & J6 & J7 --> K[aggregator.py\nweighted_sum x direction\nclamped -1.0 to +1.0]
        K --> L[insider_signals_phase2.csv]
    end
```

---

## D. Cognitive Dissonance Model — Feature Flow

```mermaid
flowchart TD
    subgraph SIGNALS["Three Independent Signals"]
        A["insider_signal\nSEC Form 4 net buy/sell\n{-0.7, -0.3, 0, +0.3, +0.7}"]
        B["media_signal\nNewsAPI + TextBlob\n[-1.0, +1.0]"]
        C["options_signal\nPut/Call ratio\n{-0.8, -0.5, 0, +0.3, +0.5}"]
    end

    subgraph DISSONANCE["Dissonance Formula"]
        D["C1 = |insider - media| / 2\nweight = 0.50"]
        E["C2 = |options - media| / 2\nweight = 0.30"]
        F["C3 = stddev(all 3) / 0.94\nweight = 0.20"]
        G["score = (C1x0.50 + C2x0.30 + C3x0.20) x 100\nrange: 0 to 100"]
    end

    subgraph RISK["Risk Classification"]
        H{"score"}
        H -->|75+| I[CRITICAL]
        H -->|60-74| J[HIGH]
        H -->|40-59| K[MODERATE]
        H -->|25-39| L[LOW]
        H -->|under 25| M[MINIMAL]
    end

    A --> D & F
    B --> D & E & F
    C --> E & F
    D & E & F --> G --> H
```

---

## E. Before vs After — Architecture Change

```mermaid
flowchart LR
    subgraph BEFORE["Phase 1 — Root Level Scripts"]
        direction TB
        B1[SEC_INSIDER.PY]
        B2[NEWS_SENTIMENT.PY]
        B3[price_signal.py]
        B4[dissonance_calculator.py]
        B5[run_mirror.py]
        B5 --> B1 & B2 & B3
        B1 & B2 & B3 --> B4
    end

    subgraph AFTER["Phase 2 — Layered src/ Architecture"]
        direction TB
        A1[src/parsers/\n2 parsers + fetcher]
        A2[src/enrichment/\n3 enrichment modules]
        A3[src/scoring/\nregistry + 7 scorers]
        A4[src/pipeline/\norchestrator]
        A5[config/scoring.yaml\nYAML weights]
        A6[tests/\n4 modules 31 tests]
        A1 --> A2 --> A3
        A3 --> A4
        A5 --> A3
        A6 -.->|covers| A1 & A2 & A3
    end

    BEFORE -->|refactor| AFTER
```

---

## F. Scorer Registry Pattern

```mermaid
flowchart TD
    subgraph REGISTER["Registration — import time"]
        R1[conviction.py] -->|@register_scorer| R[SCORER_REGISTRY dict]
        R2[role.py] -->|@register_scorer| R
        R3[market_cap.py] -->|@register_scorer| R
        R4[cluster.py] -->|@register_scorer| R
        R5[liquidity.py] -->|@register_scorer| R
        R6[routine_penalty.py] -->|@register_scorer| R
        R7[tenb_penalty.py] -->|@register_scorer| R
        R8[__init__.py imports all] --> R1 & R2 & R3 & R4 & R5 & R6 & R7
    end

    subgraph USE["Usage — per transaction row"]
        R --> AGG[aggregator.py\naggregate(row, config)]
        YAML[config/scoring.yaml] --> AGG
        AGG -->|for each enabled scorer| CALL[scorer_fn(row) x weight]
        CALL --> SUM[weighted_sum]
        SUM --> DIR["x direction — BUY=+1 SELL=-1"]
        DIR --> CLAMP[clamp to -1.0..+1.0]
        CLAMP --> OUT[conviction_signal]
    end
```

---

## Folder Structure

```
MIRROR/
├── src/                          # Phase 2 production code
│   ├── parsers/
│   │   ├── sec_filings_fetcher.py    # EDGAR API -> insider_filings.csv
│   │   ├── insider_parser_v2.py      # Form 4 XML parser (production)
│   │   └── universe.py               # Ticker -> CIK resolver
│   ├── enrichment/
│   │   ├── enrich_ownership.py       # shares_before + pct_holdings_transacted
│   │   ├── enrich_market_context.py  # yfinance market cap + ADV
│   │   └── enrich_tenb51.py          # 10b5-1 plan detection
│   ├── scoring/
│   │   ├── registry.py               # @register_scorer decorator
│   │   ├── aggregator.py             # Weighted aggregation + explain()
│   │   ├── conviction.py             # % holdings transacted (weight: 0.30)
│   │   ├── role.py                   # Role weight map (weight: 0.20)
│   │   ├── market_cap.py             # Market cap normalized (weight: 0.15)
│   │   ├── cluster.py                # Multi-insider detection (weight: 0.15)
│   │   ├── liquidity.py              # Trade vs ADV (weight: 0.10)
│   │   ├── routine_penalty.py        # Calendar seasonality (weight: -0.20)
│   │   └── tenb_penalty.py           # Pre-planned trades (weight: -0.25)
│   └── pipeline/
│       └── run_scoring_pipeline.py   # Phase 2 main entry point
├── config/
│   ├── scoring.yaml                  # Scorer weights (tune without code changes)
│   └── universe_smallmid.txt         # 146-ticker curated universe
├── tests/
│   ├── test_conviction.py            # 15 tests
│   ├── test_cluster.py               # 5 tests
│   ├── test_10b51_extraction.py      # 7 tests
│   └── test_entity_filer.py          # 4 tests
├── legacy/                           # Archived Phase 1 code (reference only)
│   ├── run_mirror.py
│   ├── dissonance_calculator.py
│   ├── price_signal.py
│   └── insider_parser.py
├── data/                             # Input data (gitignored)
│   ├── insider_transactions.csv      # 8013 transactions, 111 tickers
│   └── ...
├── results/                          # Output data (gitignored)
│   ├── insider_signals_phase2.csv    # Phase 2 scored output
│   └── dissonance_scores.csv         # Phase 1 dissonance output
├── scripts/                          # Developer utilities
├── docs/                             # Documentation
├── NEWS_SENTIMENT.PY                 # Active - Phase 1 Stage 2
├── insider_parser.py                 # v1 parser (deprecated root-level copy)
├── .env                              # Secrets (gitignored)
└── requirements.txt                  # numpy, pandas, requests, textblob, yfinance
```

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| Registry pattern for scorers | New scorer = one decorated file, zero changes to aggregator |
| YAML-driven weights | Analysts can A/B test without touching Python code |
| Flat CSV storage (no database) | Matches research workflow; SQLite upgrade planned for Phase 3 |
| Enrichment as separate layer | Keeps parsers pure; enrichment can be retried independently |
| Graceful degradation on None | Conviction scorer returns 0.0, not crash, on missing ownership data |
| Hard-gate for entity filers | Prevents non-discretionary institutional trades from polluting signals |
| is_company via XML tag + name fallback | XML tag is authoritative for modern filings; fallback covers pre-2023 filings |
