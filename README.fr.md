# Factorio Modding Hub

> Centralisateur local de prototypes Factorio pour moddeurs.
> Scrape, indexe et rend consultables les données de `data.raw`, l'API officielle Wube et le dépôt GitHub des prototypes de base.

---

## Sommaire

- [À quoi ça sert](#à-quoi-ça-sert)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Configuration](#configuration)
- [Commandes](#commandes)
  - [sync](#sync--synchroniser-les-sources)
  - [serve](#serve--lancer-linterface-web)
  - [status](#status--état-de-la-base)
  - [reset](#reset--remise-à-zéro)
- [Architecture du projet](#architecture-du-projet)
- [Sources de données](#sources-de-données)
- [Phase 2 — Import GitHub & Localisation](#phase-2--import-github--localisation)
- [Phase 3 — Vérificateur de prototype](#phase-3--vérificateur-de-prototype)
- [FAQ](#faq)

---

## À quoi ça sert

Quand on fait un mod Factorio, on passe beaucoup de temps à chercher des réponses à des questions du type :

- *Quelles propriétés accepte un `AssemblingMachinePrototype` ?*
- *Est-ce que `crafting_speed` est obligatoire ou optionnel ? Quel est son type attendu ?*
- *Qu'est-ce qui a changé sur `RecipePrototype` entre la 1.1 et la 2.0 ?*
- *Quels prototypes héritent de `EntityWithHealthPrototype` ?*

Aujourd'hui, répondre à ces questions implique de jongler entre le wiki, la doc API en ligne, le gist `data.raw`, et les fichiers Lua du repo GitHub — sans aucune recherche croisée possible.

**Factorio Modding Hub centralise tout ça en local**, dans une base SQLite, et expose une interface web consultable sans connexion.

### Ce que l'app fait concrètement

| Fonctionnalité | Description |
|---|---|
| **Recherche de prototype** | Trouvez `assembling-machine-1` ou tous les prototypes de type `recipe` en une requête |
| **Détail de prototype** | Affichez toutes les propriétés d'un prototype, avec leur type attendu et leur description tirée de la doc officielle |
| **Navigation par héritage** | Remontez ou descendez l'arbre d'héritage (`RecipePrototype` → `PrototypeBase`) |
| **Références croisées** | Voyez quels prototypes utilisent un item donné comme ingrédient, carburant, module, etc. |
| **Comparaison inter-versions** | Diff des propriétés d'un prototype entre deux versions de Factorio (ex: 1.1.107 vs 2.0.65) |
| **Annotations personnelles** | Prenez des notes sur un prototype, ajoutez des tags (`todo`, `bug`, `important`) |
| **Consultation hors-ligne** | Une fois synchronisé, tout fonctionne sans internet |

---

## Prérequis

- **Python 3.10+** (3.11+ recommandé pour `tomllib` natif)
- **pip**
- Un token GitHub (optionnel, mais recommandé pour la source GitHub)

Vérifier votre version Python :
```bash
python --version
```

---

## Installation

```bash
# 1. Cloner le dépôt
git clone https://github.com/votre-compte/factorio-modding-hub.git
cd factorio-modding-hub

# 2. Créer un environnement virtuel (recommandé)
python -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows
.venv\Scripts\activate

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Premier lancement : synchroniser les données
python main.py sync

# 5. Lancer l'interface web
python main.py serve
```

L'interface s'ouvre automatiquement dans votre navigateur sur `http://127.0.0.1:5000`.

---

## Configuration

Créez le fichier `config/settings.toml` pour personnaliser le comportement de l'app.  
Toutes les clés sont optionnelles — les valeurs par défaut fonctionnent sans configuration.

```toml
# config/settings.toml

[sources]
github_token = "ghp_xxxxxxxxxxxxxxxxxxxx"
gist_url = "https://gist.githubusercontent.com/Bilka2/6b8a6a9e4a4ec779573ad703d03c1ae7/raw"
prototype_api_url = "https://lua-api.factorio.com/latest/prototype-api.json"

[database]
path = "data/factorio_hub.db"

[cache]
dir = "data/cache"

[server]
host  = "127.0.0.1"
port  = 5000
debug = false
```

Le token GitHub peut aussi être fourni via variable d'environnement :
```bash
export GITHUB_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxx"
python main.py sync --source github --version 2.0.65
```

---

## Commandes

### `sync` — Synchroniser les sources

```bash
python main.py sync                              # api_docs + raw_data (défaut)
python main.py sync --all                        # toutes sources incl. GitHub
python main.py sync --source api_docs            # schéma des types uniquement
python main.py sync --source raw_data            # instances vanilla uniquement
python main.py sync --source github --version 2.0.65
python main.py sync --force                      # ignore le cache local
```

### `serve` — Lancer l'interface web

```bash
python main.py serve
python main.py serve --port 8080
python main.py serve --no-browser
python main.py serve --debug
python main.py serve --host 0.0.0.0 --port 5000
```

### `status` — État de la base

```bash
python main.py status
```

### `reset` — Remise à zéro

```bash
python main.py reset --confirm
```

---

## Architecture du projet

```
factorio_modding_hub/
├── config/
│   └── settings.toml
├── data/
│   ├── factorio_hub.db
│   └── cache/
│       ├── raw_data/
│       ├── api_docs/
│       └── github/
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
├── core/
│   ├── sync_manager.py
│   ├── search_engine.py
│   ├── diff_engine.py
│   └── validator.py
├── api/
│   └── routes.py
├── ui/
│   ├── templates/
│   └── static/
├── main.py
├── requirements.txt
├── README.md
└── README.fr.md
```

---

## Sources de données

### 1. Gist `data.raw`
Dump JSON de 20 MB de `data.raw` complet (version 2.0.65, Space Age). Valeurs concrètes de tous les prototypes vanilla.

### 2. `prototype-api.json`
JSON machine-readable officiel Wube. Schéma complet des types, héritage, propriétés, types attendus.

### 3. GitHub `wube/factorio-data`
Fichiers Lua officiels des prototypes de base, tagués par version. Source de vérité pour la comparaison inter-versions.

---

## Phase 2 — Import GitHub & Localisation

En développement :
- **Import GitHub → DB** : parsing des fichiers Lua cachés et insertion en base
- **Localisation** : interface disponible en français et en anglais

---

## Phase 3 — Vérificateur de prototype

Prévu :
```python
validator = PrototypeValidator(repo, version="2.0.65")
errors = validator.validate(my_mod_prototype_dict)
# → [ValidationError(property_path="results", severity="error", ...)]
```

---

## FAQ

**L'app fonctionne-t-elle sans internet ?**  
Oui, une fois `sync` effectué.

**Combien de temps prend la synchronisation ?**  
- `api_docs` : ~5 secondes
- `raw_data` : 30s à 2 minutes
- `github` (1 version) : 2 à 10 minutes

**Faut-il un token GitHub ?**  
Non, mais recommandé (60 req/h sans token, 5000/h avec).

**Mes annotations survivent-elles à un `sync --force` ?**  
Oui. Pas à un `reset --confirm`.