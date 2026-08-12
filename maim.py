import os
import time
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests


# ============================================================
# BTC SMC BOT V3.1
# - Binance public M15 data
# - Liquidity contact detection
# - Memory of N candles after contact
# - Structural report
# - Dynamic swing zones
# - Telegram commands
# - Levels saved in state
# - NO automatic BUY/SELL
# ============================================================

BINANCE_URL = "https://data-api.binance.vision/api/v3/klines"

SYMBOL = "BTCUSDT"
INTERVAL = "15m"
POLL_SECONDS = 15

OBSERVATION_CANDLES = int(os.getenv("OBSERVATION_CANDLES", "8"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

ENV_LIQUIDITY_LEVELS = os.getenv("LIQUIDITY_LEVELS", "")

STATE_FILE = "smc_state.json"

bot_running = True
last_candle_time = None
telegram_offset = 0

active_observations = {}
completed_observations = []
dynamic_zones = []

# Levels used by the running bot.
# Environment variable is used as initial/default configuration.
current_liquidity_levels = []


# ============================================================
# TIME / UTILS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def candle_datetime(timestamp):
    return datetime.fromtimestamp(
        timestamp / 1000,
        tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")


def parse_level_string(value):
    levels = []

    if not value or not value.strip():
        return levels

    for item in value.split(","):
        item = item.strip()

        try:
            levels.append(float(item))
        except ValueError:
            print(
                f"[WARNING] Niveau invalide ignoré : {item}",
                flush=True
            )

    # Remove duplicates and sort
    return sorted(set(levels))


# ============================================================
# STATE
# ============================================================

def save_state():
    data = {
        "liquidity_levels": current_liquidity_levels,
        "active_observations": active_observations,
        "completed_observations": completed_observations[-20:],
        "dynamic_zones": dynamic_zones[-100:]
    }

    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    except Exception as e:
        print(
            f"[STATE] Erreur sauvegarde : {type(e).__name__} - {e}",
            flush=True
        )


def load_state():
    global active_observations
    global completed_observations
    global dynamic_zones
    global current_liquidity_levels

    # Initial/default levels from Render environment.
    env_levels = parse_level_string(ENV_LIQUIDITY_LEVELS)

    if not os.path.exists(STATE_FILE):
        current_liquidity_levels = env_levels
        print(
            "[STATE] Aucun état précédent. "
            "Niveaux chargés depuis Render.",
            flush=True
        )
        return

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        saved_levels = data.get("liquidity_levels")

        if isinstance(saved_levels, list) and saved_levels:
            current_liquidity_levels = [
                float(x) for x in saved_levels
            ]
            print(
                "[STATE] Niveaux Telegram restaurés.",
                flush=True
            )
        else:
            current_liquidity_levels = env_levels

        active_observations = data.get(
            "active_observations", {}
        )

        completed_observations = data.get(
            "completed_observations", []
        )

        dynamic_zones = data.get(
            "dynamic_zones", []
        )

        print("[STATE] Mémoire restaurée.", flush=True)

    except Exception as e:
        current_liquidity_levels = env_levels

        print(
            f"[STATE] Impossible de restaurer : "
            f"{type(e).__name__} - {e}",
            flush=True
        )


# ============================================================
# RENDER HTTP
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(
                b"BTC SMC BOT V3.1 - ONLINE\n"
            )

        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                b'{"status":"online","bot":"BTC SMC V3.1"}'
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
# TELEGRAM
# ============================================================

def telegram_send(message):

    if not TELEGRAM_TOKEN:
        print("[TELEGRAM] Token non configuré.", flush=True)
        return False

    if not TELEGRAM_CHAT_ID:
        print("[TELEGRAM] CHAT_ID non configuré.", flush=True)
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
            f"[TELEGRAM] Erreur : "
            f"{type(e).__name__} - {e}",
            flush=True
        )
        return False


def telegram_api(method, params=None):

    if not TELEGRAM_TOKEN:
        return None

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/{method}"
    )

    try:
        response = requests.get(
            url,
            params=params,
            timeout=30
        )

        response.raise_for_status()
        return response.json()

    except Exception as e:
        print(
            f"[TELEGRAM API] {method} : {e}",
            flush=True
        )
        return None


# ============================================================
# COMMANDS
# ============================================================

def handle_command(text):

    global current_liquidity_levels

    if not text:
        return

    parts = text.strip().split()

    if not parts:
        return

    command = parts[0].lower()

    # --------------------------------------------------------
    # /start
    # --------------------------------------------------------

    if command == "/start":

        levels_text = (
            "\n".join(
                f"• {x:.2f}"
                for x in current_liquidity_levels
            )
            if current_liquidity_levels
            else "Aucun niveau configuré."
        )

        telegram_send(
            "🤖 BTC SMC BOT V3.1\n\n"
            "✅ Bot opérationnel.\n"
            f"📊 {SYMBOL} — {INTERVAL}\n"
            f"🔎 Observation : {OBSERVATION_CANDLES} bougies M15\n\n"
            "📍 Niveaux surveillés :\n"
            f"{levels_text}\n\n"
            "Commandes :\n"
            "/levels 63700 63580\n"
            "/levels\n"
            "/status\n"
            "/zones\n"
            "/reset\n"
            "/clear"
        )

        return

    # --------------------------------------------------------
    # /levels
    # --------------------------------------------------------

    if command == "/levels":

        if len(parts) == 1:

            if not current_liquidity_levels:
                telegram_send(
                    "⚠️ Aucun niveau principal configuré."
                )
                return

            telegram_send(
                "📊 NIVEAUX PRINCIPAUX\n\n"
                + "\n".join(
                    f"{i}. {level:.2f}"
                    for i, level in enumerate(
                        current_liquidity_levels,
                        start=1
                    )
                )
            )

            return

        new_levels = parse_level_string(
            ",".join(parts[1:])
        )

        if not new_levels:
            telegram_send(
                "❌ Aucun niveau valide."
            )
            return

        current_liquidity_levels = new_levels

        # Sauvegarde immédiate
        save_state()

        telegram_send(
            "✅ NIVEAUX MIS À JOUR\n\n"
            + "\n".join(
                f"• {x:.2f}"
                for x in new_levels
            )
            + "\n\n"
            "Le bot surveille maintenant ces niveaux."
        )

        print(
            "[LIQUIDITÉ] Niveaux mis à jour via Telegram : "
            f"{current_liquidity_levels}",
            flush=True
        )

        return

    # --------------------------------------------------------
    # /status
    # --------------------------------------------------------

    if command == "/status":

        telegram_send(
            "📡 BTC SMC BOT V3.1\n\n"
            "État : ACTIF\n"
            f"Symbole : {SYMBOL}\n"
            f"Timeframe : {INTERVAL}\n"
            f"Observation : {OBSERVATION_CANDLES} bougies\n\n"
            f"Niveaux : {len(current_liquidity_levels)}\n"
            f"Observations actives : "
            f"{len(active_observations)}\n"
            f"Rapports terminés : "
            f"{len(completed_observations)}\n"
            f"Zones dynamiques : "
            f"{len(dynamic_zones)}"
        )

        return

    # --------------------------------------------------------
    # /zones
    # --------------------------------------------------------

    if command == "/zones":

        if not dynamic_zones:
            telegram_send(
                "📭 Aucune nouvelle zone détectée."
            )
            return

        message = "🧭 NOUVELLES ZONES\n\n"

        for zone in dynamic_zones[-10:]:
            message += (
                f"• {zone['type']} : "
                f"{zone['price']:.2f}\n"
                f"  Source : "
                f"{zone['source_level']:.2f}\n"
                f"  Temps : "
                f"{zone['time']}\n\n"
            )

        telegram_send(message)
        return

    # --------------------------------------------------------
    # /reset
    # --------------------------------------------------------

    if command == "/reset":

        active_observations.clear()
        completed_observations.clear()

        save_state()

        telegram_send(
            "♻️ MÉMOIRE RÉINITIALISÉE.\n\n"
            "Les niveaux principaux restent actifs."
        )

        return

    # --------------------------------------------------------
    # /clear
    # --------------------------------------------------------

    if command == "/clear":

        active_observations.clear()
        completed_observations.clear()
        dynamic_zones.clear()

        save_state()

        telegram_send(
            "🗑️ Observations, rapports et "
            "zones dynamiques supprimés.\n\n"
            "Les niveaux principaux restent actifs."
        )

        return

    telegram_send(
        "❓ Commande inconnue.\n\n"
        "Utilise /start pour voir les commandes."
    )


def telegram_listener():

    global telegram_offset

    print(
        "[TELEGRAM] Écoute des commandes activée.",
        flush=True
    )

    # Ignore les anciens messages présents avant le démarrage.
    result = telegram_api(
        "getUpdates",
        {
            "offset": -1,
            "timeout": 1
        }
    )

    if result and result.get("ok"):
        updates = result.get("result", [])

        if updates:
            telegram_offset = (
                updates[-1]["update_id"] + 1
            )

    while bot_running:

        try:

            result = telegram_api(
                "getUpdates",
                {
                    "offset": telegram_offset,
                    "timeout": 25
                }
            )

            if not result or not result.get("ok"):
                time.sleep(3)
                continue

            updates = result.get("result", [])

            for update in updates:

                telegram_offset = (
                    update["update_id"] + 1
                )

                message = update.get("message")

                if not message:
                    continue

                chat_id = str(
                    message["chat"]["id"]
                )

                # Seul le CHAT_ID configuré peut commander le bot.
                if str(TELEGRAM_CHAT_ID) != chat_id:
                    continue

                text = message.get("text", "")

                if text.startswith("/"):
                    handle_command(text)

        except Exception as e:

            print(
                f"[TELEGRAM LOOP] "
                f"{type(e).__name__}: {e}",
                flush=True
            )

            time.sleep(5)


# ============================================================
# BINANCE
# ============================================================

def get_candles(limit=60):

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
                "User-Agent": "BTC-SMC-Bot/3.1"
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
            f"[BINANCE] Erreur : "
            f"{type(e).__name__} - {e}",
            flush=True
        )

        return None


