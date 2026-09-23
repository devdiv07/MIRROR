# MIRROR — Product brief

_Status: active direction as of 2026-09-23. Architecture: [adr/0001-watchlist-event-foundation.md](adr/0001-watchlist-event-foundation.md). Current task: [FOCUS.md](FOCUS.md)._

## What MIRROR is for

MIRROR is a **personal, source-linked research assistant for a watchlist of India and US stocks**. Its owner has limited research time each day. MIRROR answers four questions:

1. **What changed?** Which material company, industry or macro events happened for my stocks since I last checked?
2. **Why did it move?** When a watched stock makes a large move (for example +10% in one session), what is the evidence, when was each piece available, and what is still unknown?
3. **Does it matter for my thesis?** Do the new facts strengthen or weaken my saved thesis, or leave it unresolved?
4. **What should I look at next?** Which filings, results or numbers should I read before making **my own** decision?

MIRROR does not tell the owner what to buy or sell, does not predict prices, and makes **no claim to improve returns**.

## Research utility versus predictive alpha

| | Research utility (this product) | Predictive alpha (separate research track) |
|---|---|---|
| Question | Did MIRROR surface the right facts, correctly dated and sourced, faster than I would have found them? | Does a score predict forward returns? |
| Evidence needed | Source links, timestamps, reproducible numbers, owner feedback | Point-in-time backtests with out-of-sample IC, enough independent events |
| Status | Not built yet; first slice defined in the ADR | The insider conviction score is **unvalidated** and has confirmed defects ([ADR §12](adr/0001-watchlist-event-foundation.md#12-separate-track-insider-signal-research-blockers)) |
| Can gate the other? | No | No. The product does not wait for an IC result, and product usefulness is not evidence of alpha |

## Primary user journey (pilot)

1. **Set up once.** The owner adds 10–20 stocks they already follow (NSE and US listings). For each they save a short **thesis** and a **horizon** (for example "margin recovery as input costs fall — 2–3 years"). They can also set a **move trigger** per stock; otherwise a global one applies.
2. **Each morning.** The owner opens `briefs/YYYY-MM-DD.md`. How long it takes to read is one of the pilot measures, not an assumption. It contains:
   - A header with when the data was last refreshed from each source, and any source that failed.
   - **What changed:** new official disclosures per stock since the last brief, each with a link and its publication time.
   - **Unusual-move cards** for stocks that crossed their trigger.
   - **Coverage**, one group per state, so that silence never means "nothing happened":
     - *Checked, new disclosures above*: the source was checked for the whole window, and what it found is listed under "What changed".
     - *Checked, no new disclosures*: the source was checked for the whole window and returned nothing.
     - *Not checked*: no check covers the window. For NSE this means the owner has not recorded a manual check. Entering an event does not count as checking.
     - *Source failed*: the source was tried and failed.
     - *Coverage incomplete*: only part of the window, or part of the source, was checked.
3. **Correct and record.** From the CLI, the owner marks items relevant or not relevant, flags a wrong attribution, reports a missed event, or updates a thesis. Everything is kept as history.
4. **Decide.** The owner reads the linked primary documents and makes their own decision. MIRROR records nothing about trades.

## Unusual-move card (shape, not real data)

```
<SYMBOL> (NSE) · session YYYY-MM-DD · +X.X% adjusted from previous close
Market-relative: +Y.Y% vs <benchmark> · Volume: Z.Z× 20-session median
Prices: owner-supplied file <name> · sha256 <12 hex> · imported <time IST> · upstream source: <vendor | UNKNOWN>
Trace: close(D) <x> vs close(D-1) <y> ÷ k=<k> · calc <version>
Coverage: NSE checked through <time> (manual)

Evidence label: DOCUMENTED EVENT (preceded the move; causation not established)
  • [pre-open 08:40 IST] "<verbatim NSE subject>" — <link> (entered <time>)
Reported after the move:
  • (none)
Competing factors: benchmark moved +W.W%; no corporate action on this date
Your thesis (2–3 yrs): "<saved text>" → relevance: not yet assessed (your call)
Missing: no intraday prices (order of disclosure vs move unknown); NSE covered by manual entry only
```

There are five evidence labels:
- **documented event**
- **multiple factors**
- **plausible association**
- **no verified explanation yet**, used only when every required source was checked for the move window
- **no evidence — coverage incomplete**, used when a source was not checked, failed, or was only partly checked

When coverage is incomplete, the card's **first line** says so, whatever the label. The rules are in [ADR §8](adr/0001-watchlist-event-foundation.md#8-explanation-contract). A news article published near a move does not establish its cause. MIRROR never shows statements like "92% chance this caused the jump".

## Initial scope

| | India | US |
|---|---|---|
| Listings | NSE equities on the owner's watchlist | NYSE/Nasdaq equities on the owner's watchlist |
| Company disclosures | **Manual entry for now**, plus a manual "checked through" record. NSE's website terms prohibit systematic automated collection ([NSE terms of use](https://www.nseindia.com/static/nse-terms-of-use)). NSE also offers [RSS feeds](https://www.nseindia.com/static/rss-feed) and paid [data products](https://www.nseindia.com/static/nse-data-and-analytics), but whether either permits MIRROR's use is **unresolved**. A time-bounded source investigation ([ADR §4.3](adr/0001-watchlist-event-foundation.md#43-india-source-investigation-time-bounded-decides-india-automation)) decides it | **Automatic** from the SEC EDGAR submissions API: 8-K, 10-Q, 10-K, Form 4. Free reuse is documented ([SEC webmaster FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions)) |
| Prices | Daily bars imported from a CSV the owner supplies. **The upstream source is not yet chosen** (ADR Q2). Until it is, cards show "upstream source: unknown" with the file hash and calculation trace | Same |
| Corporate actions | Manual entry (splits, bonus issues, dividends, symbol changes) | Manual entry in slice 1 |
| Macro | Not in slice 1; sources not yet verified | FRED in slice 2 (API key and attribution required: [FRED API terms](https://fred.stlouisfed.org/docs/api/terms_of_use.html)) |
| Timezone / currency | Asia/Kolkata, INR | America/New_York, USD |

MIRROR **does not currently have India coverage**. Everything in the India column is planned. With manual entry, India is a **data-model prototype**. It tests whether the event, coverage and move model works for Indian listings, but it cannot show that MIRROR saves research time, because the owner is doing the source-watching themselves.

## Out of scope (for the pilot)

- Buy/sell recommendations, price targets, portfolio construction, position sizing, order placement.
- Claims of improved returns, and any probability or confidence percentage without a validated model.
- Intraday alerts. They would need a dependable, permitted real-time feed, and none has been identified.
- Scraping NSE/BSE pages. Polling NSE RSS or buying a feed only happens after the source investigation records a permission (ADR §4.3). No redistribution of any exchange or vendor data.
- A web UI, multi-user access, hosting, and paid feeds. Revisit after the pilot.
- LLM-generated numbers. An LLM may later help with wording, only around numbers that were already computed.
- Using the insider conviction score as a product signal.

## Pilot and measurable feedback

A **time-saving pilot** runs only where event coverage is measured by the source, not by the owner's own entry:

- **US pilot:** 10–20 of the owner's US stocks for at least 4 weeks, starting after the brief ships (ADR §13, Milestone 4). SEC coverage is recorded automatically.
- **India:** runs alongside as a prototype. It joins the time-saving pilot only after the source investigation (ADR §4.3) establishes a route whose coverage is measurable without relying on the owner's own entry.

The measures below come from the `feedback` table, the coverage records and the brief files. Targets other than the hard gates are set **after** week 1 establishes a baseline. Nothing here is a claim about markets, and nothing here claims time is saved until the measurements say so.

| Measure | How it is computed | Hard gate? |
|---|---|---|
| Filing-claim provenance | Share of filing claims with a working source link, a publication time (and its basis) and a first-seen time | **Yes — 100%** |
| Price-claim provenance | Share of price numbers with import identity, file hash, observation time and calculation trace. An unknown upstream source is allowed but must be shown as "unknown" | **Yes — 100%** |
| Coverage honesty | Securities shown as "checked, no new disclosures" without a successful check spanning the window | **Yes — 0** |
| Number reproducibility | Brief numbers recomputed from stored rows by tests | **Yes — 100%** |
| As-of correctness | Brief items with `first_seen_at` after the brief's as-of time | **Yes — 0** |
| Relevance precision | `relevant / (relevant + not_relevant)` over "What changed" items | Baseline in week 1 |
| Missed events | Count of `missed_event` reports per week (the owner found something MIRROR did not show) | Baseline in week 1 |
| Attribution errors | Count of `wrong_attribution` on move cards | Baseline; every case gets reviewed |
| Duplicates | Repeated events in a brief | Target 0 |
| Unexplained moves | Share of cards labelled "no verified explanation yet", reported separately from "no evidence — coverage incomplete". Reported honestly; it is not a failure metric | Informational |
| Coverage | Per market and week: the share of (security, day) pairs in each of the five coverage states | Informational; decides when a market can join the time-saving pilot |
| Time spent | Owner's self-reported minutes per brief, **plus** minutes spent on manual NSE entry and checks, noted weekly | Informational |

**After the pilot:** keep going, change course, or stop, based on these numbers and the owner's judgement. Nothing about predictive performance can be concluded from the pilot.
