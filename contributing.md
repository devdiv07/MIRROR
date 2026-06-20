# Contributing to MIRROR

## Quick Start (under 10 minutes)

```bash
git clone https://github.com/<your-fork>/MIRROR.git
cd MIRROR
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt -r requirements-dev.txt
pytest tests/ -v          # should show 31 passed
```

If all 31 tests pass, you are ready to contribute.

---

## Architecture in 60 seconds

```
src/
  parsers/      → fetch Form 4 filings from SEC EDGAR + parse XML
  enrichment/   → add ownership %, market cap, 10b5-1 flag per transaction
  scoring/      → 7 registered scorers; weights in config/scoring.yaml
  pipeline/     → orchestrator that wires all stages together

config/
  scoring.yaml            → scorer weights (edit here, no code change needed)
  universe_smallmid.txt   → 146-ticker universe for Phase 2

tests/                    → pytest suite; run before every commit
```

Full architecture: [docs/architecture.md](docs/architecture.md)

---

## How to add a new scorer

1. Create `src/scoring/your_scorer.py`:

```python
from .registry import register_scorer

@register_scorer('your_scorer_name', default_weight=0.0)
def score_your_scorer(row: dict) -> float:
    """Return a float in [0.0, 1.0]. Aggregator handles direction + clamp."""
    val = row.get('your_column')
    if val is None:
        return 0.0
    return min(1.0, float(val))
```

2. Import it in `src/scoring/__init__.py` to trigger registration.

3. Add an entry to `config/scoring.yaml`:

```yaml
your_scorer_name:
  weight: 0.10
  enabled: true
```

4. Write at least two tests in `tests/test_your_scorer.py` (None input + a normal case).

5. Run `pytest tests/ -v` — all tests must pass.

---

## Commit convention

| Prefix | When |
|--------|------|
| `fix:` | Bug fix |
| `feat:` | New scorer, enrichment, CLI feature |
| `test:` | Test additions or fixes |
| `docs:` | Documentation only |
| `chore:` | CI, deps, config changes |
| `security:` | Security fix |
| `refactor:` | No behavior change, code quality |

Example: `feat: add technical_score scorer using 200DMA pullback signal`

Branch naming: `feat/scorer-technical`, `fix/config-path-bug`, `test/pipeline-e2e`

---

## Quality gates — run before every commit

```bash
pytest tests/ -v          # all must pass
pyflakes src/ tests/      # zero errors
pip-audit --strict        # zero known CVEs
```

---

## Security rules

- **Never** commit `.env`, API keys, or real credentials
- **Never** use `xml.etree.ElementTree` — use `defusedxml.ElementTree` instead
- **Always** add `timeout=30` to every `requests.get()` call
- **Never** add a bare `except:` or `except Exception: pass`
- **Always** add a new dependency to `requirements.txt` with a pinned version and a comment

---

## Coding standards

- All public functions must have type hints
- Return `0.0` (not `None`, not crash) when a scorer receives missing data
- No `print()` in library code — use the logger from `src/utils/logger.py` (coming in Phase 3)
- Keep scorer functions pure: no side effects, no I/O
- Config paths must be relative to project root and verified to exist at startup

---

## Pull request process

1. Open a PR against `main`
2. Fill out the PR template completely
3. CI must be green (pytest + pyflakes + pip-audit)
4. At least one human review before merge
5. Squash-merge with a clean commit message following the convention above

---

## Getting help

- Read [docs/architecture.md](docs/architecture.md) first
- Check [docs/roadmap.md](docs/roadmap.md) for planned work
- Open an issue using the bug report or feature request template
