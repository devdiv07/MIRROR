# MIRROR — Documentation Map (start here to *find* anything)

**Three-doc rule:** [FOCUS.md](FOCUS.md) tells you what to *build* right now. [PRODUCT.md](PRODUCT.md) tells you *what MIRROR is for*. [ADR 0001](adr/0001-watchlist-event-foundation.md) tells you *how the next code is built*. **This INDEX** tells you where to look for anything else.

_Last organized: 2026-09-23. The active direction changed from "insider IC first" to the watchlist research assistant. Earlier planning docs are kept unchanged as dated research direction._

---

## Quick decision guide — "I want… → open…"

| If you want to know… | Open |
|---|---|
| What am I building **right now**? | [FOCUS.md](FOCUS.md) |
| What is MIRROR **for**, and what is out of scope? | [PRODUCT.md](PRODUCT.md) |
| How is the **next code** designed (data model, provenance, coverage states, sources, PR plan, acceptance tests)? | [adr/0001-watchlist-event-foundation.md](adr/0001-watchlist-event-foundation.md) |
| Which **insider-signal defects** are verified, and how will they be fixed? | [ADR 0001 §12](adr/0001-watchlist-event-foundation.md#12-separate-track-insider-signal-research-blockers) |
| How is the **existing** insider code structured? | [architecture.md](architecture.md) |
| Where did the insider research stand in June 2026? | [layer3_current_state.md](layer3_current_state.md) 🧪 |
| The original **5-layer vision**? | [mirror_vision_roadmap.md](mirror_vision_roadmap.md) 🧪 |
| How do I **set up / contribute**? | [contributing.md](../contributing.md) |

---

## All docs

Legend: ✅ current · ⚠️ accurate for what it covers, with a noted caveat · 🧪 historical research direction (dated; not the active plan) · 🗄️ frozen snapshot · 📭 empty

| # | Doc | What it's for | Status |
|---|---|---|---|
| 1 | [FOCUS.md](FOCUS.md) | The one active outcome, the ordered slice, the do-not-start list | ✅ |
| 2 | [PRODUCT.md](PRODUCT.md) | Product brief: user journey, brief and move card, India/US scope, pilot measures | ✅ |
| 3 | [adr/0001-watchlist-event-foundation.md](adr/0001-watchlist-event-foundation.md) | Architecture decision: modules, provenance (filing vs price claims), coverage states, data model, sources and the India source investigation, acceptance matrix, milestones 0–4 plan, insider blockers | ✅ (Proposed) |
| 4 | [README.md](../README.md) | Code status, run and test commands | ✅ |
| 5 | [architecture.md](architecture.md) | How the **existing** insider and legacy pipelines are built (June 2026). It describes the insider aggregation as intended; the actual sign behaviour is in ADR §12 (B1) | ⚠️ existing code only |
| 6 | [contributing.md](../contributing.md) | Setup, coding standards, PR flow | ✅ |
| 7 | [layer3_current_state.md](layer3_current_state.md) | June 21 state of the insider/dissonance research, including the inconclusive bucket backtest. Its "do not start anything until the IC gate" conclusion is **superseded** for the product by FOCUS.md | 🧪 Jun-21 |
| 8 | [mirror_vision_roadmap.md](mirror_vision_roadmap.md) | Original 5-layer north star with "signal vs metaphor" grades | 🧪 Jun-21 |
| 9 | [roadmap.md](roadmap.md) | Insider component hardening/production roadmap (Phases 3–7) | 🧪 Jun-19 |
| 10 | [implementation_plan.md](../implementation_plan.md) | Specs for backtester / optimizer / risk / stats (legacy-anchored) | 🧪 research track |
| 11 | [change_justification.md](change_justification.md) | Why the insider Phase 1 → Phase 2 rebuild was done | 🧪 |
| 12 | [MIRROR_Future_Roadmap_Production_Plan.html](MIRROR_Future_Roadmap_Production_Plan.html) | Polished roadmap report | 🗄️ Jun-19 |
| 13 | [MIRROR_Architecture_Report.html](MIRROR_Architecture_Report.html) | Polished architecture report | 🗄️ Jun-19 |
| 14 | `Phase Reports PDFs/MIRROR — Architecture…pdf` | PDF export of #13 | 🗄️ Jun-19 |
| 15 | [backtest_results.md](backtest_results.md) | Reserved for insider backtest findings (research track T7) | 📭 empty |
| 16 | [runs/](runs/) | Run notes: what a live run did and found, e.g. [the first live SEC ingest](runs/2026-09-23-sec-live-check.md) | ✅ |

> The previous index listed `next_steps.md` and `audit_findings.md`. Neither file exists in the repository at `e068c91`, so they have been removed from this map.
> GitHub issue/PR templates live in `.github/`. They are process scaffolding, not reading docs.

---

## The mental model (how the docs nest)

```
FOCUS.md                         ← what to do NOW
  └ PRODUCT.md                   ← what the product is for, and how the pilot is judged
      └ adr/0001-…md             ← how the first slice is built + verified insider defects (§12)

Research track (dated, not the active plan):
  layer3_current_state.md · mirror_vision_roadmap.md · roadmap.md · implementation_plan.md

architecture.md / change_justification.md / contributing.md  ← reference for existing code
*.html + *.pdf  ← frozen snapshots (don't trust for live status)
```

**Live status comes from #1–#4.** Never take it from the 🧪 or 🗄️ documents.

## Maintenance rule

When the active task changes, update **FOCUS.md**. When a design decision changes, add a new ADR (`docs/adr/000N-…md`) instead of editing an accepted one. Do not rewrite historical research documents. Mark them here instead.
