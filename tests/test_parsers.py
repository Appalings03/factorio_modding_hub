"""
tests/test_parsers.py
=====================
Tests des modules de parsing (Lua, prototype, héritage).
"""

import pytest

from parsers.lua_json_parser    import parse_lua_string, parse_lua_file, strip_comments, extract_data_extend_blocks
from parsers.prototype_parser   import PrototypeParser, extract_localised_name
from parsers.inheritance_resolver import InheritanceResolver


# ------------------------------------------------------------------ #
# LuaTableParser                                                        #
# ------------------------------------------------------------------ #

class TestLuaParser:

    def test_simple_dict(self):
        result = parse_lua_string('{ name = "iron-plate", stack_size = 100 }')
        assert result == {"name": "iron-plate", "stack_size": 100}

    def test_simple_list(self):
        result = parse_lua_string('{ "a", "b", "c" }')
        assert result == ["a", "b", "c"]

    def test_nested_dict(self):
        result = parse_lua_string('{ outer = { inner = 42 } }')
        assert result == {"outer": {"inner": 42}}

    def test_bool_values(self):
        result = parse_lua_string('{ enabled = true, hidden = false }')
        assert result["enabled"] is True
        assert result["hidden"]  is False

    def test_nil_value(self):
        result = parse_lua_string('{ val = nil }')
        assert result["val"] is None

    def test_float(self):
        result = parse_lua_string('{ speed = 3.14 }')
        assert abs(result["speed"] - 3.14) < 1e-6

    def test_negative_number(self):
        result = parse_lua_string('{ offset = -5 }')
        assert result["offset"] == -5

    def test_string_single_quote(self):
        result = parse_lua_string("{ name = 'iron-plate' }")
        assert result["name"] == "iron-plate"

    def test_long_string(self):
        result = parse_lua_string('{ desc = [[hello world]] }')
        assert result["desc"] == "hello world"

    def test_trailing_comma(self):
        result = parse_lua_string('{ a = 1, b = 2, }')
        assert result == {"a": 1, "b": 2}

    def test_empty_table(self):
        result = parse_lua_string('{}')
        assert result == {}

    def test_mixed_list_and_dict(self):
        # Listes avec clés numériques
        result = parse_lua_string('{ "a", key = "b" }')
        assert "key" in result
        assert result["key"] == "b"

    def test_reference_becomes_string(self):
        result = parse_lua_string('{ flag = defines.direction.north }')
        assert isinstance(result["flag"], str)
        assert "defines" in result["flag"]

    def test_strip_comments_line(self):
        source = '-- ceci est un commentaire\n{ name = "foo" }'
        cleaned = strip_comments(source)
        assert "commentaire" not in cleaned
        assert "foo" in cleaned

    def test_strip_comments_block(self):
        source = '--[[bloc\ncommentaire]]\n{ name = "bar" }'
        cleaned = strip_comments(source)
        assert "bloc" not in cleaned

    def test_extract_data_extend_single(self):
        source = 'data:extend({ {type="item", name="foo"} })'
        blocks = extract_data_extend_blocks(source)
        assert len(blocks) == 1

    def test_extract_data_extend_multiple(self):
        source = (
            'data:extend({ {type="item", name="a"} })\n'
            'data:extend({ {type="item", name="b"} })'
        )
        blocks = extract_data_extend_blocks(source)
        assert len(blocks) == 2

    def test_parse_lua_file(self, tmp_path):
        lua_content = '''
        data:extend({
          {
            type = "item",
            name = "iron-plate",
            stack_size = 100,
          },
          {
            type = "item",
            name = "copper-plate",
            stack_size = 100,
          },
        })
        '''
        f = tmp_path / "items.lua"
        f.write_text(lua_content, encoding="utf-8")
        protos = parse_lua_file(f)
        assert len(protos) == 2
        names = {p["name"] for p in protos}
        assert "iron-plate" in names
        assert "copper-plate" in names


# ------------------------------------------------------------------ #
# PrototypeParser                                                        #
# ------------------------------------------------------------------ #

