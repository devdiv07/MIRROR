# MIRROR

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Data Source: SEC](https://img.shields.io/badge/Data-SEC%20EDGAR-0052CC)](https://www.sec.gov/edgar)
[![Data Source: NewsAPI](https://img.shields.io/badge/Data-NewsAPI-1A1A1A)](https://newsapi.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

MIRROR is a market intelligence pipeline that detects cognitive dissonance between:

- What insiders do (SEC Form 4 activity)
- What media says (financial-news sentiment)
- What options flow implies (put/call behavior)

It outputs a Dissonance Score from 0 to 100 for each stock, highlighting where public narrative and market behavior diverge.

## Executive Summary

Financial narratives can stay optimistic while informed participants hedge or distribute risk. MIRROR turns that mismatch into a measurable signal so you can rank symbols by narrative fragility instead of relying on headlines alone.

## Core Capabilities

- Collects insider transaction filings from SEC EDGAR
- Collects and filters financial news from trusted domains
- Computes weighted sentiment with source-credibility tiers
- Extracts price, volume, and options signals from Yahoo Finance
- Computes multi-component dissonance scores and risk labels
- Saves all intermediate datasets for full auditability

## System Architecture

```text
SEC_INSIDER.PY       -> data/insider_filings.csv
NEWS_SENTIMENT.PY    -> data/news_articles.csv
                     -> data/news_sentiment_summary.csv
price_signal.py      -> data/price_signals.csv

dissonance_calculator.py
  + insider_filings
  + news_sentiment_summary
  + price_signals
  -> results/dissonance_scores.csv
```

## Repository Layout

- SEC_INSIDER.PY: insider filings collector (Form 4)
- NEWS_SENTIMENT.PY: news collection, filtering, sentiment scoring
- price_signal.py: market and options feature extraction
- dissonance_calculator.py: signal fusion and score computation
- run_mirror.py: full end-to-end pipeline runner
- data/: generated intermediate artifacts
- results/: final ranked outputs

## Methodology

For each ticker, MIRROR computes three normalized signals in [-1, +1]:

- Insider signal: proxy from recent Form 4 filing activity
- Media signal: weighted average sentiment
- Options signal: mapped from put/call ratio

Then it calculates three dissonance components:

- C1 = Insider-Media gap
- C2 = Options-Media gap
- C3 = Triple-divergence dispersion

Final score:

$$
	ext{Dissonance} = 100 \times (0.50\cdot C_1 + 0.30\cdot C_2 + 0.20\cdot C_3)
$$

Risk bands:

- 75-100: CRITICAL
- 60-74: HIGH
- 40-59: MODERATE
- 25-39: LOW
- 0-24: MINIMAL

## Data Quality Controls

NEWS_SENTIMENT.PY applies four filtering layers before sentiment is used:

- Trusted-domain allowlist for financial publishers
- Query design that includes ticker context
- Relevance scoring with financial keywords
- Blacklist terms to reject non-financial noise

It also applies source-credibility weighting to reduce low-quality signal contamination.

## Setup

### 1. Prerequisites

- Python 3.10+
- NewsAPI account and API key

### 2. Create environment

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Configure secrets

Copy the template and set required values:

```powershell
Copy-Item .env.example .env
```

Set variables in your shell (or load from your preferred env manager):

```powershell
$env:NEWS_API_KEY="your_newsapi_key_here"
$env:SEC_USER_AGENT="MIRROR/1.0 (contact: your_email@example.com)"
```

## Usage

Run complete pipeline:

```powershell
python run_mirror.py
```

Or run each stage manually:

```powershell
python SEC_INSIDER.PY
python NEWS_SENTIMENT.PY
python price_signal.py
python dissonance_calculator.py
```

## Outputs

- data/insider_filings.csv
- data/news_articles.csv
- data/news_sentiment_summary.csv
- data/price_signals.csv
- results/dissonance_scores.csv

Interpretation guide:

- Higher score: stronger contradiction between narrative and behavior
- Lower score: stronger alignment across signals

## Public Release Checklist (GitHub)

### Option A: GitHub CLI (fastest)

```powershell
git add .
git commit -m "Public release: MIRROR v1"
gh repo create MIRROR --public --source . --remote origin --push
```

### Option B: GitHub web UI + git

```powershell
git add .
git commit -m "Public release: MIRROR v1"
git branch -M main
git remote add origin https://github.com/<your-username>/MIRROR.git
git push -u origin main
```

Recommended repository settings after publish:

- Add topics: quant, finance, sentiment-analysis, sec-edgar, options, python
- Add social preview image
- Enable Discussions (optional)
- Protect main branch and require PRs for future changes

## Limitations

- Insider signal currently uses filing frequency proxy, not transaction-level buy/sell parsing
- News sentiment is lexical and may miss deep context
- Options signal is simplified to put/call interpretation
- API coverage and rate limits can affect timeliness

## Roadmap

- Parse Form 4 transactions directly for net insider buy/sell intensity
- Add rolling z-score normalization by ticker regime
- Add backtesting module for dissonance-to-forward-return analysis
- Add dashboard and scheduled daily runs
- Add unit tests and CI pipeline

## Compliance and Disclaimer

This repository is for research and education only. It is not investment advice. Always perform independent due diligence and consult licensed financial professionals before making investment decisions.

## License

MIT License. See [LICENSE](LICENSE).
