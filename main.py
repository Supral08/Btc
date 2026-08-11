import os
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests


# ============================================================
# CONFIGURATION
# ============================================================

PORT = int(os.environ.get("PORT", 10000))

BYBIT_URL = "https://api.bybit.com/v5/market/kline"

SYMBOL = "BTCUSDT"
CATEGORY = "linear"
INTERVAL = "15"

NUMBER_OF_CANDLES = 20


# ============================================================
# SERVEUR HTTP POUR RENDER
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"SMC Trading Bot is running.")

    def log_message(self, format, *args):
        return


def start_server():

    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)

    print(f"[SYSTEM] HTTP server actif sur le port {PORT}")

    server.serve_forever()


# ============================================================
# BYBIT — RECUPERATION DES BOUGIES M15
# ============================================================

def get_btc_candles():

    params = {
        "category": CATEGORY,
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "limit": NUMBER_OF_CANDLES
    }

    try:

        response = requests.get(
            BYBIT_URL,
            params=params,
            timeout=10
        )

        response.raise_for_status()

        data = response.json()

        if data.get("retCode") != 0:

            print("[BYBIT ERROR]", data)

            return None

        candles = data["result"]["list"]

        # Bybit renvoie généralement les bougies
        # de la plus récente à la plus ancienne.
        candles.reverse()

        return candles

    except Exception as e:

        print("[BYBIT CONNECTION ERROR]", e)

        return None


# ============================================================
# AFFICHAGE DES DONNEES
# ============================================================

def analyze_market():

    candles = get_btc_candles()

    if not candles:

        print("[WARNING] Impossible de récupérer les bougies.")

        return

    latest = candles[-1]

    timestamp = latest[0]
    open_price = float(latest[1])
    high_price = float(latest[2])
    low_price = float(latest[3])
    close_price = float(latest[4])
    volume = float(latest[5])

    print("-----------------------------------")
    print("BTCUSDT — M15")
    print("-----------------------------------")

    print(f"Open   : {open_price}")
    print(f"High   : {high_price}")
    print(f"Low    : {low_price}")
    print(f"Close  : {close_price}")
    print(f"Volume : {volume}")

    print("-----------------------------------")

    if close_price > open_price:

        print("Bougie : HAUSSIERE")

    elif close_price < open_price:

        print("Bougie : BAISSIERE")

    else:

        print("Bougie : NEUTRE")

    print("-----------------------------------")


# ============================================================
# BOT PRINCIPAL
# ============================================================

def trading_bot():

    print("===================================")
    print("SMC TRADING BOT — V1.1")
    print("===================================")
    print("Connexion Bybit : ACTIVE")
    print("Marché : BTCUSDT")
    print("Timeframe : M15")
    print("Mode : SEMI-AUTOMATIQUE")
    print("Aucun ordre automatique")
    print("===================================")

    while True:

        try:

            analyze_market()

            # Vérification toutes les 60 secondes
            time.sleep(60)

        except Exception as e:

            print("[BOT ERROR]", e)

            time.sleep(10)


# ============================================================
# DEMARRAGE
# ============================================================

if __name__ == "__main__":

    server_thread = threading.Thread(
        target=start_server,
        daemon=True
    )

    server_thread.start()

    trading_bot()
