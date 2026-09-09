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

``--consumer-side`` adds the inverse, whole-tree report: artifact reads whose
writer is **absent**, reads whose writer is **located but of undetermined
execution**, named reader/writer families whose paths diverge, and (with
``--frame``) reads backed only by a producer in a decayed mass member.

The first two are separate sentences on purpose and this paragraph used to
flatten them into one. A located writer that cannot be shown to run is not an
absence, and saying "nothing writes this" about a file something may write is
the false-absence error the row exists to avoid — see
``consumer-reads-artifact-with-unresolved-writer`` in ``CONSUMER_SIDE_KINDS``
below, which the prose above it predated (review finding, claude).

That mode is deliberately report-only until a follow-on row authorises its
named arm, and its CI step carries ``continue-on-error`` so the workflow
enforces that rather than the script asserting it about its caller.

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
import operator as operator_module
import os
import re
import subprocess
import sys
import tomllib
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import NamedTuple

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
    # **A resolved-path writer whose EXECUTION is uncertain is not an absent one.** The report
    # used to say "unwritten" for an artifact whose writer this scanner had located precisely and
    # then declined to certify — an unqualified absence asserted on top of a recorded doubt.
    # Neither existing weak kind fits: the path is resolved, the root is not dynamic, and the
    # reader's API is modelled; what is unknown is only whether the site runs.
    #
    # Additive, and deliberately NOT a suppression: the reader, its count and its candidate
    # writer sites are all still reported. It creates no bounded pair and certifies no
    # production (coordinator direction, 2026-09-08).
    "consumer-reads-artifact-with-unresolved-writer",
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


@dataclass
class _ScopeEvidence:
    accesses: list[ArtifactAccess]
    unresolved: int
    unrecognised: Counter[str]
    calls: dict[ast.AST, list[dict[str, str]]]
    #: Which of `calls` this scope supplied from a REACHED site and which only from an unreached
    #: one. Carried on the evidence rather than left in the table, so a cache replay reproduces
    #: the uncertainty instead of re-certifying what the original walk withheld — and so it
    #: reaches a callee's callee, which is the transitive half of the same finding.
    certain_calls: dict[ast.AST, set[tuple]]
    uncertain_calls: dict[ast.AST, set[tuple]]
    nested: dict[ast.AST, list[dict[str, str]]]
    defaults: dict[ast.AST, dict[str, str]]
    paths: set[str]
    closures: set[str]


@dataclass(frozen=True)
class _OuterEffects:
    # Keep the storing function's identity, including its module and lexical owners.
    owners: frozenset[ast.AST] = frozenset()
    unresolved: str = ""
    uncertain_owners: frozenset[ast.AST] = frozenset()
    capped: bool = False


class PathFunctionTable(dict[str, PathFunction]):
    """Path helpers keyed by definition identity, with qualified export lookups.

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
        self.helper_results: dict[tuple[int, tuple[tuple[str, str], ...]], _HelperReturn] = {}
        self.definition_defaults: dict[ast.AST, dict[str, str]] = {}
        self.call_bindings: dict[ast.AST, list[dict[str, str]]] = {}
        #: Which invocation states were observed from a call site whose region is REACHED, and
        #: which only from one that is not. `_demote_from` marks the access list unbounded, but
        #: the callee's parameters are resolved from these bindings in a different scope walk, so
        #: an argument supplied inside an unreached region certified a concrete path there
        #: (review finding at `:4359`, raised independently by two families). A state is treated
        #: as uncertain only when NO reached call site supplied it: one real caller is enough to
        #: certify, and withholding then would assert absence rather than withhold.
        #:
        #: Named for STATES, not bindings: `uncertain_bindings` below is a different question
        #: about a different subject — which function NODES lost a rebound export — and holding
        #: both under one noun silently overwrote it.
        self.certain_call_states: dict[ast.AST, set[tuple]] = {}
        self.uncertain_call_states: dict[ast.AST, set[tuple]] = {}
        #: True while a body is being scanned under a state no reached call site supplied. A
        #: callee reached only through such a body is no better established than the body, so
        #: the calls IT records inherit the doubt — otherwise the withholding stops at the first
        #: callee and one relay function restores certification (measured: a helper called by a
        #: helper certified a writer the run never reached).
        self.scanning_uncertain = False
        self.scope_results: dict[ast.AST, dict[tuple, _ScopeEvidence]] = {}
        self.binding_states: dict[ast.AST, set[tuple]] = {}
        self.capped_scopes: set[ast.AST] = set()
        self.global_snapshot_ids: dict[tuple[tuple[str, str], ...], str] = {}
        self.global_snapshots: list[dict[str, str]] = []
        self.scope_calls: dict[ast.AST, list[ast.Call]] = {}
        self.scope_helpers: dict[tuple, tuple[ast.AST, ...]] = {}
        self.scope_locals: dict[ast.AST, set[str]] = {}
        self.scope_mutations: dict[ast.AST, tuple[set[str], set[str]]] = {}
        self.call_edges: dict[ast.AST, set[ast.AST]] = {}
        self.functions_by_node: dict[ast.AST, PathFunction] = {}
        self.export_bindings: dict[str, str] = {}
        self.export_paths: dict[str, Path] = {}
        self.uncertain_bindings: set[ast.AST] = set()
        self.unknown_effects: dict[ast.AST, str] = {}
        self.outer_effects: dict[ast.AST, _OuterEffects] = {}
        self.effect_revisions: Counter[ast.AST] = Counter()
        self.scope_captures: dict[ast.AST, set[str]] = {}
        self.capped_reads: set[ArtifactAccess] = set()

    def close_outer_effects(self) -> set[ast.AST]:
        """Close the discovered call graph from leaves, with bounded summaries, no recursion.

        Nodes left after leaf removal reach a cycle. They cannot certify an effect closure,
        even when invocation arguments happen to converge. Missing bodies and state/summary
        caps are likewise explicit uncertainty. Only changed summaries invalidate scan caches.
        """
        parents: dict[ast.AST, set[ast.AST]] = {}
        remaining = {node: len(callees) for node, callees in self.call_edges.items()}
        for node, callees in self.call_edges.items():
            for callee in callees:
                remaining.setdefault(callee, 0)
                parents.setdefault(callee, set()).add(node)
        pending = [node for node, count in remaining.items() if not count]
        closed: dict[ast.AST, _OuterEffects] = {}
        depths: dict[ast.AST, int] = {}
        while pending:
            node = pending.pop()
            function = self.functions_by_node.get(node)
            if function is not None and node not in self.scope_mutations:
                self.scope_mutations[node] = _scope_outer_mutations(function.node)
            direct = self.scope_mutations.get(node, (set(), set()))
            owners = {node} if any(direct) else set()
            reason = self.unknown_effects.get(node, "")
            capped = node in self.capped_scopes
            if node in self.capped_scopes:
                reason = "binding state cap"
            elif node not in self.scope_results:
                reason = "unresolved call target body"
            uncertain_owners = {node} if reason else set()
            depth = 0
            for callee in self.call_edges.get(node, ()):
                effects = closed[callee]
                owners.update(effects.owners)
                uncertain_owners.update(effects.uncertain_owners)
                reason = reason or effects.unresolved
                capped |= effects.capped
                depth = min(_MAX_BINDING_ROUNDS, max(depth, depths[callee] + 1))
                if len(owners | uncertain_owners) > _MAX_BINDING_STATES:
                    owners = {node} if any(direct) else set()
                    uncertain_owners = {node}
                    reason = "outer effect summary cap"
                    capped = True
                    break
            if depth >= _MAX_BINDING_ROUNDS:
                reason = "outer effect depth cap"
                capped = True
            closed[node] = _OuterEffects(
                frozenset(owners), reason, frozenset(uncertain_owners), capped
            )
            depths[node] = depth
            for parent in parents.get(node, ()):
                remaining[parent] -= 1
                if not remaining[parent]:
                    pending.append(parent)
        for node, count in remaining.items():
            if count:
                closed[node] = _OuterEffects(unresolved="recursive outer effect cycle")
        changed = {
            node
            for node in closed.keys() | self.outer_effects.keys()
            if closed.get(node, _OuterEffects()) != self.outer_effects.get(node, _OuterEffects())
        }
        if changed:
            # A changed effect summary is a dependency revision, not a new invocation.
            # Each callee was closed once above; only its callers used that summary.
            # A global epoch repeatedly rescans unrelated modules on every graph revision.
            affected = {parent for node in changed for parent in parents.get(node, ())}
            for node in affected - self.capped_scopes:
                if any(closed[callee].capped for callee in self.call_edges.get(node, ())):
                    # A callee cap withdraws certainty, not already observed reader identity.
                    # Keep only unresolved reads before evicting provisional scope evidence;
                    # neither bounded reads/defaults nor any producer can survive this way.
                    self.capped_reads.update(
                        access
                        for evidence in self.scope_results.get(node, {}).values()
                        for access in evidence.accesses
                        if access.action == "read" and not access.bounded
                    )
                self.effect_revisions[node] += 1
                self.scope_results.get(node, {}).clear()
        self.outer_effects = closed
        return changed

    def record_calls(self, node: ast.AST, states: list[dict[str, str]]) -> None:
        """Bound distinct invocation states across all fixpoint rounds, including cache replay."""
        seen = self.binding_states.setdefault(node, set())
        current = self.call_bindings.setdefault(node, [])
        for state in states:
            if node in self.capped_scopes:
                return
            key = tuple(sorted(state.items()))
            if key not in seen:
                if len(seen) >= _MAX_BINDING_STATES:
                    self.capped_scopes.add(node)
                    current.clear()
                    return
                seen.add(key)
            if state not in current:
                current.append(state)

    def merge_binding_certainty(
        self,
        certain: Mapping[ast.AST, set[tuple]],
        uncertain: Mapping[ast.AST, set[tuple]],
    ) -> None:
        """Union one walk's verdict about its own call sites into the repository-wide view.

        A walk classifies its recordings only once it has finished, because a region's
        reachability is decided after the call inside it has already been recorded. Merged as a
        union and tested as `uncertain and not certain`, so **one reached call site is enough**:
        withholding on the mere existence of an unreached site would assert that the reached one
        does not exist, which is the over-reach the demotion itself is careful not to commit.
        """
        reached = (
            self.uncertain_call_states if self.scanning_uncertain else self.certain_call_states
        )
        for node, keys in certain.items():
            reached.setdefault(node, set()).update(keys)
        for node, keys in uncertain.items():
            self.uncertain_call_states.setdefault(node, set()).update(keys)

    def register(self, relative: Path, qualname: str, function: PathFunction) -> None:
        qualified = f"{_module_name(relative)}.{qualname}"
        self[qualified] = function
        if function.node is not None:
            self[_definition_identity(qualified, function.node)] = function
            self.functions_by_node[function.node] = function
        self.helper_results.clear()

    def canonical_name(
        self,
        name: str,
        calling_path: Path,
        lexical_prefixes: tuple[str, ...] = (),
        aliases: Mapping[str, str] | None = None,
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
        aliases: Mapping[str, str] | None = None,
        *,
        retain_uncertain: bool = False,
    ) -> PathFunction | None:
        canonical = self.canonical_name(name, calling_path, lexical_prefixes, aliases)
        if not canonical:
            return None
        # Imports see the module's evaluated export, including a replaced/decorated or
        # conditionally defined function. Registration alone cannot certify that object.
        seen: set[str] = set()
        uncertain = False
        while canonical in self.export_bindings:
            if canonical in seen:
                return None
            seen.add(canonical)
            if isinstance(aliases, _ImportAliases) and canonical in self.export_paths:
                prefix = f"{_MODULE_EFFECT_PREFIX}{self.export_paths[canonical]}\0"
                exported_name = canonical.rsplit(".", 1)[-1]
                uncertain |= (
                    f"{prefix}{exported_name}" in aliases.values or f"{prefix}*" in aliases.values
                )
            canonical = self.export_bindings[canonical]
            if not canonical:
                return None
        if uncertain:
            # The initialization body identifies evidence to withhold, not a callable to
            # follow. Otherwise the uncalled-body fallback could still certify its writes.
            function = self.get(canonical)
            if function is not None and function.node is not None:
                self.uncertain_bindings.add(function.node)
            if not retain_uncertain:
                return None
        bindings = self.aliases_by_path.get(calling_path, {}) if aliases is None else aliases
        if name.partition(".")[0] in bindings:
            # The live statement-order binding also records definitions. An import can
            # replace an earlier definition, and a later definition can replace the import.
            # A missing imported body must not fall back to a shadowed local producer.
            return self.get(canonical)
        if aliases is not None:
            # Syntax discovery is not an evaluated binding (for example a call before def).
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


def _definition_identity(qualified: str, node: ast.AST) -> str:
    return f"{qualified}@{node.lineno}:{node.col_offset}"


def _dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


# NUL cannot occur in a filename. Protect literal metacharacters in the value maps
# (including serialized branch unions), retaining bare '*' only for dynamic patterns.
_LITERAL_GLOB_MARKERS = {"*": "\0star", "?": "\0question", "[": "\0left", "]": "\0right"}
# A symbolic absolute root, independent of the scanner's HOME. Source literals cannot
# impersonate it: _literal_path escapes NUL. Only the rendered report uses '~' for home.
_HOME_ROOT = "/\0home"


def _literal_path(value: str) -> str:
    # Invalid source literals must not impersonate the internal provenance markers.
    return value.replace("\0", "\0nul").translate(str.maketrans(_LITERAL_GLOB_MARKERS))


def _literal_text(value: str, *, escape: bool = False) -> str:
    if value == _HOME_ROOT or value.startswith(_HOME_ROOT + "/"):
        value = "~" + value[len(_HOME_ROOT) :]
    for character, marker in _LITERAL_GLOB_MARKERS.items():
        value = value.replace(marker, f"[{character}]" if escape else character)
    return value


def _normalise_pattern(value: str, repo_root: Path) -> str:
    # POSIX backslashes, including runtime !r/!a output, are filename characters.
    root = repo_root.resolve().as_posix()
    if value == root:
        return "."
    if value.startswith(root + "/"):
        value = value[len(root) + 1 :]
    while value.startswith("./") and not (value == "./~" or value.startswith("./~/")):
        value = value[2:]
    while "//" in value:
        value = value.replace("//", "/")
    return value or "."


def _join_pattern(left: str, right: str, repo_root: Path) -> str:
    joined = right if right.startswith("/") or left in ("", ".") else f"{left.rstrip('/')}/{right}"
    # Preserve expression identity until access recording: this result may still
    # be an absolute RHS, or be concatenated with another string.
    return joined


def _parent_pattern(value: str, levels: int, repo_root: Path) -> str | None:
    result = value
    for _ in range(levels):
        if result == _HOME_ROOT:
            return None
        result = str(PurePosixPath(result).parent)
    return result


def _function_name(call: ast.Call, values: dict[str, str] | None = None) -> str:
    return (
        _dotted_name(_evaluated_expression(call.func, values) if values is not None else call.func)
        or ""
    )


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
_CALL_GLOBALS_KEY = "\0call-globals"
_MODULE_EFFECT_PREFIX = "\0module-effect:"
_CLASS_OUTER_KEY = "\0class-outer"
_CALL_LOCALS_KEY = "\0call-locals"
_CALL_CELLS_KEY = "\0call-cells"
_EXPRESSION_VALUE_PREFIX = "\0evaluated:"
_LOOP_VALUE_PREFIX = "\0loop-value:"
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


def _intern_binding_state(values: dict[str, str], functions: dict[str, PathFunction]) -> str:
    """Share immutable snapshots instead of copying JSON into every call state."""
    if not isinstance(functions, PathFunctionTable):
        return json.dumps(values, sort_keys=True)
    key = tuple(sorted(values.items()))
    encoded = functions.global_snapshot_ids.get(key)
    if encoded is None:
        encoded = str(len(functions.global_snapshots))
        functions.global_snapshot_ids[key] = encoded
        functions.global_snapshots.append(dict(values))
    return encoded


def _encode_call_globals(values: dict[str, str], functions: dict[str, PathFunction]) -> str:
    # Execution-frame bookkeeping is not a module binding. Including the imported callee's
    # lexical name makes identical globals look different for every entry point, exhausting
    # the state cap and propagating artificial changes around the call graph.
    metadata = {
        _CALL_GLOBALS_KEY,
        _CLASS_OUTER_KEY,
        _CALL_LOCALS_KEY,
        _CALL_CELLS_KEY,
        _LEXICAL_SCOPE_KEY,
        _HELPER_STACK_KEY,
        _HELPER_EFFECT_KEY,
        _FLOW_EXIT_KEY,
    }
    return _intern_binding_state(
        {
            key: value
            for key, value in values.items()
            if key not in metadata
            and _EXPRESSION_VALUE_PREFIX not in key
            and _LOOP_VALUE_PREFIX not in key
        },
        functions,
    )


def _decode_call_globals(encoded: str | None, functions: dict[str, PathFunction]) -> dict[str, str]:
    if encoded is None:
        return {}
    if isinstance(functions, PathFunctionTable):
        return dict(functions.global_snapshots[int(encoded)])
    return json.loads(encoded)


def _call_global_values(
    function: PathFunction,
    values: dict[str, str],
    calling_path: Path,
    path_functions: dict[str, PathFunction],
) -> dict[str, str]:
    """Keep invocation globals separate from the caller's parameters and local bindings."""
    if calling_path != function.path:
        globals_ = dict(function.module_values)
        # Foreign effects belong to this invocation's view, never the shared definition.
        # Carry them through intermediate modules so a later imported call cannot reload
        # a certified value from the producer's initialization snapshot.
        globals_.update(
            (key, value) for key, value in values.items() if key.startswith(_MODULE_EFFECT_PREFIX)
        )
        prefix = f"{_MODULE_EFFECT_PREFIX}{function.path}\0"
        names = {key.removeprefix(prefix) for key in globals_ if key.startswith(prefix)}
        if "*" in names:
            names = {name for name in globals_ if not name.startswith("\0")}
        _BlockScanner._invalidate_effect_names(globals_, names)
        return globals_
    return _current_global_values(values, path_functions)


def _current_global_values(
    values: dict[str, str], path_functions: dict[str, PathFunction]
) -> dict[str, str]:
    """Invocation globals shared by function calls and immediately executed class bodies."""
    inherited = _decode_call_globals(values.get(_CALL_GLOBALS_KEY), path_functions)
    local_keys = {
        key
        for name in (
            *json.loads(values.get(_CALL_LOCALS_KEY, "[]")),
            *json.loads(values.get(_CALL_CELLS_KEY, "[]")),
        )
        for key in _binding_keys(name)
    }
    for key in inherited.keys() | values.keys():
        if (
            key in local_keys
            or key
            in {
                _CALL_GLOBALS_KEY,
                _CLASS_OUTER_KEY,
                _CALL_LOCALS_KEY,
                _CALL_CELLS_KEY,
                _LEXICAL_SCOPE_KEY,
            }
            or _EXPRESSION_VALUE_PREFIX in key
            or _LOOP_VALUE_PREFIX in key
        ):
            continue
        inherited.pop(key, None)
        if key in values:
            inherited[key] = values[key]
    return inherited


def _definition_scope_values(
    values: dict[str, str], path_functions: dict[str, PathFunction]
) -> dict[str, str]:
    """Methods and lambdas capture enclosing function cells, never class attributes."""
    captured = dict(values)
    if _CLASS_OUTER_KEY not in captured:
        return captured
    globals_ = _current_global_values(captured, path_functions)
    while _CLASS_OUTER_KEY in captured:
        outer = _decode_call_globals(captured[_CLASS_OUTER_KEY], path_functions)
        cells = set(json.loads(captured.get(_CALL_CELLS_KEY, "[]"))) - set(
            json.loads(captured.get(_CALL_LOCALS_KEY, "[]"))
        )
        for name in cells:
            for key in _binding_keys(name):
                outer.pop(key, None)
                if key in captured:
                    outer[key] = captured[key]
        captured = outer
    captured[_CALL_GLOBALS_KEY] = _encode_call_globals(globals_, path_functions)
    return captured


def _expression_value_name(node: ast.AST) -> str:
    return (
        f"{_EXPRESSION_VALUE_PREFIX}{type(node).__name__}:"
        f"{getattr(node, 'lineno', 0)}:{getattr(node, 'col_offset', 0)}:"
        f"{getattr(node, 'end_lineno', 0)}:{getattr(node, 'end_col_offset', 0)}"
    )


def _evaluated_expression(node: ast.expr | None, values: dict[str, str]) -> ast.expr | None:
    """Reuse an operand's value after a later operand has changed its source binding."""
    if isinstance(node, ast.Name) and node.id.startswith(_EXPRESSION_VALUE_PREFIX):
        return node
    if node is not None and (name := _expression_value_name(node)) in values:
        return ast.copy_location(ast.Name(id=name, ctx=ast.Load()), node)
    return node


def _unresolved_expression_origins(node: ast.expr | None, values: dict[str, str]) -> set[str]:
    """Frozen operands retain their own provenance after subsequent outer stores."""
    pending = [node] if node is not None else []
    origins: set[str] = set()
    while pending:
        item = _evaluated_expression(pending.pop(), values)
        if isinstance(item, ast.Name):
            origin = values.get(f"{_UNRESOLVED_CLOSURE_PREFIX}{item.id}")
            if origin is not None:
                origins.add(origin)
        pending.extend(ast.iter_child_nodes(item))
    return origins


