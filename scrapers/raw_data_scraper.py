# scrapers/raw_data_scraper.py

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import requests

# Limite de récursion pour le parser Lua (20 MB de Lua imbriqué)
sys.setrecursionlimit(10000)

GIST_RAW_URL = (
    "https://gist.githubusercontent.com/Bilka2/"
    "6b8a6a9e4a4ec779573ad703d03c1ae7/raw"
)


class RawDataScraper:

    def __init__(self, cache_dir: Path, force_refresh: bool = False):
        self.cache_dir     = Path(cache_dir)
        self.cache_file    = self.cache_dir / "data_raw.json"   # cache JSON converti
        self.cache_lua     = self.cache_dir / "data_raw.lua"    # cache Lua brut
        self.meta_file     = self.cache_dir / "data_raw_meta.json"
        self.force_refresh = force_refresh

    def _compute_hash(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def fetch(self) -> dict:
        """
        Retourne le dict data.raw complet.
        - Si le cache JSON existe → le relit directement (rapide)
        - Sinon → télécharge le Lua, le parse, sauvegarde en JSON
        """
        # Cache JSON déjà converti → lecture directe
        if self.cache_file.exists() and not self.force_refresh:
            content = self.cache_file.read_text(encoding="utf-8")
            if content.strip():
                print("[raw_data] Cache hit — chargement local")
                return json.loads(content)
            self.cache_file.unlink()

        # Téléchargement
        print(f"[raw_data] Téléchargement ({GIST_RAW_URL})")
        print("[raw_data] Attention : fichier ~20 MB, patience...")

        resp = requests.get(GIST_RAW_URL, timeout=120)
        resp.raise_for_status()
        raw_bytes = resp.content
        checksum  = self._compute_hash(raw_bytes)

        # Anti re-import si contenu identique
        if self.meta_file.exists() and self.cache_file.exists():
            meta = json.loads(self.meta_file.read_text(encoding="utf-8"))
            if meta.get("checksum") == checksum:
                print("[raw_data] Contenu identique — import ignoré")
                return json.loads(self.cache_file.read_text(encoding="utf-8"))

        # Décodage du contenu
        content = raw_bytes.decode("utf-8")

        # Détection du format
        stripped = content.lstrip()
        if stripped.startswith('{'):
            # JSON pur (format futur possible)
            print("[raw_data] Format détecté : JSON")
            data = json.loads(content)
        else:
            # Format Lua Serpent : "Script @...:1: { ... }"
            print("[raw_data] Format détecté : Lua Serpent — parsing en cours...")
            brace_pos = content.find('{')
            if brace_pos == -1:
                raise ValueError(
                    f"Format inattendu — ni JSON ni Lua trouvé.\n"
                    f"Début reçu : {content[:300]}"
                )
            lua_table = content[brace_pos:]

            # Sauvegarde du Lua brut (debug)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.cache_lua.write_text(lua_table, encoding="utf-8")

            data = self._parse_lua(lua_table)

        # Validation minimale
        if not isinstance(data, dict) or len(data) == 0:
            raise ValueError("Le parsing a produit un dict vide — vérifiez le format source.")

        proto_count = sum(
            len(v) for v in data.values() if isinstance(v, dict)
        )
        print(f"[raw_data] Parsé : {len(data)} types, {proto_count} prototypes")

        # Sauvegarde du cache JSON converti
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.meta_file.write_text(json.dumps({
            "checksum":    checksum,
            "fetch_date":  datetime.utcnow().isoformat(),
            "source_url":  GIST_RAW_URL,
            "type_count":  len(data),
            "proto_count": proto_count,
        }, indent=2), encoding="utf-8")

        print(f"[raw_data] Cache JSON écrit : {self.cache_file}")
        return data

    def _parse_lua(self, lua_table: str) -> dict:
        """
        Parse la table Lua Serpent en dict Python.
        Utilise lua_json_parser si disponible, sinon lève une erreur claire.
        """
        try:
            from parsers.lua_json_parser import parse_lua_string
        except ImportError as e:
            raise ImportError(
                "parsers/lua_json_parser.py introuvable.\n"
                "Assurez-vous que le fichier existe dans le dossier parsers/."
            ) from e

        print("[raw_data] Parsing Lua... (peut prendre 1-3 minutes pour 20 MB)")
        try:
            data = parse_lua_string(lua_table)
        except SyntaxError as e:
            # Affiche le contexte autour de la position d'erreur
            msg = str(e)
            import re
            match = re.search(r'pos (\d+)', msg)
            if match:
                pos = int(match.group(1))
                ctx_start = max(0, pos - 100)
                ctx_end   = min(len(lua_table), pos + 100)
                print(f"\n[DEBUG] Contexte autour de pos {pos}:")
                print(repr(lua_table[ctx_start:ctx_end]))
            raise

        if not isinstance(data, dict):
            raise ValueError(
                f"Le parser Lua a retourné {type(data).__name__} au lieu de dict.\n"
                f"Début du contenu parsé : {str(data)[:200]}"
            )
        return data

    def iter_prototypes(self, data: dict):
        """
        Générateur : yield (type_name, proto_name, proto_dict)
        """
        for type_name, instances in data.items():
            if not isinstance(instances, dict):
                continue
            for proto_name, proto_data in instances.items():
                if isinstance(proto_data, dict):
                    yield type_name, proto_name, proto_data