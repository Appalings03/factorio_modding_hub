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
from core.i18n import t,init_flask, set_language, get_language, available_languages, t as _t

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
    
    from core.i18n import init_from_config, init_flask
    init_from_config(config)
    init_flask(app)

    db_path = Path(config["database"]["path"])
    init_db(db_path)

    repo   = Repository(db_path)
    search = SearchEngine(repo)
    diff   = DiffEngine(repo)

    # ------------------------------------------------------------------ #
    # Context processor — données injectées dans tous les templates      #
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
    # Routes principales                                                 #
    # ------------------------------------------------------------------ #

    @app.route("/")
    def index():
        versions   = repo.get_all_versions()
        version_id = _get_version_id(request, repo, versions)
        typenames  = search.get_typenames(version_id)
        type_groups = _build_type_groups(repo, version_id, typenames)
        stats      = _build_stats(repo, version_id, versions)
 
        return render_template(
            "index.html",
            type_groups=type_groups,
            stats=stats,
        )
    
    @app.route("/set-version", methods=["POST"])
    def set_default_version():
        """
        Marque une version comme is_latest en DB.
        Redirige vers l'index avec la nouvelle version active.
        """
        version_id_str = request.form.get("version_id", "")
        try:
            new_vid = int(version_id_str)
        except ValueError:
            flash("Version invalide.", "error")
            return redirect(url_for("index"))
 
        versions = repo.get_all_versions()
        target   = next((v for v in versions if v["id"] == new_vid), None)
        if not target:
            flash("Version introuvable.", "error")
            return redirect(url_for("index"))
 
        repo.set_latest_version(target["version_tag"])
        flash(f"Version active : {target['version_tag']}", "success")
        return redirect(url_for("index"))
    
    @app.route("/set-language", methods=["POST"])
    def set_language_route():
        """
        Change la langue active et la persiste dans settings.toml.
        """
        lang = request.form.get("lang", "en").strip()
        from core.i18n import set_language, available_languages
        langs = [l["code"] for l in available_languages()]
 
        if lang not in langs:
            flash(f"Langue inconnue : {lang}", "error")
            return redirect(request.referrer or url_for("index"))
 
        set_language(lang)
 
        _persist_language(lang, config)
 
        return redirect(request.referrer or url_for("index"))

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
    
    @app.route("/mods")
    def mods_page():
        mods = repo.get_all_mods()
        # Ajouter le comptage de prototypes pour chaque mod
        for mod in mods:
            mod["proto_count"] = repo.count_mod_prototypes(mod["id"])
        return render_template("mods.html", mods=mods)
 
    @app.route("/mods/<int:mod_id>/delete")
    def mods_delete(mod_id: int):
        mod = repo.get_mod(mod_id)
        if not mod:
            abort(404)
        repo.delete_mod(mod_id)
        flash(f"Mod '{mod['name']} v{mod['mod_version']}' supprimé.", "success")
        return redirect(url_for("mods_page"))
 
