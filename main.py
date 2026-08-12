import os
import time
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests


# ============================================================
# CONFIGURATION
# ============================================================

BINANCE_URL = "https://data-api.binance.vision/api/v3/klines"

SYMBOL = "BTCUSDT"
INTERVAL = "15m"

POLL_SECONDS = 15

# Nombre de bougies M15 observées APRÈS le contact
OBSERVATION_CANDLES = int(
    os.getenv("OBSERVATION_CANDLES", "8")
)

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)

LIQUIDITY_LEVELS = os.getenv(
    "LIQUIDITY_LEVELS",
    ""
)

STATE_FILE = "smc_state.json"


# ============================================================
# VARIABLES GLOBALES
# ============================================================

bot_running = True

last_candle_time = None

telegram_offset = 0

# Observations actuellement actives
active_observations = {}

# Historique terminé
completed_observations = []

# Nouvelles zones détectées
dynamic_zones = []


# ============================================================
# TEMPS
# ============================================================

def utc_now():
    return datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")


def candle_datetime(timestamp):
    return datetime.fromtimestamp(
        timestamp / 1000,
        tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")


# ============================================================
# STOCKAGE
# ============================================================

def save_state():

    data = {
        "active_observations": active_observations,
        "completed_observations": completed_observations[-20:],
        "dynamic_zones": dynamic_zones[-100:]
    }

    try:

        with open(
            STATE_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                indent=2
            )

    except Exception as e:

        print(
            f"[STATE] Erreur sauvegarde : {e}",
            flush=True
        )


def load_state():

    global active_observations
    global completed_observations
    global dynamic_zones

    if not os.path.exists(STATE_FILE):
        return

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        active_observations = data.get(
            "active_observations",
            {}
        )

        completed_observations = data.get(
            "completed_observations",
            []
        )

        dynamic_zones = data.get(
            "dynamic_zones",
            []
        )

        print(
            "[STATE] Mémoire restaurée.",
            flush=True
        )

    except Exception as e:

        print(
            f"[STATE] Impossible de restaurer : {e}",
            flush=True
        )


# ============================================================
# SERVEUR HTTP RENDER
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        if self.path == "/":

            self.send_response(200)

            self.send_header(
                "Content-Type",
                "text/plain"
            )

            self.end_headers()

            self.wfile.write(
                b"BTC SMC BOT V3 - ONLINE\n"
            )

        elif self.path == "/health":

            self.send_response(200)

            self.send_header(
                "Content-Type",
                "application/json"
            )

            self.end_headers()

            self.wfile.write(
                b'{"status":"online","bot":"BTC SMC V3"}'
            )

        else:

            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return


def start_web_server():

    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    server = HTTPServer(
        ("0.0.0.0", port),
        HealthHandler
    )

    print(
        f"[{utc_now()}] "
        f"Serveur HTTP Render actif sur port {port}",
        flush=True
    )

    server.serve_forever()


# ============================================================
# LIQUIDITÉ
# ============================================================

def parse_levels():

    if not LIQUIDITY_LEVELS.strip():
        return []

    levels = []

    for value in LIQUIDITY_LEVELS.split(","):

        value = value.strip()

        try:

            levels.append(
                float(value)
            )

        except ValueError:

            print(
                f"[WARNING] Niveau invalide : {value}",
                flush=True
            )

    return levels


def get_current_levels():

    """
    Les niveaux peuvent venir de Render
    ou être modifiés avec /levels.
    """

    if dynamic_zones:

        # Les zones dynamiques ne remplacent pas
        # les niveaux principaux.
        pass

    return parse_levels()


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):

    if not TELEGRAM_TOKEN:

        print(
            "[TELEGRAM] Token non configuré.",
            flush=True
        )

        return False

    if not TELEGRAM_CHAT_ID:

        print(
            "[TELEGRAM] CHAT_ID non configuré.",
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
# COMMANDES TELEGRAM
# ============================================================

def handle_command(text):

    global LIQUIDITY_LEVELS
    global active_observations
    global dynamic_zones

    if not text:
        return

    parts = text.strip().split()

    command = parts[0].lower()

    # --------------------------------------------------------
    # /start
    # --------------------------------------------------------

    if command == "/start":

        telegram_send(
            "🤖 BTC SMC BOT V3\n\n"
            "Bot opérationnel.\n\n"
            "Commandes disponibles :\n"
            "/levels 63900 63600\n"
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

            levels = parse_levels()

            if not levels:

                telegram_send(
                    "⚠️ Aucun niveau principal configuré."
                )

                return

            message = (
                "📊 NIVEAUX PRINCIPAUX\n\n"
            )

            for i, level in enumerate(
                levels,
                start=1
            ):

                message += (
                    f"{i}. {level:.2f}\n"
                )

            telegram_send(message)

            return

        new_levels = []

        for value in parts[1:]:

            try:

                new_levels.append(
                    float(value)
                )

            except ValueError:

                pass

        if not new_levels:

            telegram_send(
                "❌ Aucun niveau valide."
            )

            return

        # Mise à jour en mémoire
        LIQUIDITY_LEVELS = ",".join(
            str(x)
            for x in new_levels
        )

        telegram_send(
            "✅ NIVEAUX MIS À JOUR\n\n"
            + "\n".join(
                f"• {x:.2f}"
                for x in new_levels
            )
            + "\n\n"
            "Le bot surveille maintenant "
            "ces niveaux."
        )

        print(
            "[LIQUIDITÉ] Niveaux mis à jour via Telegram : "
            f"{LIQUIDITY_LEVELS}",
            flush=True
        )

        return

    # --------------------------------------------------------
    # /status
    # --------------------------------------------------------

    if command == "/status":

        levels = parse_levels()

        message = (
            "📡 BTC SMC BOT V3\n\n"
            f"État : ACTIF\n"
            f"Symbole : {SYMBOL}\n"
            f"Timeframe : {INTERVAL}\n"
            f"Observation : "
            f"{OBSERVATION_CANDLES} bougies\n\n"
            f"Niveaux : {len(levels)}\n"
            f"Observations actives : "
            f"{len(active_observations)}\n"
            f"Zones dynamiques : "
            f"{len(dynamic_zones)}"
        )

        telegram_send(message)

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

        message = (
            "🧭 NOUVELLES ZONES\n\n"
        )

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
            "🗑️ Mémoire, observations et "
            "zones dynamiques supprimées."
        )

        return


def telegram_listener():

    global telegram_offset

    print(
        "[TELEGRAM] Écoute des commandes activée.",
        flush=True
    )

    # Évite les anciens messages accumulés
    result = telegram_api(
        "getUpdates",
        {
            "offset": -1,
            "timeout": 1
        }
    )

    if result and result.get("ok"):

        updates = result.get(
            "result",
            []
        )

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

            updates = result.get(
                "result",
                []
            )

            for update in updates:

                telegram_offset = (
                    update["update_id"] + 1
                )

                message = update.get(
                    "message"
                )

                if not message:
                    continue

                chat_id = str(
                    message["chat"]["id"]
                )

                # Sécurité : seul ton CHAT_ID
                # peut contrôler le bot.
                if str(TELEGRAM_CHAT_ID) != chat_id:

                    continue

                text = message.get(
                    "text",
                    ""
                )

                if text.startswith("/"):

                    handle_command(text)

        except Exception as e:

            print(
                f"[TELEGRAM LOOP] {type(e).__name__}: {e}",
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
                "User-Agent": "BTC-SMC-Bot/3.0"
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
# BOUGIE
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
# CONTACT LIQUIDITÉ
# ============================================================

def detect_liquidity_touch(candle):

    levels = parse_levels()

    if not levels:
        return []

    touched = []

    for level in levels:

        if (
            candle["low"]
            <= level
            <= candle["high"]
        ):

            touched.append(level)

    return touched


# ============================================================
# CRÉATION OBSERVATION
# ============================================================

def create_observation(
    level,
    candle
):

    key = str(level)

    # Une observation du même niveau
    # ne doit pas être recréée.
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
        f"→ OBSERVATION : "
        f"{OBSERVATION_CANDLES} M15\n"
        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!",
        flush=True
    )

    telegram_send(
        "🚨 CONTACT LIQUIDITÉ BTC\n\n"
        f"Niveau : {level:.2f}\n"
        f"Timeframe : {INTERVAL}\n"
        f"Bougie contact : "
        f"{candle_datetime(candle['open_time'])}\n\n"
        f"📋 Mémoire activée.\n"
        f"Observation des "
        f"{OBSERVATION_CANDLES} prochaines bougies M15.\n\n"
        "⚠️ Aucun BUY/SELL."
    )


# ============================================================
# ANALYSE BOUGIE
# ============================================================

def candle_rejection(
    candle,
    level
):

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
        - max(
            candle["open"],
            candle["close"]
        )
    )

    lower_wick = (
        min(
            candle["open"],
            candle["close"]
        )
        - candle["low"]
    )

    # Rejet haussier du niveau
    if (
        candle["low"] <= level
        and candle["close"] > level
        and lower_wick > body
    ):
        return True

    # Rejet baissier du niveau
    if (
        candle["high"] >= level
        and candle["close"] < level
        and upper_wick > body
    ):
        return True

    return False


