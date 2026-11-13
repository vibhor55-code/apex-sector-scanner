import os
import io
import html
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

BOT_TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()

CAPITAL = float(os.environ.get("TRADING_CAPITAL", 1000000))
MAX_ALLOC_PCT = float(os.environ.get("MAX_ALLOC_PCT", 0.20))

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
    if resp.status_code != 200:
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
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def evaluate_market_regime(nifty_df, pct_above_200):
    try:
        close = nifty_df['Close'].squeeze()
        ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
        sma200 = float(close.rolling(200).mean().iloc[-1])
        curr = float(close.iloc[-1])
    except Exception:
        curr, ema50, sma200 = 0, 0, 0

    if curr > ema50 and pct_above_200 >= 50.0:
        return "🟢 BULL EXPANSION (Full 1.0% Risk)", 0.01
    elif curr > sma200 or pct_above_200 >= 38.0:
        return "🟡 SELECTIVE / ROTATION (0.5% Risk)", 0.005
    else:
        return "🔴 DEFENSIVE / CAUTION (0.25% Pilot Risk)", 0.0025

def check_fundamentals(yahoo_ticker, industry):
    try:
        info = yf.Ticker(yahoo_ticker).info
        rev_g = info.get('revenueGrowth')
        earn_g = info.get('earningsGrowth')
        roe = info.get('returnOnEquity')
        dte = info.get('debtToEquity')
        pe = info.get('trailingPE')

        rev_pct = round(rev_g * 100, 0) if rev_g is not None else None
        earn_pct = round(earn_g * 100, 0) if earn_g is not None else None
        roe_pct = round(roe * 100, 0) if roe is not None else None
        dte_ratio = round(dte / 100.0, 2) if dte is not None else None
        pe_val = round(pe, 1) if pe is not None else "N/A"

        is_financial = "Financial" in str(industry) or "Bank" in str(industry)
        high_debt = (not is_financial) and (dte_ratio is not None and dte_ratio > 1.5)

        if (earn_pct is not None and earn_pct < -5) or (rev_pct is not None and rev_pct < 0) or high_debt:
            grade, score = "🟡 TECH-ONLY", 0
        elif (earn_pct is not None and earn_pct >= 15) and (rev_pct is not None and rev_pct >= 12):
            grade, score = "🟢 A+ LEADER", 3
        elif (earn_pct is not None and earn_pct >= 10) or (rev_pct is not None and rev_pct >= 10):
            grade, score = "🟢 SOLID FUNDA", 2
        else:
            grade, score = "⚪ MODERATE", 1

        r_str = f"{rev_pct:+.0f}%" if rev_pct is not None else "NA"
        e_str = f"{earn_pct:+.0f}%" if earn_pct is not None else "NA"
        roe_str = f"{roe_pct:.0f}%" if roe_pct is not None else "NA"
        return score, f"{grade} | Sales:{r_str} PAT:{e_str} ROE:{roe_str} PE:{pe_val}"
    except Exception:
        return 1, "⚪ FUNDA N/A"

