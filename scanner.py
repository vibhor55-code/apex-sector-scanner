import os
import io
import re
import html
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

BOT_TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()

CAPITAL = float(os.environ.get("TRADING_CAPITAL", 1000000))      # Rs. 10,00,000
MAX_ALLOC_PCT = float(os.environ.get("MAX_ALLOC_PCT", 0.20))     # Max 20% in 1 stock

NSE_500_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"

def send_telegram_message(text):
    if not BOT_TOKEN:
        print("❌ ERROR: TELEGRAM_BOT_TOKEN missing!")
        return

    target_chat_id = CHAT_ID
    if not target_chat_id:
        try:
            u = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates", timeout=10).json()
            results = u.get("result", [])
            if results:
                target_chat_id = str(results[-1]["message"]["chat"]["id"])
        except Exception as e:
            print(f"Auto-discovery error: {e}")

    if not target_chat_id:
        print("❌ ERROR: TELEGRAM_CHAT_ID missing!")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": target_chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    resp = requests.post(url, json=payload, timeout=20)
    print(f"Telegram API Status ({resp.status_code}): {resp.text}")

    # Bulletproof Fallback: Strip HTML tags and send plain text if HTML ever fails
    if resp.status_code != 200:
        print("⚠️ HTML parse issue detected. Sending clean plain-text fallback...")
        clean_text = re.sub(r'<[^>]+>', '', text)
        clean_text = html.unescape(clean_text)
        payload2 = {
            "chat_id": target_chat_id,
            "text": clean_text[:4000],
            "disable_web_page_preview": True
        }
        resp2 = requests.post(url, json=payload2, timeout=20)
        print(f"Fallback Status ({resp2.status_code}): {resp2.text}")

def get_nse_universe():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "
