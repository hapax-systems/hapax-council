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
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

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
        entries.append(AllowlistEntry(str(raw["pattern"]), str(raw["reason"])))
    return entries


def is_allowlisted(key: str, path: Path, entries: list[AllowlistEntry]) -> AllowlistEntry | None:
    for entry in entries:
        if fnmatch.fnmatch(key, entry.pattern) or fnmatch.fnmatch(str(path), entry.pattern):
            return entry
    return None


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
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=DEFAULT_ALLOWLIST_PATH,
        help="JSON allowlist of intentional consumer-less producers (reason required)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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
