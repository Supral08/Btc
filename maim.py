import os
import time
import threading
from datetime import datetime, timezone

import requests
from http.server import BaseHTTPRequestHandler, HTTPServer


# ============================================================
# CONFIGURATION
# ============================================================

BINANCE_URL = "https://data-api.binance.vision/api/v3/klines"

SYMBOL = "BTCUSDT"
INTERVAL = "15m"

POLL_SECONDS = 15

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Niveaux de liquidité.
# Exemple dans Render :
# LIQUIDITY_LEVELS=65576.8,66157.4,66968.5,64689,63987.9,63724.1
LIQUIDITY_LEVELS = os.getenv("LIQUIDITY_LEVELS", "")


# ============================================================
# VARIABLES GLOBALES
# ============================================================

last_candle_time = None
last_alerted_level = None
last_alerted_candle = None

bot_running = True


# ============================================================
# SERVEUR HTTP POUR RENDER
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()

            self.wfile.write(
                b"BTC SMC BOT - ONLINE\n"
            )

        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()

            self.wfile.write(
                b'{"status":"online","bot":"BTC SMC"}'
            )

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return


def start_web_server():

    port = int(os.getenv("PORT", "10000"))

    server = HTTPServer(
        ("0.0.0.0", port),
        HealthHandler
    )

    print(
        f"[{utc_now()}] Serveur HTTP Render actif sur port {port}",
        flush=True
    )

    server.serve_forever()


# ============================================================
# OUTILS
# ============================================================

def utc_now():

    return datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")


def parse_levels():

    if not LIQUIDITY_LEVELS.strip():
        return []

    levels = []

    for value in LIQUIDITY_LEVELS.split(","):

        value = value.strip()

        try:
            levels.append(float(value))
        except ValueError:
            print(
                f"[WARNING] Niveau invalide ignoré : {value}",
                flush=True
            )

    return levels


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(
            "[TELEGRAM] Token ou Chat ID non configuré.",
            flush=True
        )
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=15
        )

        response.raise_for_status()

        return True

    except Exception as e:

        print(
            f"[ERREUR TELEGRAM] {type(e).__name__}: {e}",
            flush=True
        )

        return False


# ============================================================
# BINANCE
# ============================================================

def get_candles(limit=10):

    params = {
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "limit": limit
    }

    try:

        response = requests.get(
            BINANCE_URL,
            params=params,
            timeout=15,
            headers={
                "User-Agent": "BTC-SMC-Bot/1.0"
            }
        )

        response.raise_for_status()

        data = response.json()

        candles = []

        for row in data:

            candles.append({
                "open_time": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "close_time": int(row[6])
            })

        return candles

    except Exception as e:

        print(
            f"[ERREUR BINANCE] {type(e).__name__}: {e}",
            flush=True
        )

        return None


# ============================================================
# AFFICHAGE BOUGIE
# ============================================================

