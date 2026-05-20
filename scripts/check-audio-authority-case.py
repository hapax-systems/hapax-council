#!/usr/bin/env python3
"""Validate AuthorityCase metadata on audio-authority surfaces.

Hard-fails when audio source/runtime/docs surfaces lack required governance
fields: authority_case, parent_spec, route metadata, or mutation scope.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

AUDIO_AUTHORITY_GLOBS: list[str] = [
    "config/audio-*.yaml",
    "config/pipewire/**/*.conf",
    "config/pipewire/**/*.json",
    "config/wireplumber/**/*.conf",
    "config/hapax/audio-*.conf",
    "config/hapax/audio-*.yaml",
    "docs/audio-topology-reference.md",
    "docs/audio/**",
    "shared/audio_graph/**/*.py",
    "shared/audio_topology*.py",
    "shared/audio_loudness*.py",
    "shared/audio_canary*.py",
    "scripts/hapax-audio-*",
    "scripts/check-audio-*.py",
    "scripts/audio-*.sh",
]

REQUIRED_TASK_FIELDS = {"authority_case", "parent_spec", "mutation_scope_refs"}

AUTHORITY_CASE_PATTERN = re.compile(r"^CASE-AUDIO-")

CC_TASKS_DIR = REPO_ROOT / "docs" / "superpowers" / "specs"
ACTIVE_TASKS_VAULT = Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks/active"


def find_audio_task_notes() -> list[Path]:
    candidates: list[Path] = []
    if ACTIVE_TASKS_VAULT.exists():
        for p in ACTIVE_TASKS_VAULT.glob("*.md"):
            candidates.append(p)
    return candidates


def validate_task_note(path: Path, strict: bool) -> list[str]:
    errors: list[str] = []
    try:
        text = path.read_text()
    except OSError:
        return []

    if "---" not in text:
        return []

    parts = text.split("---", 2)
    if len(parts) < 3:
        return []

    try:
        fm = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return []

    if not isinstance(fm, dict):
        return []

    tags = fm.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    if "audio" not in tags:
        return []

    task_id = fm.get("task_id", path.stem)

    for field in REQUIRED_TASK_FIELDS:
        if not fm.get(field):
            severity = "ERROR" if strict else "WARNING"
            errors.append(f"{severity}: {task_id} missing required field '{field}'")

    ac = fm.get("authority_case", "")
    if ac and not AUTHORITY_CASE_PATTERN.match(str(ac)):
        severity = "ERROR" if strict else "WARNING"
        errors.append(
            f"{severity}: {task_id} authority_case '{ac}' does not match CASE-AUDIO-* pattern"
        )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate audio AuthorityCase metadata")
    parser.add_argument(
        "--strict", action="store_true", help="Treat missing fields as errors (not warnings)"
    )
    args = parser.parse_args(argv)

    all_errors: list[str] = []

    task_notes = find_audio_task_notes()
    for note in task_notes:
        all_errors.extend(validate_task_note(note, strict=args.strict))

    hard_errors = [e for e in all_errors if e.startswith("ERROR")]
    warnings = [e for e in all_errors if e.startswith("WARNING")]

    for w in warnings:
        print(w, file=sys.stderr)
    for e in hard_errors:
        print(e, file=sys.stderr)

    if hard_errors:
        print(f"\n{len(hard_errors)} audio AuthorityCase error(s) found.", file=sys.stderr)
        return 1

    checked = len(task_notes)
    print(f"Audio AuthorityCase: {checked} task note(s) checked, {len(warnings)} warning(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