def detect_displacement(
    candles,
    index
):

    if index < 3:
        return False

    current = candles[index]

    current_range = (
        current["high"]
        - current["low"]
    )

    previous_ranges = []

    for c in candles[
        max(0, index - 5):index
    ]:

        previous_ranges.append(
            c["high"] - c["low"]
        )

    if not previous_ranges:
        return False

    average_range = (
        sum(previous_ranges)
        / len(previous_ranges)
    )

    if average_range <= 0:
        return False

    # Displacement objectif :
    # range nettement supérieur à la moyenne
    # + clôture proche d'une extrémité.
    bullish_close = (
        current["close"]
        - current["low"]
    ) / current_range

    bearish_close = (
        current["high"]
        - current["close"]
    ) / current_range

    if (
        current_range
        >= average_range * 1.5
    ):

        if (
            bullish_close >= 0.70
            or bearish_close >= 0.70
        ):

            return True

    return False


# ============================================================
# SWINGS / NOUVELLES ZONES
# ============================================================

def detect_swing_high(
    candles,
    index
):

    if index < 1:
        return False

    if index >= len(candles) - 1:
        return False

    return (
        candles[index]["high"]
        > candles[index - 1]["high"]
        and
        candles[index]["high"]
        >= candles[index + 1]["high"]
    )


