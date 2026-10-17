"""A caller's stale checkout must not supply cc-close's inline Python imports."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TASK = "cwd-import-test"


@pytest.fixture
def close_layout(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, str]]:
    # Copy the real entrypoint into an installed layout, with its real shared modules
    # and runtime. No production vault, claims, services or release files are changed.
    installed = tmp_path / "installed"
    (installed / "scripts").mkdir(parents=True)
    script = installed / "scripts" / "cc-close"
    shutil.copy2(REPO_ROOT / "scripts" / "cc-close", script)
    (installed / "shared").symlink_to(REPO_ROOT / "shared", target_is_directory=True)
    (installed / "hooks").symlink_to(REPO_ROOT / "hooks", target_is_directory=True)
    (installed / ".venv").symlink_to(Path(sys.prefix), target_is_directory=True)
    vault = tmp_path / "tasks"
    (vault / "active").mkdir(parents=True)
    (vault / "closed").mkdir()
    caller = tmp_path / "stale-checkout"
    caller.mkdir()
    env = {
        "PATH": os.defpath,
        "HOME": str(tmp_path / "home"),
        "HAPAX_AGENT_ROLE": "cwd-test",
        "HAPAX_CC_TASKS_ROOT": str(vault),
        "HAPAX_COORD_DIR": str(tmp_path / "coord"),
    }
    return script, vault, caller, env


def _row(vault: Path, *, claimed_at: str = "2020-01-01T00:00:00Z") -> Path:
    note = vault / "active" / f"{TASK}.md"
    note.write_text(
        f"---\ntype: cc-task\ntask_id: {TASK}\nstatus: claimed\n"
        f"claimed_at: {claimed_at}\ncompleted_at: null\nupdated_at: null\n---\n"
        "\n## Session log\n",
        encoding="utf-8",
    )
    return note


def _close(
    layout: tuple[Path, Path, Path, dict[str, str]], *args: str
) -> subprocess.CompletedProcess[str]:
    script, _, caller, env = layout
    return subprocess.run(
        ["bash", str(script), TASK, *args],
        cwd=caller,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


@pytest.mark.parametrize("decoy", [None, "shared", "datetime"])
def test_close_uses_installed_modules_from_an_unrelated_cwd(close_layout, decoy):
    _, vault, caller, _ = close_layout
    note = _row(vault)
    if decoy == "shared":
        package = caller / "shared"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        # This is the measured failure: an older sdlc_claim without the new symbol.
        (package / "sdlc_claim.py").write_text("STALE_CHECKOUT = True\n", encoding="utf-8")
    elif decoy:
        (caller / f"{decoy}.py").write_text(
            f"raise RuntimeError('cwd decoy imported: {decoy}')\n", encoding="utf-8"
        )

    result = _close(close_layout, "--status", "withdrawn", "--reason", "fixture disposition")

    assert result.returncode == 0, result.stderr
    assert not note.exists()
    closed = (vault / "closed" / note.name).read_text(encoding="utf-8")
    assert "status: withdrawn\n" in closed
    assert "cwd-test closed as withdrawn: fixture disposition (cc-close)" in closed


def test_duplicate_check_cannot_import_the_callers_re_module(close_layout):
    _, vault, caller, _ = close_layout
    note = _row(vault)
    before = note.read_bytes()
    duplicate = vault / "closed" / note.name
    duplicate.write_bytes(before)
    (caller / "re.py").write_text("raise RuntimeError('cwd decoy imported: re')\n")

    result = _close(close_layout, "--status", "withdrawn", "--reason", "fixture disposition")

    assert result.returncode == 8, result.stderr
    assert "closed task duplicate" in result.stderr
    assert note.read_bytes() == duplicate.read_bytes() == before
    assert "cwd decoy imported" not in result.stderr


@pytest.mark.parametrize("decoy", ["re", "datetime"])
def test_rapid_close_still_refuses_from_a_cwd_with_stdlib_decoys(close_layout, decoy):
    _, vault, caller, _ = close_layout
    note = _row(vault, claimed_at=datetime.now(UTC).isoformat())
    before = note.read_bytes()
    (caller / f"{decoy}.py").write_text(f"raise RuntimeError('cwd decoy imported: {decoy}')\n")

    result = _close(close_layout)

    assert result.returncode == 2, result.stderr
    assert "< 5min threshold" in result.stderr
    assert note.read_bytes() == before
    assert not (vault / "closed" / note.name).exists()
