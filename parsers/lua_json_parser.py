"""
parsers/lua_json_parser.py
==========================
Parser Lua simplifié pour les fichiers de prototypes Factorio.

Stratégie : on ne parse pas du Lua générique.
On cible le sous-ensemble utilisé dans base/prototypes/ :
  - Tables littérales  { key = value, ... }
  - Listes             { value, value, ... }
  - Strings            "...", '...' ou [[...]]
  - Nombres            42, 3.14, -1
  - Booléens           true, false
  - nil
  - Références simples  defines.xxx, "string-id"

Ce qu'on ne supporte PAS (et c'est voulu pour le MVP) :
  - Appels de fonctions complexes
  - Métatables
  - Héritage Lua OOP
  - data:extend() → géré séparément dans prototype_parser.py

Pour les cas complexes, envisager lupa (LuaJIT binding) en phase 2.
"""

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("factorio_hub.parsers.lua")

# ---------------------------------------------------------------------------
# Tokenizer léger
# ---------------------------------------------------------------------------

_RE_COMMENT_LINE  = re.compile(r"--[^\[\n][^\n]*")
_RE_COMMENT_BLOCK = re.compile(r"--\[\[.*?\]\]", re.DOTALL)
_RE_NUMBER        = re.compile(r"^-?\d+(\.\d+)?([eE][+-]?\d+)?$")
_RE_STRING_DQ     = re.compile(r'"((?:[^"\\]|\\.)*)"')
_RE_STRING_SQ     = re.compile(r"'((?:[^'\\]|\\.)*)'")
_RE_STRING_LONG   = re.compile(r"\[\[([^\]]*(?:\][^\]]+)*)\]\]", re.DOTALL)
_RE_IDENT         = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]*$")


def strip_comments(source: str) -> str:
    """Retire les commentaires Lua (ligne et bloc)."""
    source = _RE_COMMENT_BLOCK.sub("", source)
    source = _RE_COMMENT_LINE.sub("", source)
    return source


# ---------------------------------------------------------------------------
# Extraction des blocs data:extend(...)
# ---------------------------------------------------------------------------

