import yfinance as yf
import pandas as pd

# Test: Download Apple stock data
ticker = yf.Ticker("RELIANCE.NS")

# Get 6 months of daily data
data = ticker.history(period="6mo")

# Print last 5 days
print("Last 5 days of Apple:")
print(data[['Close', 'Volume']].tail())

# Get basic info
info = ticker.info
print(f"\nCompany: {info.get('longName', 'N/A')}")
print(f"Sector: {info.get('sector', 'N/A')}")
print(f"Market Cap: {info.get('marketCap', 'N/A')}")
