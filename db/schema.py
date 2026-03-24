"""
db/schema.py
============
Initialisation et migration de la base SQLite.
Point d'entrée unique : init_db(path).
"""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger("factorio_hub.db.schema")

# Répertoire contenant les fichiers de migration SQL
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


# ---------------------------------------------------------------------------
# Schéma inline (migration 001)
# Dupliqué ici pour permettre init_db() sans dépendance aux fichiers .sql
# → Le fichier 001_initial.sql reste la référence documentaire
# ---------------------------------------------------------------------------
SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Table de contrôle des migrations appliquées
CREATE TABLE IF NOT EXISTS schema_migrations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    version     TEXT NOT NULL UNIQUE,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Versions synchronisées
CREATE TABLE IF NOT EXISTS versions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    version_tag      TEXT NOT NULL,
    api_version      INTEGER,
    sync_date        TEXT NOT NULL DEFAULT (datetime('now')),
    sources_synced   TEXT NOT NULL DEFAULT '[]',
    is_latest        INTEGER DEFAULT 0,
    checksum_raw     TEXT,
    checksum_api     TEXT,
    UNIQUE(version_tag)
);

-- Types de prototypes (depuis prototype-api.json)
CREATE TABLE IF NOT EXISTS prototype_types (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id       INTEGER NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    typename         TEXT,
    parent_name      TEXT,
    parent_id        INTEGER REFERENCES prototype_types(id),
    is_abstract      INTEGER DEFAULT 0,
    is_deprecated    INTEGER DEFAULT 0,
    description      TEXT,
    properties_json  TEXT,
    UNIQUE(name, version_id)
);

-- Types de données réutilisables (EnergySource, IconData, etc.)
CREATE TABLE IF NOT EXISTS data_types (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id       INTEGER NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    parent_name      TEXT,
    description      TEXT,
    properties_json  TEXT,
    UNIQUE(name, version_id)
);

-- Prototypes concrets (instances depuis data.raw)
CREATE TABLE IF NOT EXISTS prototypes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id       INTEGER NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    type_id          INTEGER REFERENCES prototype_types(id),
    typename         TEXT NOT NULL,
    name             TEXT NOT NULL,
    raw_json         TEXT NOT NULL,
    localised_name   TEXT,
    order_key        TEXT,
    subgroup         TEXT,
    UNIQUE(typename, name, version_id)
);

-- Propriétés extraites (pour diff et recherche sans parser raw_json)
CREATE TABLE IF NOT EXISTS prototype_properties (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    prototype_id     INTEGER NOT NULL REFERENCES prototypes(id) ON DELETE CASCADE,
    key              TEXT NOT NULL,
    value_text       TEXT,
    value_type       TEXT NOT NULL DEFAULT 'string'
);

-- Propriétés de schéma (ce que chaque TYPE accepte)
CREATE TABLE IF NOT EXISTS type_properties (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    type_id          INTEGER NOT NULL REFERENCES prototype_types(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    type_str         TEXT NOT NULL,
    is_optional      INTEGER DEFAULT 0,
    default_value    TEXT,
    description      TEXT,
    is_inherited     INTEGER DEFAULT 0,
    property_order   INTEGER DEFAULT 0,
    override         INTEGER DEFAULT 0
);

-- Relations entre prototypes
CREATE TABLE IF NOT EXISTS prototype_relations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id       INTEGER NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    source_typename  TEXT NOT NULL,
    source_name      TEXT NOT NULL,
    target_typename  TEXT,
    target_name      TEXT NOT NULL,
    relation_type    TEXT NOT NULL,
    property_path    TEXT
);

-- Annotations utilisateur
CREATE TABLE IF NOT EXISTS annotations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    typename         TEXT NOT NULL,
    proto_name       TEXT NOT NULL,
    version_tag      TEXT,
    content          TEXT NOT NULL,
    tags_json        TEXT NOT NULL DEFAULT '[]',
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS prototypes_fts USING fts5(
    name,
    typename,
    localised_name,
    properties_flat,
    content='prototypes',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 1'
);

-- Triggers FTS
CREATE TRIGGER IF NOT EXISTS proto_ai AFTER INSERT ON prototypes BEGIN
    INSERT INTO prototypes_fts(rowid, name, typename, localised_name, properties_flat)
    VALUES (NEW.id, NEW.name, NEW.typename, COALESCE(NEW.localised_name, ''), '');
