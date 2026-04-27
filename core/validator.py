"""
core/validator.py
=================
Validateur de prototypes de mod contre le schéma officiel Factorio.

Pipeline de validation :
1. Récupérer le type officiel depuis prototype_types
2. Remonter l'arbre d'héritage pour collecter toutes les propriétés attendues
3. Pour chaque propriété requise : vérifier qu'elle est présente
4. Pour chaque propriété présente : vérifier le type attendu
5. Vérifier les références croisées (ingredients, results, subgroup...)
6. Retourner la liste des erreurs/warnings/infos
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from db.repository import Repository

logger = logging.getLogger("factorio_hub.validator")


# ------------------------------------------------------------------ #
# Structures de données                                                #
# ------------------------------------------------------------------ #

@dataclass
class ValidationIssue:
    severity:      str          # "error" | "warning" | "info"
    property_path: str          # "ingredients[0].name"
    message:       str
    expected:      str  = ""    # type ou valeur attendue
    actual:        Any  = None  # valeur trouvée
    inherited_from: str = ""    # si propriété héritée

    def to_dict(self) -> dict:
        return {
            "severity":       self.severity,
            "property_path":  self.property_path,
            "message":        self.message,
            "expected":       self.expected,
            "actual":         str(self.actual) if self.actual is not None else "",
            "inherited_from": self.inherited_from,
        }


@dataclass
class ValidationResult:
    typename:   str
    name:       str
    issues:     list[ValidationIssue] = field(default_factory=list)
    schema_found: bool = True

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def infos(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "info"]

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    @property
    def status(self) -> str:
        if not self.schema_found:
            return "unknown"
        if self.errors:
            return "error"
        if self.warnings:
            return "warning"
        return "ok"

    def to_dict(self) -> dict:
        return {
            "typename":     self.typename,
            "name":         self.name,
            "status":       self.status,
            "schema_found": self.schema_found,
            "error_count":   len(self.errors),
            "warning_count": len(self.warnings),
            "info_count":    len(self.infos),
            "issues":        [i.to_dict() for i in self.issues],
        }


# ------------------------------------------------------------------ #
# Validateur principal                                                 #
# ------------------------------------------------------------------ #

class PrototypeValidator:
    """
    Valide les prototypes d'un mod contre le schéma officiel.

    Usage :
        validator = PrototypeValidator(repo, game_version="2.0.76")
        results   = validator.validate_mod(mod_id)
        # ou pour un seul prototype :
        result    = validator.validate_one(typename, name, raw_dict)
    """

    def __init__(self, repo: Repository, game_version: str):
        self.repo         = repo
        self.game_version = game_version
        self._version_id  = self._resolve_version_id(game_version)
        self._schema_cache: dict[str, list[dict]] = {}   # typename → properties
        self._vanilla_cache: dict[str, set[str]]  = {}   # typename → set of names

    # ------------------------------------------------------------------ #
    # API publique                                                         #
    # ------------------------------------------------------------------ #

    def validate_mod(self, mod_id: int) -> list[ValidationResult]:
        """Valide tous les prototypes d'un mod."""
        prototypes = self.repo.get_mod_prototypes(mod_id, limit=9999)
        results    = []

        for proto_meta in prototypes:
            typename = proto_meta["typename"]
            name     = proto_meta["name"]

            # Récupère le raw_json complet
            version_tag = self._get_mod_version_tag(mod_id)
            vid         = self.repo.get_version_id(version_tag) if version_tag else None
            proto       = self.repo.get_prototype(typename, name, vid)
            if not proto:
                continue

            raw    = proto["raw_json"]
            result = self.validate_one(typename, name, raw)
            results.append(result)

        logger.info(
            "Validation mod %d : %d prototypes, %d erreurs, %d warnings",
            mod_id,
            len(results),
            sum(len(r.errors)   for r in results),
            sum(len(r.warnings) for r in results),
        )
        return results

    def validate_one(
        self, typename: str, name: str, raw: dict
    ) -> ValidationResult:
        """Valide un seul prototype."""
        result = ValidationResult(typename=typename, name=name)

        if not self._version_id:
            result.schema_found = False
            result.issues.append(ValidationIssue(
                severity="warning",
                property_path="",
                message=f"Version Factorio '{self.game_version}' introuvable en DB — validation partielle",
            ))
            return result

        # Récupère le schéma du type
        schema_props = self._get_schema(typename)
        if schema_props is None:
            result.schema_found = False
            result.issues.append(ValidationIssue(
                severity="info",
                property_path="type",
                message=f"Type '{typename}' non trouvé dans le schéma officiel",
            ))
            return result

        # Validation des propriétés
        self._check_required(raw, schema_props, result)
        self._check_types(raw, schema_props, result)
        self._check_references(raw, typename, result)

        return result

    # ------------------------------------------------------------------ #
    # Vérifications                                                        #
    # ------------------------------------------------------------------ #

    def _check_required(
        self, raw: dict, schema_props: list[dict], result: ValidationResult
    ) -> None:
        """Vérifie que toutes les propriétés requises sont présentes."""
        for prop in schema_props:
            prop_name   = prop.get("name", "")
            is_optional = prop.get("is_optional", 1)
            inherited   = prop.get("is_inherited", 0)

            if is_optional:
                continue
            if prop_name in ("type", "name"):
                continue  # toujours présents

            if prop_name not in raw:
                result.issues.append(ValidationIssue(
                    severity      = "error",
                    property_path = prop_name,
                    message       = f"Propriété requise manquante : '{prop_name}'",
                    expected      = prop.get("type_str", "?"),
                    inherited_from= prop.get("inherited_from", "") if inherited else "",
                ))

    def _check_types(
        self, raw: dict, schema_props: list[dict], result: ValidationResult
    ) -> None:
        """Vérifie les types des propriétés présentes."""
        schema_index = {p["name"]: p for p in schema_props}

        for key, value in raw.items():
            if key.startswith("_"):
                continue  # clés internes (ex: _merged_from_vanilla)

            schema = schema_index.get(key)
            if not schema:
                continue  # propriété inconnue → info seulement si trop de bruit

            type_str = schema.get("type_str", "")
            if not type_str or type_str == "unknown":
                continue

            issue = self._type_mismatch(key, value, type_str)
            if issue:
                result.issues.append(issue)

    def _check_references(
        self, raw: dict, typename: str, result: ValidationResult
    ) -> None:
        """Vérifie que les références vers d'autres prototypes sont valides."""
        if not self._version_id:
            return

        # Ingrédients de recette
        for i, ing in enumerate(raw.get("ingredients", []) or []):
            if not isinstance(ing, dict):
                continue
            ref_name = ing.get("name")
            if ref_name and not self._proto_exists("item", ref_name):
                result.issues.append(ValidationIssue(
                    severity      = "warning",
                    property_path = f"ingredients[{i}].name",
                    message       = f"Ingrédient '{ref_name}' introuvable dans la DB vanilla",
                    expected      = "item existant",
                    actual        = ref_name,
                ))

        # Résultats de recette
        for i, res in enumerate(raw.get("results", []) or []):
            if not isinstance(res, dict):
                continue
            ref_name = res.get("name")
            if ref_name and not self._proto_exists("item", ref_name):
                result.issues.append(ValidationIssue(
                    severity      = "warning",
                    property_path = f"results[{i}].name",
                    message       = f"Résultat '{ref_name}' introuvable dans la DB vanilla",
                    expected      = "item existant",
                    actual        = ref_name,
                ))

        # Subgroup
        sg = raw.get("subgroup")
        if sg and not self._proto_exists("item-subgroup", sg):
            result.issues.append(ValidationIssue(
                severity      = "warning",
                property_path = "subgroup",
                message       = f"Subgroup '{sg}' introuvable",
                expected      = "item-subgroup existant",
                actual        = sg,
            ))

    # ------------------------------------------------------------------ #
    # Vérification de type                                                 #
    # ------------------------------------------------------------------ #

    def _type_mismatch(
        self, key: str, value: Any, type_str: str
    ) -> ValidationIssue | None:
        """
        Vérifie si la valeur correspond au type attendu.
        Retourne un ValidationIssue si mismatch, None sinon.
        """
        # Types de base
        checks = {
            "bool":   lambda v: isinstance(v, bool),
            "string": lambda v: isinstance(v, str),
            "float":  lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "double": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "uint":   lambda v: isinstance(v, int) and v >= 0,
            "int":    lambda v: isinstance(v, int),
            "uint8":  lambda v: isinstance(v, int) and 0 <= v <= 255,
            "uint16": lambda v: isinstance(v, int) and 0 <= v <= 65535,
            "uint32": lambda v: isinstance(v, int) and 0 <= v <= 4294967295,
        }

        # Normalise le type_str
        base_type = type_str.split("|")[0].strip().lower()
        # Retire les suffixes courants
        for suffix in ["id", "definition", "prototype"]:
            if base_type.endswith(suffix) and base_type != suffix:
                base_type = "string"
                break

        checker = checks.get(base_type)
        if checker and value is not None:
            if not checker(value):
                return ValidationIssue(
                    severity      = "warning",
                    property_path = key,
                    message       = f"Type inattendu pour '{key}'",
                    expected      = type_str,
                    actual        = f"{type(value).__name__}({value!r})",
                )
        return None

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _resolve_version_id(self, game_version: str) -> int | None:
        vid = self.repo.get_version_id(game_version)
        if vid:
            return vid
        # Fallback : cherche une version qui commence par game_version
        for v in self.repo.get_all_versions():
            if v["version_tag"].startswith(game_version):
                return v["id"]
        return None

    def _get_schema(self, typename: str) -> list[dict] | None:
        """Retourne les propriétés de schéma pour un typename, avec cache."""
        if typename in self._schema_cache:
            return self._schema_cache[typename]

        if not self._version_id:
            return None

        type_info = self.repo.get_type_by_typename(typename, self._version_id)
        if not type_info:
            self._schema_cache[typename] = None
            return None

        # Propriétés directes + héritées
        props = self.repo.get_type_properties(type_info["id"], include_inherited=True)

        # Enrichir avec inherited_from depuis les ancêtres
        ancestors = self.repo.get_type_ancestors(type_info["id"])
        ancestor_props = {}
        for anc in ancestors:
            for p in self.repo.get_type_properties(anc["id"], include_inherited=False):
                ancestor_props[p["name"]] = anc["name"]

        for prop in props:
            if prop.get("is_inherited") and prop["name"] in ancestor_props:
                prop["inherited_from"] = ancestor_props[prop["name"]]

        self._schema_cache[typename] = props
        return props

    def _proto_exists(self, typename: str, name: str) -> bool:
        """Vérifie qu'un prototype existe en DB vanilla."""
        if not self._version_id:
            return True  # pas de DB vanilla → on ne bloque pas

        cache_key = typename
        if cache_key not in self._vanilla_cache:
            with self.repo._conn() as con:
                rows = con.execute(
                    "SELECT name FROM prototypes WHERE typename = ? AND version_id = ?",
                    (typename, self._version_id),
                ).fetchall()
            self._vanilla_cache[cache_key] = {r["name"] for r in rows}

        return name in self._vanilla_cache[cache_key]

    def _get_mod_version_tag(self, mod_id: int) -> str | None:
        mod = self.repo.get_mod(mod_id)
        if not mod:
            return None
        return f"mod:{mod['name']}:{mod['mod_version']}"


# ------------------------------------------------------------------ #
# Helper : résumé global                                               #
# ------------------------------------------------------------------ #

def summarize_results(results: list[ValidationResult]) -> dict:
    """Résumé global d'une validation de mod."""
    total     = len(results)
    ok        = sum(1 for r in results if r.status == "ok")
    warnings  = sum(1 for r in results if r.status == "warning")
    errors    = sum(1 for r in results if r.status == "error")
    unknowns  = sum(1 for r in results if r.status == "unknown")

    return {
        "total":    total,
        "ok":       ok,
        "warnings": warnings,
        "errors":   errors,
        "unknown":  unknowns,
        "valid_pct": round(ok / total * 100) if total else 0,
    }