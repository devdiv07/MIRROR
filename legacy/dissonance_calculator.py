import pandas as pd
import numpy as np
import os
from datetime import datetime, timedelta

def load_all_data():
    """
    Load all three data sources:
    1. Insider filings (what insiders DO)
    2. News sentiment (what media SAYS)
    3. Price signals (what smart money DOES quietly)
    
    Returns three DataFrames.
    """

    try:
        insider_df = pd.read_csv('data/insider_transactions.csv')
    except:
        print("⚠ Warning: No insider data found. Run insider_parser.py first.")
        insider_df = pd.DataFrame()
    try:
        news_df = pd.read_csv('data/news_sentiment_summary.csv')
    except:
        print("⚠ Warning: No news sentiment data found. Run NEWS_SENTIMENT.PY first.")
        news_df = pd.DataFrame()
    try:
        price_df = pd.read_csv('data/price_signals.csv')
    except:
        print("⚠ Warning: No price signal data found. Run price_signal.py first.")
        price_df = pd.DataFrame()

    return insider_df, news_df, price_df

def calculate_insider_signals(ticker, insider_df):
    """
    Convert insider filings into a single signal: -1 to +1
    
    -1 = Heavy insider selling (they know something bad)
     0 = No significant activity
    +1 = Heavy insider buying (they know something good)
    
    Logic:
    - More Form 4 filings in recent period = more activity
    - We can't see BUY vs SELL from basic API (need deeper parsing)
    - So we use filing FREQUENCY as a proxy
    - Sudden spike in filings = insiders are active = signal
    
    NOTE: This is simplified. Real version would parse each
    Form 4 to see if it was a buy or sell transaction.
    """
    if insider_df.empty:
        return 0.0, "No Data"

    ticker_tx = insider_df[insider_df['ticker'] == ticker].copy()
    if len(ticker_tx) == 0:
        return 0.0, "No transactions"

    ticker_tx['date'] = pd.to_datetime(ticker_tx['date'], errors='coerce')
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=30)
    recent = ticker_tx[ticker_tx['date'] > cutoff]

    if len(recent) == 0:
        return 0.0, "No recent transactions (30d)"

    net_dollars = recent['dollar_value'].sum()
    buy_count   = (recent['transaction_type'] == 'BUY').sum()
    sell_count  = (recent['transaction_type'] == 'SELL').sum()

    # Signal strength based on net dollar volume of open-market trades.
    # Buying = insider paid market price = conviction signal.
    # Thresholds match insider_parser.net_insider_signal_per_ticker().
    if net_dollars > 1_000_000:
        signal = 0.7    # Heavy net buying
    elif net_dollars > 100_000:
        signal = 0.3    # Mild net buying
    elif net_dollars < -1_000_000:
        signal = -0.7   # Heavy net selling
    elif net_dollars < -100_000:
        signal = -0.3   # Mild net selling
    else:
        signal = 0.0    # No significant open-market activity

    note = f"Net: ${net_dollars:+,.0f} ({buy_count}B/{sell_count}S)"
    return signal, note
    
def calculate_media_signals(ticker, news_df):
     """
    Convert news sentiment into a single signal: -1 to +1
    
    -1 = Very bearish media coverage
     0 = Neutral coverage
    +1 = Very bullish media coverage
    
    This comes directly from our weighted sentiment analysis.
    """
     if news_df.empty:
        return 0.0, "No Data" #No data = neutral signal
     
     # Find this ticker in news data
     ticker_news = news_df[news_df['ticker']==ticker]
     if len(ticker_news) == 0:
        return 0.0, "No News" #No news for this ticker = neutral signal
     
     # Get average sentiment (already weighted by source credibility)
     avg_sentiment = ticker_news['avg_sentiment'].iloc[0]
     article_count = ticker_news['article_count'].iloc[0]

      # Sentiment is already -1 to +1 scale from TextBlob
     return avg_sentiment, f"{article_count} articles"