def _set_import_alias(values: dict[str, str], name: str, target: str | None) -> None:
    values[f"{_IMPORT_ALIAS_PREFIX}{name}"] = target or ""


class _ImportAliases(Mapping[str, str]):
    """A live binding view: resolving one name must not copy every module global."""

    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def __getitem__(self, name: str) -> str:
        return self.values[f"{_IMPORT_ALIAS_PREFIX}{name}"]

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and f"{_IMPORT_ALIAS_PREFIX}{name}" in self.values

    def get(self, name: str, default=None):
        return self.values.get(f"{_IMPORT_ALIAS_PREFIX}{name}", default)

    def __iter__(self) -> Iterator[str]:
        return (
            key.removeprefix(_IMPORT_ALIAS_PREFIX)
            for key in self.values
            if key.startswith(_IMPORT_ALIAS_PREFIX)
        )

    def __len__(self) -> int:
        return sum(1 for _ in self)


def _import_aliases(values: dict[str, str]) -> Mapping[str, str]:
    return _ImportAliases(values)


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
    # Expressions are read-only throughout evaluation. Copy only the spine being
    # replaced, not every unaffected operand for each conditional alternative.
    if not path:
        return replacement
    result = copy.copy(node)
    current: ast.AST = result
    for offset, (field_name, index) in enumerate(path):
        value = getattr(current, field_name)
        child = value if index is None else value[index]
        changed = replacement if offset == len(path) - 1 else copy.copy(child)
        if index is None:
            setattr(current, field_name, changed)
        else:
            items = list(value)
            items[index] = changed
            setattr(current, field_name, items)
        current = changed
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
        # Reachability is decided here too, not only in the expression walker. This expander
        # used to emit EVERY alternative, so `open('wrong.json' or 'actual.json', 'w')`
        # certified both filenames and suppressed an orphan reader of the one Python never
        # writes (codex, at `c01c645d2`). Repairing the walker alone left this path deciding
        # the same question the opposite way, one layer over.
        alternatives = _reachable_alternatives(conditional)
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


def _reachable_alternatives(
    conditional: ast.expr, resolve: _ConstantResolver | None = None
) -> tuple[ast.expr, ...]:
    """Which arms of a conditional can actually be evaluated — ONE decision, every caller.

    This exists because writing the decision twice is exactly how it went wrong. Reachability
    filtering was added to `_conditional_expr_variants` and NOT to `_expand_conditional_union`,
    which re-expands the same node when the variant cap trips, so past the eight-variant
    boundary the filtered-out arms came straight back and certified phantom writers
    (codex, at `45a37aeda`). The scanner decides this in several places; it must not *derive*
    it in several places.
    """
    if isinstance(conditional, ast.IfExp):
        known, constant = _literal_operand(conditional.test, resolve)
        if known:
            return (conditional.body,) if constant else (conditional.orelse,)
        return (conditional.body, conditional.orelse)
    assert isinstance(conditional, ast.BoolOp)
    if isinstance(conditional.op, ast.Or):
        return _reachable_or_operands(tuple(conditional.values), resolve)
    return tuple(conditional.values)


def _reachable_or_operands(
    values: tuple[ast.expr, ...], resolve: _ConstantResolver | None = None
) -> tuple[ast.expr, ...]:
    """Which operands of an ``or`` can actually be its value.

    ``a or b or c`` yields the first truthy operand, or the last one if none is truthy. So a
    **constant falsy** operand can never be the result unless it is last, and a **constant
    truthy** one always is — nothing after it is reachable. Only constants decide; a dynamic
    operand leaves everything from it onward possible, which is the existing behaviour.
    """
    reachable: list[ast.expr] = []
    for index, value in enumerate(values):
        known, constant = _literal_operand(value, resolve)
        last = index == len(values) - 1
        if known and not constant and not last:
            continue  # a falsy constant is never what `or` returns
        reachable.append(value)
        if known and constant:
            break  # a truthy constant is the value; later operands do not evaluate
    return tuple(reachable) if reachable else (values[-1],)


def _expand_conditional_union(expression: ast.expr) -> Iterator[ast.expr]:
    """Stream leaves of a compact union without materialising its Cartesian product."""
    conditional_path = _first_conditional_expression_path(expression)
    if conditional_path is None:
        yield expression
        return
    conditional = _ast_node_at(expression, conditional_path)
    # The SAME decision as the uncapped path. Deriving it separately here is what let the
    # cap fallback restore arms that reachability had already ruled out.
    alternatives = _reachable_alternatives(conditional)
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
    node = _evaluated_expression(node, values)
    variants = [
        _resolve_path_expr(expression, state, path, repo_root, path_functions)
        for expression in _path_expressions(node, path, path_functions)
        for state in _expand_value_alternative_states(expression, values)
    ]
    if not variants:
        variants.append(None)
    return tuple(dict.fromkeys(variants))


def _builtin_str_call(
    node: ast.Call,
    values: dict[str, str],
    path: Path | None,
    path_functions: object | None,
) -> bool:
    """Whether this call is the BUILTIN `str`, rather than something wearing its name.

    `def str(value): return 'actual'` makes `f'{str(1)}'` produce `actual`, and folding the raw
    spelling certified `artifacts/1.json` for a file Python never writes (review finding, codex,
    2026-09-07 — a defect I introduced one round earlier by folding on the name alone). The
    resolver canonicalises names through the function table for exactly this reason; the constant
    channel did not, so it is given the same table here.

    Without a table the answer is "not established", and the fold does not happen: a missed
    constant costs a wildcard, a wrong one costs a certification.
    """

    if node.keywords or _function_name(node, values) != "str":
        return False
    if not isinstance(path_functions, PathFunctionTable) or path is None:
        return False
    shadow = path_functions.resolve(
        "str", path, _lexical_scope(values), _import_aliases(values), retain_uncertain=True
    )
    return shadow is None


def _constant_value(
    node: ast.expr | None,
    values: dict[str, str],
    path: Path | None = None,
    path_functions: object | None = None,
) -> tuple[bool, object]:
    """Keep scalar types for formatting; a path-shaped abstract string is not a constant."""
    node = _evaluated_expression(node, values)
    if isinstance(node, ast.NamedExpr):
        # The walker freezes this value before rebinding its target.
        return _constant_value(node.value, values, path, path_functions)
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, type(None))):
        return True, node.value
    if isinstance(node, ast.Name):
        encoded = values.get(f"{_CONSTANT_VALUE_PREFIX}{node.id}")
        if encoded is not None:
            return True, json.loads(encoded)
    if isinstance(node, ast.IfExp):
        known, condition = _constant_value(node.test, values, path, path_functions)
        if known:
            return _constant_value(
                node.body if condition else node.orelse, values, path, path_functions
            )
        left_known, left = _constant_value(node.body, values, path, path_functions)
        right_known, right = _constant_value(node.orelse, values, path, path_functions)
        if left_known and right_known and type(left) is type(right) and left == right:
            return True, left
    if isinstance(node, ast.Call) and _builtin_str_call(node, values, path, path_functions):
        # `str()` is the empty string and `str(<known scalar>)` is that scalar's text. The path
        # resolver already knows both; the constant channel did not, so an interpolation of `str()`
        # became an unknown and the whole f-string widened to a wildcard — which bounded a writer
        # over `artifacts/*state.json` and silenced the orphan for `artifacts/alienstate.json`.
        # Only this one builtin, and only over values that are already known: an unknown argument
        # stays unknown, so an unknown interpolation stays unbounded.
        if not node.args:
            return True, ""
        if len(node.args) == 1:
            known, value = _constant_value(node.args[0], values, path, path_functions)
            if known:
                return True, str(value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left_known, left = _constant_value(node.left, values, path, path_functions)
        right_known, right = _constant_value(
            node.right,
            values,
            path,
            path_functions,
        )
        if (
            left_known
            and right_known
            and (
                isinstance(left, str)
                and isinstance(right, str)
                or isinstance(left, (int, float))
                and isinstance(right, (int, float))
            )
        ):
            return True, left + right
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        known, value = _constant_value(node.operand, values, path, path_functions)
        if known and isinstance(value, (int, float)):
            return True, -value if isinstance(node.op, ast.USub) else +value
    return False, None


def _format_constant(
    node: ast.FormattedValue,
    values: dict[str, str],
    path: Path | None = None,
    path_functions: object | None = None,
    repo_root: Path | None = None,
) -> str | None:
    known, value = _constant_value(node.value, values, path, path_functions)
    if not known and path is not None and isinstance(path_functions, PathFunctionTable):
        known, value = _returned_constant(
            node.value, path, values, path_functions, repo_root=repo_root
        )
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
    node = _evaluated_expression(node, values)
    if node is None:
        return False
    for item in ast.walk(node):
        # Preserve uncertainty in composed path operands without turning a separate
        # unresolved call branch into uncertainty about its known sibling branch.
        evaluated = (
            _evaluated_expression(item, values)
            if isinstance(item, (ast.Attribute, ast.Subscript, ast.BinOp))
            else item
        )
        if (
            isinstance(evaluated, ast.Name)
            and f"{_UNRESOLVED_FORMAT_PREFIX}{evaluated.id}" in values
        ):
            return True
        if (
            isinstance(item, ast.Attribute)
            and item.attr == "parent"
            or isinstance(item, ast.Subscript)
            and isinstance(item.value, ast.Attribute)
            and item.value.attr == "parents"
        ):
            base = item.value if isinstance(item, ast.Attribute) else item.value.value
            resolved = _resolve_path_expr(base, values, path, repo_root, path_functions)
            if (
                resolved is not None
                and resolved.startswith(_HOME_ROOT)
                and _resolve_path_expr(item, values, path, repo_root, path_functions) is None
            ):
                # The parent above home is not a known wildcard root.
                return True
        if isinstance(item, ast.Call):
            name = (
                path_functions.canonical_name(
                    _function_name(item, values),
                    path,
                    _lexical_scope(values),
                    _import_aliases(values),
                )
                if isinstance(path_functions, PathFunctionTable)
                else _function_name(item)
            )
            # A default is useful evidence, not an established environment binding.
            if name in {"os.getenv", "os.environ.get"}:
                return True
            if isinstance(item.func, ast.Attribute) and item.func.attr in {
                "expanduser",
                "absolute",
                "resolve",
            }:
                return True
        if isinstance(item, ast.Call) and isinstance(path_functions, PathFunctionTable):
            result, unbounded = _resolve_path_helper(item, values, path, repo_root, path_functions)
            if unbounded or "*" in (result or ""):
                return True
        if (
            isinstance(item, ast.FormattedValue)
            and _format_constant(item, values, path, path_functions, repo_root) is None
        ):
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
    node = _evaluated_expression(node, values)
    if node is None or depth > 12:
        return None
    if isinstance(node, ast.NamedExpr):
        # The walrus's value, not its target: see `_constant_value` for why the target is stale
        # exactly where it matters.
        return _resolve_path_expr(
            node.value, values, path, repo_root, path_functions, depth=depth + 1
        )
    # An unbounded closure cell is not a dynamic path component. In particular, formatting
    # it must not turn an obsolete binding into a wildcard producer.
    if depth == 0 and _unresolved_expression_origins(node, values):
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
        # The shared walker has frozen each interpolation before later effects.
        scope = values
        for item in node.values:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                parts.append(_literal_path(item.value))
            elif isinstance(item, ast.FormattedValue):
                formatted = _format_constant(item, scope, path, path_functions, repo_root)
                if formatted is not None:
                    parts.append(_literal_path(formatted))
                    continue
                if item.format_spec is not None or item.conversion != -1:
                    return None
                # Preserve the existing unformatted dynamic-pattern gap evidence. Explicit
                # formatting cannot use this approximation: its type/spec must be known.
                resolved = _resolve_path_expr(
                    item.value,
                    scope,
                    path,
                    repo_root,
                    path_functions,
                    depth=depth + 1,
                )
                parts.append(resolved if resolved and resolved != "*" else "*")
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.Add)):
        left = _resolve_path_expr(
            node.left, values, path, repo_root, path_functions, depth=depth + 1
        )
        right = _resolve_path_expr(
            node.right,
            values,
            path,
            repo_root,
            path_functions,
            depth=depth + 1,
        )
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add):
            return left + right
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
            # An attribute has an object owner, never the identity of a lexical namesake.
            return None
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
            _function_name(node, values), path, _lexical_scope(values), _import_aliases(values)
        )
        if isinstance(path_functions, PathFunctionTable)
        else _function_name(node)
    )
    if name in _PATH_CONSTRUCTORS:
        components: list[str] = []
        for argument in node.args:
            known, value = _constant_value(argument, values, path, path_functions)
            if known and not isinstance(value, str):
                return None
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
            # Empty is a known string component, not an unknown path or current directory.
            return "" if not node.keywords else None
        if len(node.args) == 1 and not node.keywords:
            known, value = _constant_value(node.args[0], values, path, path_functions)
            if not known:
                known, value = _returned_constant(
                    node.args[0], path, values, path_functions, repo_root=repo_root
                )
            if known:
                return _literal_path(str(value))
        return _resolve_path_expr(
            node.args[0], values, path, repo_root, path_functions, depth=depth + 1
        )
    if name in {"Path.home", "pathlib.Path.home"}:
        return _HOME_ROOT
    if name in {"os.getenv", "os.environ.get"}:
        default = node.args[1] if len(node.args) > 1 else None
        for keyword in node.keywords:
            if keyword.arg == "default":
                default = keyword.value
        return _resolve_path_expr(default, values, path, repo_root, path_functions, depth=depth + 1)
    if isinstance(node.func, ast.Attribute) and node.func.attr == "expanduser":
        # Expansion depends on runtime home/user bindings. Do not certify its input
        # as its result or inspect the scanner's environment to guess that result.
        return None
    if isinstance(node.func, ast.Attribute) and node.func.attr == "absolute":
        # Runtime cwd is unknown, so retain input evidence without certifying a result.
        return None
    if isinstance(node.func, ast.Attribute) and node.func.attr == "resolve":
        # Runtime cwd and symlink targets are unknown. Retain input evidence without
        # certifying a resolved path or following the scanner's filesystem.
        return None
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
            # The home root is a symbol, not a location: this scanner does not know whose home it
            # is, so it does not know the parent either. Taking `PurePosixPath` of the sentinel
            # yields the filesystem root and named `/state.json` for what Python evaluates as the
            # home's sibling — a bounded writer at a path the code never touches, which then
            # silenced the real reader's orphan. A home CHILD still has a known parent (the home
            # itself), so `(Path.home() / 'x').with_name(...)` keeps working.
            if base == _HOME_ROOT:
                return None
            return _join_pattern(str(PurePosixPath(base).parent), new_name, repo_root)

    return _resolve_path_helper(node, values, path, repo_root, path_functions)[0]


def _returned_constant(
    node: ast.expr | None,
    path: Path,
    values: dict[str, str],
    path_functions: dict[str, PathFunction],
    *,
    repo_root: Path | None = None,
) -> tuple[bool, object]:
    """Read typed evidence from the same invocation summary as path resolution."""
    if not isinstance(node, ast.Call) or not isinstance(path_functions, PathFunctionTable):
        return False, None
    result = _helper_return_summary(node, values, path, repo_root or path.parent, path_functions)
    return (True, json.loads(result.constant)) if result.constant is not None else (False, None)


@dataclass(frozen=True)
class _HelperReturn:
    pattern: str | None = None
    unbounded: bool = False
    constant: str | None = None


def _resolve_path_helper(
    node: ast.Call,
    values: dict[str, str],
    path: Path,
    repo_root: Path,
    path_functions: dict[str, PathFunction],
) -> tuple[str | None, bool]:
    result = _helper_return_summary(node, values, path, repo_root, path_functions)
    return result.pattern, result.unbounded


def _helper_return_summary(
    node: ast.Call,
    values: dict[str, str],
    path: Path,
    repo_root: Path,
    path_functions: dict[str, PathFunction],
) -> _HelperReturn:
    """Keep a visible helper's literal result separate from its certification certainty."""
    name = _function_name(node, values)
    function = (
        path_functions.resolve(
            name, path, _lexical_scope(values), _import_aliases(values), retain_uncertain=True
        )
        if isinstance(path_functions, PathFunctionTable)
        else (path_functions.get(name) or path_functions.get(name.rsplit(".", 1)[-1]))
    )
    if function is None or function.node is None or function.return_expr is None:
        return _HelperReturn()
    uncertain = (
        isinstance(path_functions, PathFunctionTable)
        and function.node in path_functions.uncertain_bindings
    )
    if _HELPER_EFFECT_KEY in values:
        # An unknown effect already prevents this helper invocation from returning a bounded
        # path. Keep walking its control flow, but do not recursively expand more helpers.
        return _HelperReturn()
    if (
        isinstance(path_functions, PathFunctionTable)
        and function.node not in path_functions.definition_defaults
    ):
        # Registration discovers syntax, but an unreachable definition creates no binding.
        return _HelperReturn()
    helper_key = f"{function.path}:{function.node.lineno}"
    stack = values.get(_HELPER_STACK_KEY, "").split("|")
    if helper_key in stack or len(stack) > 12:
        return _HelperReturn()
    invocation_globals = _call_global_values(function, values, path, path_functions)
    inherited = dict(invocation_globals)
    if len(function.lexical_prefixes) > 1:
        if function.lexical_prefixes[1] not in _lexical_scope(values):
            return _HelperReturn()
        inherited = dict(values)
    inherited[_HELPER_STACK_KEY] = "|".join((*stack, helper_key))
    bound = _scope_initial_values(
        function.node,
        inherited,
        function.path,
        repo_root,
        path_functions,
        function.lexical_prefixes,
        invocation_globals,
    )
    supplied = _call_parameter_values(function, node, values, path, repo_root, path_functions)
    _invalidate_names(bound, {name for name in supplied if not name.startswith("\0")})
    bound.update(supplied)
    cache = path_functions.helper_results if isinstance(path_functions, PathFunctionTable) else {}
    cache_key = (id(function), tuple(sorted(bound.items())))
    if cache_key in cache:
        result = cache[cache_key]
        return _HelperReturn(
            result.pattern, result.unbounded or uncertain, None if uncertain else result.constant
        )
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
    constant = (
        next(iter(scanner.return_constants))
        if not fallthrough and len(scanner.return_constants) == 1
        else None
    )
    summary = _HelperReturn(result, scanner.unbounded_return, constant)
    cache[cache_key] = summary
    return _HelperReturn(
        summary.pattern, summary.unbounded or uncertain, None if uncertain else summary.constant
    )


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
    node = _evaluated_expression(node, values)
    if node is None or depth > 12:
        return False
    if isinstance(node, ast.NamedExpr):
        return _is_path_valued_expr(node.value, values, path, path_functions, depth=depth + 1)
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
            _function_name(node, values), path, _lexical_scope(values), _import_aliases(values)
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
        path_functions.resolve(
            _function_name(node, values),
            path,
            _lexical_scope(values),
            _import_aliases(values),
            retain_uncertain=True,
        )
        if isinstance(path_functions, PathFunctionTable)
        else (path_functions.get(name) or path_functions.get(name.rsplit(".", 1)[-1]))
    )
    return bool(function and function.returns_path)


def _iter_python_sources(
    repo_root: Path, *, tests_only: bool = False, source_gaps: list[SourceGap] | None = None
) -> list[Path]:
    files: set[Path] = set()

    def unread_directory(exc: OSError) -> None:
        if source_gaps is None:
            return
        failed = Path(exc.filename) if exc.filename else repo_root
        # `os.walk` does not catch what its `onerror` callback raises, so a callback that can
        # raise defeats its own purpose: this one exists to RECORD an unreadable directory, and
        # `relative_to` raises `ValueError` for any path the OS reports from outside the root
        # (review finding, gemini, 2026-09-07). Nothing here promises the error's filename is
        # under the tree being walked — that is a fact about the OS's report, not about our
        # arguments — so the gap is recorded under the absolute path when it cannot be relative.
        # A failure path that fails is worse than the gap it was written to describe.
        try:
            recorded = failed.relative_to(repo_root)
        except ValueError:
            recorded = failed
        source_gaps.append(SourceGap(recorded, "read", type(exc).__name__))

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
        and pattern not in {"*", ".", "~", _HOME_ROOT}
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


def _mode_effect(call: ast.Call, position: int) -> str | None:
    """Read/write from a mode argument at ``position`` (or ``mode=``), as tarfile.open and
    zipfile.ZipFile take it; ``_open_effect`` reads Path.open's first argument instead."""
    mode_node: ast.expr | None = call.args[position] if len(call.args) > position else None
    for keyword in call.keywords:
        if keyword.arg == "mode":
            mode_node = keyword.value
    if any(isinstance(arg, ast.Starred) for arg in call.args[: position + 1]) or any(
        keyword.arg is None for keyword in call.keywords
    ):
        return None
    if mode_node is not None and not (
        isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str)
    ):
        return None
    mode = mode_node.value if mode_node is not None else "r"
    return "write" if isinstance(mode, str) and any(flag in mode for flag in "wax") else "read"


