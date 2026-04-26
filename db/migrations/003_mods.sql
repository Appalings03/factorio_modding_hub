-- db/migrations/003_mods.sql
-- Table des mods importés

CREATE TABLE IF NOT EXISTS mods (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,          -- nom du mod (ex: "my-mod")
    mod_version     TEXT NOT NULL,          -- version du mod (ex: "1.0.0")
    game_version    TEXT,                   -- version Factorio cible (ex: "2.0.76")
    import_date     TEXT NOT NULL DEFAULT (datetime('now')),
    file_name       TEXT,                   -- nom du zip original
    description     TEXT,                   -- depuis info.json
    author          TEXT,                   -- depuis info.json
    is_validated    INTEGER DEFAULT 0,      -- 1 si validation lancée
    validation_date TEXT,
    UNIQUE(name, mod_version)
);

-- Lier les prototypes à un mod
ALTER TABLE prototypes ADD COLUMN mod_id INTEGER REFERENCES mods(id) ON DELETE CASCADE;

-- Index
CREATE INDEX IF NOT EXISTS idx_proto_mod ON prototypes(mod_id);
CREATE INDEX IF NOT EXISTS idx_mods_name ON mods(name);