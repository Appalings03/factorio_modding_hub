-- Migration 002 : enrichissement de la table annotations
-- Ajout d'un champ "color" pour le code couleur visuel des tags
-- et d'un index sur updated_at pour trier par récence

ALTER TABLE annotations ADD COLUMN color TEXT DEFAULT 'default';

CREATE INDEX IF NOT EXISTS idx_annot_updated ON annotations(updated_at DESC);