def generate_html_dashboard(today_str, regime_str, pct_above_200, sec_df, stocks_df):
    """Generates a self-contained dark-mode interactive index.html dashboard."""
    sec_rows = ""
    for idx, r in sec_df.iterrows():
        pct = r['Participation_%']
        sec_rows += f"""
        <div class="mb-3">
          <div class="flex justify-between text-sm mb-1">
            <span class="font-semibold text-slate-200">{html.escape(str(idx))}</span>
            <span class="text-emerald-400 font-mono">{int(r['Breakouts'])}/{int(r['Total'])} stocks ({pct}%)</span>
          </div>
          <div class="w-full bg-slate-800 rounded-full h-2.5">
            <div class="bg-emerald-500 h-2.5 rounded-full" style="width: {min(pct*2.5, 100)}%"></div>
          </div>
        </div>"""

    stock_rows = ""
    for _, s in stocks_df.iterrows():
        sym = html.escape(str(s['Symbol']))
        ind = html.escape(str(s['Industry']))
        fline = html.escape(str(s['Funda_Line']))
        tv_url = f"https://in.tradingview.com/chart/?symbol=NSE:{sym}"
        sc_url = f"https://www.screener.in/company/{sym}/consolidated/"
        stock_rows += f"""
        <tr class="border-b border-slate-800 hover:bg-slate-800/60">
          <td class="p-3 font-bold text-white">{sym} <span class="text-xs px-2 py-0.5 rounded bg-slate-700 text-amber-300">{s['VCP_Tag']}</span></td>
          <td class="p-3 text-slate-300 text-sm">{ind}</td>
          <td class="p-3 font-mono text-emerald-400 font-bold">{s['RS_Rating']}</td>
          <td class="p-3 font-mono">₹{s['Close']}</td>
          <td class="p-3 font-mono text-rose-400">₹{s['Stop_Loss']} ({s['SL_Width_%']}%)</td>
          <td class="p-3 font-mono font-bold text-amber-300">{s['Qty']}</td>
          <td class="p-3 font-mono">{s['Vol_Mult']}x</td>
          <td class="p-3 text-xs text-slate-300">{fline}</td>
          <td class="p-3 text-sm">
            <a href="{tv_url}" target="_blank" class="text-sky-400 hover:underline mr-2">Chart</a>
            <a href="{sc_url}" target="_blank" class="text-indigo-400 hover:underline">Screener</a>
          </td>
        </tr>"""

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Apex Master Techno-Funda Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen p-4 md:p-8">
  <div class="max-w-7xl mx-auto">
    <div class="flex flex-col md:flex-row justify-between items-start md:items-center mb-6 border-b border-slate-800 pb-4">
      <div>
        <h1 class="text-2xl md:text-3xl font-bold text-white">🏛️ Apex Master Techno-Funda Dashboard</h1>
        <p class="text-slate-400 text-sm mt-1">Full-Market NSE 500 Stage-2 Consolidation Breakouts • Updated: {today_str}</p>
      </div>
      <div class="mt-3 md:mt-0 bg-slate-900 border border-slate-800 rounded-lg px-4 py-2 text-sm">
        <div><b>Regime:</b> {regime_str}</div>
        <div class="text-slate-400"><b>NSE 500 Breadth (>40W EMA):</b> {pct_above_200}%</div>
      </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 lg:col-span-1">
        <h2 class="text-lg font-bold mb-4 text-emerald-400">🔥 Top Sector Clusters Waking Up</h2>
        {sec_rows if sec_rows else "<p class='text-slate-400'>No clusters triggered today.</p>"}
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 lg:col-span-2">
        <h2 class="text-lg font-bold mb-4 text-amber-400">🧮 Quick 1% Risk Position Sizer</h2>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label class="text-xs text-slate-400">Trading Capital (₹)</label>
            <input id="cap" type="number" value="1000000" oninput="calc()" class="w-full mt-1 bg-slate-800 border border-slate-700 rounded p-2 text-white">
          </div>
          <div>
            <label class="text-xs text-slate-400">Entry Price (₹)</label>
            <input id="entry" type="number" value="1447" oninput="calc()" class="w-full mt-1 bg-slate-800 border border-slate-700 rounded p-2 text-white">
          </div>
          <div>
            <label class="text-xs text-slate-400">Stop-Loss Price (₹)</label>
            <input id="sl" type="number" value="1314" oninput="calc()" class="w-full mt-1 bg-slate-800 border border-slate-700 rounded p-2 text-white">
          </div>
        </div>
        <div id="res" class="mt-4 p-3 bg-slate-950 rounded border border-slate-800 text-sm font-mono text-emerald-400"></div>
      </div>
    </div>

    <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 overflow-x-auto">
      <h2 class="text-lg font-bold mb-4 text-sky-400">📈 Actionable Stage-2 Breakouts (Ranked by Funda + RS)</h2>
      <table class="w-full text-left border-collapse">
        <thead>
          <tr class="border-b border-slate-700 text-xs uppercase text-slate-400">
            <th class="p-3">Symbol</th>
            <th class="p-3">Sector</th>
            <th class="p-3">RS</th>
            <th class="p-3">CMP</th>
            <th class="p-3">Stop-Loss</th>
            <th class="p-3">Qty (1% Risk)</th>
            <th class="p-3">Vol</th>
            <th class="p-3">Fundamentals</th>
            <th class="p-3">Links</th>
          </tr>
        </thead>
        <tbody>
          {stock_rows if stock_rows else "<tr><td colspan='9' class='p-4 text-slate-400'>No breakouts today.</td></tr>"}
        </tbody>
      </table>
    </div>
  </div>
  <script>
    function calc() {{
      const cap = parseFloat(document.getElementById('cap').value) || 0;
      const entry = parseFloat(document.getElementById('entry').value) || 0;
      const sl = parseFloat(document.getElementById('sl').value) || 0;
      const risk = cap * 0.01;
      const diff = entry - sl;
      if (diff <= 0 || entry <= 0) {{
        document.getElementById('res').innerText = "Stop-Loss must be below Entry Price.";
        return;
      }}
      const qty = Math.min(Math.floor(risk / diff), Math.floor((cap * 0.20) / entry));
      document.getElementById('res').innerText = `Buy Qty: ${{qty}} shares | Total Allocation: ₹${{(qty * entry).toLocaleString('en-IN')}} | Max Loss (1%): ₹${{risk.toLocaleString('en-IN')}}`;
    }}
    calc();
  </script>
