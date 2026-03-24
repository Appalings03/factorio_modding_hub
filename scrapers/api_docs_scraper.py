# scrapers/api_docs_scraper.py

import requests
import json
from pathlib import Path
from datetime import datetime

# JSON officiel machine-readable — documenté par Wube
# https://lua-api.factorio.com/latest/auxiliary/json-docs-prototype.html
PROTOTYPE_API_URL = "https://lua-api.factorio.com/latest/prototype-api.json"
RUNTIME_API_URL   = "https://lua-api.factorio.com/latest/runtime-api.json"

class ApiDocsParser:
    """
    Consomme le JSON officiel prototype-api.json.

    Structure top-level :
    {
      "application": "factorio",
      "application_version": "2.0.65",
      "api_version": 6,
      "stage": "prototype",
      "prototypes": [ ... ],   ← liste des types de prototypes
      "types": [ ... ]         ← liste des types de données réutilisables
    }

    Chaque prototype a :
    {
      "name": "RecipePrototype",
      "order": 42,
      "description": "...",
      "lists": [...],
      "examples": [...],
      "parent": "PrototypeBase",     ← héritage direct
      "abstract": false,
      "typename": "recipe",          ← clé dans data.raw
      "instance_limit": null,
      "deprecated": false,
      "properties": [
        {
          "name": "category",
          "order": 3,
          "description": "...",
          "optional": true,
          "default": {"type":"literal","value":"crafting"},
          "type": "RecipeCategoryID",
          "override": false
        },
        ...
      ]
    }
    """

    def __init__(self, cache_dir: Path, force_refresh: bool = False):
        self.cache_dir     = cache_dir
        self.cache_proto   = cache_dir / "prototype-api.json"
        self.cache_runtime = cache_dir / "runtime-api.json"
        self.force_refresh = force_refresh

    def _fetch_json(self, url: str, cache_path: Path) -> dict:
        if cache_path.exists() and not self.force_refresh:
            return json.loads(cache_path.read_text(encoding="utf-8"))

        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        print(f"[api_docs] Téléchargé : {url}")
        return data

    def get_prototype_api(self) -> dict:
        return self._fetch_json(PROTOTYPE_API_URL, self.cache_proto)

    def get_runtime_api(self) -> dict:
        return self._fetch_json(RUNTIME_API_URL, self.cache_runtime)

    # ------------------------------------------------------------------
    # Extraction structurée
    # ------------------------------------------------------------------

    def extract_prototype_types(self, api_data: dict) -> list[dict]:
        """
        Retourne une liste de dicts normalisés pour l'import en DB.
        Chaque dict = une ligne dans prototype_types.
        """
        result = []
        for proto in api_data.get("prototypes", []):
            result.append({
                "name":        proto["name"],          # "RecipePrototype"
                "typename":    proto.get("typename"),  # "recipe" (clé data.raw)
                "parent":      proto.get("parent"),    # "PrototypeBase"
                "abstract":    proto.get("abstract", False),
                "description": proto.get("description", ""),
                "deprecated":  proto.get("deprecated", False),
                "properties":  proto.get("properties", []),
                # on garde le JSON brut des propriétés pour la DB
            })
        return result

    def extract_custom_types(self, api_data: dict) -> list[dict]:
        """
        Les types réutilisables (EnergySource, IconData, etc.)
        Utiles pour la phase 2 (validation de types).
        """
        result = []
        for t in api_data.get("types", []):
            result.append({
                "name":        t["name"],
                "parent":      t.get("parent"),
                "description": t.get("description", ""),
                "properties":  t.get("properties", []),
            })
        return result

    def build_inheritance_map(self, api_data: dict) -> dict[str, str | None]:
        """
        Retourne {type_name: parent_name | None}
        Ex: {"RecipePrototype": "PrototypeBase", "PrototypeBase": None}
        Utilisé par inheritance_resolver.py
        """
        return {
            p["name"]: p.get("parent")
            for p in api_data.get("prototypes", [])
        }

    def get_api_version(self, api_data: dict) -> str:
        return api_data.get("application_version", "unknown")