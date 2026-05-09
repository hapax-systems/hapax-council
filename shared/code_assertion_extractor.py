"""Extract assertions from Python source code via ast.

Three extraction strategies:
1. assert statements → INVARIANT assertions
2. Docstrings containing MUST/NEVER/ALWAYS → CONSTRAINT assertions
3. Pydantic @field_validator / @model_validator → CONSTRAINT assertions
"""

from __future__ import annotations

import ast
import re
import textwrap
from pathlib import Path

from shared.assertion_model import (
    Assertion,
    AssertionType,
    ProvenanceRecord,
    SourceType,
)

_DEONTIC_RE = re.compile(
    r"[^.]*\b(MUST|NEVER|ALWAYS)\b[^.]*[.]",
    re.DOTALL,
)

EXTRACTION_VERSION = "1.0"


def _unparse_safe(node: ast.expr) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return "<unparseable>"


def _source_lines(node: ast.AST) -> tuple[int, int]:
    start = getattr(node, "lineno", 0)
    end = getattr(node, "end_lineno", start)
    return (start, end)


def _docstring_of(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Module,
) -> tuple[str, ast.AST] | None:
    if not node.body:
        return None
    first = node.body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return (first.value.value, first)
    return None


class _AssertVisitor(ast.NodeVisitor):
    def __init__(self, uri: str) -> None:
        self.uri = uri
        self.assertions: list[Assertion] = []

    def visit_Assert(self, node: ast.Assert) -> None:
        test_text = _unparse_safe(node.test)
        msg_text = _unparse_safe(node.msg) if node.msg else ""
        text = f"assert {test_text}"
        if msg_text:
            text += f", {msg_text}"

        self.assertions.append(
            Assertion(
                text=text,
                source_type=SourceType.CODE,
                source_uri=self.uri,
                source_span=_source_lines(node),
                confidence=0.9,
                domain="code",
                assertion_type=AssertionType.INVARIANT,
                provenance=ProvenanceRecord(
                    extraction_method="ast_assert_visitor",
                    extraction_version=EXTRACTION_VERSION,
                ),
            )
        )
        self.generic_visit(node)


class _DocstringVisitor(ast.NodeVisitor):
    def __init__(self, uri: str) -> None:
        self.uri = uri
        self.assertions: list[Assertion] = []

    def _extract_from_docstring(self, owner: ast.AST) -> None:
        result = _docstring_of(owner)  # type: ignore[arg-type]
        if result is None:
            return
        docstring, doc_node = result
        for match in _DEONTIC_RE.finditer(docstring):
            sentence = match.group(0).strip()
            sentence = textwrap.dedent(sentence).replace("\n", " ")
            sentence = re.sub(r"\s+", " ", sentence)
            self.assertions.append(
                Assertion(
                    text=sentence,
                    source_type=SourceType.CODE,
                    source_uri=self.uri,
                    source_span=_source_lines(doc_node),
                    confidence=0.8,
                    domain="code",
                    assertion_type=AssertionType.CONSTRAINT,
                    provenance=ProvenanceRecord(
                        extraction_method="ast_docstring_deontic",
                        extraction_version=EXTRACTION_VERSION,
                    ),
                    tags=[f"keyword:{match.group(1)}"],
                )
            )

    def visit_Module(self, node: ast.Module) -> None:
        self._extract_from_docstring(node)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._extract_from_docstring(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._extract_from_docstring(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._extract_from_docstring(node)
        self.generic_visit(node)


def _decorator_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    return None


def _decorator_args(node: ast.expr) -> list[str]:
    if isinstance(node, ast.Call):
        return [_unparse_safe(a) for a in node.args]
    return []


def _decorator_mode(node: ast.expr) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    for kw in node.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    return None


class _ValidatorVisitor(ast.NodeVisitor):
    _VALIDATOR_DECORATORS = {"field_validator", "model_validator"}

    def __init__(self, uri: str) -> None:
        self.uri = uri
        self.assertions: list[Assertion] = []
        self._class_stack: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for dec in node.decorator_list:
            name = _decorator_name(dec)
            if name not in self._VALIDATOR_DECORATORS:
                continue

            fields = _decorator_args(dec)
            mode = _decorator_mode(dec) or "after"
            cls = self._class_stack[-1] if self._class_stack else "<module>"

            if name == "field_validator":
                field_desc = ", ".join(fields) if fields else "unknown"
                text = f"{cls}.{node.name} validates field(s) {field_desc}"
            else:
                text = f"{cls}.{node.name} model validator (mode={mode})"

            docresult = _docstring_of(node)
            if docresult:
                doc_first_line = docresult[0].strip().split("\n")[0]
                text += f": {doc_first_line}"

            tags = [f"validator_type:{name}", f"mode:{mode}"]
            tags.extend(f"field:{f}" for f in fields)

            self.assertions.append(
                Assertion(
                    text=text,
                    source_type=SourceType.CODE,
                    source_uri=self.uri,
                    source_span=_source_lines(node),
                    confidence=0.85,
                    domain="code",
                    assertion_type=AssertionType.CONSTRAINT,
                    provenance=ProvenanceRecord(
                        extraction_method="ast_pydantic_validator",
                        extraction_version=EXTRACTION_VERSION,
                    ),
                    tags=tags,
                )
            )

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_func(node)


def extract_from_python_file(path: Path) -> list[Assertion]:
    """Extract all assertion types from a single Python file."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    uri = str(path)

    assert_v = _AssertVisitor(uri)
    assert_v.visit(tree)

    doc_v = _DocstringVisitor(uri)
    doc_v.visit(tree)

    val_v = _ValidatorVisitor(uri)
    val_v.visit(tree)

    return assert_v.assertions + doc_v.assertions + val_v.assertions


def extract_from_directory(root: Path, *, exclude_tests: bool = True) -> list[Assertion]:
    """Recursively extract assertions from all Python files under root."""
    results: list[Assertion] = []
    for py_file in sorted(root.rglob("*.py")):
        if exclude_tests and "test" in py_file.name:
            continue
        results.extend(extract_from_python_file(py_file))
    return results
