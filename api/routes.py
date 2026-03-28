"""
api/routes.py
=============
Endpoints Flask de Factorio Modding Hub.
Point d'entrée : create_app(config) → Flask app.
"""

import json
import logging
from pathlib import Path

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, jsonify, abort,
)

from db.schema     import init_db
from db.repository import Repository
from core.search_engine import SearchEngine
from core.diff_engine   import DiffEngine

logger = logging.getLogger("factorio_hub.routes")


def create_app(config: dict) -> Flask:
    """
    Factory Flask.
    Appelé par main.py cmd_serve().
    """
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent.parent / "ui" / "templates"),
        static_folder=str(Path(__file__).parent.parent / "ui" / "static"),
    )
    app.secret_key = "fmh-local-secret-not-for-prod"

    db_path = Path(config["database"]["path"])
    init_db(db_path)

    repo   = Repository(db_path)
    search = SearchEngine(repo)
    diff   = DiffEngine(repo)

    # ------------------------------------------------------------------ #
    # Context processor — données injectées dans tous les templates       #
    # ------------------------------------------------------------------ #

    @app.context_processor
    def inject_globals():
        versions   = repo.get_all_versions()
        version_id = _get_version_id(request, repo, versions)
        return {
            "versions":        versions,
            "version_id":      version_id,
            "db_version":      versions[0]["version_tag"] if versions else None,
            "current_version_tag": _version_tag_from_id(version_id, versions),
        }

    # ------------------------------------------------------------------ #
    # Routes principales                                                   #
    # ------------------------------------------------------------------ #

    @app.route("/")
    def index():
        return redirect(url_for("search_page"))

    @app.route("/search")
    def search_page():
        versions   = repo.get_all_versions()
        version_id = _get_version_id(request, repo, versions)

        q           = request.args.get("q", "").strip()
        typename    = request.args.get("typename", "").strip() or None
        page        = max(1, int(request.args.get("page", 1)))
        typenames   = search.get_typenames(version_id)

        if q or typename:
            result = search.search(
                query=q,
                version_id=version_id,
                typename=typename,
                page=page,
            )
            return render_template(
                "search.html",
                query=q,
                results=result["results"],
                total=result["total"],
                page=result["page"],
                pages=result["pages"],
                current_typename=typename,
                typenames=typenames,
            )
        else:
            # Page d'accueil — grille enrichie
            type_cards = _build_type_cards(repo, version_id, typenames)
            return render_template(
                "search.html",
                query="",
                typenames=typenames,
                type_cards=type_cards,
                current_typename=None,
            )

    @app.route("/prototype/<typename>/<name>")
    def prototype_detail(typename: str, name: str):
        versions   = repo.get_all_versions()
        version_id = _get_version_id(request, repo, versions)

        if not version_id:
            flash("Aucune version synchronisée. Lancez 'sync' d'abord.", "error")
            return redirect(url_for("search_page"))

        prototype = repo.get_prototype(typename, name, version_id)
        if not prototype:
            abort(404)

        # Infos de type (schéma)
        type_info  = repo.get_type_by_typename(typename, version_id)
        type_props = []
        type_ancestors = []
        type_children  = []

        if type_info:
            type_ancestors = repo.get_type_ancestors(type_info["id"])
            type_children  = repo.get_type_children(type_info["id"])
            type_props     = repo.get_type_properties(type_info["id"])

        # Propriétés du prototype enrichies avec le schéma
        raw          = prototype["raw_json"]
        schema_index = {p["name"]: p for p in type_props}
        properties   = _build_property_list(raw, schema_index)

        # Relations
        relations_from = repo.get_relations_from(typename, name, version_id)
        relations_to   = repo.get_relations_to(name, version_id)

        # Annotations
        current_tag  = _version_tag_from_id(version_id, versions)
        annotations  = repo.get_annotations(typename, name, current_tag)

        return render_template(
            "prototype_detail.html",
            prototype=prototype,
            raw_json=json.dumps(raw, indent=2, ensure_ascii=False),
            type_info=type_info,
            type_ancestors=type_ancestors,
            type_children=type_children,
            properties=properties,
            relations_from=relations_from,
            relations_to=relations_to,
            annotations=annotations,
        )

    @app.route("/compare")
    def compare_page():
        versions   = repo.get_all_versions()
        typenames  = search.get_typenames()

        typename  = request.args.get("typename", "").strip() or None
        name      = request.args.get("name", "").strip()     or None
        version_a = request.args.get("va", "").strip()       or None
        version_b = request.args.get("vb", "").strip()       or None

        diff_result = None

        if typename and name and version_a and version_b:
            raw_diff = diff.diff_prototype(typename, name, version_a, version_b)
            diff_result = diff.to_dict(raw_diff)

        return render_template(
            "compare.html",
            typename=typename,
            name=name,
            version_a=version_a,
            version_b=version_b,
            versions=versions,
            typenames=typenames,
            diff=diff_result,
        )

    @app.route("/status")
    def status_page():
        from db.schema import get_db_info
        info = get_db_info(db_path)
        return render_template("status.html", info=info)

    # ------------------------------------------------------------------ #
    # Annotations                                                          #
    # ------------------------------------------------------------------ #

    @app.route("/annotate", methods=["POST"])
    def save_annotation():
        typename   = request.form.get("typename", "")
        proto_name = request.form.get("proto_name", "")
        content    = request.form.get("content", "").strip()
        tags_raw   = request.form.get("tags", "")
        version_tag = request.form.get("version_tag")

        if not content:
            flash("L'annotation ne peut pas être vide.", "error")
            return redirect(request.referrer or url_for("search_page"))

        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        repo.upsert_annotation(typename, proto_name, content, tags, version_tag)
        flash("Annotation enregistrée.", "success")
        return redirect(url_for("prototype_detail", typename=typename, name=proto_name))

    @app.route("/annotation/<int:annotation_id>/delete")
    def delete_annotation(annotation_id: int):
        # Récupère typename/name pour la redirection
        with repo._conn() as con:
            row = con.execute(
                "SELECT typename, proto_name FROM annotations WHERE id = ?",
                (annotation_id,),
            ).fetchone()
        if row:
            repo.delete_annotation(annotation_id)
            flash("Annotation supprimée.", "success")
            return redirect(url_for(
                "prototype_detail",
                typename=row["typename"],
                name=row["proto_name"],
            ))
        abort(404)

    # ------------------------------------------------------------------ #
    # API JSON (autocomplete, etc.)                                        #
    # ------------------------------------------------------------------ #

    @app.route("/api/autocomplete")
    def api_autocomplete():
        q          = request.args.get("q", "").strip()
        versions   = repo.get_all_versions()
        version_id = _get_version_id(request, repo, versions)
        results    = search.autocomplete(q, version_id, limit=12)
        return jsonify(results)

    @app.route("/api/prototype/<typename>/<name>")
    def api_prototype(typename: str, name: str):
        versions   = repo.get_all_versions()
        version_id = _get_version_id(request, repo, versions)
        prototype  = repo.get_prototype(typename, name, version_id)
        if not prototype:
            return jsonify({"error": "not found"}), 404
        return jsonify(prototype)

    # ------------------------------------------------------------------ #
    # Erreurs                                                              #
    # ------------------------------------------------------------------ #

    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html"), 404

    return app


