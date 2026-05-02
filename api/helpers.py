import json
from pathlib import Path
from db.repository import Repository

# ------------------------------------------------------------------ #
# Helpers                                                            #
# ------------------------------------------------------------------ #

# Catégories et ordre logique pour la page d'accueil
_TYPE_CATEGORIES = {
    "Items & Fluides": [
        "item", "fluid", "capsule", "ammo", "armor", "gun", "tool",
        "item-with-entity-data", "selection-tool", "copy-paste-tool",
        "deconstruction-item", "upgrade-item", "blueprint", "blueprint-book",
        "item-group", "item-subgroup", "fuel-category",
    ],
    "Recettes & Crafting": [
        "recipe", "recipe-category", "module", "module-category",
    ],
    "Entités": [
        "assembling-machine", "furnace", "mining-drill", "boiler", "generator",
        "electric-pole", "transport-belt", "inserter", "container",
        "logistic-container", "storage-tank", "pipe", "pump", "offshore-pump",
        "reactor", "heat-pipe", "accumulator", "solar-panel", "beacon",
        "lab", "radar", "roboport", "gate", "wall", "turret",
        "ammo-turret", "electric-turret", "fluid-turret", "artillery-turret",
        "car", "locomotive", "cargo-wagon", "fluid-wagon", "artillery-wagon",
        "spider-vehicle", "character", "combat-robot", "construction-robot",
        "logistic-robot", "land-mine", "cliff", "fish", "tree",
        "simple-entity", "resource", "market", "lamp",
    ],
    "Technologie": [
        "technology", "tool",
    ],
    "Signaux & Combinateurs": [
        "virtual-signal", "constant-combinator", "arithmetic-combinator",
        "decider-combinator", "display-panel",
    ],
    "Équipement": [
        "equipment-grid", "equipment-category", "battery-equipment",
        "active-defense-equipment", "belt-immunity-equipment",
        "energy-shield-equipment", "generator-equipment",
        "inventory-bonus-equipment", "movement-bonus-equipment",
        "night-vision-equipment", "roboport-equipment",
    ],
    "Achievements": [
        "achievement", "build-entity-achievement", "combat-robot-count-achievement",
        "construct-with-robots-achievement", "deconstruct-with-robots-achievement",
        "deliver-by-robots-achievement", "dont-build-entity-achievement",
        "dont-craft-manually-achievement", "dont-kill-manually-achievement",
        "kill-achievement", "research-achievement", "produce-achievement",
        "produce-per-hour-achievement", "train-path-achievement",
    ],
    "Sons & Visuels": [
        "ambient-sound", "font", "gui-style", "mouse-cursor",
        "noise-expression", "noise-function", "optimized-decorative",
        "optimized-particle", "particle-source", "tile", "tile-effect",
    ],
    "Autres": [],  # catch-all
}


def _build_type_cards(repo, version_id: int | None, typenames: list[str]) -> list[dict]:
    """
    Construit la liste enrichie des types pour la page d'accueil.
    Chaque entrée : {typename, count, description, category}
    """
    if not version_id:
        return [{"typename": t, "count": 0, "description": "", "category": "Autres"}
                for t in typenames]

    with repo._conn() as con:
        rows = con.execute(
            "SELECT typename, COUNT(*) as cnt FROM prototypes "
            "WHERE version_id = ? GROUP BY typename",
            (version_id,),
        ).fetchall()
    counts = {r["typename"]: r["cnt"] for r in rows}

    with repo._conn() as con:
        rows = con.execute(
            "SELECT typename, description FROM prototype_types "
            "WHERE version_id = ? AND typename IS NOT NULL",
            (version_id,),
        ).fetchall()
    descriptions = {r["typename"]: r["description"] for r in rows}

    assigned = {}
    for category, types in _TYPE_CATEGORIES.items():
        if category == "Autres":
            continue
        for t in types:
            assigned[t] = category

    groups = {cat: [] for cat in _TYPE_CATEGORIES}
    for typename in typenames:
        category = assigned.get(typename, "Autres")
        desc = descriptions.get(typename, "")
        if desc and len(desc) > 80:
            desc = desc[:77] + "..."
        groups[category].append({
            "typename":    typename,
            "count":       counts.get(typename, 0),
            "description": desc,
            "category":    category,
        })

    result = []
    for category, cards in groups.items():
        if cards:
            result.append({
                "category": category,
                "cards":    sorted(cards, key=lambda c: c["typename"]),
            })

    return result

