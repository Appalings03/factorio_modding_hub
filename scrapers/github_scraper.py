# scrapers/github_scraper.py

import requests
import base64
import json
import time
from pathlib import Path

GITHUB_API = "https://api.github.com"
REPO       = "wube/factorio-data"

# Fichiers Lua qui nous intéressent dans le repo
PROTOTYPE_PATHS = [
    "base/prototypes/",
    "core/prototypes/",
    "space-age/prototypes/",   # DLC Space Age
]

class GitHubScraper:
    """
    Récupère les fichiers Lua de prototypes depuis le repo officiel Wube.
    Usage principal : comparaison inter-versions et audit des changements.

    Note : sans token GitHub = 60 req/h. Avec token = 5000 req/h.
    Le repo a ~200 fichiers Lua de prototypes → token fortement recommandé.
    """

    def __init__(self, cache_dir: Path, token: str = None):
        self.cache_dir = cache_dir
        self.session   = requests.Session()
        if token:
            self.session.headers["Authorization"] = f"token {token}"
        self.session.headers["Accept"] = "application/vnd.github.v3+json"

    def _get(self, url: str) -> dict | list:
        """GET avec retry simple sur rate limit."""
        for attempt in range(3):
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 403:
                reset = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
                wait  = max(reset - time.time(), 0) + 5
                print(f"[github] Rate limit — attente {wait:.0f}s")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"GitHub API inaccessible après 3 tentatives : {url}")

    def list_versions(self, limit: int = 20) -> list[str]:
        """
        Retourne les N derniers tags (= versions de Factorio).
        Ex: ["2.0.65", "2.0.60", ..., "1.1.107"]
        """
        tags = self._get(f"{GITHUB_API}/repos/{REPO}/tags?per_page={limit}")
        return [t["name"] for t in tags]

    def get_latest_version(self) -> str:
        return self.list_versions(limit=1)[0]

    def get_tree(self, version_tag: str) -> list[dict]:
        """Arbre récursif du repo pour un tag donné."""
        data = self._get(
            f"{GITHUB_API}/repos/{REPO}/git/trees/{version_tag}?recursive=1"
        )
        return data.get("tree", [])

    def get_lua_prototype_files(self, version_tag: str) -> list[str]:
        """
        Filtre l'arbre pour ne garder que les .lua des dossiers prototypes.
        """
        tree = self.get_tree(version_tag)
        return [
            item["path"] for item in tree
            if item["type"] == "blob"
            and item["path"].endswith(".lua")
            and any(item["path"].startswith(p) for p in PROTOTYPE_PATHS)
        ]

    def download_file(self, path: str, version_tag: str) -> str:
        """Retourne le contenu texte d'un fichier Lua."""
        data = self._get(
            f"{GITHUB_API}/repos/{REPO}/contents/{path}?ref={version_tag}"
        )
        return base64.b64decode(data["content"]).decode("utf-8")

    def sync_version(self, version_tag: str) -> Path:
        """
        Télécharge tous les fichiers Lua de prototype pour un tag donné.
        Stocke dans : cache/github/<version_tag>/<path>.lua
        Retourne le chemin du dossier version.
        Idempotent : skippe les fichiers déjà téléchargés.
        """
        version_dir = self.cache_dir / "github" / version_tag
        meta_file   = version_dir / ".sync_complete"

        if meta_file.exists():
            print(f"[github] Version {version_tag} déjà synchronisée")
            return version_dir

        lua_files = self.get_lua_prototype_files(version_tag)
        print(f"[github] {len(lua_files)} fichiers Lua trouvés pour {version_tag}")

        for i, file_path in enumerate(lua_files, 1):
            dest = version_dir / file_path
            if dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            content = self.download_file(file_path, version_tag)
            dest.write_text(content, encoding="utf-8")

            if i % 10 == 0:
                print(f"[github]   {i}/{len(lua_files)} fichiers téléchargés...")
            time.sleep(0.1)  # Politesse envers l'API

        meta_file.write_text(json.dumps({
            "version":     version_tag,
            "file_count":  len(lua_files),
            "sync_date":   __import__("datetime").datetime.utcnow().isoformat(),
        }))
        print(f"[github] Sync complète : {version_tag}")
        return version_dir