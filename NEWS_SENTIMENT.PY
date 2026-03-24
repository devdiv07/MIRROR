import requests
import pandas as pd
from textblob import TextBlob
from datetime import datetime, timedelta
import time
import os
# ============================================
# YOUR NEWSAPI KEY GOES HERE
# Get it from: https://newsapi.org/
# ============================================
NEWS_API_KEY = os.getenv('NEWS_API_KEY', '').strip()
# Companies to monitor
# Using full names because NewsAPI searches by name, not ticker
#the ticker is used for mapping to CIK and for labeling the data, but the company name is used for searching news articles.
COMPANIES = {
    'AAPL':  'Apple',
    'MSFT':  'Microsoft', 
    'NVDA':  'Nvidia',
    'TSLA':  'Tesla',
    'JPM':   'JPMorgan',
    'GS':    'Goldman Sachs',
    'META':  'Meta',
    'GOOGL': 'Google',
    'AMZN':  'Amazon',
    'NFLX':  'Netflix'
}

# ============================================
# LAYER 1: Trusted Financial News Sources Only
# These domains publish legitimate financial news
# ============================================
FINANCIAL_DOMAINS = [# financia_domain this line mean that the list of trusted financial news sources is defined in the variable FINANCIAL_DOMAINS. This list includes popular and reputable financial news websites such as reuters.com, bloomberg.com, cnbc.com, wsj.com, marketwatch.com, finance.yahoo.com, ft.com, barrons.com, investopedia.com, seekingalpha.com, fool.com, businessinsider.com, and forbes.com. By specifying these domains in the NewsAPI request parameters, the code ensures that it only retrieves news articles from these trusted sources, which increases the likelihood of getting accurate and relevant financial news for sentiment analysis.
    'reuters.com', 'bloomberg.com', 'cnbc.com', 'wsj.com',
    'marketwatch.com', 'finance.yahoo.com', 'ft.com',
    'barrons.com', 'investopedia.com', 'seekingalpha.com',
    'fool.com', 'businessinsider.com', 'forbes.com'
]

# ============================================
# LAYER 3: Financial Relevance Keywords
# Articles with these terms are more likely real stock news
# ============================================
FINANCIAL_KEYWORDS = [
    'stock', 'shares', 'trading', 'nyse', 'nasdaq', 'sec', 
    'earnings', 'revenue', 'quarterly', 'dividend', 'ipo',
    'market cap', 'analyst', 'upgrade', 'downgrade', 'ceo',
    'quarterly report', 'fiscal', 'investor', 'wall street'
]

# ============================================
# LAYER 4: Blacklist Terms - Reject if found
# These indicate non-financial garbage content
# ============================================
BLACKLIST_TERMS = [
    'recipe', 'cooking', 'music review', 'album review', 
    'tv show', 'movie review', 'fashion', 'jeans', 'playlist',
    'apple pie', 'apple cider', 'apple watch band', 'apple music',
    'netflix show', 'amazon prime video', 'google maps directions',
    'facebook friend', 'instagram post', 'tiktok', 'youtube video'
]

# Minimum relevance score to keep an article
MIN_RELEVANCE_SCORE = 2

def calculate_relevance_score(headline, description, ticker):
    """
    LAYER 3 & 4: Score how likely this is REAL financial news vs garbage.
    
    Scoring:
    - Ticker symbol mentioned: +3 (strong signal)
    - Each financial keyword: +1
    - Each blacklist term: -5 (likely garbage)
    
    Returns: Integer score. Higher = more likely real financial news.
    """
    text = f"{headline} {description}".lower()
    score = 0
    
    # Ticker mentioned = strong signal (financial articles use tickers)
    if ticker.lower() in text:
        score += 3
    
    # Financial terms = good signal
    for term in FINANCIAL_KEYWORDS:
        if term in text:
            score += 1
    
    # Blacklist terms = reject (likely garbage)
    for term in BLACKLIST_TERMS:
        if term in text:
            score -= 5
    
    return score

