#!/usr/bin/env python3
"""Class-closure gate for the unrotated-jsonl-writer disease (audit W0.2).

Every append-mode open of a ``*.jsonl`` path in first-party code must be
covered by the rotation registry (``shared/runtime_jsonl_rotator.py``
``DEFAULT_TARGETS``) or carry an explicit
``# jsonl-rotation: exempt(<reason>)`` pragma. The registry is the single
source of truth — coverage is computed FROM it, so registering a target
automatically licenses its writers without a second drift-prone list.

Effect-based per the taxonomy anti-theses: the check walks the AST for the
append-open EFFECT (open/Path.open with mode containing 'a' whose target
expression mentions a .jsonl name), not for blessed function names.
"""

from __future__ import annotations

import ast
import posixpath
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("agents", "shared", "scripts", "logos")


def _normalize_path(parts: list[str]) -> str | None:
    useful = [part for part in parts if part]
    if not useful or not any(part.endswith(".jsonl") or ".jsonl" in part for part in useful):
        return None
    path = useful[0]
    for part in useful[1:]:
        path = posixpath.join(path, part)
    path = path.replace("\\", "/")
    if ".jsonl" not in path:
        return None
    path = path[: path.index(".jsonl") + len(".jsonl")]
    if "/" not in path:
        return Path(path).name
    return posixpath.normpath(path)


def _path_parts(node: ast.AST, bindings: dict[str, list[str]]) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Name):
        return bindings.get(node.id, [])
    if isinstance(node, ast.Attribute):
        return bindings.get(node.attr, [])
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _path_parts(node.left, bindings) + _path_parts(node.right, bindings)
    if isinstance(node, ast.IfExp):
        body = _path_parts(node.body, bindings)
        orelse = _path_parts(node.orelse, bindings)
        if body and orelse and body != orelse:
            return []
        return body or orelse
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id in bindings and not node.args:
            return bindings[func.id]
        if isinstance(func, ast.Name) and func.id == "Path" and node.args:
            return _path_parts(node.args[0], bindings)
        if isinstance(func, ast.Attribute):
            if func.attr in {"expanduser", "resolve"}:
                return _path_parts(func.value, bindings)
            if func.attr == "get" and len(node.args) >= 2:
                return _path_parts(node.args[1], bindings)
        return []
    return []


def _path_expr(node: ast.AST, bindings: dict[str, list[str]]) -> str | None:
    return _normalize_path(_path_parts(node, bindings))


def _path_name_bindings(tree: ast.AST) -> dict[str, list[str]]:
    """Names bound to literal path fragments.

    The codebase commonly builds paths as ``DIR = Path("/x")`` and
    ``FILE = DIR / "y.jsonl"``. Binding the directory name lets the checker
    distinguish unrelated ``events.jsonl`` ledgers by path suffix.
    """

    bindings: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            positional_args = list(node.args.posonlyargs) + list(node.args.args)
            positional_defaults = [None] * (len(positional_args) - len(node.args.defaults)) + list(
                node.args.defaults
            )
            for arg, default in zip(positional_args, positional_defaults, strict=True):
                if default is None:
                    continue
                parts = _path_parts(default, bindings)
                if parts:
                    bindings[arg.arg] = parts
            for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True):
                if default is None:
                    continue
                parts = _path_parts(default, bindings)
                if parts:
                    bindings[arg.arg] = parts
            local_bindings = dict(bindings)
            bound_return = False
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    parts = _path_parts(stmt.value, local_bindings)
                    if not parts:
                        continue
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            local_bindings[target.id] = parts
                elif isinstance(stmt, ast.Return) and stmt.value is not None:
                    parts = _path_parts(stmt.value, local_bindings)
                    if parts:
                        bindings[node.name] = parts
                        bound_return = True
                    break
            if not bound_return:
                for child in ast.walk(node):
                    if not isinstance(child, ast.Return) or child.value is None:
                        continue
                    parts = _path_parts(child.value, local_bindings)
                    if parts:
                        bindings[node.name] = parts
                    break
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if value is None:
            continue
        parts = _path_parts(value, bindings)
        if not parts:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                bindings[target.id] = parts
            elif isinstance(target, ast.Attribute):
                bindings[target.attr] = parts
    return bindings


