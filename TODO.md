# Factorio Modding Hub — TODO

> Priorisé par impact / effort  
> 🔴 Critique · 🟡 Important · 🟢 Amélioration · 💡 Idée future

---

## 🔴 Bugs critiques

- [x] **B01** — Automatiser `set_latest_version()` dans `sync_manager`  
  Dans `sync_raw_data()` et `sync_github()`, ajouter à la fin :
  ```python
  self.repo.set_latest_version(actual_version)
  ```

- [ ] **B02** — `_compute_mod_diff()` : tags incorrects pour `diff_engine`  
  Dans `routes.py`, remplacer :
  ```python
  # AVANT
  raw_diff = diff_engine.diff_prototype(typename, name, version_a, version_b)
  # APRÈS — version_a et version_b sont des mod_version (ex: "1.0.0")
  # diff_engine attend des version_tags DB (ex: "mod:advanced-pumpjacks:1.0.0")
  tag_a = f"mod:{mod_name}:{version_a}"
  tag_b = f"mod:{mod_name}:{version_b}"
  raw_diff = diff_engine.diff_prototype(typename, name, tag_a, tag_b)
  ```

---

## 🔴 Validator — Corrections majeures

- [ ] **VAL01** — Ajouter support des types `*-setting` (settings stage)  
  Les types `int-setting`, `bool-setting`, `string-setting`, `double-setting` ne sont pas dans `prototype-api.json`.  
  **Solution :** Dans `validator.py`, `_get_schema()`, si `typename` se termine par `-setting` → retourner un schéma minimal hardcodé au lieu de `None` :
  ```python
  _SETTING_SCHEMAS = {
      "int-setting":    [{"name": "setting_type", "is_optional": 0, "type_str": "string"},
                         {"name": "default_value", "is_optional": 0, "type_str": "int"},
                         {"name": "minimum_value", "is_optional": 1, "type_str": "int"},
                         {"name": "maximum_value", "is_optional": 1, "type_str": "int"}],
      "bool-setting":   [{"name": "setting_type", "is_optional": 0, "type_str": "string"},
                         {"name": "default_value", "is_optional": 0, "type_str": "bool"}],
      "string-setting": [{"name": "setting_type", "is_optional": 0, "type_str": "string"},
                         {"name": "default_value", "is_optional": 0, "type_str": "string"},
                         {"name": "allowed_values", "is_optional": 1, "type_str": "array[string]"}],
      "double-setting": [{"name": "setting_type", "is_optional": 0, "type_str": "string"},
                         {"name": "default_value", "is_optional": 0, "type_str": "double"}],
  }
  ```

- [ ] **VAL02** — Corriger la propagation des propriétés héritées dans la validation  
  **Problème :** `get_type_properties(type_id, include_inherited=True)` retourne seulement les propriétés directes si les héritées n'ont pas été insérées dans `type_properties`.  
  **Solution :** Dans `validator.py`, `_get_schema()`, remonter manuellement l'arbre :
  ```python
  # Après avoir récupéré les props directes, ajouter les héritées depuis les ancêtres
  ancestors = self.repo.get_type_ancestors(type_info["id"])
  seen = {p["name"] for p in props}
  for anc in ancestors:
      for p in self.repo.get_type_properties(anc["id"], include_inherited=False):
          if p["name"] not in seen:
              p = dict(p)
              p["is_inherited"] = 1
              p["inherited_from"] = anc["name"]
              props.append(p)
              seen.add(p["name"])
  ```

- [ ] **VAL03** — Support du pattern `table.deepcopy()` dans le parser Lua  
  **Problème :** Les mods qui génèrent des prototypes via `table.deepcopy(base_proto)` + modifications produisent des prototypes non parsés.  
  **Solution partielle :** Dans `lua_json_parser.py`, détecter le pattern :
  ```lua
  local my_proto = table.deepcopy(other_proto)
  my_proto.name = "new-name"
  data:extend({my_proto})
  ```
  Traiter `table.deepcopy(x)` comme retournant un dict vide `{}` (le mod surécrit les valeurs ensuite de toute façon). Les propriétés modifiées seront bien capturées.  
  
  Dans `_parse_reference()` ou `_parse_value()` :
  ```python
  # Détecter table.deepcopy(...) → retourner {}
  if self.source.startswith("table.deepcopy", self.pos):
      # Skip jusqu'à la fermeture de la parenthèse
      ...
      return {}
  ```

- [ ] **VAL04** — Afficher clairement "settings non validés" vs "erreur"  
  Quand un typename est `*-setting`, afficher une info `"Type settings — validation basique"` au lieu de `"type not in schema"`.

---

## 🟡 Améliorations importantes

### Performance

