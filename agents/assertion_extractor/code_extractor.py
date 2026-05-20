"""AST-based assertion extractor for Python source files.

Extracts assert statements, docstring MUST/NEVER/ALWAYS directives,
Pydantic validator signatures, and invariant comments. Each extraction
produces an Assertion record with full provenance.
"""

from __future__ import annotations

import ast
import hashlib
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from shared.assertion_model import (
    Assertion,
    AssertionType,
    GovernanceStatus,
    ProvenanceRecord,
    SourceType,
)

log = logging.getLogger(__name__)

DIRECTIVE_PATTERN = re.compile(
    r"\b(MUST|NEVER|ALWAYS|SHALL|SHALL NOT|REQUIRED|PROHIBITED|INVARIANT)\b",
    re.IGNORECASE,
)
INVARIANT_COMMENT_PATTERN = re.compile(
    r"#\s*(INVARIANT|PROTECTED|MANDATORY|NEVER|MUST|ALWAYS)[:\s]",
    re.IGNORECASE,
)
PYDANTIC_VALIDATOR_DECORATORS = frozenset(
    {"validator", "field_validator", "model_validator", "root_validator"}
)


def _content_hash(text: str, source: str, line: int) -> str:
    raw = f"{source}:{line}:{text}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def extract_from_python_file(path: Path, *, repo_root: Path | None = None) -> list[Assertion]:
    """Extract assertions from a single Python file."""
    try:
        source_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    try:
        tree = ast.parse(source_text, filename=str(path))
    except SyntaxError:
        return []

    rel_path = (
        str(path.relative_to(repo_root))
        if repo_root and path.is_relative_to(repo_root)
        else str(path)
    )
    now = datetime.now(UTC)
    results: list[Assertion] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            text = ast.get_source_segment(source_text, node) or "assert ..."
            results.append(
                Assertion(
                    assertion_id=f"code-assert-{_content_hash(text, rel_path, node.lineno)}",
                    text=text.strip(),
                    source_type=SourceType.CODE,
                    source_uri=rel_path,
                    source_line=node.lineno,
                    assertion_type=AssertionType.INVARIANT,
                    governance_status=GovernanceStatus.DERIVED,
                    provenance=ProvenanceRecord(
                        extraction_method="ast_assert_visitor", extracted_at=now
                    ),
                    tags=["assert_statement"],
                )
            )

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            docstring = ast.get_docstring(node)
            if docstring:
                for match in DIRECTIVE_PATTERN.finditer(docstring):
                    line_offset = docstring[: match.start()].count("\n")
                    line_no = getattr(node, "lineno", 1) + line_offset + 1
                    ctx_start = max(0, match.start() - 40)
                    ctx_end = min(len(docstring), match.end() + 80)
                    context = docstring[ctx_start:ctx_end].strip()
                    results.append(
                        Assertion(
                            assertion_id=f"code-directive-{_content_hash(context, rel_path, line_no)}",
                            text=context,
                            source_type=SourceType.CODE,
                            source_uri=rel_path,
                            source_line=line_no,
                            assertion_type=AssertionType.CONSTRAINT,
                            governance_status=GovernanceStatus.DERIVED,
                            provenance=ProvenanceRecord(
                                extraction_method="docstring_directive", extracted_at=now
                            ),
                            tags=["docstring_directive", match.group(1).lower()],
                        )
                    )

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                dec_name = ""
                if isinstance(decorator, ast.Name):
                    dec_name = decorator.id
                elif isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name):
                    dec_name = decorator.func.id
                elif isinstance(decorator, ast.Attribute):
                    dec_name = decorator.attr
                elif isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                    dec_name = decorator.func.attr

                if dec_name in PYDANTIC_VALIDATOR_DECORATORS:
                    text = f"@{dec_name} {node.name}"
                    results.append(
                        Assertion(
                            assertion_id=f"code-validator-{_content_hash(text, rel_path, node.lineno)}",
                            text=text,
                            source_type=SourceType.CODE,
                            source_uri=rel_path,
                            source_line=node.lineno,
                            assertion_type=AssertionType.CONSTRAINT,
                            governance_status=GovernanceStatus.DERIVED,
                            provenance=ProvenanceRecord(
                                extraction_method="pydantic_validator", extracted_at=now
                            ),
                            tags=["pydantic_validator", dec_name],
                        )
                    )

    for line_no, line in enumerate(source_text.splitlines(), 1):
        match = INVARIANT_COMMENT_PATTERN.search(line)
        if match:
            comment_text = line[line.index("#") + 1 :].strip()
            results.append(
                Assertion(
                    assertion_id=f"code-comment-{_content_hash(comment_text, rel_path, line_no)}",
                    text=comment_text,
                    source_type=SourceType.CODE,
                    source_uri=rel_path,
                    source_line=line_no,
                    assertion_type=AssertionType.INVARIANT,
                    governance_status=GovernanceStatus.DERIVED,
                    provenance=ProvenanceRecord(
                        extraction_method="invariant_comment", extracted_at=now
                    ),
                    tags=["invariant_comment"],
                )
            )

    return results


def extract_from_directory(
    root: Path,
    *,
    repo_root: Path | None = None,
    extensions: frozenset[str] = frozenset({".py"}),
) -> list[Assertion]:
    """Extract assertions from all Python files in a directory tree."""
    all_assertions: list[Assertion] = []
    seen_ids: set[str] = set()

    for path in sorted(root.rglob("*")):
        if path.suffix not in extensions:
            continue
        if "__pycache__" in path.parts or ".venv" in path.parts:
            continue
        for assertion in extract_from_python_file(path, repo_root=repo_root):
            if assertion.assertion_id not in seen_ids:
                seen_ids.add(assertion.assertion_id)
                all_assertions.append(assertion)

    return all_assertions


__all__ = [
    "extract_from_directory",
    "extract_from_python_file",
]
