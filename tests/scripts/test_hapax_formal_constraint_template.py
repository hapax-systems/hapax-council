"""CLI tests for scripts/hapax-formal-constraint-template."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-formal-constraint-template"


def _args() -> list[str]:
    return [
        "--constraint-id",
        "CONSTRAINT-template",
        "--title",
        "Template constraint",
        "--scope-type",
        "surface",
        "--scope-ref",
        "sbcl-clog-control-surface",
        "--effect",
        "hold",
        "--reason",
        "test reason",
        "--created-at",
        "2026-05-17T08:40:00Z",
    ]


def test_prints_schema_valid_draft_frontmatter() -> None:
    result = subprocess.run([str(SCRIPT), *_args()], text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
    frontmatter = result.stdout.split("---", 2)[1]
    payload = yaml.safe_load(frontmatter)
    assert payload["type"] == "formal-constraint"
    assert payload["lifecycle_state"] == "draft"
    assert payload["effect"] == "hold"
    assert payload["authority"] == "gate"


def test_writes_to_explicit_output_only(tmp_path: Path) -> None:
    output = tmp_path / "draft.md"

    result = subprocess.run(
        [str(SCRIPT), *_args(), "--output", str(output)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert output.exists()
    assert "lifecycle_state: draft" in output.read_text(encoding="utf-8")
