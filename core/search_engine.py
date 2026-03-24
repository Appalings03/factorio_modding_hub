"""
core/search_engine.py
======================
Moteur de recherche sur les prototypes.
Encapsule la logique de requête pour ne pas polluer les routes Flask.

Modes de recherche :
- Full-text (FTS5) : recherche dans name, typename, localised_name, properties_flat
- Exact : recherche par typename + name exact
- Par propriété : prototypes ayant key=value
- Filtres combinables : typename, version, subgroup
"""

import logging
import sqlite3
from pathlib import Path

from db.repository import Repository

logger = logging.getLogger("factorio_hub.search")

# Nombre de résultats par page par défaut
DEFAULT_PAGE_SIZE = 50


class SearchEngine:
    """
    Fournit des méthodes de recherche de haut niveau sur la DB.
    """

    def __init__(self, repo: Repository):
        self.repo = repo

    # ------------------------------------------------------------------ #
    # Recherche principale                                                 #
    # ------------------------------------------------------------------ #

    def search(
        self,
        query: str,
        version_id: int | None = None,
        typename: str | None = None,
        subgroup: str | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict:
        """
        Recherche full-text avec filtres optionnels.
        Retourne un dict :
        {
            "results": [...],
            "total":   int,
            "page":    int,
            "pages":   int,
            "query":   str,
        }
        """
        if version_id is None:
            version_id = self._latest_version_id()
        if version_id is None:
            return _empty_result(query, page)

        query   = query.strip()
        offset  = (page - 1) * page_size

        if not query:
            # Sans query : liste paginée par typename
            results, total = self._list_all(
                version_id, typename, subgroup, page_size, offset
            )
        else:
            results, total = self._fts_search(
                query, version_id, typename, subgroup, page_size, offset
            )

        return {
            "results":  results,
            "total":    total,
            "page":     page,
            "pages":    max(1, (total + page_size - 1) // page_size),
            "query":    query,
            "typename": typename,
            "version_id": version_id,
        }

    def _fts_search(
        self,
        query: str,
        version_id: int,
        typename: str | None,
        subgroup: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict], int]:
        """
        Recherche FTS5.
        FTS5 supporte : "mot exact", mot*, mot1 OR mot2, -exclusion
        On sanitize la query pour éviter les erreurs de syntaxe FTS5.
        """
        safe_query = _sanitize_fts_query(query)
        if not safe_query:
            return [], 0

        with self.repo._conn() as con:
            # Construction dynamique des filtres SQL
            filters = ["p.version_id = ?"]
            params  = [version_id]

            if typename:
                filters.append("p.typename = ?")
                params.append(typename)
            if subgroup:
                filters.append("p.subgroup = ?")
                params.append(subgroup)

            where = " AND ".join(filters)

            sql_results = f"""
                SELECT p.id, p.name, p.typename, p.localised_name,
                       p.order_key, p.subgroup
                FROM prototypes_fts f
                JOIN prototypes p ON p.id = f.rowid
                WHERE prototypes_fts MATCH ?
                  AND {where}
                ORDER BY rank
                LIMIT ? OFFSET ?
            """
            sql_count = f"""
                SELECT COUNT(*)
                FROM prototypes_fts f
                JOIN prototypes p ON p.id = f.rowid
                WHERE prototypes_fts MATCH ?
                  AND {where}
            """

            try:
                rows  = con.execute(sql_results, [safe_query] + params + [limit, offset]).fetchall()
                count = con.execute(sql_count,   [safe_query] + params).fetchone()[0]
            except sqlite3.OperationalError as e:
                logger.warning("Erreur FTS query=%r : %s", query, e)
                return [], 0

            return [dict(r) for r in rows], count

    def _list_all(
        self,
        version_id: int,
        typename: str | None,
        subgroup: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict], int]:
        with self.repo._conn() as con:
            filters = ["version_id = ?"]
            params  = [version_id]
            if typename:
                filters.append("typename = ?")
                params.append(typename)
            if subgroup:
                filters.append("subgroup = ?")
                params.append(subgroup)

            where = " AND ".join(filters)

            rows = con.execute(
                f"SELECT id, name, typename, localised_name, order_key, subgroup "
                f"FROM prototypes WHERE {where} "
                f"ORDER BY typename, order_key, name LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()

            count = con.execute(
                f"SELECT COUNT(*) FROM prototypes WHERE {where}", params
            ).fetchone()[0]

            return [dict(r) for r in rows], count

    # ------------------------------------------------------------------ #
    # Recherche par propriété                                              #
    # ------------------------------------------------------------------ #

    def search_by_property(
        self,
        key: str,
        value: str,
        version_id: int | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Trouve tous les prototypes ayant la propriété key=value.
        Ex: search_by_property("subgroup", "raw-resource")
        """
        if version_id is None:
            version_id = self._latest_version_id()
        if version_id is None:
            return []

        with self.repo._conn() as con:
            rows = con.execute(
                """
                SELECT p.id, p.name, p.typename, p.localised_name
                FROM prototype_properties pp
                JOIN prototypes p ON p.id = pp.prototype_id
                WHERE pp.key = ? AND pp.value_text = ?
                  AND p.version_id = ?
                ORDER BY p.typename, p.name
                LIMIT ?
                """,
                (key, str(value), version_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Suggestions / autocomplete                                           #
    # ------------------------------------------------------------------ #

    def autocomplete(
        self,
        prefix: str,
        version_id: int | None = None,
        limit: int = 10,
    ) -> list[str]:
        """
        Retourne des noms de prototypes commençant par prefix.
        Utilisé pour le champ de recherche avec suggestions.
        """
        if version_id is None:
            version_id = self._latest_version_id()
        if version_id is None or not prefix:
            return []

        with self.repo._conn() as con:
            rows = con.execute(
                "SELECT name FROM prototypes "
                "WHERE name LIKE ? AND version_id = ? "
                "ORDER BY name LIMIT ?",
                (f"{prefix}%", version_id, limit),
            ).fetchall()
            return [r["name"] for r in rows]

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _latest_version_id(self) -> int | None:
        versions = self.repo.get_all_versions()
        if not versions:
            return None
        # Priorité : is_latest, puis sync_date
        latest = sorted(
            versions,
            key=lambda v: (v["is_latest"], v["sync_date"]),
            reverse=True,
        )
        return latest[0]["id"]

    def get_typenames(self, version_id: int | None = None) -> list[str]:
        if version_id is None:
            version_id = self._latest_version_id()
        if version_id is None:
            return []
        return self.repo.list_typenames(version_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize_fts_query(query: str) -> str:
    """
    Sanitize une query FTS5 pour éviter les erreurs de syntaxe.
    - Charactères spéciaux FTS5 non supportés → on les échappe ou retire
    - Query vide → ""
    """
    if not query or not query.strip():
        return ""

    q = query.strip()

    # Si la query contient des guillemets non fermés → on les retire
    if q.count('"') % 2 != 0:
        q = q.replace('"', '')

    # Wildcards implicites sur le dernier terme (si pas déjà présent)
    tokens = q.split()
    if tokens and not tokens[-1].endswith("*") and len(tokens[-1]) >= 2:
        tokens[-1] = tokens[-1] + "*"

    return " ".join(tokens)


def _empty_result(query: str, page: int) -> dict:
    return {
        "results":    [],
        "total":      0,
        "page":       page,
        "pages":      1,
        "query":      query,
        "typename":   None,
        "version_id": None,
    }