"""
core/i18n.py
============
Système de traduction simple et extensible.

Fonctionnement :
- Les traductions sont dans i18n/<lang>.json
- Langue par défaut : "en" (configurable dans settings.toml → [ui] language)
- Langue active stockée en mémoire, modifiable via set_language()
- Accès via t("key") ou t("section.key")
- Fallback : si clé absente dans la langue active → cherche en "en" → retourne la clé

Ajouter une langue :
  1. Créer i18n/xx.json (copier en.json comme base)
  2. Traduire les valeurs
  3. Changer [ui] language = "xx" dans settings.toml
  → Aucune modification de code nécessaire
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger("factorio_hub.i18n")

# Répertoire des fichiers de traduction
I18N_DIR = Path(__file__).parent.parent / "i18n"

# Langue active en mémoire (modifiable via set_language)
_current_lang: str = "en"
_translations: dict[str, dict] = {}   # cache {lang: {key: value}}


# ------------------------------------------------------------------ #
# Chargement                                                           #
# ------------------------------------------------------------------ #

def load_language(lang: str) -> dict:
    """
    Charge et met en cache le fichier i18n/<lang>.json.
    Retourne le dict des traductions.
    """
    if lang in _translations:
        return _translations[lang]

    path = I18N_DIR / f"{lang}.json"
    if not path.exists():
        logger.warning("Fichier de traduction introuvable : %s", path)
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _translations[lang] = data
        logger.info("Langue chargée : %s (%d clés)", lang, _count_keys(data))
        return data
    except json.JSONDecodeError as e:
        logger.error("Erreur JSON dans %s : %s", path, e)
        return {}


def available_languages() -> list[dict]:
    """
    Retourne la liste des langues disponibles (fichiers i18n/*.json).
    Chaque entrée : {code, name, native_name}
    Le nom est lu depuis la clé "meta.name" et "meta.native_name" du fichier.
    """
    langs = []
    for path in sorted(I18N_DIR.glob("*.json")):
        code = path.stem
        data = load_language(code)
        meta = data.get("meta", {})
        langs.append({
            "code":        code,
            "name":        meta.get("name", code.upper()),
            "native_name": meta.get("native_name", code.upper()),
            "flag":        meta.get("flag", ""),
        })
    return langs


# ------------------------------------------------------------------ #
# Langue active                                                        #
# ------------------------------------------------------------------ #

def set_language(lang: str) -> bool:
    """
    Change la langue active.
    Retourne True si la langue existe, False sinon.
    """
    global _current_lang
    path = I18N_DIR / f"{lang}.json"
    if not path.exists():
        logger.warning("Langue inconnue : %s", lang)
        return False
    _current_lang = lang
    load_language(lang)   # précharge en cache
    logger.info("Langue active : %s", lang)
    return True


def get_language() -> str:
    return _current_lang


def init_from_config(config: dict) -> None:
    """
    Initialise la langue depuis la config (settings.toml → [ui] language).
    À appeler au démarrage dans main.py.
    """
    lang = config.get("ui", {}).get("language", "en")
    set_language(lang)
    # Précharge aussi l'anglais pour le fallback
    if lang != "en":
        load_language("en")


# ------------------------------------------------------------------ #
# Traduction                                                           #
# ------------------------------------------------------------------ #

def t(key: str, **kwargs) -> str:
    """
    Traduit une clé dans la langue active.
    Supporte les clés imbriquées avec "." : t("nav.search") → translations["nav"]["search"]
    Supporte les variables : t("sync.imported", count=42) → "42 prototypes imported"
    Fallback : langue active → anglais → clé brute
    """
    value = _resolve(key, _current_lang) or _resolve(key, "en") or key

    # Substitution des variables {count}, {version}, etc.
    if kwargs:
        try:
            value = value.format(**kwargs)
        except (KeyError, ValueError):
            pass

    return value


def _resolve(key: str, lang: str) -> str | None:
    """Résout une clé pointée dans un dict de traductions."""
    data = load_language(lang)
    if not data:
        return None

    parts = key.split(".")
    current = data
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None

    return str(current) if not isinstance(current, dict) else None


def _count_keys(data: dict, prefix: str = "") -> int:
    """Compte récursivement le nombre de clés feuilles."""
    count = 0
    for k, v in data.items():
        if isinstance(v, dict):
            count += _count_keys(v, f"{prefix}.{k}")
        else:
            count += 1
    return count


# ------------------------------------------------------------------ #
# Intégration Flask                                                    #
# ------------------------------------------------------------------ #

def init_flask(app) -> None:
    """
    Enregistre le filtre Jinja {{ "key" | t }} et la fonction globale t().
    À appeler dans create_app() après avoir créé l'app Flask.
    """
    # Filtre : {{ "nav.search" | t }}
    app.jinja_env.filters["t"] = lambda key, **kw: t(key, **kw)

    # Fonction globale : {{ t("nav.search") }}
    app.jinja_env.globals["t"] = t

    # Langue active accessible dans tous les templates
    app.jinja_env.globals["get_lang"] = get_language
    app.jinja_env.globals["available_langs"] = available_languages

    logger.info("i18n Flask initialisé (langue: %s)", _current_lang)