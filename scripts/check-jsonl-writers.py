#!/usr/bin/env python3
"""Class-closure gate for the unrotated-jsonl-writer disease (audit W0.2).

Every append-mode open of a ``*.jsonl`` path in first-party code must be
covered by the rotation registry (shared/runtime_jsonl_rotator.py TARGETS) or
carry an explicit ```` pragma on the same
line. The registry is the single source of truth — coverage is computed FROM
it, so registering a target automatically licenses its writers (generative,
not a second list to drift).

Effect-based per the taxonomy anti-theses: the check walks the AST for the
append-open EFFECT (open/Path.open with mode containing 'a' whose target
expression mentions a .jsonl name), not for blessed function names.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("agents", "shared", "scripts", "logos")


def registry_names() -> set[str]:
    """Basenames covered by the rotation registry (parsed, not imported —
    the gate must not depend on the runtime venv)."""
    src = (REPO / "shared" / "runtime_jsonl_rotator.py").read_text()
    tree = ast.parse(src)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.endswith(".jsonl"):
                names.add(Path(node.value).name)
    return names


def _mode_is_append(call: ast.Call, *, is_method: bool) -> bool:
    """Mode position differs: builtin open(path, mode) vs PATH.open(mode)."""
    idx = 0 if is_method else 1
    candidates = list(call.args[idx : idx + 1]) + [
        k.value for k in call.keywords if k.arg == "mode"
    ]
    for arg in candidates:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and "a" in arg.value:
            return True
    return False


def _jsonl_basename(node: ast.AST) -> str | None:
    """A .jsonl basename mentioned anywhere inside the expression, if any."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and ".jsonl" in sub.value:
            tail = sub.value.rsplit("/", 1)[-1]
            if tail.endswith(".jsonl"):
                return tail
    return None


def _jsonl_name_bindings(tree: ast.AST) -> dict[str, str]:
    """Names bound (anywhere in the module) to expressions that mention a
    .jsonl basename — the codebase's dominant writer idiom is
    ``SOME_FILE = Path(...)/"x.jsonl"`` then ``SOME_FILE.open("a")``
    (dossier finding 2026-06-12: literal-only matching detected ZERO of the
    three original log bombs)."""
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if value is None:
            continue
        base = _jsonl_basename(value)
        if base is None:
            continue
        for tgt in targets:
            if isinstance(tgt, ast.Name):
                bindings[tgt.id] = base
            elif isinstance(tgt, ast.Attribute):
                bindings[tgt.attr] = base
    return bindings


def check_file(path: Path, covered: set[str], src_lines: list[str]) -> list[str]:
    problems: list[str] = []
    try:
        tree = ast.parse("\n".join(src_lines))
    except SyntaxError:
        return problems
    bindings = _jsonl_name_bindings(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        is_builtin_open = isinstance(fn, ast.Name) and fn.id == "open"
        is_method_open = isinstance(fn, ast.Attribute) and fn.attr == "open"
        if not (is_builtin_open or is_method_open):
            continue
        if not _mode_is_append(node, is_method=is_method_open):
            continue
        base = _jsonl_basename(node)
        if base is None and isinstance(fn, ast.Attribute):
            base = _jsonl_basename(fn.value)
            # the dominant idiom: NAME.open("a") / self.NAME.open("a") where
            # NAME was bound to a .jsonl path elsewhere in the module
            if base is None:
                inner = fn.value
                if isinstance(inner, ast.Name):
                    base = bindings.get(inner.id)
                elif isinstance(inner, ast.Attribute):
                    base = bindings.get(inner.attr)
        if base is None:
            continue
        # pragma on the call line OR the immediately preceding comment line
        # (ruff-format rewraps long trailing comments; standalone lines are stable)
        window = src_lines[max(0, node.lineno - 2) : node.lineno]
        if any("jsonl-rotation: exempt" in ln for ln in window):
            continue
        if base not in covered:
            problems.append(
                f"{path.relative_to(REPO)}:{node.lineno}: append-mode jsonl writer "
                f"'{base}' has no rotation-registry target and no exempt pragma"
            )
    return problems


def main() -> int:
    covered = registry_names()
    problems: list[str] = []
    for d in SCAN_DIRS:
        root = REPO / d
        if not root.is_dir():
            continue
        for py in root.rglob("*.py"):
            src_lines = py.read_text(errors="replace").splitlines()
            problems.extend(check_file(py, covered, src_lines))
    if problems:
        print("Unrotated jsonl writers (register in runtime_jsonl_rotator.TARGETS")
        print("or annotate ``):")
        for p in problems:
            print(f"  {p}")
        return 1
    print(f"jsonl-writer gate: clean ({len(covered)} registered targets)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