# ------------------------------------------------------------------ #
# MODS — import zip                                                  #
# ------------------------------------------------------------------ #
 
    @app.route("/mods/import", methods=["GET", "POST"])
    def mods_import():
        versions = repo.get_all_versions()
 
        if request.method == "POST":
            file = request.files.get("mod_file")
            if not file or file.filename == "":
                flash(t("mods.no_file_error"), "error")
                return redirect(url_for("mods_import"))
 
            from core.mod_importer import allowed_file, save_upload, ModImporter, ModImportError
 
            if not allowed_file(file.filename):
                flash(t("mods.invalid_file_error"), "error")
                return redirect(url_for("mods_import"))
 
            # Sauvegarde temporaire
            upload_dir = Path(config["cache"]["dir"]) / "mod_uploads"
            zip_path   = save_upload(file, upload_dir)
 
            # Version Factorio choisie
            game_version = request.form.get("game_version") or None
 
            try:
                importer = ModImporter(repo, Path(config["cache"]["dir"]))
                result   = importer.import_zip(zip_path, game_version=game_version)
            except ModImportError as e:
                flash(str(e), "error")
                return redirect(url_for("mods_import"))
 
            return render_template("mods_import.html",
                                   versions=versions,
                                   import_result=result)
 
        return render_template("mods_import.html",
                               versions=versions,
                               import_result=None)
 
    # ------------------------------------------------------------------ #
    # MODS — détail (remplace le placeholder)                              #
    # ------------------------------------------------------------------ #
 
    @app.route("/mods/<int:mod_id>")
    def mods_detail(mod_id: int):
        mod = repo.get_mod(mod_id)
        if not mod:
            abort(404)
 
        page      = max(1, int(request.args.get("page", 1)))
        page_size = 100
        offset    = (page - 1) * page_size
 
        proto_count = repo.count_mod_prototypes(mod_id)
        prototypes  = repo.get_mod_prototypes(mod_id, limit=page_size, offset=offset)
        pages       = max(1, (proto_count + page_size - 1) // page_size)
 
        # Enrichir avec flag is_merged
        for proto in prototypes:
            raw = {}
            try:
                import json as _json
                p = repo.get_prototype(proto["typename"], proto["name"],
                                       _get_mod_version_id(mod, repo))
                if p:
                    raw = p.get("raw_json", {})
            except Exception:
                pass
            proto["is_merged"] = raw.get("_merged_from_vanilla", False)
 
        # Comptage par type
        type_counts = {}
        for p in repo.get_mod_prototypes(mod_id, limit=9999):
            type_counts[p["typename"]] = type_counts.get(p["typename"], 0) + 1
        typenames = sorted(type_counts.keys())
 
        return render_template(
            "mods_detail.html",
            mod=mod,
            prototypes=prototypes,
            proto_count=proto_count,
            typenames=typenames,
            type_counts=type_counts,
            page=page,
            pages=pages,
        )
 
    @app.route("/mods/<int:mod_id>/proto/<typename>/<name>")
    def mods_proto_detail(mod_id: int, typename: str, name: str):
        """Détail d'un prototype de mod — réutilise prototype_detail.html."""
        mod = repo.get_mod(mod_id)
        if not mod:
            abort(404)
        version_id = _get_mod_version_id(mod, repo)
        prototype  = repo.get_prototype(typename, name, version_id)
        if not prototype:
            abort(404)
 
        type_info      = repo.get_type_by_typename(typename, version_id)
        type_props     = []
        type_ancestors = []
        type_children  = []
        if type_info:
            type_ancestors = repo.get_type_ancestors(type_info["id"])
            type_children  = repo.get_type_children(type_info["id"])
            type_props     = repo.get_type_properties(type_info["id"])
 
        import json as _json
        raw          = prototype["raw_json"]
        schema_index = {p["name"]: p for p in type_props}
        properties   = _build_property_list(raw, schema_index)
 
        versions        = repo.get_all_versions()
        current_tag     = f"mod:{mod['name']}:{mod['mod_version']}"
 
        return render_template(
            "prototype_detail.html",
            prototype=prototype,
            raw_json=_json.dumps(raw, indent=2, ensure_ascii=False),
            type_info=type_info,
            type_ancestors=type_ancestors,
            type_children=type_children,
            properties=properties,
            relations_from=[],
            relations_to=[],
            annotations=[],
        )
 
    # ------------------------------------------------------------------ #
    # MODS — validation                                                  #
    # ------------------------------------------------------------------ #
 
    @app.route("/mods/<int:mod_id>/validate", methods=["GET", "POST"])
    def mods_validate(mod_id: int):
        from core.validator import PrototypeValidator, summarize_results
 
        mod      = repo.get_mod(mod_id)
        if not mod:
            abort(404)
 
        versions = repo.get_all_versions()
        results  = None
        summary  = None
 
        if request.method == "POST":
            game_version = request.form.get("game_version") or mod.get("game_version")
            if not game_version:
                flash(t("mods.validate_no_version"), "error")
                return redirect(url_for("mods_validate", mod_id=mod_id))
 
            validator = PrototypeValidator(repo, game_version=game_version)
            raw_results = validator.validate_mod(mod_id)
 
            # Marquer comme validé en DB
            repo.mark_mod_validated(mod_id)
 
            # Sérialiser pour le template
            results = [r.to_dict() for r in raw_results]
            summary = summarize_results(raw_results)
 
        return render_template(
            "mods_validate.html",
            mod=mod,
            versions=versions,
            results=results,
            summary=summary,
        )
 
    # ------------------------------------------------------------------ #
    # MODS — enregistrement permanent                                    #
    # ------------------------------------------------------------------ #
 
    @app.route("/mods/<int:mod_id>/save", methods=["POST"])
    def mods_save_permanent(mod_id: int):
        """
        Marque le mod comme permanent après validation.
        Dans notre architecture, le mod est déjà en DB —
        cette route sert juste à confirmer et rediriger.
        """
        mod = repo.get_mod(mod_id)
        if not mod:
            abort(404)
 
        repo.mark_mod_validated(mod_id)
        flash(
            t("mods.val_saved", name=mod["name"], version=mod["mod_version"]),
            "success"
        )
        return redirect(url_for("mods_detail", mod_id=mod_id))
 
    @app.route("/mods/compare/<mod_name>")
    def mods_compare_select(mod_name: str):
        versions = repo.get_mods_by_name(mod_name)
        return render_template("mods_compare.html", mod_name=mod_name,
                               versions=versions, diff=None)
 
    # ------------------------------------------------------------------ #
    # Annotations                                                        #
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
    # API JSON (autocomplete, etc.)                                      #
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
    # Erreurs                                                            #
    # ------------------------------------------------------------------ #

    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html"), 404

    return app


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