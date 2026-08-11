import time
from datetime import datetime, timezone

print("=" * 50, flush=True)
print("BOT BTC SMC - DEMARRAGE", flush=True)
print("=" * 50, flush=True)


def heartbeat():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{now}] BOT ACTIF - connexion en fonctionnement", flush=True)


print("Initialisation terminée.", flush=True)

while True:
    heartbeat()
    time.sleep(60)