def _open_effect(call: ast.Call, *, path_method: bool) -> str | None:
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
    action: str | None,
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
    bounded = action is not None and not _has_unbounded_format(
        expression, values, path, repo_root, path_functions
    )
    # Unknown modes retain a possible literal read as uncertainty, never a certified access.
    action = action or "read"
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
        # Keep a literal relative '~' distinct from the symbolic home root in both
        # human-readable paths and glob matching, without guessing a home layout.
        if pattern == "~" or pattern.startswith("~/"):
            pattern = "./" + pattern
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
    raw_name = _function_name(call, values)
    name = (
        path_functions.canonical_name(
            raw_name, path, _lexical_scope(values), _import_aliases(values)
        )
        if isinstance(path_functions, PathFunctionTable)
        else raw_name
    )
    # API labels use the qualified spelling; helper resolution above retains its identity.
    name = name.partition("@")[0]
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
        # Descriptor identity is typed evidence; a numeric filename is still a path.
        if not path_method:
            known, value = _constant_value(expression, values, path, path_functions)
            if not known:
                known, value = _returned_constant(
                    expression, path, values, path_functions, repo_root=repo_root
                )
            if known and isinstance(value, int):
                expression = None
        # A custom `opener` receives the path and returns a descriptor of its own choosing, so
        # the literal in the call is not evidence of what was written. Same for `**` unpacking,
        # which can supply `opener` without naming it here.
        if expression is not None and (
            any(keyword.arg == "opener" for keyword in call.keywords)
            or any(keyword.arg is None for keyword in call.keywords)
        ):
            expression = None
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
        # `os.rename`/`os.replace` accept `src_dir_fd` and `dst_dir_fd`. When either is
        # supplied, that operand is interpreted relative to the open directory descriptor —
        # not to the working directory this scanner resolves against — so the literal it
        # carries names a different file than the one written. The descriptor's directory is
        # established at a call this expression does not carry, so the operand is withheld
        # and its access stays unresolved rather than certifying a wrong target.
        # Both are keyword-only in `os.rename`/`os.replace`, so a keyword scan sees them when
        # they are named. `**` unpacking is the case a name scan cannot see: the mapping may
        # carry either descriptor and this call site does not say. An undetermined keyword set
        # is not an absent one, so both operands are withheld rather than certified.
        unpacked_keywords = any(keyword.arg is None for keyword in call.keywords)
        supplied_fds = {
            keyword.arg for keyword in call.keywords if keyword.arg in {"src_dir_fd", "dst_dir_fd"}
        }
        src_fd = unpacked_keywords or "src_dir_fd" in supplied_fds
        dst_fd = unpacked_keywords or "dst_dir_fd" in supplied_fds
        _record_access(
            accesses,
            unresolved,
            action="read",
            expression=None if src_fd else _call_argument(call, 0, "src"),
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
            expression=None if dst_fd else _call_argument(call, 1, "dst"),
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
                and not any(isinstance(item, ast.Starred) for item in statement.value.elts)
                else [None] * len(target.elts)
            )
            starred = [i for i, item in enumerate(target.elts) if isinstance(item, ast.Starred)]
            if (
                len(starred) == 1
                and isinstance(statement.value, (ast.Tuple, ast.List))
                and not any(isinstance(item, ast.Starred) for item in statement.value.elts)
                and len(statement.value.elts) >= len(target.elts) - 1
            ):
                # The captured list is unresolved as a path; its fixed siblings still bind.
                index = starred[0]
                tail = len(target.elts) - index - 1
                components = [
                    *statement.value.elts[:index],
                    None,
                    *(statement.value.elts[-tail:] if tail else []),
                ]
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
        known, constant = _constant_value(statement.value, values, path, path_functions)
        if not known:
            # `fd = descriptor()` kept the helper's resolved TEXT and dropped its type, so the
            # later `open(fd, 'w')` saw a plain name and certified a file called `True` (review
            # finding, codex, 2026-09-07 — my previous round covered the direct call and stopped
            # at the assignment beside it). The typed evidence travels with the binding now.
            known, constant = _returned_constant(
                statement.value, path, values, path_functions, repo_root=repo_root
            )
        if known:
            assigned[constant_key] = json.dumps(constant)
        format_key = f"{_UNRESOLVED_FORMAT_PREFIX}{target.id}"
        assigned.pop(format_key, None)
        if _has_unbounded_format(statement.value, values, path, repo_root, path_functions):
            assigned[format_key] = "1"
        _set_path_value(assigned, target.id, is_path)
        _set_import_alias(assigned, target.id, None)
        alias_expression = _evaluated_expression(statement.value, values)
        if isinstance(alias_expression, (ast.Name, ast.Attribute)) and isinstance(
            path_functions, PathFunctionTable
        ):
            aliased = path_functions.resolve(
                _dotted_name(alias_expression) or "",
                path,
                _lexical_scope(values),
                _import_aliases(values),
            )
            if aliased is not None:
                _set_import_alias(
                    assigned,
                    target.id,
                    _definition_identity(
                        f"{_module_name(aliased.path)}.{aliased.lexical_prefixes[0]}", aliased.node
                    ),
                )
        _clear_value_alternatives(assigned, target.id)
        closure_origins = _unresolved_expression_origins(statement.value, values)
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


def _scope_outer_mutations(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    *,
    stores_only: bool = True,
) -> tuple[set[str], set[str]]:
    """Names a callee may store outside its local frame; nested bodies run separately."""
    globals_: set[str] = set()
    nonlocals: set[str] = set()
    stores: set[str] = set()
    namespace_stores: set[str] = set()
    pending = list(node.body)
    while pending:
        item = pending.pop()
        if isinstance(item, ast.Global):
            globals_.update(item.names)
        elif isinstance(item, ast.Nonlocal):
            nonlocals.update(item.names)
        elif isinstance(item, ast.ClassDef):
            stores.add(item.name)
            if stores_only:
                class_globals, class_nonlocals = _scope_outer_mutations(item)
                namespace_stores.update(class_globals)
                stores.update(class_nonlocals)
                if isinstance(node, ast.ClassDef):
                    nonlocals.update(class_nonlocals)
            continue
        elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stores.add(item.name)
            continue
        elif isinstance(item, ast.Lambda):
            continue
        elif isinstance(item, (ast.Import, ast.ImportFrom)):
            stores.update(alias.asname or alias.name.split(".")[0] for alias in item.names)
        elif isinstance(getattr(item, "ctx", None), (ast.Store, ast.Del)):
            stores.update(_target_names(item))
            if (
                isinstance(item, ast.Subscript)
                and isinstance(item.value, ast.Call)
                and _function_name(item.value) == "globals"
            ):
                namespace_stores.add(
                    item.slice.value
                    if isinstance(item.slice, ast.Constant) and isinstance(item.slice.value, str)
                    else "*"
                )
        pending.extend(ast.iter_child_nodes(item))
    if not stores_only:
        return globals_, nonlocals
    return (globals_ & stores) | namespace_stores, nonlocals & stores


def _scope_initial_values(
    node: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
    module_values: dict[str, str],
    path: Path,
    repo_root: Path,
    path_functions: dict[str, PathFunction],
    lexical_prefixes: tuple[str, ...],
    invocation_globals: dict[str, str] | None = None,
) -> dict[str, str]:
    if isinstance(node, ast.Module):
        # Module scope executes top to bottom: a read before an assignment sees nothing.
        return {}
    nested = len(lexical_prefixes) > 1
    if invocation_globals is None:
        invocation_globals = (
            _decode_call_globals(module_values[_CALL_GLOBALS_KEY], path_functions)
            if nested and _CALL_GLOBALS_KEY in module_values
            else module_values
        )
    values = dict(invocation_globals)
    cells: set[str] = set()
    if nested:
        cells.update(json.loads(module_values.get(_CALL_LOCALS_KEY, "[]")))
        cells.update(json.loads(module_values.get(_CALL_CELLS_KEY, "[]")))
        pending = [node.body] if isinstance(node, ast.Lambda) else list(node.body)
        while pending:
            item = pending.pop()
            if isinstance(item, ast.Global):
                cells.difference_update(item.names)
            elif not isinstance(
                item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
            ):
                pending.extend(ast.iter_child_nodes(item))
        # A global snapshot must not overwrite a stable closure cell with the same name.
        # Explicit global declarations bypass cells, including inside path helpers.
        for name in cells:
            for key in _binding_keys(name):
                values.pop(key, None)
                if key in module_values:
                    values[key] = module_values[key]
    values[_CALL_CELLS_KEY] = json.dumps(sorted(cells))
    if _HELPER_STACK_KEY in module_values:
        values[_HELPER_STACK_KEY] = module_values[_HELPER_STACK_KEY]
    values[_CALL_GLOBALS_KEY] = _encode_call_globals(
        {
            key: value
            for key, value in invocation_globals.items()
            if key not in {_CALL_GLOBALS_KEY, _CALL_LOCALS_KEY, _CALL_CELLS_KEY, _LEXICAL_SCOPE_KEY}
            and _EXPRESSION_VALUE_PREFIX not in key
            and _LOOP_VALUE_PREFIX not in key
        },
        path_functions,
    )
    _set_lexical_scope(values, lexical_prefixes)
    if isinstance(path_functions, PathFunctionTable):
        if node not in path_functions.scope_locals:
            path_functions.scope_locals[node] = _scope_local_names(node)
        local_names = path_functions.scope_locals[node]
    else:
        local_names = _scope_local_names(node)
    for name in local_names:
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
    values[_CALL_LOCALS_KEY] = json.dumps(sorted(local_names | {arg.arg for arg in parameters}))
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
_MAX_BINDING_STATES = 16
_MAX_BINDING_ROUNDS = 12


def _fork(states: list[dict[str, str]]) -> list[dict[str, str]]:
    return [dict(state) for state in states]


_ConstantResolver = Callable[[ast.Call], tuple[bool, object]]


def _literal_operand(
    node: ast.expr, resolve: _ConstantResolver | None = None
) -> tuple[bool, object]:
    """``(True, value)`` when the operand is a compile-time constant, else ``(False, None)``.

    `ast.literal_eval` is NOT a sufficient test on its own. It special-cases ``set()`` —
    the empty set has no literal spelling — so it accepts a *call* and returns a falsy
    value for it. A module that shadows the name then decides the branch differently
    from this scanner (codex, at `c01c645d2`)::

        def set(): return 'nonempty'
        x = 'artifacts/wrong.json'
        set() and (x := 'artifacts/actual.json')
        open(x, 'w')

    Python calls the shadow, gets a truthy string, runs the assignment and writes
    `actual.json`; the scanner read `set()` as an empty set, took the short circuit and
    certified `wrong.json` — a file never written — while suppressing its orphan reader.

    So a call is refused outright rather than evaluated. A name resolved from the
    enclosing module could be anything at all, and "constant" here has to mean *no
    binding can change it*, not merely "literal_eval accepted it".
    """
    if isinstance(node, ast.Constant):
        return True, node.value
    if any(isinstance(item, ast.Call) for item in ast.walk(node)):
        # A call is still refused BY DEFAULT, and the paragraph above is why. `resolve` is the
        # one exception, supplied only by the walker, which alone holds the binding table this
        # question needs: a call to a UNIQUELY BOUND helper whose return is a constant is not
        # "a name that could be anything at all" — it is a value the existing summary machinery
        # already computes for path resolution. Nothing is evaluated and no source is executed.
        #
        # Restricted to a node that IS a call, never one that merely contains one: the summary
        # answers "what does this helper return", not "what does this expression evaluate to".
        if resolve is not None and isinstance(node, ast.Call):
            return resolve(node)
        return False, None
    if isinstance(node, ast.Compare):
        # **A comparison is a constant when its operands are.** `literal_eval` refuses an
        # `ast.Compare` outright, so every caller that asked this function "is this decided" got
        # False for `1 == 2` — and the module has carried `_comparison_outcome` for exactly this
        # question since the chain repair, consulted by the chain handler and by ONE filter.
        #
        # Measured cost of that, thirteen shapes against a runtime oracle: `(1 == 2) and open()`,
        # `(1 == 1) or open()`, `open() if 1 == 2 else n`, `(1 < 0 < 5) and open()` and
        # `if 1 == 2:` each certified a writer Python never calls. Folding it HERE rather than at
        # each of those sites is the point — the sites had drifted to three different capability
        # levels precisely because the rule lived beside them instead of under them.
        #
        # After the call refusal, so `f() == 2` is still refused and the shadowed-`set()` case is
        # untouched: `_comparison_outcome` resolves its operands without the resolver.
        outcome = _decided_comparison(node)
        if outcome is not None:
            return True, outcome
        return False, None
    try:
        return True, ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False, None


#: The value types this scanner can enumerate as a loop or comprehension source. Deliberately
#: narrow: membership is what licenses counting the elements and binding a single one.
_ENUMERABLE_TYPES = (list, tuple, set, frozenset, dict, str, bytes)

#: A source this scanner can enumerate: element count and single-element binding are exact.
SOURCE_ENUMERABLE = "enumerable"
#: A source Python CANNOT iterate. `iter()` raises TypeError, so the body runs zero times —
#: a decided negative, on the same footing as a constant-empty source, not an uncertainty.
SOURCE_NOT_ITERABLE = "not-iterable"
#: Either unresolved, or a value that iterates in ways this scanner does not model.
SOURCE_UNDECIDED = "undecided"


def _iteration_domain(known: bool, constant: object) -> str:
    """Which of the THREE iteration cases a resolved loop/comprehension source falls in.

    `known` answers "can this scanner see the value". It does not answer "can Python iterate
    it", and the comprehension handler spent one for the other: every value it could resolve
    was allowed to certify the body, so `[open(...) for x in None]` — and the same with `True`,
    `0`, `3`, `1.25` and `2j`, inline, via a name, and behind an eager `any()` — produced a
    bounded writer for a file Python never opens, because `iter()` raises TypeError before the
    first element (review finding, root, at `120d38d9b`, 36 counterexamples, runtime oracle
    recording zero opens in every one).

    That is the recurring collapse in this file, in a new place: a domain with three cases
    forced through one boolean. `sized` said "I can count this", the code read its False as
    "I cannot count this *yet*", and the fall-through certified. The three cases are:

    * `SOURCE_ENUMERABLE` — decide from the value: empty, single, or several.
    * `SOURCE_NOT_ITERABLE` — the body cannot run. **Proven, not assumed**: this is the same
      kind of answer as a constant-empty source, so it costs no uncertainty.
    * `SOURCE_UNDECIDED` — unresolved, or iterable in a way not modelled here. The caller
      decides what withholding means at its own boundary.

    Iterability is read off the type's PROTOCOL, the way `iter()` itself decides, rather than
    from a list of non-iterable types. An enumeration of what is excluded is only ever as
    complete as the day it was written — the same reason `_literal_binding_is_unchallenged`
    inverted its escape routes — and a value type this predicate has never seen must land in
    `SOURCE_UNDECIDED`, never in a certifying default.

    Nothing is evaluated here: the constant is already a value, and the lookup is on its type.
    """
    if not known:
        return SOURCE_UNDECIDED
    if isinstance(constant, _ENUMERABLE_TYPES):
        return SOURCE_ENUMERABLE
    source_type = type(constant)
    if hasattr(source_type, "__iter__") or hasattr(source_type, "__getitem__"):
        # Iterable, but outside what this scanner enumerates. Not a negative.
        return SOURCE_UNDECIDED
    return SOURCE_NOT_ITERABLE


def _boolop_stops_after(
    op: ast.boolop, value: ast.expr, resolve: _ConstantResolver | None = None
) -> bool | None:
    """Does this operand decide an ``and``/``or``? ``True`` stops, ``False`` continues.

    ``None`` means only the runtime knows, and the analysis keeps both continuations as
    disjunctive states.

    That is a statement about this ANALYSIS, not about the program. An earlier version of this
    docstring said an unknown means both continuations are "genuinely reachable"; that was
    unsupported, and root corrected it at `813b0857e` — *admitting both possibilities is not
    proof both executions exist*, and a statically found write site is not a witnessed runtime
    producer either. The distinction is kept explicit here because collapsing it is what makes
    a scanner start certifying files nothing ever writes.

    Deciding is reserved for a compile-time constant, where one alternative is not merely
    unlikely but impossible — or, when `resolve` is supplied, for a call to a uniquely bound
    helper whose constant return the existing summary machinery already computes. That is the
    same standard, not a weaker one: a helper with one binding and a constant return has one
    value, and refusing to read it is what left the shadowed-call case certifying a phantom.
    """
    known, constant = _literal_operand(value, resolve)
    if not known:
        return None
    return not constant if isinstance(op, ast.And) else bool(constant)


def _comparison_outcome(left: ast.expr, op: ast.cmpop, right: ast.expr) -> bool | None:
    """``left op right`` decided from constants alone, or ``None`` when only runtime knows.

    A chain stops on the first FALSE comparison, so a decided ``False`` ends it and a decided
    ``True`` means it certainly continues — and the "stopped here" alternative is then just as
    unreachable as the "kept going" one is after a decided false.
    """
    comparison = _CONSTANT_COMPARISONS.get(type(op))
    if comparison is None:
        return None
    left_known, left_value = _literal_operand(left)
    right_known, right_value = _literal_operand(right)
    if not (left_known and right_known):
        return None
    try:
        return bool(comparison(left_value, right_value))
    except TypeError:
        # An ill-typed comparison raises at runtime; it does not quietly take a branch.
        return None


def _decided_comparison(node: ast.Compare) -> bool | None:
    """A whole comparison, chain included, decided from constants alone — or ``None``.

    A chain evaluates left to right and stops at its first false link, so the links are read in
    that order and the FIRST one that is not a decided true ends the reading:

    * an undecided link ends it as ``None``. Nothing after it is reached in any decided way, and
      — this is the part that makes it more than caution — ``_comparison_outcome`` returns
      ``None`` for an ill-typed comparison as well as for an unresolvable one. An ill-typed link
      RAISES, so the chain has no truth value at all, and a later decided-false link does not
      supply one.
    * a decided false link ends it as ``False``. The chain genuinely stops there, so whatever
      follows — including an unresolvable operand — is never evaluated. ``2 < 1 < missing`` is
      False.
    * every link a decided true ends it as ``True``.

    **The first version of this function stated exactly that rule and did not implement it.** It
    tracked the undecided case in a variable and then returned ``False`` unconditionally on a
    later false link, so ``missing < 1 < 0`` and ``None < 1 < 0`` came back False against their
    own docstring (review finding, root, at `fb590f991`, isolated direct-helper test, eight
    orders). Same ordering fault as the anchor read earlier today: once one side can raise, the
    order carries the whole meaning — and the same comment-names-its-own-defect shape, since the
    paragraph above the loop said what the loop should have done.
    """
    operands = [node.left, *node.comparators]
    for index, op in enumerate(node.ops):
        link = _comparison_outcome(operands[index], op, operands[index + 1])
        if link is None:
            return None
        if link is False:
            return False
    return True


_CONSTANT_COMPARISONS: dict[type, Callable[[object, object], object]] = {
    ast.Lt: operator_module.lt,
    ast.LtE: operator_module.le,
    ast.Gt: operator_module.gt,
    ast.GtE: operator_module.ge,
    ast.Eq: operator_module.eq,
    ast.NotEq: operator_module.ne,
}


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
        if name.startswith(_MODULE_EFFECT_PREFIX) and "1" in alternatives:
            collapsed[name] = "1"
            continue
        if name.startswith(_UNRESOLVED_FORMAT_PREFIX) and any(alternatives):
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


#: Builtins that DRIVE a generator argument to completion (or at least into its body) during the
#: call. Passing a generator to one of these is proof its body runs; passing it anywhere else is
#: not. The lazy builtins are deliberately absent — `iter`, `enumerate`, `zip`, `map`, `filter`
#: and `reversed` all return without touching the body — and so is every non-builtin, because a
#: callee that merely stores its argument runs nothing.
#:
#: The earlier revision treated EVERY call argument as consuming, on the reasoning that the
#: alternative fabricates an orphan for `list(open(...) for _ in [1])`. `list` is on this table,
#: so that case keeps its answer; what the over-approximation also did was certify the body of a
#: generator handed to a non-consuming helper, absorbing a real orphan reader — the same mistake
#: in the opposite direction (root readback, 2026-09-08, two reader twins).
_GENERATOR_CONSUMING_BUILTINS = frozenset(
    {"all", "any", "dict", "frozenset", "list", "max", "min", "set", "sorted", "sum", "tuple"}
)


def _target_is_read_by(comprehension: ast.expr, generator: ast.comprehension) -> bool:
    """Whether the comprehension's body or filters READ this generator's target name.

    Withholding on a multi-element literal is right only where the elements can change what
    runs. `[open(...) for _ in [1, 2]]` never consults `_`, so certifying it is still correct;
    `[x or open(...) for x in [True, True]]` consults `x` in a position that decides whether the
    call happens at all. Checking for the read is what keeps the withholding from becoming a
    blanket over every multi-element source.
    """
    if not isinstance(generator.target, ast.Name):
        return True  # a tuple or starred target is not analysed here; assume it matters
    name = generator.target.id
    # **Every clause AFTER this generator, not only its own filters and the final body.** The
    # first version checked `generator.ifs` and the element, and omitted the iterables and
    # filters of SUBSEQUENT generators — so `[y for x in [True, True] for y in [x or open(...)]]`
    # left the outer target unknown while the next iterable certified its conditional call
    # (review finding, codex, at `187bbe1f2`). A dependency check that stops at its own clause
    # is not a dependency check; the target is in scope for everything downstream of it.
    bodies: list[ast.expr] = list(generator.ifs)
    following = comprehension.generators[comprehension.generators.index(generator) + 1 :]
    for later in following:
        bodies.append(later.iter)
        bodies.extend(later.ifs)
    if isinstance(comprehension, ast.DictComp):
        bodies.extend((comprehension.key, comprehension.value))
    elif isinstance(
        comprehension, (ast.ListComp, ast.SetComp, ast.GeneratorExp)
    ):  # pragma: no branch
        bodies.append(comprehension.elt)
    return any(
        isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load)
        for body in bodies
        for node in ast.walk(body)
    )


