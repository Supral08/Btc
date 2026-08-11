import os
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


# ============================================================
# SERVEUR HTTP — nécessaire pour Render Web Service
# ============================================================

PORT = int(os.environ.get("PORT", 10000))


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
    print(f"[SYSTEM] Serveur HTTP actif sur le port {PORT}")
    server.serve_forever()


# ============================================================
# BOT SMC
# ============================================================

def trading_bot():

    print("===================================")
    print("SMC TRADING BOT — V1.0")
    print("===================================")
    print("Bot démarré avec succès")
    print("Mode : SEMI-AUTOMATIQUE")
    print("Aucun ordre automatique")
    print("===================================")

    while True:

        try:
            # ------------------------------------------------
            # POUR L'INSTANT : TEST DU BOT
            # ------------------------------------------------

            current_time = time.strftime(
                "%Y-%m-%d %H:%M:%S UTC",
                time.gmtime()
            )

            print(f"[{current_time}] Bot actif...")

            # ------------------------------------------------
            # Prochaine étape :
            # connexion Bybit
            # détection des liquidités
            # surveillance M15
            # analyse IA
            # IA sceptique
            # juge final
            # Telegram
            # ------------------------------------------------

            time.sleep(60)

        except Exception as e:

            print(f"[ERROR] {e}")

            time.sleep(10)


# ============================================================
# DÉMARRAGE
# ============================================================

if __name__ == "__main__":

    # Le serveur HTTP tourne dans un thread séparé.
    server_thread = threading.Thread(
        target=start_server,
        daemon=True
    )

    server_thread.start()

    # Le bot principal continue de fonctionner.
    trading_bot()
