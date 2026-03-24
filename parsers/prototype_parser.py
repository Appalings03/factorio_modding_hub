"""
parsers/prototype_parser.py
============================
Normalise les prototypes bruts (depuis data.raw JSON ou Lua parsé)
vers le format attendu par repository.upsert_prototype().

Responsabilités :
- Valider la présence des champs obligatoires (name, type)
- Extraire les champs dénormalisés (localised_name, order, subgroup)
- Convertir les types ambigus (nombres Lua → int/float Python)
- Rejeter les entrées malformées avec un log clair
"""

import json
import logging
from typing import Any, Iterator

logger = logging.getLogger("factorio_hub.parsers.prototype")


# Champs obligatoires pour qu'un prototype soit valide
_REQUIRED_FIELDS = ("name", "type")

# Champs connus à extraire comme colonnes DB (dénormalisés pour les requêtes)
_SCALAR_EXTRACT_KEYS = {
    "order", "subgroup", "stack_size", "crafting_speed",
    "energy_usage", "module_slots", "ingredient_count",
    "mining_speed", "resource_categories",
}


class PrototypeParser:
    """
    Normalise un prototype brut dict Python vers un format DB-ready.

    Usage :
        parser = PrototypeParser()
        for result in parser.parse_many(raw_data_dict):
            repo.upsert_prototype(version_id, **result)
    """

    def __init__(self, strict: bool = False):
        """
        strict=True → lève une exception sur chaque entrée malformée.
        strict=False (défaut) → log et skip.
        """
        self.strict    = strict
        self._accepted = 0
        self._rejected = 0

    @property
    def stats(self) -> dict:
        return {
            "accepted": self._accepted,
            "rejected": self._rejected,
            "total":    self._accepted + self._rejected,
        }

    # ------------------------------------------------------------------ #
    # Point d'entrée principal : data.raw complet                         #
    # ------------------------------------------------------------------ #

    def parse_raw_data(self, raw_data: dict) -> Iterator[dict]:
        """
        Itère sur le dict data.raw complet :
        { typename: { proto_name: proto_dict, ... }, ... }

        Yield des dicts prêts pour repository.upsert_prototype() :
        { typename, name, data }
        """
        for typename, instances in raw_data.items():
            if not isinstance(instances, dict):
                logger.debug("Clé non-dict ignorée : %s", typename)
                continue

            for proto_name, proto_dict in instances.items():
                if not isinstance(proto_dict, dict):
                    continue
                result = self._normalize(typename, proto_name, proto_dict)
                if result is not None:
                    yield result

    # ------------------------------------------------------------------ #
    # Point d'entrée : liste de prototypes (depuis Lua parser)            #
    # ------------------------------------------------------------------ #

    def parse_many(self, prototypes: list[dict]) -> Iterator[dict]:
        """
        Normalise une liste de prototypes (output du Lua parser).
        Chaque entrée doit avoir au minimum {"type": ..., "name": ...}.
        """
        for proto in prototypes:
            if not isinstance(proto, dict):
                continue
            typename = proto.get("type", "")
            name     = proto.get("name", "")
            result   = self._normalize(typename, name, proto)
            if result is not None:
                yield result

    # ------------------------------------------------------------------ #
    # Normalisation d'un prototype unique                                  #
    # ------------------------------------------------------------------ #

    def _normalize(
        self, typename: str, name: str, data: dict
    ) -> dict | None:
        """
        Valide et normalise un prototype.
        Retourne None si le prototype doit être rejeté.
        """
        # Validation des champs obligatoires
        if not typename or not name:
            self._rejected += 1
            msg = f"Prototype sans type ou nom ignoré : type={typename!r} name={name!r}"
            if self.strict:
                raise ValueError(msg)
            logger.debug(msg)
            return None

        # Nettoyage des champs connus
        normalized = dict(data)
        normalized["type"] = typename
        normalized["name"] = name

        # Conversion des types ambigus
        normalized = _coerce_types(normalized)

        self._accepted += 1
        return {
            "typename": typename,
            "name":     name,
            "data":     normalized,
        }

    def reset_stats(self) -> None:
        self._accepted = 0
        self._rejected = 0


# ---------------------------------------------------------------------------
# Helpers de normalisation de types
# ---------------------------------------------------------------------------

def _coerce_types(data: dict) -> dict:
    """
    Convertit récursivement les types ambigus dans un prototype :
    - Strings numériques → int ou float
    - "true"/"false" string → bool (artefact de certains parsers Lua)
    """
    result = {}
    for k, v in data.items():
        result[k] = _coerce_value(v)
    return result


def _coerce_value(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _coerce_value(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_coerce_value(item) for item in v]
    if isinstance(v, str):
        if v == "true":
            return True
        if v == "false":
            return False
        # Tentative de conversion numérique sur les strings pures
        try:
            return int(v)
        except ValueError:
            pass
        try:
            return float(v)
        except ValueError:
            pass
    return v


# ---------------------------------------------------------------------------
# Extraction de champs dénormalisés (pour les colonnes DB)
# ---------------------------------------------------------------------------

def extract_localised_name(data: dict) -> str | None:
    """
    Extrait le nom localisé depuis un prototype.
    Factorio stocke localised_name comme :
      - string simple : "Iron Plate"
      - liste Lua : {"item-name.iron-plate"} → on prend la clé de localisation
      - absent → None
    """
    ln = data.get("localised_name")
    if isinstance(ln, str) and ln:
        return ln
    if isinstance(ln, list) and ln:
        return str(ln[0])
    # Fallback : on utilise le nom interne
    return None


def extract_order_key(data: dict) -> str | None:
    order = data.get("order")
    if isinstance(order, str):
        return order
    return None


def summarize(data: dict, max_keys: int = 10) -> str:
    """
    Retourne un résumé court d'un prototype (pour les logs).
    Affiche les max_keys premiers champs scalaires.
    """
    parts = []
    for k, v in data.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            parts.append(f"{k}={v!r}")
        if len(parts) >= max_keys:
            break
    return "{" + ", ".join(parts) + "}"