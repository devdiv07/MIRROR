# MIRROR — Future Roadmap & Production Plan

**Version:** 1.0 | **Date:** June 19, 2026 | **Author:** devdiv07  
**Status:** Post Phase 2 — Research-grade; not yet production-ready

---

## Honest Assessment Up Front

MIRROR has a solid Phase 2 foundation: layered `src/` architecture, YAML-driven scorer registry, 8,013 transactions across 111 tickers, and 31 passing tests. **It is not production-ready.** This document maps the gap and how to close it — without over-engineering a solo project.

---

## Immediate Real Bugs Found (Fix Before Anything Else)

| # | Bug | File | Fix |
|---|-----|------|-----|
| 1 | **Wrong config path** — loads `'insider_signal_phase1/config/scoring.yaml'` which does not exist | `src/pipeline/run_scoring_pipeline.py:50` | Change to `'config/scoring.yaml'` |
| 2 | **Exploratory test comment** — "we can delete this test file after we confirm" | `tests/test_conviction.py` (last line) | Remove comment; treat as permanent |
| 3 | **Dep versions not pinned** — `numpy` not `numpy==x.y.z` | `requirements.txt` | Run `pip freeze > requirements.txt` in .venv |
| 4 | **Phase naming conflict** — `implementation_plan.md` calls Universe Manager "Phase 2" but Phase 2 is already shipped | `implementation_plan.md` | Add note renaming plan phases to R3–R8 |

---

## Current State — Maturity Scorecard

| Area | Level | Evidence | Gap | Priority |
|------|-------|----------|-----|----------|
| Architecture | ★★★☆☆ | Layered src/; registry pattern; YAML weights | Hardcoded wrong config path; no error recovery | High |
| Data pipeline reliability | ★★☆☆☆ | Graceful None/NaN handling in scorers | Config path crash; no retry; no checksums | Critical |
| Security | ★★☆☆☆ | .env gitignored; data/ gitignored | No dep scanning; no secret scanning CI | High |
| Testing | ★★★☆☆ | 31 tests; edge cases covered | No e2e pipeline test; no API failure mock; exploratory comment | High |
| Observability | ★☆☆☆☆ | print() shows stage progress | No structured logs; no run IDs; failures invisible | Critical |
| Error handling | ★★☆☆☆ | Aggregator degrades gracefully | Pipeline crashes on missing CSV; API timeouts missing | High |
| Configuration | ★★★☆☆ | YAML-driven weights; .env for secrets | Wrong config path in pipeline | Medium |
| Documentation | ★★★☆☆ | architecture.md; change_justification.md | No CONTRIBUTING.md; no setup guide; no runbooks | Medium |
| Git workflow | ★☆☆☆☆ | Meaningful commit messages | No CI/CD; no templates; no branch protection | High |
| Contributor onboarding | ★★☆☆☆ | README with quickstart exists | No CONTRIBUTING.md; no local dev guide | Medium |
| Deployment readiness | ★☆☆☆☆ | Runs locally | No Docker; no deployment scripts | Low (now) |
| Performance | ★★★☆☆ | 8,013 rows scored acceptably | yfinance uncached; no request timeouts | Low (now) |
| Scalability | ★★☆☆☆ | CSV sufficient for current volume | No database; single-process | Low (now) |

---

## Future Vision

### 3 Months — Research-Grade Stable System

- Config path bug fixed; all hardcoded paths resolved
- Structured logging with run IDs (replacing print statements)
- GitHub Actions CI running pytest + pip-audit on every push
- CONTRIBUTING.md, setup guide, PR template in place
- Walk-forward backtester validating signal quality
- Experiment tracker recording every pipeline run

### 6 Months — Signal Validated + Internal Tool

- Bayesian parameter optimizer replacing manually-chosen YAML weights
- Walk-forward backtester with IC, hit rate, Sharpe, deflated Sharpe reported
- Statistical uncertainty reporting (bootstrap CIs, p-values on IC)
- Universe management (survivorship-bias-free)
- Docker container for reproducible local runs
- SQLite for multi-run history

### 12 Months — Platform (Only If Signal Validates)

> **Gate:** Proceed to platform features only if out-of-sample IC > 0.05 and deflated Sharpe > 0.3.

- FastAPI REST API with JWT auth and rate limiting
- PostgreSQL replacing SQLite at meaningful data volume
- Scheduled pipeline runs via APScheduler
- Simple web dashboard for signal exploration
- Docker Compose + cloud deployment

---

## Production Architecture Roadmap

### Stage A — Research-Grade Stable (Now → 3 months)