def detect_swing_low(
    candles,
    index
):

    if index < 1:
        return False

    if index >= len(candles) - 1:
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

    # Évite les doublons proches
    for zone in dynamic_zones:

        if (
            zone["type"] == zone_type
            and abs(
                zone["price"] - price
            ) < 1.0
        ):

            return

    zone = {

        "type": zone_type,

        "price": price,

        "source_level": source_level,

        "time": utc_now()
    }

    dynamic_zones.append(zone)

    observation["new_zones"].append(
        zone
    )

    print(
        f"[NOUVELLE ZONE] "
        f"{zone_type} : {price:.2f} "
        f"(source {source_level:.2f})",
        flush=True
    )


# ============================================================
# MSS OBJECTIF
# ============================================================

def detect_mss(
    candles
):

    if len(candles) < 4:
        return False

    # Structure simplifiée :
    # recherche d'un dépassement du dernier
    # swing pertinent.

    last = candles[-1]

    highs = [
        c["high"]
        for c in candles[:-1]
    ]

    lows = [
        c["low"]
        for c in candles[:-1]
    ]

    previous_high = max(highs)
    previous_low = min(lows)

    bullish_break = (
        last["close"]
        > previous_high
    )

    bearish_break = (
        last["close"]
        < previous_low
    )

    return (
        bullish_break
        or bearish_break
    )


