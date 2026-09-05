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
import copy
import fnmatch
import json
import os
import re
import subprocess
import sys
import tomllib
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
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


def _parse(
    source: str, path: Path, source_gaps: list[SourceGap] | None = None
) -> ast.Module | None:
    try:
        return ast.parse(source, filename=str(path))
    except (SyntaxError, ValueError) as exc:
        if source_gaps is not None:
            source_gaps.append(SourceGap(path, "parse", type(exc).__name__))
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


def _read(
    path: Path,
    source_gaps: list[SourceGap] | None = None,
    repo_root: Path | None = None,
) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        if source_gaps is not None:
            relative = path.relative_to(repo_root) if repo_root is not None else path
            source_gaps.append(SourceGap(relative, "read", type(exc).__name__))
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
        # Kinds are separate authority domains.  In particular, the producer-side caller uses
        # ``kind=None`` for the original untyped entries; that must not turn a consumer-side exit
        # into a wildcard exemption for a producer refusal.
        if entry.kind != kind:
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
    "consumer-reads-through-unmodelled-api",
    "consumer-reads-artifact-under-dynamic-root",
    "consumer-reads-artifact-with-non-python-producer",
    "consumer-reads-artifact-documented-elsewhere",
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
    modelled: bool = True
    bounded: bool = True
    # None denotes a literal filename. Patterns contain escaped literal components.
    glob_pattern: str | None = None


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


@dataclass(frozen=True)
class SourceGap:
    path: Path
    operation: str
    error_class: str


@dataclass
class ConsumerSideReport:
    findings: list[ConsumerSideFinding]
    allowlisted: list[tuple[ConsumerSideFinding, AllowlistEntry]]
    pairs: list[ArtifactPair]
    unresolvable: int
    exclusions: dict[str, int]
    errors: tuple[str, ...] = ()
    # Calls whose callee this scanner does not model but whose argument resolved to a path
    # (review finding on #4626, round 5). Read-shaped calls also produce a finding; the counter
    # retains every such call so unsupported write APIs remain visible without fabricating writes.
    unrecognised_path_calls: dict[str, int] = field(default_factory=dict)
    # What this report measured (review finding on #4626, round 8, and the dominator consumer's
    # own need): a report with no head is unusable by any later reader, because nothing says
    # which tree it describes.
    measured: dict[str, object] = field(default_factory=dict)
    source_gaps: tuple[SourceGap, ...] = ()
    capped_expressions: tuple[str, ...] = ()
    unresolved_closures: tuple[str, ...] = ()
    unresolved_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class PathFunction:
    params: tuple[str, ...]
    return_expr: ast.expr | None
    module_values: dict[str, str]
    path: Path
    returns_path: bool = False
    lexical_prefixes: tuple[str, ...] = ()
    node: ast.FunctionDef | ast.AsyncFunctionDef | None = None


@dataclass(frozen=True)
class LexicalScope:
    qualname: str
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda
    lexical_prefixes: tuple[str, ...]


class PathFunctionTable(dict[str, PathFunction]):
    """Path helpers keyed by their qualified name (``module.function``).

    A repository-global table keyed by bare function name let a later module's ``artifact_path``
    overwrite an earlier module's, so calls in the earlier module resolved through an unrelated
    return expression (review finding on #4626, round 5). Resolution now follows lexical scope,
    then the calling module and explicit import bindings; it never guesses via an unrelated bare
    helper elsewhere in the tree.
    """

    def __init__(self) -> None:
        super().__init__()
        self.imports_by_path: dict[Path, frozenset[str]] = {}
        self.aliases_by_path: dict[Path, dict[str, str]] = {}
        self.capped_expressions: set[str] = set()
        self.unresolved_closures: set[str] = set()
        self.unresolved_paths: set[str] = set()
        self.helper_results: dict[tuple[int, tuple[tuple[str, str], ...]], str | None] = {}
        self.definition_defaults: dict[ast.AST, dict[str, str]] = {}
        self.call_bindings: dict[ast.AST, list[dict[str, str]]] = {}

    def register(self, relative: Path, qualname: str, function: PathFunction) -> None:
        self[f"{_module_name(relative)}.{qualname}"] = function
        self.helper_results.clear()

    def canonical_name(
        self,
        name: str,
        calling_path: Path,
        lexical_prefixes: tuple[str, ...] = (),
        aliases: dict[str, str] | None = None,
    ) -> str:
        """Resolve the import binding used by a call without guessing through shadowing."""
        if not name:
            return name
        head, separator, tail = name.partition(".")
        bindings = self.aliases_by_path.get(calling_path, {}) if aliases is None else aliases
        if head in bindings:
            target = bindings[head]
            if not target:  # An assignment in this scope shadows the imported binding.
                return ""
            return f"{target}.{tail}" if separator else target
        module = _module_name(calling_path)
        if not separator:
            # A lexically local or module-level helper shadows a same-named import.
            local_keys = [f"{module}.{prefix}.{head}" for prefix in lexical_prefixes]
            if any(key in self for key in (*local_keys, f"{module}.{head}")):
                return name
        return name

    def resolve(
        self,
        name: str,
        calling_path: Path,
        lexical_prefixes: tuple[str, ...] = (),
        aliases: dict[str, str] | None = None,
    ) -> PathFunction | None:
        if not self.canonical_name(name, calling_path, lexical_prefixes, aliases):
            return None
        short = name.rsplit(".", 1)[-1]
        imports = self.imports_by_path.get(calling_path, frozenset())
        if "." in name:
            # A qualified call names its module: the exact key, or the qualifier mapped through
            # the caller's imports. It never falls back to the caller's own helper of the same
            # name (review finding on #4626, round 6: other.artifact_path() resolved locally).
            canonical = self.canonical_name(name, calling_path, lexical_prefixes, aliases)
            if canonical in self:
                return self[canonical]
            qualifier = canonical.rsplit(".", 1)[0]
            for imported in imports:
                if imported == qualifier or imported.endswith(f".{qualifier}"):
                    candidate = self.get(f"{imported}.{short}")
                    if candidate is not None:
                        return candidate
            return None
        module = _module_name(calling_path)
        for prefix in lexical_prefixes:
            lexical = self.get(f"{module}.{prefix}.{short}")
            if lexical is not None:
                return lexical
        own = self.get(f"{module}.{short}")
        if own is not None:
            return own
        canonical = self.canonical_name(name, calling_path, lexical_prefixes, aliases)
        if canonical != name:
            imported = self.get(canonical)
            if imported is not None:
                return imported
        imported_candidates: dict[str, PathFunction] = {}
        for imported in imports:
            candidate = self.get(f"{imported}.{short}")
            if candidate is None and imported.endswith(f".{short}"):
                candidate = self.get(imported)
            if candidate is not None:
                imported_candidates[str(candidate.path)] = candidate
        if len(imported_candidates) == 1:
            return next(iter(imported_candidates.values()))
        # A repository-global bare-name fallback can bind a caller to a nested method in an
        # unrelated module. Local and imported helpers above are the only sound bare bindings.
        return None


def _dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


# NUL cannot occur in a filename. Protect literal metacharacters in the value maps
# (including serialized branch unions), retaining bare '*' only for dynamic patterns.
_LITERAL_GLOB_MARKERS = {"*": "\0star", "?": "\0question", "[": "\0left", "]": "\0right"}


def _literal_path(value: str) -> str:
    # Invalid source literals must not impersonate the internal provenance markers.
    return value.replace("\0", "\0nul").translate(str.maketrans(_LITERAL_GLOB_MARKERS))


def _literal_text(value: str, *, escape: bool = False) -> str:
    for character, marker in _LITERAL_GLOB_MARKERS.items():
        value = value.replace(marker, f"[{character}]" if escape else character)
    return value


def _normalise_pattern(value: str, repo_root: Path) -> str:
    # This estate uses POSIX paths. A backslash produced by !r/!a is a filename
    # character, not a directory separator.
    if value.startswith("$HOME\\"):
        value = value.replace("\\", "/")
    if value == "$HOME":
        value = "~"
    elif value.startswith("$HOME/"):
        value = "~/" + value[len("$HOME/") :]
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
    """Return the sole expression in this function, excluding nested lexical scopes."""

    class _OwnReturnVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.returns: list[ast.expr] = []

        def visit_Return(self, item: ast.Return) -> None:
            if item.value is not None:
                self.returns.append(item.value)

        def visit_FunctionDef(self, item: ast.FunctionDef) -> None:
            return

        def visit_AsyncFunctionDef(self, item: ast.AsyncFunctionDef) -> None:
            return

        def visit_Lambda(self, item: ast.Lambda) -> None:
            return

        def visit_ClassDef(self, item: ast.ClassDef) -> None:
            return

    visitor = _OwnReturnVisitor()
    for statement in node.body:
        visitor.visit(statement)
    return visitor.returns[0] if len(visitor.returns) == 1 else None


def _function_defaults(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
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


def _call_parameter_values(
    function: PathFunction,
    call: ast.Call,
    values: dict[str, str],
    path: Path,
    repo_root: Path,
    path_functions: dict[str, PathFunction],
) -> dict[str, str]:
    supplied: dict[str, ast.expr | None] = (
        dict.fromkeys(function.params)
        if any(isinstance(arg, ast.Starred) for arg in call.args)
        or any(kw.arg is None for kw in call.keywords)
        else {}
    )
    # A starred argument changes all later positional indices; do not guess them.
    for name, argument in zip(function.params, call.args, strict=False):
        if isinstance(argument, ast.Starred):
            break
        supplied[name] = argument
    supplied.update((kw.arg, kw.value) for kw in call.keywords if kw.arg is not None)
    bound: dict[str, str] = {}
    for name, expression in supplied.items():
        assigned = _apply_assignment(
            ast.Assign(targets=[ast.Name(id=name)], value=expression),
            values,
            path,
            repo_root,
            path_functions,
        )[0]
        bound.update((key, assigned[key]) for key in _binding_keys(name) if key in assigned)
    return bound


_MAX_PATH_EXPR_VARIANTS = 8
_PATH_VALUE_PREFIX = "\0path-value:"
_LEXICAL_SCOPE_KEY = "\0lexical-scope"
_IMPORT_ALIAS_PREFIX = "\0import-alias:"
_VALUE_ALTERNATIVES_PREFIX = "\0value-alternatives:"
_CONSTANT_VALUE_PREFIX = "\0constant-value:"
_UNRESOLVED_FORMAT_PREFIX = "\0unresolved-format:"
_UNRESOLVED_CLOSURE_PREFIX = "\0unresolved-closure:"
_HELPER_STACK_KEY = "\0helper-stack"
_HELPER_EFFECT_KEY = "\0helper-unbounded-effect"
_FLOW_EXIT_KEY = "\0flow-exit"
_PATH_CONSTRUCTORS = frozenset(
    {
        "Path",
        "PurePath",
        "PurePosixPath",
        "pathlib.Path",
        "pathlib.PurePath",
        "pathlib.PurePosixPath",
    }
)


def _path_value_key(name: str) -> str:
    return f"{_PATH_VALUE_PREFIX}{name}"


def _set_path_value(values: dict[str, str], name: str, is_path: bool) -> None:
    key = _path_value_key(name)
    if is_path:
        values[key] = "1"
    else:
        values.pop(key, None)


def _set_lexical_scope(values: dict[str, str], prefixes: tuple[str, ...]) -> None:
    if prefixes:
        values[_LEXICAL_SCOPE_KEY] = "|".join(prefixes)
    else:
        values.pop(_LEXICAL_SCOPE_KEY, None)


def _lexical_scope(values: dict[str, str]) -> tuple[str, ...]:
    encoded = values.get(_LEXICAL_SCOPE_KEY, "")
    return tuple(part for part in encoded.split("|") if part)


def _set_import_alias(values: dict[str, str], name: str, target: str | None) -> None:
    values[f"{_IMPORT_ALIAS_PREFIX}{name}"] = target or ""


def _import_aliases(values: dict[str, str]) -> dict[str, str]:
    return {
        key.removeprefix(_IMPORT_ALIAS_PREFIX): target
        for key, target in values.items()
        if key.startswith(_IMPORT_ALIAS_PREFIX)
    }


def _value_alternatives_key(name: str) -> str:
    return f"{_VALUE_ALTERNATIVES_PREFIX}{name}"


def _set_value_alternatives(
    values: dict[str, str], name: str, alternatives: set[str | None]
) -> None:
    ordered = sorted(alternatives, key=lambda item: (item is None, item or ""))
    values[_value_alternatives_key(name)] = json.dumps(ordered)


def _clear_value_alternatives(values: dict[str, str], name: str) -> None:
    values.pop(_value_alternatives_key(name), None)


def _value_alternatives(values: dict[str, str], name: str) -> tuple[str | None, ...] | None:
    encoded = values.get(_value_alternatives_key(name))
    if encoded is None:
        return None
    decoded = json.loads(encoded)
    return tuple(item if isinstance(item, str) else None for item in decoded)


def _expand_value_alternative_states(
    node: ast.expr, values: dict[str, str]
) -> list[dict[str, str]]:
    """Expand only abstract bindings referenced by ``node`` into concrete value states."""
    referenced = sorted({item.id for item in ast.walk(node) if isinstance(item, ast.Name)})
    expanded = [dict(values)]
    for name in referenced:
        alternatives = _value_alternatives(values, name)
        if alternatives is None:
            continue
        next_states: list[dict[str, str]] = []
        for state in expanded:
            for alternative in alternatives:
                concrete = dict(state)
                _clear_value_alternatives(concrete, name)
                if alternative is None:
                    concrete.pop(name, None)
                else:
                    concrete[name] = alternative
                next_states.append(concrete)
        expanded = next_states
    return expanded


def _first_conditional_expression_path(
    node: ast.AST, path: tuple[tuple[str, int | None], ...] = ()
) -> tuple[tuple[str, int | None], ...] | None:
    # These expressions cannot resolve to a path. Their contents (notably lambda bodies and
    # collection literals) are not alternatives of the containing path expression.
    if isinstance(
        node,
        (
            ast.Lambda,
            ast.Dict,
            ast.List,
            ast.Set,
            ast.Tuple,
            ast.ListComp,
            ast.SetComp,
            ast.DictComp,
            ast.GeneratorExp,
        ),
    ):
        return None
    if isinstance(node, ast.IfExp) or (
        isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)
    ):
        return path
    for field_name in node._fields:
        value = getattr(node, field_name)
        if isinstance(value, ast.AST):
            found = _first_conditional_expression_path(value, (*path, (field_name, None)))
            if found is not None:
                return found
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if not isinstance(item, ast.AST):
                    continue
                found = _first_conditional_expression_path(item, (*path, (field_name, index)))
                if found is not None:
                    return found
    return None


