#!/usr/bin/env python3
"""Consumer-existence gate: a PR adding a producer must carry a verified consumer.

Closes UNWIRED-WORK (A1) at merge per the LLM-agent failure-taxonomy spec
(2026-06-11, CASE-SYSTEM-INTEGRITY-20260611). Producer classes gated:

- **collection writer** — a new Qdrant write site (``upsert``,
  ``create_collection``, ...) must have a reader of the same collection
  somewhere in non-test code (same PR counts);
- **agent** — a new entry module under ``agents/`` (``__main__.py`` or a
  ``__main__`` guard) must be referenced by a live runner (systemd ``Exec*=``
  directive, compose/workflow/script line, ``[project.scripts]``) or a
  non-test importer;
- **surface** — a new ``*Publisher`` subclass declaring a ``SURFACE`` slug
  must have its contract YAML at ``axioms/contracts/publication/{slug}.yaml``
  plus a runner reference or non-test importer.

``--consumer-side`` adds the inverse, whole-tree report: artifact reads with
no resolved writer, named reader/writer families whose paths diverge, and
(with ``--frame``) reads backed only by a producer in a decayed mass member.
That mode is deliberately report-only until a follow-on row authorises its
named arm.

Anti-theses honored (taxonomy §4.3):

- EFFECT-BASED, not regex: detection is AST / structured-directive parsing,
  so comments, docstrings, and PR prose cannot satisfy the gate, and
  dynamic (unresolvable) collection names fail closed.
- Sanctioned exit: ``scripts/producer-consumer-allowlist.json`` entries
  (``reason`` mandatory) exempt intentional dead-drops; consumers added in
  the same PR count; no-base-SHA invocations skip clean.

Canary battery: ``tests/scripts/test_check_producer_consumers.py``.

Instance recheck:
    uv run python scripts/check-producer-consumers.py --base-ref origin/main
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import subprocess
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

DEFAULT_ALLOWLIST_PATH = Path("scripts/producer-consumer-allowlist.json")

# Qdrant-shaped write methods. Names are specific enough to resolve a
# positional first-arg collection name without false positives.
WRITER_METHODS = {
    "upsert",
    "create_collection",
    "recreate_collection",
    "upload_points",
    "upload_collection",
    "upload_records",
}

# Read methods that unambiguously take a positional collection name.
READER_METHODS_POSITIONAL = {
    "query_points",
    "scroll",
    "retrieve",
    "search_groups",
    "search_batch",
    "query_batch_points",
}

# Read methods too generic for positional resolution (``re.search`` etc.);
# they count only with an explicit ``collection_name=`` kwarg.
READER_METHODS_KWARG_ONLY = {"search", "query", "count"}

EXCLUDE_DIR_PARTS = {
    "__pycache__",
    ".git",
    ".venv",
    "node_modules",
    "_retired",
}

UNIT_SUFFIXES = {".service", ".timer", ".path", ".socket", ".target"}

RECHECK_CMD = "uv run python scripts/check-producer-consumers.py --base-ref origin/main"


class AllowlistError(Exception):
    """Raised when the allowlist exists but is not a governed exit."""


@dataclass
class CollectionWrite:
    collection: str | None
    method: str
    lineno: int


@dataclass
class PublisherSurface:
    class_name: str
    surface: str | None
    lineno: int


@dataclass
class AllowlistEntry:
    pattern: str
    reason: str
    kind: str | None = None


@dataclass
class Refusal:
    kind: str
    label: str
    path: Path
    lineno: int
    why: str
    key: str


# ── AST primitives ────────────────────────────────────────────────────


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level NAME = "literal" assignments, for collection-name resolution."""
    constants: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = node.value.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str) and isinstance(node.target, ast.Name):
                constants[node.target.id] = node.value.value
    return constants


def _resolve_str(node: ast.expr | None, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _collection_arg(call: ast.Call, constants: dict[str, str], positional_ok: bool) -> str | None:
    for kw in call.keywords:
        if kw.arg == "collection_name":
            return _resolve_str(kw.value, constants)
    if positional_ok and call.args:
        return _resolve_str(call.args[0], constants)
    return None


def _parse(source: str, path: Path) -> ast.Module | None:
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError:
        return None


def find_collection_writes(source: str, path: Path) -> list[CollectionWrite]:
    """Effect-based: actual write-method call sites, comments/prose invisible."""
    tree = _parse(source, path)
    if tree is None:
        return []
    constants = _module_constants(tree)
    writes: list[CollectionWrite] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in WRITER_METHODS
        ):
            name = _collection_arg(node, constants, positional_ok=True)
            writes.append(CollectionWrite(name, node.func.attr, node.lineno))
    return writes


def find_collection_reads(source: str, path: Path) -> set[str]:
    """Collections actually read by this source (resolvable names only)."""
    tree = _parse(source, path)
    if tree is None:
        return set()
    constants = _module_constants(tree)
    reads: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        attr = node.func.attr
        if attr in READER_METHODS_POSITIONAL:
            name = _collection_arg(node, constants, positional_ok=True)
        elif attr in READER_METHODS_KWARG_ONLY:
            name = _collection_arg(node, constants, positional_ok=False)
        else:
            continue
        if name:
            reads.add(name)
    return reads


def is_agent_entry(path: Path, source: str) -> bool:
    """A runnable producer under agents/: ``__main__.py`` or a ``__main__`` guard."""
    parts = path.parts
    if not parts or parts[0] != "agents" or path.suffix != ".py":
        return False
    if path.name == "__main__.py":
        return True
    tree = _parse(source, path)
    if tree is None:
        return False
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if isinstance(test, ast.Compare) and len(test.comparators) == 1:
            sides = (test.left, test.comparators[0])
            names = {n.id for n in sides if isinstance(n, ast.Name)}
            literals = {
                n.value for n in sides if isinstance(n, ast.Constant) and isinstance(n.value, str)
            }
            if "__name__" in names and "__main__" in literals:
                return True
    return False


def _base_name(base: ast.expr) -> str | None:
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return None


def find_publisher_surfaces(source: str, path: Path) -> list[PublisherSurface]:
    """Publication-bus surfaces: ``*Publisher`` subclasses with a SURFACE slug."""
    tree = _parse(source, path)
    if tree is None:
        return []
    surfaces: list[PublisherSurface] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        base_names = [_base_name(b) for b in node.bases]
        if not any(n and (n == "BasePublisher" or n.endswith("Publisher")) for n in base_names):
            continue
        surface: str | None = None
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                targets = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
                value: ast.expr | None = stmt.value
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                targets = [stmt.target.id]
                value = stmt.value
            else:
                continue
            if "SURFACE" in targets and isinstance(value, ast.Constant):
                if isinstance(value.value, str):
                    surface = value.value
        surfaces.append(PublisherSurface(node.name, surface, node.lineno))
    return surfaces


# ── Runner / importer discovery ───────────────────────────────────────


def _contains_token(text: str, token: str) -> bool:
    """Substring match with identifier-boundary checks on both ends."""
    start = 0
    while True:
        idx = text.find(token, start)
        if idx == -1:
            return False
        before = text[idx - 1] if idx > 0 else " "
        after_idx = idx + len(token)
        after = text[after_idx] if after_idx < len(text) else " "
        boundary = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_."
        if before not in boundary and after not in boundary:
            return True
        start = idx + 1


def _module_tokens(module: str) -> list[str]:
    return [f"-m {module}", module.replace(".", "/") + ".py", module]


