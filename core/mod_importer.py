"""
core/mod_importer.py
====================
Import d'un mod Factorio depuis un fichier .zip.

Pipeline :
1. Extraction du zip dans un dossier temporaire
2. Lecture de info.json (nom, version, description, auteur)
3. Parsing des fichiers Lua : data.lua → data-updates.lua → data-final-fixes.lua
4. Fusion optionnelle avec les prototypes vanilla (data:extend sur existants)
5. Stockage en DB (temporaire ou permanent)

Gestion de data:extend :
- Nouveaux prototypes  → insérés directement
- Prototypes existants → fusionnés avec le vanilla, résultat stocké séparément
"""

import json
import logging
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

logger = logging.getLogger("factorio_hub.mod_importer")

# Ordre de chargement Lua Factorio
LUA_LOAD_ORDER = ["data.lua", "data-updates.lua", "data-final-fixes.lua"]


class ModImportError(Exception):
    pass


class ModImporter:
    """
    Importe un mod Factorio depuis un .zip.

    Usage :
        importer = ModImporter(repo, cache_dir)
        result   = importer.import_zip(zip_path, game_version="2.0.76")
        # result = {mod_id, name, version, proto_count, skipped, errors}
    """

    def __init__(self, repo, cache_dir: Path):
        self.repo      = repo
        self.cache_dir = cache_dir

    # ------------------------------------------------------------------ #
    # Point d'entrée principal                                             #
    # ------------------------------------------------------------------ #

    def import_zip(
        self,
        zip_path: Path,
        game_version: str | None = None,
        permanent: bool = False,
    ) -> dict:
        """
        Importe un mod depuis un zip.

        permanent=False → prototypes en DB mais mod marqué temporaire
        permanent=True  → mod marqué permanent (après validation)

        Retourne un dict avec les stats d'import et le mod_id.
        """
        zip_path = Path(zip_path)
        if not zip_path.exists():
            raise ModImportError(f"Fichier introuvable : {zip_path}")
        if not zipfile.is_zipfile(zip_path):
            raise ModImportError(f"Fichier invalide (pas un zip) : {zip_path.name}")

        # Extraction dans un dossier temporaire
        tmp_dir = Path(tempfile.mkdtemp(prefix="fmh_mod_"))
        try:
            result = self._process(zip_path, tmp_dir, game_version, permanent)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        return result

    # ------------------------------------------------------------------ #
    # Pipeline interne                                                     #
    # ------------------------------------------------------------------ #

    def _process(
        self,
        zip_path: Path,
        tmp_dir: Path,
        game_version: str | None,
        permanent: bool,
    ) -> dict:
        # 1. Extraction
        mod_dir = self._extract(zip_path, tmp_dir)

        # 2. Lecture info.json
        info = self._read_info(mod_dir)
        mod_name    = info.get("name", zip_path.stem)
        mod_version = info.get("version", "0.0.1")
        description = info.get("description", "")
        author      = info.get("author", "")
        if not game_version:
            game_version = info.get("factorio_version", "unknown")

        logger.info("Import mod : %s v%s (Factorio %s)", mod_name, mod_version, game_version)

        # 3. Création du mod en DB
        mod_id = self.repo.create_mod(
            name         = mod_name,
            mod_version  = mod_version,
            game_version = game_version,
            file_name    = zip_path.name,
            description  = description,
            author       = author,
        )

        # 4. Version DB dédiée au mod
        version_tag = f"mod:{mod_name}:{mod_version}"
        version_id  = self.repo.upsert_version(version_tag, source="mod")

        # 5. Chargement des prototypes vanilla pour la fusion
        vanilla_protos = self._load_vanilla(game_version)

        # 6. Parsing Lua
        all_protos, parse_errors = self._parse_lua_files(mod_dir)
        logger.info("%d prototypes parsés, %d erreurs de parsing",
                    len(all_protos), len(parse_errors))

        # 7. Fusion vanilla + import DB
        count_new    = 0
        count_merged = 0
        count_skip   = 0
        import_errors = []

        for proto in all_protos:
            typename = proto.get("type", "")
            name     = proto.get("name", "")
            if not typename or not name:
                count_skip += 1
                continue

            # Fusion avec vanilla si le prototype existe déjà
            vanilla = vanilla_protos.get(typename, {}).get(name)
            if vanilla:
                merged = {**vanilla, **proto}  # mod écrase vanilla
                merged["_merged_from_vanilla"] = True
                count_merged += 1
            else:
                merged = proto
                count_new += 1

            try:
                self.repo.upsert_mod_prototype(
                    mod_id, version_id, typename, name, merged
                )
            except Exception as e:
                logger.warning("Erreur import %s/%s : %s", typename, name, e)
                import_errors.append(f"{typename}/{name}: {e}")

        # 8. Post-traitement FTS
        total_imported = count_new + count_merged
        if total_imported > 0:
            self.repo.rebuild_properties_flat(version_id)
            self.repo.extract_relations(version_id)

        logger.info(
            "Import terminé : %d nouveaux, %d fusionnés, %d skippés, %d erreurs",
            count_new, count_merged, count_skip, len(import_errors)
        )

        return {
            "mod_id":       mod_id,
            "name":         mod_name,
            "version":      mod_version,
            "game_version": game_version,
            "version_tag":  version_tag,
            "count_new":    count_new,
            "count_merged": count_merged,
            "count_skip":   count_skip,
            "proto_count":  total_imported,
            "parse_errors": parse_errors,
            "import_errors":import_errors,
        }

    # ------------------------------------------------------------------ #
    # Extraction                                                           #
    # ------------------------------------------------------------------ #

    def _extract(self, zip_path: Path, tmp_dir: Path) -> Path:
        """
        Extrait le zip. Factorio zips contiennent souvent un dossier racine
        du type "mod-name_version/" — on le détecte et retourne ce dossier.
        """
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_dir)

        # Détecter le dossier racine du mod
        contents = list(tmp_dir.iterdir())
        if len(contents) == 1 and contents[0].is_dir():
            mod_dir = contents[0]
        else:
            mod_dir = tmp_dir

        logger.debug("Dossier mod extrait : %s", mod_dir)
        return mod_dir

    # ------------------------------------------------------------------ #
    # info.json                                                            #
    # ------------------------------------------------------------------ #

    def _read_info(self, mod_dir: Path) -> dict:
        info_path = mod_dir / "info.json"
        if not info_path.exists():
            logger.warning("info.json introuvable dans %s", mod_dir)
            return {}
        try:
            return json.loads(info_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Erreur lecture info.json : %s", e)
            return {}

    # ------------------------------------------------------------------ #
    # Parsing Lua                                                          #
    # ------------------------------------------------------------------ #

    def _parse_lua_files(self, mod_dir: Path) -> tuple[list[dict], list[str]]:
        """
        Parse les fichiers Lua dans l'ordre Factorio.
        Retourne (prototypes, erreurs).
        """
        from parsers.lua_json_parser import parse_lua_file

        all_protos = []
        errors     = []

        for lua_name in LUA_LOAD_ORDER:
            lua_path = mod_dir / lua_name
            if not lua_path.exists():
                continue
            logger.debug("Parsing %s...", lua_name)
            try:
                protos = parse_lua_file(lua_path)
                all_protos.extend(protos)
                logger.info("%s → %d prototypes", lua_name, len(protos))
            except Exception as e:
                msg = f"{lua_name}: {e}"
                logger.warning("Erreur parsing %s : %s", lua_name, e)
                errors.append(msg)

        # Scan récursif des autres .lua (certains mods splitent en sous-fichiers)
        # On skippe les fichiers déjà parsés
        already_parsed = set(LUA_LOAD_ORDER)
        for lua_path in sorted(mod_dir.rglob("*.lua")):
            if lua_path.name in already_parsed:
                continue
            # On cherche uniquement les fichiers qui contiennent data:extend
            try:
                content = lua_path.read_text(encoding="utf-8", errors="ignore")
                if "data:extend" not in content:
                    continue
                protos = parse_lua_file(lua_path)
                if protos:
                    all_protos.extend(protos)
                    logger.debug("%s → %d prototypes", lua_path.name, len(protos))
            except Exception as e:
                errors.append(f"{lua_path.name}: {e}")

        return all_protos, errors

    # ------------------------------------------------------------------ #
    # Vanilla loader                                                        #
    # ------------------------------------------------------------------ #

    def _load_vanilla(self, game_version: str) -> dict[str, dict[str, dict]]:
        """
        Charge les prototypes vanilla depuis la DB pour la version donnée.
        Retourne {typename: {name: raw_dict}}.
        """
        vanilla = {}
        version_id = self.repo.get_version_id(game_version)
        if not version_id:
            # Essaye sans suffix (ex: "2.0.76" si "2.0.76-space-age" absent)
            versions = self.repo.get_all_versions()
            for v in versions:
                if v["version_tag"].startswith(game_version):
                    version_id = v["id"]
                    break

        if not version_id:
            logger.warning(
                "Version vanilla '%s' introuvable en DB — pas de fusion",
                game_version
            )
            return {}

        logger.info("Chargement vanilla depuis version_id=%d...", version_id)

        with self.repo._conn() as con:
            rows = con.execute(
                "SELECT typename, name, raw_json FROM prototypes WHERE version_id = ?",
                (version_id,),
            ).fetchall()

        for row in rows:
            tn = row["typename"]
            n  = row["name"]
            if tn not in vanilla:
                vanilla[tn] = {}
            try:
                vanilla[tn][n] = json.loads(row["raw_json"])
            except Exception:
                pass

        logger.info("Vanilla chargé : %d prototypes", sum(len(v) for v in vanilla.values()))
        return vanilla


# ---------------------------------------------------------------------------
# Helper standalone pour l'upload Flask
# ---------------------------------------------------------------------------

def allowed_file(filename: str) -> bool:
    return filename.lower().endswith(".zip")


def save_upload(file_storage, upload_dir: Path) -> Path:
    """Sauvegarde un FileStorage Flask dans upload_dir. Retourne le chemin."""
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = Path(file_storage.filename).name  # sécurité : pas de path traversal
    dest     = upload_dir / filename
    file_storage.save(str(dest))
    return dest