def _ast_node_at(node: ast.AST, path: tuple[tuple[str, int | None], ...]) -> ast.AST:
    current = node
    for field_name, index in path:
        value = getattr(current, field_name)
        current = value if index is None else value[index]
    return current


def _replace_ast_node(
    node: ast.expr,
    path: tuple[tuple[str, int | None], ...],
    replacement: ast.expr,
) -> ast.expr:
    if not path:
        return copy.deepcopy(replacement)
    result = copy.deepcopy(node)
    current: ast.AST = result
    for field_name, index in path[:-1]:
        value = getattr(current, field_name)
        current = value if index is None else value[index]
    field_name, index = path[-1]
    if index is None:
        setattr(current, field_name, copy.deepcopy(replacement))
    else:
        getattr(current, field_name)[index] = copy.deepcopy(replacement)
    return result


def _conditional_expr_variants(node: ast.expr | None) -> tuple[list[ast.expr], bool]:
    """Expand conditional and ``or`` expressions without selecting one possible branch."""
    if node is None:
        return [], False
    pending = [node]
    resolved: list[ast.expr] = []
    truncated = False
    while pending:
        expression = pending.pop()
        conditional_path = _first_conditional_expression_path(expression)
        if conditional_path is None:
            resolved.append(expression)
            continue
        conditional = _ast_node_at(expression, conditional_path)
        if isinstance(conditional, ast.IfExp):
            alternatives = (conditional.body, conditional.orelse)
        else:
            assert isinstance(conditional, ast.BoolOp) and isinstance(conditional.op, ast.Or)
            alternatives = tuple(conditional.values)
        if len(pending) + len(resolved) + len(alternatives) > _MAX_PATH_EXPR_VARIANTS:
            truncated = True
            # Keep the remaining disjunction as a compact union. The cap bounds expanded ASTs,
            # never the set of concrete artifacts that can be read from this expression.
            resolved.append(expression)
            continue
        pending.extend(
            _replace_ast_node(expression, conditional_path, alternative)
            for alternative in reversed(alternatives)
        )
    return resolved, truncated


def _expand_conditional_union(expression: ast.expr) -> Iterator[ast.expr]:
    """Stream leaves of a compact union without materialising its Cartesian product."""
    conditional_path = _first_conditional_expression_path(expression)
    if conditional_path is None:
        yield expression
        return
    conditional = _ast_node_at(expression, conditional_path)
    alternatives = (
        (conditional.body, conditional.orelse)
        if isinstance(conditional, ast.IfExp)
        else conditional.values
    )
    for alternative in alternatives:
        yield from _expand_conditional_union(
            _replace_ast_node(expression, conditional_path, alternative)
        )


def _path_expressions(
    node: ast.expr | None, path: Path, path_functions: dict[str, PathFunction]
) -> Iterator[ast.expr]:
    expressions, capped = _conditional_expr_variants(node)
    if capped and node is not None and isinstance(path_functions, PathFunctionTable):
        path_functions.capped_expressions.add(f"{path}:{node.lineno}:{node.col_offset}")
    for expression in expressions:
        yield from _expand_conditional_union(expression)


def _resolve_path_expr_variants(
    node: ast.expr | None,
    values: dict[str, str],
    path: Path,
    repo_root: Path,
    path_functions: dict[str, PathFunction],
) -> tuple[str | None, ...]:
    variants = [
        _resolve_path_expr(expression, state, path, repo_root, path_functions)
        for expression in _path_expressions(node, path, path_functions)
        for state in _expand_value_alternative_states(expression, values)
    ]
    if not variants:
        variants.append(None)
    return tuple(dict.fromkeys(variants))


def _constant_value(node: ast.expr | None, values: dict[str, str]) -> tuple[bool, object]:
    """Keep scalar types for formatting; a path-shaped abstract string is not a constant."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, type(None))):
        return True, node.value
    if isinstance(node, ast.Name):
        encoded = values.get(f"{_CONSTANT_VALUE_PREFIX}{node.id}")
        if encoded is not None:
            return True, json.loads(encoded)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        known, value = _constant_value(node.operand, values)
        if known and isinstance(value, (int, float)):
            return True, -value if isinstance(node.op, ast.USub) else +value
    return False, None


def _format_constant(node: ast.FormattedValue, values: dict[str, str]) -> str | None:
    known, value = _constant_value(node.value, values)
    if not known:
        return None
    spec = ""
    if node.format_spec is not None:
        if not isinstance(node.format_spec, ast.JoinedStr) or any(
            not isinstance(item, ast.Constant) or not isinstance(item.value, str)
            for item in node.format_spec.values
        ):
            return None
        spec = "".join(item.value for item in node.format_spec.values)
    conversions = {ord("r"): repr, ord("s"): str, ord("a"): ascii}
    if node.conversion != -1:
        conversion = conversions.get(node.conversion)
        if conversion is None:
            return None
        value = conversion(value)
    try:
        return format(value, spec)
    except (ValueError, TypeError, OverflowError):
        return None


def _has_unbounded_format(
    node: ast.expr | None,
    values: dict[str, str],
    path: Path,
    repo_root: Path,
    path_functions: dict[str, PathFunction],
) -> bool:
    if node is None:
        return False
    for item in ast.walk(node):
        if isinstance(item, ast.Name) and f"{_UNRESOLVED_FORMAT_PREFIX}{item.id}" in values:
            return True
        if isinstance(item, ast.Call) and isinstance(path_functions, PathFunctionTable):
            helper = path_functions.resolve(
                _function_name(item), path, _lexical_scope(values), _import_aliases(values)
            )
            if helper is not None and "*" in (
                _resolve_path_expr(item, values, path, repo_root, path_functions) or ""
            ):
                return True
        if isinstance(item, ast.FormattedValue) and _format_constant(item, values) is None:
            if (
                item.format_spec is not None
                or item.conversion != -1
                or _resolve_path_expr(item.value, values, path, repo_root, path_functions)
                in (None, "*")
            ):
                return True
    return False


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
    # An unbounded closure cell is not a dynamic path component. In particular, formatting
    # it must not turn an obsolete binding into a wildcard producer.
    if depth == 0 and any(
        f"{_UNRESOLVED_CLOSURE_PREFIX}{item.id}" in values
        for item in ast.walk(node)
        if isinstance(item, ast.Name)
    ):
        return None
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (str, int)):
            return _literal_path(str(node.value))
        return None
    if isinstance(node, ast.Name):
        if node.id == "__file__":
            return _literal_path(path.as_posix())
        return values.get(node.id)
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for item in node.values:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                parts.append(_literal_path(item.value))
            elif isinstance(item, ast.FormattedValue):
                formatted = _format_constant(item, values)
                if formatted is not None:
                    parts.append(_literal_path(formatted))
                    continue
                if item.format_spec is not None or item.conversion != -1:
                    return None
                # Preserve the existing unformatted dynamic-pattern gap evidence. Explicit
                # formatting cannot use this approximation: its type/spec must be known.
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
        resolved = [
            _resolve_path_expr(item, values, path, repo_root, path_functions, depth=depth + 1)
            for item in node.values
        ]
        # Access and assignment callers expand ``or`` first.  A nested caller that cannot carry
        # variants must refuse an ambiguous choice instead of silently selecting one branch.
        return resolved[0] if resolved and all(item == resolved[0] for item in resolved) else None
    if isinstance(node, ast.IfExp):
        left = _resolve_path_expr(
            node.body, values, path, repo_root, path_functions, depth=depth + 1
        )
        right = _resolve_path_expr(
            node.orelse, values, path, repo_root, path_functions, depth=depth + 1
        )
        # Access and assignment callers expand conditional expressions before resolving them.
        # Any other caller must fail closed instead of silently choosing one possible path.
        return left if left == right else None
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

    name = (
        path_functions.canonical_name(
            _function_name(node), path, _lexical_scope(values), _import_aliases(values)
        )
        if isinstance(path_functions, PathFunctionTable)
        else _function_name(node)
    )
    if name in _PATH_CONSTRUCTORS:
        components: list[str] = []
        for argument in node.args:
            component = _resolve_path_expr(
                argument, values, path, repo_root, path_functions, depth=depth + 1
            )
            if component is None or (
                component == "*"
                and not (isinstance(argument, ast.Constant) and argument.value == "*")
            ):
                return None
            if len(node.args) > 1 and any(
                _resolve_path_expr(
                    item.value, values, path, repo_root, path_functions, depth=depth + 1
                )
                in (None, "*")
                for item in ast.walk(argument)
                if isinstance(item, ast.FormattedValue)
            ):
                return None
            components.append(component)
        # Preserve absolute components until the entire construction has been joined. Early
        # repository-relative normalization loses a nested Path's absolute reset semantics.
        return str(PurePosixPath(*components))
    if name == "str":
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

    function = (
        path_functions.resolve(name, path, _lexical_scope(values), _import_aliases(values))
        if isinstance(path_functions, PathFunctionTable)
        else (path_functions.get(name) or path_functions.get(name.rsplit(".", 1)[-1]))
    )
    if function is None or function.node is None or function.return_expr is None:
        return None
    if (
        isinstance(path_functions, PathFunctionTable)
        and function.node not in path_functions.definition_defaults
    ):
        # Registration discovers syntax, but an unreachable definition creates no binding.
        return None
    helper_key = f"{function.path}:{function.node.lineno}"
    stack = values.get(_HELPER_STACK_KEY, "").split("|")
    if helper_key in stack or len(stack) > 12:
        return None
    inherited = dict(function.module_values)
    if path == function.path and not _lexical_scope(values):
        # A module expression (including a default) calls the helper with the globals
        # available at that point, before later module stores.
        inherited = dict(values)
    if len(function.lexical_prefixes) > 1:
        if function.lexical_prefixes[1] not in _lexical_scope(values):
            return None
        # Closure cells come from the enclosing invocation, while declared globals still
        # belong to the defining module. Local stores are reset by _scope_initial_values.
        inherited.update(values)
        for statement in ast.walk(function.node):
            if isinstance(statement, ast.Global):
                for global_name in statement.names:
                    for key in _binding_keys(global_name):
                        inherited.pop(key, None)
                        if key in function.module_values:
                            inherited[key] = function.module_values[key]
    inherited[_HELPER_STACK_KEY] = "|".join((*stack, helper_key))
    bound = _scope_initial_values(
        function.node,
        inherited,
        function.path,
        repo_root,
        path_functions,
        function.lexical_prefixes,
    )
    supplied = _call_parameter_values(function, node, values, path, repo_root, path_functions)
    _invalidate_names(bound, {name for name in supplied if not name.startswith("\0")})
    bound.update(supplied)
    cache = path_functions.helper_results if isinstance(path_functions, PathFunctionTable) else {}
    cache_key = (id(function), tuple(sorted(bound.items())))
    if cache_key in cache:
        return cache[cache_key]
    scanner = _PathHelperScanner(
        path=function.path,
        repo_root=repo_root,
        path_functions=path_functions,
        accesses=[],
        unresolved=[0],
        unrecognised=Counter(),
        context_family="path-helper",
        nested_scope_values={},
    )
    fallthrough = scanner.scan_block(function.node.body, [bound])
    result = (
        next(iter(scanner.return_values))
        if not fallthrough and len(scanner.return_values) == 1
        else None
    )
    # Classification and assignment evaluate the same calls; memoize their binding state so
    # nested helpers do not repeatedly expand the same bodies. Bound the per-scan cache.
    if len(cache) >= 4096:
        cache.clear()
    cache[cache_key] = result
    return result


def _is_path_annotation(node: ast.expr | None) -> bool:
    name = _dotted_name(node) if node is not None else None
    return bool(name and name.rsplit(".", 1)[-1] == "Path")


def _is_path_valued_expr(
    node: ast.expr | None,
    values: dict[str, str],
    path: Path,
    path_functions: dict[str, PathFunction],
    *,
    depth: int = 0,
) -> bool:
    """Whether an expression is modelled as a pathlib path, never merely path-shaped text."""
    if node is None or depth > 12:
        return False
    if isinstance(node, ast.Name):
        return _path_value_key(node.id) in values
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _is_path_valued_expr(node.left, values, path, path_functions, depth=depth + 1)
    if isinstance(node, ast.IfExp):
        return _is_path_valued_expr(
            node.body, values, path, path_functions, depth=depth + 1
        ) and _is_path_valued_expr(node.orelse, values, path, path_functions, depth=depth + 1)
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        return bool(node.values) and all(
            _is_path_valued_expr(item, values, path, path_functions, depth=depth + 1)
            for item in node.values
        )
    if isinstance(node, ast.Attribute):
        return node.attr == "parent" and _is_path_valued_expr(
            node.value, values, path, path_functions, depth=depth + 1
        )
    if not isinstance(node, ast.Call):
        return False
    name = (
        path_functions.canonical_name(
            _function_name(node), path, _lexical_scope(values), _import_aliases(values)
        )
        if isinstance(path_functions, PathFunctionTable)
        else _function_name(node)
    )
    if name in {"Path", "pathlib.Path", "Path.home", "pathlib.Path.home"}:
        return True
    if isinstance(node.func, ast.Attribute) and node.func.attr in {
        "expanduser",
        "absolute",
        "resolve",
        "with_suffix",
        "with_name",
    }:
        return _is_path_valued_expr(node.func.value, values, path, path_functions, depth=depth + 1)
    function = (
        path_functions.resolve(name, path, _lexical_scope(values), _import_aliases(values))
        if isinstance(path_functions, PathFunctionTable)
        else (path_functions.get(name) or path_functions.get(name.rsplit(".", 1)[-1]))
    )
    return bool(function and function.returns_path)


def _iter_python_sources(
    repo_root: Path, *, tests_only: bool = False, source_gaps: list[SourceGap] | None = None
) -> list[Path]:
    files: set[Path] = set()

    def unread_directory(exc: OSError) -> None:
        if source_gaps is not None:
            failed = Path(exc.filename) if exc.filename else repo_root
            source_gaps.append(SourceGap(failed.relative_to(repo_root), "read", type(exc).__name__))

    # Prune excluded trees before descending. os.walk's error callback also makes unreadable
    # source directories visible; pathlib glob silently suppresses directory-listing failures.
    for directory, subdirs, names in os.walk(repo_root, onerror=unread_directory):
        subdirs[:] = [name for name in subdirs if name not in EXCLUDE_DIR_PARTS]
        for name in names:
            candidate = Path(directory) / name
            relative = candidate.relative_to(repo_root)
            is_test = _is_test_path(relative)
            if tests_only != is_test:
                continue
            if candidate.suffix == ".py":
                files.add(candidate)
            elif not tests_only and relative.parts[0] == "scripts":
                source = _read(candidate, source_gaps, repo_root)
                if source.startswith("#!/") and "python" in source.splitlines()[0]:
                    files.add(candidate)
    return sorted(files)


def _module_values(
    tree: ast.Module,
    path: Path,
    repo_root: Path,
    path_functions: dict[str, PathFunction],
) -> dict[str, str]:
    scanner = _ModuleBindingScanner(
        path=path,
        repo_root=repo_root,
        path_functions=path_functions,
        accesses=[],
        unresolved=[0],
        unrecognised=Counter(),
        context_family="module-bindings",
        nested_scope_values={},
    )
    states = scanner.scan_block(tree.body, [{"__file__": path.as_posix()}])
    return _merge_states(states, collapse=True)[0] if states else {}


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
        and _literal_text(pattern).isprintable()
        and pattern not in {"*", ".", "~"}
        and pattern.strip("*/.")
    )


def _looks_like_artifact_pattern(pattern: str | None) -> bool:
    if not _useful_pattern(pattern) or pattern is None or any(char.isspace() for char in pattern):
        return False
    path = PurePosixPath(pattern)
    return (
        pattern.startswith(("/", "~/", "./", "../"))
        or "/" in pattern
        or bool(path.suffix)
        or any(marker in pattern for marker in "*?[")
    )


def _mode_effect(call: ast.Call, position: int) -> str:
    """Read/write from a mode argument at ``position`` (or ``mode=``), as tarfile.open and
    zipfile.ZipFile take it; ``_open_effect`` reads Path.open's first argument instead."""
    mode_node: ast.expr | None = call.args[position] if len(call.args) > position else None
    for keyword in call.keywords:
        if keyword.arg == "mode":
            mode_node = keyword.value
    mode = mode_node.value if isinstance(mode_node, ast.Constant) else "r"
    return "write" if isinstance(mode, str) and any(flag in mode for flag in "wax") else "read"


