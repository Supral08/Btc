import time
from datetime import datetime, timezone

print("===================================")
print("SMC TRADING BOT — V1.0")
print("Bot démarré avec succès")
print("===================================")

while True:
    now = datetime.now(timezone.utc)
    print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')} UTC] Bot actif...")
    time.sleep(60)
