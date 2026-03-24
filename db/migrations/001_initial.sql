-- db/migrations/001_initial.sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ============================================================
-- VERSIONS synchronisées
-- ============================================================
CREATE TABLE IF NOT EXISTS versions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    version_tag      TEXT NOT NULL,          -- "2.0.65"
    api_version      INTEGER,                -- version du format JSON (ex: 6)
    sync_date        TEXT NOT NULL,
    sources_synced   TEXT NOT NULL,          -- JSON array ["raw_data","api_docs","github"]
    is_latest        INTEGER DEFAULT 0,
    checksum_raw     TEXT,                   -- SHA256 du gist data.raw
    checksum_api     TEXT,                   -- SHA256 du prototype-api.json
    UNIQUE(version_tag)
);

-- ============================================================
-- TYPES DE PROTOTYPES (depuis prototype-api.json)
-- Ex: RecipePrototype, EntityPrototype, ItemPrototype...
-- ============================================================
CREATE TABLE IF NOT EXISTS prototype_types (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id       INTEGER NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,          -- "RecipePrototype"
    typename         TEXT,                   -- "recipe" (clé dans data.raw)
    parent_name      TEXT,                   -- "PrototypeBase" (résolu après import)
    parent_id        INTEGER REFERENCES prototype_types(id),
    is_abstract      INTEGER DEFAULT 0,
    is_deprecated    INTEGER DEFAULT 0,
    description      TEXT,
    properties_json  TEXT,                   -- JSON brut du tableau properties[]
    UNIQUE(name, version_id)
);

-- ============================================================
-- TYPES DE DONNÉES réutilisables (depuis prototype-api.json → "types")
-- Ex: EnergySource, IconData, Color, SoundDefinition...
-- Utiles pour la phase 2 (validation de types)
-- ============================================================
CREATE TABLE IF NOT EXISTS data_types (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id       INTEGER NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,          -- "EnergySource"
    parent_name      TEXT,
    description      TEXT,
    properties_json  TEXT,                   -- JSON brut des propriétés
    UNIQUE(name, version_id)
);

-- ============================================================
-- PROTOTYPES (instances concrètes depuis data.raw)
-- Ex: assembling-machine-1, iron-plate, recipe/iron-plate...
-- ============================================================
CREATE TABLE IF NOT EXISTS prototypes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id       INTEGER NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    type_id          INTEGER REFERENCES prototype_types(id),
    typename         TEXT NOT NULL,          -- "assembling-machine" (clé data.raw)
    name             TEXT NOT NULL,          -- "assembling-machine-1"
    raw_json         TEXT NOT NULL,          -- dump JSON complet du prototype
    -- Champs dénormalisés pour les recherches rapides (évite JSON parsing)
    localised_name   TEXT,                   -- extrait de raw_json si présent
    order_key        TEXT,                   -- champ "order" pour tri UI
    subgroup         TEXT,                   -- item-subgroup de référence
    UNIQUE(typename, name, version_id)
);

-- ============================================================
-- PROPRIÉTÉS EXTRAITES (pour diff inter-versions et recherche)
-- Évite de parser raw_json à chaque requête
-- ============================================================
CREATE TABLE IF NOT EXISTS prototype_properties (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    prototype_id     INTEGER NOT NULL REFERENCES prototypes(id) ON DELETE CASCADE,
    key              TEXT NOT NULL,          -- "crafting_speed", "stack_size"
    value_text       TEXT,                   -- valeur sérialisée (même les tables)
    value_type       TEXT NOT NULL           -- "string"|"number"|"bool"|"table"|"nil"
    -- Note : pas de value_number séparé volontairement,
    -- les comparaisons numériques se font via CAST(value_text AS REAL)
);

-- ============================================================
-- PROPRIÉTÉS DE SCHÉMA (depuis prototype-api.json)
-- Ce que chaque TYPE accepte/requiert, avec leurs types attendus
-- ============================================================
CREATE TABLE IF NOT EXISTS type_properties (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    type_id          INTEGER NOT NULL REFERENCES prototype_types(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,          -- "crafting_speed"
    type_str         TEXT NOT NULL,          -- "double" | "RecipeCategoryID" | ...
    is_optional      INTEGER DEFAULT 0,
    default_value    TEXT,                   -- JSON du default (peut être complexe)
    description      TEXT,
    is_inherited     INTEGER DEFAULT 0,      -- 1 = hérité du parent, pas déclaré ici
    property_order   INTEGER DEFAULT 0,      -- champ "order" de l'API pour tri
    override         INTEGER DEFAULT 0       -- surcharge d'une propriété parent
);

-- ============================================================
-- RELATIONS entre prototypes
-- ============================================================
CREATE TABLE IF NOT EXISTS prototype_relations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id       INTEGER NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    source_typename  TEXT NOT NULL,
    source_name      TEXT NOT NULL,
    target_typename  TEXT,                   -- NULL si relation vers un type abstrait
    target_name      TEXT NOT NULL,
    relation_type    TEXT NOT NULL,
    /*
      Valeurs de relation_type :
      'ingredient'       → recipe utilise cet item
      'result'           → recipe produit cet item
      'fuel'             → utilise cette catégorie de fuel
      'module_category'  → accepte ce type de module
      'crafting_category'→ appartient à cette catégorie
      'subgroup'         → appartient à ce subgroup
      'ammo_category'    → utilise cette catégorie d'ammo
      'equipment_grid'   → possède cette grille
    */
    property_path    TEXT                    -- "ingredients[0].name" pour débogage
);

-- ============================================================
-- ANNOTATIONS UTILISATEUR
-- ============================================================
CREATE TABLE IF NOT EXISTS annotations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    typename         TEXT NOT NULL,          -- "recipe"
    proto_name       TEXT NOT NULL,          -- "iron-plate"
    version_tag      TEXT,                   -- NULL = toutes versions
    content          TEXT NOT NULL,
    tags_json        TEXT DEFAULT '[]',      -- ["todo","important"]
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

-- ============================================================
-- FULL-TEXT SEARCH
-- ============================================================
CREATE VIRTUAL TABLE IF NOT EXISTS prototypes_fts USING fts5(
    name,
    typename,
    localised_name,
    properties_flat,    -- valeurs concaténées "key:value key:value ..."
    content='prototypes',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 1'
);

-- Triggers de maintien FTS
CREATE TRIGGER proto_ai AFTER INSERT ON prototypes BEGIN
    INSERT INTO prototypes_fts(rowid, name, typename, localised_name, properties_flat)
    VALUES (NEW.id, NEW.name, NEW.typename, NEW.localised_name, '');
END;

CREATE TRIGGER proto_ad AFTER DELETE ON prototypes BEGIN
    INSERT INTO prototypes_fts(prototypes_fts, rowid, name, typename, localised_name, properties_flat)
    VALUES ('delete', OLD.id, OLD.name, OLD.typename, OLD.localised_name, '');
END;

-- ============================================================
-- INDEX
-- ============================================================
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