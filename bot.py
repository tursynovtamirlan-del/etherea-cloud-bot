# bot.py
# Совет директоров: Технический аналитик + Риск-менеджер + Консенсус
# Добавлен минимальный веб-сервер для совместимости с бесплатным тарифом Render

import os
import time
import datetime
import requests
import pandas as pd
import pandas_ta as ta
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# ============================================
# 1. ВЕБ-СЕРВЕР ДЛЯ RENDER (чтобы порт был открыт)
# ============================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Etherea Bot is running")
    def log_message(self, format, *args):
        # Отключаем шумные логи веб-сервера
        pass

def run_webserver():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    server.serve_forever()

# Запускаем веб-сервер в фоновом потоке
webserver_thread = threading.Thread(target=run_webserver, daemon=True)
webserver_thread.start()
print(f"Веб-сервер запущен на порту {os.environ.get('PORT', 10000)}")

# ============================================
# 2. ОСТАЛЬНОЙ КОД БОТА (без изменений)
# ============================================
MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    raise Exception("MONGO_URI не задана")

client = MongoClient(MONGO_URI)
db = client["etherea"]
collection_decisions = db["council_decisions"]
collection_prices = db["prices"]

print("Совет директоров запущен. Подключение к MongoDB OK.")

def get_btc_price():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
        r = requests.get(url)
        return r.json()["bitcoin"]["usd"]
    except Exception as e:
        print(f"Ошибка получения цены: {e}")
        return None

def fetch_historical_klines(symbol="BTC/USDT", timeframe="1h", limit=100):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol.replace('/', '')}&interval={timeframe}&limit={limit}"
    try:
        r = requests.get(url)
        data = r.json()
        df = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        df['close'] = df['close'].astype(float)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df
    except Exception as e:
        print(f"Ошибка загрузки истории: {e}")
        return None

def calculate_indicators(df):
    df['rsi'] = ta.rsi(df['close'], length=14)
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    df['macd'] = macd['MACD_12_26_9']
    df['sma10'] = ta.sma(df['close'], length=10)
    df['sma30'] = ta.sma(df['close'], length=30)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    return df

def technical_analyst(row):
    if row['rsi'] < 30 and row['macd'] > 0:
        return 'BUY'
    elif row['rsi'] > 70 and row['macd'] < 0:
        return 'SELL'
    else:
        return 'HOLD'

def risk_manager(row, current_drawdown_pct=0.0):
    atr_ratio = row['atr'] / row['close']
    if atr_ratio > 0.05 or current_drawdown_pct > 10.0:
        return 'REJECT'
    return 'APPROVE'

def consensus_engine(tech_vote, risk_vote):
    if risk_vote == 'REJECT':
        return 'HOLD'
    return tech_vote

# Загружаем историю
history_df = fetch_historical_klines(limit=100)
if history_df is None or len(history_df) < 50:
    print("Не удалось загрузить историю. Завершение.")
    exit(1)

balance = 10000.0
position = 0.0
peak_balance = balance

while True:
    now = datetime.datetime.now()
    current_price = get_btc_price()
    if current_price is None:
        time.sleep(60)
        continue

    new_row = pd.DataFrame([{
        'open': current_price,
        'high': current_price,
        'low': current_price,
        'close': current_price,
        'volume': 0
    }], index=[now])
    history_df = pd.concat([history_df, new_row])
    if len(history_df) > 100:
        history_df = history_df.iloc[-100:]

    history_df = calculate_indicators(history_df)
    last = history_df.iloc[-1]

    current_value = balance + position * current_price
    if current_value > peak_balance:
        peak_balance = current_value
    drawdown = (peak_balance - current_value) / peak_balance * 100.0 if peak_balance > 0 else 0.0

    tech_vote = technical_analyst(last)
    risk_vote = risk_manager(last, drawdown)
    final_decision = consensus_engine(tech_vote, risk_vote)

    if final_decision == 'BUY' and position == 0:
        position = balance / current_price
        balance = 0
        print(f"!!! СОВЕТ РЕШИЛ КУПИТЬ по {current_price}")
    elif final_decision == 'SELL' and position > 0:
        balance = position * current_price
        position = 0
        print(f"!!! СОВЕТ РЕШИЛ ПРОДАТЬ по {current_price}")

    doc_price = {
        "timestamp": now,
        "btc_usd": current_price,
        "source": "coingecko"
    }
    collection_prices.insert_one(doc_price)

    doc_decision = {
        "timestamp": now,
        "price": current_price,
        "technical_vote": tech_vote,
        "risk_vote": risk_vote,
        "final_decision": final_decision,
        "rsi": float(last['rsi']) if pd.notna(last['rsi']) else None,
        "macd": float(last['macd']) if pd.notna(last['macd']) else None,
        "atr_ratio": float(last['atr'] / last['close']) if pd.notna(last['atr']) else None,
        "drawdown_pct": round(drawdown, 2)
    }
    collection_decisions.insert_one(doc_decision)

    print(f"[{now}] Цена: {current_price} | Tech: {tech_vote} | Risk: {risk_vote} | FINAL: {final_decision} | Просадка: {drawdown:.1f}%")

    time.sleep(60)
