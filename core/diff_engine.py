"""
core/diff_engine.py
====================
Comparaison de prototypes entre deux versions de Factorio.

Produit un diff structuré :
- Propriétés ajoutées (présentes en v2, absentes en v1)
- Propriétés supprimées (présentes en v1, absentes en v2)
- Propriétés modifiées (présentes dans les deux, valeur différente)
- Propriétés inchangées (optionnel, pour affichage complet)
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from db.repository import Repository

logger = logging.getLogger("factorio_hub.diff")


@dataclass
class PropChange:
    key:       str
    change:    str          # "added" | "removed" | "modified" | "unchanged"
    value_a:   Any = None   # valeur en version A (None si added)
    value_b:   Any = None   # valeur en version B (None si removed)


@dataclass
class PrototypeDiff:
    typename:    str
    name:        str
    version_a:   str
    version_b:   str
    exists_in_a: bool = True
    exists_in_b: bool = True
    changes:     list[PropChange] = field(default_factory=list)

    @property
    def added(self) -> list[PropChange]:
        return [c for c in self.changes if c.change == "added"]

    @property
    def removed(self) -> list[PropChange]:
        return [c for c in self.changes if c.change == "removed"]

    @property
    def modified(self) -> list[PropChange]:
        return [c for c in self.changes if c.change == "modified"]

    @property
    def unchanged(self) -> list[PropChange]:
        return [c for c in self.changes if c.change == "unchanged"]

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.modified
                    or not self.exists_in_a or not self.exists_in_b)

    def summary(self) -> str:
        if not self.exists_in_a:
            return f"Nouveau dans {self.version_b}"
        if not self.exists_in_b:
            return f"Supprimé dans {self.version_b}"
        parts = []
        if self.added:
            parts.append(f"+{len(self.added)} propriétés")
        if self.removed:
            parts.append(f"-{len(self.removed)} propriétés")
        if self.modified:
            parts.append(f"~{len(self.modified)} modifiées")
        return ", ".join(parts) if parts else "Aucun changement"


class DiffEngine:
    """
    Compare des prototypes entre deux versions de Factorio.

    Usage :
        engine = DiffEngine(repo)
        diff = engine.diff_prototype("recipe", "iron-plate", "1.1.107", "2.0.65")
        for change in diff.modified:
            print(f"  {change.key}: {change.value_a!r} → {change.value_b!r}")
    """

    def __init__(self, repo: Repository):
        self.repo = repo

    def diff_prototype(
        self,
        typename: str,
        name: str,
        version_a: str,
        version_b: str,
        include_unchanged: bool = False,
    ) -> PrototypeDiff:
        """
        Compare un prototype entre deux versions.
        version_a = ancienne, version_b = nouvelle.
        """
        vid_a = self.repo.get_version_id(version_a)
        vid_b = self.repo.get_version_id(version_b)

        diff = PrototypeDiff(
            typename  = typename,
            name      = name,
            version_a = version_a,
            version_b = version_b,
        )

        raw_a = self.repo.get_prototype_raw(typename, name, vid_a) if vid_a else None
        raw_b = self.repo.get_prototype_raw(typename, name, vid_b) if vid_b else None

        diff.exists_in_a = raw_a is not None
        diff.exists_in_b = raw_b is not None

        if not raw_a and not raw_b:
            return diff

        # Aplatissement des dicts pour comparaison clé par clé
        flat_a = _flatten(raw_a or {})
        flat_b = _flatten(raw_b or {})

        all_keys = sorted(set(flat_a) | set(flat_b))

        for key in all_keys:
            in_a = key in flat_a
            in_b = key in flat_b

            if in_a and not in_b:
                diff.changes.append(PropChange(key, "removed", flat_a[key], None))
            elif in_b and not in_a:
                diff.changes.append(PropChange(key, "added", None, flat_b[key]))
            else:
                va = flat_a[key]
                vb = flat_b[key]
                if _values_equal(va, vb):
                    if include_unchanged:
                        diff.changes.append(PropChange(key, "unchanged", va, vb))
                else:
                    diff.changes.append(PropChange(key, "modified", va, vb))

        return diff

    def diff_type(
        self,
        type_name: str,
        version_a: str,
        version_b: str,
    ) -> list[PrototypeDiff]:
        """
        Compare tous les prototypes d'un typename entre deux versions.
        Retourne uniquement les prototypes qui ont changé.
        """
        vid_a = self.repo.get_version_id(version_a)
        vid_b = self.repo.get_version_id(version_b)

        if not vid_a or not vid_b:
            logger.warning("Version(s) introuvable(s) : %s / %s", version_a, version_b)
            return []

        # Prototypes présents dans chaque version
        protos_a = {
            p["name"]
            for p in self.repo.get_prototypes_by_type(type_name, vid_a, limit=9999)
        }
        protos_b = {
            p["name"]
            for p in self.repo.get_prototypes_by_type(type_name, vid_b, limit=9999)
        }

        all_names = protos_a | protos_b
        diffs = []

        for name in sorted(all_names):
            d = self.diff_prototype(type_name, name, version_a, version_b)
            if d.has_changes:
                diffs.append(d)

        logger.info(
            "Diff %s [%s → %s] : %d/%d prototypes modifiés",
            type_name, version_a, version_b, len(diffs), len(all_names),
        )
        return diffs

    def to_dict(self, diff: PrototypeDiff) -> dict:
        """Sérialise un PrototypeDiff en dict JSON-serializable."""
        return {
            "typename":    diff.typename,
            "name":        diff.name,
            "version_a":   diff.version_a,
            "version_b":   diff.version_b,
            "exists_in_a": diff.exists_in_a,
            "exists_in_b": diff.exists_in_b,
            "summary":     diff.summary(),
            "added":   [{"key": c.key, "value": _ser(c.value_b)} for c in diff.added],
            "removed": [{"key": c.key, "value": _ser(c.value_a)} for c in diff.removed],
            "modified": [
                {"key": c.key, "from": _ser(c.value_a), "to": _ser(c.value_b)}
                for c in diff.modified
            ],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flatten(data: dict, prefix: str = "", max_depth: int = 4) -> dict[str, Any]:
    """Aplatit récursivement un dict en clés pointées."""
    result = {}
    for k, v in data.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict) and max_depth > 1:
            result.update(_flatten(v, full_key, max_depth - 1))
        elif isinstance(v, list):
            # Listes : on sérialise pour comparaison simple
            result[full_key] = json.dumps(v, ensure_ascii=False, sort_keys=True)
        else:
            result[full_key] = v
    return result


def _values_equal(a: Any, b: Any) -> bool:
    """Comparaison tolerante aux différences de type int/float."""
    if type(a) == type(b):
        return a == b
    # int vs float : comparer numériquement
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a) == str(b)


def _ser(v: Any) -> Any:
    """Rend une valeur JSON-serializable."""
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)