# ============================================================
# TRAITEMENT D'UNE BOUGIE D'OBSERVATION
# ============================================================

def process_observation_candle(
    observation,
    candle
):

    observation["candles"].append(
        candle
    )

    candles = observation["candles"]

    index = len(candles) - 1

    # ----------------------------------------
    # Rejet
    # ----------------------------------------

    if candle_rejection(
        candle,
        observation["level"]
    ):

        observation["rejection"] = True
        observation["reaction"] = True

    # ----------------------------------------
    # Displacement
    # ----------------------------------------

    if detect_displacement(
        candles,
        index
    ):

        observation["displacement"] = True
        observation["reaction"] = True

    # ----------------------------------------
    # MSS
    # ----------------------------------------

    if detect_mss(candles):

        observation["mss"] = True
        observation["reaction"] = True

    # ----------------------------------------
    # Swing zones
    #
    # On analyse l'avant-dernière bougie,
    # car elle possède maintenant une bougie
    # à droite pour confirmer le swing.
    # ----------------------------------------

    if len(candles) >= 3:

        swing_index = len(candles) - 2

        swing_candle = candles[
            swing_index
        ]

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
# RAPPORT STRUCTURÉ
# ============================================================

def generate_report(
    observation
):

    candles = observation["candles"]

    level = observation["level"]

    report = []

    report.append(
        "📊 RAPPORT BTC SMC — OBSERVATION TERMINÉE"
    )

    report.append(
        ""
    )

    report.append(
        f"Liquidité surveillée : {level:.2f}"
    )

    report.append(
        f"Bougie contact : "
        f"{candle_datetime(observation['contact_candle']['open_time'])}"
    )

    report.append(
        f"Nombre de bougies observées : "
        f"{len(candles)}"
    )

    report.append("")

    # ----------------------------------------
    # Réaction
    # ----------------------------------------

    report.append(
        "1️⃣ RÉACTION"
    )

    report.append(
        f"Rejet : "
        f"{'OUI' if observation['rejection'] else 'NON'}"
    )

    report.append(
        f"Displacement : "
        f"{'OUI' if observation['displacement'] else 'NON'}"
    )

    report.append(
        f"MSS potentiel : "
        f"{'OUI' if observation['mss'] else 'NON'}"
    )

    report.append("")

    # ----------------------------------------
    # Verdict objectif
    # ----------------------------------------

    report.append(
        "2️⃣ ÉTAT DE LA RÉACTION"
    )

    if observation["reaction"]:

        report.append(
            "🟡 RÉACTION STRUCTURELLE DÉTECTÉE"
        )

    else:

        report.append(
            "⚪ AUCUNE RÉACTION EXPLOITABLE"
        )

    report.append("")

    # ----------------------------------------
    # Bougies
    # ----------------------------------------

    report.append(
        "3️⃣ BOUGIES M15 MÉMORISÉES"
    )

    for i, candle in enumerate(
        candles,
        start=1
    ):

        report.append(
            f"C{i} | "
            f"O {candle['open']:.2f} | "
            f"H {candle['high']:.2f} | "
            f"L {candle['low']:.2f} | "
            f"C {candle['close']:.2f}"
        )

    report.append("")

    # ----------------------------------------
    # Nouvelles zones
    # ----------------------------------------

    report.append(
        "4️⃣ NOUVELLES ZONES / STRUCTURES"
    )

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

    report.append("")

    # ----------------------------------------
    # Règle importante
    # ----------------------------------------

    report.append(
        "5️⃣ RÈGLE"
    )

    report.append(
        "Ce rapport est descriptif."
    )

    report.append(
        "Aucun BUY/SELL automatique."
    )

    report.append(
        "Aucune entrée validée."
    )

    report.append(
        "Analyse sceptique externe nécessaire."
    )

    return "\n".join(report)