def print_candle(candle):

    candle_time = datetime.fromtimestamp(
        candle["open_time"] / 1000,
        tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")

    print(
        "\n"
        "----------------------------------------\n"
        f"BTCUSDT M15\n"
        f"Ouverture : {candle_time}\n"
        f"Open       : {candle['open']:.2f}\n"
        f"High       : {candle['high']:.2f}\n"
        f"Low        : {candle['low']:.2f}\n"
        f"Close      : {candle['close']:.2f}\n"
        f"Volume     : {candle['volume']:.4f}\n"
        "----------------------------------------",
        flush=True
    )


# ============================================================
# DETECTION LIQUIDITE
# ============================================================

def detect_liquidity_touch(candle):

    levels = parse_levels()

    if not levels:
        return None

    high = candle["high"]
    low = candle["low"]

    for level in levels:

        if low <= level <= high:

            return level

    return None


# ============================================================
# ALERTE LIQUIDITE
# ============================================================

def process_candle(candle):

    global last_alerted_level
    global last_alerted_candle

    touched_level = detect_liquidity_touch(candle)

    if touched_level is None:
        return

    candle_id = candle["open_time"]

    # Empêche plusieurs alertes identiques
    # pendant la même bougie.
    if (
        last_alerted_level == touched_level
        and last_alerted_candle == candle_id
    ):
        return

    last_alerted_level = touched_level
    last_alerted_candle = candle_id

    message = (
        "🚨 LIQUIDITÉ BTC TOUCHÉE\n\n"
        f"Symbol : {SYMBOL}\n"
        f"Timeframe : M15\n"
        f"Niveau : {touched_level:.2f}\n\n"
        f"Open : {candle['open']:.2f}\n"
        f"High : {candle['high']:.2f}\n"
        f"Low : {candle['low']:.2f}\n"
        f"Close : {candle['close']:.2f}\n\n"
        "⚠️ ZONE D'INTÉRÊT — PAS D'ENTRÉE\n"
        "Appliquer le protocole SMC.\n"
        "Attendre la réaction du marché."
    )

    print(
        "\n"
        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
        "🚨 LIQUIDITE TOUCHEE\n"
        f"Niveau : {touched_level:.2f}\n"
        f"High   : {candle['high']:.2f}\n"
        f"Low    : {candle['low']:.2f}\n"
        "→ OBSERVATION OBLIGATOIRE\n"
        "→ PAS DE BUY / SELL AUTOMATIQUE\n"
        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!",
        flush=True
    )

    telegram_send(message)


# ============================================================
# SURVEILLANCE PRINCIPALE
# ============================================================

def trading_loop():

    global last_candle_time

    print(
        "==================================================",
        flush=True
    )

    print(
        "BTC SMC BOT - SCANNER",
        flush=True
    )

    print(
        "Source : Binance Public Market Data",
        flush=True
    )

    print(
        f"Symbol : {SYMBOL}",
        flush=True
    )

    print(
        f"Timeframe : {INTERVAL}",
        flush=True
    )

    print(
        "==================================================",
        flush=True
    )

    levels = parse_levels()

    if levels:

        print(
            f"[LIQUIDITÉ] {len(levels)} niveaux configurés :",
            flush=True
        )

        for level in levels:

            print(
                f"  - {level:.2f}",
                flush=True
            )

    else:

        print(
            "[LIQUIDITÉ] Aucun niveau configuré.",
            flush=True
        )

    print(
        "Connexion aux données publiques Binance...",
        flush=True
    )

    # Test immédiat
    candles = get_candles(10)

    if candles is None:

        print(
            "[ERREUR] Impossible de récupérer les données Binance.",
            flush=True
        )

    else:

        print(
            f"[OK] {len(candles)} bougies M15 reçues.",
            flush=True
        )

        print_candle(candles[-1])

    # Boucle
    while bot_running:

        try:

            candles = get_candles(10)

            if candles is None:

                time.sleep(POLL_SECONDS)

                continue

            # La dernière bougie peut encore être en formation.
            # On travaille sur la dernière bougie clôturée.
            closed_candle = candles[-2]

            candle_time = closed_candle["open_time"]

            if candle_time != last_candle_time:

                last_candle_time = candle_time

                print(
                    f"\n[{utc_now()}] NOUVELLE BOUGIE M15 CLÔTURÉE",
                    flush=True
                )

                print_candle(closed_candle)

                process_candle(closed_candle)

            time.sleep(POLL_SECONDS)

        except Exception as e:

            print(
                f"[ERREUR LOOP] {type(e).__name__}: {e}",
                flush=True
            )

            time.sleep(POLL_SECONDS)


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "==================================================",
        flush=True
    )

    print(
        "BOT BTC SMC - DEMARRAGE",
        flush=True
    )

    print(
        "==================================================",
        flush=True
    )

    # Render doit détecter un port ouvert.
    web_thread = threading.Thread(
        target=start_web_server,
        daemon=True
    )

    web_thread.start()

    # Scanner BTC
    trading_loop()


if __name__ == "__main__":
    main()
