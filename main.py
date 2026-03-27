"""
main.py — Point d'entrée de Factorio Modding Hub
=================================================
Usage :
    python main.py sync --all
    python main.py sync --source api_docs
    python main.py sync --source raw_data
    python main.py sync --source github --version 2.0.65
    python main.py serve [--port 5000] [--no-browser] [--debug]
    python main.py status
    python main.py reset --confirm
"""

import argparse
import json
import os
import sys
import time
import webbrowser
from pathlib import Path
from threading import Timer

# ---------------------------------------------------------------------------
# Résolution des chemins projet
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Chargement de la configuration
# ---------------------------------------------------------------------------
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib 
    except ImportError:
        tomllib = None

DEFAULT_CONFIG = {
    "database": {
        "path": str(PROJECT_ROOT / "data" / "factorio_hub.db"),
    },
    "cache": {
        "dir": str(PROJECT_ROOT / "data" / "cache"),
    },
    "sources": {
        "gist_url": (
            "https://gist.githubusercontent.com/Bilka2/"
            "6b8a6a9e4a4ec779573ad703d03c1ae7/raw"
        ),
        "prototype_api_url": "https://lua-api.factorio.com/latest/prototype-api.json",
        "github_repo":       "wube/factorio-data",
        "github_token":      None,  # Surcharger dans settings.toml
    },
    "server": {
        "host":  "127.0.0.1",
        "port":  5000,
        "debug": False,
    },
}


def load_config() -> dict:
    """
    Charge settings.toml si présent, fusionne avec DEFAULT_CONFIG.
    Les clés de settings.toml ont priorité sur les défauts.
    """
    config = DEFAULT_CONFIG.copy()
    settings_path = PROJECT_ROOT / "config" / "settings.toml"

    if settings_path.exists() and tomllib is not None:
        with open(settings_path, "rb") as f:
            user_config = tomllib.load(f)
        # Fusion récursive superficielle (1 niveau de profondeur)
        for section, values in user_config.items():
            if section in config and isinstance(values, dict):
                config[section].update(values)
            else:
                config[section] = values
    elif settings_path.exists() and tomllib is None:
        print(
            "[config] Avertissement : settings.toml trouvé mais tomllib/tomli "
            "non installé. Utilisation des valeurs par défaut.\n"
            "         Installez tomli : pip install tomli"
        )

    # Résolution des chemins relatifs
    config["database"]["path"] = str(
        Path(config["database"]["path"]).expanduser().resolve()
    )
    config["cache"]["dir"] = str(
        Path(config["cache"]["dir"]).expanduser().resolve()
    )

    # Surcharge via variables d'environnement
    if token := os.environ.get("GITHUB_TOKEN"):
        config["sources"]["github_token"] = token

    return config


# ---------------------------------------------------------------------------
# Helpers d'affichage
# ---------------------------------------------------------------------------
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def _c(text: str, color: str) -> str:
    """Colorise le texte si stdout est un terminal."""
    if sys.stdout.isatty():
        return f"{color}{text}{RESET}"
    return text

def print_header():
    print()
    print(_c("╔══════════════════════════════════════╗", CYAN))
    print(_c("║   Factorio Modding Hub               ║", CYAN))
    print(_c("║   Centralisateur de prototypes       ║", CYAN))
    print(_c("╚══════════════════════════════════════╝", CYAN))
    print()

def print_ok(msg: str):
    print(_c(f"  ✓ {msg}", GREEN))

def print_warn(msg: str):
    print(_c(f"  ⚠ {msg}", YELLOW))

def print_err(msg: str):
    print(_c(f"  ✗ {msg}", RED), file=sys.stderr)

def print_step(msg: str):
    print(_c(f"\n▶ {msg}", BOLD))