END;

CREATE TRIGGER IF NOT EXISTS proto_ad AFTER DELETE ON prototypes BEGIN
    INSERT INTO prototypes_fts(prototypes_fts, rowid, name, typename, localised_name, properties_flat)
    VALUES ('delete', OLD.id, OLD.name, OLD.typename, COALESCE(OLD.localised_name, ''), '');
END;

-- Index
CREATE INDEX IF NOT EXISTS idx_proto_name         ON prototypes(name);
CREATE INDEX IF NOT EXISTS idx_proto_typename      ON prototypes(typename);
CREATE INDEX IF NOT EXISTS idx_proto_version       ON prototypes(version_id);
CREATE INDEX IF NOT EXISTS idx_proto_type          ON prototypes(type_id);
CREATE INDEX IF NOT EXISTS idx_proto_subgroup      ON prototypes(subgroup);
CREATE INDEX IF NOT EXISTS idx_prop_proto          ON prototype_properties(prototype_id);
CREATE INDEX IF NOT EXISTS idx_prop_key            ON prototype_properties(key);
CREATE INDEX IF NOT EXISTS idx_prop_key_val        ON prototype_properties(key, value_text);
CREATE INDEX IF NOT EXISTS idx_typeprop_type       ON type_properties(type_id);
CREATE INDEX IF NOT EXISTS idx_rel_source          ON prototype_relations(source_typename, source_name);
CREATE INDEX IF NOT EXISTS idx_rel_target          ON prototype_relations(target_name);
CREATE INDEX IF NOT EXISTS idx_rel_type            ON prototype_relations(relation_type);
CREATE INDEX IF NOT EXISTS idx_annot_proto         ON annotations(typename, proto_name);
CREATE INDEX IF NOT EXISTS idx_ptypes_typename     ON prototype_types(typename);
CREATE INDEX IF NOT EXISTS idx_ptypes_version      ON prototype_types(version_id);
"""

MIGRATION_002 = """
-- Migration 002 : ajout colonne notes sur les annotations (exemple)
-- Voir db/migrations/002_annotations.sql
"""


def init_db(db_path: Path) -> None:
    """
    Crée et initialise la base SQLite si elle n'existe pas.
    Idempotent : sûr à appeler à chaque démarrage.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(db_path)
    try:
        con.executescript(SCHEMA_SQL)
        # Marquer migration 001 comme appliquée
        con.execute(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
            ("001_initial",),
        )
        con.commit()
        logger.info("Base de données initialisée : %s", db_path)
    finally:
        con.close()

    # Appliquer les migrations supplémentaires
    _apply_file_migrations(db_path)


def _apply_file_migrations(db_path: Path) -> None:
    """
    Applique les fichiers .sql de migrations/ qui ne sont pas encore en DB.
    Convention de nommage : 002_xxx.sql, 003_xxx.sql...
    """
    if not MIGRATIONS_DIR.exists():
        return

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        return

    con = sqlite3.connect(db_path)
    try:
        applied = {
            row[0]
            for row in con.execute("SELECT version FROM schema_migrations")
        }
        for sql_file in sql_files:
            version = sql_file.stem  # ex: "002_annotations"
            if version in applied:
                continue
            logger.info("Application migration : %s", version)
            con.executescript(sql_file.read_text(encoding="utf-8"))
            con.execute(
                "INSERT INTO schema_migrations(version) VALUES (?)", (version,)
            )
            con.commit()
    finally:
        con.close()


def get_db_info(db_path: Path) -> dict:
    """Retourne un résumé de l'état de la base (utilisé par cmd_status)."""
    db_path = Path(db_path)
    if not db_path.exists():
        return {"exists": False}

    con = sqlite3.connect(db_path)
    info = {"exists": True, "path": str(db_path)}
    try:
        tables = [
            "versions", "prototype_types", "prototypes",
            "prototype_properties", "type_properties",
            "prototype_relations", "annotations",
        ]
        info["counts"] = {}
        for table in tables:
            try:
                row = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                info["counts"][table] = row[0]
            except sqlite3.OperationalError:
                info["counts"][table] = None  # table absente

        info["versions"] = con.execute(
            "SELECT version_tag, sources_synced, sync_date, is_latest "
            "FROM versions ORDER BY sync_date DESC"
        ).fetchall()

        info["migrations"] = [
            r[0] for r in con.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]
    finally:
        con.close()

    return info