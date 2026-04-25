"""
main.py — Point d'entrée de Factorio Modding Hub
=================================================
Usage :
    python main.py sync --all
    python main.py sync --source api_docs
    python main.py sync --source raw_data [--version 2.0.76]
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
        "github_token":      None,
    },
    "server": {
        "host":  "127.0.0.1",
        "port":  5000,
        "debug": False,
    },
    "ui": {
        "language": "en",
    },
}


def load_config() -> dict:
    config = DEFAULT_CONFIG.copy()
    # Copie profonde des sous-dicts
    config = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_CONFIG.items()}

    settings_path = PROJECT_ROOT / "config" / "settings.toml"

    if settings_path.exists() and tomllib is not None:
        with open(settings_path, "rb") as f:
            user_config = tomllib.load(f)
        for section, values in user_config.items():
            if section in config and isinstance(values, dict):
                config[section].update(values)
            else:
                config[section] = values
    elif settings_path.exists() and tomllib is None:
        print(
            "[config] Warning: settings.toml found but tomllib/tomli not installed.\n"
            "         Install tomli: pip install tomli"
        )

    config["database"]["path"] = str(
        Path(config["database"]["path"]).expanduser().resolve()
    )
    config["cache"]["dir"] = str(
        Path(config["cache"]["dir"]).expanduser().resolve()
    )

    if token := os.environ.get("GITHUB_TOKEN"):
        config["sources"]["github_token"] = token

    return config


# ---------------------------------------------------------------------------
# i18n CLI
# ---------------------------------------------------------------------------
def _init_i18n(config: dict):
    """Initialise le système i18n pour le CLI."""
    try:
        from core.i18n import init_from_config, t as _t
        init_from_config(config)
        return _t
    except ImportError:
        # Fallback si core/i18n.py absent
        return lambda key, **kw: key


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
    if sys.stdout.isatty():
        return f"{color}{text}{RESET}"
    return text


def print_header():
    print()
    print(_c("╔══════════════════════════════════════╗", CYAN))
    print(_c("║   Factorio Modding Hub               ║", CYAN))
    print(_c("║   Prototype Centralizer               ║", CYAN))
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
def cmd_status(config: dict, t):
    print_step(t("cli.status_title"))

    db_path = Path(config["database"]["path"])
    if not db_path.exists():
        print_warn(t("cli.serve_no_db"))
        return

    import sqlite3
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    size_mb = db_path.stat().st_size / (1024 * 1024)
    print_ok(f"Base : {db_path}  ({size_mb:.1f} MB)")

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
            print_warn(t("status.no_versions"))
    except sqlite3.OperationalError:
        print_warn(t("status.not_initialized"))
        con.close()
        return

    print()
    tables = [
        ("prototype_types", t("status.row_types")),
        ("prototypes",      t("status.row_prototypes")),
        ("type_properties", t("status.row_schema_props")),
        ("annotations",     t("status.row_annotations")),
    ]
    for table, label in tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            count = cur.fetchone()[0]
            print_ok(f"{label:<30} {count:>6} lignes")
        except sqlite3.OperationalError:
            print_warn(f"{label:<30}   table absente")

    cache_dir = Path(config["cache"]["dir"])
    print(f"\n  {t('status.cache_title')} : {cache_dir}")
    for subdir in ["raw_data", "api_docs", "github"]:
        sub = cache_dir / subdir
        if sub.exists():
            files = list(sub.rglob("*"))
            size  = sum(f.stat().st_size for f in files if f.is_file())
            print_ok(f"  cache/{subdir:<12} {len(files):>4} fichiers  ({size / 1024:.0f} KB)")
        else:
            print_warn(f"  cache/{subdir:<12} absent")

    con.close()


# ---------------------------------------------------------------------------
# Commande : sync
# ---------------------------------------------------------------------------
def cmd_sync(args, config: dict, t):
    try:
        from db.schema     import init_db
        from db.repository import Repository
        from core.sync_manager import SyncManager
    except ImportError as e:
        print_err(t("cli.module_missing", error=str(e)))
        sys.exit(1)

    db_path   = Path(config["database"]["path"])
    cache_dir = Path(config["cache"]["dir"])

    db_path.parent.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    init_db(db_path)

    repo    = Repository(db_path)
    manager = SyncManager(repo, cache_dir, config)

    sources = _resolve_sources(args)
    t_start = time.time()

    for source in sources:
        if source == "api_docs":
            print_step(t("cli.sync_api_docs"))
            try:
                manager.sync_api_docs()
                print_ok(t("cli.sync_ok_api"))
            except Exception as e:
                print_err(t("cli.sync_fail_api", error=str(e)))
                if args.fail_fast:
                    sys.exit(1)

        elif source == "raw_data":
            print_step(t("cli.sync_raw_data"))
            try:
                raw_version = getattr(args, "version", None)
                manager.sync_raw_data(version_tag=raw_version)
                print_ok(t("cli.sync_ok_raw"))
            except Exception as e:
                print_err(t("cli.sync_fail_raw", error=str(e)))
                if args.fail_fast:
                    sys.exit(1)

        elif source == "github":
            version = args.version or _ask_github_version(manager, config)
            if not version:
                print_err("Version GitHub non spécifiée. Utilisez --version <tag>")
                sys.exit(1)
            print_step(t("cli.sync_github", version=version))
            try:
                token = config["sources"].get("github_token")
                if not token:
                    print_warn(t("cli.no_token_warn"))
                    print_warn(t("cli.no_token_hint"))
                force = getattr(args, "force_refresh", False)
                manager.sync_github(version, token=token, force=force)
                print_ok(t("cli.sync_ok_github", version=version))
            except Exception as e:
                print_err(t("cli.sync_fail_github", error=str(e)))
                if args.fail_fast:
                    sys.exit(1)

    elapsed = time.time() - t_start
    print()
    print_ok(t("cli.sync_done", elapsed=f"{elapsed:.1f}"))
    repo.close()


def _resolve_sources(args) -> list[str]:
    if getattr(args, "all", False):
        return ["api_docs", "raw_data", "github"]
    if getattr(args, "source", None):
        return [args.source]
    return ["api_docs", "raw_data"]


def _ask_github_version(manager, config: dict) -> str | None:
    try:
        from scrapers.github_scraper import GitHubScraper
        token   = config["sources"].get("github_token")
        cache   = Path(config["cache"]["dir"])
        scraper = GitHubScraper(cache, token=token)
        print("  Fetching available versions...")
        versions = scraper.list_versions(limit=10)
    except Exception:
        return None

    print("\n  Available versions:")
    for i, v in enumerate(versions, 1):
        print(f"    {i:>2}. {v}")
    print()
    choice = input("  Version number (Enter to cancel): ").strip()
    if not choice:
        return None
    try:
        return versions[int(choice) - 1]
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Commande : serve
# ---------------------------------------------------------------------------
def cmd_serve(args, config: dict, t):
    try:
        from api.routes import create_app
    except ImportError as e:
        print_err(t("cli.module_missing", error=str(e)))
        sys.exit(1)

    db_path = Path(config["database"]["path"])
    if not db_path.exists():
        print_err(t("cli.serve_no_db"))
        sys.exit(1)

    host  = args.host  or config["server"]["host"]
    port  = args.port  or config["server"]["port"]
    debug = args.debug or config["server"]["debug"]

    app = create_app(config)
    url = f"http://{host}:{port}"

    print_step(t("cli.serve_starting", url=url))
    print(_c(f"  {t('cli.serve_stop')}\n", YELLOW))

    if not getattr(args, "no_browser", False):
        Timer(1.2, webbrowser.open, args=[url]).start()

    try:
        app.run(host=host, port=port, debug=debug, use_reloader=debug)
    except OSError as e:
        print_err(t("cli.serve_port_error", port=port, error=str(e), next_port=port + 1))
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n" + _c(f"  {t('cli.serve_stop')}.", YELLOW))


# ---------------------------------------------------------------------------
# Commande : reset
# ---------------------------------------------------------------------------
def cmd_reset(args, config: dict, t):
    if not getattr(args, "confirm", False):
        print_err(t("cli.reset_confirm_required"))
        sys.exit(1)

    db_path   = Path(config["database"]["path"])
    cache_dir = Path(config["cache"]["dir"])

    print_step(t("cli.reset_title"))

    if db_path.exists():
        db_path.unlink()
        print_ok(t("cli.reset_db_done", path=str(db_path)))
    else:
        print_warn(t("cli.reset_no_db"))

    import shutil
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
        print_ok(t("cli.reset_cache_done", path=str(cache_dir)))
    else:
        print_warn(t("cli.reset_no_cache"))

    print_ok(t("cli.reset_done"))


# ---------------------------------------------------------------------------
# Parser CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="factorio_hub",
        description="Factorio Modding Hub — Prototype Centralizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py sync                          # api_docs + raw_data (default)
  python main.py sync --all                    # all sources incl. GitHub
  python main.py sync --source api_docs
  python main.py sync --source raw_data --version 2.0.76
  python main.py sync --source github --version 2.0.76
  python main.py sync --source github --version 2.0.76 --force
  python main.py serve
  python main.py serve --port 8080 --no-browser
  python main.py status
  python main.py reset --confirm
        """,
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # sync
    p_sync = sub.add_parser("sync", help="Synchronize data sources")
    src_group = p_sync.add_mutually_exclusive_group()
    src_group.add_argument(
        "--all", action="store_true",
        help="Sync all sources (api_docs + raw_data + github)",
    )
    src_group.add_argument(
        "--source", choices=["api_docs", "raw_data", "github"], metavar="SOURCE",
        help="Single source: api_docs | raw_data | github",
    )
    p_sync.add_argument(
        "--version", metavar="TAG",
        help=(
            "Version tag. "
            "For --source github: Git tag (e.g. 2.0.76). "
            "For --source raw_data: force version in DB (e.g. 2.0.76)."
        ),
    )
    p_sync.add_argument(
        "--force", action="store_true", dest="force_refresh",
        help="Force re-download even if cache is valid",
    )
    p_sync.add_argument(
        "--fail-fast", action="store_true",
        help="Stop on first error (default: log and continue)",
    )

    # serve
    p_serve = sub.add_parser("serve", help="Start the web interface")
    p_serve.add_argument("--port", "-p", type=int, default=None)
    p_serve.add_argument("--host", default=None)
    p_serve.add_argument("--no-browser", action="store_true")
    p_serve.add_argument("--debug", action="store_true")

    # status
    sub.add_parser("status", help="Show database status")

    # reset
    p_reset = sub.add_parser("reset", help="Delete database and caches")
    p_reset.add_argument(
        "--confirm", action="store_true",
        help="Required confirmation flag",
    )

    return parser


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------
def main():
    print_header()
    config = load_config()

    # Init i18n — doit être fait avant tout affichage traduit
    t = _init_i18n(config)

    parser = build_parser()
    args   = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "sync":   lambda: cmd_sync(args, config, t),
        "serve":  lambda: cmd_serve(args, config, t),
        "status": lambda: cmd_status(config, t),
        "reset":  lambda: cmd_reset(args, config, t),
    }

    handler = dispatch.get(args.command)
    if handler:
        handler()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()