def _comparison_operands(test: ast.expr | None) -> list[ast.expr]:
    """The operands of a test that is a comparison, or nothing. One level, never recursive."""
    if not isinstance(test, ast.Compare):
        return []
    return [test.left, *test.comparators]


def _literal_binding_is_unchallenged(name: str, scope: ast.AST | None) -> bool:
    """Whether ``name`` is bound exactly once in ``scope`` and nothing there can have changed it.

    **Conservative by construction: True only when it can be shown.** The caller spends a True as
    "this name still denotes that literal", and a wrong True certifies a writer for a file
    nothing writes — which is what the stateful version did in ten measured ways.

    Anything that could rebind the name, mutate the object it denotes, or hand it to something
    that might, disqualifies it: a second ``Store`` or any ``Del`` — including one in a branch
    this scan does not take — an augmented assignment, an attribute or subscript reached through
    it, and **any read at all other than the comprehension iterables it is being consulted for**.

    That last clause is the one that matters and it was wrong on the first attempt. The prose
    said "hands it to something that might change it" while the predicate checked only bare-name
    `Assign`/`AnnAssign` values, so `empty(items)` with a callee that clears it, and a container
    alias like `holder = [items]`, both slipped past (source-review concern, coordinator, on the
    uncommitted repair). **Enumerating the escape routes is the losing game** — a call, a
    container, a starred argument, a default, a yield, a return — so the rule is inverted:
    a read is safe only where this predicate can see the whole use, which is an iteration source
    — a comprehension clause's ``iter``, or a ``for`` statement's. Everything else is an escape
    whether or not it is on anyone's list.

    Note which direction that list runs. Enumerating ESCAPES is the losing game because a route
    left off certifies. Enumerating provably-whole USES is the inverse: a form left off — a
    ``while``, an unpacking, a ``yield from``, an ``in`` test — costs a refusal, never a wrong
    certification. The ``for`` statement was left off at first, and the cost was exactly that
    shape: `items = 0` followed by `for x in items:` kept the loop body certified, because the
    binding never became a literal for the non-iterable check to read (measured, not inferred).

    Conservative by construction: True only where it can be shown, because the caller spends a
    True as "this name still denotes that literal" and a wrong True certifies a phantom writer.
    """
    if scope is None:
        return False
    safe_reads = {
        id(source)
        for node in ast.walk(scope)
        for source in (
            [generator.iter for generator in node.generators]
            if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
            else [node.iter]
            if isinstance(node, (ast.For, ast.AsyncFor))
            # A branch or loop TEST reads the name for truthiness and hands the object nowhere.
            # Added for the same reason the `for` source was: `x = (1 == 2)` followed by `if x:`
            # kept the guarded writer certified, because the binding never became a literal for
            # the condition check to read.
            #
            # **And the operands of a test that IS a comparison, because the read is nested one
            # level down.** Registering only `node.test` matched `if x:` and missed
            # `if v < 1 < 2:` — the `Name` there sits inside the `Compare`, so the read was never
            # on the safe list and the binding was disqualified by its own guard. Comparison
            # reads an operand's value and hands the object nowhere, which is the same
            # whole-use argument; nothing deeper than one comparison is admitted, so
            # `if f(x):` and `if x.y:` still disqualify.
            else [node.test, *_comparison_operands(node.test)]
            if isinstance(node, (ast.If, ast.While, ast.IfExp))
            else []
        )
        if isinstance(source, ast.Name) and source.id == name
    }
    stores = 0
    for node in ast.walk(scope):
        if isinstance(node, ast.Name) and node.id == name:
            if isinstance(node.ctx, ast.Store):
                stores += 1
                if stores > 1:
                    return False
            elif isinstance(node.ctx, ast.Del):
                return False
            elif id(node) not in safe_reads:
                # Any other read can hand the object somewhere this predicate cannot follow.
                return False
        elif isinstance(node, ast.AugAssign):
            target = node.target
            if isinstance(target, ast.Name) and target.id == name:
                return False
            if isinstance(target, (ast.Attribute, ast.Subscript)):
                value = target.value
                if isinstance(value, ast.Name) and value.id == name:
                    return False
    return stores == 1