def _open_effect(call: ast.Call, *, path_method: bool) -> str:
    """Classify open without confusing a module function's path with ``Path.open``'s mode."""
    return _mode_effect(call, 0 if path_method else 1)


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
    modelled: bool = True,
) -> None:
    bounded = not _has_unbounded_format(expression, values, path, repo_root, path_functions)
    for pattern in _resolve_path_expr_variants(expression, values, path, repo_root, path_functions):
        if pattern is not None and append is not None:
            pattern = _join_pattern(pattern, append, repo_root)
        if not _useful_pattern(pattern) or not bounded:
            unresolved[0] += 1
            if isinstance(path_functions, PathFunctionTable):
                expression_label = (
                    ast.unparse(expression) if expression is not None else "<unknown>"
                )
                path_functions.unresolved_paths.add(
                    f"{path}:{call.lineno}:{call.col_offset}: {action} {operation} "
                    f"path={expression_label}"
                )
            if not _useful_pattern(pattern):
                continue
        assert pattern is not None
        pattern = _normalise_pattern(pattern, repo_root)
        accesses.append(
            ArtifactAccess(
                action,
                _literal_text(pattern),
                path,
                call.lineno,
                family,
                operation,
                modelled,
                bounded,
                _literal_text(pattern, escape=True)
                if any(marker in pattern for marker in "*?[")
                else None,
            )
        )


def _classify_call(
    call: ast.Call,
    values: dict[str, str],
    path: Path,
    repo_root: Path,
    path_functions: dict[str, PathFunction],
    accesses: list[ArtifactAccess],
    unresolved: list[int],
    unrecognised: Counter[str],
    context_family: str,
) -> None:
    raw_name = _function_name(call)
    name = (
        path_functions.canonical_name(
            raw_name, path, _lexical_scope(values), _import_aliases(values)
        )
        if isinstance(path_functions, PathFunctionTable)
        else raw_name
    )
    short_name = name.rsplit(".", 1)[-1]
    if name in FILE_BACKED_APIS:
        # A file-backed API this scanner models as an access (review finding on #4626, round 5:
        # sqlite3.connect fell through without an access and without an unresolvable count). It
        # is tested first: shelve.open, dbm.open and tarfile.open end in "open", and the generic
        # open branch below would read the module object as the path (round 6).
        action, position, keyword = FILE_BACKED_APIS[name]
        if action == "mode":
            action = _mode_effect(call, position + 1)
        _record_access(
            accesses,
            unresolved,
            action=action,
            expression=_call_argument(call, position, keyword),
            call=call,
            values=values,
            path=path,
            repo_root=repo_root,
            path_functions=path_functions,
            family=context_family,
            operation=name,
        )
    elif isinstance(call.func, ast.Attribute) and call.func.attr in {
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
    elif short_name == "open" or (
        isinstance(call.func, ast.Attribute) and call.func.attr == "open"
    ):
        receiver = call.func.value if isinstance(call.func, ast.Attribute) else None
        path_method = receiver is not None and _is_path_valued_expr(
            receiver, values, path, path_functions
        )
        known_function = name in {"open", "builtins.open", "codecs.open", "io.open"}
        expression = receiver if path_method else _call_argument(call, 0, "file") if name else None
        operation = "Path.open" if path_method else name or raw_name
        _record_access(
            accesses,
            unresolved,
            # An unknown ``obj.open`` signature cannot authorize a writer.  Retaining it as an
            # unmodelled read is conservative: it remains visible and cannot suppress an orphan.
            action=_open_effect(call, path_method=path_method)
            if known_function or path_method
            else "read",
            expression=expression,
            call=call,
            values=values,
            path=path,
            repo_root=repo_root,
            path_functions=path_functions,
            family=context_family,
            operation=operation,
            modelled=known_function or path_method,
        )
        if not known_function and not path_method:
            unrecognised[name or raw_name] += 1
    elif isinstance(call.func, ast.Attribute) and call.func.attr in {"glob", "rglob"}:
        suffix = _resolve_path_expr(
            _call_argument(call, 0), values, path, repo_root, path_functions
        )
        if suffix is None:
            unresolved[0] += 1
        else:
            # Only the glob argument is pattern syntax; the receiver stays literal.
            suffix = _literal_text(suffix)
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
    elif name in {"os.replace", "os.rename", "os.renames"}:
        _record_access(
            accesses,
            unresolved,
            action="read",
            expression=_call_argument(call, 0, "src"),
            call=call,
            values=values,
            path=path,
            repo_root=repo_root,
            path_functions=path_functions,
            family=context_family,
            operation=short_name,
        )
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
    elif (
        isinstance(call.func, ast.Attribute)
        and call.func.attr in {"replace", "rename"}
        and _is_path_valued_expr(call.func.value, values, path, path_functions)
    ):
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
    elif name in {
        "shutil.copy",
        "shutil.copy2",
        "shutil.copyfile",
        "shutil.copytree",
        "shutil.move",
    }:
        _record_access(
            accesses,
            unresolved,
            action="read",
            expression=_call_argument(call, 0, "src"),
            call=call,
            values=values,
            path=path,
            repo_root=repo_root,
            path_functions=path_functions,
            family=context_family,
            operation=short_name,
        )
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
        short_name == "_load_json_object" and path == Path("shared/platform_capability_registry.py")
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
    elif _looks_like_file_api(name):
        # An unknown signature cannot tell us which argument is the path. Retain the first
        # modelled Path expression (or strongly path-shaped literal); a read-shaped callee keeps
        # that expression as an explicitly unmodelled read. Merely resolvable prose is not a file:
        # parser.add_argument("description"), for example, must not manufacture artifact reads.
        for argument in (*call.args, *(keyword.value for keyword in call.keywords)):
            patterns = _resolve_path_expr_variants(
                argument, values, path, repo_root, path_functions
            )
            if not _is_path_valued_expr(argument, values, path, path_functions) and not any(
                _looks_like_artifact_pattern(pattern) for pattern in patterns
            ):
                continue
            if _looks_like_file_reader(name):
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
                    operation=name,
                    modelled=False,
                )
            unrecognised[name] += 1
            break


# Callee -> (action, positional index of the path, keyword name). "mode" reads the mode argument
# the way open() does (zipfile.ZipFile / tarfile.open take it second).
FILE_BACKED_APIS: dict[str, tuple[str, int, str]] = {
    "sqlite3.connect": ("read", 0, "database"),
    "shelve.open": ("read", 0, "filename"),
    "dbm.open": ("read", 0, "file"),
    "zipfile.ZipFile": ("mode", 0, "file"),
    "tarfile.open": ("mode", 0, "name"),
}
_FILE_API_HINTS = (
    "open",
    "load",
    "read",
    "connect",
    "parse",
    "dump",
    "save",
    "write",
    "fetch",
    "import",
    "export",
    "pickle",
)
_FILE_READER_HINTS = frozenset(
    {"open", "load", "read", "connect", "parse", "fetch", "import", "pickle"}
)
_IN_MEMORY_APIS = frozenset(
    {
        "json.dump",
        "json.dumps",
        "json.load",
        "json.loads",
        "tomllib.load",
        "yaml.dump",
        "yaml.load",
        "yaml.safe_dump",
        "yaml.safe_load",
    }
)


def _looks_like_file_api(name: str) -> bool:
    lowered = name.lower()
    if lowered in {"str", "repr", "print", "path", "purepath", "pureposixpath", "len"}:
        return False
    if lowered in _IN_MEMORY_APIS or lowered.startswith(("argparse.", "importlib.")):
        return False
    short = lowered.rsplit(".", 1)[-1].strip("_")
    if short in {"dumps", "loads", "model_dump"}:
        return False
    tokens = {token for token in short.split("_") if token}
    return bool(tokens.intersection(_FILE_API_HINTS))


def _looks_like_file_reader(name: str) -> bool:
    short = name.lower().rsplit(".", 1)[-1].strip("_")
    tokens = {token for token in short.split("_") if token}
    return bool(tokens.intersection(_FILE_READER_HINTS))


def _statement_calls(statement: ast.stmt) -> list[ast.Call]:
    """Calls in a statement's own expressions — not in its nested statements or nested scopes."""
    visitor = _ScopeCallVisitor()
    for child in ast.iter_child_nodes(statement):
        if isinstance(child, (ast.stmt, ast.ExceptHandler, ast.match_case)):
            continue
        visitor.visit(child)
    return visitor.calls


