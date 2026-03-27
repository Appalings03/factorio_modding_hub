# core/sync_manager.py

import json
from pathlib import Path
from db.repository import Repository
from scrapers.raw_data_scraper import RawDataScraper
from scrapers.api_docs_scraper import ApiDocsParser
from scrapers.github_scraper import GitHubScraper

class SyncManager:
    """
    Orchestre l'import des 3 sources dans la DB.
    Ordre d'import recommandé :
      1. prototype-api.json  → peuple prototype_types (le schéma)
      2. data.raw JSON       → peuple prototypes (les instances)
      3. GitHub Lua          → optionnel MVP, utile pour versioning
    """

    def __init__(self, repo: Repository, cache_dir: Path, config: dict):
        self.repo      = repo
        self.cache_dir = cache_dir
        self.config    = config

    def sync_api_docs(self, version_tag: str = "latest") -> None:
        """Étape 1 : importe le schéma des types depuis prototype-api.json"""
        parser   = ApiDocsParser(self.cache_dir / "api_docs")
        api_data = parser.get_prototype_api()
        actual_version = parser.get_api_version(api_data)

        version_id = self.repo.upsert_version(actual_version, source="api_docs")

        # Import des types de prototypes
        types = parser.extract_prototype_types(api_data)
        for t in types:
            self.repo.upsert_prototype_type(version_id, t)

        # Résolution de l'héritage (parent_name → parent_id)
        self.repo.resolve_type_inheritance(version_id)

        # Import des propriétés de schéma par type
        for t in types:
            type_id = self.repo.get_type_id(t["name"], version_id)
            if type_id and t["properties"]:
                self.repo.upsert_type_properties(type_id, t["properties"])

        print(f"[sync] API docs importées : {len(types)} types")

    def sync_raw_data(self) -> None:
        """Étape 2 : importe les instances depuis le gist data.raw"""
        scraper  = RawDataScraper(self.cache_dir / "raw_data")
        data     = scraper.fetch()

        # Version issue du meta fichier
        meta_file = self.cache_dir / "raw_data" / "data_raw_meta.json"
        meta      = json.loads(meta_file.read_text()) if meta_file.exists() else {}
        version_tag = meta.get("game_version", "2.0.65-space-age")

        version_id = self.repo.upsert_version(version_tag, source="raw_data")

        count = 0
        for typename, proto_name, proto_dict in scraper.iter_prototypes(data):
            self.repo.upsert_prototype(version_id, typename, proto_name, proto_dict)
            count += 1
            if count % 500 == 0:
                print(f"[sync] {count} prototypes importés...")

        # Extraction des propriétés plates pour FTS et diff
        import traceback
        try:
            self.repo.rebuild_properties_flat(version_id)
        except Exception as e:
            traceback.print_exc()
            raise
        # Extraction des relations (ingredients, results, etc.)
        self.repo.extract_relations(version_id)

        print(f"[sync] data.raw importé : {count} prototypes")

    def sync_github(self, version_tag: str, token: str = None) -> None:
        """Étape 3 : télécharge les Lua pour une version spécifique"""
        scraper = GitHubScraper(self.cache_dir, token=token)
        scraper.sync_version(version_tag)
        # Le parsing Lua est différé (phase 2 ou option avancée)
        print(f"[sync] GitHub {version_tag} mis en cache")