**Build:** Fix config path; structured logging + run IDs; GitHub Actions CI; CONTRIBUTING.md; pip-audit; experiment tracker; walk-forward backtester

**Do not build yet:** API layer, database, Docker, dashboard, optimizer

**Exit criteria:** Zero crashes on full pipeline run; CI green on every push; new developer runs tests in < 10 min

### Stage B — Internal Tool (3 → 6 months)

**Build:** Bayesian optimizer; universe manager; statistical reporter; SQLite run history; Docker; CLI report command

**Do not build yet:** Public API; web dashboard; external auth; load balancer

**Exit criteria:** Out-of-sample IC > 0.05; deflated Sharpe > 0.3; Docker run works; optimizer output reproducible

### Stage C — Platform (6 → 12 months, IF signal valid)

**Build:** FastAPI REST; PostgreSQL; JWT auth; scheduled jobs; Jinja2 dashboard; Docker Compose; cloud deploy

**Do not build:** Kubernetes (overkill for < 50 users); GraphQL (REST sufficient); Redis (only if > 5 concurrent users trigger queue need)

---

## Security Plan

### Immediate Actions

| Action | Tool | When |
|--------|------|------|
| Add secret scanning to CI | `gitleaks` | Before next push |
| Dependency vulnerability scan | `pip-audit` in GitHub Actions | Stage A CI |
| Replace xml.etree with defusedxml | `pip install defusedxml` | Stage A |
| Pin all dep versions | `pip freeze > requirements.txt` | Now |
| Add request timeouts | `timeout=30` in all `requests.get()` | Now |
| Sanitize CSV output fields | Custom sanitize() before `df.to_csv()` | Stage A |
| API key rotation schedule | Calendar reminder every 90 days | Now |

### Threat Model

| Threat | Impact | Mitigation | Priority |
|--------|--------|------------|----------|
| API key committed to git | Key exposure | gitleaks in CI; .env gitignored (done) | Critical |
| Dependency supply chain attack | Malicious code in pipeline | pip-audit weekly; pin versions | High |
| Malicious SEC EDGAR XML | XXE injection; parser crash | defusedxml; request timeouts | High |
| CSV injection in output | Formula injection in Excel | Sanitize cells starting with =, +, -, @ | Medium |
| yfinance data poisoning | False signals | Validate return ranges (no > ±50% single-day) | Medium |
| Secrets in logs | API key leakage | Mask keys in log formatter | High |
| AI-generated insecure code | Wrong paths; silent exceptions | See AI Safety Workflow below | High |
| Prompt injection via financial data | AI manipulation | Never paste raw API responses into AI prompts | Medium |

---

## AI-Assisted Coding Safety Workflow

**Rule:** AI proposes; human verifies; tests confirm.

| AI Risk | Rule | Verification |
|---------|------|-------------|
| Hallucinated file paths | AI states every file it reads before editing | `ls` the path before trusting AI's claim |
| Silent exception swallowing | No bare `except:` or `except Exception: pass` | `grep -n "except:" diff` |
| Fake test results | AI never claims tests pass — you run them | Always run `pytest -v` yourself |
| Large refactor without design note | No refactor touching > 3 files without written design note | Count files in `git diff --stat` |
| Undocumented dependency additions | Any new import justified in commit message | `git diff requirements.txt` before commit |
| Secret exposure | Never paste .env into AI prompts | Review prompt before sending |
| Wrong config/path assumptions | All paths verified to exist | `python -c "import os; print(os.path.exists('path'))"` |
| Fabricated benchmark claims | No speed claims without measured baseline | Require benchmark command in commit message |

### Claude Code Safe Prompt Template

```
## Task
[One sentence: what should change and why]

## Scope
Files to read: [exact paths]
Files to modify: [exact paths]
Files NOT to touch: [exact paths]

## Constraints
- Do not add new dependencies without justification
- No bare except: or silent error swallowing
- All new functions must have type hints
- Do not claim tests pass — I will run them
- Do not paste or reference .env contents
- Config paths must use os.path.join() from project root

## Definition of Done
- [ ] Diff is small and focused
- [ ] Tests written for new behavior
- [ ] pytest passes (I will verify)
- [ ] No new warnings in output
- [ ] Docs updated only if behavior changed
```

---

## Testing Strategy

### Test Pyramid (bottom to top)