# ---------------------------------------------------------------------------
# Commande : status
# ---------------------------------------------------------------------------
def cmd_status(config: dict):
    """Affiche l'état de la base de données et des caches."""
    print_step("État de la base de données")

    db_path = Path(config["database"]["path"])
    if not db_path.exists():
        print_warn("Base de données inexistante — lancez 'sync' pour initialiser.")
        return

    import sqlite3
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    # Taille du fichier DB
    size_mb = db_path.stat().st_size / (1024 * 1024)
    print_ok(f"Base : {db_path}  ({size_mb:.1f} MB)")

    # Versions synchronisées
    try:
        cur.execute(
            "SELECT version_tag, sources_synced, sync_date, is_latest "
            "FROM versions ORDER BY sync_date DESC"
        )
        rows = cur.fetchall()
        if rows:
            print(f"\n  {'Version':<15} {'Sources':<35} {'Date':<22} {'Latest'}")
            print("  " + "─" * 75)
            for tag, sources, date, latest in rows:
                mark = " ◄" if latest else ""
                print(f"  {tag:<15} {sources:<35} {date[:19]:<22}{mark}")
        else:
            print_warn("Aucune version synchronisée.")
    except sqlite3.OperationalError:
        print_warn("Tables manquantes — base non initialisée.")
        con.close()
        return

    # Compteurs
    print()
    tables = [
        ("prototype_types", "Types de prototypes"),
        ("prototypes",      "Prototypes (instances)"),
        ("type_properties", "Propriétés de schéma"),
        ("annotations",     "Annotations utilisateur"),
    ]
    for table, label in tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            count = cur.fetchone()[0]
            print_ok(f"{label:<30} {count:>6} lignes")
        except sqlite3.OperationalError:
            print_warn(f"{label:<30}   table absente")

    # Cache
    cache_dir = Path(config["cache"]["dir"])
    print(f"\n  Cache : {cache_dir}")
    for subdir in ["raw_data", "api_docs", "github"]:
        sub = cache_dir / subdir
        if sub.exists():
            files = list(sub.rglob("*"))
            size  = sum(f.stat().st_size for f in files if f.is_file())
            print_ok(f"  cache/{subdir:<12} {len(files):>4} fichiers  "
                     f"({size / 1024:.0f} KB)")
        else:
            print_warn(f"  cache/{subdir:<12} absent")

    con.close()


# ---------------------------------------------------------------------------
# Commande : sync
# ---------------------------------------------------------------------------
def cmd_sync(args, config: dict):
    """Orchestre la synchronisation des sources."""

    # Import différé pour ne pas ralentir --help
    try:
        from db.schema     import init_db
        from db.repository import Repository
        from core.sync_manager import SyncManager
    except ImportError as e:
        print_err(
            f"Module manquant : {e}\n"
            "  Assurez-vous d'avoir créé db/schema.py, db/repository.py "
            "et core/sync_manager.py"
        )
        sys.exit(1)

    db_path   = Path(config["database"]["path"])
    cache_dir = Path(config["cache"]["dir"])

    # Initialisation de la DB (idempotent)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    init_db(db_path)

    repo    = Repository(db_path)
    manager = SyncManager(repo, cache_dir, config)

    sources = _resolve_sources(args)

    t_start = time.time()

    for source in sources:
        if source == "api_docs":
            print_step("Synchronisation : prototype-api.json (schéma des types)")
            try:
                manager.sync_api_docs()
                print_ok("prototype-api.json importé avec succès.")
            except Exception as e:
                print_err(f"Échec api_docs : {e}")
                if args.fail_fast:
                    sys.exit(1)

        elif source == "raw_data":
            print_step("Synchronisation : data.raw JSON (instances vanilla)")
            try:
                manager.sync_raw_data()
                print_ok("data.raw importé avec succès.")
            except Exception as e:
                print_err(f"Échec raw_data : {e}")
                if args.fail_fast:
                    sys.exit(1)

        elif source == "github":
            version = args.version or _ask_github_version(manager, config)
            if not version:
                print_err("Version GitHub non spécifiée. "
                          "Utilisez --version <tag>")
                sys.exit(1)
            print_step(f"Synchronisation : GitHub wube/factorio-data @ {version}")
            try:
                token = config["sources"].get("github_token")
                if not token:
                    print_warn(
                        "Pas de token GitHub configuré. "
                        "Limite : 60 req/h (suffisant pour 1 version).\n"
                        "  Ajoutez github_token dans config/settings.toml "
                        "ou GITHUB_TOKEN en variable d'environnement."
                    )
                manager.sync_github(version, token=token)
                print_ok(f"GitHub {version} synchronisé.")
            except Exception as e:
                print_err(f"Échec github : {e}")
                if args.fail_fast:
                    sys.exit(1)

    elapsed = time.time() - t_start
    print()
    print_ok(f"Synchronisation terminée en {elapsed:.1f}s")
    repo.close()