# ============================================================
# CANDLE
# ============================================================

def print_candle(candle):

    print(
        "\n"
        "----------------------------------------\n"
        "BTCUSDT M15\n"
        f"Ouverture : "
        f"{candle_datetime(candle['open_time'])}\n"
        f"Open       : {candle['open']:.2f}\n"
        f"High       : {candle['high']:.2f}\n"
        f"Low        : {candle['low']:.2f}\n"
        f"Close      : {candle['close']:.2f}\n"
        f"Volume     : {candle['volume']:.4f}\n"
        "----------------------------------------",
        flush=True
    )


# ============================================================
# LIQUIDITY CONTACT
# ============================================================

def detect_liquidity_touch(candle):

    touched = []

    for level in current_liquidity_levels:

        if (
            candle["low"]
            <= level
            <= candle["high"]
        ):
            touched.append(level)

    return touched


# ============================================================
# CREATE OBSERVATION
# ============================================================

def create_observation(level, candle):

    key = str(level)

    if key in active_observations:
        return

    observation = {
        "level": level,
        "contact_candle": candle,
        "candles": [],
        "created_at": utc_now(),
        "status": "OBSERVATION",
        "reaction": False,
        "mss": False,
        "displacement": False,
        "rejection": False,
        "new_zones": []
    }

    active_observations[key] = observation

    save_state()

    print(
        "\n"
        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
        f"🚨 CONTACT LIQUIDITÉ : {level:.2f}\n"
        "→ MÉMOIRE ACTIVÉE\n"
        f"→ OBSERVATION : {OBSERVATION_CANDLES} M15\n"
        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!",
        flush=True
    )

    telegram_send(
        "🚨 CONTACT LIQUIDITÉ BTC\n\n"
        f"Niveau : {level:.2f}\n"
        f"Timeframe : {INTERVAL}\n"
        f"Bougie contact : "
        f"{candle_datetime(candle['open_time'])}\n\n"
        "📋 Mémoire activée.\n"
        f"Observation des {OBSERVATION_CANDLES} "
        "prochaines bougies M15.\n\n"
        "⚠️ Aucun BUY/SELL."
    )


