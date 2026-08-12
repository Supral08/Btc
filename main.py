import os
import time
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import requests

# ===================== CONFIG =====================
BINANCE_URL = "https://data-api.binance.vision/api/v3/klines"
SYMBOL = "BTCUSDT"
INTERVAL = "15m"
POLL_SECONDS = 15
OBSERVATION_CANDLES = int(os.getenv("OBSERVATION_CANDLES", "8"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
LIQUIDITY_LEVELS = os.getenv("LIQUIDITY_LEVELS", "").strip()
STATE_FILE = "smc_state.json"

bot_running = True
last_candle_time = None
telegram_offset = 0
active_observations = {}
completed_observations = []
dynamic_zones = []

def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def ctime(ts):
    return datetime.fromtimestamp(ts/1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

# ===================== STATE =====================
def save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "liquidity_levels": LIQUIDITY_LEVELS,
                "active_observations": active_observations,
                "completed_observations": completed_observations[-20:],
                "dynamic_zones": dynamic_zones[-100:]
            }, f, indent=2)
    except Exception as e:
        print(f"[STATE] Erreur: {type(e).__name__} - {e}", flush=True)

def load_state():
    global active_observations, completed_observations, dynamic_zones, LIQUIDITY_LEVELS
    if not os.path.exists(STATE_FILE):
        print("[STATE] Aucun état précédent.", flush=True)
        return
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        active_observations = d.get("active_observations", {})
        completed_observations = d.get("completed_observations", [])
        dynamic_zones = d.get("dynamic_zones", [])
        saved = d.get("liquidity_levels", "")
        if saved:
            LIQUIDITY_LEVELS = str(saved)
        print("[STATE] Mémoire restaurée.", flush=True)
    except Exception as e:
        print(f"[STATE] Restauration impossible: {type(e).__name__} - {e}", flush=True)

# ===================== RENDER =====================
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            body = b'{"status":"online","bot":"BTC SMC V3.2"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        else:
            body = b"BTC SMC BOT V3.2 - ONLINE\n"
            self.send_response(200 if self.path == "/" else 404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        return

def web_server():
    port = int(os.getenv("PORT", "10000"))
    print(f"[{now()}] Serveur Render sur port {port}", flush=True)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()

# ===================== LEVELS =====================
def parse_levels():
    out = []
    for x in LIQUIDITY_LEVELS.split(","):
        try:
            if x.strip():
                out.append(float(x.strip()))
        except ValueError:
            print(f"[LIQUIDITE] Niveau invalide: {x}", flush=True)
    return out

# ===================== TELEGRAM =====================
def tg(method, params=None, timeout=30):
    if not TELEGRAM_TOKEN:
        print("[TELEGRAM] TOKEN absent.", flush=True)
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        d = r.json()
        if not d.get("ok"):
            print(f"[TELEGRAM API] {method}: {d}", flush=True)
        return d
    except Exception as e:
        print(f"[TELEGRAM API] {method}: {type(e).__name__} - {e}", flush=True)
        return None

def send(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TELEGRAM SEND] TOKEN ou CHAT_ID absent.", flush=True)
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=15
        )
        r.raise_for_status()
        print("[TELEGRAM SEND] OK", flush=True)
        return True
    except Exception as e:
        print(f"[TELEGRAM SEND] Erreur: {type(e).__name__} - {e}", flush=True)
        return False

def prepare_telegram():
    print("[TELEGRAM] Vérification getMe...", flush=True)
    me = tg("getMe", timeout=15)
    if not me or not me.get("ok"):
        print("[TELEGRAM] ECHEC getMe: vérifie le token.", flush=True)
        return False
    b = me["result"]
    print(f"[TELEGRAM] Bot: @{b.get('username')} ID={b.get('id')}", flush=True)

    wh = tg("getWebhookInfo", timeout=15)
    if wh and wh.get("ok") and wh["result"].get("url"):
        print(f"[TELEGRAM] Webhook détecté: {wh['result']['url']}", flush=True)
        tg("deleteWebhook", {"drop_pending_updates": False}, timeout=15)
        print("[TELEGRAM] Webhook supprimé.", flush=True)
    else:
        print("[TELEGRAM] Aucun webhook actif.", flush=True)

    global telegram_offset
    old = tg("getUpdates", {"offset": -1, "timeout": 1}, timeout=10)
    if old and old.get("ok") and old["result"]:
        telegram_offset = old["result"][-1]["update_id"] + 1
        print(f"[TELEGRAM] Anciens updates ignorés. Offset={telegram_offset}", flush=True)
    return True

def command(text):
    global LIQUIDITY_LEVELS
    p = text.strip().split()
    if not p:
        return
    cmd = p[0].lower().split("@")[0]
    print(f"[TELEGRAM] Commande: {cmd}", flush=True)

    if cmd == "/start":
        lv = parse_levels()
        s = "\n".join(f"• {x:.2f}" for x in lv) if lv else "Aucun niveau configuré."
        send(
            "🤖 BTC SMC BOT V3.2\n\n"
            "✅ Bot opérationnel.\n"
            f"📊 {SYMBOL} — {INTERVAL}\n"
            f"🔎 Observation: {OBSERVATION_CANDLES} bougies M15\n\n"
            f"📍 Niveaux surveillés:\n{s}\n\n"
            "Commandes:\n"
            "/levels 63700 63580\n/levels\n/status\n/zones\n/reset\n/clear"
        )
        return

    if cmd == "/levels":
        if len(p) == 1:
            lv = parse_levels()
            send("📊 NIVEAUX\n\n" + ("\n".join(f"• {x:.2f}" for x in lv) if lv else "Aucun niveau configuré."))
            return
        vals = []
        for x in p[1:]:
            try:
                v = float(x)
                if v > 0:
                    vals.append(v)
            except ValueError:
                pass
        if not vals:
            send("❌ Aucun niveau valide. Exemple: /levels 63700 63580")
            return
        LIQUIDITY_LEVELS = ",".join(str(x) for x in vals)
        save_state()
        send("✅ NIVEAUX MIS À JOUR\n\n" + "\n".join(f"• {x:.2f}" for x in vals) +
             "\n\n👁️ Surveillance active.\n⚠️ Aucun BUY/SELL automatique.")
        print(f"[LIQUIDITE] Niveaux: {LIQUIDITY_LEVELS}", flush=True)
        return

    if cmd == "/status":
        lv = parse_levels()
        send(
            "📡 BTC SMC BOT V3.2\n\n"
            "État: ACTIF\n"
            f"Symbole: {SYMBOL}\nTimeframe: {INTERVAL}\n"
            f"Observation: {OBSERVATION_CANDLES} bougies\n\n"
            f"Niveaux: {', '.join(f'{x:.2f}' for x in lv) if lv else 'Aucun'}\n"
            f"Observations actives: {len(active_observations)}\n"
            f"Rapports terminés: {len(completed_observations)}\n"
            f"Zones dynamiques: {len(dynamic_zones)}"
        )
        return

    if cmd == "/zones":
        if not dynamic_zones:
            send("📭 Aucune nouvelle zone détectée.")
            return
        send("🧭 NOUVELLES ZONES\n\n" + "\n".join(
            f"• {z['type']}: {z['price']:.2f} | source {z['source_level']:.2f} | {z['time']}"
            for z in dynamic_zones[-10:]
        ))
        return

    if cmd == "/reset":
        active_observations.clear()
        completed_observations.clear()
        save_state()
        send("♻️ MÉMOIRE RÉINITIALISÉE.\nLes niveaux restent actifs.")
        return

    if cmd == "/clear":
        active_observations.clear()
        completed_observations.clear()
        dynamic_zones.clear()
        save_state()
        send("🗑️ Mémoire, observations et zones supprimées.\nLes niveaux restent actifs.")
        return

    send("❓ Commande inconnue. Utilise /start.")

def telegram_loop():
    global telegram_offset
    print("[TELEGRAM] Listener démarré.", flush=True)
    if not TELEGRAM_TOKEN:
        print("[TELEGRAM] ❌ TELEGRAM_BOT_TOKEN absent.", flush=True)
        return
    if not prepare_telegram():
        return
    print("[TELEGRAM] ✅ Polling getUpdates actif.", flush=True)

    while bot_running:
        try:
            d = tg("getUpdates", {
                "offset": telegram_offset,
                "timeout": 25,
                "allowed_updates": json.dumps(["message"])
            }, timeout=35)

            if not d or not d.get("ok"):
                print("[TELEGRAM] getUpdates non-OK; nouvelle tentative.", flush=True)
                if d and d.get("error_code") == 409:
                    print("[TELEGRAM] ⚠️ 409 CONFLICT: un autre processus utilise ce bot.", flush=True)
                time.sleep(5)
                continue

            for u in d.get("result", []):
                telegram_offset = u["update_id"] + 1
                print(f"[TELEGRAM] UPDATE RECU: {u['update_id']}", flush=True)

                m = u.get("message")
                if not m:
                    continue

                chat_id = str(m.get("chat", {}).get("id", ""))
                text = m.get("text", "")

                print(f"[TELEGRAM] Chat ID reçu: {chat_id}", flush=True)
                print(f"[TELEGRAM] Texte reçu: {text!r}", flush=True)

                if TELEGRAM_CHAT_ID and chat_id != TELEGRAM_CHAT_ID:
                    print(f"[TELEGRAM] ⚠️ CHAT ID NON AUTORISE. Attendu={TELEGRAM_CHAT_ID}", flush=True)
                    continue

                if text.startswith("/"):
                    command(text)
                else:
                    print("[TELEGRAM] Message non-commande ignoré.", flush=True)

        except Exception as e:
            print(f"[TELEGRAM LOOP] {type(e).__name__} - {e}", flush=True)
            time.sleep(5)

# ===================== BINANCE =====================
def candles(limit=60):
    try:
        r = requests.get(
            BINANCE_URL,
            params={"symbol": SYMBOL, "interval": INTERVAL, "limit": limit},
            timeout=15,
            headers={"User-Agent": "BTC-SMC-Bot/3.2"}
        )
        r.raise_for_status()
        return [{
            "open_time": int(x[0]), "open": float(x[1]), "high": float(x[2]),
            "low": float(x[3]), "close": float(x[4]), "volume": float(x[5]),
            "close_time": int(x[6])
        } for x in r.json()]
    except Exception as e:
        print(f"[BINANCE] {type(e).__name__} - {e}", flush=True)
        return None

def print_candle(c):
    print(
        "\n----------------------------------------\nBTCUSDT M15\n"
        f"Ouverture: {ctime(c['open_time'])}\n"
        f"Open: {c['open']:.2f}\nHigh: {c['high']:.2f}\n"
        f"Low: {c['low']:.2f}\nClose: {c['close']:.2f}\n"
        f"Volume: {c['volume']:.4f}\n----------------------------------------",
        flush=True
    )

# ===================== STRUCTURE =====================
def rejection(c, level):
    body = abs(c["close"] - c["open"])
    rng = c["high"] - c["low"]
    if rng <= 0:
        return False
    upper = c["high"] - max(c["open"], c["close"])
    lower = min(c["open"], c["close"]) - c["low"]
    return (
        (c["low"] <= level and c["close"] > level and lower > body) or
        (c["high"] >= level and c["close"] < level and upper > body)
    )

def displacement(cs, i):
    if i < 3:
        return False
    r = cs[i]["high"] - cs[i]["low"]
    if r <= 0:
        return False
    prev = [x["high"] - x["low"] for x in cs[max(0, i-5):i]]
    avg = sum(prev) / len(prev) if prev else 0
    if avg <= 0 or r < avg * 1.5:
        return False
    return ((cs[i]["close"]-cs[i]["low"])/r >= .70 or
            (cs[i]["high"]-cs[i]["close"])/r >= .70)

def swing_high(cs, i):
    return 0 < i < len(cs)-1 and cs[i]["high"] > cs[i-1]["high"] and cs[i]["high"] >= cs[i+1]["high"]

def swing_low(cs, i):
    return 0 < i < len(cs)-1 and cs[i]["low"] < cs[i-1]["low"] and cs[i]["low"] <= cs[i+1]["low"]

def mss(cs):
    if len(cs) < 4:
        return False
    last = cs[-1]
    return last["close"] > max(x["high"] for x in cs[:-1]) or last["close"] < min(x["low"] for x in cs[:-1])

def add_zone(obs, typ, price):
    for z in dynamic_zones:
        if z["type"] == typ and abs(z["price"] - price) < 1:
            return
    z = {"type": typ, "price": price, "source_level": obs["level"], "time": now()}
    dynamic_zones.append(z)
    obs["new_zones"].append(z)
    print(f"[NOUVELLE ZONE] {typ}: {price:.2f}", flush=True)

def process_obs(obs, c):
    obs["candles"].append(c)
    cs = obs["candles"]
    i = len(cs) - 1
    if rejection(c, obs["level"]):
        obs["rejection"] = obs["reaction"] = True
    if displacement(cs, i):
        obs["displacement"] = obs["reaction"] = True
    if mss(cs):
        obs["mss"] = obs["reaction"] = True
    if len(cs) >= 3:
        j = len(cs) - 2
        if swing_high(cs, j):
            add_zone(obs, "SWING_HIGH", cs[j]["high"])
        if swing_low(cs, j):
            add_zone(obs, "SWING_LOW", cs[j]["low"])

def report(obs):
    s = [
        "📊 RAPPORT BTC SMC — OBSERVATION TERMINÉE",
        "",
        f"Liquidité: {obs['level']:.2f}",
        f"Contact: {ctime(obs['contact_candle']['open_time'])}",
        f"Bougies observées: {len(obs['candles'])}",
        "",
        "1️⃣ RÉACTION",
        f"Rejet: {'OUI' if obs['rejection'] else 'NON'}",
        f"Displacement: {'OUI' if obs['displacement'] else 'NON'}",
        f"MSS potentiel: {'OUI' if obs['mss'] else 'NON'}",
        "",
        "2️⃣ ÉTAT",
        "🟡 RÉACTION STRUCTURELLE DÉTECTÉE" if obs["reaction"] else "⚪ AUCUNE RÉACTION EXPLOITABLE",
        "",
        "3️⃣ BOUGIES M15"
    ]
    for i, c in enumerate(obs["candles"], 1):
        s.append(f"C{i} | O {c['open']:.2f} | H {c['high']:.2f} | L {c['low']:.2f} | C {c['close']:.2f}")
    s += ["", "4️⃣ NOUVELLES ZONES / STRUCTURES"]
    if obs["new_zones"]:
        s += [f"• {z['type']}: {z['price']:.2f}" for z in obs["new_zones"]]
    else:
        s.append("Aucune nouvelle zone détectée.")
    s += ["", "5️⃣ RÈGLE", "Rapport descriptif.", "Aucun BUY/SELL automatique.", "Analyse sceptique externe nécessaire."]
    return "\n".join(s)

def touch(c):
    return [x for x in parse_levels() if c["low"] <= x <= c["high"]]

def create_obs(level, c):
    key = str(level)
    if key in active_observations:
        return
    o = {
        "level": level, "contact_candle": c, "candles": [],
        "created_at": now(), "status": "OBSERVATION",
        "reaction": False, "mss": False, "displacement": False,
        "rejection": False, "new_zones": []
    }
    active_observations[key] = o
    save_state()
    print(f"[CONTACT LIQUIDITE] {level:.2f} -> observation {OBSERVATION_CANDLES} M15", flush=True)
    send(
        "🚨 CONTACT LIQUIDITÉ BTC\n\n"
        f"Niveau: {level:.2f}\n"
        f"Bougie contact: {ctime(c['open_time'])}\n\n"
        f"📋 Mémoire activée: {OBSERVATION_CANDLES} prochaines bougies M15.\n"
        "⚠️ Aucun BUY/SELL."
    )

def update_obs(c):
    done = []
    for key, o in list(active_observations.items()):
        if c["open_time"] <= o["contact_candle"]["open_time"]:
            continue
        if any(x["open_time"] == c["open_time"] for x in o["candles"]):
            continue
        process_obs(o, c)
        n = len(o["candles"])
        print(f"[OBSERVATION] {o['level']:.2f} -> {n}/{OBSERVATION_CANDLES}", flush=True)
        if n >= OBSERVATION_CANDLES:
            done.append(key)
    for key in done:
        o = active_observations[key]
        o["status"] = "TERMINEE"
        r = report(o)
        print("\n" + r + "\n", flush=True)
        send(r)
        completed_observations.append(o)
        del active_observations[key]
        save_state()

def trading():
    global last_candle_time
    print("==================================================", flush=True)
    print("BTC SMC BOT V3.2 - PROTOCOLE", flush=True)
    print(f"Source: Binance | {SYMBOL} | {INTERVAL}", flush=True)
    print(f"Observation: {OBSERVATION_CANDLES} bougies M15", flush=True)
    print("==================================================", flush=True)

    lv = parse_levels()
    if lv:
        print("[LIQUIDITE] " + ", ".join(f"{x:.2f}" for x in lv), flush=True)
    else:
        print("[WARNING] Aucun niveau configuré.", flush=True)
        print("[INFO] Telegram: /levels 63700 63580", flush=True)

    first = candles(60)
    if first:
        print(f"[OK] {len(first)} bougies M15 reçues.", flush=True)
        print_candle(first[-2])

    while bot_running:
        try:
            cs = candles(60)
            if not cs:
                time.sleep(POLL_SECONDS)
                continue
            c = cs[-2]
            if c["open_time"] != last_candle_time:
                last_candle_time = c["open_time"]
                print(f"[{now()}] NOUVELLE BOUGIE M15 CLÔTURÉE", flush=True)
                print_candle(c)
                update_obs(c)
                for level in touch(c):
                    create_obs(level, c)
                save_state()
            time.sleep(POLL_SECONDS)
        except Exception as e:
            print(f"[LOOP] {type(e).__name__} - {e}", flush=True)
            time.sleep(POLL_SECONDS)

def main():
    print("==================================================", flush=True)
    print("BOT BTC SMC V3.2 - DEMARRAGE", flush=True)
    print("==================================================", flush=True)
    load_state()

    threading.Thread(target=web_server, daemon=True).start()
    threading.Thread(target=telegram_loop, daemon=True).start()

    trading()

if __name__ == "__main__":
    main()