def _statement_scopes(statement: ast.stmt) -> list[ast.AST]:
    """Deferred bodies defined by this statement, excluding bodies of nested statements."""
    scopes: list[ast.AST] = []

    class Visitor(ast.NodeVisitor):
        def visit_Lambda(self, node: ast.Lambda) -> None:
            scopes.append(node)

    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
        scopes.append(statement)
    visitor = Visitor()
    for child in ast.iter_child_nodes(statement):
        if not isinstance(child, (ast.stmt, ast.ExceptHandler, ast.match_case)):
            visitor.visit(child)
    return scopes


_POTENTIALLY_RAISING_EXPRESSIONS = (
    ast.Attribute,
    ast.Await,
    ast.BinOp,
    ast.Compare,
    ast.DictComp,
    ast.GeneratorExp,
    ast.ListComp,
    ast.SetComp,
    ast.Starred,
    ast.Subscript,
    ast.UnaryOp,
    ast.YieldFrom,
)


def _statement_may_raise(statement: ast.stmt) -> bool:
    """Whether the statement can transfer control to its enclosing exception handler.

    Only the statement's own expressions count here; nested statement bodies contribute their
    predecessor states while they are scanned.  The analysis is deliberately conservative, but
    constants, names, and ordinary binding statements do not invent an exception edge.
    """
    if isinstance(statement, (ast.Raise, ast.Assert, ast.Import, ast.ImportFrom)):
        return True
    if _statement_calls(statement):
        return True
    for child in ast.iter_child_nodes(statement):
        if isinstance(child, (ast.stmt, ast.ExceptHandler, ast.match_case)):
            continue
        if any(
            isinstance(descendant, _POTENTIALLY_RAISING_EXPRESSIONS)
            for descendant in ast.walk(child)
        ):
            return True
    return False


def _binding_keys(name: str) -> tuple[str, ...]:
    return (
        name,
        _path_value_key(name),
        _value_alternatives_key(name),
        f"{_IMPORT_ALIAS_PREFIX}{name}",
        f"{_UNRESOLVED_CLOSURE_PREFIX}{name}",
        f"{_CONSTANT_VALUE_PREFIX}{name}",
        f"{_UNRESOLVED_FORMAT_PREFIX}{name}",
    )


def _invalidate_names(values: dict[str, str], names: set[str]) -> None:
    for name in names:
        for key in _binding_keys(name):
            values.pop(key, None)
        values[name] = "*"
        _set_import_alias(values, name, None)


def _target_names(target: ast.AST) -> set[str]:
    # Attribute/subscript stores mutate an object we cannot model. Invalidate its base
    # and attribute fallback as well, rather than letting either supply obsolete evidence.
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, ast.Attribute):
        return _target_names(target.value) | {target.attr}
    if isinstance(target, (ast.Subscript, ast.Starred)):
        return _target_names(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        return set().union(*(_target_names(child) for child in target.elts))
    return set()


def _apply_assignment(
    statement: ast.Assign | ast.AnnAssign,
    values: dict[str, str],
    path: Path,
    repo_root: Path,
    path_functions: dict[str, PathFunction],
    *,
    strict_formatted: bool = False,
) -> list[dict[str, str]]:
    targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
    assigned = dict(values)
    for target in targets:
        if isinstance(target, (ast.Tuple, ast.List)):
            components = (
                statement.value.elts
                if isinstance(statement.value, (ast.Tuple, ast.List))
                and len(target.elts) == len(statement.value.elts)
                and not any(isinstance(item, ast.Starred) for item in target.elts)
                else [None] * len(target.elts)
            )
            for child, component in zip(target.elts, components, strict=True):
                child_state = _apply_assignment(
                    ast.Assign(targets=[child], value=component),
                    values,
                    path,
                    repo_root,
                    path_functions,
                    strict_formatted=strict_formatted,
                )[0]
                # All RHS components use the incoming bindings (including swaps).
                for name in _target_names(child):
                    for key in _binding_keys(name):
                        assigned.pop(key, None)
                        if key in child_state:
                            assigned[key] = child_state[key]
        elif not isinstance(target, ast.Name):
            # Starred, Attribute and Subscript are the remaining concrete Store forms;
            # conservatively cover any future/unmodelled target too.
            _invalidate_names(assigned, _target_names(target))
    if strict_formatted and _has_unbounded_format(
        statement.value, values, path, repo_root, path_functions
    ):
        # Container components have already been bound individually above. An unknown
        # iteration element cannot make a wildcard writer or erase a known sibling.
        statement = ast.Assign(targets=targets, value=None)
    is_path = (
        isinstance(statement, ast.AnnAssign) and _is_path_annotation(statement.annotation)
    ) or _is_path_valued_expr(statement.value, assigned, path, path_functions)
    resolved_values: set[str | None] = set()
    for expression in _path_expressions(statement.value, path, path_functions):
        tentative = _resolve_path_expr(expression, values, path, repo_root, path_functions)
        abstract_names = {
            item.id
            for item in ast.walk(expression)
            if isinstance(item, ast.Name) and _value_alternatives(values, item.id) is not None
        }
        if abstract_names and (
            len(abstract_names) == 1 or is_path or _looks_like_artifact_pattern(tentative)
        ):
            resolved_values.update(
                _resolve_path_expr(expression, state, path, repo_root, path_functions)
                for state in _expand_value_alternative_states(expression, values)
            )
        else:
            resolved_values.add(tentative)
    if not resolved_values:
        resolved_values.add(None)
    for target in targets:
        if not isinstance(target, ast.Name):
            continue
        # A name rebound to something this scanner cannot resolve stops meaning its old path
        # (the old fixpoint kept the old value and resolved every later read through it).
        resolved = next(iter(resolved_values)) if len(resolved_values) == 1 else None
        assigned[target.id] = resolved if resolved is not None else "*"
        constant_key = f"{_CONSTANT_VALUE_PREFIX}{target.id}"
        assigned.pop(constant_key, None)
        known, constant = _constant_value(statement.value, values)
        if known:
            assigned[constant_key] = json.dumps(constant)
        format_key = f"{_UNRESOLVED_FORMAT_PREFIX}{target.id}"
        assigned.pop(format_key, None)
        if _has_unbounded_format(statement.value, values, path, repo_root, path_functions):
            assigned[format_key] = "1"
        _set_path_value(assigned, target.id, is_path)
        _set_import_alias(assigned, target.id, None)
        _clear_value_alternatives(assigned, target.id)
        closure_origins = (
            {
                values[f"{_UNRESOLVED_CLOSURE_PREFIX}{item.id}"]
                for item in ast.walk(statement.value)
                if isinstance(item, ast.Name) and f"{_UNRESOLVED_CLOSURE_PREFIX}{item.id}" in values
            }
            if statement.value is not None
            else set()
        )
        closure_key = f"{_UNRESOLVED_CLOSURE_PREFIX}{target.id}"
        assigned.pop(closure_key, None)
        if closure_origins:
            assigned[closure_key] = "|".join(sorted(closure_origins))
        if len(resolved_values) > 1:
            _set_value_alternatives(assigned, target.id, resolved_values)
    return [assigned]


def _scope_local_names(node: ast.AST) -> set[str]:
    """Python local bindings shadow outer names throughout the function, even before a store."""
    local: set[str] = set()
    outer: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def visit_Name(self, item: ast.Name) -> None:
            if isinstance(item.ctx, (ast.Store, ast.Del)):
                local.add(item.id)

        def visit_FunctionDef(self, item: ast.FunctionDef) -> None:
            local.add(item.name)

        visit_AsyncFunctionDef = visit_FunctionDef
        visit_ClassDef = visit_FunctionDef

        def visit_Lambda(self, item: ast.Lambda) -> None:
            return

        def visit_Import(self, item: ast.Import) -> None:
            local.update(alias.asname or alias.name.split(".")[0] for alias in item.names)

        def visit_ImportFrom(self, item: ast.ImportFrom) -> None:
            local.update(alias.asname or alias.name for alias in item.names)

        def visit_Global(self, item: ast.Global) -> None:
            outer.update(item.names)

        visit_Nonlocal = visit_Global

        def visit_ExceptHandler(self, item: ast.ExceptHandler) -> None:
            if item.name:
                local.add(item.name)
            self.generic_visit(item)

        # Comprehension targets live in their own scope.
        visit_ListComp = visit_Lambda
        visit_SetComp = visit_Lambda
        visit_DictComp = visit_Lambda
        visit_GeneratorExp = visit_Lambda

    visitor = Visitor()
    if isinstance(node, ast.Lambda):
        visitor.visit(node.body)
    else:
        for statement in node.body:
            visitor.visit(statement)
    return local - outer


def _scope_initial_values(
    node: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
    module_values: dict[str, str],
    path: Path,
    repo_root: Path,
    path_functions: dict[str, PathFunction],
    lexical_prefixes: tuple[str, ...],
) -> dict[str, str]:
    if isinstance(node, ast.Module):
        # Module scope executes top to bottom: a read before an assignment sees nothing.
        return {}
    values = dict(module_values)
    _set_lexical_scope(values, lexical_prefixes)
    for name in _scope_local_names(node):
        values.pop(f"{_UNRESOLVED_FORMAT_PREFIX}{name}", None)
        values.pop(f"{_CONSTANT_VALUE_PREFIX}{name}", None)
        values.pop(f"{_UNRESOLVED_CLOSURE_PREFIX}{name}", None)
        values[name] = "*"
        _set_path_value(values, name, False)
        _set_import_alias(values, name, None)
        _clear_value_alternatives(values, name)
    parameters = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    if node.args.vararg is not None:
        parameters.append(node.args.vararg)
    if node.args.kwarg is not None:
        parameters.append(node.args.kwarg)
    for arg in parameters:
        values.pop(f"{_UNRESOLVED_FORMAT_PREFIX}{arg.arg}", None)
        values.pop(f"{_CONSTANT_VALUE_PREFIX}{arg.arg}", None)
        values.pop(f"{_UNRESOLVED_CLOSURE_PREFIX}{arg.arg}", None)
        values[arg.arg] = "*"
        _set_path_value(values, arg.arg, _is_path_annotation(arg.annotation))
        # Parameters are bindings in the function's lexical scope.  A module import with the
        # same name is no longer the callee used by calls in this scope.
        _set_import_alias(values, arg.arg, None)
        _clear_value_alternatives(values, arg.arg)
    # Defaults are parameter bindings evaluated in the defining scope, before its later
    # stores and before the callee's locals/parameters shadow names. Missing snapshots
    # cannot borrow a value from initialized globals.
    if isinstance(path_functions, PathFunctionTable):
        values.update(path_functions.definition_defaults.get(node, {}))
    return values


def _closure_rebound_names(enclosing: ast.AST, closure: ast.AST) -> set[str]:
    """Cells whose invocation-time value cannot be bounded by a definition snapshot.

    We do not model callback escape or call scheduling. A later store (including a loop
    back-edge or a nonlocal store in another callback) therefore invalidates a captured
    value. Stable captures and definition-time defaults keep their existing evidence.
    """
    local = _scope_local_names(closure)
    arguments = closure.args
    local.update(
        arg.arg for arg in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
    )
    local.update(arg.arg for arg in (arguments.vararg, arguments.kwarg) if arg is not None)
    body = [closure.body] if isinstance(closure, ast.Lambda) else closure.body
    referenced = {
        item.id
        for statement in body
        for item in ast.walk(statement)
        if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)
    } - local
    start = (closure.lineno, closure.col_offset)
    # Stores textually before a definition inside a loop can execute after it on the next
    # iteration. Treat the entire containing loop as a possible rebinding region.
    for item in ast.walk(enclosing):
        if isinstance(item, (ast.For, ast.AsyncFor, ast.While)) and closure in ast.walk(item):
            start = min(start, (item.lineno, item.col_offset))
    rebound: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def bind(self, item: ast.AST, names: set[str]) -> None:
            if (item.lineno, item.col_offset) >= start:
                rebound.update(names)

        def visit_Name(self, item: ast.Name) -> None:
            if isinstance(item.ctx, (ast.Store, ast.Del)):
                self.bind(item, {item.id})

        def visit_FunctionDef(self, item: ast.FunctionDef) -> None:
            self.bind(item, {item.name})
            # Nested locals do not rebind enclosing cells; explicit nonlocal declarations
            # may, and scheduling these callbacks is outside this scanner's model.
            for child in ast.walk(item):
                if isinstance(child, ast.Nonlocal):
                    rebound.update(child.names)

        visit_AsyncFunctionDef = visit_FunctionDef
        visit_ClassDef = visit_FunctionDef

        def visit_Lambda(self, item: ast.Lambda) -> None:
            return

        def visit_Import(self, item: ast.Import) -> None:
            self.bind(item, {alias.asname or alias.name.split(".")[0] for alias in item.names})

        def visit_ImportFrom(self, item: ast.ImportFrom) -> None:
            self.bind(item, {alias.asname or alias.name for alias in item.names})

        def visit_ExceptHandler(self, item: ast.ExceptHandler) -> None:
            if item.name:
                self.bind(item, {item.name})
            self.generic_visit(item)

        def visit_MatchAs(self, item: ast.MatchAs) -> None:
            if item.name:
                self.bind(item, {item.name})
            self.generic_visit(item)

        visit_MatchStar = visit_MatchAs

        def visit_MatchMapping(self, item: ast.MatchMapping) -> None:
            if item.rest:
                self.bind(item, {item.rest})
            self.generic_visit(item)

    visitor = Visitor()
    enclosing_body = [enclosing.body] if isinstance(enclosing, ast.Lambda) else enclosing.body
    for statement in enclosing_body:
        visitor.visit(statement)
    return referenced & rebound


