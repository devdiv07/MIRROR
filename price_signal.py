import yfinance as yf
import pandas as pd
import numpy as np
from  datetime import datetime, timedelta
import os

#our watchlist
TICKERS = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'JPM', 
           'GS', 'META', 'GOOGL', 'AMZN', 'NFLX']

def get_price_signal(ticker):# here ticker is used for the stock symbol, like 'AAPL' for Apple Inc.
    """
    Extract signals from price and volume that reveal
    what smart money is actually doing.
    
    These are not predictions. These are measurements of
    current hidden behavior in the market.
    """
    try:
        stock = yf.Ticker(ticker)
        # Get historical market data for the past 1 month
        hist = stock.history(period="6mo")
        if hist.empty or len(hist) < 60:
            print(f"Not enough data for {ticker}. Skipping.")
            return None
        
        # ============================================
        # SIGNAL 1: Volume Anomaly
        # When volume spikes without news = hidden activity
        # ============================================

        avg_volume_20d = hist['Volume'].rolling(20).mean()#this line calculates the average trading volume over the past 20 days using a rolling window. The 'Volume' column from the historical data is used, and the rolling function computes the mean for each 20-day period.
        current_volume = hist['Volume'].iloc[-1]
        volume_ratio = current_volume / avg_volume_20d.iloc[-1]#this line calculates the ratio of the current trading volume to the average trading volume over the past 20 days. It takes the current volume (the last value in the 'Volume' column) and divides it by the last value of the average volume calculated in the previous line.
        
        # ============================================
        # SIGNAL 2: Price-Volume Divergence
        # Price up + volume down = weak rally = suspect
        # Price down + volume up = strong selling = real
        # ============================================

        recent_price_change = hist['Close'].pct_change(5).iloc[-1] #iloc means we are looking at the last value of the percentage change over 5 days
        recent_volume_change = hist['Volume'].pct_change(5).iloc[-1] #here pct means percentage change in volume over 5 days and this line means we are looking at the last value of that percentage change
         
        # If price and volume move opposite directions = divergence
        if recent_price_change > 0 and recent_volume_change < -0.2:
            pv_divergence = -1 
            # pv means price volume divergence, here we are checking if the recent price change is positive (price went up) and the recent volume change is negative (volume went down significantly, more than 20%). If this condition is true, it indicates a bearish divergence, suggesting that the rally may be weak and potentially suspect.
        elif recent_price_change < 0 and recent_volume_change > 0.2: 
            pv_divergence = -1 #BearisH(real selling)
        else:
            pv_divergence = 0 #No divergence

        # ============================================
        # SIGNAL 3: Put/Call Ratio
        # More puts than calls = smart money hedging
        # ============================================

        try:
            # Get nearest expiration date for options
            options_dates = stock.options
            if options_dates:
                option = stock.option_chain(options_dates[0]) #this line retrieves the option chain for the nearest expiration date available in the stock's options data. The option chain contains information about both call and put options for that specific expiration date.
                put_volume = option.puts['volume'].sum() #this line calculates the total trading volume of put options by summing the 'volume' column from the puts DataFrame in the option chain.
                call_volume = option.calls['volume'].sum() #this line calculates the total trading volume of call options by summing the 'volume' column from the calls DataFrame in the option chain.
                if call_volume > 0:
                    put_volume = option.puts['volume'].sum() #this line calculates the total trading volume of put options by summing the 'volume' column from the puts DataFrame in the option chain.
                    call_volume = option.calls['volume'].sum() #this line calculates the total trading volume of call options by summing the 'volume' column from the calls DataFrame in the option chain.

                    if call_volume > 0:
                        put_call_ratio = put_volume / call_volume #this line calculates the put/call ratio by dividing the total put volume by the total call volume. The put/call ratio is a commonly used indicator in options trading that helps to gauge market sentiment. A higher put/call ratio may indicate bearish sentiment, while a lower ratio may indicate bullish sentiment.
                    else:
                        put_call_ratio = None # Avoid division by zero
                else:
                    put_call_ratio = None # Avoid division by zero
        
        except:
            put_call_ratio = None # If options data is not available, set ratio to None
        
        # ============================================
        # SIGNAL 4: Recent Price Momentum
        # Not a prediction. A measurement of current state.
        # ============================================

        returns_5d = hist['Close'].pct_change(5).iloc[-1]*100 #this line calculates the percentage change in the closing price over the last 5 days. It uses the pct_change function to compute the percentage change and iloc to access the last value of that change.
        returns_20d = hist['Close'].pct_change(20).iloc[-1]*100 #this line calculates the percentage change in the closing price over the last 20 days. Similar to the previous line, it uses pct_change to compute the percentage change and iloc to access the last value of that change.
        returns_60d = hist['Close'].pct_change(60).iloc[-1]*100 #this line calculates the percentage change in the closing price over the last 60 days. It uses pct_change to compute the percentage change and iloc to access the last value of that change.
       
        # ============================================
        # SIGNAL 5: Volatility State
        # High volatility = unstable = fragile
        # ============================================
        returns = hist['Close'].pct_change()
        volatility_20d = returns.rolling(20).std().iloc[-1] * 100 # THIS LINE CODE CALCULATES THE 20-DAY ROLLING STANDARD DEVIATION OF THE PERCENTAGE CHANGES IN THE CLOSING PRICE, WHICH IS A MEASURE OF VOLATILITY. IT THEN MULTIPLIES THIS VALUE BY 100 TO EXPRESS IT AS A PERCENTAGE.
        return{
            'ticker': ticker,
            'current_price': round(hist['Close'].iloc[-1], 2),# round in simple words is used to limit the number of decimal places for the current price to 2, making it easier to read and interpret.
            'volume_ratio': round(volume_ratio, 2),
            'pv_divergence': pv_divergence,
            'put_call_ratio': round(put_call_ratio, 2) if put_call_ratio else None,
            'return_5d': round(returns_5d, 2),
            'return_20d': round(returns_20d, 2),
            'return_60d': round(returns_60d, 2),
            'volatility_20d': round(volatility_20d, 2),
            'avg_volume_20d': int(avg_volume_20d.iloc[-1])
        }
    except Exception as e:
        print(f"Error {ticker}: {e}")
        return None