# ============================================================
# REJECTION
# ============================================================

def candle_rejection(candle, level):

    body = abs(
        candle["close"]
        - candle["open"]
    )

    total_range = (
        candle["high"]
        - candle["low"]
    )

    if total_range <= 0:
        return False

    upper_wick = (
        candle["high"]
        - max(candle["open"], candle["close"])
    )

    lower_wick = (
        min(candle["open"], candle["close"])
        - candle["low"]
    )

    if (
        candle["low"] <= level
        and candle["close"] > level
        and lower_wick > body
    ):
        return True

    if (
        candle["high"] >= level
        and candle["close"] < level
        and upper_wick > body
    ):
        return True

    return False


# ============================================================
# DISPLACEMENT
# ============================================================

def detect_displacement(candles, index):

    if index < 3:
        return False

    current = candles[index]

    current_range = (
        current["high"]
        - current["low"]
    )

    previous_ranges = []

    for c in candles[max(0, index - 5):index]:
        previous_ranges.append(
            c["high"] - c["low"]
        )

    if not previous_ranges:
        return False

    average_range = (
        sum(previous_ranges)
        / len(previous_ranges)
    )

    if average_range <= 0 or current_range <= 0:
        return False

    bullish_close = (
        current["close"] - current["low"]
    ) / current_range

    bearish_close = (
        current["high"] - current["close"]
    ) / current_range

    if current_range >= average_range * 1.5:

        if (
            bullish_close >= 0.70
            or bearish_close >= 0.70
        ):
            return True

    return False


