import os
import io
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

# Read credentials securely from GitHub Secrets
BOT_TOKEN = os.environ.get("9206595079:AAHqcmM2rQbpRE-b-D6FZSHOhBmV_iQc0rU")
CHAT_ID = os.environ.get("1109049909")
CAPITAL = 1000000  # Rs. 10 Lakhs Default Capital
RISK_PCT = 0.01    # 1% Risk per trade (Rs. 10,000)

NSE_500_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"

def get_nse_universe():
    """Fetches Nifty 500 CSV using browser headers so NSE doesn't block cloud servers."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    response = requests.get(NSE_500_URL, headers=headers, timeout=15)
    response.raise_for_status()
    df = pd.read_csv(io.StringIO(response.text))
    df['Yahoo_Ticker'] = df['Symbol'] + ".NS"
    return df[['Symbol', 'Company Name', 'Industry', 'Yahoo_Ticker']]

def evaluate_stock(df_price):
    """Checks for multi-month base tightness + Stage 2 breakout + volume spike."""
    if len(df_price) < 200:
        return None

    close = df_price['Close'].squeeze()
    high = df_price['High'].squeeze()
    low = df_price['Low'].squeeze()
    volume = df_price['Volume'].squeeze()

    ema_50 = close.ewm(span=50, adjust=False).mean()
    sma_200 = close.rolling(200).mean()
    vol_sma_20 = volume.rolling(20).mean()

    curr_close = float(close.iloc[-1])
    curr_ema50 = float(ema_50.iloc[-1])
    curr_sma200 = float(sma_200.iloc[-1])

    # 1. Stage 2 Trend Alignment
    if not (curr_close > curr_ema50 and curr_close > curr_sma200):
        return None

    # 2. Multi-Month Consolidation Base (Day -120 to Day -10)
    base_high = float(high.iloc[-120:-10].max())
    base_low = float(low.iloc[-120:-10].min())
    if base_low <= 0:
        return None
    base_depth_pct = ((base_high - base_low) / base_low) * 100

    # Must be a controlled consolidation base (< 42% depth over 5 months)
    if base_depth_pct > 42.0:
        return None

    # 3. Positive Price Action near/above Base High + 1M Momentum
    is_breaking_out = curr_close >= (base_high * 0.97)
    ret_1m = ((curr_close / float(close.iloc[-21])) - 1) * 100

    # 4. Pocket Pivot Volume Spike in last 5 sessions (>= 1.4x 20-day avg)
    recent_vol_mult = float((volume.iloc[-5:] / vol_sma_20.iloc[-5:]).max())

    if is_breaking_out and recent_vol_mult >= 1.4 and ret_1m > 4.0:
        darvas_low = float(low.iloc[-10:].min())
        stop_loss = max(curr_ema50, darvas_low)
        risk_per_share = max(curr_close - stop_loss, curr_close * 0.02)
        qty_1pct = int((CAPITAL * RISK_PCT) / risk_per_share)

        return {
            'Close': round(curr_close, 1),
            'Base_Depth_%': round(base_depth_pct, 1),
            '1M_Ret_%': round(ret_1m, 1),
            'Vol_Mult': round(recent_vol_mult, 1),
            'Stop_Loss': round(stop_loss, 1),
            'Qty_1Pct': qty_1pct
        }
    return None

def send_telegram_message(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram credentials not set. Printing message locally:\n", text)
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    requests.post(url, json=payload, timeout=15)

def main():
    universe = get_nse_universe()
    tickers = universe['Yahoo_Ticker'].tolist()
    print(f"Downloading data for {len(tickers)} NSE stocks...")
    data = yf.download(tickers, period="1y", group_by='ticker', threads=True, progress=False)

    breakouts = []
    for _, row in universe.iterrows():
        t = row['Yahoo_Ticker']
        try:
            if t not in data.columns.get_level_values(0):
                continue
            df_stock = data[t].dropna()
            res = evaluate_stock(df_stock)
            if res:
                res['Symbol'] = row['Symbol']
                res['Industry'] = row['Industry']
                breakouts.append(res)
        except Exception:
            continue

    df_out = pd.DataFrame(breakouts)
    today_str = datetime.now().strftime("%d %b %Y")

    if df_out.empty:
        send_telegram_message(f"📊 <b>Apex Full-Market Scan ({today_str})</b>\nNo tight-base Stage 2 breakouts triggered today.")
        return

    # Group by Sector to find Theme Clusters
    total_sector = universe.groupby('Industry')['Symbol'].count()
    brk_sector = df_out.groupby('Industry')['Symbol'].count()
    sec_df = pd.DataFrame({'Breakouts': brk_sector, 'Total': total_sector}).dropna()
    sec_df['Participation_%'] = round((sec_df['Breakouts'] / sec_df['Total']) * 100, 1)
    sec_df = sec_df.sort_values(by=['Breakouts', 'Participation_%'], ascending=False).head(6)

    # Sort stocks by 1M Momentum & Volume
    df_out = df_out.sort_values(by=['Vol_Mult', '1M_Ret_%'], ascending=False).head(10)

    # Build Formatted Telegram Report
    msg = f"🚀 <b>APEX TECHNO-FUNDA SCAN ({today_str})</b>\n"
    msg += "<i>Whole-Market Consolidation Breakouts</i>\n\n"
    msg += "🔥 <b>TOP SECTOR CLUSTERS WAKING UP:</b>\n"
    for idx, r in sec_df.iterrows():
        msg += f"• <b>{idx}</b>: {int(r['Breakouts'])}/{int(r['Total'])} stocks ({r['Participation_%']}%)\n"

    msg += "\n📈 <b>TOP ACTIONABLE BREAKOUTS (1% Risk Sizing):</b>\n"
    for _, s in df_out.iterrows():
        msg += (
            f"• <b>{s['Symbol']}</b> ({s['Industry']})\n"
            f"  CMP: ₹{s['Close']} | SL: ₹{s['Stop_Loss']} | <b>Qty: {s['Qty_1Pct']}</b> | Vol: {s['Vol_Mult']}x\n"
        )

    send_telegram_message(msg)
    print("Scan complete and sent to Telegram!")

if __name__ == "__main__":
    main()