1. **Unit tests** (31 existing) — scorer logic, edge cases, clamp, registry wiring, entity gate
2. **Integration tests** — enrichment chain, aggregator wiring, config loading, API mock responses
3. **Pipeline E2E tests** — full run on fixture CSV; verify output shape + range *(missing — add in Phase 3)*
4. **Security tests** — dep scan, secret scan, input fuzzing *(in Stage A CI)*
5. **Performance tests** — pipeline < 5 min for 111 tickers *(future Stage B)*

### Quality Gates (Required Before Any Merge)

```bash
pytest tests/ -v                     # all must pass
pyflakes src/ tests/                # zero errors
pip-audit --strict                  # zero CVEs
gitleaks detect --no-git            # zero secret leaks
```

---

## Observability Plan

### Proposed Structure

```
MIRROR/
├── logs/
│   └── mirror_YYYY-MM-DD.jsonl        # structured JSON logs
├── runs/
│   └── {run_id}/
│       ├── run_metadata.json           # full run audit record
│       ├── data_quality_report.txt     # per-stage row counts + warnings
│       └── failed_tickers.txt
├── reports/
│   └── signal_explanation_{run_id}.csv
├── artifacts/
│   └── config_snapshot_{run_id}.yaml
└── docs/runbooks/
    ├── how_to_run_pipeline.md
    ├── how_to_add_a_scorer.md
    └── how_to_debug_a_failed_run.md
```

### Run Metadata Schema

```json
{
  "run_id": "20260619_143022_a3f8",
  "started_at": "2026-06-19T14:30:22Z",
  "ended_at": "2026-06-19T14:38:45Z",
  "git_commit": "c549c2f",
  "config_hash": "sha256:ab3f...",
  "config_file": "config/scoring.yaml",
  "stage_status": {
    "load_transactions": {"rows_in": 8013, "status": "ok"},
    "enrich_ownership":  {"null_pct": 0.005, "status": "ok"},
    "enrich_market":     {"failed_tickers": ["XYZ"], "status": "warn"},
    "scoring":           {"range_violations": 0, "status": "ok"}
  },
  "warnings": ["technical_score enabled but not registered"],
  "signal_stats": {"mean": -0.14, "std": 0.18, "min": -0.488, "max": 0.644}
}
```

---

## Data and Database Strategy

| Storage | Best For | Stage |
|---------|----------|-------|
| CSV (current) | Single-run research; zero infra | Stage A — keep |
| SQLite | Multi-run history; experiment tracking | Stage B — add |
| DuckDB | Large analytical queries on Parquet | Stage B optional |
| PostgreSQL | Multi-user API backend; concurrent writes | Stage C |
| Parquet + object storage | Large historical archives | Stage C optional |

**Current recommendation:** Keep CSV. Add SQLite for experiment tracking in Stage B. Migrate to PostgreSQL only at Stage C when concurrent users or API requires it.

---

## Scalability Plan

| Concern | Needed Now? | Trigger | Solution |
|---------|-------------|---------|----------|
| yfinance latency | **Yes** | Current bottleneck | Cache per ticker per date |
| Request timeouts | **Yes** | No timeouts exist | `timeout=30` in all API calls |
| Retry with backoff | **Yes** | API failures crash pipeline | tenacity; 3 attempts, 2s/4s/8s |
| Database indexing | No | When SQLite/PG added | Index on (ticker, date), (run_id) |
| Horizontal scaling | No | > 50 concurrent users | Docker + nginx; not before Stage C |
| Redis cache | No | API response time > 500ms | Cache /signals for 15 min |
| Load balancer | No | Public high-traffic | Never before Stage C |
| Kubernetes | No | Never for < 100 users | Single VPS handles Stage C fine |

---

## Contributor Readiness Plan

### Required Documents