# ============================================================
# SWINGS / DYNAMIC ZONES
# ============================================================

def detect_swing_high(candles, index):

    if index < 1 or index >= len(candles) - 1:
        return False

    return (
        candles[index]["high"]
        > candles[index - 1]["high"]
        and
        candles[index]["high"]
        >= candles[index + 1]["high"]
    )


def detect_swing_low(candles, index):

    if index < 1 or index >= len(candles) - 1:
        return False

    return (
        candles[index]["low"]
        < candles[index - 1]["low"]
        and
        candles[index]["low"]
        <= candles[index + 1]["low"]
    )


def register_dynamic_zone(
    observation,
    zone_type,
    price
):

    source_level = observation["level"]

    for zone in dynamic_zones:

        if (
            zone["type"] == zone_type
            and abs(zone["price"] - price) < 1.0
        ):
            return

    zone = {
        "type": zone_type,
        "price": price,
        "source_level": source_level,
        "time": utc_now()
    }

    dynamic_zones.append(zone)

    observation["new_zones"].append(zone)

    print(
        f"[NOUVELLE ZONE] "
        f"{zone_type} : {price:.2f} "
        f"(source {source_level:.2f})",
        flush=True
    )


# ============================================================
# MSS OBJECTIF / DESCRIPTIF
# ============================================================

def detect_mss(candles):

    if len(candles) < 4:
        return False

    last = candles[-1]

    previous_high = max(
        c["high"] for c in candles[:-1]
    )

    previous_low = min(
        c["low"] for c in candles[:-1]
    )

    bullish_break = last["close"] > previous_high
    bearish_break = last["close"] < previous_low

    return bullish_break or bearish_break


# ============================================================
# PROCESS OBSERVATION CANDLE
# ============================================================

def process_observation_candle(
    observation,
    candle
):

    observation["candles"].append(candle)

    candles = observation["candles"]
    index = len(candles) - 1

    if candle_rejection(
        candle,
        observation["level"]
    ):
        observation["rejection"] = True
        observation["reaction"] = True

    if detect_displacement(
        candles,
        index
    ):
        observation["displacement"] = True
        observation["reaction"] = True

    if detect_mss(candles):
        observation["mss"] = True
        observation["reaction"] = True

    if len(candles) >= 3:

        swing_index = len(candles) - 2
        swing_candle = candles[swing_index]

        if detect_swing_high(
            candles,
            swing_index
        ):
            register_dynamic_zone(
                observation,
                "SWING_HIGH",
                swing_candle["high"]
            )

        if detect_swing_low(
            candles,
            swing_index
        ):
            register_dynamic_zone(
                observation,
                "SWING_LOW",
                swing_candle["low"]
            )


# ============================================================
# REPORT
# ============================================================

def generate_report(observation):

    candles = observation["candles"]
    level = observation["level"]

    report = [
        "📊 RAPPORT BTC SMC — OBSERVATION TERMINÉE",
        "",
        f"Liquidité surveillée : {level:.2f}",
        "Bougie contact : "
        f"{candle_datetime(observation['contact_candle']['open_time'])}",
        f"Nombre de bougies observées : {len(candles)}",
        "",
        "1️⃣ RÉACTION",
        "Rejet : "
        f"{'OUI' if observation['rejection'] else 'NON'}",
        "Displacement : "
        f"{'OUI' if observation['displacement'] else 'NON'}",
        "MSS potentiel : "
        f"{'OUI' if observation['mss'] else 'NON'}",
        "",
        "2️⃣ ÉTAT DE LA RÉACTION",
        (
            "🟡 RÉACTION STRUCTURELLE DÉTECTÉE"
            if observation["reaction"]
            else "⚪ AUCUNE RÉACTION EXPLOITABLE"
        ),
        "",
        "3️⃣ BOUGIES M15 MÉMORISÉES"
    ]

    for i, candle in enumerate(candles, start=1):

        report.append(
            f"C{i} | "
            f"O {candle['open']:.2f} | "
            f"H {candle['high']:.2f} | "
            f"L {candle['low']:.2f} | "
            f"C {candle['close']:.2f} | "
            f"V {candle['volume']:.4f}"
        )

    report.extend([
        "",
        "4️⃣ NOUVELLES ZONES / STRUCTURES"
    ])

    if observation["new_zones"]:

        for zone in observation["new_zones"]:
            report.append(
                f"• {zone['type']} : "
                f"{zone['price']:.2f}"
            )

    else:
        report.append(
            "Aucune nouvelle zone détectée."
        )

    report.extend([
        "",
        "5️⃣ RÈGLE",
        "Ce rapport est descriptif.",
        "Aucun BUY/SELL automatique.",
        "Aucune entrée validée.",
        "Analyse sceptique externe nécessaire."
    ])

    return "\n".join(report)