def unit_references_module(unit_source: str, module: str) -> bool:
    """True iff an ``Exec*=`` directive value runs the module. Comments,
    ``Description=``, and section headers are not runners."""
    tokens = _module_tokens(module)
    for raw in unit_source.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";", "[")):
            continue
        key, sep, value = line.partition("=")
        if not sep or not key.strip().startswith("Exec"):
            continue
        if any(_contains_token(value, t) for t in tokens):
            return True
    return False


def line_references_module(text: str, module: str) -> bool:
    """Non-comment-line token search for compose / workflow / script files."""
    tokens = _module_tokens(module)
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if any(_contains_token(line, t) for t in tokens):
            return True
    return False


def _is_excluded(path: Path) -> bool:
    return any(part in EXCLUDE_DIR_PARTS for part in path.parts)


def _is_test_path(path: Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_")


def _iter_python_files(repo_root: Path, include_tests: bool = False) -> list[Path]:
    files = []
    for py_file in repo_root.rglob("*.py"):
        rel = py_file.relative_to(repo_root)
        if _is_excluded(rel):
            continue
        if not include_tests and _is_test_path(rel):
            continue
        files.append(py_file)
    return files


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def collect_collection_reads(repo_root: Path) -> set[str]:
    reads: set[str] = set()
    for py_file in _iter_python_files(repo_root):
        reads |= find_collection_reads(_read(py_file), py_file)
    return reads


def _imported_modules(source: str, path: Path) -> set[str]:
    tree = _parse(source, path)
    if tree is None:
        return set()
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
            for alias in node.names:
                imports.add(f"{node.module}.{alias.name}")
    return imports


def has_nontest_importer(repo_root: Path, module: str, producer_path: Path) -> bool:
    for py_file in _iter_python_files(repo_root):
        if py_file.relative_to(repo_root) == producer_path:
            continue  # self-import is not a consumer
        imported = _imported_modules(_read(py_file), py_file)
        if any(imp == module or imp.startswith(module + ".") for imp in imported):
            return True
    return False


def has_runner_reference(repo_root: Path, module: str) -> bool:
    units_dir = repo_root / "systemd" / "units"
    if units_dir.is_dir():
        for unit in units_dir.rglob("*"):
            if unit.is_file() and unit.suffix in UNIT_SUFFIXES:
                if unit_references_module(_read(unit), module):
                    return True

    line_scanned: list[Path] = []
    for pattern in ("docker/**/*.yml", "docker/**/*.yaml", ".github/workflows/*.yml"):
        line_scanned.extend(repo_root.glob(pattern))
    for name in ("process-compose.yaml", "process-compose.yml"):
        candidate = repo_root / name
        if candidate.is_file():
            line_scanned.append(candidate)
    scripts_dir = repo_root / "scripts"
    if scripts_dir.is_dir():
        line_scanned.extend(p for p in scripts_dir.rglob("*") if p.is_file())
    for path in line_scanned:
        if _is_excluded(path.relative_to(repo_root)):
            continue
        if line_references_module(_read(path), module):
            return True

    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(_read(pyproject))
        except tomllib.TOMLDecodeError:
            data = {}
        scripts = data.get("project", {}).get("scripts", {})
        for target in scripts.values():
            mod = str(target).split(":")[0]
            if mod == module or mod.startswith(module + "."):
                return True
    return False


def contract_yaml_exists(repo_root: Path, slug: str) -> bool:
    contracts = repo_root / "axioms" / "contracts" / "publication"
    return (contracts / f"{slug}.yaml").is_file() or (contracts / f"{slug}.yml").is_file()


# ── Allowlist (the governed exit) ─────────────────────────────────────


def load_allowlist(path: Path) -> list[AllowlistEntry]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AllowlistError(f"allowlist {path} is unreadable: {exc}") from exc
    raw_entries = data.get("entries") if isinstance(data, dict) else data
    if not isinstance(raw_entries, list):
        raise AllowlistError(f"allowlist {path} must contain an 'entries' list")
    entries: list[AllowlistEntry] = []
    for raw in raw_entries:
        if not isinstance(raw, dict) or not raw.get("pattern") or not raw.get("reason"):
            raise AllowlistError(
                f"allowlist {path}: every entry needs a non-empty 'pattern' AND a "
                f"non-empty 'reason' (governed exit, not a silent one): {raw!r}"
            )
        entries.append(
            AllowlistEntry(
                str(raw["pattern"]),
                str(raw["reason"]),
                str(raw["kind"]) if raw.get("kind") is not None else None,
            )
        )
    return entries


def is_allowlisted(
    key: str,
    path: Path,
    entries: list[AllowlistEntry],
    *,
    kind: str | None = None,
) -> AllowlistEntry | None:
    for entry in entries:
        if kind is not None and entry.kind != kind:
            continue
        if fnmatch.fnmatch(key, entry.pattern) or fnmatch.fnmatch(str(path), entry.pattern):
            return entry
    return None


# ── Whole-tree consumer-side artifact binding report ─────────────────


DECAY_RELATIONS = frozenset({"scope_exited", "superseded", "discharged"})
CONSUMER_SIDE_ARM = "HAPAX_CONSUMER_SIDE_PRODUCER_BINDING_GATE=1"
CONSUMER_SIDE_REPORT_LIMIT = 25
CONSUMER_SIDE_KINDS = (
    "consumer-reads-unwritten-artifact",
    "consumer-reads-artifact-with-non-python-producer",
    "consumer-producer-path-mismatch",
    "consumer-reads-decayed-producer",
)
CONSUMER_SIDE_EXCLUSIONS = (
    "committed-in-repository",
    "system-path",
    "corpus-walk",
)
CONSUMER_SIDE_CANARY_PATTERNS = frozenset({"config/platform-capability-registry.json"})


@dataclass(frozen=True)
class ArtifactAccess:
    action: str
    pattern: str
    path: Path
    lineno: int
    family: str
    operation: str


@dataclass(frozen=True)
class ConsumerSideFinding:
    kind: str
    readers: tuple[ArtifactAccess, ...]
    writers: tuple[ArtifactAccess, ...]
    key: str
    detail: str = ""
    reader_total: int = 0

    @property
    def reader(self) -> ArtifactAccess:
        return self.readers[0]

    @property
    def reader_count(self) -> int:
        return self.reader_total or len(self.readers)


@dataclass(frozen=True)
class ArtifactPair:
    family: str
    reader: ArtifactAccess
    writer: ArtifactAccess


@dataclass(frozen=True)
class DecayedMember:
    member_id: str
    relation: str
    patterns: tuple[str, ...]


@dataclass
class ConsumerSideReport:
    findings: list[ConsumerSideFinding]
    allowlisted: list[tuple[ConsumerSideFinding, AllowlistEntry]]
    pairs: list[ArtifactPair]
    unresolvable: int
    exclusions: dict[str, int]


@dataclass(frozen=True)
class PathFunction:
    params: tuple[str, ...]
    defaults: dict[str, ast.expr]
    return_expr: ast.expr
    module_values: dict[str, str]
    path: Path


def _dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _normalise_pattern(value: str, repo_root: Path) -> str:
    value = value.replace("\\", "/")
    home = Path.home().as_posix()
    root = repo_root.resolve().as_posix()
    if value == root:
        return "."
    if value.startswith(root + "/"):
        value = value[len(root) + 1 :]
    elif value == home:
        return "~"
    elif value.startswith(home + "/"):
        value = "~/" + value[len(home) + 1 :]
    while value.startswith("./"):
        value = value[2:]
    while "//" in value:
        value = value.replace("//", "/")
    return value or "."


def _join_pattern(left: str, right: str, repo_root: Path) -> str:
    if right.startswith(("/", "~/")):
        return _normalise_pattern(right, repo_root)
    if left in ("", "."):
        return _normalise_pattern(right, repo_root)
    return _normalise_pattern(f"{left.rstrip('/')}/{right.lstrip('/')}", repo_root)


def _parent_pattern(value: str, levels: int, repo_root: Path) -> str:
    result = value
    for _ in range(levels):
        result = str(PurePosixPath(result).parent)
    return _normalise_pattern(result, repo_root)


def _function_name(call: ast.Call) -> str:
    return _dotted_name(call.func) or ""


def _return_expression(node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.expr | None:
    returns = [item.value for item in ast.walk(node) if isinstance(item, ast.Return) and item.value]
    return returns[0] if len(returns) == 1 else None


def _function_defaults(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, ast.expr]:
    positional = [*node.args.posonlyargs, *node.args.args]
    start = len(positional) - len(node.args.defaults)
    defaults = {
        arg.arg: value for arg, value in zip(positional[start:], node.args.defaults, strict=True)
    }
    defaults.update(
        {
            arg.arg: value
            for arg, value in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True)
            if value is not None
        }
    )
    return defaults


def _resolve_path_expr(
    node: ast.expr | None,
    values: dict[str, str],
    path: Path,
    repo_root: Path,
    path_functions: dict[str, PathFunction],
    *,
    depth: int = 0,
) -> str | None:
    if node is None or depth > 12:
        return None
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (str, int)):
            return str(node.value)
        return None
    if isinstance(node, ast.Name):
        if node.id == "__file__":
            return path.as_posix()
        return values.get(node.id)
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for item in node.values:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                parts.append(item.value)
            elif isinstance(item, ast.FormattedValue):
                resolved = _resolve_path_expr(
                    item.value,
                    values,
                    path,
                    repo_root,
                    path_functions,
                    depth=depth + 1,
                )
                parts.append(resolved if resolved and resolved != "*" else "*")
        return _normalise_pattern("".join(parts), repo_root)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.Add)):
        left = _resolve_path_expr(
            node.left, values, path, repo_root, path_functions, depth=depth + 1
        )
        right = _resolve_path_expr(
            node.right, values, path, repo_root, path_functions, depth=depth + 1
        )
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add):
            return _normalise_pattern(left + right, repo_root)
        return _join_pattern(left, right, repo_root)
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        for item in reversed(node.values):
            resolved = _resolve_path_expr(
                item, values, path, repo_root, path_functions, depth=depth + 1
            )
            if resolved is not None:
                return resolved
        return None
    if isinstance(node, ast.IfExp):
        left = _resolve_path_expr(
            node.body, values, path, repo_root, path_functions, depth=depth + 1
        )
        right = _resolve_path_expr(
            node.orelse, values, path, repo_root, path_functions, depth=depth + 1
        )
        return left if left == right else left or right
    if isinstance(node, ast.Attribute):
        base = _resolve_path_expr(
            node.value, values, path, repo_root, path_functions, depth=depth + 1
        )
        if base is None:
            return values.get(node.attr)
        if node.attr == "parent":
            return _parent_pattern(base, 1, repo_root)
        if node.attr == "name":
            return PurePosixPath(base).name
        return None
    if isinstance(node, ast.Subscript):
        if isinstance(node.value, ast.Attribute) and node.value.attr == "parents":
            base = _resolve_path_expr(
                node.value.value,
                values,
                path,
                repo_root,
                path_functions,
                depth=depth + 1,
            )
            index = _resolve_path_expr(
                node.slice, values, path, repo_root, path_functions, depth=depth + 1
            )
            if base is not None and index is not None and index.isdecimal():
                return _parent_pattern(base, int(index) + 1, repo_root)
        return None
    if not isinstance(node, ast.Call):
        return None

    name = _function_name(node)
    if name in {"Path", "pathlib.Path", "str"}:
        if not node.args:
            return "."
        return _resolve_path_expr(
            node.args[0], values, path, repo_root, path_functions, depth=depth + 1
        )
    if name in {"Path.home", "pathlib.Path.home"}:
        return "~"
    if name in {"os.getenv", "os.environ.get"}:
        default = node.args[1] if len(node.args) > 1 else None
        for keyword in node.keywords:
            if keyword.arg == "default":
                default = keyword.value
        return _resolve_path_expr(default, values, path, repo_root, path_functions, depth=depth + 1)
    if isinstance(node.func, ast.Attribute) and node.func.attr in {
        "expanduser",
        "absolute",
        "resolve",
    }:
        return _resolve_path_expr(
            node.func.value, values, path, repo_root, path_functions, depth=depth + 1
        )
    if isinstance(node.func, ast.Attribute) and node.func.attr == "with_suffix":
        base = _resolve_path_expr(
            node.func.value, values, path, repo_root, path_functions, depth=depth + 1
        )
        suffix = _resolve_path_expr(
            node.args[0] if node.args else None,
            values,
            path,
            repo_root,
            path_functions,
            depth=depth + 1,
        )
        if base is not None and suffix is not None:
            try:
                return str(PurePosixPath(base).with_suffix(suffix))
            except ValueError:
                return None
    if isinstance(node.func, ast.Attribute) and node.func.attr == "with_name":
        base = _resolve_path_expr(
            node.func.value, values, path, repo_root, path_functions, depth=depth + 1
        )
        new_name = _resolve_path_expr(
            node.args[0] if node.args else None,
            values,
            path,
            repo_root,
            path_functions,
            depth=depth + 1,
        )
        if base is not None and new_name is not None:
            return _join_pattern(str(PurePosixPath(base).parent), new_name, repo_root)

    function = path_functions.get(name) or path_functions.get(name.rsplit(".", 1)[-1])
    if function is None:
        return None
    bound = dict(function.module_values)
    for parameter, default in function.defaults.items():
        resolved = _resolve_path_expr(
            default,
            bound,
            function.path,
            repo_root,
            path_functions,
            depth=depth + 1,
        )
        if resolved is not None:
            bound[parameter] = resolved
    for parameter, argument in zip(function.params, node.args, strict=False):
        bound[parameter] = (
            _resolve_path_expr(
                argument,
                values,
                path,
                repo_root,
                path_functions,
                depth=depth + 1,
            )
            or "*"
        )
    for keyword in node.keywords:
        if keyword.arg is not None:
            bound[keyword.arg] = (
                _resolve_path_expr(
                    keyword.value,
                    values,
                    path,
                    repo_root,
                    path_functions,
                    depth=depth + 1,
                )
                or "*"
            )
    return _resolve_path_expr(
        function.return_expr,
        bound,
        function.path,
        repo_root,
        path_functions,
        depth=depth + 1,
    )


