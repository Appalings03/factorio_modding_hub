# core/sync_manager.py

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from db.repository import Repository
from scrapers.raw_data_scraper import RawDataScraper
from scrapers.api_docs_scraper import ApiDocsParser
from scrapers.github_scraper import GitHubScraper
from parsers.lua_json_parser import parse_lua_file
from parsers.prototype_parser import PrototypeParser

logger = logging.getLogger("factorio_hub.sync")

LOGS_DIR = Path(__file__).parent.parent / "data" / "logs"


def _write_skip_log(version_tag: str, skipped: list[dict]) -> Path:
    """
    Écrit les prototypes skippés dans un fichier log horodaté.
    Format : data/logs/github_skip_<version>_<timestamp>.log
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts       = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"github_skip_{version_tag}_{ts}.log"

    with log_path.open("w", encoding="utf-8") as f:
        f.write(f"GitHub sync skip log — version: {version_tag}\n")
        f.write(f"Date : {datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"Total skippés : {len(skipped)}\n")
        f.write("=" * 60 + "\n\n")
        for entry in skipped:
            f.write(
                f"[SKIP] {entry['typename']}/{entry['name']}\n"
                f"       fichier : {entry['lua_file']}\n"
                f"       raison  : {entry['reason']}\n\n"
            )

    return log_path


class SyncManager:
    """
    Orchestre l'import des 3 sources dans la DB.
    Ordre d'import recommandé :
      1. prototype-api.json  → peuple prototype_types (le schéma)
      2. data.raw JSON       → peuple prototypes (les instances)
      3. GitHub Lua          → prototypes depuis les sources Lua officielles
    """

    def __init__(self, repo: Repository, cache_dir: Path, config: dict):
        self.repo      = repo
        self.cache_dir = cache_dir
        self.config    = config

    # ------------------------------------------------------------------ #
    # Étape 1 : API docs                                                   #
    # ------------------------------------------------------------------ #

    def sync_api_docs(self, version_tag: str = "latest") -> None:
        """Importe le schéma des types depuis prototype-api.json"""
        parser   = ApiDocsParser(self.cache_dir / "api_docs")
        api_data = parser.get_prototype_api()
        actual_version = parser.get_api_version(api_data)

        version_id = self.repo.upsert_version(actual_version, source="api_docs")

        types = parser.extract_prototype_types(api_data)
        for t in types:
            self.repo.upsert_prototype_type(version_id, t)

        self.repo.resolve_type_inheritance(version_id)

        for t in types:
            type_id = self.repo.get_type_id(t["name"], version_id)
            if type_id and t["properties"]:
                self.repo.upsert_type_properties(type_id, t["properties"])

        print(f"[sync] API docs importées : {len(types)} types (version: {actual_version})")

    # ------------------------------------------------------------------ #
    # Étape 2 : data.raw                                                   #
    # ------------------------------------------------------------------ #

    def sync_raw_data(self, version_tag: str | None = None) -> None:
        """
        Importe les instances depuis le gist data.raw.
        version_tag : si fourni, utilise ce tag au lieu de celui du meta fichier.
        """
        scraper = RawDataScraper(self.cache_dir / "raw_data")
        data    = scraper.fetch()

        if version_tag:
            actual_version = version_tag
            print(f"[sync] Version raw_data forcée : {actual_version}")
        else:
            meta_file = self.cache_dir / "raw_data" / "data_raw_meta.json"
            meta      = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
            actual_version = meta.get("game_version", "2.0.65-space-age")
            print(f"[sync] Version raw_data depuis meta : {actual_version}")

        version_id = self.repo.upsert_version(actual_version, source="raw_data")

        count = 0
        for typename, proto_name, proto_dict in scraper.iter_prototypes(data):
            self.repo.upsert_prototype(version_id, typename, proto_name, proto_dict)
            count += 1
            if count % 500 == 0:
                print(f"[sync] {count} prototypes importés...")

        self.repo.rebuild_properties_flat(version_id)
        self.repo.extract_relations(version_id)

        print(f"[sync] data.raw importé : {count} prototypes (version: {actual_version})")

    # ------------------------------------------------------------------ #
    # Étape 3 : GitHub Lua → DB                                           #
    # ------------------------------------------------------------------ #

    def sync_github(self, version_tag: str, token: str = None, force: bool = False) -> None:
        """
        Télécharge les fichiers Lua depuis GitHub, les parse et les importe en DB.

        Stratégie :
        - Version DB séparée : "<version_tag>-github" (ex: "2.0.76-github")
        - Coexiste avec raw_data — les deux versions sont indépendantes
        - Skip uniquement si doublon dans la MÊME version github (idempotence)
        - Les skips sont loggés dans data/logs/github_skip_<version>_<ts>.log
        """
        # 1. Téléchargement dans le cache (idempotent)
        scraper     = GitHubScraper(self.cache_dir, token=token)
        version_dir = scraper.sync_version(version_tag, force=force)

        # 2. Version DB dédiée GitHub
        github_version = f"{version_tag}-github"
        version_id     = self.repo.upsert_version(github_version, source="github")
        print(f"[sync] Import GitHub → DB (version: {github_version})")

        # 3. Parcours des fichiers Lua cachés
        lua_files = list(version_dir.rglob("*.lua"))
        print(f"[sync] {len(lua_files)} fichiers Lua à parser...")

        parser     = PrototypeParser(strict=False)
        count_ok   = 0
        count_err  = 0
        skipped    = []   # liste des dicts {typename, name, lua_file, reason}

        for i, lua_path in enumerate(lua_files, 1):
            try:
                prototypes = parse_lua_file(lua_path)
            except Exception as e:
                logger.warning("Erreur parsing %s : %s", lua_path.name, e)
                count_err += 1
                continue

            for proto in prototypes:
                typename = proto.get("type", "")
                name     = proto.get("name", "")

                if not typename or not name:
                    skipped.append({
                        "typename": typename or "(vide)",
                        "name":     name     or "(vide)",
                        "lua_file": str(lua_path.name),
                        "reason":   "type ou name manquant",
                    })
                    continue

                # Skip si déjà présent dans cette version (idempotence)
                existing = self.repo.get_prototype(typename, name, version_id)
                if existing:
                    skipped.append({
                        "typename": typename,
                        "name":     name,
                        "lua_file": str(lua_path.name),
                        "reason":   "déjà présent dans cette version (doublon)",
                    })
                    continue

                try:
                    self.repo.upsert_prototype(version_id, typename, name, proto)
                    count_ok += 1
                except Exception as e:
                    logger.warning("Erreur import %s/%s : %s", typename, name, e)
                    skipped.append({
                        "typename": typename,
                        "name":     name,
                        "lua_file": str(lua_path.name),
                        "reason":   f"erreur import : {e}",
                    })
                    count_err += 1

            if i % 20 == 0:
                print(f"[sync]   {i}/{len(lua_files)} fichiers traités "
                      f"({count_ok} importés, {len(skipped)} skippés)...")

        # 4. Post-traitement
        if count_ok > 0:
            print(f"[sync] Reconstruction FTS et relations...")
            self.repo.rebuild_properties_flat(version_id)
            self.repo.extract_relations(version_id)

        # 5. Fichier log des skips
        if skipped:
            log_path = _write_skip_log(version_tag, skipped)
            print(f"[sync] {len(skipped)} skips loggés → {log_path}")

        print(
            f"[sync] GitHub {version_tag} importé : "
            f"{count_ok} prototypes, {len(skipped)} skippés, {count_err} erreurs"
        )