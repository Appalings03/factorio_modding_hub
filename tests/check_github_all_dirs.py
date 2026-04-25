"""
check_github_all_dirs.py
Affiche tous les dossiers disponibles dans le repo GitHub (sans filtre).
"""
from pathlib import Path

cache = Path("data/cache/github")
versions = [d for d in cache.iterdir() if d.is_dir()]

for version_dir in sorted(versions):
    print(f"\n=== {version_dir.name} ===")
    top_dirs = sorted([d for d in version_dir.iterdir() if d.is_dir()])
    for top in top_dirs:
        lua_count = len(list(top.rglob("*.lua")))
        print(f"  {top.name}/  ({lua_count} .lua)")
    print(f"  → Total : {len(list(version_dir.rglob('*.lua')))} fichiers Lua")