# ------------------------------------------------------------------ #
# Helpers                                                              #
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

    # Comptage par typename
    with repo._conn() as con:
        rows = con.execute(
            "SELECT typename, COUNT(*) as cnt FROM prototypes "
            "WHERE version_id = ? GROUP BY typename",
            (version_id,),
        ).fetchall()
    counts = {r["typename"]: r["cnt"] for r in rows}

    # Descriptions depuis prototype_types
    with repo._conn() as con:
        rows = con.execute(
            "SELECT typename, description FROM prototype_types "
            "WHERE version_id = ? AND typename IS NOT NULL",
            (version_id,),
        ).fetchall()
    descriptions = {r["typename"]: r["description"] for r in rows}

    # Assignation des catégories
    assigned = {}
    for category, types in _TYPE_CATEGORIES.items():
        if category == "Autres":
            continue
        for t in types:
            assigned[t] = category

    # Construction des cards groupées
    groups = {cat: [] for cat in _TYPE_CATEGORIES}
    for typename in typenames:
        category = assigned.get(typename, "Autres")
        desc = descriptions.get(typename, "")
        # Tronque la description
        if desc and len(desc) > 80:
            desc = desc[:77] + "..."
        groups[category].append({
            "typename":    typename,
            "count":       counts.get(typename, 0),
            "description": desc,
            "category":    category,
        })

    # Retourne dans l'ordre des catégories
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

    # Propriétés du schéma non présentes dans raw → affichées quand même
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

    # Propriétés de schéma absentes du prototype (valeurs par défaut implicites)
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