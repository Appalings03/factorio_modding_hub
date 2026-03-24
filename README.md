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
- [Phase 2 — Vérificateur de prototype](#phase-2--vérificateur-de-prototype)
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
# Token GitHub personnel (optionnel, mais fortement recommandé)
# Sans token : limite à 60 requêtes/heure → suffisant pour 1 version
# Avec token : 5000 requêtes/heure → confortable pour plusieurs versions
# Créer un token : https://github.com/settings/tokens (scope "public_repo")
github_token = "ghp_xxxxxxxxxxxxxxxxxxxx"

# URL du dump data.raw (gist communautaire référencé par le wiki officiel)
# Ne changer que si une version plus récente du gist est publiée
gist_url = "https://gist.githubusercontent.com/Bilka2/6b8a6a9e4a4ec779573ad703d03c1ae7/raw"

# URL de l'API Wube machine-readable
prototype_api_url = "https://lua-api.factorio.com/latest/prototype-api.json"

[database]
# Chemin vers la base SQLite (relatif au projet ou absolu)
path = "data/factorio_hub.db"

[cache]
# Dossier de cache pour les fichiers téléchargés
dir = "data/cache"

[server]
host  = "127.0.0.1"   # Utiliser "0.0.0.0" pour exposer sur le réseau local
port  = 5000
debug = false          # true = rechargement automatique (dev uniquement)
```

Le token GitHub peut aussi être fourni via variable d'environnement (prioritaire sur le fichier) :
```bash
export GITHUB_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxx"
python main.py sync --source github --version 2.0.65
```

---

## Commandes

### `sync` — Synchroniser les sources

Télécharge et importe les données dans la base SQLite locale.

```bash
python main.py sync [OPTIONS]
```

**Sans option** — synchronise les deux sources principales (recommandé pour débuter) :
```bash
python main.py sync
# Équivalent à : --source api_docs puis --source raw_data
# Durée approximative : 30s à 2min selon votre connexion
```

**`--all`** — synchronise toutes les sources, y compris GitHub :
```bash
python main.py sync --all
# Déclenche un menu interactif pour choisir la version GitHub à télécharger
```

**`--source`** — synchronise une source spécifique :
```bash
# Schéma des types (prototype-api.json) — ~200 types, rapide
python main.py sync --source api_docs

# Instances vanilla (gist data.raw, ~20 MB) — ~4000 prototypes
python main.py sync --source raw_data

# Fichiers Lua d'une version spécifique depuis GitHub
python main.py sync --source github --version 2.0.65
python main.py sync --source github --version 1.1.107
```

**`--version`** — tag de version GitHub à synchroniser (requis avec `--source github`) :
```bash
python main.py sync --source github --version 2.0.65
```

**`--force`** — ignore le cache local et re-télécharge tout :
```bash
python main.py sync --force
# Utile quand le gist data.raw a été mis à jour
```

**`--fail-fast`** — arrête dès le premier échec (par défaut, les erreurs sont loguées et on continue) :
```bash
python main.py sync --all --fail-fast
```

> **Note sur la synchronisation GitHub :** sans token configuré, l'API GitHub est limitée à 60 requêtes/heure. Un dépôt complet représente ~200 fichiers Lua, soit ~200 requêtes. Avec un token, la limite passe à 5000/heure. Le sync d'une version est idempotent : les fichiers déjà téléchargés ne sont pas re-téléchargés.

---

### `serve` — Lancer l'interface web

Démarre le serveur Flask et ouvre l'interface dans le navigateur.

```bash
python main.py serve [OPTIONS]
```

```bash
# Lancement standard (ouvre le navigateur automatiquement)
python main.py serve

# Port personnalisé
python main.py serve --port 8080

# Sans ouverture automatique du navigateur
python main.py serve --no-browser

# Mode développement (rechargement automatique sur modification du code)
python main.py serve --debug

# Exposer sur le réseau local (accessible depuis d'autres machines)
python main.py serve --host 0.0.0.0 --port 5000
```

**Options disponibles :**

| Option | Défaut | Description |
|---|---|---|
| `--port`, `-p` | `5000` | Port d'écoute HTTP |
| `--host` | `127.0.0.1` | Adresse d'écoute |
| `--no-browser` | — | Ne pas ouvrir le navigateur |
| `--debug` | — | Mode debug Flask |

Arrêter le serveur : `Ctrl+C`.

---

### `status` — État de la base

Affiche un résumé de ce qui est synchronisé dans la base de données.

```bash
python main.py status
```

Exemple de sortie :
```
╔══════════════════════════════════════╗
║   Factorio Modding Hub               ║
║   Centralisateur de prototypes        ║
╚══════════════════════════════════════╝

▶ État de la base de données

  ✓ Base : /home/user/factorio-modding-hub/data/factorio_hub.db  (14.3 MB)

  Version          Sources                              Date                   Latest
  ───────────────────────────────────────────────────────────────────────────────────
  2.0.65           ["api_docs","raw_data"]              2025-03-20T14:32:11    ◄
  1.1.107          ["github"]                           2025-03-19T11:05:44

  ✓ Types de prototypes              214 lignes
  ✓ Prototypes (instances)          4127 lignes
  ✓ Propriétés de schéma            8943 lignes
  ✓ Annotations utilisateur            3 lignes

  Cache : /home/user/factorio-modding-hub/data/cache
  ✓ cache/raw_data        3 fichiers  (20480 KB)
  ✓ cache/api_docs        2 fichiers  (312 KB)
  ✓ cache/github        198 fichiers  (1843 KB)
```

---

### `reset` — Remise à zéro

Supprime la base de données et tous les caches téléchargés.

```bash
python main.py reset --confirm
```

Le flag `--confirm` est obligatoire — protection contre les suppressions accidentelles.

```bash
# Supprime data/factorio_hub.db et data/cache/ entièrement
python main.py reset --confirm
```

Après un reset, relancez `python main.py sync` pour réinitialiser.

---

## Architecture du projet

```
factorio_modding_hub/
│
├── config/
│   └── settings.toml          # Configuration utilisateur (à créer)
│
├── data/
│   ├── factorio_hub.db        # Base SQLite (générée par sync)
│   └── cache/                 # Fichiers téléchargés (JSON, Lua)
│       ├── raw_data/          # Gist data.raw (~20 MB)
│       ├── api_docs/          # prototype-api.json officiel
│       └── github/            # Fichiers Lua par version
│
├── scrapers/
│   ├── base_scraper.py        # Classe abstraite commune
│   ├── raw_data_scraper.py    # Gist data.raw (JSON 20MB)
│   ├── github_scraper.py      # API GitHub + fichiers Lua
│   └── api_docs_scraper.py    # prototype-api.json Wube
│
├── parsers/
│   ├── lua_json_parser.py     # Parser Lua simplifié
│   ├── prototype_parser.py    # Normalisation vers le schéma DB
│   └── inheritance_resolver.py # Résolution de l'arbre d'héritage
│
├── db/
│   ├── schema.py              # CREATE TABLE, init_db()
│   ├── repository.py          # Couche CRUD (Repository pattern)
│   └── migrations/            # Scripts SQL versionnés
│
├── core/
│   ├── sync_manager.py        # Orchestration du pipeline sync
│   ├── search_engine.py       # Recherche FTS + filtres
│   ├── diff_engine.py         # Comparaison inter-versions
│   └── validator.py           # Stub phase 2 : vérificateur
│
├── api/
│   └── routes.py              # Endpoints Flask
│
├── ui/
│   ├── templates/             # HTML Jinja2
│   └── static/                # CSS + JS
│
├── main.py                    # Point d'entrée CLI (ce fichier)
├── requirements.txt
└── README.md
```

---

## Sources de données

L'application agrège trois sources complémentaires :

### 1. Gist `data.raw` (wiki.factorio.com)

**Ce que c'est :** Un dump JSON de 20 MB de `data.raw` complet, avec Space Age actif (version 2.0.65). C'est la sérialisation exacte de ce que Factorio charge en mémoire au démarrage.

**Ce qu'on en tire :** Les valeurs concrètes de tous les prototypes vanilla — `crafting_speed`, `stack_size`, `ingredients`, `results`, etc.

**Mise à jour :** Le gist est maintenu par la communauté et référencé par le wiki officiel. L'app détecte les mises à jour via hash SHA256 et re-importe automatiquement si le contenu change.

### 2. `prototype-api.json` (lua-api.factorio.com)

**Ce que c'est :** Le JSON machine-readable officiel de Wube, décrivant le schéma de tous les types de prototypes — quelles propriétés ils acceptent, leurs types, leurs valeurs par défaut, et leur hiérarchie d'héritage.

**Ce qu'on en tire :** Le schéma complet (`RecipePrototype` hérite de `PrototypeBase`, la propriété `category` est de type `RecipeCategoryID`, elle est optionnelle avec la valeur par défaut `"crafting"`…).

**Mise à jour :** Disponible par URL versionnée (`/2.0.65/prototype-api.json`). Un fichier par version de Factorio.

### 3. GitHub `wube/factorio-data`

**Ce que c'est :** Le dépôt officiel Wube contenant les fichiers Lua des prototypes de base (`base/prototypes/`, `core/prototypes/`, `space-age/prototypes/`), tagués par version de Factorio.

**Ce qu'on en tire :** La source de vérité pour la comparaison inter-versions — on peut voir exactement ce qui a changé entre deux tags dans les fichiers source.

**Mise à jour :** Par tag Git. Chaque version de Factorio correspond à un tag (ex: `2.0.65`, `1.1.107`). Le sync est idempotent.

---

## Phase 2 — Vérificateur de prototype

L'architecture de l'app est conçue dès le départ pour supporter une phase 2 : un vérificateur de prototype hors-jeu.

L'idée : pouvoir coller le JSON d'un prototype de mod et recevoir une liste d'erreurs avant même de lancer Factorio.

```python
# Utilisation prévue (phase 2)
from core.validator import PrototypeValidator

validator = PrototypeValidator(repo, version="2.0.65")
errors = validator.validate({
    "type": "recipe",
    "name": "my-custom-recipe",
    "category": "crafting",
    "ingredients": [{"type": "item", "name": "iron-plate", "amount": 5}],
    # "results" manquant → erreur détectée
})
# → [ValidationError(property_path="results", severity="error", ...)]
```

Ce qui est déjà en place pour la phase 2 :

- `raw_json` dans la table `prototypes` — source de vérité intacte
- `type_properties` avec `type_str` et `is_optional` — schéma de validation prêt
- `data_types` (EnergySource, IconData…) — sous-types pour validation récursive
- `prototype_relations` — graphe de dépendances pour vérifier les références croisées
- `core/validator.py` — stub documenté, prêt à être implémenté

---

## FAQ

**L'app fonctionne-t-elle sans internet ?**  
Oui, une fois `sync` effectué. Toutes les données sont stockées localement dans `data/factorio_hub.db`. Le serveur Flask est purement local.

**Combien de temps prend la synchronisation ?**  
- `api_docs` seul : ~5 secondes
- `raw_data` seul : 30 secondes à 2 minutes (téléchargement du gist 20 MB + import)
- `github` (1 version) : 2 à 10 minutes selon le token et la connexion

**Le gist data.raw couvre-t-il Space Age ?**  
Oui. Le gist référencé par le wiki correspond à Factorio 2.0.65 avec le DLC Space Age actif.

**Peut-on avoir plusieurs versions en parallèle ?**  
Oui. Chaque version synchronisée crée des lignes séparées en base, reliées par `version_id`. La comparaison inter-versions est supportée nativement.

**Faut-il un token GitHub ?**  
Non, mais c'est fortement recommandé pour la source GitHub. Sans token, l'API GitHub est limitée à 60 requêtes/heure — synchroniser une version (~200 fichiers Lua) peut atteindre cette limite. Avec un token personnel gratuit, la limite passe à 5000/heure.

**Mes annotations survivent-elles à un `sync --force` ?**  
Oui. Les annotations sont dans une table séparée (`annotations`), référencées par `typename` et `proto_name` (pas par ID), et ne sont jamais écrasées par un re-sync.

**Et à un `reset` ?**  
Non — `reset --confirm` supprime la base entière, annotations comprises. Exportez vos annotations avant si nécessaire.