# ============================================================
# FIN D'OBSERVATION
# ============================================================

def finish_observation(
    key
):

    observation = active_observations.get(
        key
    )

    if not observation:
        return

    observation["status"] = "TERMINEE"

    report = generate_report(
        observation
    )

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

    completed_observations.append(
        observation
    )

    del active_observations[key]

    save_state()


# ============================================================
# TRAITEMENT DES CONTACTS
# ============================================================

def process_liquidity_contacts(
    candle
):

    touched_levels = detect_liquidity_touch(
        candle
    )

    for level in touched_levels:

        create_observation(
            level,
            candle
        )


# ============================================================
# SURVEILLANCE DES OBSERVATIONS
# ============================================================

def update_active_observations(
    candle
):

    finished = []

    for key, observation in list(
        active_observations.items()
    ):

        # Ne pas utiliser la bougie contact
        # comme première bougie d'observation.
        if (
            candle["open_time"]
            <= observation[
                "contact_candle"
            ]["open_time"]
        ):

            continue

        # Empêche de mémoriser deux fois
        # la même bougie.
        already = any(
            c["open_time"]
            == candle["open_time"]
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
            f"→ {count}/"
            f"{OBSERVATION_CANDLES} bougies",
            flush=True
        )

        if count >= OBSERVATION_CANDLES:

            finished.append(key)

    for key in finished:

        finish_observation(key)


# ============================================================
# BOUCLE PRINCIPALE
# ============================================================

def trading_loop():

    global last_candle_time

    print(
        "==================================================",
        flush=True
    )

    print(
        "BTC SMC BOT V3 - PROTOCOLE",
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
        f"Observation : "
        f"{OBSERVATION_CANDLES} bougies M15",
        flush=True
    )

    print(
        "==================================================",
        flush=True
    )

    levels = parse_levels()

    if levels:

        print(
            "[LIQUIDITÉ]",
            flush=True
        )

        for level in levels:

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

        print_candle(
            candles[-2]
        )

    while bot_running:

        try:

            candles = get_candles(60)

            if not candles:

                time.sleep(
                    POLL_SECONDS
                )

                continue

            # Dernière bougie clôturée
            closed_candle = candles[-2]

            candle_time = (
                closed_candle["open_time"]
            )

            if (
                candle_time
                != last_candle_time
            ):

                last_candle_time = candle_time

                print(
                    f"\n[{utc_now()}] "
                    "NOUVELLE BOUGIE M15 CLÔTURÉE",
                    flush=True
                )

                print_candle(
                    closed_candle
                )

                # ------------------------------------
                # 1. Mettre à jour les observations
                # ------------------------------------

                update_active_observations(
                    closed_candle
                )

                # ------------------------------------
                # 2. Chercher de nouveaux contacts
                # ------------------------------------

                process_liquidity_contacts(
                    closed_candle
                )

                save_state()

            time.sleep(
                POLL_SECONDS
            )

        except Exception as e:

            print(
                f"[LOOP] "
                f"{type(e).__name__}: {e}",
                flush=True
            )

            time.sleep(
                POLL_SECONDS
            )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "==================================================",
        flush=True
    )

    print(
        "BOT BTC SMC V3 - DEMARRAGE",
        flush=True
    )

    print(
        "==================================================",
        flush=True
    )

    load_state()

    # Serveur Render
    web_thread = threading.Thread(
        target=start_web_server,
        daemon=True
    )

    web_thread.start()

    # Telegram
    telegram_thread = threading.Thread(
        target=telegram_listener,
        daemon=True
    )

    telegram_thread.start()

    # Scanner
    trading_loop()


if __name__ == "__main__":

    main()