def registry_paths() -> set[str]:
    """Path suffixes covered by the rotation registry.

    Parsed, not imported: the gate must not depend on the runtime venv.
    """
    src = (REPO / "shared" / "runtime_jsonl_rotator.py").read_text()
    tree = ast.parse(src)
    bindings = _path_name_bindings(tree)
    paths: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not isinstance(fn, ast.Name) or fn.id != "RotationTarget":
            continue
        for keyword in node.keywords:
            if keyword.arg != "path":
                continue
            path = _path_expr(keyword.value, bindings)
            if path:
                paths.add(path)
    return paths


def _mode_is_append(call: ast.Call, *, is_method: bool) -> bool:
    idx = 0 if is_method else 1
    for arg in list(call.args[idx : idx + 1]) + [k.value for k in call.keywords if k.arg == "mode"]:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and "a" in arg.value:
            return True
    return False


def _mentioned_jsonl_name(node: ast.AST) -> str | None:
    """Fallback basename for dynamic paths that still mention ``*.jsonl``."""
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Constant)
            and isinstance(child.value, str)
            and ".jsonl" in child.value
        ):
            tail = child.value.rsplit("/", 1)[-1]
            if tail.endswith(".jsonl"):
                return tail
    return None


def _covered(ref: str, covered_paths: set[str]) -> bool:
    for covered in covered_paths:
        if ref == covered:
            return True
        if "/" in ref and ref.endswith("/" + covered.lstrip("/")):
            return True
        if "/" in covered and covered.endswith("/" + ref.lstrip("/")):
            return True
    return False


def check_file(path: Path, covered: set[str], src_lines: list[str]) -> list[str]:
    problems: list[str] = []
    try:
        tree = ast.parse("\n".join(src_lines))
    except SyntaxError:
        return problems
    bindings = _path_name_bindings(tree)
    covered_names = {Path(item).name for item in covered}
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

        target = node.args[0] if is_builtin_open and node.args else None
        if is_method_open:
            target = fn.value
        if target is None:
            continue

        path_ref = _path_expr(target, bindings)
        mentioned_name = _mentioned_jsonl_name(target)
        ambiguous_registered_basename = mentioned_name in covered_names and (
            path_ref is None or path_ref == mentioned_name
        )
        if path_ref and Path(path_ref).name in covered_names:
            ref = path_ref
        elif mentioned_name:
            ref = path_ref or mentioned_name
        else:
            continue

        window = src_lines[max(0, node.lineno - 2) : node.lineno]
        if any("jsonl-rotation: exempt" in line for line in window):
            continue
        if ambiguous_registered_basename or not _covered(ref, covered):
            problems.append(
                f"{path.relative_to(REPO)}:{node.lineno}: append-mode jsonl writer "
                f"'{ref}' has no rotation-registry target and no exempt pragma"
            )
    return problems


def main() -> int:
    covered = registry_paths()
    problems: list[str] = []
    for d in SCAN_DIRS:
        root = REPO / d
        if not root.is_dir():
            continue
        for py in root.rglob("*.py"):
            src_lines = py.read_text(errors="replace").splitlines()
            problems.extend(check_file(py, covered, src_lines))
    if problems:
        print("Unrotated jsonl writers (register in runtime_jsonl_rotator.DEFAULT_TARGETS")
        print("or annotate `# jsonl-rotation: exempt(<reason>)`):")
        for p in problems:
            print(f"  {p}")
        return 1
    print(f"jsonl-writer gate: clean ({len(covered)} registered targets)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
