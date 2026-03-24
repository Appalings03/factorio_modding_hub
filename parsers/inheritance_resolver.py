"""
parsers/inheritance_resolver.py
================================
Résolution et propagation de l'arbre d'héritage des types de prototypes.

Responsabilités :
1. Construire l'arbre d'héritage depuis prototype-api.json
2. Propager les propriétés héritées vers les types enfants (pour type_properties)
3. Fournir des utilitaires de navigation dans l'arbre (ancêtres, descendants)

Note : la résolution parent_name → parent_id en DB est dans repository.py.
Ce module travaille sur les structures Python en mémoire, avant l'import DB.
"""

import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger("factorio_hub.parsers.inheritance")


class InheritanceResolver:
    """
    Construit et interroge l'arbre d'héritage des types Factorio.

    Usage typique (dans sync_manager.py) :
        resolver = InheritanceResolver()
        resolver.build(api_data["prototypes"])

        # Ancêtres de RecipePrototype
        resolver.ancestors("RecipePrototype")
        # → ["PrototypeBase"]

        # Propriétés effectives (propres + héritées)
        resolver.effective_properties("RecipePrototype")
        # → [{"name": "name", "inherited_from": "PrototypeBase", ...}, ...]
    """

    def __init__(self):
        # name → dict complet du type
        self._types: dict[str, dict] = {}
        # name → parent_name
        self._parent: dict[str, str | None] = {}
        # name → [children names]
        self._children: dict[str, list[str]] = defaultdict(list)

    def build(self, prototypes: list[dict]) -> None:
        """
        Construit l'arbre depuis la liste des prototypes de prototype-api.json.
        """
        self._types.clear()
        self._parent.clear()
        self._children.clear()

        for proto in prototypes:
            name   = proto.get("name", "")
            parent = proto.get("parent")
            if not name:
                continue
            self._types[name]  = proto
            self._parent[name] = parent
            if parent:
                self._children[parent].append(name)

        logger.info(
            "Arbre d'héritage construit : %d types, %d racines",
            len(self._types),
            sum(1 for p in self._parent.values() if p is None),
        )

    def ancestors(self, type_name: str) -> list[str]:
        """
        Retourne la liste ordonnée des ancêtres (du parent direct vers la racine).
        Ex: ancestors("RecipePrototype") → ["PrototypeBase"]
        """
        result  = []
        current = self._parent.get(type_name)
        visited = {type_name}

        while current and current not in visited:
            result.append(current)
            visited.add(current)
            current = self._parent.get(current)

        return result

    def descendants(self, type_name: str, recursive: bool = True) -> list[str]:
        """
        Retourne tous les types qui héritent (directement ou indirectement) de type_name.
        """
        result = []
        queue  = list(self._children.get(type_name, []))
        visited = set()

        while queue:
            child = queue.pop(0)
            if child in visited:
                continue
            visited.add(child)
            result.append(child)
            if recursive:
                queue.extend(self._children.get(child, []))

        return result

    def effective_properties(self, type_name: str) -> list[dict]:
        """
        Retourne la liste complète des propriétés d'un type,
        en incluant celles héritées des parents (ordre : propres d'abord,
        puis chaque niveau d'héritage).

        Chaque propriété est augmentée d'un champ "inherited_from" :
          - None si la propriété est définie sur ce type
          - nom du type ancêtre sinon

        Les propriétés overridées (override=True) remplacent la définition parente.
        """
        chain = [type_name] + self.ancestors(type_name)
        seen_props: dict[str, dict] = {}  # prop_name → prop dict

        # On parcourt de la racine vers le type courant
        # pour que les surcharges écrasent les définitions parentes
        for ancestor in reversed(chain):
            type_data = self._types.get(ancestor)
            if not type_data:
                continue
            is_own = ancestor == type_name

            for prop in type_data.get("properties", []):
                prop_name = prop.get("name", "")
                if not prop_name:
                    continue

                enriched = dict(prop)
                enriched["inherited_from"] = None if is_own else ancestor
                enriched["is_inherited"]   = not is_own
                seen_props[prop_name] = enriched

        # Tri : propriétés propres d'abord, puis héritées ; par order
        own      = [p for p in seen_props.values() if not p["is_inherited"]]
        inherited = [p for p in seen_props.values() if p["is_inherited"]]
        own.sort(key=lambda p: p.get("order", 999))
        inherited.sort(key=lambda p: (p["inherited_from"] or "", p.get("order", 999)))

        return own + inherited

    def is_subtype_of(self, type_name: str, ancestor_name: str) -> bool:
        """
        Retourne True si type_name est un sous-type de ancestor_name.
        Ex: is_subtype_of("RecipePrototype", "PrototypeBase") → True
        """
        return ancestor_name in self.ancestors(type_name)

    def roots(self) -> list[str]:
        """Types qui n'ont pas de parent (racines de l'arbre)."""
        return [name for name, parent in self._parent.items() if parent is None]

    def all_type_names(self) -> list[str]:
        return list(self._types.keys())

    def get_type(self, type_name: str) -> dict | None:
        return self._types.get(type_name)

    def depth(self, type_name: str) -> int:
        """Profondeur dans l'arbre (0 = racine)."""
        return len(self.ancestors(type_name))

    def print_tree(self, root: str | None = None, indent: int = 0) -> None:
        """Affiche l'arbre d'héritage dans stdout (debug)."""
        if root is None:
            for r in sorted(self.roots()):
                self.print_tree(r, 0)
            return
        print("  " * indent + root)
        for child in sorted(self._children.get(root, [])):
            self.print_tree(child, indent + 1)

    def to_dict(self) -> dict[str, Any]:
        """
        Exporte l'arbre sous forme de dict sérialisable JSON.
        Utile pour debug ou cache.
        """
        return {
            name: {
                "parent":    self._parent.get(name),
                "children":  self._children.get(name, []),
                "abstract":  self._types[name].get("abstract", False),
                "typename":  self._types[name].get("typename"),
                "depth":     self.depth(name),
            }
            for name in self._types
        }