class TestPrototypeParser:

    def test_parse_raw_data_basic(self):
        raw = {
            "item": {
                "iron-plate": {"type": "item", "name": "iron-plate", "stack_size": 100},
                "copper-plate": {"type": "item", "name": "copper-plate", "stack_size": 100},
            },
            "recipe": {
                "iron-plate": {"type": "recipe", "name": "iron-plate"},
            },
        }
        parser = PrototypeParser()
        results = list(parser.parse_raw_data(raw))
        assert len(results) == 3
        typenames = {r["typename"] for r in results}
        assert typenames == {"item", "recipe"}

    def test_parse_skips_missing_name(self):
        raw = {
            "item": {
                "bad": {"type": "item"},  # pas de "name"
            }
        }
        parser = PrototypeParser()
        results = list(parser.parse_raw_data(raw))
        assert len(results) == 0
        assert parser.stats["rejected"] == 1

    def test_parse_many(self):
        protos = [
            {"type": "item",   "name": "iron-plate"},
            {"type": "recipe", "name": "iron-plate"},
            {"name": "no-type"},  # invalide
        ]
        parser = PrototypeParser()
        results = list(parser.parse_many(protos))
        assert len(results) == 2
        assert parser.stats["rejected"] == 1

    def test_coerce_string_bool(self):
        raw = {"item": {"x": {"type": "item", "name": "x", "enabled": "true"}}}
        parser = PrototypeParser()
        results = list(parser.parse_raw_data(raw))
        assert results[0]["data"]["enabled"] is True

    def test_coerce_string_number(self):
        raw = {"item": {"x": {"type": "item", "name": "x", "stack_size": "50"}}}
        parser = PrototypeParser()
        results = list(parser.parse_raw_data(raw))
        assert results[0]["data"]["stack_size"] == 50

    def test_skips_non_dict_values(self):
        raw = {"settings": "not-a-dict"}
        parser = PrototypeParser()
        results = list(parser.parse_raw_data(raw))
        assert len(results) == 0

    def test_stats_reset(self):
        parser = PrototypeParser()
        list(parser.parse_many([{"type": "item", "name": "x"}]))
        assert parser.stats["accepted"] == 1
        parser.reset_stats()
        assert parser.stats["accepted"] == 0

    def test_extract_localised_name_string(self):
        data = {"localised_name": "Iron Plate"}
        assert extract_localised_name(data) == "Iron Plate"

    def test_extract_localised_name_list(self):
        data = {"localised_name": ["item-name.iron-plate"]}
        assert extract_localised_name(data) == "item-name.iron-plate"

    def test_extract_localised_name_absent(self):
        assert extract_localised_name({}) is None


# ------------------------------------------------------------------ #
# InheritanceResolver                                                   #
# ------------------------------------------------------------------ #

class TestInheritanceResolver:

    @pytest.fixture
    def resolver(self):
        r = InheritanceResolver()
        r.build([
            {"name": "PrototypeBase",       "parent": None,              "typename": None,    "abstract": True,  "properties": [{"name": "name"}, {"name": "type"}]},
            {"name": "EntityPrototype",      "parent": "PrototypeBase",   "typename": None,    "abstract": True,  "properties": [{"name": "collision_box"}]},
            {"name": "EntityWithHealthPrototype", "parent": "EntityPrototype", "typename": None, "abstract": True, "properties": [{"name": "max_health"}]},
            {"name": "AssemblingMachinePrototype", "parent": "EntityWithHealthPrototype", "typename": "assembling-machine", "abstract": False, "properties": [{"name": "crafting_speed"}]},
            {"name": "RecipePrototype",      "parent": "PrototypeBase",   "typename": "recipe", "abstract": False, "properties": [{"name": "category"}]},
        ])
        return r

    def test_ancestors_direct(self, resolver):
        ancestors = resolver.ancestors("RecipePrototype")
        assert ancestors == ["PrototypeBase"]

    def test_ancestors_chain(self, resolver):
        ancestors = resolver.ancestors("AssemblingMachinePrototype")
        assert ancestors == [
            "EntityWithHealthPrototype",
            "EntityPrototype",
            "PrototypeBase",
        ]

    def test_ancestors_root_is_empty(self, resolver):
        assert resolver.ancestors("PrototypeBase") == []

    def test_descendants_direct(self, resolver):
        children = resolver.descendants("EntityPrototype", recursive=False)
        assert "EntityWithHealthPrototype" in children

    def test_descendants_recursive(self, resolver):
        desc = resolver.descendants("EntityPrototype", recursive=True)
        assert "AssemblingMachinePrototype" in desc

    def test_is_subtype_of(self, resolver):
        assert resolver.is_subtype_of("AssemblingMachinePrototype", "PrototypeBase")
        assert resolver.is_subtype_of("RecipePrototype", "PrototypeBase")
        assert not resolver.is_subtype_of("RecipePrototype", "EntityPrototype")

    def test_effective_properties(self, resolver):
        props = resolver.effective_properties("AssemblingMachinePrototype")
        prop_names = [p["name"] for p in props]
        # Propriétés propres
        assert "crafting_speed" in prop_names
        # Propriétés héritées
        assert "name" in prop_names
        assert "collision_box" in prop_names
        assert "max_health" in prop_names

    def test_effective_properties_own_not_inherited(self, resolver):
        props = resolver.effective_properties("AssemblingMachinePrototype")
        own = [p for p in props if p["name"] == "crafting_speed"]
        assert len(own) == 1
        assert own[0]["is_inherited"] is False

    def test_effective_properties_parent_is_inherited(self, resolver):
        props = resolver.effective_properties("AssemblingMachinePrototype")
        inherited = [p for p in props if p["name"] == "name"]
        assert len(inherited) == 1
        assert inherited[0]["is_inherited"] is True

    def test_roots(self, resolver):
        roots = resolver.roots()
        assert "PrototypeBase" in roots
        assert len(roots) == 1

    def test_depth(self, resolver):
        assert resolver.depth("PrototypeBase")            == 0
        assert resolver.depth("EntityPrototype")          == 1
        assert resolver.depth("AssemblingMachinePrototype") == 3

    def test_to_dict(self, resolver):
        d = resolver.to_dict()
        assert "RecipePrototype" in d
        assert d["RecipePrototype"]["parent"] == "PrototypeBase"
        assert isinstance(d["RecipePrototype"]["children"], list)