def calculate_options_signal(ticker, price_df):
    """
    Convert put/call ratio into a signal: -1 to +1
    
    High put/call = smart money buying protection = bearish signal
    Low put/call = confidence = bullish signal
    """
    if price_df.empty:
        return 0.0,"No Data" #No data = neutral signal
    
    ticker_price = price_df[price_df['ticker']==ticker]
    if len(ticker_price) == 0:
        return 0.0,"NO Price Data" #No price data for this ticker = neutral signal
    pc_ratio = ticker_price['put_call_ratio'].iloc[0]

    if pd.isna(pc_ratio):
        return 0.0,"No valid P/C ratio" #No valid ratio = neutral signal
    
    # Normal P/C ratio is around 0.7-1.0
    # Above 1.3 = bearish (lots of puts being bought)
    # Below 0.5 = bullish (lots of calls being bought)
    if pc_ratio > 1.5:
        signal = -0.8
    elif pc_ratio > 1.2:
        signal = -0.5
    elif pc_ratio < 0.5:
        signal = +0.5
    elif pc_ratio < 0.7:
        signal = +0.3
    else:
        signal = 0
    
    return signal, f"P/C: {pc_ratio:.2f}"#.2f for 2 decimal places which works to make it more readable

def calculate_dissonance_score(ticker, insider_df, news_df, price_df):
     """
    THE CORE CALCULATION OF MIRROR
    
    Calculate cognitive dissonance between:
    - What insiders DO (insider signal)
    - What media SAYS (news sentiment)
    - What smart money DOES (options signal)
    
    High dissonance = Actions contradict narrative = Market fragility
    
    Returns score 0-100 and detailed breakdown.
    """
     # Get all three signals
     insider_signal, insider_note = calculate_insider_signals(ticker, insider_df)
     media_signal, media_note = calculate_media_signals(ticker, news_df)
     options_signal, options_note = calculate_options_signal(ticker, price_df)
 
    # ============================================
    # COMPONENT 1: Insider vs Media Gap
    # The bigger the gap, the higher the dissonance
    # ============================================
     insider_media_gap = abs(insider_signal - media_signal)# abs means we only care about the size of the gap, not the direction

    #Normalize to 0-1 scale
    # Maximum possible gap is 2 (insider at -1, media at +1)

     insider_media_component = insider_media_gap / 2.0

     # ============================================
    # COMPONENT 2: Options Market Warning
    # If options show fear while media shows optimism = dissonance
    # ============================================

     options_media_gap = abs(options_signal - media_signal)
     options_media_component = options_media_gap / 2.0

      # ============================================
    # COMPONENT 3: Triple Divergence
    # If all three signals point different directions = maximum fragility
    # ============================================

     signals = [insider_signal , media_signal , options_signal]
     signal_std = np.std(signals) # Standard deviation of the three signals

    # High std = signals are spread out = high dissonance
    # Maximum std is ~0.94 when signals are -1, 0, +1
     
     triple_divergence_component = min(signal_std / 0.94, 1.0)

      # ============================================
    # WEIGHTED COMBINATION
    # ============================================
     # Component weights
     W1 = 0.50  # Insider vs media (most important)
     W2 = 0.30  # Options vs media
     W3 = 0.20  # Triple divergence
     
     dissonance =(
        insider_media_component * W1 +
        options_media_component * W2 +
        triple_divergence_component * W3
      )
     
         # Convert to 0-100 scale
     final_score = round(dissonance * 100, 1)
     # ============================================
    # CLASSIFICATION
    # ============================================
     if final_score >= 75:
        risk_level = "CRITICAL"
        interpretation = "Severe contradiction between actions and narrative"
     elif final_score >= 60:
        risk_level = "HIGH"
        interpretation = "Significant dissonance detected"
     elif final_score >= 40:
        risk_level = "MODERATE"
        interpretation = "Some misalignment present"
     elif final_score >= 25:
        risk_level = "LOW"
        interpretation = "Minor inconsistencies"
     else:
        risk_level = "MINIMAL"
        interpretation = "Actions and narrative aligned"
    
     return {
        'ticker': ticker,
        'dissonance_score': final_score,
        'risk_level': risk_level,
        'interpretation': interpretation,
        'insider_signal': round(insider_signal, 2),
        'media_signal': round(media_signal, 2),
        'options_signal': round(options_signal, 2),
        'insider_note': insider_note,
        'media_note': media_note,
        'options_note': options_note,
        'component_1_insider_media': round(insider_media_component * 100, 1),
        'component_2_options_media': round(options_media_component * 100, 1),
        'component_3_triple_divergence': round(triple_divergence_component * 100, 1)
    } 
