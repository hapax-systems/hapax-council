#!/usr/bin/env python3
"""Class-closure gate for the unrotated-jsonl-writer disease (audit W0.2).

Every append-mode open of a ``*.jsonl`` path in first-party code must be
covered by the rotation registry (shared/runtime_jsonl_rotator.py TARGETS) or
carry an explicit ``# jsonl-rotation: exempt(<reason>)`` pragma on the same
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


def _mode_is_append(call: ast.Call) -> bool:
    for arg in list(call.args[1:2]) + [k.value for k in call.keywords if k.arg == "mode"]:
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


def check_file(path: Path, covered: set[str], src_lines: list[str]) -> list[str]:
    problems: list[str] = []
    try:
        tree = ast.parse("\n".join(src_lines))
    except SyntaxError:
        return problems
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        is_open = (isinstance(fn, ast.Name) and fn.id == "open") or (
            isinstance(fn, ast.Attribute) and fn.attr == "open"
        )
        if not is_open or not _mode_is_append(node):
            continue
        base = _jsonl_basename(node)
        if base is None and isinstance(fn, ast.Attribute):
            base = _jsonl_basename(fn.value)
        if base is None:
            continue
        line = src_lines[node.lineno - 1] if node.lineno <= len(src_lines) else ""
        if "jsonl-rotation: exempt" in line:
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
        print("or annotate `# jsonl-rotation: exempt(<reason>)`):")
        for p in problems:
            print(f"  {p}")
        return 1
    print(f"jsonl-writer gate: clean ({len(covered)} registered targets)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