# ============================================================
# FIN OBSERVATION
# ============================================================

def finish_observation(key):

    observation = active_observations.get(key)

    if not observation:
        return

    observation["status"] = "TERMINEE"

    report = generate_report(observation)

    print(
        "\n"
        "==================================================\n"
        "RAPPORT OBSERVATION\n"
        "==================================================\n"
        f"{report}\n"
        "==================================================",
        flush=True
    )

    telegram_send(report)

    completed_observations.append(observation)

    del active_observations[key]

    save_state()


# ============================================================
# CONTACTS
# ============================================================

def process_liquidity_contacts(candle):

    touched_levels = detect_liquidity_touch(candle)

    for level in touched_levels:
        create_observation(level, candle)


# ============================================================
# ACTIVE OBSERVATIONS
# ============================================================

def update_active_observations(candle):

    finished = []

    for key, observation in list(
        active_observations.items()
    ):

        contact_time = observation[
            "contact_candle"
        ]["open_time"]

        if candle["open_time"] <= contact_time:
            continue

        already = any(
            c["open_time"] == candle["open_time"]
            for c in observation["candles"]
        )

        if already:
            continue

        process_observation_candle(
            observation,
            candle
        )

        count = len(
            observation["candles"]
        )

        print(
            f"[OBSERVATION] "
            f"Niveau {observation['level']:.2f} "
            f"→ {count}/{OBSERVATION_CANDLES} bougies",
            flush=True
        )

        if count >= OBSERVATION_CANDLES:
            finished.append(key)

    for key in finished:
        finish_observation(key)


# ============================================================
# MAIN TRADING LOOP
# ============================================================

def trading_loop():

    global last_candle_time

    print("=" * 50, flush=True)
    print("BTC SMC BOT V3.1 - PROTOCOLE", flush=True)
    print("Source : Binance Public Market Data", flush=True)
    print(f"Symbol : {SYMBOL}", flush=True)
    print(f"Timeframe : {INTERVAL}", flush=True)
    print(
        f"Observation : {OBSERVATION_CANDLES} bougies M15",
        flush=True
    )
    print("=" * 50, flush=True)

    if current_liquidity_levels:

        print("[LIQUIDITÉ]", flush=True)

        for level in current_liquidity_levels:
            print(
                f"  - {level:.2f}",
                flush=True
            )

    else:
        print(
            "[WARNING] Aucun niveau configuré.",
            flush=True
        )

    print(
        "Connexion aux données Binance...",
        flush=True
    )

    candles = get_candles(60)

    if candles:

        print(
            f"[OK] {len(candles)} bougies M15 reçues.",
            flush=True
        )

        print_candle(candles[-2])

    while bot_running:

        try:

            candles = get_candles(60)

            if not candles:
                time.sleep(POLL_SECONDS)
                continue

            closed_candle = candles[-2]

            candle_time = closed_candle["open_time"]

            if candle_time != last_candle_time:

                last_candle_time = candle_time

                print(
                    f"\n[{utc_now()}] "
                    "NOUVELLE BOUGIE M15 CLÔTURÉE",
                    flush=True
                )

                print_candle(closed_candle)

                # 1. Observations existantes
                update_active_observations(
                    closed_candle
                )

                # 2. Nouveaux contacts
                process_liquidity_contacts(
                    closed_candle
                )

                save_state()

            time.sleep(POLL_SECONDS)

        except Exception as e:

            print(
                f"[LOOP] "
                f"{type(e).__name__}: {e}",
                flush=True
            )

            time.sleep(POLL_SECONDS)


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 50, flush=True)
    print("BOT BTC SMC V3.1 - DEMARRAGE", flush=True)
    print("=" * 50, flush=True)

    load_state()

    web_thread = threading.Thread(
        target=start_web_server,
        daemon=True
    )

    web_thread.start()

    telegram_thread = threading.Thread(
        target=telegram_listener,
        daemon=True
    )

    telegram_thread.start()

    trading_loop()


if __name__ == "__main__":
    main()
