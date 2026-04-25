import sqlite3
from pathlib import Path

db_path = Path("data/factorio_hub.db")
con = sqlite3.connect(db_path)

# Affiche l'état actuel
rows = con.execute("SELECT id, version_tag, is_latest FROM versions").fetchall()
print("Versions actuelles:")
for r in rows:
    print(f"  id={r[0]} tag={r[1]} is_latest={r[2]}")

# Marque 2.0.65-space-age comme latest (celle qui a les prototypes)
con.execute("UPDATE versions SET is_latest = 0")
con.execute("UPDATE versions SET is_latest = 1 WHERE version_tag = '2.0.65-space-age'")
con.commit()

print("\nFix appliqué — 2.0.65-space-age marquée comme latest.")
con.close()