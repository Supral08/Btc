import time
import requests
from datetime import datetime, timezone

BYBIT_URL = "https://api.bybit.com/v5/market/kline"
SYMBOL = "BTCUSDT"
INTERVAL = "15"
LIMIT = 10


def get_btc_data():
    params = {
        "category": "linear",
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "limit": LIMIT
    }

    response = requests.get(BYBIT_URL, params=params, timeout=10)
    response.raise_for_status()

    data = response.json()

    if data.get("retCode") != 0:
        raise Exception(data.get("retMsg", "Erreur Bybit"))

    candles = data["result"]["list"]

    candles.reverse()

    return candles


def display_btc_data():
    candles = get_btc_data()

    last = candles[-1]

    timestamp = int(last[0]) / 1000
    candle_time = datetime.fromtimestamp(
        timestamp,
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")

    open_price = float(last[1])
    high = float(last[2])
    low = float(last[3])
    close = float(last[4])
    volume = float(last[5])

    now = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    print("=" * 50, flush=True)
    print(f"[{now}] BTCUSDT - DONNEES BYBIT", flush=True)
    print(f"Bougie M15 : {candle_time}", flush=True)
    print(f"Open  : {open_price}", flush=True)
    print(f"High  : {high}", flush=True)
    print(f"Low   : {low}", flush=True)
    print(f"Close : {close}", flush=True)
    print(f"Volume: {volume}", flush=True)
    print("=" * 50, flush=True)


print("=" * 50, flush=True)
print("BOT BTC SMC - DEMARRAGE", flush=True)
print("Connexion aux données publiques Bybit...", flush=True)
print("=" * 50, flush=True)


while True:

    try:
        display_btc_data()

    except Exception as e:
        print(
            f"ERREUR BYBIT : {type(e).__name__} - {e}",
            flush=True
        )

    time.sleep(60)
