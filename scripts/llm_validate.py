#!/usr/bin/env python3
"""METADATA.yaml validator.

Validates METADATA.yaml files against the JSON Schema and checks the
self-contained invariant (dependencies.internal == []).

Usage::

    uv run python scripts/llm_validate.py
    uv run python scripts/llm_validate.py --compare-baseline
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "metadata.schema.json"
BASELINE_PATH = PROJECT_ROOT / "profiles" / "token-baseline.json"
TOKENS_PER_LINE_PY = 10


@dataclass
class ValidationResult:
    path: str
    valid: bool
    self_contained: bool
    token_budget: int
    errors: list[str] = field(default_factory=list)


def load_schema() -> dict[str, Any]:
    """Load JSON Schema from schemas/metadata.schema.json."""
    with SCHEMA_PATH.open() as f:
        return json.load(f)


def validate_metadata(
    metadata: dict[str, Any],
    schema: dict[str, Any] | None = None,
    path: str = "",
) -> ValidationResult:
    """Validate a metadata dict against the JSON Schema.

    Returns a ValidationResult with valid, self_contained, token_budget, and errors.
    """
    if schema is None:
        schema = load_schema()

    errors: list[str] = []

    validator = jsonschema.Draft7Validator(schema)
    for error in sorted(validator.iter_errors(metadata), key=lambda e: list(e.absolute_path)):
        # Build a human-readable path to the failing field
        path_parts = list(error.absolute_path)
        field_path = ".".join(str(p) for p in path_parts) if path_parts else error.schema_path[-1]
        errors.append(f"{field_path}: {error.message}")

    valid = len(errors) == 0

    # Self-contained: dependencies.internal must be empty
    internal_deps: list[str] = []
    if isinstance(metadata.get("dependencies"), dict):
        internal_deps = metadata["dependencies"].get("internal", [])
    self_contained = isinstance(internal_deps, list) and len(internal_deps) == 0

    token_budget = 0
    if isinstance(metadata.get("token_budget"), dict):
        token_budget = metadata["token_budget"].get("self", 0) or 0

    return ValidationResult(
        path=path,
        valid=valid,
        self_contained=self_contained,
        token_budget=token_budget,
        errors=errors,
    )


def find_metadata_files() -> list[Path]:
    """Find all METADATA.yaml files under PROJECT_ROOT."""
    return sorted(PROJECT_ROOT.rglob("METADATA.yaml"))


def calculate_package_tokens(metadata_path: Path) -> int:
    """Count tokens for all .py files in the same directory as the METADATA.yaml."""
    package_dir = metadata_path.parent
    total_lines = 0
    for py_file in sorted(package_dir.glob("*.py")):
        try:
            lines = py_file.read_text(encoding="utf-8").splitlines()
            total_lines += len(lines)
        except OSError:
            pass
    return total_lines * TOKENS_PER_LINE_PY


def validate_all() -> list[ValidationResult]:
    """Validate all METADATA.yaml files found under PROJECT_ROOT."""
    schema = load_schema()
    results: list[ValidationResult] = []

    for meta_path in find_metadata_files():
        try:
            raw = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
        except Exception as exc:
            results.append(
                ValidationResult(
                    path=str(meta_path.relative_to(PROJECT_ROOT)),
                    valid=False,
                    self_contained=False,
                    token_budget=0,
                    errors=[f"YAML parse error: {exc}"],
                )
            )
            continue

        rel_path = str(meta_path.relative_to(PROJECT_ROOT))
        result = validate_metadata(raw or {}, schema=schema, path=rel_path)

        # Override token_budget with measured value if not already set in file
        if result.token_budget == 0:
            result.token_budget = calculate_package_tokens(meta_path)

        results.append(result)

    return results


def compare_baseline(results: list[ValidationResult]) -> list[str]:
    """Compare current token budgets against saved baseline.

    Returns a list of human-readable delta lines.
    """
    if not BASELINE_PATH.exists():
        return ["No baseline found at " + str(BASELINE_PATH)]

    try:
        baseline: dict[str, Any] = json.loads(BASELINE_PATH.read_text())
    except Exception as exc:
        return [f"Could not read baseline: {exc}"]

    # baseline format expected: {"modules": {"path": {"token_budget": N}}}
    baseline_modules: dict[str, Any] = baseline.get("modules", {})

    lines: list[str] = []
    for result in results:
        baseline_entry = baseline_modules.get(result.path, {})
        baseline_tokens = baseline_entry.get("token_budget", None)
        if baseline_tokens is None:
            lines.append(f"  NEW  {result.path}: {result.token_budget} tokens")
        else:
            delta = result.token_budget - baseline_tokens
            sign = "+" if delta >= 0 else ""
            status = "OK  " if delta == 0 else "DIFF"
            lines.append(f"  {status} {result.path}: {result.token_budget} tokens ({sign}{delta})")

    return lines


def format_report(results: list[ValidationResult]) -> str:
    """Return a human-readable validation report."""
    lines: list[str] = []

    valid_count = sum(1 for r in results if r.valid)
    self_contained_count = sum(1 for r in results if r.self_contained)
    total = len(results)

    lines.append(
        f"METADATA Validation Report: {valid_count}/{total} valid, "
        f"{self_contained_count}/{total} self-contained"
    )
    lines.append("")

    for result in results:
        status = "OK" if result.valid else "FAIL"
        sc = "SC" if result.self_contained else "  "
        lines.append(
            f"  [{status}][{sc}] {result.path or '(inline)'} (budget: {result.token_budget})"
        )
        for err in result.errors:
            lines.append(f"         ERROR: {err}")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate METADATA.yaml files")
    parser.add_argument(
        "--compare-baseline",
        action="store_true",
        help="Compare token budgets against saved baseline",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    args = parser.parse_args()

    results = validate_all()

    if args.json:
        import dataclasses

        print(json.dumps([dataclasses.asdict(r) for r in results], indent=2))
    else:
        print(format_report(results))

    if args.compare_baseline:
        print("\nBaseline Comparison:")
        for line in compare_baseline(results):
            print(line)

    # Exit non-zero if any invalid
    any_invalid = any(not r.valid for r in results)
    if any_invalid:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
