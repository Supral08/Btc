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
CANDLE_LIMIT = 60

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Format recommandé :
#
# LIQUIDITY_LEVELS=
# BSL:65576.8,66157.4,66968.5;
# SSL:64689,63987.9,63724.1
#
LIQUIDITY_LEVELS = os.getenv("LIQUIDITY_LEVELS", "")


# ============================================================
# ETAT GLOBAL
# ============================================================

last_candle_time = None

observation = None

bot_running = True


# ============================================================
# SERVEUR HTTP RENDER
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        if self.path == "/":

            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()

            self.wfile.write(
                b"BTC SMC BOT V2 - ONLINE\n"
            )

        elif self.path == "/health":

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()

            self.wfile.write(
                b'{"status":"online","bot":"BTC SMC V2"}'
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


def candle_time(candle):

    return datetime.fromtimestamp(
        candle["open_time"] / 1000,
        tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")


# ============================================================
# LIQUIDITÉS
# ============================================================

def parse_levels():

    result = {
        "BSL": [],
        "SSL": []
    }

    if not LIQUIDITY_LEVELS.strip():
        return result

    try:

        sections = LIQUIDITY_LEVELS.split(";")

        for section in sections:

            if ":" not in section:
                continue

            role, values = section.split(":", 1)

            role = role.strip().upper()

            if role not in result:
                continue

            for value in values.split(","):

                value = value.strip()

                try:
                    result[role].append(float(value))

                except ValueError:

                    print(
                        f"[WARNING] Niveau invalide : {value}",
                        flush=True
                    )

    except Exception as e:

        print(
            f"[ERREUR LEVELS] {e}",
            flush=True
        )

    return result


def all_levels():

    levels = parse_levels()

    return levels["BSL"] + levels["SSL"]


def get_level_role(level):

    levels = parse_levels()

    if level in levels["BSL"]:
        return "BSL"

    if level in levels["SSL"]:
        return "SSL"

    return "UNKNOWN"


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

def get_candles(limit=CANDLE_LIMIT):

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
                "User-Agent": "BTC-SMC-Bot/2.0"
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
# EMA
# ============================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    result = sum(values[:period]) / period

    for value in values[period:]:

        result = (
            (value - result) * multiplier
        ) + result

    return result


# ============================================================
# MACD
# ============================================================

def calculate_macd(candles):

    closes = [
        candle["close"]
        for candle in candles
    ]

    if len(closes) < 35:
        return None

    ema12_values = []

    ema26_values = []

    # Calcul simplifié mais cohérent
    # pour permettre le suivi du momentum.

    def ema_series(values, period):

        if len(values) < period:
            return []

        multiplier = 2 / (period + 1)

        current = sum(values[:period]) / period

        result = [current]

        for value in values[period:]:

            current = (
                (value - current) * multiplier
            ) + current

            result.append(current)

        return result

    e12 = ema_series(closes, 12)
    e26 = ema_series(closes, 26)

    if not e12 or not e26:
        return None

    # Alignement approximatif des séries
    length = min(len(e12), len(e26))

    e12 = e12[-length:]
    e26 = e26[-length:]

    macd_values = [
        a - b
        for a, b in zip(e12, e26)
    ]

    if len(macd_values) < 10:
        return None

    signal = ema(
        macd_values,
        9
    )

    if signal is None:
        return None

    macd_value = macd_values[-1]

    histogram = macd_value - signal

    previous_macd = macd_values[-2]

    previous_signal = ema(
        macd_values[:-1],
        9
    )

    if previous_signal is None:
        previous_histogram = None
    else:
        previous_histogram = (
            previous_macd - previous_signal
        )

    return {
        "macd": macd_value,
        "signal": signal,
        "histogram": histogram,
        "previous_histogram": previous_histogram
    }


# ============================================================
# EMA INDICATEURS
# ============================================================

def calculate_emas(candles):

    closes = [
        candle["close"]
        for candle in candles
    ]

    return {
        "ema7": ema(closes, 7),
        "ema14": ema(closes, 14)
    }


# ============================================================
# LIQUIDITÉ TOUCHÉE
# ============================================================

def detect_liquidity_touch(candle):

    levels = all_levels()

    if not levels:
        return None

    for level in levels:

        if (
            candle["low"]
            <= level
            <= candle["high"]
        ):

            return level

    return None


# ============================================================
# SWEEP
# ============================================================

def detect_sweep(candle, level, role):

    if role == "SSL":

        return (
            candle["low"] < level
            and candle["close"] > level
        )

    if role == "BSL":

        return (
            candle["high"] > level
            and candle["close"] < level
        )

    return False


# ============================================================
# CASSURE
# ============================================================

def detect_breakout(candles, level, role):

    if len(candles) < 2:
        return False

    c1 = candles[-2]
    c2 = candles[-1]

    if role == "SSL":

        return (
            c1["close"] < level
            and c2["close"] < level
        )

    if role == "BSL":

        return (
            c1["close"] > level
            and c2["close"] > level
        )

    return False


# ============================================================
# REJET
# ============================================================

def detect_rejection(candles, level, role):

    if len(candles) < 2:
        return False

    c1 = candles[-2]
    c2 = candles[-1]

    if role == "SSL":

        return (
            c1["close"] > level
            and c2["close"] > level
            and min(c1["low"], c2["low"]) <= level
        )

    if role == "BSL":

        return (
            c1["close"] < level
            and c2["close"] < level
            and max(c1["high"], c2["high"]) >= level
        )

    return False


# ============================================================
# CONSOLIDATION
# ============================================================

def detect_consolidation(candles):

    if len(candles) < 4:
        return False

    recent = candles[-4:]

    highs = [
        c["high"]
        for c in recent
    ]

    lows = [
        c["low"]
        for c in recent
    ]

    highest = max(highs)
    lowest = min(lows)

    range_size = highest - lowest

    if range_size <= 0:
        return False

    # Aucun nouveau high/low extrêmement dominant.
    last = recent[-1]

    previous_high = max(
        c["high"]
        for c in recent[:-1]
    )

    previous_low = min(
        c["low"]
        for c in recent[:-1]
    )

    return (
        last["high"] <= previous_high
        and last["low"] >= previous_low
    )


# ============================================================
# DOUBLE SWEEP
# ============================================================

def detect_double_sweep(candles, level, role):

    if len(candles) < 4:
        return False

    recent = candles[-6:]

    sweeps = []

    for candle in recent:

        if detect_sweep(
            candle,
            level,
            role
        ):

            sweeps.append(candle)

    if len(sweeps) < 2:
        return False

    return True


# ============================================================
# ACCEPTATION / REJET DU PRIX
# ============================================================

def detect_acceptance(candles, level, role):

    if len(candles) < 3:
        return False

    recent = candles[-3:]

    if role == "SSL":

        return all(
            c["close"] < level
            for c in recent
        )

    if role == "BSL":

        return all(
            c["close"] > level
            for c in recent
        )

    return False


def detect_price_rejection(candles, level, role):

    if len(candles) < 3:
        return False

    recent = candles[-3:]

    if role == "SSL":

        return all(
            c["close"] > level
            for c in recent
        )

    if role == "BSL":

        return all(
            c["close"] < level
            for c in recent
        )

    return False


# ============================================================
# STRUCTURE
# ============================================================

def recent_swing_high(candles):

    if len(candles) < 5:
        return None

    c1 = candles[-3]

    if (
        c1["high"] > candles[-4]["high"]
        and
        c1["high"] > candles[-2]["high"]
    ):

        return c1["high"]

    return None


def recent_swing_low(candles):

    if len(candles) < 5:
        return None

    c1 = candles[-3]

    if (
        c1["low"] < candles[-4]["low"]
        and
        c1["low"] < candles[-2]["low"]
    ):

        return c1["low"]

    return None


# ============================================================
# MSS
# ============================================================

def detect_mss(candles):

    if len(candles) < 15:

        return {
            "micro": None,
            "intermediate": None,
            "major": None
        }

    current_close = candles[-1]["close"]

    # ------------------------------
    # Micro
    # ------------------------------

    micro_high = max(
        c["high"]
        for c in candles[-5:-2]
    )

    micro_low = min(
        c["low"]
        for c in candles[-5:-2]
    )

    micro_bull = current_close > micro_high
    micro_bear = current_close < micro_low

    # ------------------------------
    # Intermediate
    # ------------------------------

    intermediate_high = max(
        c["high"]
        for c in candles[-12:-5]
    )

    intermediate_low = min(
        c["low"]
        for c in candles[-12:-5]
    )

    intermediate_bull = (
        current_close > intermediate_high
    )

    intermediate_bear = (
        current_close < intermediate_low
    )

    # ------------------------------
    # Major
    # ------------------------------

    major_high = max(
        c["high"]
        for c in candles[:-3]
    )

    major_low = min(
        c["low"]
        for c in candles[:-3]
    )

    major_bull = current_close > major_high
    major_bear = current_close < major_low

    return {

        "micro": {
            "bullish": micro_bull,
            "bearish": micro_bear,
            "level_bull": micro_high,
            "level_bear": micro_low
        },

        "intermediate": {
            "bullish": intermediate_bull,
            "bearish": intermediate_bear,
            "level_bull": intermediate_high,
            "level_bear": intermediate_low
        },

        "major": {
            "bullish": major_bull,
            "bearish": major_bear,
            "level_bull": major_high,
            "level_bear": major_low
        }
    }


# ============================================================
# DISPLACEMENT
# ============================================================

def detect_displacement(candles):

    if len(candles) < 7:
        return None

    current = candles[-1]

    bodies = []

    for c in candles[-6:-1]:

        bodies.append(
            abs(c["close"] - c["open"])
        )

    average_body = (
        sum(bodies) / len(bodies)
    )

    current_body = abs(
        current["close"] - current["open"]
    )

    if average_body <= 0:
        return None

    body_ok = (
        current_body > average_body
    )

    candle_range = (
        current["high"] - current["low"]
    )

    if candle_range <= 0:
        return None

    close_position = (
        current["close"] - current["low"]
    ) / candle_range

    bullish = (
        current["close"]
        > current["open"]
        and
        close_position >= 0.75
    )

    bearish = (
        current["close"]
        < current["open"]
        and
        close_position <= 0.25
    )

    previous_high = max(
        c["high"]
        for c in candles[-6:-1]
    )

    previous_low = min(
        c["low"]
        for c in candles[-6:-1]
    )

    bullish_structure_break = (
        current["close"] > previous_high
    )

    bearish_structure_break = (
        current["close"] < previous_low
    )

    bullish_confirmed = (
        body_ok
        and bullish
        and bullish_structure_break
    )

    bearish_confirmed = (
        body_ok
        and bearish
        and bearish_structure_break
    )

    if bullish_confirmed:

        return {
            "direction": "BUY",
            "confirmed": True,
            "average_body": average_body,
            "body": current_body,
            "close_position": close_position
        }

    if bearish_confirmed:

        return {
            "direction": "SELL",
            "confirmed": True,
            "average_body": average_body,
            "body": current_body,
            "close_position": close_position
        }

    return {
        "direction": "NONE",
        "confirmed": False,
        "average_body": average_body,
        "body": current_body,
        "close_position": close_position
    }


# ============================================================
# DOMINANCE
# ============================================================

def determine_dominance(candles):

    macd = calculate_macd(candles)

    if macd is None:
        return "NEUTRE", macd

    histogram = macd["histogram"]

    if histogram > 0:
        return "ACHETEURS DOMINANTS", macd

    if histogram < 0:
        return "VENDEURS DOMINANTS", macd

    return "NEUTRE", macd


# ============================================================
# PULLBACK
# ============================================================

def detect_pullback(
    candles,
    displacement_direction
):

    if len(candles) < 5:
        return {
            "confirmed": False,
            "voie": None
        }

    emas = calculate_emas(candles)

    ema7 = emas["ema7"]
    ema14 = emas["ema14"]

    if ema7 is None or ema14 is None:
        return {
            "confirmed": False,
            "voie": None
        }

    recent = candles[-4:]

    if displacement_direction == "BUY":

        # Voie B : stabilisation près des EMA
        near_ema = any(
            c["low"] <= max(ema7, ema14)
            and
            c["high"] >= min(ema7, ema14)
            for c in recent
        )

        bullish_close = (
            recent[-1]["close"]
            > recent[-1]["open"]
        )

        if near_ema and bullish_close:

            return {
                "confirmed": True,
                "voie": "B"
            }

    if displacement_direction == "SELL":

        near_ema = any(
            c["high"] >= min(ema7, ema14)
            and
            c["low"] <= max(ema7, ema14)
            for c in recent
        )

        bearish_close = (
            recent[-1]["close"]
            < recent[-1]["open"]
        )

        if near_ema and bearish_close:

            return {
                "confirmed": True,
                "voie": "B"
            }

    return {
        "confirmed": False,
        "voie": None
    }


# ============================================================
# SCÉNARIO 7BIS
# ============================================================

def detect_7bis(
    candles,
    displacement,
    mss
):

    if not displacement["confirmed"]:
        return False

    direction = displacement["direction"]

    mss_ok = False

    if direction == "BUY":

        mss_ok = (
            mss["intermediate"]["bullish"]
            or
            mss["major"]["bullish"]
        )

    elif direction == "SELL":

        mss_ok = (
            mss["intermediate"]["bearish"]
            or
            mss["major"]["bearish"]
        )

    if not mss_ok:
        return False

    if len(candles) < 5:
        return False

    # Recherche d'un mouvement continu
    # sans véritable repli.

    recent = candles[-4:]

    if direction == "BUY":

        continuous = all(
            recent[i]["close"]
            >= recent[i - 1]["close"]
            for i in range(1, len(recent))
        )

    else:

        continuous = all(
            recent[i]["close"]
            <= recent[i - 1]["close"]
            for i in range(1, len(recent))
        )

    if not continuous:
        return False

    macd = calculate_macd(candles)

    if macd is None:
        return False

    if direction == "BUY":

        momentum_ok = (
            macd["histogram"] > 0
        )

    else:

        momentum_ok = (
            macd["histogram"] < 0
        )

    return momentum_ok


# ============================================================
# RAPPORT PROTOCOLE
# ============================================================

def build_protocol_report(
    candles,
    level,
    role
):

    recent = candles[-1]

    # ------------------------------
    # Étape 3
    # ------------------------------

    sweep = detect_sweep(
        recent,
        level,
        role
    )

    breakout = detect_breakout(
        candles,
        level,
        role
    )

    rejection = detect_rejection(
        candles,
        level,
        role
    )

    consolidation = detect_consolidation(
        candles
    )

    double_sweep = detect_double_sweep(
        candles,
        level,
        role
    )

    acceptance = detect_acceptance(
        candles,
        level,
        role
    )

    price_rejection = detect_price_rejection(
        candles,
        level,
        role
    )

    # ------------------------------
    # Étape 4
    # ------------------------------

    dominance, macd = determine_dominance(
        candles
    )

    # ------------------------------
    # Étape 5
    # ------------------------------

    mss = detect_mss(candles)

    # ------------------------------
    # Étape 6
    # ------------------------------

    displacement = detect_displacement(
        candles
    )

    # ------------------------------
    # Étape 7
    # ------------------------------

    pullback = {
        "confirmed": False,
        "voie": None
    }

    if displacement["confirmed"]:

        pullback = detect_pullback(
            candles,
            displacement["direction"]
        )

    # ------------------------------
    # Étape 7bis
    # ------------------------------

    extension = detect_7bis(
        candles,
        displacement,
        mss
    )

    # ------------------------------
    # Verdict
    # ------------------------------

    verdict = "OBSERVATION EN COURS"

    if displacement["confirmed"]:

        direction = displacement["direction"]

        mss_confirmed = False

        if direction == "BUY":

            mss_confirmed = (
                mss["intermediate"]["bullish"]
                or
                mss["major"]["bullish"]
            )

        elif direction == "SELL":

            mss_confirmed = (
                mss["intermediate"]["bearish"]
                or
                mss["major"]["bearish"]
            )

        if mss_confirmed:

            if pullback["confirmed"]:

                verdict = (
                    f"SETUP A+ — "
                    f"{direction} — "
                    f"VOIE {pullback['voie']}"
                )

            elif extension:

                verdict = (
                    f"SETUP A+ — {direction} — "
                    "ÉTAPE 7BIS — "
                    "RR RÉDUIT / RISQUE ACCRU"
                )

    # ------------------------------
    # Rapport
    # ------------------------------

    lines = [

        "========================================",
        "BTC SMC — RAPPORT PROTOCOLE",
        "========================================",

        f"Liquidité : {level:.2f}",
        f"Type : {role}",
        f"Prix actuel : {recent['close']:.2f}",

        "",
        "ÉTAPE 3 — RÉACTION",

        f"3.1 Sweep : {'OUI' if sweep else 'NON'}",
        f"3.2 Cassure : {'OUI' if breakout else 'NON'}",
        f"3.3 Rejet : {'OUI' if rejection else 'NON'}",
        f"3.4 Consolidation : {'OUI' if consolidation else 'NON'}",
        f"3.5 Double sweep : {'OUI' if double_sweep else 'NON'}",
        f"3.6 Acceptation : {'OUI' if acceptance else 'NON'}",
        f"3.7 Rejet du prix : {'OUI' if price_rejection else 'NON'}",

        "",
        "ÉTAPE 4 — DOMINANCE",

        f"Dominance : {dominance}",

        "",
        "ÉTAPE 5 — MSS",

        f"Micro : {mss['micro']}",
        f"Intermédiaire : {mss['intermediate']}",
        f"Major : {mss['major']}",

        "",
        "ÉTAPE 6 — DISPLACEMENT",

        f"Direction : {displacement['direction']}",
        f"Confirmé : {displacement['confirmed']}",

        "",
        "ÉTAPE 7 — PULLBACK",

        f"Confirmé : {pullback['confirmed']}",
        f"Voie : {pullback['voie']}",

        "",
        "ÉTAPE 7BIS",

        f"Extension autorisée : {extension}",

        "",
        "MACD",

    ]

    if macd:

        lines.extend([

            f"MACD : {macd['macd']:.5f}",
            f"Signal : {macd['signal']:.5f}",
            f"Histogramme : {macd['histogram']:.5f}"

        ])

    else:

        lines.append(
            "MACD : INDISPONIBLE"
        )

    lines.extend([

        "",
        "========================================",
        f"VERDICT : {verdict}",
        "========================================",

    ])

    return "\n".join(lines)


# ============================================================
# GESTION DE L'OBSERVATION
# ============================================================

def start_observation(candle, level):

    global observation

    role = get_level_role(level)

    observation = {

        "level": level,

        "role": role,

        "touch_time": candle["open_time"],

        "candles_after": 0,

        "completed": False

    }

    message = (

        "🚨 LIQUIDITÉ BTC TOUCHÉE\n\n"

        f"Type : {role}\n"
        f"Niveau : {level:.2f}\n"

        f"High : {candle['high']:.2f}\n"
        f"Low : {candle['low']:.2f}\n"
        f"Close : {candle['close']:.2f}\n\n"

        "⚠️ ZONE D'INTÉRÊT\n"
        "PAS D'ENTRÉE.\n\n"

        "Observation obligatoire activée.\n"
        "Attente : clôture de la bougie de contact "
        "+ 1 bougie M15."

    )

    print(
        message,
        flush=True
    )

    telegram_send(message)


def process_observation(candles):

    global observation

    if observation is None:
        return

    level = observation["level"]

    role = observation["role"]

    touch_time = observation["touch_time"]

    after = [

        c for c in candles

        if c["open_time"] > touch_time
    ]

    observation["candles_after"] = len(after)

    # Minimum :
    # bougie de contact clôturée
    # + une bougie suivante clôturée.

    if len(after) < 1:

        print(
            "[PROTOCOLE] Observation obligatoire en cours.",
            flush=True
        )

        return

    # Analyse uniquement après
    # satisfaction de l'attente.

    report = build_protocol_report(
        candles,
        level,
        role
    )

    print(
        report,
        flush=True
    )

    telegram_send(report)

    # On termine cette observation.
    observation["completed"] = True

    observation = None


# ============================================================
# TRAITEMENT BOUGIE
# ============================================================

def process_candle(candles):

    global observation

    candle = candles[-1]

    # --------------------------------------------------------
    # Si une observation est déjà active
    # --------------------------------------------------------

    if observation is not None:

        process_observation(candles)

        return

    # --------------------------------------------------------
    # Sinon recherche d'une nouvelle liquidité
    # --------------------------------------------------------

    touched_level = detect_liquidity_touch(
        candle
    )

    if touched_level is None:
        return

    start_observation(
        candle,
        touched_level
    )


# ============================================================
# AFFICHAGE BOUGIE
# ============================================================

def print_candle(candle):

    print(

        "\n"
        "----------------------------------------\n"
        "BTCUSDT M15\n"
        f"Ouverture : {candle_time(candle)}\n"
        f"Open       : {candle['open']:.2f}\n"
        f"High       : {candle['high']:.2f}\n"
        f"Low        : {candle['low']:.2f}\n"
        f"Close      : {candle['close']:.2f}\n"
        f"Volume     : {candle['volume']:.4f}\n"
        "----------------------------------------",

        flush=True
    )


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
        "BTC SMC BOT V2 - PROTOCOLE",
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

    print(
        "[LIQUIDITÉ]",
        flush=True
    )

    for level in levels["BSL"]:

        print(
            f"  BSL : {level:.2f}",
            flush=True
        )

    for level in levels["SSL"]:

        print(
            f"  SSL : {level:.2f}",
            flush=True
        )

    if not all_levels():

        print(
            "[WARNING] Aucun niveau configuré.",
            flush=True
        )

    print(
        "Connexion aux données Binance...",
        flush=True
    )

    # --------------------------------------------------------
    # TEST INITIAL
    # --------------------------------------------------------

    candles = get_candles()

    if candles is None:

        print(
            "[ERREUR] Impossible de récupérer les données.",
            flush=True
        )

    else:

        print(
            f"[OK] {len(candles)} bougies M15 reçues.",
            flush=True
        )

        print_candle(candles[-2])

    # --------------------------------------------------------
    # BOUCLE
    # --------------------------------------------------------

    while bot_running:

        try:

            candles = get_candles()

            if candles is None:

                time.sleep(POLL_SECONDS)

                continue

            # dernière = bougie en formation
            # avant-dernière = dernière clôturée

            closed_candle = candles[-2]

            candle_time_value = (
                closed_candle["open_time"]
            )

            if (
                candle_time_value
                != last_candle_time
            ):

                last_candle_time = (
                    candle_time_value
                )

                print(
                    f"\n[{utc_now()}] "
                    "NOUVELLE BOUGIE M15 CLÔTURÉE",
                    flush=True
                )

                print_candle(
                    closed_candle
                )

                # On transmet uniquement
                # les bougies clôturées.
                closed_candles = candles[:-1]

                process_candle(
                    closed_candles
                )

            time.sleep(
                POLL_SECONDS
            )

        except Exception as e:

            print(
                f"[ERREUR LOOP] "
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
        "BOT BTC SMC V2 - DEMARRAGE",
        flush=True
    )

    print(
        "==================================================",
        flush=True
    )

    web_thread = threading.Thread(
        target=start_web_server,
        daemon=True
    )

    web_thread.start()

    trading_loop()


if __name__ == "__main__":

    main()