def _iter_python_sources(repo_root: Path) -> list[Path]:
    files = set(_iter_python_files(repo_root))
    scripts = repo_root / "scripts"
    if scripts.is_dir():
        for candidate in scripts.rglob("*"):
            if not candidate.is_file() or candidate.suffix == ".py":
                continue
            source = _read(candidate)
            if source.startswith("#!/") and "python" in source.splitlines()[0]:
                files.add(candidate)
    return sorted(files)


def _module_values(
    tree: ast.Module,
    path: Path,
    repo_root: Path,
    path_functions: dict[str, PathFunction],
) -> dict[str, str]:
    values = _module_constants(tree)
    values["__file__"] = path.as_posix()
    assignments: list[ast.Assign | ast.AnnAssign] = [
        node for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))
    ]
    for _ in range(2):
        changed = False
        for assignment in assignments:
            targets = (
                assignment.targets if isinstance(assignment, ast.Assign) else [assignment.target]
            )
            resolved = _resolve_path_expr(assignment.value, values, path, repo_root, path_functions)
            if resolved is None:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and values.get(target.id) != resolved:
                    values[target.id] = resolved
                    changed = True
        if not changed:
            break
    return values


def _scope_values(
    node: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef,
    module_values: dict[str, str],
    path: Path,
    repo_root: Path,
    path_functions: dict[str, PathFunction],
) -> dict[str, str]:
    values = dict(module_values)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        defaults = _function_defaults(node)
        for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            values[arg.arg] = "*"
        for name, default in defaults.items():
            resolved = _resolve_path_expr(default, values, path, repo_root, path_functions)
            if resolved is not None:
                values[name] = resolved
    assignments = [item for item in ast.walk(node) if isinstance(item, (ast.Assign, ast.AnnAssign))]
    for _ in range(2):
        changed = False
        for assignment in assignments:
            targets = (
                assignment.targets if isinstance(assignment, ast.Assign) else [assignment.target]
            )
            resolved = _resolve_path_expr(assignment.value, values, path, repo_root, path_functions)
            if resolved is None:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and values.get(target.id) != resolved:
                    values[target.id] = resolved
                    changed = True
        if not changed:
            break
    return values