def analyze_sentiment(text):
    """Use TextBlob to get sentiment polarity of text
     
    Use TextBlob to analyze sentiment of a headline.
    
    Returns a score:
    -1.0 = Very negative (crash, fraud, lawsuit)
     0.0 = Neutral (earnings report, announcement)
    +1.0 = Very positive (record profit, innovation)
    
    This is the "what media is SAYING" component.
    """
    if not text:
        return 0.0
    blob = TextBlob(text)
    return round(blob.sentiment.polarity, 3)#this line rounds the sentiment score to 3 decimal places for better readability and consistency in the output.here 3 is used as an argument to the round() function to specify the number of decimal places to round to. You can adjust this value based on your preference for precision.

def get_source_credebility_weight(source_name):
     """
    Weight articles by source credibility.
    
    Not all news sources are equal. Bloomberg reporting earnings
    is more credible than a random blog reporting the same thing.
    
    Tier 1 (Premium): 1.5x weight - Institutional sources
    Tier 2 (Mainstream): 1.0x weight - Standard financial media  
    Tier 3 (Other): 0.7x weight - Less established sources
    
    This prevents low-quality noise from polluting sentiment scores.
    """
    #handle noneor empty source names
     if not source_name:
        return 0.7  # Default to lowest weight if source is unknown
     source_lower = source_name.lower()
     # Tier 1: Premium institutional financial news
    # These sources have research teams, fact-checkers, legal review
     tier_1_sources = [
        'bloomberg',
        'reuters', 
        'wall street journal',
        'wsj',
        'financial times',
        'ft.com',
        'dow jones'
    ]
    
    # Tier 2: Mainstream financial media
    # Reputable but less rigorous than Tier 1
     tier_2_sources = [
        'cnbc',
        'marketwatch',
        'seeking alpha',
        'barrons',
        'yahoo finance',
        'investing.com',
        'benzinga',
        'thestreet',
        'forbes',
        'business insider'
    ]
     #check which tier the source belong to
     for tier_1 in tier_1_sources:
         if tier_1 in source_lower:
                return 1.5 #premium sources get 1.5x weight
     
     for tier_2 in tier_2_sources:
         if tier_2 in source_lower:
                return 1.0  # mainstream sources get 1.0x weight
     
     # If not found in tier 1 or tier 2, return 0.7 for other sources
     return 0.7  # down weight less credible sources to prevent noise in sentiment scores

