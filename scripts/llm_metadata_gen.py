"""llm_metadata_gen.py — Generate draft METADATA.yaml files from Python source analysis.

Parses Python source to produce structured metadata matching the schemas/metadata.schema.json
format. Useful for bootstrapping METADATA.yaml files across the agents/ directory.

Usage:
    uv run python -m scripts.llm_metadata_gen agents.drift_detector
    uv run python -m scripts.llm_metadata_gen --all-agents
    uv run python -m scripts.llm_metadata_gen --all-agents --write
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOKENS_PER_LINE = 10

# Internal module prefixes — imports from these are "internal" deps
_INTERNAL_PREFIXES = ("shared", "agents", "logos")

# Heuristic: class names containing these strings → output models
_OUTPUT_INDICATORS = ("Report", "Result", "Output", "Response")


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _module_to_paths(module_name: str) -> list[Path]:
    """Resolve a dotted module name to its Python file(s).

    Handles both single-file modules (agents/foo.py) and packages
    (agents/foo/__init__.py + siblings).
    """
    parts = module_name.split(".")
    # Try package directory first
    pkg_dir = PROJECT_ROOT.joinpath(*parts)
    if pkg_dir.is_dir():
        return sorted(pkg_dir.rglob("*.py"))
    # Try single file
    single = PROJECT_ROOT.joinpath(*parts).with_suffix(".py")
    if single.is_file():
        return [single]
    # Fallback: search agents/ for the leaf name
    leaf = parts[-1]
    candidates = list(PROJECT_ROOT.glob(f"agents/{leaf}.py"))
    if candidates:
        return candidates
    return []


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _parse_file(filepath: Path) -> ast.Module | None:
    """Parse a Python file, returning the AST or None on error."""
    try:
        source = filepath.read_text(encoding="utf-8")
        return ast.parse(source, filename=str(filepath))
    except (SyntaxError, OSError):
        return None


def _extract_docstring(filepath: Path) -> str:
    """Extract the module-level docstring from a Python file."""
    tree = _parse_file(filepath)
    if tree is None:
        return ""
    return ast.get_docstring(tree) or ""


def _extract_pydantic_models(filepath: Path) -> list[dict]:
    """Find BaseModel subclasses and extract their fields.

    Returns a list of dicts with keys: name, fields, is_output.
    """
    tree = _parse_file(filepath)
    if tree is None:
        return []

    models: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        # Check if it inherits from BaseModel (by name, not resolution)
        base_names = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                base_names.append(base.id)
            elif isinstance(base, ast.Attribute):
                base_names.append(base.attr)
        if "BaseModel" not in base_names:
            continue

        is_output = any(ind in node.name for ind in _OUTPUT_INDICATORS)
        fields: list[dict] = []
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                field_name = item.target.id
                # Represent the annotation as a string
                field_type = ast.unparse(item.annotation)
                fields.append({"name": field_name, "type": field_type})

        models.append({"name": node.name, "fields": fields, "is_output": is_output})

    return models


def _extract_imports(filepath: Path) -> tuple[list[str], list[str]]:
    """Extract runtime and internal deps from a Python file.

    Returns (runtime_deps, internal_deps).
    - internal_deps: imports starting with shared/agents/logos
    - runtime_deps: top-level package name of other third-party imports
    """
    tree = _parse_file(filepath)
    if tree is None:
        return [], []

    stdlib_modules: set[str] = {
        "abc",
        "argparse",
        "asyncio",
        "ast",
        "collections",
        "contextlib",
        "dataclasses",
        "datetime",
        "enum",
        "functools",
        "hashlib",
        "http",
        "importlib",
        "inspect",
        "io",
        "itertools",
        "json",
        "logging",
        "math",
        "os",
        "pathlib",
        "re",
        "shutil",
        "signal",
        "socket",
        "subprocess",
        "sys",
        "tempfile",
        "textwrap",
        "threading",
        "time",
        "traceback",
        "types",
        "typing",
        "unittest",
        "urllib",
        "uuid",
        "warnings",
        "weakref",
        "__future__",
    }

    runtime: set[str] = set()
    internal: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in stdlib_modules:
                    continue
                if any(alias.name.startswith(p) for p in _INTERNAL_PREFIXES):
                    internal.add(alias.name.split(".")[0])
                else:
                    runtime.add(top)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            top = node.module.split(".")[0]
            if top in stdlib_modules:
                continue
            if any(node.module.startswith(p) for p in _INTERNAL_PREFIXES):
                internal.add(top)
            else:
                runtime.add(top)

    return sorted(runtime), sorted(internal)


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------


def _count_tokens(paths: list[Path]) -> int:
    """Estimate token count: non-empty, non-comment lines * TOKENS_PER_LINE."""
    total = 0
    for path in paths:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    total += 1
        except OSError:
            pass
    return total * TOKENS_PER_LINE


# ---------------------------------------------------------------------------
# Execution detection
# ---------------------------------------------------------------------------


def _detect_execution(module_name: str, filepath: Path) -> dict:
    """Build the execution dict: entry point, flags, environment."""
    entry = f"uv run python -m {module_name}"
    flags: list[dict] = []
    env: dict[str, str] = {}

    tree = _parse_file(filepath)
    if tree is not None:
        for node in ast.walk(tree):
            # Detect argparse add_argument calls
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
            ):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        flag_name = arg.value
                        if flag_name.startswith("-"):
                            flags.append({"name": flag_name})

    # Check for a systemd timer
    timer_name = module_name.replace("agents.", "").replace("_", "-")
    timer_path = PROJECT_ROOT / "systemd" / f"hapax-{timer_name}.timer"
    if timer_path.exists():
        env["SYSTEMD_TIMER"] = f"hapax-{timer_name}.timer"

    result: dict = {"entry": entry}
    if flags:
        # Deduplicate preserving order
        seen: set[str] = set()
        unique_flags: list[dict] = []
        for f in flags:
            if f["name"] not in seen:
                seen.add(f["name"])
                unique_flags.append(f)
        result["flags"] = unique_flags
    if env:
        result["environment"] = env

    return result


# ---------------------------------------------------------------------------
# Purpose extraction
# ---------------------------------------------------------------------------


def _extract_purpose(module_name: str, docstring: str) -> str:
    """Derive a concise purpose string from the module docstring."""
    if not docstring:
        return f"Module {module_name.split('.')[-1]}"
    # Take first non-empty line
    first_line = ""
    for line in docstring.splitlines():
        stripped = line.strip()
        if stripped:
            first_line = stripped
            break
    if not first_line:
        return f"Module {module_name.split('.')[-1]}"

    # Strip common "filename.py — " prefix patterns
    leaf = module_name.split(".")[-1]
    for prefix in (f"{leaf}.py — ", f"{leaf}.py: ", f"{leaf} — ", f"{leaf}: "):
        if first_line.startswith(prefix):
            first_line = first_line[len(prefix) :]
            break

    # Truncate to schema max of 200 chars
    return first_line[:200]


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------


def generate_metadata_for_module(module_name: str) -> dict:
    """Generate a METADATA.yaml-compatible dict for the given module.

    Args:
        module_name: Dotted Python module name, e.g. "agents.drift_detector".

    Returns:
        Dict matching the schemas/metadata.schema.json structure.
    """
    paths = _module_to_paths(module_name)

    # Primary file for docstring / execution detection
    primary = paths[0] if paths else None

    # Docstring → purpose
    docstring = _extract_docstring(primary) if primary else ""
    purpose = _extract_purpose(module_name, docstring)

    # Collect deps across all files
    all_runtime: set[str] = set()
    all_internal: set[str] = set()
    for path in paths:
        rt, intern = _extract_imports(path)
        all_runtime.update(rt)
        all_internal.update(intern)

    # Collect pydantic models across all files
    inputs: list[dict] = []
    outputs: list[dict] = []
    for path in paths:
        for model in _extract_pydantic_models(path):
            for field in model["fields"]:
                entry = {"name": field["name"], "type": field["type"]}
                if model["is_output"]:
                    outputs.append(entry)
                else:
                    inputs.append(entry)

    # Token budget
    token_self = _count_tokens(paths)

    # Execution
    execution = (
        _detect_execution(module_name, primary)
        if primary
        else {"entry": f"uv run python -m {module_name}"}
    )

    # Leaf module name
    leaf_name = module_name.split(".")[-1]

    result: dict = {
        "module": leaf_name,
        "purpose": purpose,
        "version": 1,
        "interface": {},
        "dependencies": {
            "runtime": sorted(all_runtime),
            "internal": sorted(all_internal),
        },
        "execution": execution,
        "token_budget": {
            "self": token_self,
            "note": f"Estimated from {len(paths)} source file(s) at {TOKENS_PER_LINE} tokens/line",
        },
    }

    if inputs:
        result["interface"]["inputs"] = inputs
    if outputs:
        result["interface"]["outputs"] = outputs

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate draft METADATA.yaml files from Python source analysis."
    )
    parser.add_argument(
        "module",
        nargs="?",
        help="Dotted module name, e.g. agents.drift_detector",
    )
    parser.add_argument(
        "--all-agents",
        action="store_true",
        help="Process all modules under agents/",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write METADATA.yaml to the module's directory",
    )
    args = parser.parse_args()

    if args.all_agents:
        agents_dir = PROJECT_ROOT / "agents"
        modules: list[str] = []
        # Single-file agents
        for p in sorted(agents_dir.glob("*.py")):
            if p.name.startswith("_"):
                continue
            modules.append(f"agents.{p.stem}")
        # Package agents
        for p in sorted(agents_dir.iterdir()):
            if p.is_dir() and (p / "__init__.py").exists():
                modules.append(f"agents.{p.name}")
    elif args.module:
        modules = [args.module]
    else:
        parser.print_help()
        sys.exit(1)

    for module_name in modules:
        metadata = generate_metadata_for_module(module_name)
        if args.write:
            paths = _module_to_paths(module_name)
            if paths:
                # Write to the directory containing the module
                target_dir = paths[0].parent
                out_path = target_dir / "METADATA.yaml"
                out_path.write_text(yaml.dump(metadata, sort_keys=False, allow_unicode=True))
                print(f"Written: {out_path}")
            else:
                print(f"WARNING: Could not resolve paths for {module_name}", file=sys.stderr)
        else:
            print(f"# {module_name}")
            print(yaml.dump(metadata, sort_keys=False, allow_unicode=True))


if __name__ == "__main__":
    main()