def _resolve_sources(args) -> list[str]:
    """Détermine la liste de sources à synchroniser depuis les arguments CLI."""
    if getattr(args, "all", False):
        # Ordre important : schéma avant instances
        return ["api_docs", "raw_data", "github"]
    if getattr(args, "source", None):
        return [args.source]
    # Par défaut sans --source : les deux sources principales
    return ["api_docs", "raw_data"]


def _ask_github_version(manager, config: dict) -> str | None:
    """
    Si --version non fourni, propose les 10 derniers tags GitHub.
    Retourne le tag choisi ou None.
    """
    try:
        from scrapers.github_scraper import GitHubScraper
        token   = config["sources"].get("github_token")
        cache   = Path(config["cache"]["dir"])
        scraper = GitHubScraper(cache, token=token)
        print("  Récupération des versions disponibles...")
        versions = scraper.list_versions(limit=10)
    except Exception:
        return None

    print("\n  Versions disponibles :")
    for i, v in enumerate(versions, 1):
        print(f"    {i:>2}. {v}")
    print()
    choice = input("  Numéro de version (Entrée pour annuler) : ").strip()
    if not choice:
        return None
    try:
        return versions[int(choice) - 1]
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Commande : serve
# ---------------------------------------------------------------------------
def cmd_serve(args, config: dict):
    """Lance le serveur Flask."""
    try:
        from api.routes import create_app
    except ImportError as e:
        print_err(
            f"Module Flask manquant : {e}\n"
            "  Créez api/routes.py ou installez Flask : pip install flask"
        )
        sys.exit(1)

    db_path = Path(config["database"]["path"])
    if not db_path.exists():
        print_err(
            "Base de données introuvable.\n"
            "  Lancez d'abord : python main.py sync"
        )
        sys.exit(1)

    host  = args.host  or config["server"]["host"]
    port  = args.port  or config["server"]["port"]
    debug = args.debug or config["server"]["debug"]

    app = create_app(config)

    url = f"http://{host}:{port}"
    print_step(f"Démarrage du serveur sur {url}")
    print(_c(f"  Ctrl+C pour arrêter\n", YELLOW))

    if not getattr(args, "no_browser", False):
        # Ouvre le navigateur après 1.2s (le temps que Flask démarre)
        Timer(1.2, webbrowser.open, args=[url]).start()

    try:
        app.run(host=host, port=port, debug=debug, use_reloader=debug)
    except OSError as e:
        print_err(
            f"Impossible de démarrer sur le port {port} : {e}\n"
            f"  Essayez : python main.py serve --port {port + 1}"
        )
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n" + _c("  Serveur arrêté.", YELLOW))