def calculate_all_dissonance():
     """
    Calculate dissonance scores for all tickers.
    This is MIRROR's main output.
    """
     print("=" * 70)
     print("MIRROR - COGNITIVE DISSONANCE CALCULATOR")
     print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
     print("=" * 70)

     #load all data
     insider_df, news_df , price_df = load_all_data()

     #get unique ticker for news data (most reliable source)
     if not news_df.empty:
         tickers = news_df['ticker'].unique() # .unique is used to get unique tickers from news data, which is our most reliable source for ticker list
     else:
         print("\n⚠ ERROR: No data available. Run data collectors first:")
         print("  1. python SEC_INSIDER.PY")
         print("  2. python NEWS_SENTIMENT.PY")
         print("  3. python price_signal.py")
         return pd.DataFrame()
     results = []
    
     for ticker in tickers:
         print(f"\nCalculating dissonance for {ticker}...")
         result = calculate_dissonance_score(ticker, insider_df, news_df, price_df)
         results.append(result)
         print(f"  Dissonance Score: {result['dissonance_score']}/100 ({result['risk_level']})")

     df = pd.DataFrame(results)

     #sort by dissonance score (highest first)
     df = df.sort_values(by='dissonance_score', ascending=False) # Sort the DataFrame by the 'dissonance_score' column in descending order (highest score first)

     #save results to CSV
     os.makedirs('results', exist_ok=True)
     df.to_csv('results/dissonance_scores.csv', index=False)

     print(f"Calculated dissonance for {len(df)} stocks")
     print(f"Saved to: results/dissonance_scores.csv")
     print("=" * 70)
     print("\n" + "=" * 70)
    
     return df

def display_dissonance_report(df):
     """
    Display MIRROR's main output in human-readable format.
    """
     if df.empty:
         return
     print("\n" + "=" * 70)
     print("MIRROR - COGNITIVE DISSONANCE REPORT")  
     print("=" * 70)  #ther 70 is just a visual separator for better readability

     # Critical alerts
     critical = df[df['risk_level'] == 'CRITICAL']
     if len(critical) > 0:
        print("\n⚠️  CRITICAL ALERTS - MAXIMUM DISSONANCE DETECTED\n")
        for _, row in critical.iterrows():
            print(f"🚨 {row['ticker']:6} | Score: {row['dissonance_score']:5.1f}/100")
            print(f"   {row['interpretation']}")
            print(f"   Insider: {row['insider_signal']:+.2f} ({row['insider_note']})")
            print(f"   Media:   {row['media_signal']:+.2f} ({row['media_note']})")
            print(f"   Options: {row['options_signal']:+.2f} ({row['options_note']})")
            print()

     # High risk
     high_risk = df[df['risk_level'] == 'HIGH']
     if len(high_risk) > 0:
        print("\n⚠️  HIGH RISK - SIGNIFICANT DISSONANCE\n")
        for _, row in high_risk.iterrows():
            print(f"   {row['ticker']:6} | Score: {row['dissonance_score']:5.1f}/100 | {row['interpretation']}")
    
    # Summary
     print("\n" + "─" * 70)
     print("FULL RANKING (Highest Dissonance First)")
     print("─" * 70)
    
    # Print all stocks with their scores and risk levels
     for _, row in df.iterrows():
        risk_emoji = {
            'CRITICAL': '🚨',
            'HIGH': '⚠️ ',
            'MODERATE': '⚡',
            'LOW': '  ',
            'MINIMAL': '✓ '
        }.get(row['risk_level'], '  ')
        
        # Print each stock with its score and risk level in a formatted way
        print(f"{risk_emoji} {row['ticker']:6} | "
              f"Score: {row['dissonance_score']:5.1f}/100 | "
              f"{row['risk_level']:8} | "
              f"Insider: {row['insider_signal']:+.2f} | "
              f"Media: {row['media_signal']:+.2f} | "
              f"Options: {row['options_signal']:+.2f}")
        


# ============================================
# RUN EVERYTHING
# ============================================
if __name__ == "__main__":
    df = calculate_all_dissonance()
    display_dissonance_report(df)
    print("\nMIRROR calculation complete.")

