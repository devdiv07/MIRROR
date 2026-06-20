# MIRROR — Documentation Map (start here to *find* anything)

**Two-doc rule:** [FOCUS.md](FOCUS.md) tells you what to *build* right now. **This INDEX** tells you where to *look* when you need context. Everything else is reference — don't live in it.

_Last organized: June 21, 2026_

---

## Quick decision guide — "I want… → open…"

| If you want to know… | Open |
|---|---|
| What am I building **right now**? | [FOCUS.md](FOCUS.md) |
| Where does the project **actually stand**? | [layer3_current_state.md](layer3_current_state.md) |
| The **big vision** — where is MIRROR going? | [mirror_vision_roadmap.md](mirror_vision_roadmap.md) |
| How do I **harden / productionize** the component? | [roadmap.md](roadmap.md) |
| **How to build** the backtester / optimizer (specs)? | [implementation_plan.md](../implementation_plan.md) |
| How is the **code structured**? | [architecture.md](architecture.md) |
| **Why** did Phase 2 replace Phase 1? | [change_justification.md](change_justification.md) |
| How do I **set up / contribute**? | [contributing.md](../contributing.md) |
| Something to **show a mentor / evaluator**? | the HTML/PDF reports (see #10–12) |

---

## All docs, in reading order

Legend: ✅ current · ⚠️ partly stale (usable) · 🗄️ dated snapshot · 📭 empty

| # | Doc | What it's for | When to open | Status |
|---|---|---|---|---|
| 1 | [FOCUS.md](FOCUS.md) | The one goal, the path, the gate, the ignore-list | **Every session** | ✅ |
| 2 | [layer3_current_state.md](layer3_current_state.md) | Honest current state of Layer 3 + the real backtest read + remaining work | Need current context | ✅ |
| 3 | [mirror_vision_roadmap.md](mirror_vision_roadmap.md) | Whole 5-layer MIRROR north star; honest "signal vs metaphor" grades | Thinking long-term / the *why* | ✅ |
| 4 | [roadmap.md](roadmap.md) | Component (Layer 3) production & hardening roadmap, Phase 3–7 | Planning component infra | ⚠️ (1 stale line: config bug already fixed) |
| 5 | [implementation_plan.md](../implementation_plan.md) | Build specs for backtester / optimizer / risk / stats | Building Step 1+ | ⚠️ legacy-anchored, specs still valid |
| 6 | [architecture.md](architecture.md) | How the system & pipeline are built | Understanding the code | ✅ |
| 7 | [change_justification.md](change_justification.md) | Why Phase 1 → Phase 2 was done | Justifying / explaining changes | ✅ |
| 8 | [contributing.md](../contributing.md) | Setup, coding standards, PR flow | Onboarding / contributing | ✅ |
| 9 | [README.md](../README.md) | Project overview / quickstart | First glance / sharing | ⚠️ stale — fix in Step 0 |
| 10 | [MIRROR_Future_Roadmap_Production_Plan.html](MIRROR_Future_Roadmap_Production_Plan.html) | Polished institutional roadmap report | Sharing / portfolio | 🗄️ Jun-19; hardening claims now done |
| 11 | [MIRROR_Architecture_Report.html](MIRROR_Architecture_Report.html) | Polished institutional architecture report | Sharing / portfolio | 🗄️ Jun-19 snapshot |
| 12 | `Phase Reports PDFs/MIRROR — Architecture…pdf` | PDF export of #11 | Sending a file | 🗄️ Jun-19 snapshot |
| 13 | [backtest_results.md](backtest_results.md) | (reserved) honest backtest findings | Filled in **Step 1** | 📭 empty |
| 14 | [next_steps.md](next_steps.md) | — superseded by FOCUS.md | — | 📭 delete |
| 15 | [audit_findings.md](audit_findings.md) | — covered by layer3_current_state.md | — | 📭 delete |

> GitHub issue/PR templates live in `.github/` — process scaffolding, not reading docs.

---

## The mental model (how the docs nest)

```
FOCUS.md            ← what to do NOW (daily)
  └ layer3_current_state.md   ← where Layer 3 stands (the why behind FOCUS)
      └ roadmap.md            ← how to finish the component
      └ implementation_plan.md← how to build the pieces (specs)
  └ mirror_vision_roadmap.md  ← where the WHOLE project goes (above all of it)

architecture.md / change_justification.md / contributing.md  ← reference, as needed
*.html + *.pdf  ← frozen snapshots for sharing (don't trust for live status)
```

**Live status always comes from #1–#3, never from the HTML/PDF reports** (those are Jun-19 snapshots and predate the Jun-21 hardening).

---

## Recommended cleanup (kills the clutter)

- **Delete** `next_steps.md` (📭, superseded by FOCUS.md) and `audit_findings.md` (📭, covered by layer3_current_state.md).
- **Keep** `backtest_results.md` empty — it's reserved for the Step 1 backtester output.
- **Fix** `README.md` in Step 0.

## Maintenance rule (so this stays clean)

When something changes, update **FOCUS.md** and **layer3_current_state.md**. Do **not** spawn new planning docs — the planning layer is complete.
