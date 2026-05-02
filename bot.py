# bot.py
# Технический аналитик: рассчитывает RSI, MACD, SMA и выдаёт сигналы
# Данные и сигналы сохраняются в MongoDB

import os
import time
import datetime
import requests
import pandas as pd
import pandas_ta as ta
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# ----- 1. ПОДКЛЮЧЕНИЕ К MONGODB -----
MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    raise Exception("MONGO_URI не задана в переменных окружения")

client = MongoClient(MONGO_URI)
db = client["etherea"]
collection_signals = db["signals"]
collection_prices = db["prices"]

print("Бот-аналитик запущен. Подключение к MongoDB OK.")

# ----- 2. ПОЛУЧЕНИЕ ЦЕНЫ BTC -----
def get_btc_price():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
        r = requests.get(url)
        return r.json()["bitcoin"]["usd"]
    except Exception as e:
        print(f"Ошибка получения цены: {e}")
        return None

# ----- 3. ЗАГРУЗКА ИСТОРИИ (для расчёта индикаторов) -----
def fetch_historical_klines(symbol="BTC/USDT", timeframe="1h", limit=100):
    # Используем бесплатный API Binance через публичный эндпоинт
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

# ----- 4. ТЕХНИЧЕСКИЙ АНАЛИЗ (RSI, MACD, SMA) -----
def calculate_indicators(df):
    # RSI (период 14)
    df['rsi'] = ta.rsi(df['close'], length=14)
    # MACD (12,26,9)
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    df['macd'] = macd['MACD_12_26_9']
    df['macd_signal'] = macd['MACDs_12_26_9']
    # SMA 10 и 30
    df['sma10'] = ta.sma(df['close'], length=10)
    df['sma30'] = ta.sma(df['close'], length=30)
    return df

def generate_signal(row):
    """На основе последних значений индикаторов возвращает 'BUY', 'SELL' или 'HOLD'"""
    # Условия для BUY: RSI < 30 и MACD > 0
    if row['rsi'] < 30 and row['macd'] > 0:
        return 'BUY'
    # Условия для SELL: RSI > 70 и MACD < 0
    elif row['rsi'] > 70 and row['macd'] < 0:
        return 'SELL'
    else:
        return 'HOLD'

# ----- 5. ОСНОВНОЙ ЦИКЛ (запускается раз в минуту) -----
# Сначала загружаем историю для индикаторов
history_df = fetch_historical_klines(limit=100)
if history_df is None or len(history_df) < 50:
    print("Не удалось загрузить историю. Завершение.")
    exit(1)

while True:
    now = datetime.datetime.now()
    # 1. Получаем текущую цену
    current_price = get_btc_price()
    if current_price is None:
        time.sleep(60)
        continue
    
    # 2. Добавляем новую "свечу" в историю (имитируем текущую цену как close)
    new_row = pd.DataFrame([{
        'open': current_price,
        'high': current_price,
        'low': current_price,
        'close': current_price,
        'volume': 0
    }], index=[now])
    history_df = pd.concat([history_df, new_row])
    # Оставляем последние 100 записей, чтобы не раздувать
    if len(history_df) > 100:
        history_df = history_df.iloc[-100:]
    
    # 3. Пересчитываем индикаторы
    history_df = calculate_indicators(history_df)
    last = history_df.iloc[-1]
    
    # 4. Генерируем сигнал
    signal = generate_signal(last)
    
    # 5. Сохраняем цену и сигнал в MongoDB
    doc_price = {
        "timestamp": now,
        "btc_usd": current_price,
        "source": "coingecko"
    }
    collection_prices.insert_one(doc_price)
    
    doc_signal = {
        "timestamp": now,
        "signal": signal,
        "rsi": float(last['rsi']) if pd.notna(last['rsi']) else None,
        "macd": float(last['macd']) if pd.notna(last['macd']) else None,
        "sma10": float(last['sma10']) if pd.notna(last['sma10']) else None,
        "sma30": float(last['sma30']) if pd.notna(last['sma30']) else None,
        "price": current_price
    }
    collection_signals.insert_one(doc_signal)
    
    print(f"[{now}] Цена: {current_price} | Сигнал: {signal} | RSI: {last['rsi']:.2f}")
    
    # 6. Ждём 60 секунд до следующей итерации
    time.sleep(60)