_MAX_BRANCH_STATES = 8


def _fork(states: list[dict[str, str]]) -> list[dict[str, str]]:
    return [dict(state) for state in states]


def _merge_states(states: list[dict[str, str]], *, collapse: bool = False) -> list[dict[str, str]]:
    """Deduplicate branch maps, joining excess maps without losing known values.

    Once the disjunctive-state cap is reached, each user binding keeps the union of its concrete
    alternatives as metadata.  A later expression expands just the alternatives it references.
    This bounds intermediate cross-products without deleting a statically known read pattern.
    """
    exits = {state.get(_FLOW_EXIT_KEY) for state in states}
    if len(exits) > 1:
        return [
            merged
            for reason in sorted(exits, key=lambda item: item or "")
            for merged in _merge_states(
                [state for state in states if state.get(_FLOW_EXIT_KEY) == reason],
                collapse=collapse,
            )
        ]
    distinct: dict[tuple[tuple[str, str], ...], dict[str, str]] = {}
    for state in states:
        distinct.setdefault(tuple(sorted(state.items())), state)
    merged = list(distinct.values())
    if len(merged) <= _MAX_BRANCH_STATES and not collapse:
        return merged

    internal_names = {
        name
        for state in merged
        for name in state
        if name.startswith("\0") and not name.startswith(_VALUE_ALTERNATIVES_PREFIX)
    }
    collapsed: dict[str, str] = {}
    for name in internal_names:
        alternatives = {state.get(name) for state in merged}
        if name == _HELPER_EFFECT_KEY and "1" in alternatives:
            collapsed[name] = "1"
            continue
        if name.startswith(_UNRESOLVED_FORMAT_PREFIX) and "1" in alternatives:
            collapsed[name] = "1"
            continue
        if name.startswith(_IMPORT_ALIAS_PREFIX) and len(alternatives) > 1:
            collapsed[name] = ""
            continue
        if len(alternatives) == 1 and None not in alternatives:
            value = alternatives.pop()
            assert value is not None
            collapsed[name] = value

    user_names = {name for state in merged for name in state if not name.startswith("\0")}
    user_names.update(
        name.removeprefix(_VALUE_ALTERNATIVES_PREFIX)
        for state in merged
        for name in state
        if name.startswith(_VALUE_ALTERNATIVES_PREFIX)
    )
    for name in user_names:
        alternatives: set[str | None] = set()
        for state in merged:
            abstract = _value_alternatives(state, name)
            alternatives.update(abstract if abstract is not None else (state.get(name),))
        if len(alternatives) == 1 and None not in alternatives:
            value = alternatives.pop()
            assert value is not None
            collapsed[name] = value
        else:
            collapsed[name] = "*"
            _set_value_alternatives(collapsed, name, alternatives)
    return [collapsed]