def get_news_for_company(ticker, company_name):
    """ Hit NewsAPI and get recent headlines about one company.
    
    4-LAYER FILTERING:
    Layer 1: Only trusted financial news domains
    Layer 2: Query includes ticker symbol (financial articles use tickers)
    Layer 3: Post-filter by financial keyword relevance score
    Layer 4: Reject articles with blacklist garbage terms
    """
    url = "https://newsapi.org/v2/everything"

    if not NEWS_API_KEY:
        print("ERROR: NEWS_API_KEY is not set. Add it to your environment first.")
        return []
    
    # LAYER 2: Search query includes TICKER (not just company name)
    # Financial articles almost always mention the ticker symbol
    # Recipe blogs and product reviews don't use "AAPL" or "MSFT"
    search_query = f'({ticker} OR "{company_name}") AND (stock OR shares OR trading OR earnings OR investor)'

    # NewsAPI parameters
    params = {
        'q': search_query,
        'domains': ','.join(FINANCIAL_DOMAINS),  # LAYER 1: Only trusted sources
        'language': 'en',
        'sortBy': 'publishedAt',  # Get most recent news first
        'apiKey': NEWS_API_KEY,
        'pageSize': 20,  # Fetch more since we'll filter some out
        'from': (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    }
    
    try:
        response = requests.get(url, params=params)# params=params means that the parameters defined in the params dictionary will be sent as query parameters in the GET request to the NewsAPI endpoint. This allows us to specify our search criteria and API key when making the request.
        if response.status_code != 200:
            print(f"ERROR: NewsAPI returned {response.status_code} for {ticker}")
            return[]
        data = response.json()
        #check if we hit rate limit
        if data.get('status') == 'error':
            print(f"error:{data.get('message', 'Unknown error')}")
            return []
        articles = []
        filtered_count = 0  # Track how many we reject
        
        for article in data.get('articles', []):
            headline = article.get('title', '')
            description = article.get('description', '')

            # Combine headline and description for analysis
            full_text = f"{headline} {description}"
            if not full_text.strip():
                continue
            
            # LAYER 3 & 4: Calculate relevance score
            relevance = calculate_relevance_score(headline, description, ticker)
            
            # Reject low-relevance articles (likely garbage)
            if relevance < MIN_RELEVANCE_SCORE:
                filtered_count += 1
                continue
            
           # NEW VERSION (with source weighting):
            source_name = article.get('source', {}).get('name', 'unknown')
            #calculate RAW sentiment from textblob
            raw_sentiment = analyze_sentiment(f"{headline} {description}")
            #get source credibility weight
            source_weight = get_source_credebility_weight(source_name)
            
            # Apply weight to sentiment
            # Example: Raw sentiment +0.6 from Bloomberg (1.5x) = +0.9 final
            # Example: Raw sentiment +0.6 from random blog (0.7x) = +0.42 final
            weighted_sentiment = round(raw_sentiment * source_weight, 3)
            articles.append({
                'ticker': ticker,
                'company': company_name,
                'headline': headline,
                'description': description,
                'raw_sentiment': raw_sentiment,
                'source_weight': source_weight,
                'sentiment_score': weighted_sentiment,
                'relevance_score': relevance,  # Track relevance for debugging
                'publishedAt': article.get('publishedAt', ''),
                'source': source_name,
                'url': article.get('url', '')
            })
        
        if filtered_count > 0:
            print(f"  (filtered out {filtered_count} low-relevance articles)")
        
        return articles
    except Exception as e:
        print(f"ERROR: Failed to get news for {ticker}: {e}")
        return []
def collect_all_news():
    """
    Loop through all companies.
    Collect news headlines.
    Analyze sentiment.
    Calculate average sentiment per company.
    
    This gives us the "market narrative" for each stock.
    """
    
    print("=" * 50)
    print("MIRROR - News Sentiment Collector")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    all_articles = []
    for ticker, company_name in COMPANIES.items():
        print(f"\nfetching news for {ticker} ({company_name})...")
        articles = get_news_for_company(ticker, company_name)
        count = len(articles)
        all_articles.extend(articles)

        if count > 0:
            avg_sentiment = round(sum(a['sentiment_score'] for a in articles) / count, 3)
            print(f"found {count} articles")
            print(f"average sentiment score: {avg_sentiment:.3f}")
        else:
            print("no articles found")

            # IMPORTANT: Wait 1 second between requests to avoid hitting NewsAPI rate limits
        time.sleep(1)
    # convert to DataFrame and save to CSV
    df = pd.DataFrame(all_articles)
    if df.empty:
        print("No news articles found. Exiting.")
        return df,pd.DataFrame() # Return empty DataFrames if no articles found
    #calculate average sentiment per company
    sentiment_summary = df.groupby(['ticker', 'company']).agg({
        'sentiment_score': ['mean', 'count', 'std', 'min', 'max']
    }).round(3)
    sentiment_summary.columns = ['avg_sentiment', 'article_count', 'sentiment_std', 'min_sentiment', 'max_sentiment']
    sentiment_summary = sentiment_summary.reset_index()

#save both detailed articles and summary to CSV
    os.makedirs('data', exist_ok=True)
    df.to_csv('data/news_articles.csv', index=False)
    sentiment_summary.to_csv('data/news_sentiment_summary.csv', index=False)

    print("\n" + "=" * 50)
    print(f"total articles collected: {len(df)}")
    print(f"Saved detailed articles to: data/news_articles.csv")
    print(f"Saved sentiment summary to: data/news_sentiment_summary.csv")
    print("=" * 50)

    return df, sentiment_summary

def display_sentiment_summary(summary_df):
    """
    Pretty print the sentiment summary.
    This shows us which stocks have positive vs negative media coverage.
    """
    
    if summary_df.empty:
        print("No data to display.")
        return
    
    print("\n=== NEWS SENTIMENT SUMMARY ===\n")

    # Sort_by_sentiment (most positive first)
    summary_df = summary_df.sort_values('avg_sentiment', ascending=False)
    
    for _, row in summary_df.iterrows():
        ticker = row['ticker']
        company = row['company']
        avg_sent = row['avg_sentiment']
        count = row['article_count']
        
        # Classify sentiment
        if avg_sent > 0.15:
            classification = "BULLISH ↑"
        elif avg_sent > 0.05:
            classification = "Slightly Positive"
        elif avg_sent > -0.05:
            classification = "NEUTRAL"
        elif avg_sent > -0.15:
            classification = "Slightly Negative"
        else:
            classification = "BEARISH ↓"
        
        print(f"{ticker:6} | {company:15} | Sentiment: {avg_sent:+.3f} | {classification:20} | Articles: {count}")

def show_most_extreme_headlines(df):
     """
    Show the most positive and most negative headlines.
    This helps us understand what is driving sentiment.
    """
     if not df.empty:
         print("\n======MOST BULLISH HEADLINES======")
         bullish = df.nlargest(5, 'sentiment_score')
         for _, row in bullish.iterrows():
             print(f"{row['ticker']:6} |  Sentiment: {row['sentiment_score']:+.2f} | {row['headline']}")

         print("\n======MOST BEARISH HEADLINES======")
         bearish = df.nsmallest(5, 'sentiment_score')
         for _, row in bearish.iterrows():
                print(f"{row['ticker']:6} |  Sentiment: {row['sentiment_score']:+.2f} | {row['headline']}")

def show_source_quality_breakdown(df):
    """
    Show how many articles came from each source tier.
    This helps you understand if your data is high quality or noisy.
    """
    if  df.empty:
        return
    print("\n=== SOURCE QUALITY BREAKDOWN ===\n")
    #classify each article sources
    tier_1_count = 0
    tier_2_count = 0
    tier_3_count = 0
    for _, row in df.iterrows():
        weight = row['source_weight']
        if weight >= 1.4:
            tier_1_count += 1
        elif weight >= 0.9:
            tier_2_count += 1
        else:
            tier_3_count += 1
    total = len(df)
    print(f"Tier 1 (Premium): {tier_1_count:3} articles ({tier_1_count/total*100:5.1f}%) - Bloomberg, Reuters, WSJ")
    print(f"Tier 2 (Mainstream): {tier_2_count:3} articles ({tier_2_count/total*100:5.1f}%) - CNBC, MarketWatch, etc")
    print(f"Tier 3 (Other):      {tier_3_count:3} articles ({tier_3_count/total*100:5.1f}%) - Unknown sources")
    print(f"{'-'*60}")
    print(f"Total:        {total:3} articles")
    
    #Quality score: higher % of Tier 1 = better quality data
    quality_score = (tier_1_count * 1.5 + tier_2_count * 1.0 + tier_3_count * 0.7) / total
    print(f"\nData Quality Score: {quality_score:.2f}/1.5")
    
    if quality_score > 1.2:
        print("✓ Excellent data quality - mostly premium sources")
    elif quality_score > 0.9:
        print("✓ Good data quality - mix of credible sources")
    else:
        print("⚠ Fair data quality - many unknown sources")

#=============RUN EVERYTHING================
articles_df, summary_df = collect_all_news()
display_sentiment_summary(summary_df)
show_source_quality_breakdown(articles_df)  # NEW: Show source quality
show_most_extreme_headlines(articles_df)

print("\n✓ Done. Check data/ folder for CSV files.")
print("✓ Sentiment scores are now weighted by source credibility.")