- [ ] **PERF01** — Supprimer le N+1 dans `mods_detail`  
  Remplacer la boucle `get_prototype()` par une requête SQL unique :
  ```python
  with repo._conn() as con:
      rows = con.execute(
          "SELECT typename, name, raw_json FROM prototypes "
          "WHERE mod_id = ? ORDER BY typename, name LIMIT ? OFFSET ?",
          (mod_id, page_size, offset)
      ).fetchall()
  ```

- [ ] **PERF02** — `_load_vanilla()` : filtrer par typenames du mod  
  ```python
  mod_typenames = {p["typename"] for p in all_mod_protos}
  # WHERE typename IN (...)
  ```

- [ ] **PERF03** — Ajouter `MAX_CONTENT_LENGTH` dans `create_app()`  
  ```python
  app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
  ```

### Architecture

- [ ] **ARCH01** — Créer `core/view_helpers.py`  
  Déplacer depuis `routes.py` :
  - `_build_type_cards()`
  - `_build_type_groups()`
  - `_build_stats()`
  - `_build_property_list()`
  - `_compute_mod_diff()`

- [ ] **ARCH02** — Remplacer les `print()` de `sync_manager.py` par `logger`  
  Utiliser `logger.info()` partout pour cohérence.

---

## 🟢 Améliorations UI/UX

- [ ] **UI01** — Homepage : warning si aucune version `is_latest`  
  ```html
  {% if not versions | selectattr('is_latest') | list %}
  <div class="flash flash-error">Aucune version active — sélectionnez une version ci-dessous.</div>
  {% endif %}
  ```

- [ ] **UI02** — Search : compteur de résultats par type dans le `<select>`  
  `<option value="recipe">recipe (247)</option>`

- [ ] **UI03** — Prototype detail : lien vers doc officielle Wube  
  `https://lua-api.factorio.com/latest/{TypeName}.html`

- [ ] **UI04** — Search : UI pour `search_by_property()`  
  Champ `key=value` dans les filtres de recherche avancée

- [ ] **UI05** — Mods detail : pagination côté serveur  
  Le filtrage JS côté client est lent pour les mods avec 100+ prototypes

- [ ] **UI06** — Compare : mode "diff de type complet"  
  Comparer tous les prototypes d'un typename entre deux versions vanilla

- [ ] **UI07** — Status page : bouton "Définir comme version active"  
  Route déjà présente (`set_default_version`), juste ajouter le bouton dans `status.html`
  
- [ ] **UI08** — Séparer la recherche entre prototypes de base et mods  
  Actuellement la recherche FTS5 mélange toutes les versions (vanilla, github, mods).  
  **Solution :** Ajouter un toggle dans `search.html` : `Base` vs `Mods`  
  Dans `search_engine.py`, filtrer par pattern de `version_tag` :
```python
  if source_filter == "base":
      # WHERE version_id NOT IN (SELECT id FROM versions WHERE version_tag LIKE 'mod:%')
  elif source_filter == "mods":
      # WHERE version_id IN (SELECT id FROM versions WHERE version_tag LIKE 'mod:%')
```
  URL : `?source=base` ou `?source=mods`
---

## 💡 Idées futures

- [ ] **F01** — Export d'un prototype validé en Lua  
  Générer `data:extend({...})` depuis le `raw_json`

- [ ] **F02** — Support partiel de `table.deepcopy()` dans le parser  
  Voir VAL03 — permet d'importer les mods qui génèrent des tiers programmatiquement

- [ ] **F03** — Import du `settings-api.json` (Wube)  
  `https://lua-api.factorio.com/latest/settings-api.json` pour valider les settings correctement

- [ ] **F04** — Recherche dans les annotations  
  Indexer le contenu des annotations dans FTS5

- [ ] **F05** — API REST publique  
  `/api/v1/prototypes`, `/api/v1/types` pour usage depuis scripts de mod

- [ ] **F06** — Notifications de mise à jour  
  Détecter si une nouvelle version Factorio est disponible sur GitHub

- [ ] **F07** — Mode sombre / clair  
  Toggle CSS variables, préférence dans `settings.toml`

- [ ] **F08** — 3ème langue (ex: allemand)  
  Template `i18n/de.json` comme exemple pour la communauté

---

## 📋 Tests à écrire

- [ ] **TEST01** — `tests/test_routes.py` — Tests Flask avec client de test
- [ ] **TEST02** — `tests/test_validator.py` — settings, héritage, deepcopy
- [ ] **TEST03** — `tests/test_mod_importer.py` — zip valide, fusion vanilla
- [ ] **TEST04** — `tests/test_sync_manager.py` — sync avec version forcée

---

## 📝 Documentation

- [ ] **DOC01** — Section "Adding a new language" dans `README.md`
- [ ] **DOC02** — Section exhaustive `config/settings.toml` dans `README.md`
- [ ] **DOC03** — Docstrings dans `api/routes.py` helpers privés