# ---------------------------------------------------------------------------
# Commande : reset
# ---------------------------------------------------------------------------
def cmd_reset(args, config: dict):
    """Supprime la base de données et les caches (avec confirmation)."""
    if not getattr(args, "confirm", False):
        print_err(
            "Cette commande supprime TOUTES les données synchronisées.\n"
            "  Ajoutez --confirm pour confirmer."
        )
        sys.exit(1)

    db_path   = Path(config["database"]["path"])
    cache_dir = Path(config["cache"]["dir"])

    print_step("Reset de la base de données et des caches")

    if db_path.exists():
        db_path.unlink()
        print_ok(f"Base supprimée : {db_path}")
    else:
        print_warn("Base inexistante, rien à supprimer.")

    import shutil
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
        print_ok(f"Cache supprimé : {cache_dir}")
    else:
        print_warn("Cache inexistant, rien à supprimer.")

    print_ok("Reset terminé. Relancez 'sync' pour réinitialiser.")


# ---------------------------------------------------------------------------
# Construction du parser CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="factorio_hub",
        description="Factorio Modding Hub — Centralisateur de prototypes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples :
  python main.py sync                         # api_docs + raw_data (défaut)
  python main.py sync --all                   # toutes sources incl. GitHub
  python main.py sync --source api_docs       # schéma des types uniquement
  python main.py sync --source raw_data       # instances vanilla uniquement
  python main.py sync --source github --version 2.0.65
  python main.py serve                        # lance l'interface web
  python main.py serve --port 8080 --no-browser
  python main.py status                       # état de la DB
  python main.py reset --confirm              # remet à zéro
        """,
    )

    sub = parser.add_subparsers(dest="command", metavar="<commande>")

    # ── sync ──────────────────────────────────────────────────────────────
    p_sync = sub.add_parser("sync", help="Synchroniser les sources de données")
    src_group = p_sync.add_mutually_exclusive_group()
    src_group.add_argument(
        "--all",
        action="store_true",
        help="Synchronise toutes les sources (api_docs + raw_data + github)",
    )
    src_group.add_argument(
        "--source",
        choices=["api_docs", "raw_data", "github"],
        metavar="SOURCE",
        help="Source unique : api_docs | raw_data | github",
    )
    p_sync.add_argument(
        "--version",
        metavar="TAG",
        help="Tag de version GitHub (ex: 2.0.65). Requis avec --source github",
    )
    p_sync.add_argument(
        "--force",
        action="store_true",
        dest="force_refresh",
        help="Force le re-téléchargement même si le cache est valide",
    )
    p_sync.add_argument(
        "--fail-fast",
        action="store_true",
        help="Arrête au premier échec (par défaut : continue sur erreur)",
    )

    # ── serve ─────────────────────────────────────────────────────────────
    p_serve = sub.add_parser("serve", help="Lancer l'interface web")
    p_serve.add_argument(
        "--port", "-p",
        type=int,
        default=None,
        help="Port d'écoute (défaut : 5000 ou valeur dans settings.toml)",
    )
    p_serve.add_argument(
        "--host",
        default=None,
        help="Adresse d'écoute (défaut : 127.0.0.1)",
    )
    p_serve.add_argument(
        "--no-browser",
        action="store_true",
        help="Ne pas ouvrir le navigateur automatiquement",
    )
    p_serve.add_argument(
        "--debug",
        action="store_true",
        help="Mode debug Flask (rechargement automatique)",
    )

    # ── status ────────────────────────────────────────────────────────────
    sub.add_parser("status", help="Afficher l'état de la base de données")

    # ── reset ─────────────────────────────────────────────────────────────
    p_reset = sub.add_parser(
        "reset",
        help="Supprimer la base de données et les caches",
    )
    p_reset.add_argument(
        "--confirm",
        action="store_true",
        help="Confirmation obligatoire (protection contre les accidents)",
    )

    return parser


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------
def main():
    print_header()
    config = load_config()
    parser = build_parser()
    args   = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "sync":   lambda: cmd_sync(args, config),
        "serve":  lambda: cmd_serve(args, config),
        "status": lambda: cmd_status(config),
        "reset":  lambda: cmd_reset(args, config),
    }

    handler = dispatch.get(args.command)
    if handler:
        handler()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()