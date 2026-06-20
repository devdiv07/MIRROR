# MIRROR — Cognitive Dissonance Mapper (Layer 3)

The first component of the larger **MIRROR** vision: a research platform measuring the gap between what market insiders **do** (SEC Form 4 filings) and what the market **says**. The actively-developed piece today is a multi-factor **insider conviction signal**.

> **Status:** research-grade. The signal is **not yet validated**. See [docs/layer3_current_state.md](docs/layer3_current_state.md) for the honest current state and [docs/FOCUS.md](docs/FOCUS.md) for what's being built right now.

## Quick Start

```bash
pip install -r requirements.txt
python -m src.pipeline.run_scoring_pipeline   # run from the project root
```

Output: `results/insider_signals_phase2.csv`

## Architecture

- **Parsers** (`src/parsers/`): SEC EDGAR API, Form 4 XML extraction (defusedxml)
- **Enrichment** (`src/enrichment/`): ownership %, market cap + 30d ADV, 10b5-1 detection
- **Scoring** (`src/scoring/`): 7 registered scorers, YAML-driven aggregation
- **Pipeline** (`src/pipeline/`): orchestration

`legacy/` holds the original Phase-1 dissonance pipeline (news + options + the dissonance "brain"); it is not yet rebuilt to the `src/` standard.

## Scorers (7)

| Scorer | Weight | Purpose |
|--------|--------|---------|
| conviction_score | +0.30 | % of holdings transacted |
| role_score | +0.20 | information access (CEO > director) |
| market_cap_score | +0.15 | trade size vs market cap |
| cluster_score | +0.15 | multi-insider confirmation |
| liquidity_score | +0.10 | trade size vs 30d ADV |
| routine_penalty | −0.20 | routine/seasonal trades (no signal) |
| tenb_penalty | −0.25 | 10b5-1 pre-planned trades (no information) |

Weights live in `config/scoring.yaml` — edit there, no code changes. Final signal range: **[−1.0, +1.0]**.

## Current results (descriptive — not validated)

- 8,013 transactions scored across 111 small/mid-cap tickers
- Signal range ≈ [−0.49, +0.64], mean ≈ −0.14 (net bearish this period)
- 31/31 tests passing (`pytest tests/ -v`)
- A first backtest ran but is **inconclusive** — see [docs/layer3_current_state.md](docs/layer3_current_state.md) §5

## Documentation

Start at **[docs/INDEX.md](docs/INDEX.md)** — the map of every doc. Key entries:

- [docs/FOCUS.md](docs/FOCUS.md) — what's being built right now
- [docs/layer3_current_state.md](docs/layer3_current_state.md) — honest current state
- [docs/mirror_vision_roadmap.md](docs/mirror_vision_roadmap.md) — the whole MIRROR vision
- [docs/architecture.md](docs/architecture.md) — system architecture
- [contributing.md](contributing.md) — setup & contribution guide

## License

MIT — see [LICENSE](LICENSE).
