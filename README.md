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
- [Project Architecture](#project-architecture)
- [Data Sources](#data-sources)
- [Mod Import & Validation](#mod-import--validation)
- [Adding a Language](#adding-a-language)
- [Known Limitations](#known-limitations)
- [FAQ](#faq)

---

## What it does

When making a Factorio mod, you spend a lot of time hunting for answers to questions like:

- *What properties does an `AssemblingMachinePrototype` accept?*
- *Is `crafting_speed` required or optional? What type does it expect?*
- *What changed in `RecipePrototype` between 1.1 and 2.0?*
- *Which prototypes inherit from `EntityWithHealthPrototype`?*

**Factorio Modding Hub centralizes all of this locally**, in a SQLite database, exposed through a web interface that works fully offline.

### Features

| Feature | Description |
|---|---|
| **Prototype search** | Find `assembling-machine-1` or all prototypes of type `recipe` in one query |
| **Prototype detail** | View all properties, expected types and descriptions from official docs |
| **Inheritance navigation** | Walk up or down the inheritance tree (`RecipePrototype` → `PrototypeBase`) |
| **Cross-references** | See which prototypes use a given item as ingredient, fuel, module, etc. |
| **Version comparison** | Diff prototype properties between two Factorio versions |
| **Mod import** | Import a `.zip` mod, parse its Lua files, merge with vanilla data |
| **Mod validation** | Validate mod prototypes against the official schema |
| **Mod comparison** | Diff two versions of the same mod |
| **Personal annotations** | Take notes on a prototype, add tags (`todo`, `bug`, `important`) |
| **Multilingual UI** | Interface available in English and French (extensible) |
| **Offline browsing** | Once synced, everything works without internet |

---

## Requirements

- **Python 3.10+** (3.11+ recommended for native `tomllib`)
- **pip**
- A GitHub token (optional but recommended for the GitHub source)

```bash
python --version
```

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/Appalings03/factorio_modding_hub.git
cd factorio_modding_hub

# 2. Create a virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate       # Windows
source .venv/bin/activate    # Linux / macOS

# 3. Install dependencies
pip install -r requirements.txt

# 4. First run: sync data
python main.py sync

# 5. Start the web interface
python main.py serve
```

The interface opens automatically at `http://127.0.0.1:5000`.

---

## Configuration

Create `config/settings.toml` to customize behavior. All keys are optional.

```toml
# config/settings.toml

[sources]
# GitHub personal token — create at https://github.com/settings/tokens (scope: public_repo)
# Without token: 60 req/h · With token: 5000 req/h
github_token = "ghp_xxxxxxxxxxxxxxxxxxxx"

gist_url          = "https://gist.githubusercontent.com/Bilka2/6b8a6a9e4a4ec779573ad703d03c1ae7/raw"
prototype_api_url = "https://lua-api.factorio.com/latest/prototype-api.json"

[database]
path = "data/factorio_hub.db"    # relative or absolute path

[cache]
dir = "data/cache"

[server]
host  = "127.0.0.1"   # use "0.0.0.0" to expose on local network
port  = 5000
debug = false

[ui]
language = "en"       # "en" or "fr" — change here or via the UI language selector
```

GitHub token can also be set via environment variable:
```bash
set GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx   # Windows
export GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx # Linux/macOS
```

---

## Commands

### `sync` — Synchronize sources

```bash
python main.py sync                                    # api_docs + raw_data (default)
python main.py sync --all                              # all sources incl. GitHub
python main.py sync --source api_docs                  # type schema only (~5s)
python main.py sync --source raw_data                  # vanilla instances (~1-2min)
python main.py sync --source raw_data --version 2.0.76 # force version tag in DB
python main.py sync --source github --version 2.0.76   # GitHub Lua files
python main.py sync --source github --version 2.0.76 --force  # re-download cache
python main.py sync --fail-fast                        # stop on first error
```

> **Tip:** After first sync, run `sync --source raw_data --version 2.0.76` to align the raw_data version with api_docs.

### `serve` — Start the web interface

```bash
python main.py serve
python main.py serve --port 8080
python main.py serve --no-browser
python main.py serve --debug
python main.py serve --host 0.0.0.0   # expose on local network
```

### `status` — Database state

```bash
python main.py status
```

### `reset` — Wipe everything

```bash
python main.py reset --confirm
```

**Warning:** deletes database and all caches including personal annotations.

---

## Project Architecture

```
factorio_modding_hub/
├── config/
│   └── settings.toml          # User configuration
├── data/
│   ├── factorio_hub.db        # SQLite database
│   ├── cache/                 # Downloaded files
│   │   ├── raw_data/
│   │   ├── api_docs/
│   │   ├── github/
│   │   └── mod_uploads/       # Uploaded mod zips
│   └── logs/                  # GitHub sync skip logs
├── i18n/
│   ├── en.json                # English translations
│   └── fr.json                # French translations
├── scrapers/
│   ├── base_scraper.py
│   ├── raw_data_scraper.py
│   ├── github_scraper.py
│   └── api_docs_scraper.py
├── parsers/
│   ├── lua_json_parser.py
│   ├── prototype_parser.py
│   └── inheritance_resolver.py
├── db/
│   ├── schema.py
│   ├── repository.py
│   └── migrations/
│       ├── 001_initial.sql
│       ├── 002_annotations.sql
│       └── 003_mods.sql
├── core/
│   ├── sync_manager.py
│   ├── search_engine.py
│   ├── diff_engine.py
│   ├── validator.py
│   ├── mod_importer.py
│   └── i18n.py
├── api/
│   └── routes.py
├── ui/
│   ├── templates/
│   └── static/
├── tests/
├── main.py
├── requirements.txt
├── RAPPORT.md
├── TODO.md
├── README.md
└── README.fr.md
```

---

## Data Sources

### 1. `data.raw` Gist
A 20 MB JSON dump of the complete `data.raw` with Space Age (version 2.0.65). Concrete runtime values of all vanilla prototypes.

### 2. `prototype-api.json`
Official Wube machine-readable JSON — schema of all prototype types, properties, types, inheritance.

### 3. GitHub `wube/factorio-data`
Official Lua source files for base prototypes, tagged by version. Includes `base/`, `core/`, `space-age/`, `elevated-rail/`, `quality/`.

---

## Mod Import & Validation

### Import a mod

1. Go to **Mods** → **Import a mod**
2. Drop your `.zip` file or click Browse
3. Select the target Factorio version (for vanilla merge)
4. Click Import

The importer reads `data.lua`, `data-updates.lua`, `data-final-fixes.lua` in order, merges prototypes that extend vanilla ones, and stores everything in a separate DB version (`mod:name:version`).

### Validate a mod

After import, click **Validate** to check prototypes against the official schema:
- **Errors** — required properties missing
- **Warnings** — unexpected type, broken vanilla references
- **Info** — type not found in official schema

Once satisfied, click **Save permanently** to mark the mod as validated.

### Compare mod versions

If you have imported multiple versions of the same mod, click **Compare versions** to see which prototypes were added, removed, or modified between versions.

### Known limitations

- `table.deepcopy()` patterns are not resolved — prototypes generated programmatically may be missing
- Settings types (`int-setting`, `bool-setting`, etc.) show as "unknown schema" — partial validation only
- Inherited properties are not always shown in validation results

---

## Adding a Language

1. Copy `i18n/en.json` → `i18n/xx.json` (replace `xx` with your language code)
2. Translate all values (keep the keys unchanged)
3. Fill in the `meta` section:
   ```json
   "meta": {
     "name": "German",
     "native_name": "Deutsch",
     "flag": "🇩🇪"
   }
   ```
4. Change `[ui] language = "xx"` in `config/settings.toml`

No code changes needed. The language selector in the header will automatically pick up the new file.

---

## Known Limitations

| Limitation | Impact | Planned fix |
|---|---|---|
| `table.deepcopy()` not resolved in Lua parser | Mod prototypes generated programmatically may be missing | TODO VAL03 |
| Settings types (`*-setting`) not in official schema | Validator shows "unknown type" for all settings | TODO VAL01 |
| Inherited properties not always validated | Validation incomplete for inherited required fields | TODO VAL02 |
| `is_latest` not set automatically after sync | Empty UI after first sync — must set manually | TODO B01 |

---

## FAQ

**Does the app work without internet?**  
Yes, once `sync` has run.

**How long does synchronization take?**  
- `api_docs` : ~5 seconds
- `raw_data` : 30s to 2 minutes
- `github` (1 version) : 2 to 10 minutes

**The app shows nothing after sync — why?**  
No version is marked as active. Open the homepage, use the version selector dropdown to pick your version, or run `fix_latest.py`.

**Is a GitHub token required?**  
No, but strongly recommended (60 req/h without, 5000/h with).

**Do my annotations survive `sync --force`?**  
Yes. They survive everything except `reset --confirm`.