class _BlockScanner:
    """Walk one lexical scope in source order, carrying every branch's value map separately.

    Mutually exclusive branches used to be flattened into one shared value map, so a read after
    an if/else saw only the else branch's assignment (review finding on #4626, round 6). Each
    branch now forks the states it entered with and the states are merged after the statement, so
    a read below sees every value the name can hold. A call is classified once per state; an
    access is recorded for each distinct pattern, and each unresolved access slot is counted even
    when another branch or argument resolves.
    """

    def __init__(
        self,
        *,
        path: Path,
        repo_root: Path,
        path_functions: dict[str, PathFunction],
        accesses: list[ArtifactAccess],
        unresolved: list[int],
        unrecognised: Counter[str],
        context_family: str,
        nested_scope_values: dict[ast.AST, list[dict[str, str]]],
    ) -> None:
        self.path = path
        self.repo_root = repo_root
        self.path_functions = path_functions
        self.accesses = accesses
        self.unresolved = unresolved
        self.unrecognised = unrecognised
        self.context_family = context_family
        self.nested_scope_values = nested_scope_values

    def scan_block(
        self,
        statements: list[ast.stmt],
        states: list[dict[str, str]],
        exception_states: list[dict[str, str]] | None = None,
        exit_states: list[dict[str, str]] | None = None,
    ) -> list[dict[str, str]]:
        for statement in statements:
            if not states:
                break
            states = self._scan_statement(statement, states, exception_states, exit_states)
        return states

    def _classify(self, call: ast.Call, states: list[dict[str, str]]) -> None:
        call_accesses: list[ArtifactAccess] = []
        unresolved_slots = 0
        flagged: set[str] = set()
        for state in states:
            if isinstance(self.path_functions, PathFunctionTable):
                function = self.path_functions.resolve(
                    _function_name(call), self.path, _lexical_scope(state), _import_aliases(state)
                )
                if function is not None and function.node is not None:
                    self.path_functions.call_bindings.setdefault(function.node, []).append(
                        _call_parameter_values(
                            function, call, state, self.path, self.repo_root, self.path_functions
                        )
                    )
            local_unresolved = [0]
            local_unrecognised: Counter[str] = Counter()
            _classify_call(
                call,
                state,
                self.path,
                self.repo_root,
                self.path_functions,
                call_accesses,
                local_unresolved,
                local_unrecognised,
                self.context_family,
            )
            unresolved_slots = max(unresolved_slots, local_unresolved[0])
            flagged.update(local_unrecognised)
        self.accesses.extend(dict.fromkeys(call_accesses))
        self.unresolved[0] += unresolved_slots
        for name in flagged:
            self.unrecognised[name] += 1

    def _bind_loop_target(
        self, target: ast.expr, value: ast.expr | None, state: dict[str, str]
    ) -> dict[str, str]:
        self._scan_target(target, [state])
        return _apply_assignment(
            ast.Assign(targets=[target], value=value),
            state,
            self.path,
            self.repo_root,
            self.path_functions,
            strict_formatted=True,
        )[0]

    def _loop_body_states(
        self, statement: ast.For | ast.AsyncFor, states: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        iterations = (
            statement.iter.elts
            if isinstance(statement.iter, (ast.List, ast.Tuple, ast.Set))
            else [None]
        )
        return _merge_states(
            [
                self._bind_loop_target(statement.target, value, dict(state))
                for state in states
                for value in iterations
            ]
        )

    def _bind(self, target: ast.expr, value: ast.expr | None, states: list[dict[str, str]]) -> None:
        for state in states:
            assigned = _apply_assignment(
                ast.Assign(targets=[target], value=value),
                state,
                self.path,
                self.repo_root,
                self.path_functions,
            )[0]
            state.clear()
            state.update(assigned)

    def _scan_target(self, target: ast.AST, states: list[dict[str, str]]) -> None:
        """Evaluate a store's receiver/index without treating its names as stores yet."""
        if isinstance(target, (ast.Tuple, ast.List)):
            for child in target.elts:
                self._scan_target(child, states)
        elif isinstance(target, ast.Starred):
            self._scan_target(target.value, states)
        elif isinstance(target, (ast.Attribute, ast.Subscript)):
            self._scan_expression(target.value, states)
            if isinstance(target, ast.Subscript):
                self._scan_expression(target.slice, states)

    def _store_target(
        self, target: ast.expr, bound: dict[str, str], states: list[dict[str, str]]
    ) -> None:
        # RHS bindings were computed before any target executes. Stores themselves run
        # left to right, so a later receiver/index sees earlier stores (including unpacking).
        if isinstance(target, (ast.Tuple, ast.List)):
            for child in target.elts:
                self._store_target(child, bound, states)
            return
        self._scan_target(target, states)
        for state in states:
            for name in _target_names(target):
                for key in _binding_keys(name):
                    state.pop(key, None)
                    if key in bound:
                        state[key] = bound[key]

    def _scan_defaults(
        self,
        scope: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
        states: list[dict[str, str]],
    ) -> None:
        snapshots: list[dict[str, str]] = []
        for state in states:
            current = [dict(state)]
            defaults: dict[str, str] = {}
            for name, expression in _function_defaults(scope).items():
                self._scan_expression(expression, current)
                alternatives = []
                for predecessor in current:
                    bound = _apply_assignment(
                        ast.Assign(targets=[ast.Name(id=name)], value=expression),
                        predecessor,
                        self.path,
                        self.repo_root,
                        self.path_functions,
                    )[0]
                    alternatives.append(
                        {key: bound[key] for key in _binding_keys(name) if key in bound}
                    )
                defaults.update(_merge_states(alternatives, collapse=True)[0])
            snapshots.append(defaults)
            state.clear()
            state.update(_merge_states(current, collapse=True)[0])
        if isinstance(self.path_functions, PathFunctionTable):
            self.path_functions.definition_defaults[scope] = _merge_states(
                snapshots, collapse=True
            )[0]
            self.path_functions.helper_results.clear()

    def _scan_expression(self, node: ast.AST, states: list[dict[str, str]]) -> None:
        if isinstance(node, ast.Lambda):
            self._scan_defaults(node, states)
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return
        if isinstance(node, ast.NamedExpr):
            self._scan_expression(node.value, states)
            self._bind(node.target, node.value, states)
            return
        if isinstance(node, ast.IfExp):
            self._scan_expression(node.test, states)
            taken, not_taken = _fork(states), _fork(states)
            self._scan_expression(node.body, taken)
            self._scan_expression(node.orelse, not_taken)
            states[:] = _merge_states(taken + not_taken)
            return
        if isinstance(node, ast.BoolOp):
            continued = _fork(states)
            alternatives = []
            for value in node.values:
                self._scan_expression(value, continued)
                alternatives.extend(_fork(continued))
            states[:] = _merge_states(alternatives)
            return
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            inner = _fork(states)
            for generator in node.generators:
                self._scan_expression(generator.iter, inner)
                self._bind(generator.target, None, inner)
                for condition in generator.ifs:
                    self._scan_expression(condition, inner)
            for value in (node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,):
                self._scan_expression(value, inner)
            # Do not export comprehension values. We also refuse to use a pre-comprehension
            # snapshot for these targets outside it; deferred iteration is not scheduled here.
            names = set().union(*(_target_names(g.target) for g in node.generators))
            names.update(
                item.target.id for item in ast.walk(node) if isinstance(item, ast.NamedExpr)
            )
            for state in states:
                _invalidate_names(state, names)
            return
        if isinstance(getattr(node, "ctx", None), (ast.Store, ast.Del)):
            # Fallback for every Store form not owned by a statement handler below.
            self._scan_target(node, states)
            for state in states:
                _invalidate_names(state, _target_names(node))
            return
        for child in ast.iter_child_nodes(node):
            self._scan_expression(child, states)
        if isinstance(node, ast.Call):
            self._classify(node, states)

    def _scan_statement(
        self,
        statement: ast.stmt,
        states: list[dict[str, str]],
        exception_states: list[dict[str, str]] | None = None,
        exit_states: list[dict[str, str]] | None = None,
    ) -> list[dict[str, str]]:
        if exception_states is not None and _statement_may_raise(statement):
            # An assignment's right-hand side runs before its target is rebound.  Handlers see
            # the state entering the raising statement, never its normal post-state.
            exception_states.extend(_fork(states))
        # Targets are processed after their RHS, and with-items bind in entry order.
        owned_targets = set()
        if isinstance(statement, (ast.Assign, ast.Delete)):
            owned_targets.update(statement.targets)
        elif isinstance(statement, (ast.AnnAssign, ast.AugAssign, ast.For, ast.AsyncFor)):
            owned_targets.add(statement.target)
        if isinstance(statement, ast.AugAssign):
            # Augmented assignment evaluates its target before the RHS, exactly once.
            self._scan_target(statement.target, states)
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in statement.decorator_list:
                self._scan_expression(decorator, states)
            self._scan_defaults(statement, states)
            for argument in ast.walk(statement.args):
                if isinstance(argument, ast.arg) and argument.annotation is not None:
                    self._scan_expression(argument.annotation, states)
            if statement.returns is not None:
                self._scan_expression(statement.returns, states)
        elif not isinstance(statement, (ast.With, ast.AsyncWith)):
            for child in ast.iter_child_nodes(statement):
                if child not in owned_targets and not isinstance(
                    child, (ast.stmt, ast.ExceptHandler, ast.match_case)
                ):
                    self._scan_expression(child, states)
        for scope in _statement_scopes(statement):
            self.nested_scope_values.setdefault(scope, []).extend(_fork(states))
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if isinstance(statement, ast.ClassDef):
                # Bases and decorators above run in the enclosing scope.  A class body also runs
                # immediately, but its bindings live in a fresh namespace and cannot continue
                # into the enclosing block.
                class_exceptions: list[dict[str, str]] = []
                class_exits: list[dict[str, str]] = []
                self.scan_block(
                    statement.body,
                    _fork(states),
                    class_exceptions,
                    class_exits,
                )
                if exception_states is not None and (class_exceptions or class_exits):
                    exception_states.extend(_fork(states))
            for state in states:
                _invalidate_names(state, {statement.name})
                prefix = next(iter(_lexical_scope(state)), "")
                target = ".".join(filter(None, (_module_name(self.path), prefix, statement.name)))
                _set_import_alias(
                    state,
                    statement.name,
                    target
                    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
                    else None,
                )
            return states
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            bindings = _import_bindings(
                [statement],
                _module_name(self.path),
                is_package=self.path.name == "__init__.py",
            )
            imported = _fork(states)
            for state in imported:
                for name, target in bindings.items():
                    _invalidate_names(state, {name})
                    _set_import_alias(state, name, target)
            return imported
        if isinstance(statement, ast.AugAssign):
            # Only the path operations understood by _resolve_path_expr can resolve this.
            expression = ast.copy_location(
                ast.BinOp(left=statement.target, op=statement.op, right=statement.value), statement
            )
            self._bind(statement.target, expression, states)
            return states
        if isinstance(statement, ast.Delete):
            for target in statement.targets:
                self._scan_target(target, states)
                self._bind(target, None, states)
            return states
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            assigned: list[dict[str, str]] = []
            for state in states:
                targets = (
                    statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                )
                # Freeze the RHS separately for each target before stores can rebind it.
                bindings = [
                    _apply_assignment(
                        ast.Assign(targets=[target], value=statement.value)
                        if isinstance(statement, ast.Assign)
                        else statement,
                        state,
                        self.path,
                        self.repo_root,
                        self.path_functions,
                    )[0]
                    for target in targets
                ]
                stored = [dict(state)]
                for target, bound in zip(targets, bindings, strict=True):
                    self._store_target(target, bound, stored)
                assigned.extend(stored)
            return _merge_states(assigned)
        if isinstance(statement, ast.If):
            taken = self.scan_block(statement.body, _fork(states), exception_states, exit_states)
            not_taken = (
                self.scan_block(statement.orelse, _fork(states), exception_states, exit_states)
                if statement.orelse
                else _fork(states)
            )
            return _merge_states(taken + not_taken)
        if isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
            body_states = (
                self._loop_body_states(statement, states)
                if isinstance(statement, (ast.For, ast.AsyncFor))
                else _fork(states)
            )
            loop_exits: list[dict[str, str]] = []
            looped = self.scan_block(statement.body, body_states, exception_states, loop_exits)
            broken: list[dict[str, str]] = []
            for state in loop_exits:
                reason = state.get(_FLOW_EXIT_KEY)
                if reason in {"Break", "Continue"}:
                    state.pop(_FLOW_EXIT_KEY)
                    (broken if reason == "Break" else looped).append(state)
                elif exit_states is not None:
                    exit_states.append(state)
            after = _merge_states(_fork(states) + looped)
            exhausted = (
                self.scan_block(statement.orelse, after, exception_states, exit_states)
                if statement.orelse
                else after
            )
            return _merge_states(exhausted + broken)
        if isinstance(statement, (ast.With, ast.AsyncWith)):
            for item in statement.items:
                self._scan_expression(item.context_expr, states)
                if item.optional_vars is not None:
                    self._scan_target(item.optional_vars, states)
                    for state in states:
                        expression = item.context_expr
                        name = (
                            self.path_functions.canonical_name(
                                _function_name(expression),
                                self.path,
                                _lexical_scope(state),
                                _import_aliases(state),
                            )
                            if isinstance(expression, ast.Call)
                            and isinstance(self.path_functions, PathFunctionTable)
                            else _function_name(expression)
                            if isinstance(expression, ast.Call)
                            else ""
                        )
                        self._bind(
                            item.optional_vars,
                            expression if name in _PATH_CONSTRUCTORS else None,
                            [state],
                        )
            return self.scan_block(statement.body, states, exception_states, exit_states)
        if isinstance(statement, (ast.Try, getattr(ast, "TryStar", ast.Try))):
            body_exception_states: list[dict[str, str]] = []
            body_exit_states: list[dict[str, str]] = []
            body_states = self.scan_block(
                statement.body,
                _fork(states),
                body_exception_states,
                body_exit_states,
            )
            if exception_states is not None:
                # A typed inner handler may not catch every exception its body can raise.
                exception_states.extend(_fork(body_exception_states))
            handler_inputs = _merge_states(body_exception_states)
            handler_states: list[dict[str, str]] = []
            handler_exit_states: list[dict[str, str]] = []
            for handler in statement.handlers:
                inputs = _fork(handler_inputs)
                if handler.name:
                    for state in inputs:
                        _invalidate_names(state, {handler.name})
                completed = self.scan_block(
                    handler.body,
                    inputs,
                    exception_states,
                    handler_exit_states,
                )
                if handler.name:
                    for state in completed:
                        _invalidate_names(state, {handler.name})
                handler_states += completed
            else_exit_states: list[dict[str, str]] = []
            else_states = (
                self.scan_block(
                    statement.orelse,
                    body_states,
                    exception_states,
                    else_exit_states,
                )
                if statement.orelse
                else body_states
            )
            merged = _merge_states(else_states + handler_states)
            abrupt = _merge_states(body_exit_states + handler_exit_states + else_exit_states)
            if not statement.finalbody:
                if exit_states is not None:
                    exit_states.extend(abrupt)
                return merged

            continued = self.scan_block(
                statement.finalbody,
                merged,
                exception_states,
                exit_states,
            )
            # ``finally`` runs on returns and raises as well.  Scan those states for accesses,
            # but never turn their completion into normal continuation after the try statement.
            final_exit_states: list[dict[str, str]] = []
            abrupt_after_finally = self.scan_block(
                statement.finalbody,
                abrupt,
                exception_states,
                final_exit_states,
            )
            if exit_states is not None:
                exit_states.extend(abrupt_after_finally)
                exit_states.extend(final_exit_states)
            return continued
        if isinstance(statement, ast.Match):
            case_states: list[dict[str, str]] = []
            for case in statement.cases:
                inputs = _fork(states)
                names = {
                    item.name
                    for item in ast.walk(case.pattern)
                    if isinstance(item, (ast.MatchAs, ast.MatchStar)) and item.name
                } | {
                    item.rest
                    for item in ast.walk(case.pattern)
                    if isinstance(item, ast.MatchMapping) and item.rest
                }
                for state in inputs:
                    _invalidate_names(state, names)
                if case.guard is not None:
                    self._scan_expression(case.guard, inputs)
                case_states += self.scan_block(case.body, inputs, exception_states, exit_states)
            exhaustive = any(
                isinstance(case.pattern, ast.MatchAs)
                and case.pattern.pattern is None
                and case.guard is None
                for case in statement.cases
            )
            return _merge_states(case_states + ([] if exhaustive else _fork(states)))
        if isinstance(statement, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
            if exit_states is not None:
                exit_states.extend(
                    {**state, _FLOW_EXIT_KEY: type(statement).__name__} for state in states
                )
            return []
        return states


class _ModuleBindingScanner(_BlockScanner):
    """Compute post-flow globals without publishing duplicate prepass diagnostics."""

    def _classify(self, call: ast.Call, states: list[dict[str, str]]) -> None:
        return


class _PathHelperScanner(_BlockScanner):
    """Evaluate return bindings using the same control flow as artifact access scanning.

    Helpers expose one scalar path to the expression resolver. Ambiguous returns and effects
    we cannot bound therefore remain unresolved, rather than selecting one branch's producer.
    Calls are inspected for effects here; accesses are counted by the ordinary scope scan.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.return_values: set[str | None] = set()

    def _classify(self, call: ast.Call, states: list[dict[str, str]]) -> None:
        for state in states:
            if _HELPER_EFFECT_KEY in state:
                continue
            resolved = _resolve_path_expr(
                call, state, self.path, self.repo_root, self.path_functions
            )
            if resolved is None:
                state[_HELPER_EFFECT_KEY] = "1"
            if isinstance(self.path_functions, PathFunctionTable):
                function = self.path_functions.resolve(
                    _function_name(call), self.path, _lexical_scope(state), _import_aliases(state)
                )
                if (
                    function
                    and function.node
                    and any(
                        isinstance(item, (ast.Global, ast.Nonlocal))
                        for item in ast.walk(function.node)
                    )
                ):
                    state[_HELPER_EFFECT_KEY] = "1"

    def _scan_statement(
        self,
        statement: ast.stmt,
        states: list[dict[str, str]],
        exception_states: list[dict[str, str]] | None = None,
        exit_states: list[dict[str, str]] | None = None,
    ) -> list[dict[str, str]]:
        # Effects can happen before a call raises or returns. Mark them before the shared
        # walker captures exception predecessors and before evaluating a return expression.
        for call in _statement_calls(statement):
            self._classify(call, states)
        if isinstance(statement, ast.Return):
            for state in states:
                if _HELPER_EFFECT_KEY in state:
                    self.return_values.add(None)
                else:
                    self.return_values.update(
                        _resolve_path_expr_variants(
                            statement.value, state, self.path, self.repo_root, self.path_functions
                        )
                    )
        return super()._scan_statement(statement, states, exception_states, exit_states)


def _scan_scope(
    node: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
    module_values: dict[str, str],
    path: Path,
    repo_root: Path,
    path_functions: dict[str, PathFunction],
    accesses: list[ArtifactAccess],
    unresolved: list[int],
    unrecognised: Counter[str],
    lexical_prefixes: tuple[str, ...] = (),
    nested_scope_values: dict[ast.AST, list[dict[str, str]]] | None = None,
    closure_rebindings: set[str] | None = None,
    parameter_values: dict[str, str] | None = None,
) -> None:
    initial = _scope_initial_values(
        node, module_values, path, repo_root, path_functions, lexical_prefixes
    )
    supplied = parameter_values or {}
    _invalidate_names(initial, {name for name in supplied if not name.startswith("\0")})
    initial.update(supplied)
    for name in closure_rebindings or ():
        initial.pop(f"{_CONSTANT_VALUE_PREFIX}{name}", None)
        initial.pop(f"{_UNRESOLVED_FORMAT_PREFIX}{name}", None)
        initial.pop(name, None)
        _clear_value_alternatives(initial, name)
        _set_path_value(initial, name, False)
        _set_import_alias(initial, name, None)
        site = f"{path}:{node.lineno}: closure binding {name} may change after definition"
        initial[f"{_UNRESOLVED_CLOSURE_PREFIX}{name}"] = site
        if isinstance(path_functions, PathFunctionTable):
            path_functions.unresolved_closures.add(site)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        context = node.name
    elif isinstance(node, ast.Lambda):
        context = "lambda"
    else:
        context = path.stem
    # Source order is the semantics: a read sees the assignments above it, never one below
    # (review finding on #4626, round 5), and every branch above it, not just the last one
    # (round 6) — see _BlockScanner.
    scanner = _BlockScanner(
        path=path,
        repo_root=repo_root,
        path_functions=path_functions,
        accesses=accesses,
        unresolved=unresolved,
        unrecognised=unrecognised,
        context_family=_artifact_family(context),
        nested_scope_values=nested_scope_values if nested_scope_values is not None else {},
    )
    if isinstance(node, ast.Lambda):
        scanner._scan_expression(node.body, [initial])
    else:
        scanner.scan_block(list(node.body), [initial])


def _iter_function_scopes(
    tree: ast.Module,
) -> list[LexicalScope]:
    """Lexical scopes with stable qualified names; no nested helper can replace a top-level one."""

    class _LexicalScopeVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.prefix: list[str] = []
            self.function_prefixes: list[str] = []
            self.scopes: list[LexicalScope] = []

        def _visit_named(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
            qualname = ".".join((*self.prefix, node.name))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lexical_prefixes = (qualname, *reversed(self.function_prefixes))
                self.scopes.append(LexicalScope(qualname, node, lexical_prefixes))
                self.function_prefixes.append(qualname)
            self.prefix.append(node.name)
            self.generic_visit(node)
            self.prefix.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.function_prefixes.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_named(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_named(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._visit_named(node)

        def visit_Lambda(self, node: ast.Lambda) -> None:
            label = f"<lambda>@{node.lineno}:{node.col_offset}"
            qualname = ".".join((*self.prefix, label))
            lexical_prefixes = (qualname, *reversed(self.function_prefixes))
            self.scopes.append(LexicalScope(qualname, node, lexical_prefixes))
            self.function_prefixes.append(qualname)
            self.prefix.append(label)
            self.generic_visit(node)
            self.prefix.pop()
            self.function_prefixes.pop()

    visitor = _LexicalScopeVisitor()
    visitor.visit(tree)
    return visitor.scopes


def _module_imports(
    tree: ast.Module, module_name: str = "", *, is_package: bool = False
) -> frozenset[str]:
    """Module names a file imports, as the importing module would resolve them.

    ``from .writer import write_widget`` in ``pkg/reader.py`` names ``pkg.writer``; ``from pkg
    import writer`` may name the submodule ``pkg.writer`` as well as ``pkg``. Both were recorded
    as the bare ``writer`` / ``pkg`` before, so a reader never paired with the producer it
    imported (review finding on #4626, round 5). Imported names are recorded as candidate
    submodules; an extra candidate never pairs with anything unless a module of that name exists.
    """
    imports: set[str] = set()
    parts = module_name.split(".") if module_name else []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                drop = node.level - 1 if is_package else node.level
                base = ".".join(parts[: max(len(parts) - drop, 0)])
            else:
                base = ""
            module = ".".join(part for part in (base, node.module or "") if part)
            if module:
                imports.add(module)
            for alias in node.names:
                if alias.name == "*":
                    continue
                candidate = ".".join(part for part in (module, alias.name) if part)
                if candidate:
                    imports.add(candidate)
    return frozenset(imports)


def _import_bindings(
    statements: list[ast.stmt], module_name: str = "", *, is_package: bool = False
) -> dict[str, str]:
    """Local import binding -> canonical dotted name for call provenance."""
    aliases: dict[str, str] = {}
    parts = module_name.split(".") if module_name else []
    for node in statements:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                target = alias.name if alias.asname else alias.name.split(".", 1)[0]
                aliases[local] = target
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                drop = node.level - 1 if is_package else node.level
                base = ".".join(parts[: max(len(parts) - drop, 0)])
            else:
                base = ""
            module = ".".join(part for part in (base, node.module or "") if part)
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                aliases[local] = ".".join(part for part in (module, alias.name) if part)
    return aliases


def _module_aliases(
    tree: ast.Module, module_name: str = "", *, is_package: bool = False
) -> dict[str, str]:
    """Top-level import bindings inherited by functions after module initialization."""
    aliases: dict[str, str] = {}
    for statement in tree.body:
        aliases.update(_import_bindings([statement], module_name, is_package=is_package))
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            aliases[statement.name] = f"{module_name}.{statement.name}"
        elif isinstance(statement, ast.ClassDef):
            aliases[statement.name] = ""
        elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    aliases[target.id] = ""
    return aliases


def collect_artifact_accesses(
    repo_root: Path,
    *,
    tests_only: bool = False,
    source_gaps: list[SourceGap] | None = None,
    capped_expressions: set[str] | None = None,
    unresolved_closures: set[str] | None = None,
    unresolved_paths: set[str] | None = None,
) -> tuple[list[ArtifactAccess], int, dict[Path, frozenset[str]], dict[str, int]]:
    parsed: list[tuple[Path, ast.Module]] = []
    for source_path in _iter_python_sources(
        repo_root, tests_only=tests_only, source_gaps=source_gaps
    ):
        relative = source_path.relative_to(repo_root)
        tree = _parse(_read(source_path, source_gaps, repo_root), relative, source_gaps)
        if tree is not None:
            parsed.append((relative, tree))

    path_functions = PathFunctionTable()
    imports_by_path = {
        relative: _module_imports(
            tree, _module_name(relative), is_package=relative.name == "__init__.py"
        )
        for relative, tree in parsed
    }
    path_functions.imports_by_path = imports_by_path
    path_functions.aliases_by_path = {
        relative: _module_aliases(
            tree, _module_name(relative), is_package=relative.name == "__init__.py"
        )
        for relative, tree in parsed
    }
    module_values_by_path: dict[Path, dict[str, str]] = {}
    for relative, tree in parsed:
        module_values_by_path[relative] = _module_values(tree, relative, repo_root, path_functions)
    for _ in range(2):
        for relative, tree in parsed:
            values = _module_values(tree, relative, repo_root, path_functions)
            module_values_by_path[relative] = values
            for scope in _iter_function_scopes(tree):
                node = scope.node
                if isinstance(node, ast.Lambda):
                    continue
                return_expr = _return_expression(node)
                params = tuple(
                    arg.arg
                    for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                )
                function_values = dict(values)
                _set_lexical_scope(function_values, scope.lexical_prefixes)
                path_functions.register(
                    relative,
                    scope.qualname,
                    PathFunction(
                        params,
                        return_expr,
                        function_values,
                        relative,
                        _is_path_valued_expr(
                            return_expr, function_values, relative, path_functions
                        ),
                        scope.lexical_prefixes,
                        node,
                    ),
                )

    accesses: list[ArtifactAccess] = []
    unresolved = [0]
    unrecognised: Counter[str] = Counter()
    for relative, tree in parsed:
        values = module_values_by_path[relative]
        nested_scope_values: dict[ast.AST, list[dict[str, str]]] = {}
        _scan_scope(
            tree,
            values,
            relative,
            repo_root,
            path_functions,
            accesses,
            unresolved,
            unrecognised,
            nested_scope_values=nested_scope_values,
        )
        enclosing_scopes: dict[str, LexicalScope] = {}
        for scope in _iter_function_scopes(tree):
            # Definition snapshots are usable only for cells that cannot subsequently change.
            # Module-level functions retain the initialized module map, as before.
            initial_states = (
                nested_scope_values.get(scope.node, [])
                if len(scope.lexical_prefixes) > 1
                else [values]
                if scope.node in nested_scope_values
                else []
            )
            rebindings = (
                _closure_rebound_names(enclosing_scopes[scope.lexical_prefixes[1]].node, scope.node)
                if len(scope.lexical_prefixes) > 1
                else set()
            )
            enclosing_scopes[scope.qualname] = scope
            for initial in _merge_states(initial_states):
                for supplied in _merge_states(path_functions.call_bindings.get(scope.node, [{}])):
                    _scan_scope(
                        scope.node,
                        initial,
                        relative,
                        repo_root,
                        path_functions,
                        accesses,
                        unresolved,
                        unrecognised,
                        scope.lexical_prefixes,
                        nested_scope_values,
                        rebindings,
                        supplied,
                    )
    unique = list(dict.fromkeys(accesses))
    if capped_expressions is not None:
        capped_expressions.update(path_functions.capped_expressions)
    if unresolved_closures is not None:
        unresolved_closures.update(path_functions.unresolved_closures)
    if unresolved_paths is not None:
        unresolved_paths.update(path_functions.unresolved_paths)
    return unique, unresolved[0], imports_by_path, dict(sorted(unrecognised.items()))


def _glob_has_artifact_identity(pattern: str) -> bool:
    parts = PurePosixPath(pattern).parts
    fixed_directory = any(
        "*" not in part and part not in {"/", "~", ".", ".."} for part in parts[:-1]
    )
    fixed_stem = PurePosixPath(pattern).stem.replace("*", "").strip("._-")
    return fixed_directory or bool(fixed_stem)


_REPORTED_GLOB_ERRORS: set[tuple[str, str]] = set()


def _report_glob_error(pattern: str, detail: str) -> None:
    issue = (pattern, detail)
    if issue in _REPORTED_GLOB_ERRORS:
        return
    _REPORTED_GLOB_ERRORS.add(issue)
    print(
        f"[REPORT-ERROR] glob pattern {pattern!r}: {detail}; treating it as a no-match; "
        "next action: correct or remove the bracket expression and rerun; "
        "the gate stays report-only"
    )


def _glob_class(pattern: str, start: int) -> tuple[str, int]:
    """Translate one shell-style bracket expression and return (regex, next index)."""
    close = start + 1
    if close < len(pattern) and pattern[close] == "!":
        close += 1
    if close < len(pattern) and pattern[close] == "]":
        close += 1
    while close < len(pattern) and pattern[close] != "]":
        close += 1
    if close >= len(pattern):
        return re.escape("["), start + 1

    fragment = pattern[start : close + 1]
    if "/" in fragment:
        _report_glob_error(pattern, f"character class {fragment!r} contains a path separator")
        return "(?!)", close + 1
    translated = fnmatch.translate(fragment)
    match = re.fullmatch(r"\(\?s:(.*)\)\\[zZ]", translated)
    if match is None:
        _report_glob_error(pattern, f"character class {fragment!r} could not be translated")
        return "(?!)", close + 1
    body = match.group(1)
    if body == "(?!)":
        _report_glob_error(pattern, f"character class {fragment!r} has no valid range")
    elif body == ".":
        body = "[^/]"
    elif body.startswith("[^"):
        # A negated glob class still cannot consume a directory separator.
        body = "[^/" + body[2:]
    return body, close + 1


def _glob_regex(pattern: str) -> re.Pattern[str]:
    """A glob as a regex whose `*` and `?` stop at `/` (only `**` crosses directories).

    fnmatch lets `*` match `/`, so `cache/*.json` matched `cache/sub/wanted.json`, a file that
    Path("cache").glob("*.json") can never read (review finding on #4626, round 6).
    """
    out: list[str] = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[":
            translated, i = _glob_class(pattern, i)
            out.append(translated)
            continue
        else:
            out.append(re.escape(char))
        i += 1
    expression = "^" + "".join(out) + "$"
    try:
        return re.compile(expression)
    except re.error as exc:
        _report_glob_error(pattern, f"translated regular expression is invalid ({exc})")
        return re.compile(r"(?!)")


def _glob_match(text: str, pattern: str) -> bool:
    return _glob_regex(pattern).match(text) is not None


def _patterns_match(left: str, right: str) -> bool:
    left = _normalise_pattern(left, Path.cwd())
    right = _normalise_pattern(right, Path.cwd())
    if left == right:
        return True
    for pattern in (left, right):
        # ``*/*.json`` means the path parameter was unresolved. It cannot prove
        # that a specific JSON consumer has a producer merely by sharing a suffix.
        if "*" in pattern and not _glob_has_artifact_identity(pattern):
            return False
    return _glob_match(left, right) or _glob_match(right, left)


def _accesses_match(left: ArtifactAccess, right: ArtifactAccess) -> bool:
    if left.glob_pattern is None and right.glob_pattern is None:
        return left.pattern == right.pattern
    for access in (left, right):
        if access.glob_pattern is not None and not _glob_has_artifact_identity(access.glob_pattern):
            return False
    if left.glob_pattern is None:
        return _glob_match(left.pattern, right.glob_pattern)
    if right.glob_pattern is None:
        return _glob_match(right.pattern, left.glob_pattern)
    return _patterns_match(left.glob_pattern, right.glob_pattern)


def _dedupe_findings(findings: list[ConsumerSideFinding]) -> list[ConsumerSideFinding]:
    """One finding per (kind, key); decayed-producer findings merge their reader sites.

    Decay analysis emitted one finding per reader x writer x member x relation, and identity-based
    deduplication kept them apart (review finding on #4626, round 6). Readers of one pattern are
    now a single finding whose reader_count is the number of distinct sites.
    """
    merged: dict[tuple[str, str], ConsumerSideFinding] = {}
    order: list[tuple[str, str]] = []
    for finding in findings:
        slot = (finding.kind, finding.key)
        prior = merged.get(slot)
        if prior is None:
            merged[slot] = finding
            order.append(slot)
            continue
        if finding.kind != "consumer-reads-decayed-producer":
            continue
        readers = tuple(dict.fromkeys((*prior.readers, *finding.readers)))
        writers = tuple(dict.fromkeys((*prior.writers, *finding.writers)))
        details = "; ".join(dict.fromkeys(part for part in (prior.detail, finding.detail) if part))
        merged[slot] = replace(
            prior, readers=readers, writers=writers, detail=details, reader_total=len(readers)
        )
    return [merged[slot] for slot in order]


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
        _glob_match(path, candidate)
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
        if _is_excluded(relative) or not candidate.is_file() or candidate.suffix == ".py":
            continue
        # Unit files declare an external process and are evidence about the
        # estate, not an implementation of the producer in this repository.
        if relative.parts[:1] == ("systemd",):
            continue
        if relative.parts[:1] == ("scripts",) or candidate.suffix in suffixes:
            output.append(candidate)
    return sorted(output)


def _documented_elsewhere_source_paths(repo_root: Path, tracked: frozenset[str]) -> list[Path]:
    config_suffixes = {".json", ".yaml", ".yml", ".toml"}
    candidates = (repo_root / item for item in tracked) if tracked else repo_root.rglob("*")
    output: list[Path] = []
    for candidate in candidates:
        try:
            relative = candidate.relative_to(repo_root)
        except ValueError:
            continue
        if _is_excluded(relative) or not candidate.is_file():
            continue
        is_runbook = relative.parts[:2] == ("docs", "runbooks") and candidate.suffix == ".md"
        is_config = relative.parts[:1] == ("config",) and candidate.suffix in config_suffixes
        is_systemd = relative.parts[:1] == ("systemd",)
        if is_runbook or is_config or is_systemd:
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


def _dynamic_root_basename(pattern: str) -> str | None:
    path = PurePosixPath(pattern)
    if not any("*" in part for part in path.parts[:-1]):
        return None
    basename = path.name
    fixed_stem = path.stem.replace("*", "").strip("._-")
    if "*" in basename and not fixed_stem:
        return None
    return basename


def _dynamic_root_writers(pattern: str, writes: list[ArtifactAccess]) -> list[ArtifactAccess]:
    basename = _dynamic_root_basename(pattern)
    if basename is None:
        return []
    return [
        writer
        for writer in writes
        if not any(marker in PurePosixPath(writer.pattern).name for marker in "*?[")
        and fnmatch.fnmatchcase(PurePosixPath(writer.pattern).name, basename)
    ]


def _group_reads(
    reads: list[ArtifactAccess],
) -> dict[tuple[str, str | None], tuple[ArtifactAccess, ...]]:
    grouped: dict[tuple[str, str | None], list[ArtifactAccess]] = {}
    for reader in reads:
        grouped.setdefault((reader.pattern, reader.glob_pattern), []).append(reader)
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
    # ``Path.parent`` saturates at the filesystem root.  Keeping the established three-level
    # fallback without indexing ``parents`` lets shallow but valid frame paths stay report-only.
    return logical_path.parent.parent.parent / "declaration" / "mass.yaml"


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
    try:
        frame = json.loads(frame_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"frame {frame_path} contains malformed JSON: {exc}") from exc
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

    try:
        mass = yaml.safe_load(mass_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"mass {mass_path} contains malformed YAML: {exc}") from exc
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


def _git_head(repo_root: Path) -> tuple[str | None, bool | None]:
    """The commit the tree is at and whether it is dirty; (None, None) when it is not a checkout."""
    try:
        head = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if head.returncode != 0:
            return None, None
        status = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            check=False,
        )
        dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
        return head.stdout.strip() or None, dirty
    except OSError:
        return None, None


def measured_provenance(
    repo_root: Path, frame_path: Path | None, decayed_members: list[str]
) -> dict[str, object]:
    head, dirty = _git_head(repo_root)
    epoch = frame_path.expanduser().absolute().parent.name if frame_path is not None else None
    return {
        "instrument_rev": "check-producer-consumers/consumer-side/1",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo_root": str(repo_root),
        "head": head,
        "dirty": dirty,
        "frame": {
            "elements": str(frame_path) if frame_path is not None else None,
            "epoch": epoch,
            "decayed_members": sorted(set(decayed_members)),
        },
    }


def analyse_consumer_side(
    repo_root: Path,
    allowlist: list[AllowlistEntry],
    *,
    frame_path: Path | None = None,
    mass_path: Path | None = None,
) -> ConsumerSideReport:
    tracked = _git_tracked_paths(repo_root)
    source_gaps: list[SourceGap] = []
    capped_expressions: set[str] = set()
    unresolved_closures: set[str] = set()
    unresolved_paths: set[str] = set()
    accesses, unresolved, imports_by_path, unrecognised = collect_artifact_accesses(
        repo_root,
        source_gaps=source_gaps,
        capped_expressions=capped_expressions,
        unresolved_closures=unresolved_closures,
        unresolved_paths=unresolved_paths,
    )
    reads = [item for item in accesses if item.action == "read"]
    writes = [item for item in accesses if item.action == "write"]
    findings: list[ConsumerSideFinding] = []
    pairs: list[ArtifactPair] = []
    exclusions = Counter({name: 0 for name in CONSUMER_SIDE_EXCLUSIONS})
    included_reads: list[ArtifactAccess] = []
    grouped_reads = _group_reads(reads)
    for (pattern, glob_pattern), reader_sites in grouped_reads.items():
        exclusion = _exclusion_class(
            glob_pattern
            if glob_pattern is not None
            else _literal_text(_literal_path(pattern), escape=True),
            tracked,
        )
        if exclusion is None:
            included_reads.extend(reader_sites)
        else:
            exclusions[exclusion] += 1

    non_python_sources = [
        (path, _read(path, source_gaps, repo_root))
        for path in _non_python_source_paths(repo_root, tracked)
    ]
    documented_sources = [
        (path, _read(path, source_gaps, repo_root))
        for path in _documented_elsewhere_source_paths(repo_root, tracked)
    ]
    for (pattern, glob_pattern), reader_sites in _group_reads(included_reads).items():
        representative = reader_sites[0]
        matching = [
            writer
            for writer in writes
            if writer.bounded and _accesses_match(representative, writer)
        ]
        unmodelled = tuple(reader for reader in reader_sites if not reader.modelled)
        if unmodelled:
            kind = "consumer-reads-through-unmodelled-api"
            callees = ",".join(sorted({reader.operation for reader in unmodelled}))
            detail = f"callees={callees} producer-match={'yes' if matching else 'no'}"
            modelled = tuple(reader for reader in reader_sites if reader.modelled)
            reported_sites = (*unmodelled, *modelled)
            findings.append(
                ConsumerSideFinding(
                    kind,
                    reported_sites[:3],
                    tuple(matching[:3]) or _nearest_writers(representative, writes),
                    f"{kind}:{pattern}",
                    detail,
                    reader_total=len(reader_sites),
                )
            )
        elif not matching:
            # Classification evidence is live evidence: a fixture under tests/ cannot downgrade
            # an absent producer into the weaker dynamic-root finding.
            dynamic_writers = _dynamic_root_writers(glob_pattern, writes) if glob_pattern else []
            producer_mentions = _non_python_mentions(pattern, non_python_sources, repo_root)
            documented_mentions = _non_python_mentions(pattern, documented_sources, repo_root)
            if dynamic_writers:
                kind = "consumer-reads-artifact-under-dynamic-root"
                detail = "same-basename-writer"
                nearest = _nearest_writers(representative, dynamic_writers)
            elif producer_mentions:
                kind = "consumer-reads-artifact-with-non-python-producer"
                detail = f"non-python-mentions={','.join(producer_mentions)}"
                nearest = _nearest_writers(representative, writes)
            elif documented_mentions:
                kind = "consumer-reads-artifact-documented-elsewhere"
                detail = f"documented-elsewhere={','.join(documented_mentions)}"
                nearest = _nearest_writers(representative, writes)
            else:
                kind = "consumer-reads-unwritten-artifact"
                detail = "searched=python-writers, non-python-mentions, docs, config, systemd"
                nearest = _nearest_writers(representative, writes)
            findings.append(
                ConsumerSideFinding(
                    kind,
                    reader_sites[:3],
                    nearest,
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
        paired = [
            writer
            for writer in identity_writers
            if (writer.bounded and _accesses_match(representative, writer))
            or (
                writer.pattern == pattern
                and not writer.bounded
                and all(not reader.bounded for reader in reader_sites)
            )
        ]
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

    decayed_member_ids: list[str] = []
    if frame_path is not None:
        resolved_mass = mass_path or _default_mass_path(frame_path)
        for member in load_decayed_members(frame_path, resolved_mass, repo_root):
            decayed_member_ids.append(member.member_id)
            for writer in writes:
                if not any(
                    _accesses_match(writer, replace(writer, pattern=pattern, glob_pattern=pattern))
                    for pattern in member.patterns
                ):
                    continue
                for reader in included_reads:
                    if not _accesses_match(reader, writer):
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

    unique_findings = _dedupe_findings(findings)
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
    return ConsumerSideReport(
        visible,
        allowed,
        unique_pairs,
        unresolved,
        dict(exclusions),
        unrecognised_path_calls=unrecognised,
        measured=measured_provenance(repo_root, frame_path, decayed_member_ids),
        errors=tuple(
            f"{gap.path}: {gap.operation} failed ({gap.error_class})"
            for gap in dict.fromkeys(source_gaps)
        ),
        source_gaps=tuple(dict.fromkeys(source_gaps)),
        capped_expressions=tuple(sorted(capped_expressions)),
        unresolved_closures=tuple(sorted(unresolved_closures)),
        unresolved_paths=tuple(sorted(unresolved_paths)),
    )


def _writer_label(writer: ArtifactAccess) -> str:
    return f"{writer.path}:{writer.lineno}=>{writer.pattern}"


def _finding_line(finding: ConsumerSideFinding) -> str:
    readers = ",".join(f"{reader.path}:{reader.lineno}" for reader in finding.readers[:3])
    candidates = ", ".join(_writer_label(item) for item in finding.writers[:3]) or "none"
    detail = f" {finding.detail}" if finding.detail else ""
    next_action = (
        "model the named callee's file-access semantics, then rerun"
        if finding.kind == "consumer-reads-through-unmodelled-api"
        else "bind the consumer to a live producer output or add a reasoned "
        "kind=consumer_side allowlist entry"
    )
    return (
        f"[REPORT] {finding.kind} readers={finding.reader_count} reader-sites={readers} "
        f"read={finding.reader.pattern} nearest-writers={candidates}{detail} "
        f"next-action={next_action}"
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
        "modelled": access.modelled,
        "bounded": access.bounded,
        "glob_pattern": access.glob_pattern,
    }


def _report_json(report: ConsumerSideReport) -> dict[str, object]:
    counts = Counter(finding.kind for finding in report.findings)
    return {
        "measured": report.measured,
        "summary": {
            "findings": len(report.findings),
            "findings_by_kind": {kind: counts[kind] for kind in CONSUMER_SIDE_KINDS},
            "allowlisted": len(report.allowlisted),
            "exclusions": report.exclusions,
            "unresolvable": report.unresolvable,
            "unrecognised_path_calls": report.unrecognised_path_calls,
            "errors": len(report.errors),
            "report_only": True,
            "status": "incomplete" if report.errors else "complete",
        },
        "errors": list(report.errors),
        "source_gaps": [
            {"path": str(gap.path), "operation": gap.operation, "error_class": gap.error_class}
            for gap in report.source_gaps
        ],
        "capped_expressions": list(report.capped_expressions),
        "unresolved_closures": list(report.unresolved_closures),
        "unresolved_paths": list(report.unresolved_paths),
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
                "status": "no-live-mismatch"
                if pair.reader.bounded and pair.writer.bounded
                else "unresolved",
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


def _write_consumer_side_json_report_only(report: ConsumerSideReport, path: Path) -> None:
    try:
        write_consumer_side_json(report, path)
    except (OSError, TypeError, ValueError) as exc:
        print(
            f"[REPORT-ERROR] {path}: {exc}; next action: pass a writable --report-json path "
            "(a directory under ~/.cache/hapax works) and rerun; the gate stays report-only"
        )


def print_consumer_side_report(report: ConsumerSideReport, report_path: Path) -> None:
    counts = Counter(finding.kind for finding in report.findings)
    print(
        "consumer-side counts: "
        f"status={'incomplete' if report.errors else 'complete'} "
        f"findings={len(report.findings)} "
        f"consumer-reads-unwritten-artifact={counts['consumer-reads-unwritten-artifact']} "
        "consumer-reads-through-unmodelled-api="
        f"{counts['consumer-reads-through-unmodelled-api']} "
        "consumer-reads-artifact-under-dynamic-root="
        f"{counts['consumer-reads-artifact-under-dynamic-root']} "
        "consumer-reads-artifact-with-non-python-producer="
        f"{counts['consumer-reads-artifact-with-non-python-producer']} "
        "consumer-reads-artifact-documented-elsewhere="
        f"{counts['consumer-reads-artifact-documented-elsewhere']} "
        f"consumer-producer-path-mismatch={counts['consumer-producer-path-mismatch']} "
        f"consumer-reads-decayed-producer={counts['consumer-reads-decayed-producer']} "
        f"allowlisted={len(report.allowlisted)} "
        "exclusions: "
        f"committed-in-repository={report.exclusions['committed-in-repository']} "
        f"system-path={report.exclusions['system-path']} "
        f"corpus-walk={report.exclusions['corpus-walk']} "
        f"unresolvable={report.unresolvable} "
        f"unrecognised-path-calls={sum(report.unrecognised_path_calls.values())}"
    )
    diagnostics = [
        f"[REPORT-ERROR] {gap.path}: {gap.operation} failed ({gap.error_class}); "
        "next action: make the source readable and valid Python, then rerun"
        for gap in report.source_gaps
    ]
    diagnostics.extend(
        f"[CAPPED] {site}: compact expression union; concrete alternatives retained"
        for site in report.capped_expressions
    )
    diagnostics.extend(
        f"[UNRESOLVED] {site}" for site in (*report.unresolved_closures, *report.unresolved_paths)
    )
    for diagnostic in diagnostics[:CONSUMER_SIDE_REPORT_LIMIT]:
        print(diagnostic)
    if len(diagnostics) > CONSUMER_SIDE_REPORT_LIMIT:
        print(f"{len(diagnostics) - CONSUMER_SIDE_REPORT_LIMIT} more in JSON")
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
        detail = (
            "status=no-live-mismatch; paired reader/writer resolved from two places"
            if pair.reader.bounded and pair.writer.bounded
            else "status=unresolved; equal dynamic patterns, possible pairing only"
        )
        print(
            f"[PAIRED] {pair.family} reader={pair.reader.path}:{pair.reader.lineno} "
            f"read={pair.reader.pattern} writer={pair.writer.path}:{pair.writer.lineno} "
            f"write={pair.writer.pattern} {detail}"
        )
    print(f"consumer-side full JSON report: {report_path}")
    print(
        "consumer-side gate is REPORT-ONLY until a follow-on row authorises it; "
        f"proposed arm {CONSUMER_SIDE_ARM} is intentionally not implemented"
    )


def run_consumer_side(args: argparse.Namespace) -> int:
    repo_root = Path.cwd()
    report_path = args.report_json or _report_output_path(repo_root)
    analysis_error: str | None = None
    try:
        allowlist = load_allowlist(args.allowlist)
        report = analyse_consumer_side(
            repo_root,
            allowlist,
            frame_path=args.frame,
            mass_path=args.mass,
        )
    except (AllowlistError, OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        analysis_error = f"consumer-side analysis incomplete: {exc}"
        report = ConsumerSideReport(
            [],
            [],
            [],
            0,
            {name: 0 for name in CONSUMER_SIDE_EXCLUSIONS},
            (analysis_error,),
        )
    _write_consumer_side_json_report_only(report, report_path)
    if analysis_error is not None:
        print(
            f"[REPORT-ERROR] {analysis_error}; next action: repair or drop the input the message "
            "names (--frame, --mass or the allowlist) and rerun; the gate stays report-only"
        )
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
    parser.add_argument("--report-json", type=Path, help="consumer-side JSON report destination")
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
