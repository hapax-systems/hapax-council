"""Reachability guards for no-patch dependency advisories."""

from __future__ import annotations

import ast
import os
from pathlib import Path

EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "node_modules",
}

FORBIDDEN_SYMBOLS = ("nltk.data.load", "torch.jit")
FORBIDDEN_STAR_IMPORT_MODULES = {"nltk", "nltk.data", "torch", "torch.jit"}


def _is_python_source(path: Path) -> bool:
    if path.suffix == ".py":
        return True
    try:
        first_line = path.open("rb").readline(200)
    except OSError:
        return False
    return first_line.startswith(b"#!") and b"python" in first_line.lower()


def _source_files(repo_root: Path | None = None) -> list[Path]:
    repo_root = repo_root or Path(__file__).resolve().parents[1]
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(name for name in dirnames if name not in EXCLUDED_DIRS)
        for filename in filenames:
            path = Path(dirpath) / filename
            if _is_python_source(path):
                files.append(path)
    return sorted(files)


def _imported_name(module: str | None, name: str) -> str:
    return f"{module}.{name}" if module else name


def _is_forbidden(symbol: str) -> bool:
    return any(
        symbol == forbidden or symbol.startswith(f"{forbidden}.") for forbidden in FORBIDDEN_SYMBOLS
    )


def _resolve_symbol(symbol: str, aliases: dict[str, str]) -> str:
    head, _, tail = symbol.partition(".")
    resolved_head = aliases.get(head, head)
    return f"{resolved_head}.{tail}" if tail else resolved_head


def _expr_symbol(node: ast.AST, aliases: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return _resolve_symbol(node.id, aliases)
    if isinstance(node, ast.Attribute):
        base = _expr_symbol(node.value, aliases)
        return f"{base}.{node.attr}" if base else None
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and isinstance(node.args[1].value, str)
    ):
        base = _expr_symbol(node.args[0], aliases)
        return f"{base}.{node.args[1].value}" if base else None
    return None


def _forbidden_reachability(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    aliases: dict[str, str] = {}
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
                else:
                    aliases[alias.name.split(".", maxsplit=1)[0]] = alias.name.split(
                        ".", maxsplit=1
                    )[0]
                if _is_forbidden(alias.name):
                    offenders.append(f"{path}:{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported = _imported_name(node.module, alias.name)
                if alias.name == "*" and node.module in FORBIDDEN_STAR_IMPORT_MODULES:
                    offenders.append(f"{path}:{node.lineno}: from {node.module} import *")
                    continue
                aliases[alias.asname or alias.name] = imported
                if _is_forbidden(imported):
                    offenders.append(
                        f"{path}:{node.lineno}: from {node.module} import {alias.name}"
                    )

    for node in ast.walk(tree):
        if isinstance(node, ast.expr):
            symbol = _expr_symbol(node, aliases)
            if symbol and _is_forbidden(symbol):
                offenders.append(f"{path}:{node.lineno}: {symbol}")

    return sorted(set(offenders))


def test_reachability_guard_detects_alias_imports(tmp_path: Path):
    sample = tmp_path / "uses_forbidden_advisory_apis.py"
    sample.write_text(
        "\n".join(
            [
                "from nltk.data import load as load_data",
                "from torch import jit",
                "",
                "def use_aliases():",
                "    load_data('tokenizers/punkt')",
                "    return jit.script(lambda value: value)",
                "",
            ]
        ),
        encoding="utf-8",
    )

    offenders = _forbidden_reachability(sample)

    assert any("from nltk.data import load" in offender for offender in offenders)
    assert any("from torch import jit" in offender for offender in offenders)
    assert any("torch.jit.script" in offender for offender in offenders)


def test_reachability_guard_detects_direct_star_and_getattr_forms(tmp_path: Path):
    sample = tmp_path / "uses_other_forbidden_advisory_forms.py"
    sample.write_text(
        "\n".join(
            [
                "import torch.jit as torch_jit",
                "import nltk",
                "from torch import *",
                "",
                "def use_other_forms():",
                "    torch_jit.script(lambda value: value)",
                "    getattr(torch, 'jit').script(lambda value: value)",
                "    getattr(nltk.data, 'load')('tokenizers/punkt')",
                "",
            ]
        ),
        encoding="utf-8",
    )

    offenders = _forbidden_reachability(sample)

    assert any("import torch.jit" in offender for offender in offenders)
    assert any("from torch import *" in offender for offender in offenders)
    assert any("torch.jit.script" in offender for offender in offenders)
    assert any("nltk.data.load" in offender for offender in offenders)


def test_source_files_include_python_shebang_entrypoints(tmp_path: Path):
    module = tmp_path / "module.py"
    module.write_text("print('module')\n", encoding="utf-8")
    entrypoint = tmp_path / "entrypoint"
    entrypoint.write_text("#!/usr/bin/env python3\nprint('entrypoint')\n", encoding="utf-8")
    shell = tmp_path / "script.sh"
    shell.write_text("#!/usr/bin/env bash\necho shell\n", encoding="utf-8")
    ignored = tmp_path / ".venv" / "ignored.py"
    ignored.parent.mkdir()
    ignored.write_text("print('ignored')\n", encoding="utf-8")

    assert {path.name for path in _source_files(tmp_path)} == {"entrypoint", "module.py"}


def test_no_first_party_nltk_data_load_or_torch_jit_reachability():
    offenders = [offender for path in _source_files() for offender in _forbidden_reachability(path)]
    assert offenders == []
