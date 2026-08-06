from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PACKAGE_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from hapax_agentic_trust import (  # noqa: E402
    VerifiedTerminalProjection,
    verify_terminal_projection,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "golden-terminal-v3"


def materialize_golden_terminal(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "golden-terminal-v3"
    shutil.copytree(FIXTURE_ROOT / "store", root)
    for path in root.rglob("*"):
        if path.is_file():
            path.chmod(0o400)
    anchors = json.loads((FIXTURE_ROOT / "anchors.json").read_text(encoding="utf-8"))
    return root, anchors


@pytest.fixture
def golden_terminal(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    return materialize_golden_terminal(tmp_path)


@pytest.fixture
def anchored_projection(
    golden_terminal: tuple[Path, dict[str, str]],
) -> VerifiedTerminalProjection:
    root, anchors = golden_terminal
    return verify_terminal_projection(
        root,
        "terminal/bundle.json",
        expected_bundle_sha256=anchors["bundle_sha256"],
        expected_evidence_root_sha256=anchors["evidence_root_sha256"],
        expected_manifest_snapshot_artifact_sha256=anchors["manifest_snapshot_artifact_sha256"],
    )
