#!/usr/bin/env python3
"""Generate bare-minimum METADATA.yaml files for agents missing manifests."""

from __future__ import annotations

import argparse
import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AGENTS_DIR = REPO_ROOT / "agents"
DEFAULT_SYSTEMD_DIR = REPO_ROOT / "systemd"
MANIFEST_NAME = "METADATA.yaml"
AGENT_MODULE_RE = re.compile(r"\bagents\.([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)")


@dataclass(frozen=True)
class SystemdHint:
    unit_name: str
    description: str | None = None


@dataclass
class AgentCandidate:
    module: str
    manifest_path: Path
    source_paths: set[Path] = field(default_factory=set)
    systemd_hints: list[SystemdHint] = field(default_factory=list)

    @property
    def has_manifest(self) -> bool:
        return self.manifest_path.exists()


def _is_agent_module_name(name: str) -> bool:
    return not name.startswith("_") and name not in {"__init__", "__main__"}


def _module_root(module_path: str) -> str:
    return module_path.split(".", maxsplit=1)[0]


def _read_unit_description(path: Path) -> str | None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("Description="):
                return line.split("=", maxsplit=1)[1].strip() or None
    except OSError:
        return None
    return None


def discover_systemd_hints(systemd_dir: Path) -> dict[str, list[SystemdHint]]:
    hints: dict[str, list[SystemdHint]] = {}
    for unit_path in sorted(systemd_dir.rglob("*.service")):
        try:
            text = unit_path.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in AGENT_MODULE_RE.finditer(text):
            root = _module_root(match.group(1))
            if not _is_agent_module_name(root):
                continue
            hints.setdefault(root, []).append(
                SystemdHint(
                    unit_name=unit_path.name,
                    description=_read_unit_description(unit_path),
                )
            )
    return hints


def discover_agent_candidates(agents_dir: Path, systemd_dir: Path) -> list[AgentCandidate]:
    by_module: dict[str, AgentCandidate] = {}
    systemd_hints = discover_systemd_hints(systemd_dir)

    for module_path in sorted(agents_dir.glob("*.py")):
        module = module_path.stem
        if not _is_agent_module_name(module):
            continue
        candidate = by_module.setdefault(
            module,
            AgentCandidate(module=module, manifest_path=agents_dir / module / MANIFEST_NAME),
        )
        candidate.source_paths.add(module_path)

    for package_dir in sorted(path for path in agents_dir.iterdir() if path.is_dir()):
        module = package_dir.name
        if not _is_agent_module_name(module):
            continue
        if not any(package_dir.glob("*.py")) and not (package_dir / MANIFEST_NAME).exists():
            continue
        candidate = by_module.setdefault(
            module,
            AgentCandidate(module=module, manifest_path=package_dir / MANIFEST_NAME),
        )
        candidate.source_paths.update(package_dir.glob("*.py"))

    for module, hints in systemd_hints.items():
        if module in by_module:
            by_module[module].systemd_hints.extend(hints)

    return sorted(by_module.values(), key=lambda candidate: candidate.module)


def _source_docstring(path: Path) -> str | None:
    try:
        module = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None
    docstring = ast.get_docstring(module)
    if docstring is None:
        return None
    first_line = docstring.strip().splitlines()[0].strip()
    return first_line or None


def infer_description(candidate: AgentCandidate) -> str:
    for hint in candidate.systemd_hints:
        if hint.description:
            return hint.description
    for path in sorted(candidate.source_paths):
        docstring = _source_docstring(path)
        if docstring:
            return docstring
    return f"Module {candidate.module}"


def infer_tier_and_maturity(candidate: AgentCandidate) -> tuple[int, str]:
    if candidate.systemd_hints:
        return 2, "beta"
    return 3, "experimental"


def _display_path(path: Path) -> str:
    absolute_path = path if path.is_absolute() else (Path.cwd() / path)
    try:
        return absolute_path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def build_manifest(candidate: AgentCandidate, agents_dir: Path) -> dict[str, Any]:
    tier, maturity = infer_tier_and_maturity(candidate)
    source_paths = sorted(_display_path(path) for path in candidate.source_paths)
    manifest: dict[str, Any] = {
        "module": candidate.module,
        "purpose": infer_description(candidate),
        "version": 1,
        "tier": tier,
        "maturity": maturity,
        "structure": {},
        "interface": {},
        "dependencies": {"runtime": [], "internal": []},
        "execution": {"entry": f"uv run python -m agents.{candidate.module}"},
    }

    package_dir = agents_dir / candidate.module
    if package_dir.exists() and any(package_dir.glob("*.py")):
        manifest["structure"]["package"] = f"agents/{candidate.module}/"
    if source_paths:
        manifest["structure"]["source"] = source_paths
    if candidate.systemd_hints:
        manifest["execution"]["systemd_units"] = [
            hint.unit_name
            for hint in sorted(candidate.systemd_hints, key=lambda hint: hint.unit_name)
        ]
    return manifest


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing manifest: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")


def missing_candidates(agents_dir: Path, systemd_dir: Path) -> list[AgentCandidate]:
    return [
        candidate
        for candidate in discover_agent_candidates(agents_dir, systemd_dir)
        if not candidate.has_manifest
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate bare-minimum agents/<module>/METADATA.yaml files for modules "
            "that do not already have one."
        )
    )
    parser.add_argument("--agents-dir", type=Path, default=DEFAULT_AGENTS_DIR)
    parser.add_argument("--systemd-dir", type=Path, default=DEFAULT_SYSTEMD_DIR)
    parser.add_argument(
        "--write",
        action="store_true",
        help="write missing manifests; default is a dry-run listing",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    candidates = missing_candidates(args.agents_dir, args.systemd_dir)

    action = "writing" if args.write else "dry-run"
    print(f"{action}: {len(candidates)} missing agent manifest(s)")
    for candidate in candidates:
        manifest = build_manifest(candidate, args.agents_dir)
        rel_path = _display_path(candidate.manifest_path)
        print(f"- {rel_path} ({manifest['maturity']}, tier {manifest['tier']})")
        if args.write:
            write_manifest(candidate.manifest_path, manifest)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
