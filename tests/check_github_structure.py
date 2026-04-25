"""
check_github_structure.py
Lance depuis la racine du projet pour voir les dossiers prototypes disponibles.
"""
from pathlib import Path

cache = Path("data/cache/github")
if not cache.exists():
    print("Cache GitHub vide — lancez d'abord sync --source github")
    exit()

# Lister les versions cachées
versions = [d for d in cache.iterdir() if d.is_dir()]
if not versions:
    print("Aucune version cachée.")
    exit()

for version_dir in sorted(versions):
    print(f"\n=== {version_dir.name} ===")

    # Dossiers racine
    top_dirs = sorted([d for d in version_dir.iterdir() if d.is_dir()])
    for top in top_dirs:
        proto_dir = top / "prototypes"
        lua_count = len(list(top.rglob("*.lua")))
        marker = " ← prototypes/" if proto_dir.exists() else ""
        print(f"  {top.name}/  ({lua_count} .lua){marker}")

    # Total
    total_lua = len(list(version_dir.rglob("*.lua")))
    print(f"  → Total : {total_lua} fichiers Lua")