def _call_consumes_generator_argument(
    func: ast.expr,
    values: dict[str, str],
    path: Path | None,
    path_functions: object | None,
) -> bool:
    """Whether passing a generator to this callable is PROOF that its body runs.

    **A name match is not proof, and an attribute match is not even a name match.** The first
    revision of this predicate returned True for any `ast.Name` in the table and for any
    attribute called `join`/`extend`/`update`/`writelines`. Root measured both against Python:
    a locally shadowed `def list(g): return g` writes nothing while the scanner certified a
    writer, and an arbitrary `Holder.join` that returns its argument without iterating did the
    same in eight more. The comment beside the attribute table admitted the receiver was
    unknown — and the predicate's result was then used as PROOF. Stating a limit in prose while
    the code spends the value anyway is the same defect as not knowing the limit.

    It is also the SECOND time this file has folded on a bare name: `_builtin_str_call` carries
    the same correction for `str`, made a round earlier, and its resolver is reused here rather
    than re-derived. A defect repaired in one channel is a defect to look for in the others.

    So: builtins only, and only where the name is not shadowed; the one attribute kept is a
    `join` on a string LITERAL, where the receiver's type is established by the source rather
    than assumed. Everything unproven falls through to the deferred branch, which already
    records a named uncertainty rather than certifying — the direction that costs a wildcard
    instead of a phantom.

    Without a table the answer is "not established" and nothing is certified.
    """

    if isinstance(func, ast.Attribute):
        # The ONE attribute case where the receiver's type is established rather than assumed:
        # a string literal. `''.join(...)` really does drive the generator, and knowing that
        # costs nothing because the receiver is right there in the source. Any other receiver —
        # a name, an attribute, a call — is unknown, and `Holder.join` returning its argument
        # without iterating is a real shape root measured, so nothing else qualifies.
        return (
            func.attr == "join"
            and isinstance(func.value, ast.Constant)
            and isinstance(func.value.value, str)
        )
    if not isinstance(func, ast.Name) or func.id not in _GENERATOR_CONSUMING_BUILTINS:
        return False
    if not isinstance(path_functions, PathFunctionTable) or path is None:
        return False
    # **`shadow is None` means NOT ESTABLISHED, and spending it as proof is the same collapse
    # this predicate was written to repair.** The table answers about function DEFINITIONS, so
    # it says nothing about `from builtins import iter as list` or a bare `list = iter` — both
    # of which certified a phantom writer while Python iterated nothing (review finding, codex,
    # at `4d13c27c8`). A rebinding of any kind means the name is not the builtin, whether or not
    # this scanner can say what it is instead.
    if func.id in _import_aliases(values) or func.id in values:
        return False
    shadow = path_functions.resolve(
        func.id, path, _lexical_scope(values), _import_aliases(values), retain_uncertain=True
    )
    return shadow is None


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
        scope_node: ast.AST | None = None,
    ) -> None:
        self.path = path
        self.repo_root = repo_root
        self.path_functions = path_functions
        self.accesses = accesses
        self.unresolved = unresolved
        self.unrecognised = unrecognised
        self.context_family = context_family
        self.nested_scope_values = nested_scope_values
        self.scope_node = scope_node
        #: Every invocation state this walk handed to a callee, with the access-list position it
        #: was recorded at. `_demote_from` uses the SAME position predicate it already applies to
        #: the access list, so the question "is this region reached" keeps one answer at one site
        #: rather than a second copy beside each of the four callers.
        self.recorded_bindings: list[tuple[int, ast.AST, tuple]] = []
        #: Indices into `recorded_bindings` that fell inside a region later found unreached. Held
        #: as indices rather than keys because two call sites can supply the SAME state and only
        #: one of them be unreached; collapsing them would withdraw the reached one's writer.
        self.demoted_bindings: set[int] = set()
        #: GeneratorExp nodes seen in a CONSUMING position. A generator expression's body does
        #: not run when it is created — only when something iterates it — so certifying its
        #: effects at the definition site invented a producer for a file nothing writes
        #: (review finding, codex). Consumption is a property of the PARENT, which is why it is
        #: recorded by the handlers that hold one rather than inferred inside the body handler.
        self.consumed_generators: set[int] = set()
        #: Comprehension targets bound to a literal element, for reachability INSIDE the body.
        #: A proven consumer establishes that the body runs; it says nothing about which
        #: expressions in it are reached, and `any(x or open(...) for x in [True])` writes
        #: nothing because `x` is True and the `or` never evaluates its right operand (root
        #: readback, 2026-09-08). `_literal_operand` reads literals and calls, never the value
        #: map, so the binding has to reach the operator handlers as a node substitution.
        self.literal_names: dict[str, ast.expr] = {}

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
            function = None
            if isinstance(self.path_functions, PathFunctionTable):
                function = self.path_functions.resolve(
                    _function_name(call, state),
                    self.path,
                    _lexical_scope(state),
                    _import_aliases(state),
                )
                if (
                    function is not None
                    and function.node is not None
                    and self.scope_node is not None
                ):
                    supplied = _call_parameter_values(
                        function, call, state, self.path, self.repo_root, self.path_functions
                    )
                    supplied[_CALL_GLOBALS_KEY] = _encode_call_globals(
                        _call_global_values(function, state, self.path, self.path_functions),
                        self.path_functions,
                    )
                    self.path_functions.record_calls(function.node, [supplied])
                    self.recorded_bindings.append(
                        (len(self.accesses), function.node, tuple(sorted(supplied.items())))
                    )
            local_unresolved = [0]
            local_unrecognised: Counter[str] = Counter()
            before = len(call_accesses)
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
            if function is not None and function.node is not None:
                self._invalidate_callee_mutations(function, state)
            elif isinstance(self.path_functions, PathFunctionTable):
                name = self.path_functions.canonical_name(
                    _function_name(call, state),
                    self.path,
                    _lexical_scope(state),
                    _import_aliases(state),
                )
                # These primitives are already modelled as paths, scalars, or file accesses.
                # An arbitrary unresolved helper must not acquire an empty effect summary.
                known = name in _PATH_CONSTRUCTORS | {
                    "str",
                    "int",
                    "float",
                    "bool",
                    "len",
                    "list",
                    "tuple",
                    "set",
                    "dict",
                    "range",
                    "enumerate",
                    "zip",
                    "sorted",
                    "globals",
                    "Path.home",
                    "pathlib.Path.home",
                    "os.getenv",
                    "os.environ.get",
                }
                path_method = (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr
                    in {"expanduser", "absolute", "resolve", "with_suffix", "with_name"}
                    and _is_path_valued_expr(call.func.value, state, self.path, self.path_functions)
                )
                modelled_access = not local_unrecognised and (
                    local_unresolved[0]
                    or len(call_accesses) > before
                    and all(access.modelled for access in call_accesses[before:])
                )
                if not (known or path_method or modelled_access):
                    if self.scope_node is not None:
                        self.path_functions.unknown_effects[self.scope_node] = (
                            f"unresolved call target {_function_name(call) or '<dynamic>'}"
                        )
                    self._invalidate_uncertain_bindings(state)
                    # Retain literal components surrounding an unknown result, with the
                    # same uncertainty flag that assignments and access sites already carry.
                    self._mark_untracked_result(call, state)
        self.accesses.extend(dict.fromkeys(call_accesses))
        self.unresolved[0] += unresolved_slots
        for name in flagged:
            self.unrecognised[name] += 1

    def _mark_untracked_result(self, call: ast.Call, state: dict[str, str]) -> None:
        result_name = _expression_value_name(call)
        # An obsolete helper may still expose a literal reader pattern. Its return is
        # evidence only: the uncertainty flag must accompany every retained component.
        result, unbounded = _resolve_path_helper(
            call, state, self.path, self.repo_root, self.path_functions
        )
        is_path = unbounded and _is_path_valued_expr(call, state, self.path, self.path_functions)
        state[result_name] = result if unbounded and result is not None else "*"
        _set_path_value(state, result_name, is_path)
        state[f"{_UNRESOLVED_FORMAT_PREFIX}{result_name}"] = "1"

    def _invalidate_callee_mutations(self, function: PathFunction, state: dict[str, str]) -> None:
        table = self.path_functions
        if not isinstance(table, PathFunctionTable):
            return
        if _CLASS_OUTER_KEY in state:
            outer = _decode_call_globals(state[_CLASS_OUTER_KEY], table)
            self._invalidate_callee_mutations(function, outer)
            state[_CLASS_OUTER_KEY] = _intern_binding_state(outer, table)
        if function.node not in table.scope_mutations:
            table.scope_mutations[function.node] = _scope_outer_mutations(function.node)
        effects = table.outer_effects.get(function.node, _OuterEffects())
        for owner in effects.owners | {function.node}:
            origin = table.functions_by_node[owner]
            self._invalidate_outer_bindings(origin, state, *table.scope_mutations[owner])
        if effects.unresolved:
            prefixes = _lexical_scope(state)
            captures: set[str] = set()
            for owner in effects.uncertain_owners | {function.node}:
                origin = table.functions_by_node.get(owner)
                if origin is not None and origin.path != self.path:
                    self._invalidate_outer_bindings(origin, state, {"*"}, set())
                if (
                    origin is None
                    or origin.path != self.path
                    or not prefixes
                    or prefixes[0] not in origin.lexical_prefixes[1:]
                ):
                    continue
                if effects.capped or effects.unresolved == "recursive outer effect cycle":
                    # Truncated summaries cannot certify which caller cells are untouched.
                    captures.update(json.loads(state.get(_CALL_LOCALS_KEY, "[]")))
                else:
                    if owner not in table.scope_captures:
                        table.scope_captures[owner] = {
                            item.id for item in ast.walk(owner) if isinstance(item, ast.Name)
                        } - (_scope_local_names(owner) | set(origin.params))
                    captures.update(table.scope_captures[owner])
            if not self._invalidate_uncertain_bindings(state, captures=captures):
                return
            site = (
                f"{self.path}:{function.node.lineno}: outer effects of "
                f"{function.path}:{function.lexical_prefixes[0]} UNRESOLVED ({effects.unresolved})"
            )
            table.unresolved_closures.add(site)
            if effects.capped:
                table.capped_expressions.add(site)

    def _invalidate_uncertain_bindings(
        self, state: dict[str, str], *, captures: set[str] | None = None
    ) -> bool:
        table = self.path_functions
        outer_changed = False
        if _CLASS_OUTER_KEY in state:
            outer = _decode_call_globals(state[_CLASS_OUTER_KEY], table)
            outer_changed = self._invalidate_uncertain_bindings(outer, captures=captures)
            state[_CLASS_OUTER_KEY] = _intern_binding_state(outer, table)
        locals_ = set(json.loads(state.get(_CALL_LOCALS_KEY, "[]"))) - (captures or set())
        inherited = _decode_call_globals(state.get(_CALL_GLOBALS_KEY), table)
        # Keep established API/import provenance. Unknown effects poison data globals
        # and captured cells, including globals hidden by the caller's own local names.
        names = {
            name
            for values in (state, inherited)
            for aliases in (_import_aliases(values),)
            for name in values
            if not name.startswith("\0")
            and not aliases.get(name)
            and (values is inherited or name not in locals_)
        }
        self._invalidate_effect_names(inherited, names)
        if _CALL_GLOBALS_KEY in state:
            state[_CALL_GLOBALS_KEY] = _encode_call_globals(inherited, table)
        self._invalidate_effect_names(state, names - locals_)
        return bool(names) or outer_changed

    @staticmethod
    def _invalidate_effect_names(values: dict[str, str], names: set[str]) -> None:
        # Flat validation bodies repeatedly encounter unknown APIs with identical
        # effects. An already poisoned binding needs no further stores or deletions.
        names = {
            name
            for name in names
            # __file__ denotes this scanned source in _resolve_path_expr, independently
            # of runtime globals. A visible source-relative helper keeps that identity.
            if name != "__file__" and values.get(f"{_UNRESOLVED_FORMAT_PREFIX}{name}") != "effect"
        }
        retained = {
            key: values[key]
            for name in names
            for key in (name, _path_value_key(name), f"{_VALUE_ALTERNATIVES_PREFIX}{name}")
            if key in values
        }
        _invalidate_names(values, names)
        values.update(retained)
        for name in names:
            # An effect withdraws certification, not the literal evidence of an access.
            # Callable aliases and scalar constants stay invalidated. The distinct flag
            # avoids re-invalidating identical states during effect-summary fixpoints.
            values[f"{_UNRESOLVED_FORMAT_PREFIX}{name}"] = "effect"

    def _invalidate_outer_bindings(
        self, function: PathFunction, state: dict[str, str], globals_: set[str], nonlocals: set[str]
    ) -> None:
        table = self.path_functions
        if function.path != self.path:
            for name in globals_ | nonlocals:
                state[f"{_MODULE_EFFECT_PREFIX}{function.path}\0{name}"] = "1"
            return
        if not globals_ and not nonlocals:
            return
        locals_ = set(json.loads(state.get(_CALL_LOCALS_KEY, "[]")))
        cells = set(json.loads(state.get(_CALL_CELLS_KEY, "[]")))
        if globals_:
            inherited = _decode_call_globals(state.get(_CALL_GLOBALS_KEY), table)
            names = (
                {name for name in inherited.keys() | state.keys() if not name.startswith("\0")}
                if "*" in globals_
                else globals_
            )
            self._invalidate_effect_names(inherited, names)
            if _CALL_GLOBALS_KEY in state:
                state[_CALL_GLOBALS_KEY] = _encode_call_globals(inherited, table)
            self._invalidate_effect_names(state, names - locals_ - cells)
        if nonlocals and len(function.lexical_prefixes) > 1:
            prefixes = _lexical_scope(state)
            module = _module_name(function.path)
            for name in nonlocals:
                # A nonlocal can skip several lexical frames. Locate its actual cell,
                # then check that the caller sees that same cell rather than a shadow.
                owners = []
                for candidates in (function.lexical_prefixes[1:], prefixes):
                    owner = None
                    for prefix in candidates:
                        enclosing = table.get(f"{module}.{prefix}")
                        if enclosing is None or enclosing.node is None:
                            continue
                        if enclosing.node not in table.scope_locals:
                            table.scope_locals[enclosing.node] = _scope_local_names(enclosing.node)
                        if name in table.scope_locals[enclosing.node] or name in enclosing.params:
                            owner = enclosing.node
                            break
                    owners.append(owner)
                if owners[0] is not None and owners[0] is owners[1]:
                    self._invalidate_effect_names(state, {name})

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

    def _scan_loop(
        self,
        statement: ast.For | ast.AsyncFor | ast.While,
        states: list[dict[str, str]],
        exception_states: list[dict[str, str]] | None,
        exit_states: list[dict[str, str]] | None,
    ) -> list[dict[str, str]]:
        if isinstance(statement, ast.While):
            # **This handler had NO constant-condition check at all** — not for a comparison, and
            # not for a plain literal either. `while False:`, `while 0:`, `while []:`,
            # `while None:`, `while 1 == 2:` and `while stop():` each certified their body while
            # Python entered none of them (measured, thirteen shapes). The `if` handler decided
            # literals and the comprehension filter decided everything; this one decided nothing,
            # which is the same one-question-many-sites drift the comparison folding repairs.
            #
            # FALSY ONLY. A constant-truthy condition is an infinite loop whose body does run and
            # after which nothing runs except through a `break` — modelling that is a separate
            # claim about termination, and `while True: ... break` is too common to guess at.
            # Narrowing here, nothing else.
            known, condition = self._resolved_constant(statement.test, states)
            if known and not condition:
                return self.scan_block(statement.orelse, states, exception_states, exit_states)
        if isinstance(statement, (ast.For, ast.AsyncFor)):
            # A source Python cannot iterate enters neither the body nor the `else`: `iter()`
            # raises before the first element. The comprehension boundary was repaired for this
            # first and this one had the identical defect — `for x in None:` certified a bounded
            # writer for a file the runtime oracle never opened, inline, through a name bound to
            # `0`, and through a helper returning `None`.
            #
            # **This is a decided negative and it only ever narrows**: an unresolved or merely
            # unmodelled source keeps scanning the body, because a statement loop over a value
            # this scanner cannot see is the ordinary case and refusing it would withhold nearly
            # every real writer. That asymmetry with the comprehension boundary — which does
            # withhold on unknown — is deliberate and is not what this repair changes.
            #
            # `async for` needs `__aiter__`, which is a DIFFERENT protocol — an object can define
            # it without `__iter__`, so failing the sync test does not in general imply failing
            # the async one. The scope of the claim here is only the values `_literal_operand`
            # can produce: `ast.literal_eval` results and constants, none of which define
            # `__aiter__`. Outside that set this branch says nothing, and it must not be read as
            # a statement about the object model (coordinator correction, at `605f1dd82`, where
            # this comment asserted the general implication).
            if self._resolved_iteration_source(statement.iter, states)[2] == SOURCE_NOT_ITERABLE:
                return states
        literal = isinstance(statement, (ast.For, ast.AsyncFor)) and isinstance(
            statement.iter, (ast.List, ast.Tuple, ast.Set)
        )
        capped = literal and len(statement.iter.elts) > _MAX_BINDING_STATES
        if capped and isinstance(self.path_functions, PathFunctionTable):
            self.path_functions.capped_expressions.add(
                f"{self.path}:{statement.lineno}: literal loop iteration cap UNRESOLVED"
            )
            self.unresolved[0] += 1
        exact = (
            literal
            and not capped
            and not isinstance(statement.iter, ast.Set)
            and not any(isinstance(value, ast.Starred) for value in statement.iter.elts)
        )
        iterations = statement.iter.elts if literal else [None]
        may_be_empty = not literal or not any(
            not isinstance(value, ast.Starred) for value in iterations
        )
        changed = {
            name
            for item in ast.walk(statement)
            if isinstance(getattr(item, "ctx", None), ast.Store)
            for name in _target_names(item)
        }
        looped = _fork(states)
        frozen_names: list[str] = []
        if exact:
            # The iterable's values are evaluated once, before any iteration's stores.
            # Freeze leaves, preserving containers for recursive target unpacking. A
            # dynamic leaf must not erase the independent binding of a known sibling.
            def freeze(value: ast.expr) -> ast.expr:
                if isinstance(value, (ast.Tuple, ast.List)):
                    return type(value)(elts=[freeze(child) for child in value.elts], ctx=ast.Load())
                if isinstance(value, ast.Starred):
                    return ast.Starred(value=freeze(value.value), ctx=ast.Load())
                name = (
                    f"{_LOOP_VALUE_PREFIX}{statement.lineno}:"
                    f"{statement.col_offset}:{len(frozen_names)}"
                )
                frozen_names.append(name)
                for state in looped:
                    bound = _apply_assignment(
                        ast.Assign(targets=[ast.Name(id=name)], value=value),
                        state,
                        self.path,
                        self.repo_root,
                        self.path_functions,
                    )[0]
                    state.update((key, bound[key]) for key in _binding_keys(name) if key in bound)
                return ast.Name(id=name, ctx=ast.Load())

            iterations = [freeze(value) for value in iterations]
        else:
            # Unknown counts and unordered sets use the round-eight per-element union.
            # Only stores depending on a loop-carried binding need uncertainty; a
            # constant reset has the same bounded value on every possible iteration.
            dependent: set[str] = set()
            for item in ast.walk(statement):
                if isinstance(item, ast.AugAssign):
                    dependent.update(_target_names(item.target))
                elif (
                    isinstance(item, (ast.Assign, ast.AnnAssign, ast.NamedExpr))
                    and item.value is not None
                    and any(
                        isinstance(child, ast.Name)
                        and isinstance(child.ctx, ast.Load)
                        and child.id in changed
                        for child in ast.walk(item.value)
                    )
                ):
                    targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                    dependent.update(name for target in targets for name in _target_names(target))
            changed = dependent
            for state in looped:
                for name in changed:
                    state[f"{_UNRESOLVED_FORMAT_PREFIX}{name}"] = "1"
            if isinstance(statement, (ast.For, ast.AsyncFor)):
                bound_states: list[dict[str, str]] = []
                for value in iterations:
                    # An unknown expansion retains other literal elements as evidence.
                    value = None if isinstance(value, ast.Starred) else value
                    bound_states = _merge_states(
                        bound_states
                        + [
                            self._bind_loop_target(statement.target, value, dict(state))
                            for state in looped
                        ]
                    )
                looped = bound_states
            iterations = [None]
        broken: list[dict[str, str]] = []
        for value in iterations:
            if exact:
                looped = [
                    self._bind_loop_target(statement.target, value, state) for state in looped
                ]
            loop_exits: list[dict[str, str]] = []
            looped = self.scan_block(statement.body, looped, exception_states, loop_exits)
            for state in loop_exits:
                reason = state.get(_FLOW_EXIT_KEY)
                if reason in {"Break", "Continue"}:
                    state.pop(_FLOW_EXIT_KEY)
                    (broken if reason == "Break" else looped).append(state)
                elif exit_states is not None:
                    exit_states.append(state)
            looped = _merge_states(looped)
        if not exact:
            # Calls can mutate outer bindings without a syntactic Store in this loop.
            # Its possible zero-iteration path cannot certify the old producer either.
            changed.update(
                key.removeprefix(prefix)
                for state in looped + broken
                for key in state
                for prefix in (_UNRESOLVED_CLOSURE_PREFIX, _UNRESOLVED_FORMAT_PREFIX)
                if key.startswith(prefix)
            )
            looped = _merge_states((_fork(states) if may_be_empty else []) + looped)
            # Once the fallback union exceeds the branch budget, retain concrete
            # alternatives as unresolved evidence rather than certifying correlations.
            changed.update(
                name.removeprefix(_VALUE_ALTERNATIVES_PREFIX)
                for state in looped
                for name in state
                if name.startswith(_VALUE_ALTERNATIVES_PREFIX)
                and len(_value_alternatives(state, name.removeprefix(_VALUE_ALTERNATIVES_PREFIX)))
                > _MAX_BRANCH_STATES
            )
            for state in looped + broken:
                # Retain observed reader alternatives as gaps, never bounded writers.
                for name in changed:
                    state[f"{_UNRESOLVED_FORMAT_PREFIX}{name}"] = "1"
        exhausted = self.scan_block(statement.orelse, looped, exception_states, exit_states)
        for state in exhausted + broken:
            for name in frozen_names:
                for key in _binding_keys(name):
                    state.pop(key, None)
        return _merge_states(exhausted + broken)

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

    def _region_mark(self) -> tuple[int, int]:
        """Where a region begins in BOTH channels this walk records into.

        The access list and the invocation ledger advance independently: a call that resolves
        entirely in its callee appends no access here, so its ledger entry shares the access
        position of whatever follows it. Using the access position for both then demoted a
        REACHED call because an unrelated undecided region began at the same access count —

            emit('artifacts/a.json')     # reached, appends no local access
            condition() and 0            # undecided operand region, same access position

        — and Python writes `a.json` unconditionally (review finding, codex, at `95312c946`).
        Two boundaries, captured at one moment, so the sites cannot drift apart.
        """
        return len(self.accesses), len(self.recorded_bindings)

    def _demote_from(self, mark: tuple[int, int] | None) -> None:
        """Everything recorded since ``mark`` is a site whose reachability is not established.

        `bounded` is what certification requires, so demoting keeps each access as evidence
        without asserting that it runs — the distinction between "withheld" and "absent" that
        skipping the scan destroys. **Withholding a producer is defensible; asserting that no
        producer exists is not.**

        One method rather than the same three lines at each site, for the reason the condition
        fold moved under `_literal_operand`: a rule written beside one of its callers is a rule
        the other callers do not get.
        """
        if mark is None:
            return
        access_mark, binding_mark = mark
        self.accesses[access_mark:] = [
            replace(access, bounded=False) for access in self.accesses[access_mark:]
        ]
        # The access list is not the only channel out of this region. An argument supplied here
        # is resolved in the CALLEE's scope walk, which this slice cannot reach, so demoting only
        # what was recorded locally left the helper's write certified from a call that never runs.
        # Its own boundary, because the two lists do not advance together.
        self.demoted_bindings.update(range(binding_mark, len(self.recorded_bindings)))

    def binding_certainty(self) -> tuple[dict[ast.AST, set[tuple]], dict[ast.AST, set[tuple]]]:
        """This walk's verdict on the invocation states it recorded, once the walk is over."""
        certain: dict[ast.AST, set[tuple]] = {}
        uncertain: dict[ast.AST, set[tuple]] = {}
        for index, (_position, callee, key) in enumerate(self.recorded_bindings):
            target = uncertain if index in self.demoted_bindings else certain
            target.setdefault(callee, set()).add(key)
        return certain, uncertain

    def _substituted(self, expression: ast.expr) -> ast.expr:
        """One-binding literal names replaced, for a DECISION only — never for a scan.

        Bounded to two forms on purpose. A bare `Name` is what the operator handlers already
        substituted, each with its own copy of the line. A `Compare` needs it at DEPTH, because
        the decision is made per link and the links hold the names: `v = 5` then `if v < 1 < 2:`
        could not be decided while only the whole test was checked for being a name, so the guard
        certified a body Python never enters (review findings, claude and codex, at `397535afe`).

        NOT a general rewriter. Anything else is returned as it came, so this cannot drift into a
        second value model beside the walker's — it substitutes exactly what
        `_literal_binding_is_unchallenged` has already proved unchanged, and nothing else.
        """
        if isinstance(expression, ast.Name):
            return self.literal_names.get(expression.id, expression)
        if isinstance(expression, ast.Compare):
            return ast.copy_location(
                ast.Compare(
                    left=self._substituted(expression.left),
                    ops=expression.ops,
                    comparators=[self._substituted(item) for item in expression.comparators],
                ),
                expression,
            )
        return expression

    def _resolved_constant(
        self, expression: ast.expr, states: list[dict[str, str]]
    ) -> tuple[bool, object]:
        """`_literal_operand` with the one-binding name substitution in front of it.

        The substitution and the resolution belong together and are wanted at four sites now —
        the comprehension's source and filters, the `for` statement's source, and the `if` and
        `while` tests. Each of those had grown its own answer to "is this decided", which is the
        drift the comparison folding repairs; this is the same repair one level up.
        """
        return _literal_operand(self._substituted(expression), self._constant_resolver(states))

    def _resolved_iteration_source(
        self, source: ast.expr, states: list[dict[str, str]]
    ) -> tuple[bool, object, str]:
        """Resolve a loop or comprehension source, and say which iteration case it is in.

        ONE resolution rule for both boundaries. They were written apart — the comprehension
        clause resolving names and helper returns, the `for` statement keying on `ast.List` /
        `ast.Tuple` / `ast.Set` syntax — and the non-iterable defect was found at the first and
        present at the second, in all three spellings (measured, not inferred: an inline `None`,
        a name bound to `0`, and a helper returning `None`). Two sites deciding the same question
        by different rules is how the spelling/value confusions in this file keep recurring, so
        the question is asked in one place.
        """
        known, constant = self._resolved_constant(source, states)
        return known, constant, _iteration_domain(known, constant)

    def _constant_resolver(self, states: list[dict[str, str]]) -> _ConstantResolver:
        """Let a conditional read a uniquely bound helper's constant return, through the EXISTING
        `_returned_constant`/`_helper_return_summary` machinery.

        This is the seam the shadowed-`set()` defect needs. `_literal_operand` refuses every call
        because a name resolved from the enclosing module could be anything — true of a bare
        name, and NOT true of a call whose helper this scanner has already summarised. The walker
        is the only place holding the binding table that answers it, so the resolver is passed
        down rather than a pure AST helper reaching for the table.

        **Every state must agree.** `states` is a DISJUNCTION, and a call can summarise
        differently under different bindings; taking the first would decide one branch on the
        strength of one arm of an earlier one. Disagreement, or any state that cannot answer,
        yields `(False, None)` — exactly the current behaviour — so this only narrows
        uncertainty and never invents a decision.

        Nothing is evaluated and no estate source is executed: the summary reads a return
        expression registration already parsed.
        """

        def resolve(node: ast.Call) -> tuple[bool, object]:
            answers: list[tuple[bool, object]] = []
            for values in states or [{}]:
                try:
                    answers.append(
                        _returned_constant(
                            node,
                            self.path,
                            values,
                            self.path_functions,
                            repo_root=self.repo_root,
                        )
                    )
                except RecursionError:
                    return False, None
            if not answers or not all(known for known, _ in answers):
                return False, None
            first = answers[0][1]
            if all(type(value) is type(first) and value == first for _, value in answers):
                return True, first
            return False, None

        return resolve

    def _scan_expression(self, node: ast.AST, states: list[dict[str, str]]) -> None:
        if isinstance(node, ast.FormattedValue):
            self._scan_expression(node.value, states)
            self._freeze_expression(node.value, states)
            if node.format_spec is not None:
                self._scan_expression(node.format_spec, states)
            return
        if isinstance(node, ast.Call) and any(
            isinstance(item, (ast.NamedExpr, ast.Call))
            for item in ast.walk(node)
            if item is not node
        ):
            # Python evaluates the callable (including its receiver) before arguments,
            # and each argument before the next. Snapshot complete values, not just names:
            # attributes, subscripts, and nested calls can all depend on a rebound name.
            self._scan_expression(node.func, states)
            if isinstance(node.func, (ast.Name, ast.Attribute)):
                self._freeze_callable(node.func, states)
            if isinstance(node.func, ast.Attribute):
                self._freeze_expression(node.func.value, states)
            for argument in (*node.args, *(keyword.value for keyword in node.keywords)):
                # Only a PROVEN consumer marks the body as running. Treating every call argument
                # as consuming kept `list(...)` right and made the unknown-callee case wrong in
                # the certifying direction: a generator handed to a helper that merely stores it
                # had its body certified, which absorbed a real orphan reader. Unknown stays
                # unknown here and is recorded as such by the comprehension handler.
                # Every disjunctive state must agree the name is unshadowed. One arm binding a
                # local `list` is enough to make the call not-proven, the same rule the constant
                # resolver already applies: deciding one branch on another's binding is how a
                # shadow gets spent as a builtin.
                # POSITION matters as much as the callee. `list` iterates its first positional
                # argument and nothing else, so `dict(payload=(gen))` and `max([1],
                # default=(gen))` iterate nothing at all — both reproduced certifying a phantom
                # writer without shadowing anything (review finding, codex, at `5e5331e7c`).
                # Marking every argument of a proven consumer was a second name-shaped
                # over-approximation sitting behind the first one I had just repaired.
                # `min`/`max` iterate ONE positional argument and COMPARE several: with two
                # generators and a `key=`, Python compares the objects and iterates neither, so
                # the first-positional rule certified a phantom on its own (review finding,
                # codex, at `4d13c27c8`). The call FORM decides, not just the callee and the
                # slot — a third thing the name alone was standing in for.
                if (
                    isinstance(argument, ast.GeneratorExp)
                    and node.args
                    and argument is node.args[0]
                    and not (
                        isinstance(node.func, ast.Name)
                        and node.func.id in {"min", "max"}
                        and len(node.args) > 1
                    )
                    and states
                    and all(
                        _call_consumes_generator_argument(
                            node.func, values, self.path, self.path_functions
                        )
                        for values in states
                    )
                ):
                    self.consumed_generators.add(id(argument))
                self._scan_expression(argument, states)
                self._freeze_expression(argument, states)
            self._classify(node, states)
            return
        if isinstance(node, ast.Lambda):
            self._scan_defaults(node, states)
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return
        if isinstance(node, ast.NamedExpr):
            self._scan_expression(node.value, states)
            # Preserve the evaluated RHS before its target changes that RHS's inputs.
            self._freeze_expression(node.value, states)
            self._bind(node.target, node.value, states)
            return
        if isinstance(node, ast.IfExp):
            self._scan_expression(node.test, states)
            # Same substitution as the `BoolOp` handler, and it is here because leaving it there
            # alone was a rule stated at the wrong level: `[open(...) if x else None for x in
            # [False]]` certified a writer for exactly the reason the `or` case did. The arms
            # are shared with the original node, so the returned alternative is still the real
            # one; only the test is replaced.
            probe = node
            if isinstance(node.test, ast.Name) and node.test.id in self.literal_names:
                probe = ast.IfExp(
                    test=self.literal_names[node.test.id], body=node.body, orelse=node.orelse
                )
            reachable = _reachable_alternatives(probe, self._constant_resolver(states))
            if len(reachable) == 1:
                # A constant test decides the arm, so the other one is never evaluated — and
                # scanning it does more than blur a binding, it CLASSIFIES its calls. Reported
                # critical by codex at `45a37aeda`:
                #     open('artifacts/never.json', 'w') if False else None
                # certified never.json as a producer and absorbed its orphan reader. I had
                # argued this path only withheld, reasoning about bindings and forgetting that
                # an unreachable arm can carry an effect.
                self._scan_expression(reachable[0], states)
                return
            # An undecided test reaches exactly ONE arm and this scanner does not know which, so
            # both are evidence and neither is certified — the same rule as the operator, chain
            # and comprehension sites. `def f(): return not True` before
            # `open(...) if f() else 0` opened nothing at runtime and certified the writer.
            #
            # Note what this does NOT say: it is not that the arms are unreachable. One of them
            # runs. Demoting both is the honest reading of "one of these two, unknown which",
            # and it is why the decided case above still certifies its single arm.
            arms_from = self._region_mark()
            taken, not_taken = _fork(states), _fork(states)
            self._scan_expression(node.body, taken)
            self._scan_expression(node.orelse, not_taken)
            self._demote_from(arms_from)
            states[:] = _merge_states(taken + not_taken)
            return
        if isinstance(node, ast.BoolOp):
            continued = _fork(states)
            alternatives: list[dict[str, str]] = []
            unreached_from: int | None = None
            for index, value in enumerate(node.values):
                self._scan_expression(value, continued)
                # THE INVARIANT, held identically in the `ast.Compare` handler below:
                # keep every REACHABLE stop point, and only those. A constant operand
                # decides the operator, so the alternative it rules out is not a cautious
                # extra — it is a state the program cannot reach, and a binding made there
                # certifies an artifact that is never written.
                #
                # The predicates in the two handlers are opposite because the operators are.
                # Here `decided is True` means "stops here", so a decided-False operand has
                # no reachable stop and is skipped; in `Compare`, `decided is True` means the
                # chain CONTINUES, so it is the True case that has no reachable stop. Both
                # reduce to the one sentence above; neither may be inverted on its own.
                # A comprehension target bound to a one-element literal source decides this
                # operator exactly as the literal would; substituting the node is how that
                # reaches a helper which reads literals and calls but never the value map.
                probe = self.literal_names.get(value.id) if isinstance(value, ast.Name) else None
                decided = _boolop_stops_after(
                    node.op, probe or value, self._constant_resolver(continued)
                )
                if decided is not False or index == len(node.values) - 1:
                    alternatives.extend(_fork(continued))  # stopping here is reachable
                if decided is True:
                    break  # nothing after a deciding operand can run
                # **UNRESOLVED IS NOT PERMISSION, at the operator too.** An operand this scanner
                # cannot decide may stop the operator, so everything after it is scanned as
                # evidence rather than certified: `def f(): return not True` before
                # `f() and open(...)` opened nothing at runtime and certified a writer (review
                # finding, codex, at `7824ec9ea`, raised at the chain handler and present at
                # three more operator sites). The mark is taken AFTER the decision, so it is the
                # NEXT operand's scan that falls inside it.
                if decided is None and unreached_from is None:
                    unreached_from = self._region_mark()
            self._demote_from(unreached_from)
            states[:] = _merge_states(alternatives)
            return
        if isinstance(node, ast.Compare) and len(node.comparators) > 1:
            # A CHAIN short-circuits: `a < b < c` stops at the first false comparison and
            # never evaluates `c`. A single comparison cannot, so it keeps the ordinary walk
            # below and this handler stays off the common path entirely.
            #
            # Reported by codex at b96341134 with `2 < 1 < (x := 'actual')`: the walker bound
            # the operand Python skips, then certified `artifacts/actual.json` — a file the
            # program never writes — and suppressed the orphan reader that would have shown it.
            #
            # `left` and the first comparator always evaluate; only the rest are conditional.
            #
            # THE INVARIANT, identical to the `ast.BoolOp` handler above: keep every REACHABLE
            # stop point, and only those. Here `decided is True` means the chain CONTINUES —
            # the opposite polarity to `BoolOp`, which is why the predicate reads
            # `is not True` here and `is not False` there. Both say the one sentence above.
            operands = [node.left, *node.comparators]
            # **The same substitution `BoolOp` and `IfExp` have, and this handler did not.** A
            # comprehension target bound to a one-element literal decides a link exactly as the
            # literal would, and without it `[x < 1 < open(...) for x in [5]]` could not see that
            # `5 < 1` stops the chain — so the write became an undecided-link demotion at best,
            # and a certification before that (review findings, claude and codex, at
            # `397535afe`, phrased as "does not resolve comprehension-target operands" and
            # "writes skipped by a bound comprehension target").
            #
            # Third site of one substitution rule, two of which had it. Deciding the link is
            # strictly better than demoting past it: the false case stops the scan entirely and
            # the true case keeps its certification, where demotion loses both.
            #
            # Substituted for the DECISION only. The scan below still walks the original nodes,
            # so nothing is classified against a rewritten tree.
            probes = [self._substituted(item) for item in operands]
            self._scan_expression(node.left, states)
            self._scan_expression(node.comparators[0], states)
            continued = _fork(states)
            alternatives = []
            chain_unreached_from: int | None = None
            for index in range(1, len(node.comparators)):
                decided = _comparison_outcome(probes[index - 1], node.ops[index - 1], probes[index])
                if decided is not True:
                    alternatives.extend(_fork(continued))  # stopping here is reachable
                if decided is False:
                    break  # nothing after a decided-false comparison can run
                # An UNDECIDED link may stop the chain, so what follows it is evidence rather
                # than certification — the site codex named, and the same rule as the operator
                # above. `def size(): return 5` before `size() < 1 < open(...)` opens nothing at
                # runtime (`5 < 1` is False) and certified the write. The decided-true case is
                # untouched: the chain definitely continues, so the next operand definitely runs.
                if decided is None and chain_unreached_from is None:
                    chain_unreached_from = self._region_mark()
                self._scan_expression(node.comparators[index], continued)
            self._demote_from(chain_unreached_from)
            alternatives.extend(_fork(continued))
            states[:] = _merge_states(alternatives)
            return
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            inner = _fork(states)
            # A comprehension target is scoped to the comprehension. Restored below so a name
            # bound here cannot decide an operator outside it, or in a sibling comprehension.
            outer_literal_names = dict(self.literal_names)
            # A list/set/dict comprehension runs at once. A GENERATOR does not: its body runs
            # only when something iterates it, so `g = (open(...) for _ in [1])` writes nothing
            # until `g` is consumed, and certifying it at the definition site invented a
            # producer and absorbed that file's orphan reader (review finding, codex, at
            # `07757da06`). The consuming positions record themselves on the way in; anything
            # else is deferred, and deferred is not evidence of an effect.
            body_runs = not isinstance(node, ast.GeneratorExp) or id(node) in (
                self.consumed_generators
            )
            if not body_runs:
                # NAMED UNCERTAINTY, not silence. Not scanning the body stops the phantom, but
                # going quiet would also drop the fact that something here was not analysed —
                # and "retain alternatives as unresolved evidence; prefer a named uncertainty to
                # a false producer match" is the standing contract for this row. A committed
                # control caught the difference: it counts the unresolved sites in
                # `(artifact.write_text('{}') for artifact in items)` as a bare statement, and
                # silently skipping the body lost one. The generator really is unanalysed, so
                # the count was right and my silence was wrong.
                self.unresolved[0] += 1
                if isinstance(self.path_functions, PathFunctionTable):
                    self.path_functions.unresolved_paths.add(
                        f"{self.path}:{node.lineno}:{node.col_offset}: deferred generator "
                        f"body not scheduled here expression={ast.unparse(node)}"
                    )
            # Where the target's value stops being known. Everything recorded from here on is a
            # site whose reachability this scanner has not established, and is demoted below.
            unreached_from: int | None = None
            for index, generator in enumerate(node.generators):
                # Once nothing reaches this point, nothing LATER is evaluated either — not a
                # subsequent generator's iterable, and not a filter after a false one. The
                # previous version scanned every generator and every condition regardless, so a
                # call in either was classified although Python never runs it (review finding,
                # codex, at `07757da06`; measured as `[y for x in [] for y in [open(...)]]` and
                # `[x for x in [1] if False if open(...)]` each certifying a phantom writer and
                # absorbing its orphan reader).
                #
                # This is the same constant-decided reachability the walker, the path expansion
                # and the comprehension BODY already honour. The body was the fifth place
                # deciding it blind; the generator chain and the filter chain were the sixth and
                # seventh, in the same handler as the repair.
                if not body_runs and index > 0:
                    break
                # **The OUTERMOST iterable is evaluated when the generator is CREATED.** Only
                # the body, the filters and any later iterable are deferred, so skipping the
                # whole clause chain for a deferred generator dropped a writer that really does
                # run — `(x for x in write_and_return())` executes the call at the definition
                # site whether or not anything iterates the result (root readback, 2026-09-08,
                # four reader twins). Scanning it is not the same as certifying the body, and
                # this is the only clause that gets the eager treatment.
                #
                # A comprehension iterates its own source, so a generator there is consumed —
                # but only when this one is itself iterated. A nested source has the same split
                # as its parent: eager construction, deferred iteration.
                if body_runs and isinstance(generator.iter, ast.GeneratorExp):
                    self.consumed_generators.add(id(generator.iter))
                self._scan_expression(generator.iter, inner)
                if not body_runs:
                    break
                # Bind the target to the element when the source is a ONE-element literal, so
                # the body's own short-circuits are decided by the same constant machinery the
                # filters and the walker already use. `any(x or open(...) for x in [True])`
                # writes nothing — `x` is True and the `or` never evaluates its right operand —
                # and binding `x` to nothing left that call certified against Python (root
                # readback, 2026-09-08). A proven consumer establishes that the body RUNS; it
                # says nothing about which expressions inside it are reached.
                #
                # One element only. With more, the body runs once per value and no single
                # binding describes it; guessing there would decide a branch on an arbitrary
                # element, which is the shape this file keeps having to repair.
                #
                # **But refusing to guess is not the same as permitting.** With a MULTI-element
                # literal I left the target unknown and then let the body certify anyway, so
                # `[x or open(...) for x in [True, True]]` produced a bounded writer for a file
                # Python never opens — every element short-circuits (review finding, codex, at
                # `7f5794f4b`). That is "unresolved is not permission" again, in the one place I
                # had explicitly reasoned about the ambiguity and still resolved it the
                # certifying way.
                #
                # So: withhold, but only when the target's VALUE can actually reach a decision —
                # that is, when the body or the filters read the name. `[open(...) for _ in
                # [1, 2]]` never consults `_`, so the elements cannot change what runs and it
                # certifies as before.
                # **RESOLVE FIRST, then decide from the VALUE — never from the spelling.** The
                # first version keyed the element count on `ast.List`/`ast.Tuple` syntax while
                # the resolution below accepts a far wider domain, so a NAMED `[True]`, a named
                # or inline tuple, `{1, 2}`, `{1: 0, 2: 0}`, `'ab'` and `b'ab'` all escaped the
                # withholding and certified a phantom writer — seven forms, two readers, no
                # runtime `open` at all (review finding, root, at `d70936cff`). Anchoring a
                # decision on AST syntax when the value channel is wider is the same error as
                # matching a consumer by name.
                #
                # Resolver here too: `def empty(): return []` supplying the iterable is the same
                # case as the filter below, and was named in an earlier finding.
                known, constant, domain = self._resolved_iteration_source(generator.iter, inner)

                bound: ast.expr | None = None
                # **RESOLVING A VALUE IS NOT REACHING ITS BODY.** `known` is a fact about this
                # scanner; whether `iter()` succeeds is a fact about the value, and reading the
                # first as the second let every non-iterable constant certify the body it can
                # never enter (see `_iteration_domain`). Three cases, one predicate, each
                # dispositioned below rather than left to a fall-through.
                sized = domain == SOURCE_ENUMERABLE
                if sized and len(constant) == 1:
                    # One element, whatever spelled it: bind the value the loop will take. A
                    # `set` or `dict` is unordered, but with exactly one element there is only
                    # one value to take, so the binding is exact rather than a choice.
                    only = next(iter(constant))
                    bound = ast.copy_location(ast.Constant(value=only), generator.iter)
                self._bind(generator.target, bound, inner)
                if isinstance(generator.target, ast.Name):
                    if bound is None:
                        self.literal_names.pop(generator.target.id, None)
                    else:
                        self.literal_names[generator.target.id] = bound
                if sized and len(constant) > 1 and _target_is_read_by(node, generator):
                    # **THE BODY RUNS. What is unknown is the TARGET'S VALUE.** The source is a
                    # resolved, non-empty literal, so Python enters the body once per element —
                    # the uncertainty is only about which sub-expressions inside it are reached.
                    # Refusing to scan at all confused those two, and the cost was measured:
                    # `[x or Path(...).read_text() for x in [False, False]]` executes its READER
                    # twice and the reader vanished from the report entirely, along with five
                    # writers that really do run (review finding, codex, at `120d38d9b`, three
                    # reader shapes; the writer shapes found while measuring it).
                    #
                    # So the region is scanned and its accesses are demoted to unbounded rather
                    # than dropped. That is the existing channel for "a site exists here whose
                    # reachability is not established" — certification already requires
                    # `bounded`, and an orphan reader survives as evidence instead of
                    # disappearing. **Withholding a producer is defensible; asserting that no
                    # producer exists is not**, and silence was the second thing.
                    #
                    # NOT exact, and stated as such: with the elements known, the exact answer is
                    # to scan the body once per element and union the results, the way the `for`
                    # statement handler has always bound its literal elements. That is the
                    # follow-on. This step is the sound one — it converts a silent loss into a
                    # named uncertainty and cannot certify what the old code certified before the
                    # withholding was added.
                    self.unresolved[0] += 1
                    if isinstance(self.path_functions, PathFunctionTable):
                        self.path_functions.unresolved_paths.add(
                            f"{self.path}:{node.lineno}:{node.col_offset}: comprehension target "
                            f"consulted over several resolved elements "
                            f"expression={ast.unparse(generator.iter)}"
                        )
                    if unreached_from is None:
                        unreached_from = self._region_mark()
                if domain == SOURCE_UNDECIDED:
                    # **UNRESOLVED IS NOT PERMISSION.** Leaving `body_runs` enabled here meant an
                    # iterable this scanner cannot evaluate certified everything inside it — and
                    # `def empty(): return []`, `items = []` and a helper returning `not True`
                    # each did exactly that while Python called nothing (review findings, codex
                    # and claude, at `4d13c27c8`). The deliverable's claim is that no certified
                    # producer is a wrong file, so the unresolved case must cost a wildcard
                    # rather than a certification.
                    #
                    # Recorded, not silent: the uncertainty is what distinguishes withholding
                    # from having quietly decided the other way. A value this scanner resolved
                    # but does not know how to enumerate is the same uncertainty arriving by a
                    # different road, so it is recorded as what it is rather than as a failure
                    # to resolve.
                    #
                    # **And "not silent" now means the region is still SCANNED and demoted, not
                    # skipped.** Withholding here used to stop the scan, which erased every
                    # reader and writer below it — `def go(): return not False` guarding a
                    # comprehension whose body really runs lost both (review finding, codex, at
                    # `7824ec9ea`). Three cases, not two: a DECIDED negative below drops the
                    # region because nothing runs, an UNDECIDED one keeps it as unbounded
                    # evidence because something might.
                    if unreached_from is None:
                        unreached_from = self._region_mark()
                    self.unresolved[0] += 1
                    if isinstance(self.path_functions, PathFunctionTable):
                        detail = (
                            "iterable not resolvable"
                            if not known
                            else f"resolved iterable outside enumerable domain "
                            f"type={type(constant).__name__}"
                        )
                        self.path_functions.unresolved_paths.add(
                            f"{self.path}:{node.lineno}:{node.col_offset}: comprehension "
                            f"{detail} expression={ast.unparse(generator.iter)}"
                        )
                    # **The `continue` jumps over this clause's own filters, and they are
                    # evidence.** An unresolved source may still yield elements — `def src():
                    # return [1]` does — so its filters may run, and skipping them erased a
                    # reader that executes at runtime (review finding, codex, at `da1cb13c7`).
                    # Scanned here rather than below, because the checks between this branch and
                    # the filter loop assume a sized constant this domain does not have.
                    for condition in generator.ifs:
                        self._scan_expression(condition, inner)
                    continue
                if domain == SOURCE_NOT_ITERABLE:
                    # `iter()` raises TypeError before the first element, so the body runs zero
                    # times and no filter or later clause is evaluated. **Decided, not withheld**
                    # — the count of elements is known exactly, and it is none — so this costs no
                    # uncertainty, exactly like the constant-empty source below.
                    #
                    # What this does NOT claim is that the code after the comprehension is dead.
                    # It is, unless something catches the TypeError, and this scanner does not
                    # model an expression that raises. Saying so here rather than leaving it
                    # implied: the residual is a false producer in the TAIL, not in the body,
                    # and it is narrower than what stood before this repair rather than a new
                    # permission.
                    body_runs = False
                    continue
                # A constant EMPTY iterable yields nothing, so nothing after it evaluates —
                # checked BEFORE the filters, because Python evaluates no filter for an
                # iterable that produces no element.
                if len(constant) == 0:
                    body_runs = False
                    continue
                for condition in generator.ifs:
                    self._scan_expression(condition, inner)
                    # A constant-false filter admits nothing, so nothing after it evaluates.
                    #
                    # The resolver IS passed now. An earlier revision withheld it and said so in
                    # a comment — "a widening of the same candidate, not part of it... left as a
                    # stated limit rather than an oversight". The limit was real and the code
                    # spent the unknown as permission to certify anyway: `def stop(): return
                    # False` followed by `[open(...) for _ in [1] if stop()]` produced a bounded
                    # writer and absorbed its orphan reader (review finding, codex, at
                    # `5e5331e7c`). A limit stated beside code that proceeds regardless is the
                    # defect, not a bound — the same shape as three other comments repaired
                    # today.
                    #
                    # A comparison is decided too — **by `_literal_operand` now, not by a second
                    # spelling here.** This site carried its own `_comparison_outcome` fallback,
                    # bolted on when the filter case was the only one anyone had measured; the
                    # fold moved under `_literal_operand` once four other condition sites turned
                    # out to need it, and the local copy went with it. Two spellings of one rule
                    # is how these sites drifted apart in the first place. Chains are decided now
                    # as well, which the single-op fallback here could not do.
                    known, constant = _literal_operand(condition, self._constant_resolver(inner))
                    if not known:
                        # Same rule as the iterable above: an unresolved GUARD is not permission
                        # to certify what it guards. `def stop(): return not True` reproduced a
                        # phantom writer through it — the helper's `not True` is a UnaryOp the
                        # constant channel does not fold, so the resolver answered "not
                        # established" and the filter admitted anyway.
                        #
                        # Scanned and demoted rather than skipped, for the same reason as the
                        # unresolved iterable above: an unresolved guard is not permission to
                        # CERTIFY what it guards, and it is not grounds to assert that what it
                        # guards is absent either. The guard's own truth is unknown, so the
                        # region below it is unbounded evidence.
                        if unreached_from is None:
                            unreached_from = self._region_mark()
                        self.unresolved[0] += 1
                        if isinstance(self.path_functions, PathFunctionTable):
                            self.path_functions.unresolved_paths.add(
                                f"{self.path}:{node.lineno}:{node.col_offset}: comprehension "
                                f"filter not resolvable expression={ast.unparse(condition)}"
                            )
                        # **The remaining filters are evidence too, and `break` erased them.**
                        # An undecided guard leaves the filters after it undetermined, not
                        # absent: `[1 for _ in [1] if go() if Path(...).read_text()]` with `go`
                        # returning `not False` reads once at runtime and lost its reader
                        # entirely. My earlier repair here stopped the SKIP for the body and the
                        # later clauses and left the sibling filters behind the same `break`
                        # (review finding, codex, at `da1cb13c7`).
                        continue
                    if not constant:
                        body_runs = False
                        break
            if body_runs:
                for value in (
                    (node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,)
                ):
                    self._scan_expression(value, inner)
            # Applied once over everything the region recorded — the filters after the clause
            # that could not be decided, every later clause, and the element expression,
            # including any nested comprehension inside them. Shared with the operator and chain
            # handlers, which answer the same question about their own operands.
            self._demote_from(unreached_from)
            self.literal_names = outer_literal_names
            # Otherwise the element expression is NOT scanned. Reported critical by glm at
            # `455612d07`: `[open('artifacts/never.json','w') for _ in []]`, a `if False`
            # filter, and an unexecuted generator each certified a produced artifact and
            # absorbed its orphan reader while Python wrote nothing. This is the same
            # constant-decided reachability the walker and path expansion already honour —
            # the comprehension body was simply a fifth place deciding it blind.
            # Do not export comprehension values. We also refuse to use a pre-comprehension
            # snapshot for these targets outside it; deferred iteration is not scheduled here.
            names = set().union(*(_target_names(g.target) for g in node.generators))
            # A comprehension has its OWN scope in Python 3, so a `for` target neither exports its
            # value nor disturbs an enclosing binding of the same name. Invalidating these outside
            # did the second thing: `artifact = Path('artifacts/old.json')` followed by
            # `[artifact.write_text('{}') for artifact in items]` lost the outer binding, and the
            # NEXT line's real write vanished with it — twelve shapes measured against the
            # interpreter, eight of them closed fixtures calling `use([])` or
            # `use([Path('artifacts/other.json')])`, every one of which Python writes and the
            # scanner recorded no writer for at all (review finding, root, at `2a49a0f7c`).
            #
            # Refusing to EXPORT the target was right and is unchanged: `inner` is a fork, so the
            # enclosing states never held the comprehension's binding to begin with.
            #
            # A walrus is the exception and the only one: `[(y := f(x)) for x in items]` really
            # does bind `y` in the enclosing scope, to a value this walk cannot pin, so those
            # targets are still invalidated.
            leaked_names = {
                item.target.id for item in ast.walk(node) if isinstance(item, ast.NamedExpr)
            }
            names.update(leaked_names)
            effect_names = {
                key.removeprefix(prefix)
                for state in inner
                for key in state
                for prefix in (_UNRESOLVED_CLOSURE_PREFIX, _UNRESOLVED_FORMAT_PREFIX)
                if key.startswith(prefix)
            }
            for state in states:
                _invalidate_names(state, leaked_names)
                # **The subtraction was wrong and my repair turned it into a phantom.** A callee
                # reached from the body can mutate a GLOBAL whose name coincides with a
                # comprehension target, and subtracting target names discarded that mutation
                # because the spellings matched:
                #
                #     artifact = Path('artifacts/old.json')
                #     def configure():
                #         global artifact
                #         artifact = Path('artifacts/new.json')
                #     [configure() for artifact in [1]]
                #     artifact.write_text('{}')          # Python writes NEW; this certified OLD
                #
                # At `6549d4d6c` and `2b1c95877` the enclosing invalidation hid the consequence
                # and the reader was correctly reported unwritten. Removing that invalidation
                # without removing this subtraction turned a conservative answer into a
                # CERTIFIED writer for a file nothing writes, which then absorbed the real
                # orphan reader — the exact class rounds seven to ten exist to eliminate
                # (review critical, codex, at `95312c946`; four comprehension forms).
                #
                # The two cases are not separable here: an effect key records that a name became
                # unresolved, whether by the comprehension's own target or by a callee's global
                # mutation. So the subtraction goes. Where the cause really was local this
                # over-withholds a name outside — which narrows, and withholding a producer is
                # defensible where asserting one is not.
                self._invalidate_effect_names(state, effect_names)
                if _CALL_GLOBALS_KEY in state and effect_names:
                    inherited = _decode_call_globals(state[_CALL_GLOBALS_KEY], self.path_functions)
                    self._invalidate_effect_names(inherited, effect_names)
                    state[_CALL_GLOBALS_KEY] = _encode_call_globals(inherited, self.path_functions)
            return
        if isinstance(getattr(node, "ctx", None), (ast.Store, ast.Del)):
            # Fallback for every Store form not owned by a statement handler below.
            self._scan_target(node, states)
            for state in states:
                _invalidate_names(state, _target_names(node))
            return
        ordered = any(
            isinstance(item, (ast.NamedExpr, ast.Call))
            for item in ast.walk(node)
            if item is not node
        )
        # `ast.iter_child_nodes` yields a node's fields in DECLARATION order, and `ast.Dict`
        # declares `keys` then `values` as two separate lists — so it yields every key and then
        # every value. Python evaluates key1, value1, key2, value2: each key before its own value,
        # in source order. The declaration order let an assignment in an earlier VALUE land after
        # one in a later KEY, and four reviewer families reported the wrong filename that
        # produces (2026-09-07):
        #
        #     x = 'wrong'
        #     d = {'first': (x := 'actual'), (x := 'final'): 0}
        #     return x            # Python leaves 'final'; the scanner certified 'actual'
        #
        # A `None` key is `**unpacking`, where only the value is evaluated — and an assignment
        # inside an unpacked value is one of the four cases, so the pairing has to keep it.
        if isinstance(node, ast.Dict):
            children: list[ast.AST] = [
                item
                for key, value in zip(node.keys, node.values, strict=True)
                for item in ((key, value) if key is not None else (value,))
            ]
        else:
            children = list(ast.iter_child_nodes(node))
        for child in children:
            self._scan_expression(child, states)
            if ordered and isinstance(child, ast.expr):
                self._freeze_expression(child, states)
        if isinstance(node, ast.Call):
            self._classify(node, states)

    def _freeze_expression(self, node: ast.expr, states: list[dict[str, str]]) -> None:
        # Constants cannot be rebound by a later operand. A call without nested effects
        # likewise needs no operand snapshots; its arguments are classified before effects.
        if isinstance(node, ast.Constant):
            return
        name = _expression_value_name(node)
        for state in states:
            assigned = _apply_assignment(
                ast.Assign(targets=[ast.Name(id=name)], value=node),
                state,
                self.path,
                self.repo_root,
                self.path_functions,
            )[0]
            state.update((key, assigned[key]) for key in _binding_keys(name) if key in assigned)

    def _freeze_callable(self, node: ast.expr, states: list[dict[str, str]]) -> None:
        for state in states:
            name = _expression_value_name(node)
            target = self.path_functions.canonical_name(
                _dotted_name(_evaluated_expression(node, state)) or "",
                self.path,
                _lexical_scope(state),
                _import_aliases(state),
            )
            state[name] = "*"
            _set_import_alias(state, name, target)

    def _decorator_effect_values(
        self, function: PathFunction, state: dict[str, str]
    ) -> tuple[dict[str, str], set[str]] | None:
        """Refine invalidation only for a visible, straight-line identity decorator.

        Other bodies retain the ordinary call-effect uncertainty. In particular, neither
        wrapper factories nor arbitrary return values certify the decorated definition.
        """
        node = function.node
        table = self.path_functions
        if (
            not isinstance(node, ast.FunctionDef)
            or function.path != self.path
            or not function.params
            or table.outer_effects.get(node, _OuterEffects()).unresolved
        ):
            return None
        globals_, nonlocals = _scope_outer_mutations(node)
        if nonlocals or "*" in globals_:
            return None
        bound = _scope_initial_values(
            node,
            state,
            function.path,
            self.repo_root,
            table,
            function.lexical_prefixes,
            _call_global_values(function, state, self.path, table),
        )
        for index, statement in enumerate(node.body):
            if isinstance(statement, (ast.Global, ast.Pass)) or (
                isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
            ):
                continue
            if isinstance(statement, ast.Return):
                if (
                    index == len(node.body) - 1
                    and isinstance(statement.value, ast.Name)
                    and statement.value.id == function.params[0]
                ):
                    if any("*" in bound.get(name, "*") for name in globals_):
                        return None
                    return bound, globals_
                return None
            if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                return None
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            if any(
                not isinstance(target, ast.Name) or target.id in function.params
                for target in targets
            ):
                return None
            # Only already modelled path constructors may execute in the refinement.
            # Even a visible helper uses the ordinary transitive effect machinery instead.
            if any(
                isinstance(item, (ast.NamedExpr, ast.Await, ast.Yield, ast.Lambda))
                or isinstance(item, ast.Call)
                and table.canonical_name(
                    _function_name(item),
                    function.path,
                    function.lexical_prefixes,
                    _import_aliases(bound),
                )
                not in _PATH_CONSTRUCTORS
                for item in ast.walk(statement)
            ):
                return None
            bound = _apply_assignment(statement, bound, function.path, self.repo_root, table)[0]
        return None

    def _apply_decorators(
        self,
        statement: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
        states: list[dict[str, str]],
    ) -> list[bool]:
        identities = [True] * len(states)
        table = self.path_functions
        for decorator in reversed(statement.decorator_list):
            name = f"\0decorator:{decorator.lineno}:{decorator.col_offset}"
            call = ast.copy_location(
                ast.Call(
                    func=ast.Name(id=name, ctx=ast.Load()), args=[ast.Constant(None)], keywords=[]
                ),
                decorator,
            )
            for index, state in enumerate(states):
                function = table.resolve(
                    name, self.path, _lexical_scope(state), _import_aliases(state)
                )
                refinement = self._decorator_effect_values(function, state) if function else None
                self._classify(call, [state])
                if refinement is None:
                    identities[index] = False
                    # Missing bodies and unsupported effect summaries may touch outer data.
                    self._invalidate_uncertain_bindings(state)
                else:
                    bound, globals_ = refinement
                    inherited = _current_global_values(state, table)
                    hidden = set(json.loads(state.get(_CALL_LOCALS_KEY, "[]"))) | set(
                        json.loads(state.get(_CALL_CELLS_KEY, "[]"))
                    )
                    for target in globals_:
                        for destination in [inherited] + ([] if target in hidden else [state]):
                            for key in _binding_keys(target):
                                destination.pop(key, None)
                                if key in bound:
                                    destination[key] = bound[key]
                    if _CALL_GLOBALS_KEY in state:
                        state[_CALL_GLOBALS_KEY] = _encode_call_globals(inherited, table)
                for key in _binding_keys(name):
                    state.pop(key, None)
        return identities

    def _scan_statement(
        self,
        statement: ast.stmt,
        states: list[dict[str, str]],
        exception_states: list[dict[str, str]] | None = None,
        exit_states: list[dict[str, str]] | None = None,
    ) -> list[dict[str, str]]:
        for state in states:
            for key in list(state):
                if _EXPRESSION_VALUE_PREFIX in key:
                    state.pop(key)
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
            self._freeze_expression(statement.target, states)
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for decorator in statement.decorator_list:
                self._scan_expression(decorator, states)
                self._bind(
                    ast.Name(id=f"\0decorator:{decorator.lineno}:{decorator.col_offset}"),
                    decorator,
                    states,
                )
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._scan_defaults(statement, states)
            for argument in ast.walk(statement.args):
                if isinstance(argument, ast.arg) and argument.annotation is not None:
                    self._scan_expression(argument.annotation, states)
            if statement.returns is not None:
                self._scan_expression(statement.returns, states)
        elif not isinstance(statement, (ast.With, ast.AsyncWith)):
            for child in ast.iter_child_nodes(statement):
                if (
                    child not in owned_targets
                    and child not in getattr(statement, "decorator_list", ())
                    and not isinstance(child, (ast.stmt, ast.ExceptHandler, ast.match_case))
                ):
                    # `for x in (genexp):` iterates it, so its body runs. This is the third
                    # consuming position, and the only one reached through the generic child
                    # walk rather than a dedicated handler.
                    if isinstance(child, ast.GeneratorExp) and child is getattr(
                        statement, "iter", None
                    ):
                        self.consumed_generators.add(id(child))
                    self._scan_expression(child, states)
        for scope in _statement_scopes(statement):
            self.nested_scope_values.setdefault(scope, []).extend(
                _definition_scope_values(state, self.path_functions) for state in states
            )
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if isinstance(statement, ast.ClassDef):
                states = self._scan_class_body(statement, states, exception_states)
            identities = self._apply_decorators(statement, states)
            for state, identity in zip(states, identities, strict=True):
                _invalidate_names(state, {statement.name})
                prefix = next(iter(_lexical_scope(state)), "")
                target = ".".join(filter(None, (_module_name(self.path), prefix, statement.name)))
                _set_import_alias(
                    state,
                    statement.name,
                    _definition_identity(target, statement)
                    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)) and identity
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
            # Remember a name bound to a FOLDABLE literal, so a comprehension whose iterable or
            # filter is that bare name can be decided by the same constant machinery as the
            # literal spelling. Withholding on every unresolved iterable is correct and too
            # blunt on its own: it turned `items = [1]` — a real producer with a committed twin
            # — into a lost certification, while `items = []` needed the withholding. Resolving
            # what CAN be resolved is the other half of the same instruction, and it makes the
            # two cases differ by their value rather than by their spelling.
            for target in (
                statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            ):
                if not isinstance(target, ast.Name):
                    continue
                # `x: int` is an AnnAssign with NO value, and binding None here reached
                # `ast.unparse` through the substitution and crashed the real-tree scan. An
                # annotation without a value binds nothing at runtime either.
                if statement.value is None:
                    self.literal_names.pop(target.id, None)
                    continue
                known, _ = _literal_operand(statement.value)
                # **The binding is admitted only when NOTHING in the scope can have changed it.**
                # Recording it on assignment and dropping it on re-assignment was a parallel
                # state channel that escaped the binding, mutation and branch model this scanner
                # already has: `items.clear()`, `alias = items; alias.clear()`, `items *= 0`,
                # `del items[:]` and an untaken-branch assignment each left a STALE LITERAL PROOF
                # and certified a phantom writer (review finding, root, at `44238fb5c`, ten
                # cases). Threading invalidation through every one of those was the alternative,
                # and it is how a second state model drifts from the first.
                if known and _literal_binding_is_unchallenged(target.id, self.scope_node):
                    self.literal_names[target.id] = statement.value
                else:
                    self.literal_names.pop(target.id, None)
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
            # **Through `_literal_operand`, not a private copy of it.** This handler had inlined
            # that function's shadowed-call refusal and its `literal_eval`, and so never received
            # any of the widenings the shared one has had: not the comparison folding above, and
            # not the uniquely-bound helper's constant return. Measured: `if 1 == 2:` and
            # `if stop():` with `def stop(): return False` both certified the guarded writer.
            #
            # This only ever scans LESS — a decided condition takes one branch where both were
            # merged before — and the refusals it inherits are the stricter ones.
            known, condition = self._resolved_constant(statement.test, states)
            if known:
                branch = statement.body if condition else statement.orelse
                return self.scan_block(branch, states, exception_states, exit_states)
            taken = self.scan_block(statement.body, _fork(states), exception_states, exit_states)
            not_taken = (
                self.scan_block(statement.orelse, _fork(states), exception_states, exit_states)
                if statement.orelse
                else _fork(states)
            )
            return _merge_states(taken + not_taken)
        if isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
            return self._scan_loop(statement, states, exception_states, exit_states)
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

    def _scan_class_body(
        self,
        statement: ast.ClassDef,
        states: list[dict[str, str]],
        exception_states: list[dict[str, str]] | None,
    ) -> list[dict[str, str]]:
        # Reuse function ownership metadata and effect invalidation. Keep the enclosing
        # frame as well: a class attribute can hide a global or cell that a callee changes.
        table = self.path_functions
        local_names = _scope_local_names(statement)
        globals_, nonlocals = _scope_outer_mutations(statement, stores_only=False)
        mutated_globals, _ = _scope_outer_mutations(statement)
        completed: list[dict[str, str]] = []

        def project(inner: dict[str, str]) -> dict[str, str]:
            if _CLASS_OUTER_KEY not in inner:
                # A branch join may discard differing frame snapshots at the state cap.
                # Keep the caller's identity, withdrawing certainty about its data bindings.
                outer = dict(state)
                self._invalidate_uncertain_bindings(
                    outer, captures=set(json.loads(outer.get(_CALL_LOCALS_KEY, "[]")))
                )
                return outer
            outer = _decode_call_globals(inner[_CLASS_OUTER_KEY], table)
            hidden = set(json.loads(outer.get(_CALL_LOCALS_KEY, "[]"))) | set(
                json.loads(outer.get(_CALL_CELLS_KEY, "[]"))
            )
            inherited = _current_global_values(outer, table)
            for name in globals_ | nonlocals:
                destinations = (
                    [inherited] + ([] if name in hidden else [outer])
                    if name in globals_
                    else [outer]
                )
                for destination in destinations:
                    for key in _binding_keys(name):
                        destination.pop(key, None)
                        if key in inner:
                            destination[key] = inner[key]
            # Namespace stores and stores in nested classes have no direct value in
            # this namespace. They still cannot leave an enclosing snapshot bounded.
            indirect = mutated_globals - globals_
            if "*" in indirect:
                indirect = {name for name in inherited if not name.startswith("\0")}
            self._invalidate_effect_names(inherited, indirect)
            self._invalidate_effect_names(outer, indirect - hidden)
            if _CALL_GLOBALS_KEY in outer:
                outer[_CALL_GLOBALS_KEY] = _encode_call_globals(inherited, table)
            if _HELPER_EFFECT_KEY in inner:
                outer[_HELPER_EFFECT_KEY] = inner[_HELPER_EFFECT_KEY]
            return outer

        for state in states:
            inner = dict(state)
            inherited = _current_global_values(state, table)
            cells = set(json.loads(state.get(_CALL_LOCALS_KEY, "[]"))) | set(
                json.loads(state.get(_CALL_CELLS_KEY, "[]"))
            )
            for name in globals_:
                for key in _binding_keys(name):
                    inner.pop(key, None)
                    if key in inherited:
                        inner[key] = inherited[key]
            inner[_CALL_LOCALS_KEY] = json.dumps(sorted(local_names))
            inner[_CALL_CELLS_KEY] = json.dumps(sorted(cells - globals_))
            inner[_CALL_GLOBALS_KEY] = _encode_call_globals(inherited, table)
            inner[_CLASS_OUTER_KEY] = _intern_binding_state(state, table)
            class_exceptions: list[dict[str, str]] = []
            class_exits: list[dict[str, str]] = []
            normal = self.scan_block(statement.body, [inner], class_exceptions, class_exits)
            completed.extend(project(result) for result in normal)
            if exception_states is not None:
                exception_states.extend(
                    project(result) for result in class_exceptions + class_exits
                )
        return _merge_states(completed)


