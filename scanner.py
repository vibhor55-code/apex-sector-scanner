import os
import io
import html
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

# ==============================================================================
# MASTER CONFIGURATION (Reads from GitHub Secrets or Environment Variables)
# ==============================================================================
BOT_TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()

CAPITAL = float(os.environ.get("TRADING_CAPITAL", 1000000))      # Default: Rs. 10,00,000
MAX_ALLOC_PCT = float(os.environ.get("MAX_ALLOC_PCT", 0.20))     # Max 20% capital in any 1 stock (Rs. 2L)

NSE_500_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"

def send_telegram_message(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing!")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    resp = requests.post(url, json=payload, timeout=20)
    print(f"Telegram API Status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"Fallback plain text due to: {resp.text}")
        payload.pop("parse_mode", None)
        requests.post(url, json=payload, timeout=20)

def get_nse_universe():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    response = requests.get(NSE_500_URL, headers=headers, timeout=20)
    response.raise_for_status()
    df = pd.read_csv(io.StringIO(response.text))
    df['Yahoo_Ticker'] = df['Symbol'] + ".NS"
    return df[['Symbol', 'Company Name', 'Industry', 'Yahoo_Ticker']]

def calculate_atr(high, low, close, period=14):
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def evaluate_market_regime(nifty_df, pct_above_200):
    """Determines Market Regime and automatically scales Risk-per-Trade %."""
    try:
        close = nifty_df['Close'].squeeze()
        ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
        sma200 = float(close.rolling(200).mean().iloc[-1])
        curr = float(close.iloc[-1])
        ret_3m = ((curr / float(close.iloc[-63])) - 1) * 100
        ret_6m = ((curr / float(close.iloc[-126])) - 1) * 100
    except Exception:
        curr, ema50, sma200, ret_3m, ret_6m = 0, 0, 0, 0, 0

    if curr > ema50 and pct_above_200 >= 50.0:
        regime = "🟢 BULL EXPANSION (Full 1.0% Risk)"
