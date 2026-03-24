# MIRROR

MIRROR is a Python pipeline that compares three perspectives on a stock:

- Insider activity (SEC Form 4 filing frequency)
- News/media sentiment (weighted by source credibility)
- Market positioning proxy (options put/call ratio)

It then computes a **Cognitive Dissonance Score** from 0 to 100 to highlight where narrative and behavior diverge.

## Why This Exists

Public market narratives can look bullish while insiders and options flows tell a different story. MIRROR helps you spot those mismatches quickly and systematically.

## Features

- Pulls recent insider filings from SEC EDGAR
- Pulls recent financial news from trusted domains via NewsAPI
- Scores sentiment with TextBlob and source weighting
- Pulls price and options metrics with yfinance
- Calculates a weighted dissonance score and risk label
- Exports all intermediate datasets and final rankings as CSV

## Project Structure

- `SEC_INSIDER.PY`: Collects insider filings into `data/insider_filings.csv`
- `NEWS_SENTIMENT.PY`: Collects and scores company news into:
  - `data/news_articles.csv`
  - `data/news_sentiment_summary.csv`
- `price_signal.py`: Collects price/options signals into `data/price_signals.csv`
- `dissonance_calculator.py`: Produces final output in `results/dissonance_scores.csv`
- `run_mirror.py`: Runs the full pipeline end-to-end

## Requirements

- Python 3.10+
- A NewsAPI key: https://newsapi.org

## Setup

1. Create and activate a virtual environment.

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

2. Install dependencies.

```powershell
pip install -r requirements.txt
```

3. Configure environment variables.

```powershell
Copy-Item .env.example .env
```

Then set values in your shell (or load from `.env` with your preferred method):

```powershell
$env:NEWS_API_KEY="your_newsapi_key_here"
$env:SEC_USER_AGENT="MIRROR/1.0 (contact: your_email@example.com)"
```

## Run

Full pipeline:

```powershell
python run_mirror.py
```

Or step-by-step:

```powershell
python SEC_INSIDER.PY
python NEWS_SENTIMENT.PY
python price_signal.py
python dissonance_calculator.py
```

## Output

- Raw datasets in `data/`
- Final ranking in `results/dissonance_scores.csv`

Typical high-level interpretation:

- Higher score: stronger contradiction between insider activity, media narrative, and options behavior
- Lower score: signals are more aligned

## Methodology (Simplified)

For each ticker, MIRROR builds three normalized signals in $[-1, +1]$ and computes:

$$
\text{Dissonance} = 0.50\cdot C_1 + 0.30\cdot C_2 + 0.20\cdot C_3
$$

Where:

- $C_1$: Insider vs Media gap
- $C_2$: Options vs Media gap
- $C_3$: Triple-divergence dispersion term

Final score is scaled to $[0, 100]$.

## Notes

- This project is for research/education.
- It is not investment advice.
- Sentiment and filing-frequency proxies are simplified and should be validated before production use.

## Publish To GitHub (Public)

If this folder is not already a git repository:

```powershell
git init
git branch -M main
git add .
git commit -m "Initial public release: MIRROR pipeline"
```

Create a new public GitHub repo named `MIRROR`, then push:

```powershell
git remote add origin https://github.com/<your-username>/MIRROR.git
git push -u origin main
```

If you use GitHub CLI:

```powershell
gh repo create MIRROR --public --source . --remote origin --push
```