def _get_version_id(req, repo: Repository, versions: list) -> int | None:
    """
    Détermine le version_id à utiliser pour la requête courante.
    Priorité : ?v=<id> dans l'URL > version marquée is_latest > première version.
    """
    v_param = req.args.get("v")
    if v_param:
        try:
            return int(v_param)
        except ValueError:
            pass

    if not versions:
        return None

    latest = next((v for v in versions if v["is_latest"]), None)
    return (latest or versions[0])["id"]


def _version_tag_from_id(version_id: int | None, versions: list) -> str | None:
    if version_id is None:
        return None
    for v in versions:
        if v["id"] == version_id:
            return v["version_tag"]
    return None


def _build_property_list(raw: dict, schema_index: dict) -> list[dict]:
    """
    Construit la liste des propriétés pour le template prototype_detail.
    Fusionne les valeurs réelles (raw_json) avec le schéma officiel.
    """
    properties = []

    schema_only_keys = set(schema_index.keys()) - set(raw.keys())

    for key, value in sorted(raw.items()):
        schema = schema_index.get(key)
        is_table = isinstance(value, (dict, list))

        prop = {
            "key":           key,
            "value_text":    json.dumps(value, ensure_ascii=False, indent=2)
                             if is_table else str(value),
            "value_type":    _value_type(value),
            "value_preview": _preview(value),
            "is_table":      is_table,
            "is_reference":  _is_reference_key(key, value),
            "ref_typename":  _guess_ref_typename(key),
            "schema":        schema,
        }
        properties.append(prop)

    for key in sorted(schema_only_keys):
        schema = schema_index[key]
        if schema.get("is_optional"):
            properties.append({
                "key":          key,
                "value_text":   schema.get("default_value") or "—",
                "value_type":   "nil",
                "value_preview": "",
                "is_table":     False,
                "is_reference": False,
                "ref_typename": None,
                "schema":       schema,
            })

    return properties


def _value_type(v) -> str:
    if v is None:        return "nil"
    if isinstance(v, bool):   return "bool"
    if isinstance(v, (int, float)): return "number"
    if isinstance(v, str):   return "string"
    return "table"


def _preview(v) -> str:
    """Résumé court d'une valeur complexe pour l'affichage inline."""
    if isinstance(v, dict):
        return f"{len(v)} clé{'s' if len(v) > 1 else ''}"
    if isinstance(v, list):
        return f"{len(v)} élément{'s' if len(v) > 1 else ''}"
    return ""


def _is_reference_key(key: str, value) -> bool:
    """Heuristique : si la clé se termine par _name ou est 'result', c'est une référence."""
    if not isinstance(value, str):
        return False
    reference_keys = {
        "result", "minable", "item",
    }
    return (
        key in reference_keys
        or key.endswith("_name")
        or key.endswith("_item")
    )


def _guess_ref_typename(key: str) -> str | None:
    """Devine le typename cible d'une référence à partir du nom de la clé."""
    mappings = {
        "subgroup":         "item-subgroup",
        "item_group":       "item-group",
        "equipment_grid":   "equipment-grid",
        "fuel_category":    "fuel-category",
        "ammo_category":    "ammo-category",
        "module_category":  "module-category",
    }
    return mappings.get(key)

_CATEGORY_ICONS = {
    "Items & Fluides":        "◈",
    "Recettes & Crafting":    "⚙",
    "Entités":                "⬡",
    "Technologie":            "⬡",
    "Signaux & Combinateurs": "⟨⟩",
    "Équipement":             "▣",
    "Achievements":           "★",
    "Sons & Visuels":         "◉",
    "Autres":                 "•",
}
 
 
def _build_type_groups(repo, version_id, typenames):
    """
    Comme _build_type_cards mais retourne la liste avec icônes,
    pour la homepage index.html.
    """
    cards_data = _build_type_cards(repo, version_id, typenames)
    result = []
    for group in cards_data:
        cat = group["category"]
        result.append({
            "category": cat,
            "icon":     _CATEGORY_ICONS.get(cat, "•"),
            "cards":    group["cards"],
        })
    return result
 
 
