"""cc-stage-advance × adoptability teeth (ADOPTABILITY-DETERMINATION-20260916 §7, A2).

A garage-door row cannot leave S1 without its receipts; BACKED-and-usable prior art
converts it to ``kind: contribution`` and then advances. Same harness shape as
tests/test_cc_stage_advance.py (pinned HOME, subprocess, coord dir redirected).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml

SCRIPT = Path(__file__).parent.parent / "scripts" / "cc-stage-advance"
INSTALL_LINE = "curl -fsSL https://example.org/tool/install.sh | sh"


def _block() -> dict:
    return {
        "prior_art_receipt": "receipts/prior-art.yaml",
        "demand_receipt": "receipts/demand.yaml",
        "install_line": INSTALL_LINE,
        "platforms": ["linux"],
        "zero_config": True,
        "ttfv_seconds": 30,
        "replaces_nothing": True,
        "api": "cli",
        "licence": "Apache-2.0",
        "repo_open": "acme/tool",
        "release_notes": "https://github.com/acme/tool/releases",
        "compare_page": "https://example.org/compare",
        "operator_voice_post": "https://example.org/post",
    }


def _make_garage_door_task(home: Path, task_id: str, *, kind: str = "engineering") -> Path:
    active = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    active.mkdir(parents=True, exist_ok=True)
    note = active / f"{task_id}-x.md"
    front = {
        "type": "cc-task",
        "task_id": task_id,
        "title": "T",
        "status": "offered",
        "assigned_to": "unassigned",
        "kind": kind,
        "authority_case": "CASE-TEST-001",
        "stage": "S1_OFFERED",
        "tags": ["cc-task", "garage-door"],
        "adoptability": _block(),
        "updated_at": "2026-01-01T00:00:00Z",
    }
    note.write_text(
        "---\n" + yaml.safe_dump(front, sort_keys=False) + "---\n\n# T\n\n## Session log\n"
    )
    return note


def _write_receipts(home: Path, *, verdict: str = "UNBACKED", usable: bool = True) -> None:
    receipts = home / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    prior_art = {
        "search_shapes": [
            {"shape": "github_code_search", "query": "lifecycle hooks idle working blocked"},
            {"shape": "package_registry", "query": "claude status reporter"},
        ],
        "verdict": verdict,
    }
    if verdict == "BACKED":
        prior_art.update(
            {"tier": "1", "source": "daocoding/herdr-claude-lifecycle", "usable": usable}
        )
    (receipts / "prior-art.yaml").write_text(yaml.safe_dump(prior_art))
    (receipts / "demand.yaml").write_text(yaml.safe_dump({"asked_by": ["issue #12"]}))


def _run(home: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["HAPAX_AGENT_ROLE"] = "alpha"
    env["HAPAX_COORD_DIR"] = str(home / ".cache" / "hapax" / "coord")
    env["HAPAX_AUTHORITY_CASE_LEDGER"] = str(home / ".cache" / "hapax" / "ledger.jsonl")
    env["HAPAX_ADOPTABILITY_RECEIPT_ROOTS"] = str(home)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=30
    )


def _front(note: Path) -> dict:
    text = note.read_text()
    end = text.find("\n---", 4)
    return yaml.safe_load(text[4:end])


def test_garage_door_row_without_receipts_cannot_leave_s1(tmp_path: Path) -> None:
    note = _make_garage_door_task(tmp_path, "gd-1")
    result = _run(tmp_path, "gd-1", "S6_IMPLEMENTATION")
    assert result.returncode == 2, result.stderr
    assert "stage_refused:prior_art_receipt_absent" in result.stderr
    assert "stage_refused:demand_receipt_absent" in result.stderr
    assert _front(note)["stage"] == "S1_OFFERED"


def test_garage_door_row_with_receipts_advances(tmp_path: Path) -> None:
    note = _make_garage_door_task(tmp_path, "gd-2")
    _write_receipts(tmp_path)
    result = _run(tmp_path, "gd-2", "S6_IMPLEMENTATION")
    assert result.returncode == 0, result.stderr
    front = _front(note)
    assert front["stage"] == "S6_IMPLEMENTATION"
    assert front["kind"] == "engineering"


def test_backed_usable_prior_art_converts_to_contribution_then_advances(tmp_path: Path) -> None:
    note = _make_garage_door_task(tmp_path, "gd-3")
    _write_receipts(tmp_path, verdict="BACKED", usable=True)
    result = _run(tmp_path, "gd-3", "S2_CLAIMED")
    assert result.returncode == 0, result.stderr
    assert "row_converted:contribution" in result.stderr
    front = _front(note)
    assert front["kind"] == "contribution"
    assert front["stage"] == "S2_CLAIMED"
    assert "row_converted:contribution" in note.read_text()


def test_staying_at_s1_needs_no_receipts(tmp_path: Path) -> None:
    _make_garage_door_task(tmp_path, "gd-4")
    result = _run(tmp_path, "gd-4", "S1_OFFERED")
    assert result.returncode == 0, result.stderr


def test_non_garage_door_row_is_untouched_by_the_tooth(tmp_path: Path) -> None:
    note = _make_garage_door_task(tmp_path, "plain-1")
    text = note.read_text().replace("- garage-door\n", "- plain\n")
    note.write_text(text)
    result = _run(tmp_path, "plain-1", "S6_IMPLEMENTATION")
    assert result.returncode == 0, result.stderr
    assert _front(note)["stage"] == "S6_IMPLEMENTATION"
