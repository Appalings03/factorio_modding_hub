# Factorio Modding Hub

> Centralisateur local de prototypes Factorio pour moddeurs.
> Scrape, indexe et rend consultables les données de `data.raw`, l'API officielle Wube et le dépôt GitHub des prototypes de base.

*[Read in English](README.md)*

---

## Sommaire

- [À quoi ça sert](#à-quoi-ça-sert)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Configuration](#configuration)
- [Commandes](#commandes)
- [Architecture du projet](#architecture-du-projet)
- [Sources de données](#sources-de-données)
- [Import & Validation de mods](#import--validation-de-mods)
- [Ajouter une langue](#ajouter-une-langue)
- [Limitations connues](#limitations-connues)
- [FAQ](#faq)

---

## À quoi ça sert

Quand on fait un mod Factorio, on passe beaucoup de temps à chercher des réponses à des questions du type :

- *Quelles propriétés accepte un `AssemblingMachinePrototype` ?*
- *Est-ce que `crafting_speed` est obligatoire ou optionnel ? Quel est son type attendu ?*
- *Qu'est-ce qui a changé sur `RecipePrototype` entre la 1.1 et la 2.0 ?*
- *Quels prototypes héritent de `EntityWithHealthPrototype` ?*

**Factorio Modding Hub centralise tout ça en local**, dans une base SQLite, et expose une interface web consultable sans connexion.

### Fonctionnalités

| Fonctionnalité | Description |
|---|---|
| **Recherche de prototype** | Trouvez `assembling-machine-1` ou tous les prototypes de type `recipe` |
| **Détail de prototype** | Propriétés, types attendus, descriptions tirées de la doc officielle |
| **Navigation par héritage** | Remontez ou descendez l'arbre d'héritage |
| **Références croisées** | Voyez quels prototypes utilisent un item comme ingrédient, carburant, etc. |
| **Comparaison inter-versions** | Diff des propriétés entre deux versions de Factorio |
| **Import de mod** | Importez un `.zip`, parsez les Lua, fusionnez avec le vanilla |
| **Validation de mod** | Validez vos prototypes contre le schéma officiel |
| **Comparaison de versions de mod** | Diff entre deux versions du même mod |
| **Annotations personnelles** | Prenez des notes, ajoutez des tags (`todo`, `bug`, `important`) |
| **Interface multilingue** | Disponible en français et anglais (extensible) |
| **Consultation hors-ligne** | Une fois synchronisé, tout fonctionne sans internet |

---

## Prérequis

- **Python 3.10+** (3.11+ recommandé pour `tomllib` natif)
- **pip**
- Un token GitHub (optionnel, mais recommandé)

```bash
python --version
```

---

## Installation

```bash
# 1. Cloner le dépôt
git clone https://github.com/Appalings03/factorio_modding_hub.git
cd factorio_modding_hub

# 2. Créer un environnement virtuel (recommandé)
python -m venv .venv
.venv\Scripts\activate       # Windows
source .venv/bin/activate    # Linux / macOS

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Premier lancement : synchroniser les données
python main.py sync

# 5. Lancer l'interface web
python main.py serve
```

L'interface s'ouvre automatiquement sur `http://127.0.0.1:5000`.

---

## Configuration

Créez `config/settings.toml` pour personnaliser le comportement. Toutes les clés sont optionnelles.

```toml
# config/settings.toml

[sources]
# Token GitHub personnel — créer sur https://github.com/settings/tokens (scope: public_repo)
# Sans token : 60 req/h · Avec token : 5000 req/h
github_token = "ghp_xxxxxxxxxxxxxxxxxxxx"

gist_url          = "https://gist.githubusercontent.com/Bilka2/6b8a6a9e4a4ec779573ad703d03c1ae7/raw"
prototype_api_url = "https://lua-api.factorio.com/latest/prototype-api.json"

[database]
path = "data/factorio_hub.db"

[cache]
dir = "data/cache"

[server]
host  = "127.0.0.1"   # "0.0.0.0" pour exposer sur le réseau local
port  = 5000
debug = false

[ui]
language = "fr"       # "en" ou "fr" — modifiable ici ou via le sélecteur dans l'UI
```

Le token GitHub peut aussi être fourni via variable d'environnement :
```bash
set GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx   # Windows
export GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx # Linux/macOS
```

---

## Commandes

### `sync` — Synchroniser les sources

```bash
python main.py sync                                    # api_docs + raw_data (défaut)
python main.py sync --all                              # toutes sources incl. GitHub
python main.py sync --source api_docs                  # schéma des types uniquement (~5s)
python main.py sync --source raw_data                  # instances vanilla (~1-2min)
python main.py sync --source raw_data --version 2.0.76 # forcer la version en DB
python main.py sync --source github --version 2.0.76   # fichiers Lua GitHub
python main.py sync --source github --version 2.0.76 --force  # forcer re-téléchargement
python main.py sync --fail-fast                        # arrêter à la première erreur
```

> **Conseil :** Après le premier sync, lancez `sync --source raw_data --version 2.0.76` pour aligner la version raw_data avec api_docs.

### `serve` — Lancer l'interface web

```bash
python main.py serve
python main.py serve --port 8080
python main.py serve --no-browser
python main.py serve --debug
python main.py serve --host 0.0.0.0
```

### `status` — État de la base

```bash
python main.py status
```

### `reset` — Remise à zéro

```bash
python main.py reset --confirm
```

**Attention :** supprime la base et tous les caches, y compris les annotations personnelles.

---

## Architecture du projet

```
factorio_modding_hub/
├── config/
│   └── settings.toml
├── data/
│   ├── factorio_hub.db
│   ├── cache/
│   │   ├── raw_data/
│   │   ├── api_docs/
│   │   ├── github/
│   │   └── mod_uploads/
│   └── logs/
├── i18n/
│   ├── en.json
│   └── fr.json
├── scrapers/
├── parsers/
├── db/
│   ├── schema.py
│   ├── repository.py
│   └── migrations/
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

## Sources de données

### 1. Gist `data.raw`
Dump JSON de 20 MB de `data.raw` complet avec Space Age (version 2.0.65). Valeurs concrètes de tous les prototypes vanilla.

### 2. `prototype-api.json`
JSON officiel Wube — schéma complet des types, propriétés, types attendus, héritage.

### 3. GitHub `wube/factorio-data`
Fichiers Lua sources officiels, tagués par version. Inclut `base/`, `core/`, `space-age/`, `elevated-rail/`, `quality/`.

---

## Import & Validation de mods

### Importer un mod

1. Aller dans **Mods** → **Importer un mod**
2. Déposer votre fichier `.zip` ou cliquer sur Parcourir
3. Sélectionner la version Factorio cible (pour la fusion vanilla)
4. Cliquer sur Importer

L'importeur lit `data.lua`, `data-updates.lua`, `data-final-fixes.lua` dans l'ordre, fusionne les prototypes qui étendent le vanilla, et stocke tout dans une version DB séparée (`mod:nom:version`).

### Valider un mod

Après import, cliquer sur **Valider** pour vérifier les prototypes contre le schéma officiel :
- **Erreurs** — propriétés requises manquantes
- **Avertissements** — type inattendu, références vanilla cassées
- **Infos** — type absent du schéma officiel

Une fois satisfait, cliquer sur **Enregistrer définitivement** pour marquer le mod comme validé.

### Comparer des versions de mod

Si vous avez importé plusieurs versions du même mod, cliquez sur **Comparer versions** pour voir les prototypes ajoutés, supprimés ou modifiés.

### Limitations connues

- Le pattern `table.deepcopy()` n'est pas résolu — les prototypes générés programmatiquement peuvent être absents
- Les types settings (`int-setting`, `bool-setting`, etc.) apparaissent comme "schéma inconnu"
- Les propriétés héritées ne sont pas toujours incluses dans les résultats de validation

---

## Ajouter une langue

1. Copier `i18n/en.json` → `i18n/xx.json` (remplacer `xx` par le code langue)
2. Traduire toutes les valeurs (ne pas changer les clés)
3. Remplir la section `meta` :
   ```json
   "meta": {
     "name": "German",
     "native_name": "Deutsch",
     "flag": "🇩🇪"
   }
   ```
4. Changer `[ui] language = "xx"` dans `config/settings.toml`

Aucune modification de code nécessaire. Le sélecteur de langue dans le header détecte automatiquement le nouveau fichier.

---

## Limitations connues

| Limitation | Impact | Fix prévu |
|---|---|---|
| `table.deepcopy()` non résolu | Prototypes générés dynamiquement absents | TODO VAL03 |
| Types settings (`*-setting`) absents du schéma | Validator affiche "type inconnu" | TODO VAL01 |
| Propriétés héritées pas toujours validées | Validation incomplète | TODO VAL02 |
| `is_latest` non mis à jour automatiquement | Page vide après premier sync | TODO B01 |

---

## FAQ

**L'app fonctionne-t-elle sans internet ?**  
Oui, une fois `sync` effectué.

**Combien de temps prend la synchronisation ?**  
- `api_docs` : ~5 secondes
- `raw_data` : 30s à 2 minutes
- `github` (1 version) : 2 à 10 minutes

**L'app n'affiche rien après le sync — pourquoi ?**  
Aucune version n'est marquée comme active. Utilisez le sélecteur de version sur la homepage, ou lancez `fix_latest.py`.

**Faut-il un token GitHub ?**  
Non, mais fortement recommandé (60 req/h sans token, 5000/h avec).

**Mes annotations survivent-elles à un `sync --force` ?**  
Oui. Elles survivent à tout sauf `reset --confirm`.