class _ModuleBindingScanner(_BlockScanner):
    """Compute post-flow globals with the same uncertainty as evaluated calls.

    Diagnostics are discarded by _module_values and scope_node=None does not publish
    invocation states. Unobserved bodies must still inherit unresolved result provenance.
    """


class _PathHelperScanner(_BlockScanner):
    """Evaluate return bindings using the same control flow as artifact access scanning.

    Helpers expose one scalar path to the expression resolver. Ambiguous returns and effects
    we cannot bound therefore remain unresolved, rather than selecting one branch's producer.
    Calls are inspected for effects here; accesses are counted by the ordinary scope scan.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.return_values: set[str | None] = set()
        self.return_constants: set[str | None] = set()
        self.unbounded_return = False

    def _scan_expression(self, node: ast.AST, states: list[dict[str, str]]) -> None:
        # Effect uncertainty is permanent for this return-summary path. Keep walking
        # statements (including exception/return edges), but no operand snapshot can
        # make its return bounded again. The ordinary scope scan still records accesses.
        if states and all(_HELPER_EFFECT_KEY in state for state in states):
            return
        super()._scan_expression(node, states)

    def _classify(self, call: ast.Call, states: list[dict[str, str]]) -> None:
        for state in states:
            if _HELPER_EFFECT_KEY in state:
                continue
            resolved = _resolve_path_expr(
                call, state, self.path, self.repo_root, self.path_functions
            )
            scalar_known, _ = (
                _returned_constant(
                    call, self.path, state, self.path_functions, repo_root=self.repo_root
                )
                if resolved is None
                else (False, None)
            )
            if resolved is None and not scalar_known:
                state[_HELPER_EFFECT_KEY] = "1"
            if isinstance(self.path_functions, PathFunctionTable):
                function = self.path_functions.resolve(
                    _function_name(call, state),
                    self.path,
                    _lexical_scope(state),
                    _import_aliases(state),
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
            # Project the shared walk's completed state, including frozen operand values.
            result = super()._scan_statement(statement, states, exception_states, exit_states)
            for state in states:
                if _HELPER_EFFECT_KEY in state:
                    self.return_values.add(None)
                    self.return_constants.add(None)
                else:
                    known, constant = _constant_value(
                        statement.value, state, self.path, self.path_functions
                    )
                    if not known:
                        known, constant = _returned_constant(
                            statement.value,
                            self.path,
                            state,
                            self.path_functions,
                            repo_root=self.repo_root,
                        )
                    self.return_constants.add(json.dumps(constant) if known else None)
                    # Keep scalar evidence for explicit conversion, never certify its spelling.
                    non_path = known and not isinstance(constant, str)
                    if not known:
                        for expression in _path_expressions(
                            statement.value, self.path, self.path_functions
                        ):
                            scalar_known, scalar = _constant_value(
                                expression, state, self.path, self.path_functions
                            )
                            if scalar_known and not isinstance(scalar, str):
                                non_path = True
                    self.unbounded_return |= _has_unbounded_format(
                        statement.value, state, self.path, self.repo_root, self.path_functions
                    )
                    self.return_values.update(
                        (None,)
                        if non_path
                        else _resolve_path_expr_variants(
                            statement.value, state, self.path, self.repo_root, self.path_functions
                        )
                    )
            return result
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
    table = path_functions if isinstance(path_functions, PathFunctionTable) else None
    if table is not None and node in table.capped_scopes and table.scope_results.get(node):
        return
    supplied = parameter_values or {}
    cache_key = None
    evidence = None
    helpers = None
    if table is not None:
        # Memoize the inputs, not an expanded copy of all globals for every function.
        # Look up evidence before rebuilding locals, globals, and helper import bindings.
        input_key = (_intern_binding_state(module_values, table), tuple(sorted(supplied.items())))
        helper_key = (node, input_key)
        helpers = table.scope_helpers.get(helper_key)
        results = table.scope_results.setdefault(node, {})
        for name in closure_rebindings or ():
            table.unresolved_closures.add(
                f"{path}:{node.lineno}: closure binding {name} may change after definition"
            )
        if helpers is not None:
            defaults = frozenset(
                (helper, tuple(sorted(table.definition_defaults.get(helper, {}).items())))
                for helper in (node, *helpers)
            )
            cache_key = (*input_key, defaults, table.effect_revisions[node])
            evidence = results.get(cache_key)
        if evidence is None and len(results) >= _MAX_BINDING_STATES:
            table.capped_scopes.add(node)
            return
    if evidence is None:
        invocation_globals = (
            _decode_call_globals(parameter_values[_CALL_GLOBALS_KEY], path_functions)
            if parameter_values is not None and _CALL_GLOBALS_KEY in parameter_values
            else None
        )
        initial = _scope_initial_values(
            node,
            module_values,
            path,
            repo_root,
            path_functions,
            lexical_prefixes,
            invocation_globals,
        )
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
        if table is not None:
            if helpers is None:
                if node not in table.scope_calls:
                    table.scope_calls[node] = [
                        item for item in ast.walk(node) if isinstance(item, ast.Call)
                    ]
                aliases = _import_aliases(initial)
                helpers = tuple(
                    {
                        helper.node
                        for call in table.scope_calls[node]
                        if (
                            helper := table.resolve(
                                _function_name(call), path, lexical_prefixes, aliases
                            )
                        )
                        is not None
                        and helper.node is not None
                    }
                )
                table.scope_helpers[helper_key] = helpers
            defaults = frozenset(
                (helper, tuple(sorted(table.definition_defaults.get(helper, {}).items())))
                for helper in (node, *helpers)
            )
            cache_key = (*input_key, defaults, table.effect_revisions[node])
    if evidence is None:
        saved_calls = table.call_bindings if table is not None else {}
        saved_certain = table.certain_call_states if table is not None else {}
        saved_uncertain = table.uncertain_call_states if table is not None else {}
        saved_paths = table.unresolved_paths if table is not None else set()
        saved_closures = table.unresolved_closures if table is not None else set()
        if table is not None:
            table.call_bindings = {}
            table.certain_call_states = {}
            table.uncertain_call_states = {}
            table.unresolved_paths = set()
            table.unresolved_closures = set()
        local_accesses: list[ArtifactAccess] = []
        local_unresolved = [0]
        local_unrecognised: Counter[str] = Counter()
        local_nested: dict[ast.AST, list[dict[str, str]]] = {}
        scanner = _BlockScanner(
            path=path,
            repo_root=repo_root,
            path_functions=path_functions,
            accesses=local_accesses,
            unresolved=local_unresolved,
            unrecognised=local_unrecognised,
            context_family=_artifact_family(context),
            nested_scope_values=local_nested,
            scope_node=node,
        )
        if isinstance(node, ast.Lambda):
            scanner._scan_expression(node.body, [initial])
        else:
            scanner.scan_block(list(node.body), [initial])
        # Merged into the table once, below, AFTER the swapped-out maps are restored — merging
        # here would write into the scope-local dict this branch is about to discard, and the
        # merge below runs for a cache hit as well, so one call covers both paths.
        scanned_certain, scanned_uncertain = scanner.binding_certainty()
        evidence = _ScopeEvidence(
            local_accesses,
            local_unresolved[0],
            local_unrecognised,
            table.call_bindings if table is not None else {},
            scanned_certain,
            scanned_uncertain,
            local_nested,
            {scope: dict(table.definition_defaults.get(scope, {})) for scope in local_nested}
            if table is not None
            else {},
            table.unresolved_paths if table is not None else set(),
            table.unresolved_closures if table is not None else set(),
        )
        if table is not None:
            table.call_bindings = saved_calls
            table.certain_call_states = saved_certain
            table.uncertain_call_states = saved_uncertain
            table.unresolved_paths = saved_paths
            table.unresolved_closures = saved_closures
            table.scope_results[node][cache_key] = evidence
    accesses.extend(evidence.accesses)
    unresolved[0] += evidence.unresolved
    unrecognised.update(evidence.unrecognised)
    if nested_scope_values is not None:
        for scope, states in evidence.nested.items():
            nested_scope_values.setdefault(scope, []).extend(_fork(states))
    if table is not None:
        table.call_edges.setdefault(node, set()).update(evidence.calls)
        for callee, states in evidence.calls.items():
            table.record_calls(callee, states)
        # A cache hit must reproduce the withholding the original walk decided, not re-certify
        # from the binding list alone — and this is also how the uncertainty reaches a callee's
        # callee, since the evidence is what propagates.
        table.merge_binding_certainty(evidence.certain_calls, evidence.uncertain_calls)
        table.definition_defaults.update(evidence.defaults)
        table.unresolved_paths.update(evidence.paths)
        table.unresolved_closures.update(evidence.closures)


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
            aliases[statement.name] = (
                _definition_identity(f"{module_name}.{statement.name}", statement)
                if not statement.decorator_list
                else ""
            )
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
    scopes_by_path = {relative: _iter_function_scopes(tree) for relative, tree in parsed}
    rebindings_by_node: dict[ast.AST, set[str]] = {}
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
            for scope in scopes_by_path[relative]:
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

    for relative, values in module_values_by_path.items():
        for key, target in values.items():
            if key.startswith(_IMPORT_ALIAS_PREFIX) and not (
                name := key.removeprefix(_IMPORT_ALIAS_PREFIX)
            ).startswith("\0"):
                path_functions.export_bindings[f"{_module_name(relative)}.{name}"] = target
                path_functions.export_paths[f"{_module_name(relative)}.{name}"] = relative

    # Gather calls across the whole repository before retaining any body's accesses.
    # Recompute each round: provisional defaults must disappear when a later caller is found.
    observed_calls: dict[ast.AST, list[dict[str, str]]] = {}
    #: Snapshotted with `observed_calls` and consulted from it, never read mid-round. A scope is
    #: scanned against the PREVIOUS round's bindings, so judging their certainty from the current
    #: round's partly-filled marks would make a callee's verdict depend on file order.
    observed_certain: dict[ast.AST, set[tuple]] = {}
    observed_uncertain: dict[ast.AST, set[tuple]] = {}
    changing_calls: set[ast.AST] = set()
    changed_effects: set[ast.AST] = set()
    for _ in range(_MAX_BINDING_ROUNDS):
        path_functions.call_bindings = {}
        path_functions.certain_call_states = {}
        path_functions.uncertain_call_states = {}
        path_functions.unresolved_paths.clear()
        path_functions.unresolved_closures.clear()
        path_functions.helper_results.clear()
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
            for scope in scopes_by_path[relative]:
                # Definition snapshots are usable only for cells that cannot subsequently change.
                # Called functions replace this fallback with their invocation globals.
                initial_states = (
                    nested_scope_values.get(scope.node, [])
                    if len(scope.lexical_prefixes) > 1
                    else [values]
                    if scope.node in nested_scope_values
                    else []
                )
                if scope.node not in rebindings_by_node:
                    rebindings_by_node[scope.node] = (
                        _closure_rebound_names(
                            enclosing_scopes[scope.lexical_prefixes[1]].node, scope.node
                        )
                        if len(scope.lexical_prefixes) > 1
                        else set()
                    )
                rebindings = rebindings_by_node[scope.node]
                enclosing_scopes[scope.qualname] = scope
                uncertain_keys = observed_uncertain.get(scope.node, frozenset())
                certain_keys = observed_certain.get(scope.node, frozenset())

                def _binding_uncertain(
                    state: dict[str, str],
                    uncertain_keys: frozenset[tuple] | set[tuple] = uncertain_keys,
                    certain_keys: frozenset[tuple] | set[tuple] = certain_keys,
                ) -> bool:
                    key = tuple(sorted(state.items()))
                    return key in uncertain_keys and key not in certain_keys

                # Deliberately NOT re-scanned against the empty definition baseline when every
                # observed state is uncertain. Doing so keeps the definition-only certification
                # alive, and measured, it emits the same write twice — once bounded and once
                # not — which needs a repository-wide rule about which row wins. A helper whose
                # only call site in this tree is unreached is reported as evidence rather than
                # as a certified producer; that is a real consequence of this repair, and the
                # narrower of the two, so it is taken openly rather than paid for with a
                # deduplication rule reaching every site in the corpus.
                supplied_states = list(observed_calls.get(scope.node, [{}]))
                for initial in _merge_states(initial_states):
                    for supplied in supplied_states:
                        supplied_mark = len(accesses)
                        entered_uncertain = path_functions.scanning_uncertain
                        path_functions.scanning_uncertain = entered_uncertain or _binding_uncertain(
                            supplied
                        )
                        try:
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
                        finally:
                            path_functions.scanning_uncertain = entered_uncertain
                        # The body is scanned once per invocation state, so the accesses this
                        # state produced are exactly the ones appended here. Where no reached
                        # call site supplied the state, they are what the argument binding from
                        # an unreached region resolved — evidence, not a certified writer.
                        if _binding_uncertain(supplied):
                            accesses[supplied_mark:] = [
                                replace(access, bounded=False)
                                for access in accesses[supplied_mark:]
                            ]
        discovered = {
            node: [
                dict(items) for items in sorted({tuple(sorted(state.items())) for state in states})
            ]
            for node, states in path_functions.call_bindings.items()
        }
        discovered_certain = {
            node: set(keys) for node, keys in path_functions.certain_call_states.items() if keys
        }
        discovered_uncertain = {
            node: set(keys) for node, keys in path_functions.uncertain_call_states.items() if keys
        }
        changed_effects = path_functions.close_outer_effects()
        # Certainty is part of the fixpoint, not a decoration on it. A round where the bindings
        # are stable but their certainty has just changed must run again, or the accesses kept
        # are the ones scanned before the withholding was known.
        if (
            discovered == observed_calls
            and discovered_certain == observed_certain
            and discovered_uncertain == observed_uncertain
            and not changed_effects
        ):
            changing_calls = set()
            break
        changing_calls = {
            node
            for node in discovered.keys() | observed_calls.keys()
            if discovered.get(node) != observed_calls.get(node)
        }
        observed_calls = discovered
        observed_certain = discovered_certain
        observed_uncertain = discovered_uncertain
    if changed_effects:
        # The last permitted sweep used provisional effects. Withhold its dependent
        # scope evidence, including module callers, rather than retaining stale writers.
        changing_calls.update(
            node for node, callees in path_functions.call_edges.items() if callees & changed_effects
        )
    changing_calls.update(path_functions.capped_scopes)
    if changing_calls:
        # Recursive argument growth has no finite binding in this model. Keep its gaps named,
        # and withhold function writers rather than publishing the last arbitrary approximation.
        pending = list(changing_calls)
        while pending:
            for callee in path_functions.call_edges.get(pending.pop(), set()) - changing_calls:
                changing_calls.add(callee)
                pending.append(callee)
        function_lines = {
            (relative, item.lineno)
            for relative, tree in parsed
            for node in (tree, *(scope.node for scope in scopes_by_path[relative]))
            if node in changing_calls
            for item in ast.walk(node)
            if isinstance(item, ast.Call)
        }
        accesses = [
            access
            for access in accesses
            if access.action != "write" or (access.path, access.lineno) not in function_lines
        ]
        # A cap withholds producer claims, but must not erase already observed unresolved
        # reader identities. These remain gap evidence and cannot prove a bounded producer.
        accesses.extend(
            access
            for node in changing_calls
            for evidence in path_functions.scope_results.get(node, {}).values()
            for access in evidence.accesses
            if access.action == "read" and not access.bounded
        )
        for relative, tree in parsed:
            for node, name in [
                (tree, "<module>"),
                *((scope.node, scope.qualname) for scope in scopes_by_path[relative]),
            ]:
                if node in changing_calls:
                    site = (
                        f"{relative}:{getattr(node, 'lineno', 1)}: call bindings for {name} "
                        "did not converge"
                    )
                    if node in path_functions.capped_scopes:
                        site += " (binding state cap)"
                        path_functions.capped_expressions.add(site)
                    path_functions.unresolved_paths.add(site)
                    unresolved[0] += 1
    accesses.extend(
        sorted(
            path_functions.capped_reads,
            key=lambda access: (str(access.path), access.lineno, access.pattern),
        )
    )
    # A refused export lookup must also withdraw fallback evidence from the old body
    # and the callees it could reach. Keep literal readers and writers, visibly unbounded.
    uncertain_nodes = set(path_functions.uncertain_bindings)
    pending = list(uncertain_nodes)
    while pending:
        for callee in path_functions.call_edges.get(pending.pop(), set()) - uncertain_nodes:
            uncertain_nodes.add(callee)
            pending.append(callee)
    uncertain_lines: set[tuple[Path, int]] = set()
    for node in uncertain_nodes:
        function = path_functions.functions_by_node.get(node)
        if function is None:
            continue
        uncertain_lines.update(
            (function.path, item.lineno) for item in ast.walk(node) if isinstance(item, ast.Call)
        )
        path_functions.unresolved_paths.add(
            f"{function.path}:{node.lineno}: callable binding for "
            f"{function.lexical_prefixes[0]} may have been rebound by a foreign call"
        )
        unresolved[0] += 1
    accesses = [
        replace(access, bounded=False)
        if (access.path, access.lineno) in uncertain_lines
        else access
        for access in accesses
    ]
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
#: Drained into each report's `errors`. Reset per analysis, unlike the print-dedup set above,
#: whose process lifetime would have made a second analysis in one process silently error-free.
_GLOB_ERRORS: list[str] = []


def _report_glob_error(pattern: str, detail: str) -> None:
    issue = (pattern, detail)
    if issue in _REPORTED_GLOB_ERRORS:
        return
    _REPORTED_GLOB_ERRORS.add(issue)
    # The durable report carried none of this: the JSON said status=complete with an empty errors
    # list while the console showed [REPORT-ERROR], so a reader consuming the artifact rather than
    # the terminal saw a completeness claim the run had already contradicted (review finding,
    # codex, 2026-09-07). A diagnostic that exists only on stdout is a diagnostic the next reader
    # does not get.
    _GLOB_ERRORS.append(f"glob pattern {pattern!r}: {detail}; treated as a no-match")
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


@lru_cache(maxsize=4096)
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
            if pattern.startswith("**/", i):
                out.append("(?:[^/]+/)*")
                i += 3
            else:
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


class GitTracking(NamedTuple):
    """One enumeration: the paths it returned, and whether it happened at all.

    The empty frozenset used to mean three different things — no repository, an `ls-files` that
    failed, and an index that is honestly empty. Every caller only wanted the paths, so the
    collapse cost nothing until the report's provenance began reasoning from emptiness. Then an
    untracked source in a repository whose commit tracks nothing was described as a clean tree
    with a real HEAD, and injecting `ls-files` exit 128 over a genuinely clean tracked fixture had
    the report name a tracked file as UNTRACKED (review findings, cx-blue, 2026-09-07, the second
    against the first repair of the first).

    The status travels WITH the result of the same acquisition, deliberately. A second query
    cannot witness the first: a later success does not certify an earlier empty set as an honest
    index, and an earlier success does not license a later failure. So there is one read, and it
    carries its own outcome.
    """

    paths: frozenset[str]
    enumerated: bool


#: What a caller that did not enumerate knows: nothing, and it says so rather than passing an
#: empty set that would read as "the index is empty".
NO_GIT_TRACKING = GitTracking(frozenset(), False)


def _git_tracking(repo_root: Path) -> GitTracking:
    if not (repo_root / ".git").exists():
        return NO_GIT_TRACKING
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z"],
            check=False,
            capture_output=True,
        )
    except OSError:
        # `_git_head` has always caught this; its sibling did not, so a missing git binary or a
        # fork that could not be made escaped `analyse_consumer_side` as a traceback instead of
        # reaching the report as an unknown (review finding, cx-blue, 2026-09-07). A failure to
        # ASK is the same unknown as a failure to answer.
        return NO_GIT_TRACKING
    if result.returncode != 0:
        return NO_GIT_TRACKING
    return GitTracking(
        frozenset(
            item.decode("utf-8", errors="surrogateescape")
            for item in result.stdout.split(b"\0")
            if item
        ),
        True,
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
        (
            candidate in tracked
            if not any(char in candidate for char in "*?[")
            else any(_glob_match(path, candidate) for path in tracked)
        )
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


@lru_cache(maxsize=4096)
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
    try:
        expanded = Path(value).expanduser().as_posix()
    except RuntimeError as exc:
        # `~someone-who-does-not-exist` raises RuntimeError, and the analysis handler catches
        # OSError/ValueError but not that — so a declared mass location naming an unknown user
        # crashed the run with no `[REPORT-ERROR]` and no remedy (codex, at `45a37aeda`).
        #
        # Converted here rather than by widening that handler to RuntimeError: this is a
        # DECLARED-INPUT failure and belongs in the same class as a malformed frame, while
        # widening the handler would also swallow genuine scanner faults and report them as an
        # incomplete analysis. Failure paths narrow; they do not widen.
        raise ValueError(
            f"declared location {value!r} names a home directory that cannot be resolved "
            f"({exc}); next action: declare an explicit path or a '~/' home-relative one"
        ) from exc
    canonical_repo = (Path.home() / "projects" / "hapax-council").as_posix()
    if expanded == canonical_repo:
        return "."
    if expanded.startswith(canonical_repo + "/"):
        return expanded[len(canonical_repo) + 1 :]
    # Accesses keep the home SYMBOLIC (`~/…`), because this scanner does not know whose home a
    # path will be resolved against. Expanding the declaration against the scanner host's home
    # therefore produced two representations that could never meet, and a home-rooted producer
    # declaration bound none of the home-rooted accesses it selects. Bring the declaration to the
    # accesses' representation instead of the other way round: recognising that `~/x` and this
    # host's `<home>/x` both denote the home is not a claim that every execution host shares it.
    home = Path.home().as_posix()
    if expanded == home:
        return "~"
    if expanded.startswith(home + "/"):
        return "~/" + expanded[len(home) + 1 :]
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
    repo_root: Path,
    frame_path: Path | None,
    decayed_members: list[str],
    *,
    measured_sources: Iterable[Path] = (),
    tracking: GitTracking = NO_GIT_TRACKING,
) -> dict[str, object]:
    head, dirty = _git_head(repo_root)
    # **`dirty` described the commit, not the measurement.** `git status` is asked with
    # `--untracked-files=no`, while the scan walks the filesystem and reads untracked `.py` files
    # like any other — so a report could carry findings from a file in no commit beside
    # `dirty: false`, and a later reader checking out that head would measure a different tree
    # than the report describes (review finding, codex, 2026-09-07).
    #
    # The sources that were actually read decide this, not a second opinion about the tree: any
    # measured file git does not track is named, and its presence makes the tree dirty whatever
    # `status` said about tracked paths.
    #
    # Four outcomes, kept apart, because two repairs died collapsing them (review findings,
    # cx-blue, 2026-09-07, the second against the first):
    #
    #   enumerated, non-empty  -> the list is what git does not track
    #   enumerated, empty      -> a commit that tracks nothing is still a commit; the list stands
    #   NOT enumerated         -> unknown. `null`, never `[]`: an unreadable index is not a clean
    #                             measurement, and inventing a list from it named a tracked file
    #                             as untracked when `ls-files` was made to exit 128
    #   no head                -> nothing is claimed. Not "no repository": an unborn repository
    #                             has no head and is a repository, and a detached or unreadable
    #                             head is a third thing again. What is true of all of them is
    #                             that this consumer has no commit to describe.
    untracked: list[str] | None = (
        sorted(str(path) for path in measured_sources if str(path) not in tracking.paths)
        if head is not None and tracking.enumerated
        else None
    )
    # **`dirty` is three-valued, because it describes the MEASUREMENT and two observations feed
    # it.** An earlier version returned `False` whenever `status` was clean, including when the
    # enumeration had failed — so a report read an untracked source, emitted its finding, and
    # still said `dirty: false` while real git said `?? shared/untracked.py` (review finding,
    # cx-blue, 2026-09-07, against the repair before this one; my own control asserted that
    # `False`, which is the defect pinned in a test).
    #
    # Either observation is sufficient for TRUE. Only both, agreeing, establish FALSE. Anything
    # less is unknown, and unknown is `None` — a report claiming a clean measurement is making a
    # claim, and one unreadable half does not support it.
    if dirty is True or untracked:
        measurement_dirty: bool | None = True
    elif dirty is False and untracked == []:
        measurement_dirty = False
    else:
        measurement_dirty = None
    epoch = frame_path.expanduser().absolute().parent.name if frame_path is not None else None
    return {
        "instrument_rev": "check-producer-consumers/consumer-side/1",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo_root": str(repo_root),
        "head": head,
        "dirty": measurement_dirty,
        "untracked_sources": untracked,
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
    tracking = _git_tracking(repo_root)
    tracked = tracking.paths
    _REPORTED_GLOB_ERRORS.clear()
    _GLOB_ERRORS.clear()
    # `_glob_regex` is memoised, so a second analysis in one process never re-enters the
    # translator and would have produced a report with no error where the first had one. The
    # cache is an optimisation; the report's completeness is a claim, and the claim wins.
    _glob_regex.cache_clear()
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
        # The SAME artifact-identity relation, on the writers this scanner located and then
        # declined to certify. Not a basename test and not "any unknown writer anywhere" —
        # either of those would let an uncertain unrelated writer clear a definite unmatched
        # reader, which is the failure the same-basename control below exists to catch.
        uncertain_matching = [
            writer
            for writer in writes
            if not writer.bounded and _accesses_match(representative, writer)
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
            elif uncertain_matching:
                # Last before the absence verdict, so the classifications that carry their own
                # honest uncertainty keep it: a dynamic root, a non-Python producer and a
                # documented-elsewhere mention are all decided above and are not narrowed here.
                # This branch refines only the bare "nothing writes it" case, which is the one
                # that was asserting more than the evidence held.
                kind = "consumer-reads-artifact-with-unresolved-writer"
                detail = (
                    "writer located and not certified; execution of the write site is "
                    f"undetermined (candidates={len(uncertain_matching)}); "
                    "resolve the guard or the source that makes the site undecidable, or "
                    "confirm the reader tolerates the artifact being absent"
                )
                # The ACTUAL candidate sites, not the nearest-by-distance guess used for a true
                # absence: here the writers are known, and naming them is the whole point.
                nearest = tuple(uncertain_matching[:3])
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
                and any(not reader.bounded for reader in reader_sites)
            )
        ]
        for reader in reader_sites:
            pairs.extend(
                ArtifactPair(reader.family, reader, writer)
                for writer in paired
                if (writer.bounded or not reader.bounded)
                and _specific_pair_identity(reader, writer, imports_by_path)
            )
        divergent_writers = [
            writer
            for writer in identity_writers
            if writer.bounded
            and any(reader.bounded for reader in reader_sites)
            and not _accesses_match(representative, writer)
        ]
        if divergent_writers and not paired:
            kind = "consumer-producer-path-mismatch"
            findings.append(
                ConsumerSideFinding(
                    kind,
                    reader_sites[:3],
                    _nearest_writers(representative, divergent_writers),
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
        measured=measured_provenance(
            repo_root,
            frame_path,
            decayed_member_ids,
            # What the scan actually read: every source that parsed, plus every one it could not.
            measured_sources=[*imports_by_path, *(gap.path for gap in source_gaps)],
            tracking=tracking,
        ),
        errors=tuple(
            [
                f"{gap.path}: {gap.operation} failed ({gap.error_class})"
                for gap in dict.fromkeys(source_gaps)
            ]
            + list(dict.fromkeys(_GLOB_ERRORS))
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
    # **The next action has to belong to the KIND, and for the new one it did not.** The weaker
    # finding's detail said the writer was located and its execution undetermined, and then this
    # line told the reader to "bind the consumer to a live producer output" — the one instruction
    # the coordinator ruled out for it, because the producer already exists and is named right
    # there in `nearest-writers`. A remedy that contradicts its own diagnosis two fields later is
    # worse than a generic one (review finding, root, at `7a4b8ceaf`).
    if finding.kind == "consumer-reads-through-unmodelled-api":
        next_action = "model the named callee's file-access semantics, then rerun"
    elif finding.kind == "consumer-reads-artifact-with-unresolved-writer":
        next_action = (
            "decide the guard or source that leaves the named writer's execution undetermined, "
            "or record that the reader tolerates the artifact being absent; a candidate producer "
            "is already named above, so adding one is not the first step here"
        )
        # Scoped to THIS finding rather than stated as a rule. "do NOT add a producer" was
        # categorical, and a located undecidable writer does not prove that writer suffices for
        # every actual demand — a reader may legitimately need one this site cannot supply
        # (coordinator correction, at `448edef1a`). What the remedy owes is that a producer is
        # already named, so nobody is sent looking for something the report is holding.
    else:
        next_action = (
            "bind the consumer to a live producer output or add a reasoned "
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
        "consumer-reads-artifact-with-unresolved-writer="
        f"{counts['consumer-reads-artifact-with-unresolved-writer']} "
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
        f"[CAPPED] {site}"
        + (
            ""
            if "binding state cap" in site
            else ": compact expression union; concrete alternatives retained"
        )
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
    next_action = "repair or drop the input the message names (--frame, --mass or the allowlist)"
    try:
        allowlist = load_allowlist(args.allowlist)
        report = analyse_consumer_side(
            repo_root,
            allowlist,
            frame_path=args.frame,
            mass_path=args.mass,
        )
    except (
        AllowlistError,
        OSError,
        ValueError,
        json.JSONDecodeError,
        yaml.YAMLError,
        RecursionError,
    ) as exc:
        if isinstance(exc, RecursionError):
            # Recursive AST walkers need not all carry a path. Their nearest enclosing
            # scanner frame does; walk the traceback iteratively after stack unwinding.
            source = "<unknown source>"
            trace = exc.__traceback__
            while trace is not None:
                if trace.tb_frame.f_code.co_filename == __file__:
                    for name in ("source_path", "relative", "path"):
                        candidate = trace.tb_frame.f_locals.get(name)
                        if isinstance(candidate, Path):
                            source = str(candidate)
                trace = trace.tb_next
            exc = RecursionError(f"{source}: scanner recursion exhausted (RecursionError)")
            next_action = f"simplify deeply nested expressions in {source}"
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
            f"[REPORT-ERROR] {analysis_error}; next action: {next_action} "
            "and rerun; the gate stays report-only"
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
