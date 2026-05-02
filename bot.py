# bot.py
# Простой бот-заглушка для облачного тестирования

import os
import time
import datetime
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()  # загружаем переменные из .env

# 1. Подключение к MongoDB
MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    raise Exception("Переменная MONGO_URI не задана")

client = MongoClient(MONGO_URI)
db = client["etherea"]          # название базы данных
collection = db["heartbeats"]   # коллекция для хранения "пульса"

print("Бот запущен. Подключение к MongoDB успешно.")

# 2. Функция для получения цены BTC (для имитации)
def get_btc_price():
    try:
        response = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd")
        data = response.json()
        return data["bitcoin"]["usd"]
    except Exception as e:
        print(f"Ошибка получения цены: {e}")
        return None

# 3. Основной цикл (будет работать вечно)
while True:
    timestamp = datetime.datetime.now()
    price = get_btc_price()
    
    # Записываем в MongoDB
    doc = {
        "timestamp": timestamp,
        "btc_usd": price,
        "status": "alive"
    }
    collection.insert_one(doc)
    print(f"[{timestamp}] Записано: цена BTC = {price} USD")
    
    # Ждём 60 секунд
    time.sleep(60)
