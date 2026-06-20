from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.shared.test_hkp_bundle_schema import write_bundle

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-hkp-validate"


def test_cli_json_success(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(bundle), "--json"],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["findings"] == []
    assert payload["validator_version"] == "0.2.0"


def test_cli_returns_nonzero_for_governed_error(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path, body="[missing](missing.md)\n")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(bundle), "--json"],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["findings"][0]["code"] == "broken_markdown_link"


def test_cli_research_mode_keeps_broken_links_as_warning(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path, body="[missing](missing.md)\n")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(bundle), "--mode", "research", "--json"],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["findings"][0]["severity"] == "warning"


def test_cli_human_readable_failure_includes_next_action(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path, body="[missing](missing.md)\n")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(bundle)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert result.stdout.splitlines()[0].startswith("FAIL ")
    assert "next-action\tfix findings below or rerun with --json" in result.stdout
    assert "error\tbroken_markdown_link" in result.stdout
