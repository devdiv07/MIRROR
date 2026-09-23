# MIRROR

**Intended product:** a personal, source-linked research assistant for a watchlist of India and US stocks. Each morning it says which material company events happened, why a watched stock made a large move (with dated evidence and what is still unknown), and how new facts bear on the owner's saved thesis. It makes no buy/sell calls and no claims of improved returns. → [docs/PRODUCT.md](docs/PRODUCT.md)

> **Status (2026-09-23): the watchlist product is not built yet.** The design is proposed in [docs/adr/0001-watchlist-event-foundation.md](docs/adr/0001-watchlist-event-foundation.md), and the active task is in [docs/FOCUS.md](docs/FOCUS.md). There is **no India coverage** in the code today. India will start as a manual-entry prototype, with its coverage shown explicitly. Automation depends on a sourcing decision that has not yet been made (ADR §4.3).

## What the code does today

| Part | Where | What it is | Status |
|---|---|---|---|
| Insider conviction research pipeline (US) | `src/` | SEC Form 4 fetch → parse → enrich → 7 weighted scorers → `results/insider_signals_phase2.csv` | **Research only. Unvalidated, with verified defects** (sign/penalty error, Form 4 code F counted as a sale, cluster look-ahead, current market cap on historical trades). See [ADR §12](docs/adr/0001-watchlist-event-foundation.md#12-separate-track-insider-signal-research-blockers). Do not use its scores as signals. |
| Legacy dissonance prototype | `legacy/` | News sentiment + options/price signals + a dissonance score over 10 hard-coded US mega-caps | Prototype. It does **not** use the `src/` insider scores, and `legacy/run_mirror.py` calls `SEC_INSIDER.PY`, which is not in the repository. Its dependencies are in `requirements-legacy.txt` (textblob → nltk, which has an open advisory: PYSEC-2026-3740). |
| Watchlist research product | — | Watchlist, dated events, adjusted moves, evidence-labelled explanations, daily brief | **Planned** as four milestones after the CI repair ([FOCUS.md](docs/FOCUS.md) steps 2–5) |

The earlier 5-layer vision and the insider-IC roadmap remain available as dated research direction. See [docs/INDEX.md](docs/INDEX.md).

## Setup and tests

Python 3.13 (the version CI uses).

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt     # includes requirements.txt
python -m pytest tests/ -v
```

Last observed result: **31 passed, 2 warnings**, locally (2026-09-23, Windows 11, Python 3.13.5) and in CI. The tests cover the insider parser, enrichment and scorers only. CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs `pyflakes src/ tests/`, then pytest, then `pip-audit --strict`. All three passed on `63cf01e` ([run 35858038008](https://github.com/devdiv07/MIRROR/actions/runs/35858038008)). CI had been red at the pyflakes step since `e068c91` until then. `legacy/` needs `pip install -r requirements-legacy.txt`, which is not audited in CI; see the note in that file.

## Running the insider research pipeline (optional, research only)

`data/*.csv` and `results/*.csv` are git-ignored. A clean clone has no input data, so run the stages in order from the repo root. All three stages need network access: stages 1–2 call SEC EDGAR, and stage 3 calls Yahoo Finance via `yfinance`. Set `SEC_USER_AGENT` to a name and contact email, as SEC asks for automated access.

```bash
python -m src.parsers.sec_filings_fetcher        # → data/insider_filings.csv (universe: config/universe_smallmid.txt)
python -m src.parsers.insider_parser_v2          # → data/insider_transactions.csv
python -m src.pipeline.run_scoring_pipeline      # → results/insider_signals_phase2.csv
```

These commands match the modules' `__main__` entry points, but they were **not re-run** for this README. One caveat: the parser's `__main__` demo section imports modules by pre-reorg paths ([insider_parser_v2.py:392-393](src/parsers/insider_parser_v2.py)) and will likely fail *after* the CSV has been written.

## Documentation

Start at **[docs/INDEX.md](docs/INDEX.md)**. Key entries:

- [docs/FOCUS.md](docs/FOCUS.md): the one active task
- [docs/PRODUCT.md](docs/PRODUCT.md): what MIRROR is for, scope, and pilot measures
- [docs/adr/0001-watchlist-event-foundation.md](docs/adr/0001-watchlist-event-foundation.md): architecture of the first slice, plus the verified insider defects
- [docs/architecture.md](docs/architecture.md): structure of the existing insider and legacy code
- [contributing.md](contributing.md): setup and contribution guide

## License

MIT — see [LICENSE](LICENSE).