</body>
</html>"""
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print("✅ Live index.html dashboard generated!")

def main():
    universe = get_nse_universe()
    stock_tickers = universe['Yahoo_Ticker'].tolist()
    data = yf.download(stock_tickers + ["^NSEI"], period="1y", group_by='ticker', threads=True, progress=False)
    nifty_df = data["^NSEI"].dropna() if "^NSEI" in data.columns.get_level_values(0) else pd.DataFrame()

    stock_metrics = []
    above_200_count, valid_stocks = 0, 0

    for _, row in universe.iterrows():
        t = row['Yahoo_Ticker']
        try:
            if t not in data.columns.get_level_values(0):
                continue
            df_s = data[t].dropna()
            if len(df_s) < 200:
                continue
            close = df_s['Close'].squeeze()
            curr_c = float(close.iloc[-1])
            ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
            ema200_series = close.ewm(span=200, adjust=False).mean()
            ema200_curr = float(ema200_series.iloc[-1])
            ema200_prev20 = float(ema200_series.iloc[-21])

            valid_stocks += 1
            if curr_c > ema200_curr:
                above_200_count += 1

            ret_1m = ((curr_c / float(close.iloc[-21])) - 1) * 100
            ret_3m = ((curr_c / float(close.iloc[-63])) - 1) * 100
            ret_6m = ((curr_c / float(close.iloc[-126])) - 1) * 100
            rs_raw = (0.4 * ret_3m) + (0.3 * ret_6m) + (0.3 * ret_1m)

            stock_metrics.append({
                'Symbol': row['Symbol'], 'Industry': row['Industry'], 'Yahoo_Ticker': t,
                'df': df_s, 'curr_c': curr_c, 'ema50': ema50, 'ema200_curr': ema200_curr,
                'ema200_rising': ema200_curr >= (ema200_prev20 * 0.998),
                'ret_1m': ret_1m, 'rs_raw': rs_raw
            })
        except Exception:
            continue

    df_m = pd.DataFrame(stock_metrics)
    pct_above_200 = round((above_200_count / max(valid_stocks, 1)) * 100, 1)
    regime_str, risk_pct = evaluate_market_regime(nifty_df, pct_above_200)
    df_m['RS_Rating'] = (df_m['rs_raw'].rank(pct=True) * 99).astype(int)

    breakouts = []
    for _, item in df_m.iterrows():
        if not (item['curr_c'] > item['ema50'] and item['curr_c'] > item['ema200_curr']):
            continue
        if not item['ema200_rising'] or item['RS_Rating'] < 72:
            continue

        df_s = item['df']
        close, high, low, vol = df_s['Close'].squeeze(), df_s['High'].squeeze(), df_s['Low'].squeeze(), df_s['Volume'].squeeze()
        curr_c = item['curr_c']

        if curr_c < (float(high.iloc[-250:].max()) * 0.84):
            continue

        base_high, base_low = float(high.iloc[-120:-10].max()), float(low.iloc[-120:-10].min())
        if base_low <= 0 or (((base_high - base_low) / base_low) * 100) > 42.0:
            continue

        recent_tight_range = ((float(high.iloc[-20:-5].max()) - float(low.iloc[-20:-5].min())) / float(low.iloc[-20:-5].min())) * 100
        vcp_tag = "⚡VCP" if recent_tight_range <= 12.5 else "📦Base"

        vol_mult = float((vol.iloc[-5:] / vol.rolling(20).mean().iloc[-5:]).max())
        if curr_c >= (base_high * 0.97) and vol_mult >= 1.4 and item['ret_1m'] > 3.5:
            atr14 = float(calculate_atr(high, low, close, 14).iloc[-1])
            stop_loss = min(max(item['ema50'], float(low.iloc[-10:].min()), curr_c - (2.5 * atr14)), curr_c * 0.975)
            risk_per_share = curr_c - stop_loss
            final_qty = min(int((CAPITAL * risk_pct) / risk_per_share), int((CAPITAL * MAX_ALLOC_PCT) / curr_c))

            breakouts.append({
                'Symbol': item['Symbol'], 'Industry': item['Industry'], 'Yahoo_Ticker': item['Yahoo_Ticker'],
                'Close': round(curr_c, 1), 'Stop_Loss': round(stop_loss, 1),
                'SL_Width_%': round((risk_per_share / curr_c) * 100, 1),
                'Qty': final_qty, 'Vol_Mult': round(vol_mult, 1),
                'RS_Rating': item['RS_Rating'], 'VCP_Tag': vcp_tag, '1M_Ret_%': round(item['ret_1m'], 1)
            })

    df_out = pd.DataFrame(breakouts)
    today_str = datetime.now().strftime("%d %b %Y")

    if df_out.empty:
        generate_html_dashboard(today_str, regime_str, pct_above_200, pd.DataFrame(), pd.DataFrame())
        send_telegram_message(f"📊 <b>APEX MASTER SCAN ({today_str})</b>\nRegime: {regime_str}\nNo breakouts today.")
        return

    total_sector = universe.groupby('Industry')['Symbol'].count()
    brk_sector = df_out.groupby('Industry')['Symbol'].count()
    sec_df = pd.DataFrame({'Breakouts': brk_sector, 'Total': total_sector}).dropna()
    sec_df['Participation_%'] = round((sec_df['Breakouts'] / sec_df['Total']) * 100, 1)
    sec_df = sec_df.sort_values(by=['Breakouts', 'Participation_%'], ascending=False).head(8)

    top_candidates = df_out.sort_values(by=['RS_Rating', 'Vol_Mult'], ascending=False).head(15).copy()
    scores, flines = [], []
    for _, r in top_candidates.iterrows():
        sc, fl = check_fundamentals(r['Yahoo_Ticker'], r['Industry'])
        scores.append(sc)
        flines.append(fl)

    top_candidates['Funda_Score'] = scores
    top_candidates['Funda_Line'] = flines
    top_candidates = top_candidates.sort_values(by=['Funda_Score', 'RS_Rating', 'Vol_Mult'], ascending=False).head(12)

    # 1. Generate Live Web Dashboard (index.html)
    generate_html_dashboard(today_str, regime_str, pct_above_200, sec_df, top_candidates)

    # 2. Send Telegram Summary with Direct Dashboard URL
    dash_url = "https://vibhor55-code.github.io/apex-sector-scanner/"
    msg = f"🏛️ <b>APEX MASTER TECHNO-FUNDA ({today_str})</b>\n"
    msg += f"<b>Regime:</b> {regime_str}\n"
    msg += f"<b>Breadth (>40W EMA):</b> {pct_above_200}%\n"
    msg += f"🌐 <a href='{dash_url}'><b>OPEN LIVE WEB DASHBOARD</b></a>\n\n"

    msg += "🔥 <b>DOMINANT SECTOR CLUSTERS:</b>\n"
    for idx, r in sec_df.head(6).iterrows():
        msg += f"• <b>{html.escape(str(idx))}</b>: {int(r['Breakouts'])}/{int(r['Total'])} ({r['Participation_%']}%)\n"

    msg += f"\n📈 <b>TOP STAGE-2 LEADERS:</b>\n"
    for _, s in top_candidates.head(8).iterrows():
        sym = html.escape(str(s['Symbol']))
        ind = html.escape(str(s['Industry']))
        fline = html.escape(str(s['Funda_Line']))
        tv_url = f"https://in.tradingview.com/chart/?symbol=NSE:{sym}"
        sc_url = f"https://www.screener.in/company/{sym}/consolidated/"
        msg += (
            f"• <b>{sym}</b> [{s['VCP_Tag']} | <b>RS:{s['RS_Rating']}</b>] ({ind})\n"
            f"  CMP: ₹{s['Close']} | SL: ₹{s['Stop_Loss']} ({s['SL_Width_%']}%) | <b>Qty: {s['Qty']}</b> | Vol: {s['Vol_Mult']}x\n"
            f"  {fline}\n"
            f"  🔗 <a href='{tv_url}'>Chart</a> | <a href='{sc_url}'>Screener</a>\n"
        )

    send_telegram_message(msg)

if __name__ == "__main__":
    main()