- `README.md` — update with Phase 2 entry point (`src/pipeline/run_scoring_pipeline.py`)
- `CONTRIBUTING.md` — setup guide, coding standards, PR process
- `CODEOWNERS` — @devdiv07 owns src/ scoring/ enrichment/
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/workflows/ci.yml` — pytest + pyflakes + pip-audit
- `.github/ISSUE_TEMPLATE/bug_report.md`
- `docs/adr/001-registry-pattern.md`
- `docs/adr/002-yaml-driven-weights.md`
- `docs/runbooks/how_to_run_pipeline.md`

### Commit Convention

| Prefix | Use Case |
|--------|----------|
| `fix:` | Bug fixes |
| `feat:` | New scorer, enrichment, CLI flag |
| `test:` | Adding or fixing tests |
| `docs:` | Documentation only |
| `chore:` | CI, deps, config |
| `security:` | Security fixes |
| `refactor:` | No behavior change |

Branch naming: `feat/scorer-technical`, `fix/config-path-bug`, `test/pipeline-e2e`

---

## Phased Implementation Roadmap

> **Note on Phase Numbering:** The `implementation_plan.md` uses "Phase 2–8" for features not yet built. To avoid confusion with the shipped Phase 2 (conviction engine), this roadmap continues from Phase 3.

### Phase 3 — Stability and Hardening (Weeks 1–6)

| Task | Priority | Acceptance Criteria |
|------|----------|---------------------|
| Fix config path bug | Critical | `config/scoring.yaml` loaded correctly |
| Add structured logging + run IDs | High | JSON log written per run; run_id in every line |
| Add GitHub Actions CI | High | pytest + pip-audit green on every push |
| Replace xml.etree with defusedxml | High | Tests still pass; no XMLvulns |
| Add request timeouts | High | All requests.get() have timeout=30 |
| Add pipeline e2e test | High | Full run on fixture CSV validates |
| Write CONTRIBUTING.md | Medium | New dev runs tests in < 10 min |
| Remove exploratory test comment | Low | test_conviction.py is permanent |

### Phase 4 — Signal Validation (Weeks 7–14)

| Task | Difficulty | Acceptance Criteria |
|------|------------|---------------------|
| Universe manager (bias-free) | Medium | No future ticker in historical test |
| Historical data builder | Medium | 6-month rolling signal + forward returns |
| Experiment tracker | Medium | config_hash + git_commit per run |
| Walk-forward backtester | Hard | IC, hit rate, Sharpe per window; no leakage |
| Statistical uncertainty reporter | Medium | Bootstrap CIs; p-values; deflated Sharpe |
| Bayesian weight optimizer | Hard | Optimized IC > default IC on held-out data |

### Phase 5 — Developer Experience (Weeks 15–18)

ADR folder; 3 runbooks; PR + issue templates; `pyproject.toml`; type hints + mypy clean

### Phase 6 — Internal Dashboard/API

**Gate:** IC > 0.05 out-of-sample AND deflated Sharpe > 0.3

FastAPI REST; SQLite → PostgreSQL; JWT auth; Jinja2 dashboard; APScheduler; Docker Compose

### Phase 7 — Production Deployment

Cloud VPS; HTTPS; automated backups; uptime monitoring; WAF only if public-facing

---

## Risk Register

| Risk | Severity | Mitigation |
|------|----------|------------|
| Wrong config path (silent misconfiguration) | Critical | Fix in Phase 3 immediately |
| API key accidentally committed | Critical | gitleaks in CI; key rotation policy |
| Signal has no predictive value (IC ≈ 0) | High | Phase 4 backtester; gate before Phase 6 |
| Dependency vulnerability | High | pip-audit weekly in CI |
| yfinance API breaks or rate-limits | Medium | Cache per-ticker per-date; fail gracefully |
| Phase naming confuses contributors | Medium | Rename plan phases to R3–R8 |
| Look-ahead bias in backtester | High | Universe manager; data freeze; explicit test |
| Tests deleted as "exploratory" | Medium | Remove comment; treat all tests as permanent |

---

## Statistical Validation Targets (Phase 4)

| Metric | Minimum (gate) | Good | Excellent |
|--------|----------------|------|-----------|
| IC out-of-sample | > 0.05 | > 0.10 | > 0.20 |
| Hit rate | > 55% | > 60% | > 65% |
| Sharpe | > 0.5 | > 1.0 | > 1.5 |
| Deflated Sharpe | > 0.3 | > 0.7 | > 1.0 |
| ECE (calibration) | < 0.15 | < 0.10 | < 0.05 |
| IC p-value | < 0.05 | < 0.01 | < 0.001 |

---

## Final Recommendation

Fix the operational gaps before adding features. In order:

1. **Fix config path bug** (30 min; single line; critical)
2. **Add GitHub Actions CI** (2 hours; safety net for everything else)
3. **Add structured logging + run IDs** (1 day; transforms observability)
4. **Add CONTRIBUTING.md and PR template** (half day; enables contributors)
5. **Replace xml.etree + add request timeouts** (1 hour; closes two security gaps)
6. **Write pipeline e2e test** (half day; most critical missing test)
7. **Build the backtester** — this is the highest-value technical work and determines whether Phase 6 is worth doing at all.

**What not to build yet:** API, dashboard, PostgreSQL, Docker, Kubernetes, Redis. None of these have users or a validated signal to serve.

---

*See `docs/MIRROR_Future_Roadmap_Production_Plan.html` for the full PDF-ready institutional report with diagrams and tables.*
