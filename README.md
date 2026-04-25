# Factorio Modding Hub

> A local centralizer of Factorio prototypes for modders.
> Scrapes, indexes and makes searchable the data from `data.raw`, the official Wube API and the GitHub repository of base prototypes.

*[Lire en français](README.fr.md)*

---

## Table of Contents

- [What it does](#what-it-does)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Commands](#commands)
  - [sync](#sync--synchronize-sources)
  - [serve](#serve--start-the-web-interface)
  - [status](#status--database-state)
  - [reset](#reset--wipe-everything)
- [Project Architecture](#project-architecture)
- [Data Sources](#data-sources)
- [Phase 2 — GitHub Import & Localization](#phase-2--github-import--localization)
- [Phase 3 — Prototype Validator](#phase-3--prototype-validator)
- [FAQ](#faq)

---

## What it does

When making a Factorio mod, you spend a lot of time hunting for answers to questions like:

- *What properties does an `AssemblingMachinePrototype` accept?*
- *Is `crafting_speed` required or optional? What type does it expect?*
- *What changed in `RecipePrototype` between 1.1 and 2.0?*
- *Which prototypes inherit from `EntityWithHealthPrototype`?*

Today, answering these questions means juggling the wiki, the online API docs, the `data.raw` gist, and the GitHub Lua files — with no cross-search possible.

**Factorio Modding Hub centralizes all of this locally**, in a SQLite database, exposed through a web interface that works fully offline.

### Features

| Feature | Description |
|---|---|
| **Prototype search** | Find `assembling-machine-1` or all prototypes of type `recipe` in one query |
| **Prototype detail** | View all properties of a prototype, with their expected type and description from the official docs |
| **Inheritance navigation** | Walk up or down the inheritance tree (`RecipePrototype` → `PrototypeBase`) |
| **Cross-references** | See which prototypes use a given item as ingredient, fuel, module, etc. |
| **Version comparison** | Diff prototype properties between two Factorio versions (e.g. 1.1.107 vs 2.0.65) |
| **Personal annotations** | Take notes on a prototype, add tags (`todo`, `bug`, `important`) |
| **Offline browsing** | Once synced, everything works without internet |

---

## Requirements

- **Python 3.10+** (3.11+ recommended for native `tomllib`)
- **pip**
- A GitHub token (optional but recommended for the GitHub source)

Check your Python version:
```bash
python --version
```

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/your-account/factorio-modding-hub.git
cd factorio-modding-hub

# 2. Create a virtual environment (recommended)
python -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows
.venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. First run: sync data
python main.py sync

# 5. Start the web interface
python main.py serve
```

The interface opens automatically in your browser at `http://127.0.0.1:5000`.

---

## Configuration

Create `config/settings.toml` to customize the app's behavior.  
All keys are optional — the defaults work out of the box.

```toml
# config/settings.toml

[sources]
# GitHub personal token (optional but strongly recommended)
# Without token: 60 req/h limit → enough for 1 version
# With token: 5000 req/h → comfortable for multiple versions
# Create one at: https://github.com/settings/tokens (scope "public_repo")
github_token = "ghp_xxxxxxxxxxxxxxxxxxxx"

# URL of the data.raw dump (community gist referenced by the official wiki)
gist_url = "https://gist.githubusercontent.com/Bilka2/6b8a6a9e4a4ec779573ad703d03c1ae7/raw"

# Wube machine-readable API URL
prototype_api_url = "https://lua-api.factorio.com/latest/prototype-api.json"

[database]
# Path to the SQLite database (relative to project or absolute)
path = "data/factorio_hub.db"

[cache]
# Cache folder for downloaded files
dir = "data/cache"

[server]
host  = "127.0.0.1"   # Use "0.0.0.0" to expose on local network
port  = 5000
debug = false          # true = auto-reload (dev only)
```

The GitHub token can also be provided via environment variable (takes priority):
```bash
export GITHUB_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxx"
python main.py sync --source github --version 2.0.65
```

---

## Commands

### `sync` — Synchronize sources

Downloads and imports data into the local SQLite database.

```bash
# Default: syncs both main sources (recommended to start)
python main.py sync

# All sources including GitHub
python main.py sync --all

# Specific source
python main.py sync --source api_docs       # type schema only (~5s)
python main.py sync --source raw_data       # vanilla instances (~20MB, 1-2min)
python main.py sync --source github --version 2.0.65

# Force re-download ignoring cache
python main.py sync --force

# Stop on first error (default: log and continue)
python main.py sync --all --fail-fast
```

> **Note on GitHub sync:** without a token, the GitHub API is limited to 60 req/h. One full version is ~200 Lua files. With a personal token (free), the limit rises to 5000/h. Sync is idempotent — already-downloaded files are skipped.

### `serve` — Start the web interface

```bash
python main.py serve                         # opens browser automatically
python main.py serve --port 8080
python main.py serve --no-browser
python main.py serve --debug                 # auto-reload on code change
python main.py serve --host 0.0.0.0         # expose on local network
```

Stop the server: `Ctrl+C`.

### `status` — Database state

```bash
python main.py status
```

Shows synced versions, row counts per table, and cache state.

### `reset` — Wipe everything

```bash
python main.py reset --confirm
```

Deletes the database and all caches. The `--confirm` flag is required.  
**Warning:** this also deletes all personal annotations.

---

## Project Architecture

```
factorio_modding_hub/
├── config/
│   └── settings.toml          # User configuration (create this)
├── data/
│   ├── factorio_hub.db        # SQLite database (generated by sync)
│   └── cache/                 # Downloaded files
│       ├── raw_data/          # data.raw gist (~20 MB)
│       ├── api_docs/          # prototype-api.json
│       └── github/            # Lua files by version
├── scrapers/
│   ├── base_scraper.py        # Abstract base class
│   ├── raw_data_scraper.py    # data.raw gist
│   ├── github_scraper.py      # GitHub API + Lua files
│   └── api_docs_scraper.py    # prototype-api.json
├── parsers/
│   ├── lua_json_parser.py     # Simplified Lua parser
│   ├── prototype_parser.py    # Normalization to DB schema
│   └── inheritance_resolver.py # Inheritance tree resolution
├── db/
│   ├── schema.py              # CREATE TABLE, init_db()
│   ├── repository.py          # CRUD layer (Repository pattern)
│   └── migrations/            # Versioned SQL scripts
├── core/
│   ├── sync_manager.py        # Sync pipeline orchestration
│   ├── search_engine.py       # FTS search + filters
│   ├── diff_engine.py         # Cross-version comparison
│   └── validator.py           # Phase 3 stub: prototype checker
├── api/
│   └── routes.py              # Flask endpoints
├── ui/
│   ├── templates/             # Jinja2 HTML templates
│   └── static/                # CSS + JS
├── main.py                    # CLI entry point
├── requirements.txt
├── README.md                  # This file (English)
└── README.fr.md               # French version
```

---

## Data Sources

### 1. `data.raw` Gist (wiki.factorio.com)

A 20 MB JSON dump of the complete `data.raw` with Space Age enabled (version 2.0.65). This is the exact serialization of what Factorio loads into memory at startup.

**What we get:** concrete values of all vanilla prototypes — `crafting_speed`, `stack_size`, `ingredients`, `results`, etc.

### 2. `prototype-api.json` (lua-api.factorio.com)

The official Wube machine-readable JSON describing the schema of all prototype types — which properties they accept, their types, default values, and inheritance hierarchy.

**What we get:** the complete schema (`RecipePrototype` inherits from `PrototypeBase`, the `category` property is of type `RecipeCategoryID`, optional with default `"crafting"`…).

### 3. GitHub `wube/factorio-data`

The official Wube repository containing the Lua source files for base prototypes (`base/prototypes/`, `core/prototypes/`, `space-age/prototypes/`), tagged by Factorio version.

**What we get:** the source of truth for cross-version comparison — exact diffs between tags.

---

## Phase 2 — GitHub Import & Localization

In development:

- **GitHub → DB import**: parsing cached Lua files and inserting prototypes into the database, making GitHub data searchable and comparable like other sources
- **Localization**: UI available in English and French via language selector

---

## Phase 3 — Prototype Validator

Planned feature — validate a mod prototype against the official schema before launching Factorio:

```python
# Intended usage (phase 3)
from core.validator import PrototypeValidator

validator = PrototypeValidator(repo, version="2.0.65")
errors = validator.validate({
    "type": "recipe",
    "name": "my-custom-recipe",
    "ingredients": [{"type": "item", "name": "iron-plate", "amount": 5}],
    # "results" missing → error detected
})
# → [ValidationError(property_path="results", severity="error", ...)]
```

Already in place for phase 3:
- `raw_json` in `prototypes` table — intact source of truth
- `type_properties` with `type_str` and `is_optional` — validation schema ready
- `data_types` — sub-types for recursive validation
- `prototype_relations` — dependency graph for cross-reference checks
- `core/validator.py` — documented stub, ready to implement

---

## FAQ

**Does the app work without internet?**  
Yes, once `sync` has been run. All data is stored locally in `data/factorio_hub.db`. The Flask server is purely local.

**How long does synchronization take?**  
- `api_docs` only: ~5 seconds
- `raw_data` only: 30 seconds to 2 minutes (20 MB download + import)
- `github` (1 version): 2 to 10 minutes depending on token and connection

**Does the data.raw gist cover Space Age?**  
Yes. The referenced gist corresponds to Factorio 2.0.65 with the Space Age DLC active.

**Can multiple versions coexist?**  
Yes. Each synced version creates separate rows linked by `version_id`. Cross-version comparison is natively supported.

**Is a GitHub token required?**  
No, but strongly recommended for the GitHub source. Without a token, the API is limited to 60 req/h — syncing one version (~200 Lua files) can hit this limit. A free personal token raises it to 5000/h.

**Do my annotations survive `sync --force`?**  
Yes. Annotations are in a separate table and never overwritten by a re-sync.

**What about `reset`?**  
No — `reset --confirm` deletes the entire database including annotations. Export your annotations first if needed.