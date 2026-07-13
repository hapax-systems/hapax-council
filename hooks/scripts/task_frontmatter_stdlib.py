"""Conservative stdlib-only YAML frontmatter parser for safety hooks.

The canonical parser uses PyYAML. Safety hooks also run under a bare system
Python, so this module accepts only the block/flow subset used by governance
notes and rejects every construct it cannot prove equivalent. Unsupported YAML
is a HOLD, never a partially parsed authorization decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


class FrontmatterSubsetError(ValueError):
    """The document is outside the proven stdlib YAML subset."""


class DuplicateKeyError(FrontmatterSubsetError):
    """A mapping contains the same semantic key more than once."""

    def __init__(self, key: str, line: int) -> None:
        self.key = key
        self.line = line
        super().__init__(f"duplicate mapping key {key!r} at line {line}")


@dataclass(frozen=True)
class ParsedFrontmatter:
    fields: dict[str, Any]
    body: str


@dataclass(frozen=True)
class _Line:
    number: int
    indent: int
    content: str


_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")
_INT_RE = re.compile(r"[-+]?(?:0|[1-9][0-9]*)\Z")
_FLOAT_RE = re.compile(r"[-+]?(?:(?:0|[1-9][0-9]*)\.[0-9]+)(?:[eE][-+]?[0-9]+)?\Z")
_BLOCK_SCALAR_RE = re.compile(r"[|>](?:[+-][1-9]?|[1-9][+-]?)?\Z")
_AMBIGUOUS_BOOL = {"y", "yes", "n", "no", "on", "off"}
_UNPROVEN_BLOCK_SCALAR = "__HAPAX_UNPROVEN_BLOCK_SCALAR__"


def parse_frontmatter_document(content: str) -> ParsedFrontmatter:
    """Parse one Markdown document or raise on any unproven YAML construct."""

    physical = content.splitlines(keepends=True)
    if not physical or physical[0].rstrip("\r\n") != "---":
        raise FrontmatterSubsetError("note must start with an exact '---' marker")

    closing = None
    for index, line in enumerate(physical[1:], start=1):
        if line.rstrip("\r\n") == "---":
            closing = index
            break
    if closing is None:
        raise FrontmatterSubsetError("note frontmatter must close with an exact '---' marker")

    frontmatter = "".join(physical[1:closing])
    body = "".join(physical[closing + 1 :])
    fields = _BlockParser(frontmatter).parse()
    return ParsedFrontmatter(fields=fields, body=body)


def scalar_text(value: Any) -> str:
    """Normalize a parsed scalar to the text representation gates compare."""

    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return ""


def string_list(value: Any) -> list[str]:
    """Return a list only when every member is a scalar string-like value."""

    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = scalar_text(item)
        if not text or isinstance(item, (dict, list)):
            return []
        result.append(text)
    return result


class _BlockParser:
    def __init__(self, source: str) -> None:
        self.lines: list[_Line] = []
        for number, raw in enumerate(source.splitlines(), start=1):
            prefix = raw[: len(raw) - len(raw.lstrip(" \t"))]
            if "\t" in prefix:
                raise FrontmatterSubsetError(f"tab indentation at line {number}")
            content = raw[len(prefix) :]
            if not content or content.startswith("#"):
                continue
            self.lines.append(_Line(number=number, indent=len(prefix), content=content))
        self.index = 0

    def parse(self) -> dict[str, Any]:
        if not self.lines:
            return {}
        if self.lines[0].indent != 0:
            raise FrontmatterSubsetError("frontmatter root must start at indentation zero")
        value = self._parse_block(0)
        if self.index != len(self.lines):
            line = self.lines[self.index]
            raise FrontmatterSubsetError(f"unexpected content at line {line.number}")
        if not isinstance(value, dict):
            raise FrontmatterSubsetError("frontmatter root must be a mapping")
        return value

    def _parse_block(self, indent: int) -> Any:
        line = self.lines[self.index]
        if line.indent != indent:
            raise FrontmatterSubsetError(
                f"inconsistent indentation at line {line.number}: expected {indent}"
            )
        if line.content == "-" or line.content.startswith("- "):
            return self._parse_sequence(indent)
        return self._parse_mapping(indent)

    def _parse_mapping(self, indent: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while self.index < len(self.lines):
            line = self.lines[self.index]
            if line.indent < indent:
                break
            if line.indent > indent:
                raise FrontmatterSubsetError(f"unexpected indentation at line {line.number}")
            if line.content == "-" or line.content.startswith("- "):
                raise FrontmatterSubsetError(f"sequence item in mapping at line {line.number}")
            self.index += 1
            key, raw_value = _split_mapping_pair(line.content, line.number)
            if key in result:
                raise DuplicateKeyError(key, line.number)
            result[key] = self._parse_pair_value(raw_value, indent, line.number)
        return result

    def _parse_sequence(self, indent: int) -> list[Any]:
        result: list[Any] = []
        while self.index < len(self.lines):
            line = self.lines[self.index]
            if line.indent < indent:
                break
            if line.indent > indent:
                raise FrontmatterSubsetError(f"unexpected indentation at line {line.number}")
            if line.content == "-":
                rest = ""
            elif line.content.startswith("- "):
                rest = line.content[2:]
            else:
                break
            self.index += 1
            rest = _strip_comment(rest).strip()
            if not rest:
                if self.index < len(self.lines) and self.lines[self.index].indent > indent:
                    result.append(self._parse_block(self.lines[self.index].indent))
                else:
                    result.append(None)
                continue

            pair = _try_mapping_pair(rest, line.number)
            if pair is None:
                value = _parse_inline_value(rest, line.number)
                if self.index < len(self.lines) and self.lines[self.index].indent > indent:
                    raise FrontmatterSubsetError(
                        f"multiline plain sequence scalar is unsupported at line {line.number}"
                    )
                result.append(value)
                continue

            virtual_indent = indent + 2
            item: dict[str, Any] = {}
            key, raw_value = pair
            item[key] = self._parse_pair_value(raw_value, virtual_indent, line.number)
            while self.index < len(self.lines):
                continuation = self.lines[self.index]
                if continuation.indent <= indent:
                    break
                if continuation.indent != virtual_indent:
                    raise FrontmatterSubsetError(
                        f"inconsistent sequence mapping indentation at line {continuation.number}"
                    )
                if continuation.content == "-" or continuation.content.startswith("- "):
                    raise FrontmatterSubsetError(
                        f"unexpected nested sequence at line {continuation.number}"
                    )
                self.index += 1
                key, raw_value = _split_mapping_pair(continuation.content, continuation.number)
                if key in item:
                    raise DuplicateKeyError(key, continuation.number)
                item[key] = self._parse_pair_value(raw_value, virtual_indent, continuation.number)
            result.append(item)
        return result

    def _parse_pair_value(self, raw_value: str, indent: int, line_number: int) -> Any:
        candidate = raw_value.strip()
        if candidate.startswith(('"', "'")):
            end = _quoted_token_end(candidate)
            if end is None:
                if self.index < len(self.lines) and self.lines[self.index].indent > indent:
                    return self._parse_multiline_inline(candidate, indent, line_number)
                raise FrontmatterSubsetError(f"unterminated quoted scalar at line {line_number}")
            remainder = candidate[end:].strip()
            if remainder and not remainder.startswith("#"):
                raise FrontmatterSubsetError(
                    f"trailing quoted scalar content at line {line_number}"
                )
            return _parse_quoted(candidate[:end], line_number)

        value = _strip_comment(candidate).strip()
        if not value:
            if self.index < len(self.lines):
                child = self.lines[self.index]
                if child.indent == indent and (
                    child.content == "-" or child.content.startswith("- ")
                ):
                    # PyYAML accepts indentless sequences as mapping values.
                    return self._parse_sequence(indent)
                if child.indent > indent:
                    if child.content == "-" or child.content.startswith("- "):
                        return self._parse_sequence(child.indent)
                    if _try_mapping_pair(child.content, child.number) is not None:
                        return self._parse_mapping(child.indent)
                    return self._parse_multiline_inline("", indent, line_number)
            return None
        if _BLOCK_SCALAR_RE.fullmatch(value):
            # Governance fields never use block scalars. Consume the complete
            # scalar but project a non-null sentinel so required/nullish checks
            # both HOLD. Reproducing YAML folding here would widen the subset.
            while self.index < len(self.lines) and self.lines[self.index].indent > indent:
                self.index += 1
            return _UNPROVEN_BLOCK_SCALAR
        if self.index < len(self.lines) and self.lines[self.index].indent > indent:
            return self._parse_multiline_inline(value, indent, line_number)
        return _parse_inline_value(value, line_number)

    def _parse_multiline_inline(self, first: str, indent: int, line_number: int) -> Any:
        parts = [first] if first else []
        while self.index < len(self.lines) and self.lines[self.index].indent > indent:
            continuation = self.lines[self.index]
            parts.append(continuation.content.strip())
            self.index += 1
        combined = " ".join(part for part in parts if part).strip()
        if not combined:
            return None
        return _parse_inline_value(combined, line_number)


def _split_mapping_pair(text: str, line_number: int) -> tuple[str, str]:
    pair = _try_mapping_pair(text, line_number)
    if pair is None:
        raise FrontmatterSubsetError(f"malformed mapping entry at line {line_number}")
    return pair


def _try_mapping_pair(text: str, line_number: int) -> tuple[str, str] | None:
    quote = ""
    escaped = False
    depth = 0
    for index, character in enumerate(text):
        if quote == '"':
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            continue
        if quote == "'":
            if character == "'":
                if index + 1 < len(text) and text[index + 1] == "'":
                    continue
                quote = ""
            continue
        if character in {'"', "'"}:
            quote = character
        elif character in "[{":
            depth += 1
        elif character in "]}":
            depth -= 1
            if depth < 0:
                raise FrontmatterSubsetError(f"unbalanced flow collection at line {line_number}")
        elif (
            character == ":"
            and depth == 0
            and (index + 1 == len(text) or text[index + 1].isspace())
        ):
            key = _parse_key(text[:index].strip(), line_number)
            return key, text[index + 1 :]
    if quote:
        raise FrontmatterSubsetError(f"unterminated quoted value at line {line_number}")
    return None


def _parse_key(raw: str, line_number: int) -> str:
    if not raw or raw in {"?", "<<"}:
        raise FrontmatterSubsetError(f"unsupported mapping key at line {line_number}")
    if raw[0] in {'"', "'"}:
        key = _parse_quoted(raw, line_number)
    else:
        key = raw
    if not isinstance(key, str) or not key:
        raise FrontmatterSubsetError(f"unsupported mapping key {key!r} at line {line_number}")
    if not _KEY_RE.fullmatch(key):
        if key[0] in "-?:,[]{}#&*!|>@`" or any(marker in key for marker in (":", "#")):
            raise FrontmatterSubsetError(f"unsupported mapping key {key!r} at line {line_number}")
        if _INT_RE.fullmatch(key) or _FLOAT_RE.fullmatch(key):
            raise FrontmatterSubsetError(
                f"numeric YAML mapping key {key!r} is unsupported at line {line_number}"
            )
    if key.lower() in _AMBIGUOUS_BOOL | {"true", "false", "null"}:
        raise FrontmatterSubsetError(f"ambiguous YAML mapping key {key!r} at line {line_number}")
    return key


def _strip_comment(value: str) -> str:
    quote = ""
    escaped = False
    depth = 0
    for index, character in enumerate(value):
        if quote == '"':
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            continue
        if quote == "'":
            if character == "'":
                if index + 1 < len(value) and value[index + 1] == "'":
                    continue
                quote = ""
            continue
        if character in {'"', "'"}:
            previous = value[:index].rstrip()
            if not previous or previous[-1] in "[{,:":
                quote = character
        elif character in "[{":
            depth += 1
        elif character in "]}":
            depth -= 1
        elif character == "#" and depth == 0 and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    if quote:
        raise FrontmatterSubsetError("unterminated quoted scalar")
    return value


def _parse_inline_value(value: str, line_number: int) -> Any:
    value = _strip_comment(value).strip()
    if not value:
        return None
    if value[0] in "[{":
        return _FlowParser(value, line_number).parse()
    if value[0] in {'"', "'"}:
        return _parse_quoted(value, line_number)
    return _parse_plain(value, line_number)


def _parse_quoted(value: str, line_number: int) -> str:
    if value.startswith('"'):
        end = _quoted_token_end(value)
        if end != len(value):
            raise FrontmatterSubsetError(f"invalid double-quoted scalar at line {line_number}")
        return _decode_double_quoted(value[1:-1], line_number)
    if len(value) < 2 or not value.endswith("'"):
        raise FrontmatterSubsetError(f"unterminated single-quoted scalar at line {line_number}")
    return value[1:-1].replace("''", "'")


def _quoted_token_end(value: str) -> int | None:
    if not value or value[0] not in {'"', "'"}:
        return None
    quote = value[0]
    index = 1
    while index < len(value):
        character = value[index]
        if quote == '"' and character == "\\":
            index += 2
            continue
        if character == quote:
            if quote == "'" and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            return index + 1
        index += 1
    return None


def _decode_double_quoted(inner: str, line_number: int) -> str:
    escapes = {
        "0": "\0",
        "a": "\a",
        "b": "\b",
        "t": "\t",
        "n": "\n",
        "v": "\v",
        "f": "\f",
        "r": "\r",
        "e": "\x1b",
        " ": " ",
        '"': '"',
        "/": "/",
        "\\": "\\",
        "N": "\u0085",
        "_": "\u00a0",
        "L": "\u2028",
        "P": "\u2029",
    }
    result: list[str] = []
    index = 0
    while index < len(inner):
        character = inner[index]
        if character != "\\":
            result.append(character)
            index += 1
            continue
        if index + 1 >= len(inner):
            raise FrontmatterSubsetError(f"trailing escape at line {line_number}")
        marker = inner[index + 1]
        if marker in escapes:
            result.append(escapes[marker])
            index += 2
            continue
        widths = {"x": 2, "u": 4, "U": 8}
        width = widths.get(marker)
        if width is None:
            raise FrontmatterSubsetError(
                f"unsupported double-quoted escape \\{marker} at line {line_number}"
            )
        digits = inner[index + 2 : index + 2 + width]
        if len(digits) != width or not re.fullmatch(r"[0-9A-Fa-f]+", digits):
            raise FrontmatterSubsetError(f"invalid Unicode escape at line {line_number}")
        try:
            result.append(chr(int(digits, 16)))
        except ValueError as exc:
            raise FrontmatterSubsetError(f"invalid Unicode escape at line {line_number}") from exc
        index += 2 + width
    return "".join(result)


def _parse_plain(value: str, line_number: int) -> Any:
    if value[0] in "&*!@`" or value in {"---", "..."}:
        raise FrontmatterSubsetError(
            f"anchors, aliases, tags, and directives are unsupported at line {line_number}"
        )
    if re.search(r":(?:\s|$)", value):
        raise FrontmatterSubsetError(f"mapping syntax in plain scalar at line {line_number}")
    lowered = value.lower()
    if lowered in _AMBIGUOUS_BOOL:
        raise FrontmatterSubsetError(f"ambiguous YAML boolean {value!r} at line {line_number}")
    if lowered in {"null", "~"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if _INT_RE.fullmatch(value):
        return int(value)
    if _FLOAT_RE.fullmatch(value):
        return float(value)
    if re.fullmatch(r"[-+]?0[0-9]+", value):
        raise FrontmatterSubsetError(f"ambiguous leading-zero number at line {line_number}")
    return value


class _FlowParser:
    def __init__(self, source: str, line_number: int) -> None:
        self.source = source
        self.line_number = line_number
        self.index = 0

    def parse(self) -> Any:
        value = self._value()
        self._space()
        if self.index != len(self.source):
            raise self._error("trailing flow content")
        return value

    def _value(self) -> Any:
        self._space()
        if self.index >= len(self.source):
            raise self._error("missing flow value")
        character = self.source[self.index]
        if character == "[":
            return self._list()
        if character == "{":
            return self._mapping()
        if character in {'"', "'"}:
            return self._quoted()
        start = self.index
        while self.index < len(self.source) and self.source[self.index] not in ",]}:":
            self.index += 1
        token = self.source[start : self.index].strip()
        if not token:
            raise self._error("empty flow scalar")
        return _parse_plain(token, self.line_number)

    def _list(self) -> list[Any]:
        self.index += 1
        result: list[Any] = []
        self._space()
        if self._take("]"):
            return result
        while True:
            result.append(self._value())
            self._space()
            if self._take("]"):
                return result
            if not self._take(","):
                raise self._error("expected ',' or ']' in flow list")
            self._space()
            if self._take("]"):
                return result

    def _mapping(self) -> dict[str, Any]:
        self.index += 1
        result: dict[str, Any] = {}
        self._space()
        if self._take("}"):
            return result
        while True:
            key = self._flow_key()
            self._space()
            if not self._take(":"):
                raise self._error("expected ':' in flow mapping")
            value = self._value()
            if key in result:
                raise DuplicateKeyError(key, self.line_number)
            result[key] = value
            self._space()
            if self._take("}"):
                return result
            if not self._take(","):
                raise self._error("expected ',' or '}' in flow mapping")
            self._space()
            if self._take("}"):
                return result

    def _flow_key(self) -> str:
        self._space()
        if self.index >= len(self.source):
            raise self._error("missing flow mapping key")
        if self.source[self.index] in {'"', "'"}:
            return _parse_key(self._quoted(), self.line_number)
        start = self.index
        while self.index < len(self.source) and self.source[self.index] not in ":,{}[]":
            self.index += 1
        return _parse_key(self.source[start : self.index].strip(), self.line_number)

    def _quoted(self) -> str:
        quote = self.source[self.index]
        start = self.index
        self.index += 1
        while self.index < len(self.source):
            character = self.source[self.index]
            if quote == '"' and character == "\\":
                self.index += 2
                continue
            if character == quote:
                if quote == "'" and self.index + 1 < len(self.source):
                    if self.source[self.index + 1] == "'":
                        self.index += 2
                        continue
                self.index += 1
                return _parse_quoted(self.source[start : self.index], self.line_number)
            self.index += 1
        raise self._error("unterminated quoted flow scalar")

    def _space(self) -> None:
        while self.index < len(self.source) and self.source[self.index].isspace():
            self.index += 1

    def _take(self, character: str) -> bool:
        if self.index < len(self.source) and self.source[self.index] == character:
            self.index += 1
            return True
        return False

    def _error(self, message: str) -> FrontmatterSubsetError:
        return FrontmatterSubsetError(f"{message} at line {self.line_number}")