def collect_all_price_signals():
    """
    Loop through all tickers and collect price signals.
    """
    print("=" * 50)
    print("MIRROR - Price Signals Collector")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    all_signals = []
    for ticker in TICKERS:
        print(f"\nFetching {ticker}...")
        signals = get_price_signal(ticker)
        if signals:
            all_signals.append(signals)
            print (f"  ✓ Collected price signals")
    df = pd.DataFrame(all_signals)
    #save to CSV
    os.makedirs('data', exist_ok=True)
    df.to_csv('data/price_signals.csv', index=False)#this line saves the DataFrame containing the collected price signals to a CSV file named 'price_signals.csv' in a directory called 'data'. The index=False argument ensures that the row index is not included in the saved CSV file.

    print("\n" + "=" * 50)
    print(f"TOTAL: {len(df)} stocks analyzed")
    print(f"Saved to: data/price_signals.csv")
    print("=" * 50)
    
    return df

def display_price_summary(df):
    """"
    Display the collected price signals in a readable format.
    """
    if df.empty:
        return
    
    print("\n=== PRICE SIGNALS SUMMARY ===\n")
    
    for _, row in df.iterrows():
        ticker = row['ticker']
        
        # Flag unusual volume
        vol_flag = "⚠ UNUSUAL" if row['volume_ratio'] > 1.5 else ""
        
        # Flag put/call ratio
        pc_flag = ""
        if row['put_call_ratio'] and row['put_call_ratio'] > 1.3:
            pc_flag = "⚠ HIGH PUTS"
        
        print(f"{ticker:6} | Price: ${row['current_price']:7.2f} | "
              f"5d: {row['return_5d']:+6.2f}% | "
              f"Vol Ratio: {row['volume_ratio']:.2f}x {vol_flag} | "
              f"P/C: {row['put_call_ratio'] if row['put_call_ratio'] else 'N/A':>5} {pc_flag}")


# ============================================
# RUN EVERYTHING
# ============================================
df = collect_all_price_signals()
display_price_summary(df)
print("\n✓ Done. Ready for dissonance calculation.")