def extract_data_extend_blocks(source: str) -> list[str]:
    """
    Extrait les blocs passés à data:extend({...}).
    Retourne une liste de chaînes représentant le contenu de chaque table.

    Exemple :
        data:extend({ {type="item", name="foo"} })
        → [' {type="item", name="foo"} ']
    """
    results = []
    pattern = re.compile(r"data\s*:\s*extend\s*\(", re.DOTALL)

    for match in pattern.finditer(source):
        start = match.end()
        # Trouve la parenthèse fermante correspondante
        depth = 1
        i = start
        while i < len(source) and depth > 0:
            c = source[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            i += 1
        if depth == 0:
            results.append(source[start : i - 1])

    return results


# ---------------------------------------------------------------------------
# Parser de table Lua
# ---------------------------------------------------------------------------

class LuaTableParser:
    """
    Parse une chaîne représentant une table Lua en dict/list Python.

    Usage :
        parser = LuaTableParser()
        result = parser.parse('{ name = "iron-plate", stack_size = 100 }')
        # → {"name": "iron-plate", "stack_size": 100}
    """

    def __init__(self):
        self.source = ""
        self.pos    = 0

    def parse(self, source: str) -> Any:
        self.source = source.strip()
        self.pos    = 0
        return self._parse_value()

    def _peek(self) -> str:
        self._skip_ws()
        if self.pos < len(self.source):
            return self.source[self.pos]
        return ""

    def _skip_ws(self) -> None:
        while self.pos < len(self.source) and self.source[self.pos] in " \t\n\r":
            self.pos += 1

    def _consume(self, expected: str) -> None:
        self._skip_ws()
        if not self.source.startswith(expected, self.pos):
            ctx = self.source[max(0, self.pos - 20) : self.pos + 20]
            raise SyntaxError(
                f"Attendu '{expected}' à pos {self.pos}, contexte: ...{ctx}..."
            )
        self.pos += len(expected)

    def _parse_value(self) -> Any:
        self._skip_ws()
        if self.pos >= len(self.source):
            return None

        c = self.source[self.pos]

        if c == "{":
            return self._parse_table()
        if c == '"':
            return self._parse_string_dq()
        if c == "'":
            return self._parse_string_sq()
        if self.source.startswith("[[", self.pos):
            return self._parse_string_long()
        if self.source.startswith("true", self.pos) and not self._is_ident_char_at(self.pos + 4):
            self.pos += 4
            return True
        if self.source.startswith("false", self.pos) and not self._is_ident_char_at(self.pos + 5):
            self.pos += 5
            return False
        if self.source.startswith("nil", self.pos) and not self._is_ident_char_at(self.pos + 3):
            self.pos += 3
            return None
        if c == "-" or c.isdigit():
            return self._parse_number()

        # Référence (defines.xxx, variable, etc.) → on retourne comme string
        return self._parse_reference()

    def _is_ident_char_at(self, pos: int) -> bool:
        if pos >= len(self.source):
            return False
        c = self.source[pos]
        return c.isalnum() or c == "_"

    def _parse_table(self) -> dict | list:
        self._consume("{")
        result_dict: dict   = {}
        result_list: list   = []
        is_list             = True  # jusqu'à preuve du contraire
        index               = 1

        while True:
            self._skip_ws()
            if self.pos >= len(self.source) or self.source[self.pos] == "}":
                break

            # Détecter si c'est une paire clé=valeur
            # Sauvegarde de position pour backtrack
            saved_pos = self.pos
            key = self._try_parse_key()

            if key is not None:
                # Paire key = value
                is_list = False
                self._skip_ws()
                self._consume("=")
                value = self._parse_value()
                result_dict[key] = value
            else:
                # Valeur positionnelle
                self.pos = saved_pos
                value = self._parse_value()
                result_list.append(value)

            self._skip_ws()
            # Virgule ou point-virgule optionnel
            if self.pos < len(self.source) and self.source[self.pos] in ",;":
                self.pos += 1

        self._consume("}")

        if not is_list and result_dict:
            # Si on a eu des clés ET des valeurs positionnelles : fusion
            for i, v in enumerate(result_list, 1):
                result_dict[i] = v
            return result_dict
        if result_list:
            return result_list
        return result_dict

    def _try_parse_key(self) -> str | int | None:
        """
        Essaie de lire une clé de table (ident ou [expr]).
        Retourne la clé ou None si ce n'est pas une paire clé=valeur.
        """
        self._skip_ws()
        # Clé entre crochets : [42] ou ["string"]
        if self.pos < len(self.source) and self.source[self.pos] == "[":
            saved = self.pos
            self.pos += 1
            try:
                key = self._parse_value()
                self._skip_ws()
                if self.source[self.pos] == "]":
                    self.pos += 1
                    self._skip_ws()
                    if self.pos < len(self.source) and self.source[self.pos] == "=":
                        return str(key)
            except Exception:
                pass
            self.pos = saved
            return None

        # Identifiant nu : name = ...
        start = self.pos
        while self.pos < len(self.source) and (
            self.source[self.pos].isalnum()
            or self.source[self.pos] in "_"
        ):
            self.pos += 1

        if self.pos == start:
            return None

        ident = self.source[start : self.pos]
        self._skip_ws()

        # Vérifie que le prochain char est bien '='
        if self.pos < len(self.source) and self.source[self.pos] == "=":
            # Mais pas '==' (comparaison)
            if self.pos + 1 < len(self.source) and self.source[self.pos + 1] == "=":
                self.pos = start
                return None
            return ident

        # Pas une paire clé=valeur — backtrack
        self.pos = start
        return None

    def _parse_string_dq(self) -> str:
        self._consume('"')
        result = []
        while self.pos < len(self.source):
            c = self.source[self.pos]
            if c == "\\":
                self.pos += 1
                esc = self.source[self.pos] if self.pos < len(self.source) else ""
                result.append(_unescape(esc))
                self.pos += 1
            elif c == '"':
                self.pos += 1
                break
            else:
                result.append(c)
                self.pos += 1
        return "".join(result)

    def _parse_string_sq(self) -> str:
        self._consume("'")
        result = []
        while self.pos < len(self.source):
            c = self.source[self.pos]
            if c == "\\":
                self.pos += 1
                esc = self.source[self.pos] if self.pos < len(self.source) else ""
                result.append(_unescape(esc))
                self.pos += 1
            elif c == "'":
                self.pos += 1
                break
            else:
                result.append(c)
                self.pos += 1
        return "".join(result)

    def _parse_string_long(self) -> str:
        """Parse [[...]] long strings."""
        self.pos += 2  # skip [[
        end = self.source.find("]]", self.pos)
        if end == -1:
            raise SyntaxError("Long string non fermée")
        result = self.source[self.pos : end]
        self.pos = end + 2
        return result

    def _parse_number(self) -> int | float:
        start = self.pos
        if self.pos < len(self.source) and self.source[self.pos] == "-":
            self.pos += 1
        while self.pos < len(self.source) and (
            self.source[self.pos].isdigit()
            or self.source[self.pos] in ".eE+-"
        ):
            self.pos += 1
        token = self.source[start : self.pos]
        try:
            return int(token)
        except ValueError:
            return float(token)

    def _parse_reference(self) -> str:
        """Parse un identifiant Lua (defines.x.y, variable, etc.)"""
        start = self.pos
        while self.pos < len(self.source) and (
            self.source[self.pos].isalnum()
            or self.source[self.pos] in "._"
        ):
            self.pos += 1
        if self.pos == start:
            # Caractère inconnu — skip
            self.pos += 1
            return ""
        return self.source[start : self.pos]


def _unescape(c: str) -> str:
    return {"n": "\n", "t": "\t", "r": "\r", "\\": "\\",
            '"': '"', "'": "'"}.get(c, c)


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------

def parse_lua_file(path: Path) -> list[dict]:
    """
    Parse un fichier Lua de prototypes Factorio.
    Retourne la liste des prototypes trouvés dans les blocs data:extend().
    """
    source = path.read_text(encoding="utf-8")
    source = strip_comments(source)
    blocks = extract_data_extend_blocks(source)

    parser    = LuaTableParser()
    prototypes = []

    for block in blocks:
        try:
            parsed = parser.parse(block)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and "type" in item and "name" in item:
                        prototypes.append(item)
            elif isinstance(parsed, dict) and "type" in parsed:
                prototypes.append(parsed)
        except Exception as e:
            logger.warning("Erreur parsing bloc dans %s : %s", path.name, e)

    logger.debug("%s → %d prototypes extraits", path.name, len(prototypes))
    return prototypes


def parse_lua_string(source: str) -> Any:
    """Parse directement une chaîne Lua (pour tests)."""
    source = strip_comments(source)
    return LuaTableParser().parse(source)