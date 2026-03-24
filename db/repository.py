"""
db/repository.py
================
Couche d'accès aux données (Repository pattern).
Toutes les requêtes SQL de l'application passent par ici.
Jamais de SQL dans les scrapers, parsers ou routes Flask.
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger("factorio_hub.db.repository")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Repository:
    """
    Encapsule toutes les opérations sur la base SQLite.
    Thread-safety : chaque appel ouvre/ferme sa propre connexion via
    le context manager _conn(). Pour Flask (mono-thread dev), c'est suffisant.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA journal_mode = WAL")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def close(self) -> None:
        """Compat : rien à fermer en mode connexion-par-appel."""
        pass

    # ------------------------------------------------------------------ #
    # VERSIONS                                                             #
    # ------------------------------------------------------------------ #

    def upsert_version(self, version_tag: str, source: str) -> int:
        """
        Crée ou met à jour une version.
        Retourne l'id de la version.
        """
        with self._conn() as con:
            cur = con.execute(
                "SELECT id, sources_synced FROM versions WHERE version_tag = ?",
                (version_tag,),
            )
            row = cur.fetchone()
            if row:
                # Ajouter la source si pas déjà présente
                sources = json.loads(row["sources_synced"])
                if source not in sources:
                    sources.append(source)
                con.execute(
                    "UPDATE versions SET sources_synced = ?, sync_date = ? "
                    "WHERE id = ?",
                    (json.dumps(sources), _now(), row["id"]),
                )
                return row["id"]
            else:
                cur = con.execute(
                    "INSERT INTO versions(version_tag, sources_synced, sync_date) "
                    "VALUES (?, ?, ?)",
                    (version_tag, json.dumps([source]), _now()),
                )
                return cur.lastrowid

    def set_latest_version(self, version_tag: str) -> None:
        with self._conn() as con:
            con.execute("UPDATE versions SET is_latest = 0")
            con.execute(
                "UPDATE versions SET is_latest = 1 WHERE version_tag = ?",
                (version_tag,),
            )

    def get_all_versions(self) -> list[dict]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM versions ORDER BY sync_date DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_latest_version_tag(self) -> str | None:
        with self._conn() as con:
            row = con.execute(
                "SELECT version_tag FROM versions "
                "ORDER BY is_latest DESC, sync_date DESC LIMIT 1"
            ).fetchone()
            return row["version_tag"] if row else None

    # ------------------------------------------------------------------ #
    # PROTOTYPE TYPES                                                      #
    # ------------------------------------------------------------------ #

    def upsert_prototype_type(self, version_id: int, data: dict) -> int:
        with self._conn() as con:
            cur = con.execute(
                """
                INSERT INTO prototype_types
                    (version_id, name, typename, parent_name, is_abstract,
                     is_deprecated, description, properties_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name, version_id) DO UPDATE SET
                    typename       = excluded.typename,
                    parent_name    = excluded.parent_name,
                    is_abstract    = excluded.is_abstract,
                    is_deprecated  = excluded.is_deprecated,
                    description    = excluded.description,
                    properties_json= excluded.properties_json
                """,
                (
                    version_id,
                    data["name"],
                    data.get("typename"),
                    data.get("parent"),
                    1 if data.get("abstract") else 0,
                    1 if data.get("deprecated") else 0,
                    data.get("description", ""),
                    json.dumps(data.get("properties", [])),
                ),
            )
            return cur.lastrowid

    def resolve_type_inheritance(self, version_id: int) -> None:
        """
        Résout parent_name → parent_id pour tous les types d'une version.
        À appeler après avoir inséré tous les types.
        """
        with self._conn() as con:
            con.execute(
                """
                UPDATE prototype_types AS child
                SET parent_id = (
                    SELECT parent.id
                    FROM prototype_types AS parent
                    WHERE parent.name      = child.parent_name
                      AND parent.version_id = child.version_id
                )
                WHERE version_id = ?
                  AND parent_name IS NOT NULL
                  AND parent_id IS NULL
                """,
                (version_id,),
            )

    def get_type_id(self, name: str, version_id: int) -> int | None:
        with self._conn() as con:
            row = con.execute(
                "SELECT id FROM prototype_types WHERE name = ? AND version_id = ?",
                (name, version_id),
            ).fetchone()
            return row["id"] if row else None

    def get_type_by_typename(self, typename: str, version_id: int) -> dict | None:
        """Recherche par typename (clé data.raw), pas par nom de classe."""
        with self._conn() as con:
            row = con.execute(
                "SELECT * FROM prototype_types "
                "WHERE typename = ? AND version_id = ?",
                (typename, version_id),
            ).fetchone()
            return dict(row) if row else None

    def get_type_ancestors(self, type_id: int) -> list[dict]:
        """
        Remonte la chaîne d'héritage jusqu'à la racine.
        Retourne la liste ordonnée [parent, grand-parent, ...].
        """
        with self._conn() as con:
            ancestors = []
            current_id = type_id
            visited = set()
            while current_id:
                if current_id in visited:
                    break
                visited.add(current_id)
                row = con.execute(
                    "SELECT * FROM prototype_types WHERE id = ?",
                    (current_id,),
                ).fetchone()
                if not row:
                    break
                ancestors.append(dict(row))
                current_id = row["parent_id"]
            return ancestors[1:]  # exclut le type lui-même

    def get_type_children(self, type_id: int) -> list[dict]:
        """Retourne les types qui héritent directement de type_id."""
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM prototype_types WHERE parent_id = ?",
                (type_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # TYPE PROPERTIES                                                      #
    # ------------------------------------------------------------------ #

    def upsert_type_properties(self, type_id: int, properties: list[dict]) -> None:
        with self._conn() as con:
            # Supprime et réinsère (plus simple que upsert sur 3 clés)
            con.execute(
                "DELETE FROM type_properties WHERE type_id = ? AND is_inherited = 0",
                (type_id,),
            )
            for prop in properties:
                default = prop.get("default")
                con.execute(
                    """
                    INSERT INTO type_properties
                        (type_id, name, type_str, is_optional, default_value,
                         description, property_order, override)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        type_id,
                        prop.get("name", ""),
                        _type_str(prop.get("type")),
                        1 if prop.get("optional") else 0,
                        json.dumps(default) if default is not None else None,
                        prop.get("description", ""),
                        prop.get("order", 0),
                        1 if prop.get("override") else 0,
                    ),
                )

    def get_type_properties(self, type_id: int,
                            include_inherited: bool = True) -> list[dict]:
        with self._conn() as con:
            if include_inherited:
                rows = con.execute(
                    "SELECT * FROM type_properties WHERE type_id = ? "
                    "ORDER BY is_inherited, property_order",
                    (type_id,),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM type_properties "
                    "WHERE type_id = ? AND is_inherited = 0 "
                    "ORDER BY property_order",
                    (type_id,),
                ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # PROTOTYPES                                                           #
    # ------------------------------------------------------------------ #

    def upsert_prototype(
        self,
        version_id: int,
        typename: str,
        name: str,
        data: dict,
    ) -> int:
        type_row = None
        with self._conn() as con:
            # Résolution du type_id via typename
            type_row = con.execute(
                "SELECT id FROM prototype_types "
                "WHERE typename = ? AND version_id = ?",
                (typename, version_id),
            ).fetchone()
            type_id = type_row["id"] if type_row else None

            cur = con.execute(
                """
                INSERT INTO prototypes
                    (version_id, type_id, typename, name, raw_json,
                     localised_name, order_key, subgroup)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(typename, name, version_id) DO UPDATE SET
                    raw_json       = excluded.raw_json,
                    type_id        = excluded.type_id,
                    localised_name = excluded.localised_name,
                    order_key      = excluded.order_key,
                    subgroup       = excluded.subgroup
                """,
                (
                    version_id,
                    type_id,
                    typename,
                    name,
                    json.dumps(data, ensure_ascii=False),
                    _extract_localised_name(data),
                    data.get("order"),
                    data.get("subgroup"),
                ),
            )
            return cur.lastrowid

    def get_prototype(
        self, typename: str, name: str, version_id: int | None = None
    ) -> dict | None:
        with self._conn() as con:
            if version_id:
                row = con.execute(
                    "SELECT * FROM prototypes "
                    "WHERE typename = ? AND name = ? AND version_id = ?",
                    (typename, name, version_id),
                ).fetchone()
            else:
                # Prend la version la plus récente
                row = con.execute(
                    """
                    SELECT p.* FROM prototypes p
                    JOIN versions v ON p.version_id = v.id
                    WHERE p.typename = ? AND p.name = ?
                    ORDER BY v.is_latest DESC, v.sync_date DESC
                    LIMIT 1
                    """,
                    (typename, name),
                ).fetchone()
            if not row:
                return None
            result = dict(row)
            result["raw_json"] = json.loads(result["raw_json"])
            return result

    def get_prototypes_by_type(
        self, typename: str, version_id: int, limit: int = 200, offset: int = 0
    ) -> list[dict]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT id, name, typename, localised_name, order_key, subgroup "
                "FROM prototypes "
                "WHERE typename = ? AND version_id = ? "
                "ORDER BY order_key, name "
                "LIMIT ? OFFSET ?",
                (typename, version_id, limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def count_prototypes(self, version_id: int) -> int:
        with self._conn() as con:
            return con.execute(
                "SELECT COUNT(*) FROM prototypes WHERE version_id = ?",
                (version_id,),
            ).fetchone()[0]

    # ------------------------------------------------------------------ #
    # PROTOTYPE PROPERTIES                                                 #
    # ------------------------------------------------------------------ #

    def rebuild_properties_flat(self, version_id: int) -> None:
        """
        Extrait les propriétés scalaires de raw_json vers prototype_properties.
        Aussi met à jour le champ properties_flat dans prototypes_fts.
        Opération lourde — à appeler une seule fois après import.
        """
        with self._conn() as con:
            rows = con.execute(
                "SELECT id, raw_json FROM prototypes WHERE version_id = ?",
                (version_id,),
            ).fetchall()

            for row in rows:
                proto_id  = row["id"]
                raw       = json.loads(row["raw_json"])
                flat_kvs  = list(_flatten_json(raw))

                # Supprime les anciennes propriétés
                con.execute(
                    "DELETE FROM prototype_properties WHERE prototype_id = ?",
                    (proto_id,),
                )
                # Réinsère
                con.executemany(
                    "INSERT INTO prototype_properties(prototype_id, key, value_text, value_type) "
                    "VALUES (?, ?, ?, ?)",
                    [
                        (proto_id, k, str(v), _value_type(v))
                        for k, v in flat_kvs
                    ],
                )
                # Met à jour properties_flat dans FTS
                flat_text = " ".join(f"{k}:{v}" for k, v in flat_kvs)
                con.execute(
                    "UPDATE prototypes_fts SET properties_flat = ? WHERE rowid = ?",
                    (flat_text, proto_id),
                )

    def get_prototype_properties(self, prototype_id: int) -> list[dict]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT key, value_text, value_type "
                "FROM prototype_properties WHERE prototype_id = ? ORDER BY key",
                (prototype_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # RELATIONS                                                            #
    # ------------------------------------------------------------------ #

    def extract_relations(self, version_id: int) -> None:
        """
        Parcourt les prototypes et extrait les relations connues.
        Actuellement : ingredients, results (recettes), subgroup.
        """
        with self._conn() as con:
            # Supprime les anciennes relations de cette version
            con.execute(
                "DELETE FROM prototype_relations WHERE version_id = ?",
                (version_id,),
            )
            rows = con.execute(
                "SELECT id, typename, name, raw_json FROM prototypes "
                "WHERE version_id = ?",
                (version_id,),
            ).fetchall()

            inserts = []
            for row in rows:
                raw   = json.loads(row["raw_json"])
                stype = row["typename"]
                sname = row["name"]

                # Ingrédients de recette
                for i, ing in enumerate(raw.get("ingredients", []) or []):
                    target = ing.get("name") if isinstance(ing, dict) else None
                    if target:
                        inserts.append((
                            version_id, stype, sname, "item", target,
                            "ingredient", f"ingredients[{i}].name",
                        ))

                # Résultats de recette
                for i, res in enumerate(raw.get("results", []) or []):
                    target = res.get("name") if isinstance(res, dict) else None
                    if target:
                        inserts.append((
                            version_id, stype, sname, "item", target,
                            "result", f"results[{i}].name",
                        ))

                # Subgroup
                if sg := raw.get("subgroup"):
                    inserts.append((
                        version_id, stype, sname, "item-subgroup", sg,
                        "subgroup", "subgroup",
                    ))

            con.executemany(
                """
                INSERT INTO prototype_relations
                    (version_id, source_typename, source_name,
                     target_typename, target_name, relation_type, property_path)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                inserts,
            )

    def get_relations_from(
        self, typename: str, name: str, version_id: int
    ) -> list[dict]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM prototype_relations "
                "WHERE source_typename = ? AND source_name = ? AND version_id = ?",
                (typename, name, version_id),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_relations_to(
        self, target_name: str, version_id: int,
        relation_type: str | None = None,
    ) -> list[dict]:
        with self._conn() as con:
            if relation_type:
                rows = con.execute(
                    "SELECT * FROM prototype_relations "
                    "WHERE target_name = ? AND version_id = ? AND relation_type = ?",
                    (target_name, version_id, relation_type),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM prototype_relations "
                    "WHERE target_name = ? AND version_id = ?",
                    (target_name, version_id),
                ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # SEARCH                                                               #
    # ------------------------------------------------------------------ #

    def search_prototypes(
        self,
        query: str,
        version_id: int,
        typename: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """
        Recherche full-text via FTS5.
        Si typename est fourni, filtre sur ce type.
        """
        with self._conn() as con:
            if typename:
                rows = con.execute(
                    """
                    SELECT p.id, p.name, p.typename, p.localised_name,
                           p.order_key, p.subgroup
                    FROM prototypes_fts f
                    JOIN prototypes p ON p.id = f.rowid
                    WHERE prototypes_fts MATCH ?
                      AND p.version_id = ?
                      AND p.typename   = ?
                    ORDER BY rank
                    LIMIT ? OFFSET ?
                    """,
                    (query, version_id, typename, limit, offset),
                ).fetchall()
            else:
                rows = con.execute(
                    """
                    SELECT p.id, p.name, p.typename, p.localised_name,
                           p.order_key, p.subgroup
                    FROM prototypes_fts f
                    JOIN prototypes p ON p.id = f.rowid
                    WHERE prototypes_fts MATCH ?
                      AND p.version_id = ?
                    ORDER BY rank
                    LIMIT ? OFFSET ?
                    """,
                    (query, version_id, limit, offset),
                ).fetchall()
            return [dict(r) for r in rows]

    def list_typenames(self, version_id: int) -> list[str]:
        """Liste tous les typenames présents dans la DB pour une version."""
        with self._conn() as con:
            rows = con.execute(
                "SELECT DISTINCT typename FROM prototypes "
                "WHERE version_id = ? ORDER BY typename",
                (version_id,),
            ).fetchall()
            return [r["typename"] for r in rows]

    # ------------------------------------------------------------------ #
    # ANNOTATIONS                                                          #
    # ------------------------------------------------------------------ #

    def upsert_annotation(
        self,
        typename: str,
        proto_name: str,
        content: str,
        tags: list[str] | None = None,
        version_tag: str | None = None,
        annotation_id: int | None = None,
    ) -> int:
        tags = tags or []
        with self._conn() as con:
            if annotation_id:
                con.execute(
                    "UPDATE annotations SET content=?, tags_json=?, "
                    "updated_at=? WHERE id=?",
                    (content, json.dumps(tags), _now(), annotation_id),
                )
                return annotation_id
            else:
                cur = con.execute(
                    """
                    INSERT INTO annotations
                        (typename, proto_name, version_tag, content, tags_json,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (typename, proto_name, version_tag, content,
                     json.dumps(tags), _now(), _now()),
                )
                return cur.lastrowid

    def get_annotations(
        self,
        typename: str,
        proto_name: str,
        version_tag: str | None = None,
    ) -> list[dict]:
        with self._conn() as con:
            if version_tag:
                rows = con.execute(
                    "SELECT * FROM annotations "
                    "WHERE typename=? AND proto_name=? "
                    "AND (version_tag=? OR version_tag IS NULL) "
                    "ORDER BY updated_at DESC",
                    (typename, proto_name, version_tag),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM annotations "
                    "WHERE typename=? AND proto_name=? "
                    "ORDER BY updated_at DESC",
                    (typename, proto_name),
                ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["tags"] = json.loads(d.get("tags_json") or "[]")
                result.append(d)
            return result

    def delete_annotation(self, annotation_id: int) -> None:
        with self._conn() as con:
            con.execute("DELETE FROM annotations WHERE id = ?", (annotation_id,))

    # ------------------------------------------------------------------ #
    # DIFF (support pour diff_engine.py)                                  #
    # ------------------------------------------------------------------ #

    def get_prototype_raw(
        self, typename: str, name: str, version_id: int
    ) -> dict | None:
        with self._conn() as con:
            row = con.execute(
                "SELECT raw_json FROM prototypes "
                "WHERE typename=? AND name=? AND version_id=?",
                (typename, name, version_id),
            ).fetchone()
            return json.loads(row["raw_json"]) if row else None

    def get_version_id(self, version_tag: str) -> int | None:
        with self._conn() as con:
            row = con.execute(
                "SELECT id FROM versions WHERE version_tag = ?",
                (version_tag,),
            ).fetchone()
            return row["id"] if row else None


# ------------------------------------------------------------------ #
# Helpers privés                                                       #
# ------------------------------------------------------------------ #

def _type_str(type_info: Any) -> str:
    """
    Convertit le champ 'type' du JSON prototype-api en chaîne lisible.
    Le champ peut être une string simple ou un dict complexe.
    """
    if isinstance(type_info, str):
        return type_info
    if isinstance(type_info, dict):
        complex_type = type_info.get("complex_type")
        if complex_type == "literal":
            return f'literal:{type_info.get("value")}'
        if complex_type == "union":
            options = type_info.get("options", [])
            return " | ".join(_type_str(o) for o in options)
        if complex_type == "array":
            return f'array[{_type_str(type_info.get("value", "?"))}]'
        if complex_type == "dictionary":
            k = _type_str(type_info.get("key", "?"))
            v = _type_str(type_info.get("value", "?"))
            return f'dict[{k}, {v}]'
        return complex_type or "unknown"
    return "unknown"


def _value_type(v: Any) -> str:
    if v is None:
        return "nil"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, (dict, list)):
        return "table"
    return "string"


def _flatten_json(
    data: dict,
    prefix: str = "",
    max_depth: int = 3,
) -> Iterator[tuple[str, Any]]:
    """
    Aplatit un dict JSON jusqu'à max_depth niveaux.
    Yield (key_path, scalar_value).
    Les listes et dicts profonds sont sérialisés en JSON string.
    """
    for k, v in data.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict) and max_depth > 1:
            yield from _flatten_json(v, full_key, max_depth - 1)
        elif isinstance(v, list):
            # On ne descend pas dans les listes — trop verbeux
            yield full_key, json.dumps(v, ensure_ascii=False)
        else:
            yield full_key, v


def _extract_localised_name(data: dict) -> str | None:
    """
    Extrait le nom localisé depuis data.raw.
    Factorio stocke localised_name comme string ou table Lua.
    """
    ln = data.get("localised_name")
    if isinstance(ln, str):
        return ln
    if isinstance(ln, list) and ln:
        # Format Lua : {"item-name.iron-plate"} → on prend la clé
        return str(ln[0])
    return None