def _artifact_family(name: str) -> str:
    value = name.rsplit(".", 1)[-1].strip("_").lower()
    for prefix in (
        "load_",
        "read_",
        "write_",
        "save_",
        "persist_",
        "emit_",
        "collect_",
        "capture_",
    ):
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    for suffix in ("_path", "_file", "_output", "_input"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break
    return value or "artifact"


def _useful_pattern(pattern: str | None) -> bool:
    return bool(
        pattern
        and pattern.isprintable()
        and pattern not in {"*", ".", "~"}
        and pattern.strip("*/.")
    )


def _open_effect(call: ast.Call) -> str:
    mode_node: ast.expr | None = None
    if isinstance(call.func, ast.Attribute) and call.func.attr == "open":
        if call.args:
            mode_node = call.args[0]
    elif len(call.args) > 1:
        mode_node = call.args[1]
    for keyword in call.keywords:
        if keyword.arg == "mode":
            mode_node = keyword.value
    mode = mode_node.value if isinstance(mode_node, ast.Constant) else "r"
    return "write" if isinstance(mode, str) and any(flag in mode for flag in "wax") else "read"


class _ScopeCallVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.calls: list[ast.Call] = []

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return


def _scope_calls(node: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Call]:
    visitor = _ScopeCallVisitor()
    for statement in node.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        visitor.visit(statement)
    return visitor.calls


def _call_argument(call: ast.Call, position: int, keyword_name: str = "") -> ast.expr | None:
    if len(call.args) > position:
        return call.args[position]
    for keyword in call.keywords:
        if keyword.arg == keyword_name:
            return keyword.value
    return None


def _record_access(
    accesses: list[ArtifactAccess],
    unresolved: list[int],
    *,
    action: str,
    expression: ast.expr | None,
    call: ast.Call,
    values: dict[str, str],
    path: Path,
    repo_root: Path,
    path_functions: dict[str, PathFunction],
    family: str,
    operation: str,
    append: str | None = None,
) -> None:
    pattern = _resolve_path_expr(expression, values, path, repo_root, path_functions)
    if pattern is not None and append is not None:
        pattern = _join_pattern(pattern, append, repo_root)
    if not _useful_pattern(pattern):
        unresolved[0] += 1
        return
    assert pattern is not None
    accesses.append(ArtifactAccess(action, pattern, path, call.lineno, family, operation))


def _scan_scope(
    node: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef,
    module_values: dict[str, str],
    path: Path,
    repo_root: Path,
    path_functions: dict[str, PathFunction],
    accesses: list[ArtifactAccess],
    unresolved: list[int],
) -> None:
    values = _scope_values(node, module_values, path, repo_root, path_functions)
    context = node.name if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else path.stem
    context_family = _artifact_family(context)
    for call in _scope_calls(node):
        name = _function_name(call)
        short_name = name.rsplit(".", 1)[-1]
        if isinstance(call.func, ast.Attribute) and call.func.attr in {
            "read_text",
            "read_bytes",
        }:
            _record_access(
                accesses,
                unresolved,
                action="read",
                expression=call.func.value,
                call=call,
                values=values,
                path=path,
                repo_root=repo_root,
                path_functions=path_functions,
                family=context_family,
                operation=call.func.attr,
            )
        elif isinstance(call.func, ast.Attribute) and call.func.attr in {
            "write_text",
            "write_bytes",
        }:
            _record_access(
                accesses,
                unresolved,
                action="write",
                expression=call.func.value,
                call=call,
                values=values,
                path=path,
                repo_root=repo_root,
                path_functions=path_functions,
                family=context_family,
                operation=call.func.attr,
            )
        elif short_name == "open":
            expression = (
                call.func.value
                if isinstance(call.func, ast.Attribute)
                else _call_argument(call, 0, "file")
            )
            _record_access(
                accesses,
                unresolved,
                action=_open_effect(call),
                expression=expression,
                call=call,
                values=values,
                path=path,
                repo_root=repo_root,
                path_functions=path_functions,
                family=context_family,
                operation="open",
            )
        elif isinstance(call.func, ast.Attribute) and call.func.attr in {"glob", "rglob"}:
            suffix = _resolve_path_expr(
                _call_argument(call, 0), values, path, repo_root, path_functions
            )
            if suffix is None:
                unresolved[0] += 1
            else:
                if call.func.attr == "rglob" and not suffix.startswith("**/"):
                    suffix = f"**/{suffix}"
                _record_access(
                    accesses,
                    unresolved,
                    action="read",
                    expression=call.func.value,
                    call=call,
                    values=values,
                    path=path,
                    repo_root=repo_root,
                    path_functions=path_functions,
                    family=context_family,
                    operation=call.func.attr,
                    append=suffix,
                )
        elif name in {"os.replace", "os.rename"}:
            _record_access(
                accesses,
                unresolved,
                action="write",
                expression=_call_argument(call, 1, "dst"),
                call=call,
                values=values,
                path=path,
                repo_root=repo_root,
                path_functions=path_functions,
                family=context_family,
                operation=short_name,
            )
        elif isinstance(call.func, ast.Attribute) and call.func.attr in {"replace", "rename"}:
            _record_access(
                accesses,
                unresolved,
                action="write",
                expression=_call_argument(call, 0, "target"),
                call=call,
                values=values,
                path=path,
                repo_root=repo_root,
                path_functions=path_functions,
                family=context_family,
                operation=call.func.attr,
            )
        elif name.startswith("shutil.copy"):
            _record_access(
                accesses,
                unresolved,
                action="write",
                expression=_call_argument(call, 1, "dst"),
                call=call,
                values=values,
                path=path,
                repo_root=repo_root,
                path_functions=path_functions,
                family=context_family,
                operation=short_name,
            )
        elif short_name == "load_claim_dispatch_binding" or (
            short_name == "_load_json_object"
            and path == Path("shared/platform_capability_registry.py")
        ):
            argument = _call_argument(call, 0, "path")
            if argument is not None:
                _record_access(
                    accesses,
                    unresolved,
                    action="read",
                    expression=argument,
                    call=call,
                    values=values,
                    path=path,
                    repo_root=repo_root,
                    path_functions=path_functions,
                    family=_artifact_family(short_name),
                    operation=short_name,
                )


def _iter_function_scopes(
    tree: ast.Module,
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _module_imports(tree: ast.Module) -> frozenset[str]:
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return frozenset(imports)


def collect_artifact_accesses(
    repo_root: Path,
) -> tuple[list[ArtifactAccess], int, dict[Path, frozenset[str]]]:
    parsed: list[tuple[Path, ast.Module]] = []
    for source_path in _iter_python_sources(repo_root):
        relative = source_path.relative_to(repo_root)
        tree = _parse(_read(source_path), relative)
        if tree is not None:
            parsed.append((relative, tree))

    path_functions: dict[str, PathFunction] = {}
    imports_by_path = {relative: _module_imports(tree) for relative, tree in parsed}
    module_values_by_path: dict[Path, dict[str, str]] = {}
    for relative, tree in parsed:
        module_values_by_path[relative] = _module_values(tree, relative, repo_root, path_functions)
    for _ in range(2):
        for relative, tree in parsed:
            values = _module_values(tree, relative, repo_root, path_functions)
            module_values_by_path[relative] = values
            for node in _iter_function_scopes(tree):
                return_expr = _return_expression(node)
                if return_expr is None:
                    continue
                params = tuple(
                    arg.arg
                    for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                )
                path_functions[node.name] = PathFunction(
                    params, _function_defaults(node), return_expr, values, relative
                )

    accesses: list[ArtifactAccess] = []
    unresolved = [0]
    for relative, tree in parsed:
        values = module_values_by_path[relative]
        _scan_scope(
            tree,
            values,
            relative,
            repo_root,
            path_functions,
            accesses,
            unresolved,
        )
        for node in _iter_function_scopes(tree):
            _scan_scope(
                node,
                values,
                relative,
                repo_root,
                path_functions,
                accesses,
                unresolved,
            )
    unique = list(dict.fromkeys(accesses))
    return unique, unresolved[0], imports_by_path


def _glob_has_artifact_identity(pattern: str) -> bool:
    parts = PurePosixPath(pattern).parts
    fixed_directory = any(
        "*" not in part and part not in {"/", "~", ".", ".."} for part in parts[:-1]
    )
    fixed_stem = PurePosixPath(pattern).stem.replace("*", "").strip("._-")
    return fixed_directory or bool(fixed_stem)


def _patterns_match(left: str, right: str) -> bool:
    if left == right:
        return True
    for pattern in (left, right):
        # ``*/*.json`` means the path parameter was unresolved. It cannot prove
        # that a specific JSON consumer has a producer merely by sharing a suffix.
        if "*" in pattern and not _glob_has_artifact_identity(pattern):
            return False
    if fnmatch.fnmatch(left, right) or fnmatch.fnmatch(right, left):
        return True
    if "*" not in left and "*" not in right:
        return False
    left_prefix = left.split("*", 1)[0].rstrip("/")
    right_prefix = right.split("*", 1)[0].rstrip("/")
    return bool(
        left_prefix
        and right_prefix
        and (
            left_prefix.startswith(right_prefix + "/") or right_prefix.startswith(left_prefix + "/")
        )
    )


def _nearest_writers(
    reader: ArtifactAccess, writes: list[ArtifactAccess]
) -> tuple[ArtifactAccess, ...]:
    def score(writer: ArtifactAccess) -> tuple[int, int, str]:
        same_family = int(writer.family == reader.family)
        common = len(os.path.commonprefix((writer.pattern, reader.pattern)))
        return (-same_family, -common, writer.pattern)

    return tuple(sorted(writes, key=score)[:3])


def _git_tracked_paths(repo_root: Path) -> frozenset[str]:
    if not (repo_root / ".git").exists():
        return frozenset()
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        return frozenset()
    return frozenset(
        item.decode("utf-8", errors="surrogateescape")
        for item in result.stdout.split(b"\0")
        if item
    )


def _pattern_is_committed(pattern: str, tracked: frozenset[str]) -> bool:
    canonical_repo = "~/projects/hapax-council/"
    candidates = [pattern]
    if pattern.startswith(canonical_repo):
        candidates.append(pattern[len(canonical_repo) :])
    parts = list(PurePosixPath(pattern).parts)
    while parts and parts[0] in {"*", "**"}:
        parts.pop(0)
        if parts:
            candidates.append(PurePosixPath(*parts).as_posix())
    return any(
        fnmatch.fnmatchcase(path, candidate)
        for path in tracked
        for candidate in candidates
        if not candidate.startswith(("/", "~/"))
    )


def _pattern_is_system_path(pattern: str) -> bool:
    if any(
        pattern == prefix or pattern.startswith(prefix + "/")
        for prefix in ("/proc", "/sys", "/etc", "/usr")
    ):
        return True
    if pattern.startswith("/dev/") and not pattern.startswith("/dev/shm"):
        return True
    if (pattern == "/run" or pattern.startswith("/run/")) and not pattern.startswith("/run/user"):
        return True
    config_prefix = "~/.config/"
    if pattern.startswith(config_prefix):
        app = pattern[len(config_prefix) :].split("/", 1)[0]
        return not app.startswith("hapax")
    return False


def _exclusion_class(pattern: str, tracked: frozenset[str]) -> str | None:
    # This path is deliberately load-bearing even though it is committed: the
    # live producer/consumer split is the named real-tree canary for this mode.
    if pattern in CONSUMER_SIDE_CANARY_PATTERNS:
        return None
    if _pattern_is_committed(pattern, tracked):
        return "committed-in-repository"
    if _pattern_is_system_path(pattern):
        return "system-path"
    if "*" in pattern and not _glob_has_artifact_identity(pattern):
        return "corpus-walk"
    return None


def _module_name(path: Path) -> str:
    parts = list(path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _artifact_identity(pattern: str) -> tuple[str, str] | None:
    path = PurePosixPath(pattern)
    directory = path.parent.name
    stem = path.stem.replace("*", "").strip("._-").lower()
    if not directory or "*" in directory or not stem:
        return None
    return directory.lower(), stem


def _stem_appears_in_family(pattern: str, family: str) -> bool:
    stem = PurePosixPath(pattern).stem.replace("*", "").strip("._-")
    stem = stem.lower().replace("-", "_")
    tokens = [token for token in stem.split("_") if token and token not in {"cc"}]
    if not tokens:
        return False
    candidates = {"_".join(tokens)}
    if len(tokens) > 1:
        candidates.update("_".join(tokens[index:]) for index in range(1, len(tokens)))
        candidates.update("_".join(tokens[:index]) for index in range(2, len(tokens) + 1))
    return any(len(candidate) >= 4 and candidate in family for candidate in candidates)


def _specific_pair_identity(
    reader: ArtifactAccess,
    writer: ArtifactAccess,
    imports_by_path: dict[Path, frozenset[str]],
) -> bool:
    reader_identity = _artifact_identity(reader.pattern)
    writer_identity = _artifact_identity(writer.pattern)
    if reader_identity is not None and reader_identity == writer_identity:
        return True
    return _module_name(writer.path) in imports_by_path.get(
        reader.path, frozenset()
    ) and _stem_appears_in_family(reader.pattern, writer.family)


def _non_python_source_paths(repo_root: Path, tracked: frozenset[str]) -> list[Path]:
    suffixes = {".sh", ".rs", ".conf"}
    candidates = (repo_root / item for item in tracked) if tracked else repo_root.rglob("*")
    output: list[Path] = []
    for candidate in candidates:
        try:
            relative = candidate.relative_to(repo_root)
        except ValueError:
            continue
        if not candidate.is_file() or candidate.suffix == ".py":
            continue
        if relative.parts[:1] in {("scripts",), ("systemd",)} or candidate.suffix in suffixes:
            output.append(candidate)
    return sorted(output)


def _mention_needles(pattern: str) -> tuple[str, ...]:
    basename = PurePosixPath(pattern).name
    needles = [pattern]
    if "*" not in basename:
        needles.append(basename)
    else:
        fixed_parts = [part for part in basename.split("*") if len(part.strip("._-")) >= 4]
        needles.extend(fixed_parts)
    return tuple(dict.fromkeys(needle for needle in needles if len(needle) >= 4))


def _non_python_mentions(
    pattern: str,
    sources: list[tuple[Path, str]],
    repo_root: Path,
) -> tuple[str, ...]:
    if not pattern.startswith(("/dev/shm", "~/.cache")):
        return ()
    needles = _mention_needles(pattern)
    matches: list[str] = []
    for path, source in sources:
        if any(needle in source for needle in needles):
            matches.append(path.relative_to(repo_root).as_posix())
            if len(matches) == 3:
                break
    return tuple(matches)


def _group_reads(reads: list[ArtifactAccess]) -> dict[str, tuple[ArtifactAccess, ...]]:
    grouped: dict[str, list[ArtifactAccess]] = {}
    for reader in reads:
        grouped.setdefault(reader.pattern, []).append(reader)
    return {
        pattern: tuple(sorted(sites, key=lambda item: (str(item.path), item.lineno)))
        for pattern, sites in grouped.items()
    }


def _default_mass_path(frame_path: Path) -> Path:
    logical_path = frame_path.expanduser().absolute()
    for parent in logical_path.parents:
        candidate = parent / "declaration" / "mass.yaml"
        if candidate.is_file():
            return candidate
    return logical_path.parents[2] / "declaration" / "mass.yaml"


def _declared_pattern(value: str, repo_root: Path) -> str:
    expanded = Path(value).expanduser().as_posix()
    canonical_repo = (Path.home() / "projects" / "hapax-council").as_posix()
    if expanded == canonical_repo:
        return "."
    if expanded.startswith(canonical_repo + "/"):
        return expanded[len(canonical_repo) + 1 :]
    return _normalise_pattern(expanded, repo_root)


def _mass_member_patterns(member: dict[str, object], repo_root: Path) -> tuple[str, ...]:
    location = member.get("location")
    if not isinstance(location, dict):
        return ()
    patterns = location.get("patterns")
    globs = [str(item) for item in patterns] if isinstance(patterns, list) else []
    roots: list[str] = []
    if isinstance(location.get("path"), str):
        roots.append(str(location["path"]))
    if isinstance(location.get("roots"), list):
        roots.extend(str(item) for item in location["roots"] if isinstance(item, str))
    output: list[str] = []
    for root in roots:
        normalised = _declared_pattern(root, repo_root)
        if globs:
            output.extend(_join_pattern(normalised, item, repo_root) for item in globs)
        else:
            output.append(_join_pattern(normalised, "**", repo_root))
    files = location.get("files")
    if isinstance(files, list):
        output.extend(
            _declared_pattern(str(item), repo_root) for item in files if isinstance(item, str)
        )
    return tuple(output)


def load_decayed_members(
    frame_path: Path,
    mass_path: Path,
    repo_root: Path,
) -> list[DecayedMember]:
    frame = json.loads(frame_path.read_text(encoding="utf-8"))
    if not isinstance(frame, list):
        raise ValueError(f"frame {frame_path} must contain a JSON list")
    verdicts: list[dict[str, object]] = []
    for element in frame:
        if not isinstance(element, dict) or not isinstance(element.get("payload"), dict):
            continue
        rows = element["payload"].get("verdicts")
        if isinstance(rows, list):
            verdicts.extend(row for row in rows if isinstance(row, dict))
    decay: dict[str, set[str]] = {}
    for row in verdicts:
        subject = row.get("subject")
        relation = str(row.get("relation") or "")
        verdict = row.get("verdict")
        if (
            isinstance(subject, dict)
            and isinstance(subject.get("member_id"), str)
            and relation in DECAY_RELATIONS
            and (verdict is True or str(verdict).upper() == "TRUE")
        ):
            decay.setdefault(str(subject["member_id"]), set()).add(relation)

    mass = yaml.safe_load(mass_path.read_text(encoding="utf-8"))
    if not isinstance(mass, dict) or not isinstance(mass.get("members"), list):
        raise ValueError(f"mass {mass_path} must contain a members list")
    members: list[DecayedMember] = []
    for member in mass["members"]:
        if not isinstance(member, dict) or str(member.get("id")) not in decay:
            continue
        member_id = str(member["id"])
        patterns = _mass_member_patterns(member, repo_root)
        for relation in sorted(decay[member_id]):
            members.append(DecayedMember(member_id, relation, patterns))
    return members


def analyse_consumer_side(
    repo_root: Path,
    allowlist: list[AllowlistEntry],
    *,
    frame_path: Path | None = None,
    mass_path: Path | None = None,
) -> ConsumerSideReport:
    tracked = _git_tracked_paths(repo_root)
    accesses, unresolved, imports_by_path = collect_artifact_accesses(repo_root)
    reads = [item for item in accesses if item.action == "read"]
    writes = [item for item in accesses if item.action == "write"]
    findings: list[ConsumerSideFinding] = []
    pairs: list[ArtifactPair] = []
    exclusions = Counter({name: 0 for name in CONSUMER_SIDE_EXCLUSIONS})
    included_reads: list[ArtifactAccess] = []
    grouped_reads = _group_reads(reads)
    for pattern, reader_sites in grouped_reads.items():
        exclusion = _exclusion_class(pattern, tracked)
        if exclusion is None:
            included_reads.extend(reader_sites)
        else:
            exclusions[exclusion] += 1

    non_python_sources = [
        (path, _read(path)) for path in _non_python_source_paths(repo_root, tracked)
    ]
    for pattern, reader_sites in _group_reads(included_reads).items():
        representative = reader_sites[0]
        matching = [writer for writer in writes if _patterns_match(pattern, writer.pattern)]
        if not matching:
            mentions = _non_python_mentions(pattern, non_python_sources, repo_root)
            if mentions:
                kind = "consumer-reads-artifact-with-non-python-producer"
                detail = f"non-python-mentions={','.join(mentions)}"
            else:
                kind = "consumer-reads-unwritten-artifact"
                detail = ""
            findings.append(
                ConsumerSideFinding(
                    kind,
                    reader_sites[:3],
                    _nearest_writers(representative, writes),
                    f"{kind}:{pattern}",
                    detail,
                    reader_total=len(reader_sites),
                )
            )
        identity_writers = [
            writer
            for writer in writes
            if any(
                _specific_pair_identity(reader, writer, imports_by_path) for reader in reader_sites
            )
        ]
        paired = [writer for writer in identity_writers if _patterns_match(pattern, writer.pattern)]
        for reader in reader_sites:
            pairs.extend(
                ArtifactPair(reader.family, reader, writer)
                for writer in paired
                if _specific_pair_identity(reader, writer, imports_by_path)
            )
        if identity_writers and not paired:
            kind = "consumer-producer-path-mismatch"
            findings.append(
                ConsumerSideFinding(
                    kind,
                    reader_sites[:3],
                    _nearest_writers(representative, identity_writers),
                    f"{kind}:{pattern}",
                    reader_total=len(reader_sites),
                )
            )

    if frame_path is not None:
        resolved_mass = mass_path or _default_mass_path(frame_path)
        for member in load_decayed_members(frame_path, resolved_mass, repo_root):
            for writer in writes:
                if not any(_patterns_match(writer.pattern, pattern) for pattern in member.patterns):
                    continue
                for reader in included_reads:
                    if not _patterns_match(reader.pattern, writer.pattern):
                        continue
                    kind = "consumer-reads-decayed-producer"
                    findings.append(
                        ConsumerSideFinding(
                            kind,
                            (reader,),
                            (writer,),
                            f"{kind}:{reader.pattern}",
                            f"member={member.member_id} relation={member.relation} verdict=TRUE",
                        )
                    )

    unique_findings = list(dict.fromkeys(findings))
    unique_pairs = list(dict.fromkeys(pairs))
    visible: list[ConsumerSideFinding] = []
    allowed: list[tuple[ConsumerSideFinding, AllowlistEntry]] = []
    for finding in unique_findings:
        entry = is_allowlisted(
            finding.key,
            finding.reader.path,
            allowlist,
            kind="consumer_side",
        )
        if entry is None:
            visible.append(finding)
        else:
            allowed.append((finding, entry))
    return ConsumerSideReport(visible, allowed, unique_pairs, unresolved, dict(exclusions))


def _writer_label(writer: ArtifactAccess) -> str:
    return f"{writer.path}:{writer.lineno}=>{writer.pattern}"


def _finding_line(finding: ConsumerSideFinding) -> str:
    readers = ",".join(f"{reader.path}:{reader.lineno}" for reader in finding.readers[:3])
    candidates = ", ".join(_writer_label(item) for item in finding.writers[:3]) or "none"
    detail = f" {finding.detail}" if finding.detail else ""
    return (
        f"[REPORT] {finding.kind} readers={finding.reader_count} reader-sites={readers} "
        f"read={finding.reader.pattern} nearest-writers={candidates}{detail} "
        "next-action=bind the consumer to a live producer output or add a reasoned "
        "kind=consumer_side allowlist entry"
    )


def _finding_priority(finding: ConsumerSideFinding) -> tuple[int, str, str, int]:
    canary = int(finding.reader.pattern not in CONSUMER_SIDE_CANARY_PATTERNS)
    return canary, finding.reader.pattern, str(finding.reader.path), finding.reader.lineno


def _pair_priority(pair: ArtifactPair) -> tuple[int, str, str, int]:
    return (
        int(pair.family != "claim_dispatch_binding"),
        pair.family,
        str(pair.reader.path),
        pair.reader.lineno,
    )


def _access_json(access: ArtifactAccess) -> dict[str, object]:
    return {
        "action": access.action,
        "pattern": access.pattern,
        "path": str(access.path),
        "line": access.lineno,
        "family": access.family,
        "operation": access.operation,
    }


def _report_json(report: ConsumerSideReport) -> dict[str, object]:
    counts = Counter(finding.kind for finding in report.findings)
    return {
        "summary": {
            "findings": len(report.findings),
            "findings_by_kind": {kind: counts[kind] for kind in CONSUMER_SIDE_KINDS},
            "allowlisted": len(report.allowlisted),
            "exclusions": report.exclusions,
            "unresolvable": report.unresolvable,
            "report_only": True,
        },
        "findings": [
            {
                "kind": finding.kind,
                "key": finding.key,
                "read_pattern": finding.reader.pattern,
                "reader_count": finding.reader_count,
                "readers": [_access_json(reader) for reader in finding.readers],
                "nearest_writers": [_access_json(writer) for writer in finding.writers],
                "detail": finding.detail,
            }
            for finding in report.findings
        ],
        "allowlisted": [
            {
                "finding": finding.key,
                "reason": entry.reason,
                "readers": [_access_json(reader) for reader in finding.readers],
            }
            for finding, entry in report.allowlisted
        ],
        "pairs": [
            {
                "family": pair.family,
                "reader": _access_json(pair.reader),
                "writer": _access_json(pair.writer),
                "status": "no-live-mismatch",
            }
            for pair in report.pairs
        ],
    }


def _report_output_path(repo_root: Path) -> Path:
    runner_temp = os.environ.get("RUNNER_TEMP")
    return (
        Path(runner_temp) / "consumer-side-report.json"
        if runner_temp
        else repo_root / ".consumer-side-report.json"
    )


def write_consumer_side_json(report: ConsumerSideReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_report_json(report), indent=2) + "\n", encoding="utf-8")


def print_consumer_side_report(report: ConsumerSideReport, report_path: Path) -> None:
    counts = Counter(finding.kind for finding in report.findings)
    print(
        "consumer-side counts: "
        f"findings={len(report.findings)} "
        f"consumer-reads-unwritten-artifact={counts['consumer-reads-unwritten-artifact']} "
        "consumer-reads-artifact-with-non-python-producer="
        f"{counts['consumer-reads-artifact-with-non-python-producer']} "
        f"consumer-producer-path-mismatch={counts['consumer-producer-path-mismatch']} "
        f"consumer-reads-decayed-producer={counts['consumer-reads-decayed-producer']} "
        f"allowlisted={len(report.allowlisted)} "
        "exclusions: "
        f"committed-in-repository={report.exclusions['committed-in-repository']} "
        f"system-path={report.exclusions['system-path']} "
        f"corpus-walk={report.exclusions['corpus-walk']} "
        f"unresolvable={report.unresolvable}"
    )
    printed_by_kind: Counter[str] = Counter()
    for finding, entry in report.allowlisted:
        if printed_by_kind[finding.kind] >= CONSUMER_SIDE_REPORT_LIMIT:
            continue
        print(
            f"[ALLOWLISTED] {finding.kind} reader={finding.reader.path}:"
            f"{finding.reader.lineno} read={finding.reader.pattern} reason={entry.reason}"
        )
        printed_by_kind[finding.kind] += 1
    for kind in CONSUMER_SIDE_KINDS:
        kind_findings = sorted(
            (finding for finding in report.findings if finding.kind == kind),
            key=_finding_priority,
        )
        remaining = CONSUMER_SIDE_REPORT_LIMIT - printed_by_kind[kind]
        for finding in kind_findings[:remaining]:
            print(_finding_line(finding))
    for pair in sorted(report.pairs, key=_pair_priority)[:CONSUMER_SIDE_REPORT_LIMIT]:
        print(
            f"[PAIRED] {pair.family} reader={pair.reader.path}:{pair.reader.lineno} "
            f"read={pair.reader.pattern} writer={pair.writer.path}:{pair.writer.lineno} "
            f"write={pair.writer.pattern} status=no-live-mismatch; paired reader/writer "
            "resolved from two places"
        )
    print(f"consumer-side full JSON report: {report_path}")
    print(
        "consumer-side gate is REPORT-ONLY until a follow-on row authorises it; "
        f"proposed arm {CONSUMER_SIDE_ARM} is intentionally not implemented"
    )


def run_consumer_side(args: argparse.Namespace) -> int:
    repo_root = Path.cwd()
    try:
        allowlist = load_allowlist(args.allowlist)
        report = analyse_consumer_side(
            repo_root,
            allowlist,
            frame_path=args.frame,
            mass_path=args.mass,
        )
    except (AllowlistError, OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"[REPORT-ERROR] consumer-side analysis incomplete: {exc}")
        print(
            "consumer-side gate is REPORT-ONLY until a follow-on row authorises it; "
            f"proposed arm {CONSUMER_SIDE_ARM} is intentionally not implemented"
        )
        return 0
    report_path = _report_output_path(repo_root)
    write_consumer_side_json(report, report_path)
    print_consumer_side_report(report, report_path)
    return 0


# ── Diff plumbing ─────────────────────────────────────────────────────


def _run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=False,
        capture_output=True,
        text=True,
    )


def resolve_base(args: argparse.Namespace) -> str | None:
    if args.staged:
        return "HEAD"
    if args.diff_range:
        spec = args.diff_range
        if "..." in spec:
            left, _, right = spec.partition("...")
            result = _run_git(["merge-base", left, right or "HEAD"])
            return result.stdout.strip() if result.returncode == 0 else None
        if ".." in spec:
            return spec.split("..", 1)[0]
        return spec
    if args.base_ref:
        result = _run_git(["merge-base", args.base_ref, "HEAD"])
        return result.stdout.strip() if result.returncode == 0 else None
    return None


def changed_files(args: argparse.Namespace) -> list[tuple[str, Path, Path]]:
    """(status, head_path, base_path) for added/modified/renamed files."""
    command = ["diff", "--name-status"]
    if args.staged:
        command.append("--cached")
    elif args.diff_range:
        command.append(args.diff_range)
    elif args.base_ref:
        command.append(f"{args.base_ref}...HEAD")
    result = _run_git(command)
    if result.returncode != 0:
        print(f"git diff failed: {result.stderr.strip()}", file=sys.stderr)
        return []
    changes: list[tuple[str, Path, Path]] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        if status.startswith(("R", "C")) and len(parts) >= 3:
            changes.append(("M", Path(parts[2]), Path(parts[1])))
        elif status in ("A", "M"):
            changes.append((status, Path(parts[1]), Path(parts[1])))
    return changes


def base_content(base: str | None, path: Path) -> str | None:
    if base is None:
        return None
    result = _run_git(["show", f"{base}:{path.as_posix()}"])
    return result.stdout if result.returncode == 0 else None


# ── Gate core ─────────────────────────────────────────────────────────


def _module_name(path: Path) -> str:
    return ".".join(path.with_suffix("").parts)


def collect_refusals(
    repo_root: Path,
    changes: list[tuple[str, Path, Path]],
    base: str | None,
) -> list[Refusal]:
    refusals: list[Refusal] = []
    reads: set[str] | None = None  # lazy: scanning the tree is the expensive step

    def tree_reads() -> set[str]:
        nonlocal reads
        if reads is None:
            reads = collect_collection_reads(repo_root)
        return reads

    for status, path, old_path in changes:
        if path.suffix != ".py" or _is_test_path(path) or _is_excluded(path):
            continue
        head_source = _read(repo_root / path)
        if not head_source:
            continue
        base_source = base_content(base, old_path) if status == "M" else None

        # 1. Collection writers: only sites NEW in this PR trip the gate.
        head_writes = find_collection_writes(head_source, path)
        if head_writes:
            base_keys = {
                (w.collection, w.method)
                for w in (find_collection_writes(base_source, old_path) if base_source else [])
            }
            for write in head_writes:
                if (write.collection, write.method) in base_keys:
                    continue
                if write.collection is None:
                    refusals.append(
                        Refusal(
                            kind="collection writer",
                            label="<unresolvable>",
                            path=path,
                            lineno=write.lineno,
                            why=(
                                f"dynamic collection name in .{write.method}() is "
                                "unresolvable at merge time — the gate fails closed"
                            ),
                            key="collection:<unresolvable>",
                        )
                    )
                elif write.collection not in tree_reads():
                    refusals.append(
                        Refusal(
                            kind="collection writer",
                            label=write.collection,
                            path=path,
                            lineno=write.lineno,
                            why="no non-test reader of this collection exists in the tree",
                            key=f"collection:{write.collection}",
                        )
                    )

        # 2. Agents: a new entry module needs a live runner or importer.
        if status == "A" and is_agent_entry(path, head_source):
            module = _module_name(path)
            if path.name in ("__main__.py", "__init__.py"):
                # the consumable unit is the package, not the dunder module
                module = ".".join(path.parts[:-1])
            if not (
                has_runner_reference(repo_root, module)
                or has_nontest_importer(repo_root, module, path)
            ):
                refusals.append(
                    Refusal(
                        kind="agent",
                        label=module,
                        path=path,
                        lineno=1,
                        why=(
                            "no runner (systemd Exec*, compose, workflow, script, "
                            "[project.scripts]) or non-test importer references it"
                        ),
                        key=f"agent:{module}",
                    )
                )

        # 3. Surfaces: a new publisher needs its contract + a consumer.
        head_surfaces = [s for s in find_publisher_surfaces(head_source, path) if s.surface]
        if head_surfaces:
            base_classes = {
                s.class_name
                for s in (find_publisher_surfaces(base_source, old_path) if base_source else [])
            }
            module = _module_name(path)
            for surf in head_surfaces:
                if surf.class_name in base_classes:
                    continue
                assert surf.surface is not None
                missing: list[str] = []
                if not contract_yaml_exists(repo_root, surf.surface):
                    missing.append(f"contract axioms/contracts/publication/{surf.surface}.yaml")
                if not (
                    has_runner_reference(repo_root, module)
                    or has_nontest_importer(repo_root, module, path)
                ):
                    missing.append("a runner reference or non-test importer")
                if missing:
                    refusals.append(
                        Refusal(
                            kind="surface",
                            label=surf.surface,
                            path=path,
                            lineno=surf.lineno,
                            why=f"missing {' and '.join(missing)}",
                            key=f"surface:{surf.surface}",
                        )
                    )
    return refusals


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--staged", action="store_true", help="gate the staged diff")
    scope.add_argument("--base-ref", help="gate producers added since merge-base with this ref")
    scope.add_argument("--diff-range", help="gate producers added in an explicit git diff range")
    scope.add_argument(
        "--consumer-side",
        action="store_true",
        help="report whole-tree consumers with missing, mismatched, or decayed producers",
    )
    parser.add_argument("--frame", type=Path, help="optional frame elements.json decay verdicts")
    parser.add_argument(
        "--mass", type=Path, help="optional frame mass.yaml member/path declaration"
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=DEFAULT_ALLOWLIST_PATH,
        help="JSON allowlist of intentional consumer-less producers (reason required)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.consumer_side:
        return run_consumer_side(args)
    if args.frame is not None or args.mass is not None:
        print("--frame/--mass require --consumer-side", file=sys.stderr)
        return 2
    if not (args.staged or args.base_ref or args.diff_range):
        print("no diff scope given (--staged / --base-ref / --diff-range); skipping")
        return 0

    repo_root = Path.cwd()
    try:
        allowlist = load_allowlist(args.allowlist)
    except AllowlistError as exc:
        print(f"[REFUSED] {exc}")
        print("Every allowlist entry must carry a 'reason' — the exit is governed.")
        return 1

    changes = changed_files(args)
    if not changes:
        print("no added/modified files in scope; consumer-existence gate passes")
        return 0

    base = resolve_base(args)
    refusals = collect_refusals(repo_root, changes, base)

    allowed = 0
    blocking: list[Refusal] = []
    for refusal in refusals:
        entry = is_allowlisted(refusal.key, refusal.path, allowlist)
        if entry is not None:
            allowed += 1
            print(
                f"[ALLOWLISTED] {refusal.kind} '{refusal.label}' "
                f"({refusal.path}:{refusal.lineno}) — reason: {entry.reason}"
            )
        else:
            blocking.append(refusal)

    if blocking:
        print("\nConsumer-existence gate REFUSED this diff (UNWIRED-WORK / A1):")
        for r in blocking:
            print(f"  [REFUSED] {r.kind} '{r.label}' ({r.path}:{r.lineno}) — {r.why}")
        print("\nNext actions:")
        print("  1. Wire a real consumer in non-test code (reader / runner / importer);")
        print("     adding it in this same PR satisfies the gate.")
        print("  2. If this producer is intentionally consumer-less, add a pattern WITH a")
        print(f"     reason to {DEFAULT_ALLOWLIST_PATH}.")
        print(f"  3. Re-check: {RECHECK_CMD}")
        return 1

    print(
        "consumer-existence gate passes "
        f"({len(changes)} changed file(s), {allowed} allowlisted producer(s))"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
