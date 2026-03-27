"""
tests/test_db.py
================
Tests de la couche base de données (schema + repository).
"""

import json
import tempfile
from pathlib import Path

import pytest

from db.schema     import init_db
from db.repository import Repository


@pytest.fixture
def tmp_db(tmp_path):
    """DB temporaire initialisée, nettoyée après chaque test."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def repo(tmp_db):
    return Repository(tmp_db)


# ------------------------------------------------------------------ #
# Versions                                                             #
# ------------------------------------------------------------------ #

class TestVersions:

    def test_upsert_version_creates(self, repo):
        vid = repo.upsert_version("2.0.65", "api_docs")
        assert isinstance(vid, int)
        assert vid > 0

    def test_upsert_version_idempotent(self, repo):
        vid1 = repo.upsert_version("2.0.65", "api_docs")
        vid2 = repo.upsert_version("2.0.65", "raw_data")
        assert vid1 == vid2

    def test_upsert_version_accumulates_sources(self, repo):
        repo.upsert_version("2.0.65", "api_docs")
        repo.upsert_version("2.0.65", "raw_data")
        versions = repo.get_all_versions()
        sources = json.loads(versions[0]["sources_synced"])
        assert "api_docs" in sources
        assert "raw_data" in sources

    def test_get_all_versions_empty(self, repo):
        assert repo.get_all_versions() == []

    def test_set_latest(self, repo):
        repo.upsert_version("1.1.107", "github")
        repo.upsert_version("2.0.65",  "api_docs")
        repo.set_latest_version("2.0.65")
        versions = repo.get_all_versions()
        latest = next(v for v in versions if v["version_tag"] == "2.0.65")
        assert latest["is_latest"] == 1

    def test_get_latest_version_tag(self, repo):
        repo.upsert_version("1.1.107", "github")
        vid = repo.upsert_version("2.0.65", "api_docs")
        repo.set_latest_version("2.0.65")
        assert repo.get_latest_version_tag() == "2.0.65"


# ------------------------------------------------------------------ #
# Prototype types                                                       #
# ------------------------------------------------------------------ #

class TestPrototypeTypes:

    @pytest.fixture(autouse=True)
    def setup(self, repo):
        self.repo = repo
        self.vid  = repo.upsert_version("2.0.65", "api_docs")

    def test_upsert_type(self):
        tid = self.repo.upsert_prototype_type(self.vid, {
            "name":     "RecipePrototype",
            "typename": "recipe",
            "parent":   "PrototypeBase",
            "abstract": False,
            "deprecated": False,
            "description": "A recipe.",
            "properties": [],
        })
        assert tid > 0

    def test_upsert_type_idempotent(self):
        data = {"name": "RecipePrototype", "typename": "recipe",
                "parent": None, "abstract": False, "deprecated": False,
                "description": "", "properties": []}
        tid1 = self.repo.upsert_prototype_type(self.vid, data)
        tid2 = self.repo.upsert_prototype_type(self.vid, data)
        assert tid1 == tid2

    def test_resolve_inheritance(self):
        self.repo.upsert_prototype_type(self.vid, {
            "name": "PrototypeBase", "typename": None, "parent": None,
            "abstract": True, "deprecated": False, "description": "", "properties": [],
        })
        self.repo.upsert_prototype_type(self.vid, {
            "name": "RecipePrototype", "typename": "recipe",
            "parent": "PrototypeBase", "abstract": False,
            "deprecated": False, "description": "", "properties": [],
        })
        self.repo.resolve_type_inheritance(self.vid)
        ancestors = self.repo.get_type_ancestors(
            self.repo.get_type_id("RecipePrototype", self.vid)
        )
        assert any(a["name"] == "PrototypeBase" for a in ancestors)

    def test_get_type_by_typename(self):
        self.repo.upsert_prototype_type(self.vid, {
            "name": "RecipePrototype", "typename": "recipe", "parent": None,
            "abstract": False, "deprecated": False, "description": "", "properties": [],
        })
        t = self.repo.get_type_by_typename("recipe", self.vid)
        assert t is not None
        assert t["name"] == "RecipePrototype"


# ------------------------------------------------------------------ #
# Prototypes                                                            #
# ------------------------------------------------------------------ #

class TestPrototypes:

    @pytest.fixture(autouse=True)
    def setup(self, repo):
        self.repo = repo
        self.vid  = repo.upsert_version("2.0.65", "raw_data")

    def test_upsert_and_get(self):
        data = {
            "type": "item", "name": "iron-plate",
            "stack_size": 100, "subgroup": "raw-resource",
        }
        self.repo.upsert_prototype(self.vid, "item", "iron-plate", data)
        result = self.repo.get_prototype("item", "iron-plate", self.vid)

        assert result is not None
        assert result["name"] == "iron-plate"
        assert result["typename"] == "item"
        assert result["raw_json"]["stack_size"] == 100

    def test_upsert_overwrites(self):
        data1 = {"type": "item", "name": "iron-plate", "stack_size": 100}
        data2 = {"type": "item", "name": "iron-plate", "stack_size": 200}
        self.repo.upsert_prototype(self.vid, "item", "iron-plate", data1)
        self.repo.upsert_prototype(self.vid, "item", "iron-plate", data2)
        result = self.repo.get_prototype("item", "iron-plate", self.vid)
        assert result["raw_json"]["stack_size"] == 200

    def test_get_nonexistent_returns_none(self):
        result = self.repo.get_prototype("item", "nonexistent-item", self.vid)
        assert result is None

    def test_count_prototypes(self):
        for i in range(5):
            self.repo.upsert_prototype(
                self.vid, "item", f"item-{i}",
                {"type": "item", "name": f"item-{i}"},
            )
        assert self.repo.count_prototypes(self.vid) == 5

    def test_get_prototypes_by_type(self):
        self.repo.upsert_prototype(self.vid, "item", "iron-plate",
                                   {"type": "item", "name": "iron-plate"})
        self.repo.upsert_prototype(self.vid, "item", "copper-plate",
                                   {"type": "item", "name": "copper-plate"})
        self.repo.upsert_prototype(self.vid, "recipe", "iron-plate",
                                   {"type": "recipe", "name": "iron-plate"})
        items = self.repo.get_prototypes_by_type("item", self.vid)
        assert len(items) == 2
        assert all(p["typename"] == "item" for p in items)


# ------------------------------------------------------------------ #
# Annotations                                                           #
# ------------------------------------------------------------------ #

class TestAnnotations:

    @pytest.fixture(autouse=True)
    def setup(self, repo):
        self.repo = repo

    def test_create_annotation(self):
        aid = self.repo.upsert_annotation(
            "recipe", "iron-plate",
            content="À revoir",
            tags=["todo"],
        )
        assert aid > 0

    def test_get_annotations(self):
        self.repo.upsert_annotation("recipe", "iron-plate", "Note 1", ["todo"])
        self.repo.upsert_annotation("recipe", "iron-plate", "Note 2", ["important"])
        annots = self.repo.get_annotations("recipe", "iron-plate")
        assert len(annots) == 2
        assert all("tags" in a for a in annots)

    def test_delete_annotation(self):
        aid = self.repo.upsert_annotation("item", "copper-plate", "Temporaire")
        self.repo.delete_annotation(aid)
        annots = self.repo.get_annotations("item", "copper-plate")
        assert len(annots) == 0

    def test_annotation_tags_parsed(self):
        self.repo.upsert_annotation("item", "iron-plate", "Note",
                                    tags=["bug", "important"])
        annots = self.repo.get_annotations("item", "iron-plate")
        assert set(annots[0]["tags"]) == {"bug", "important"}


# ------------------------------------------------------------------ #
# Relations                                                             #
# ------------------------------------------------------------------ #

class TestRelations:

    def test_extract_recipe_relations(self, repo):
        vid = repo.upsert_version("2.0.65", "raw_data")
        repo.upsert_prototype(vid, "recipe", "iron-gear-wheel", {
            "type": "recipe",
            "name": "iron-gear-wheel",
            "ingredients": [{"type": "item", "name": "iron-plate", "amount": 2}],
            "results":     [{"type": "item", "name": "iron-gear-wheel", "amount": 1}],
        })
        repo.extract_relations(vid)

        relations = repo.get_relations_from("recipe", "iron-gear-wheel", vid)
        types = {r["relation_type"] for r in relations}
        targets = {r["target_name"] for r in relations}

        assert "ingredient" in types
        assert "result" in types
        assert "iron-plate" in targets
        assert "iron-gear-wheel" in targets

    def test_get_relations_to(self, repo):
        vid = repo.upsert_version("2.0.65", "raw_data")
        repo.upsert_prototype(vid, "recipe", "copper-cable", {
            "type": "recipe", "name": "copper-cable",
            "ingredients": [{"type": "item", "name": "copper-plate", "amount": 1}],
            "results":     [{"type": "item", "name": "copper-cable", "amount": 2}],
        })
        repo.extract_relations(vid)
        usages = repo.get_relations_to("copper-plate", vid, relation_type="ingredient")
        assert any(r["source_name"] == "copper-cable" for r in usages)