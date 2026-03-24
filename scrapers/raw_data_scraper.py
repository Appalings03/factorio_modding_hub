# scrapers/raw_data_scraper.py

import requests
import json
import hashlib
from pathlib import Path
from datetime import datetime

# URL stable référencée par le wiki officiel
WIKI_PAGE_URL  = "https://wiki.factorio.com/Data.raw"
GIST_RAW_URL   = (
    "https://gist.githubusercontent.com/Bilka2/"
    "6b8a6a9e4a4ec779573ad703d03c1ae7/raw"
)

class RawDataScraper:
    """
    Télécharge le dump JSON complet de data.raw (Space Age 2.0.65).
    Structure du JSON :
    {
      "assembling-machine": {
        "assembling-machine-1": { "name": "assembling-machine-1",
                                  "type": "assembling-machine",
                                  "crafting_speed": 0.5,
                                  ... },
        ...
      },
      "item": { "iron-plate": { ... }, ... },
      ...
    }
    Donc : data_raw[prototype_type][prototype_name] = propriétés
    """

    def __init__(self, cache_dir: Path, force_refresh: bool = False):
        self.cache_dir = cache_dir
        self.cache_file = cache_dir / "data_raw.json"
        self.meta_file  = cache_dir / "data_raw_meta.json"
        self.force_refresh = force_refresh

    def _compute_hash(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def fetch(self) -> dict:
        """
        Retourne le dict data.raw complet.
        Utilise le cache local si disponible et non périmé.
        """
        if self.cache_file.exists() and not self.force_refresh:
            print("[raw_data] Cache hit — chargement local")
            return json.loads(self.cache_file.read_text(encoding="utf-8"))

        print(f"[raw_data] Téléchargement depuis le gist ({GIST_RAW_URL})")
        print("[raw_data] Attention : fichier ~20 MB, patience...")

        resp = requests.get(GIST_RAW_URL, timeout=120, stream=True)
        resp.raise_for_status()

        raw_bytes = resp.content
        checksum  = self._compute_hash(raw_bytes)

        # Vérification anti-re-import inutile
        if self.meta_file.exists():
            meta = json.loads(self.meta_file.read_text())
            if meta.get("checksum") == checksum:
                print("[raw_data] Contenu identique au cache — import ignoré")
                return json.loads(self.cache_file.read_text(encoding="utf-8"))

        data = json.loads(raw_bytes.decode("utf-8"))

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_bytes(raw_bytes)
        self.meta_file.write_text(json.dumps({
            "checksum":    checksum,
            "fetch_date":  datetime.utcnow().isoformat(),
            "source_url":  GIST_RAW_URL,
            "type_count":  len(data),
            "proto_count": sum(len(v) for v in data.values()),
        }, indent=2))

        print(f"[raw_data] OK — {len(data)} types, "
              f"{sum(len(v) for v in data.values())} prototypes")
        return data

    def iter_prototypes(self, data: dict):
        """
        Générateur : yield (type_name, proto_name, proto_dict)
        Permet un import incrémental sans tout charger en mémoire.
        """
        for type_name, instances in data.items():
            if not isinstance(instances, dict):
                continue  # skip les clés non-prototype (metadata éventuelle)
            for proto_name, proto_data in instances.items():
                if isinstance(proto_data, dict):
                    yield type_name, proto_name, proto_data