def _build_stats(repo, version_id, versions):
    """Stats globales pour le hero de la homepage."""
    if not version_id:
        return None
    with repo._conn() as con:
        proto_count = con.execute(
            "SELECT COUNT(*) FROM prototypes WHERE version_id = ?",
            (version_id,),
        ).fetchone()[0]
        type_count = con.execute(
            "SELECT COUNT(DISTINCT typename) FROM prototypes WHERE version_id = ?",
            (version_id,),
        ).fetchone()[0]
    version_tag = _version_tag_from_id(version_id, versions)
    return {
        "proto_count": proto_count,
        "type_count":  type_count,
        "version_tag": version_tag,
    }
    
def _persist_language(lang: str, config: dict) -> None:
    """Écrit la langue dans config/settings.toml."""
    import tomllib as _tomllib
    settings_path = Path(__file__).parent.parent / "config" / "settings.toml"
 
    if settings_path.exists():
        try:
            import tomllib
            with open(settings_path, "rb") as f:
                current = tomllib.load(f)
        except Exception:
            current = {}
    else:
        current = {}
 
    if "ui" not in current:
        current["ui"] = {}
    current["ui"]["language"] = lang
 
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    _write_toml(settings_path, current)
 
 
def _write_toml(path: Path, data: dict) -> None:
    """Sérialise un dict simple en TOML (1 niveau de section)."""
    lines = []
    for k, v in data.items():
        if not isinstance(v, dict):
            lines.append(f'{k} = {_toml_value(v)}')
    for section, values in data.items():
        if isinstance(values, dict):
            lines.append(f'\n[{section}]')
            for k, v in values.items():
                lines.append(f'{k} = {_toml_value(v)}')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
 
 
def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return f'"{v}"'

def _get_mod_version_id(mod: dict, repo) -> int | None:
    """Retourne le version_id DB associé à un mod."""
    version_tag = f"mod:{mod['name']}:{mod['mod_version']}"
    return repo.get_version_id(version_tag)
 
def _compute_mod_diff(
    repo, diff_engine,
    vid_a: int, vid_b: int,
    version_a: str, version_b: str,
    typename_filter: str | None,
    mod_name: str,
) -> tuple[list[dict], dict]:
    """
    Compare tous les prototypes entre deux versions d'un mod.
    Retourne (diffs, summary).
    """
    # Prototypes de chaque version
    with repo._conn() as con:
        q_filter = "AND typename = ?" if typename_filter else ""
 
        def get_names(vid):
            params = [vid]
            if typename_filter:
                params.append(typename_filter)
            rows = con.execute(
                f"SELECT typename, name FROM prototypes "
                f"WHERE version_id = ? {q_filter} ORDER BY typename, name",
                params,
            ).fetchall()
            return {(r["typename"], r["name"]) for r in rows}
 
        protos_a = get_names(vid_a)
        protos_b = get_names(vid_b)
 
    added_keys   = protos_b - protos_a
    removed_keys = protos_a - protos_b
    common_keys  = protos_a & protos_b
 
    diffs = []
 
    # Prototypes ajoutés
    for typename, name in sorted(added_keys):
        diffs.append({
            "change_type": "added",
            "typename":    typename,
            "name":        name,
            "summary":     f"Nouveau dans v{version_b}",
            "added":       [],
            "removed":     [],
            "modified":    [],
        })
 
    # Prototypes supprimés
    for typename, name in sorted(removed_keys):
        diffs.append({
            "change_type": "removed",
            "typename":    typename,
            "name":        name,
            "summary":     f"Supprimé dans v{version_b}",
            "added":       [],
            "removed":     [],
            "modified":    [],
        })
 
    # Prototypes communs — diff des propriétés
    for typename, name in sorted(common_keys):
        tag_a = f"mod:{mod_name}:{version_a}"
        tag_b = f"mod:{mod_name}:{version_b}"

        raw_diff = diff_engine.diff_prototype(typename, name, tag_a, tag_b)
        d = diff_engine.to_dict(raw_diff)
 
        if not raw_diff.has_changes:
            continue
 
        diffs.append({
            "change_type": "modified",
            "typename":    typename,
            "name":        name,
            "summary":     d["summary"],
            "added":       d["added"],
            "removed":     d["removed"],
            "modified":    d["modified"],
        })
 
    summary = {
        "added":     len(added_keys),
        "removed":   len(removed_keys),
        "modified":  sum(1 for d in diffs if d["change_type"] == "modified"),
        "unchanged": len(common_keys) - sum(1 for d in diffs if d["change_type"] == "modified"),
    }
 
    return diffs, summary