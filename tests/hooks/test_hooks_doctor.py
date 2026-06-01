"""Tests for hooks/scripts/hooks-doctor.sh — the gate-drift detector (reform FM-6).

Pins: classify (shim / drift-warn / drift-critical / missing), --check refusal on
a regressed committed gate or an INV-5-less impl, --deploy-canonical landing a
healthy closure (and refusing an impl without the carve-out), and --fanout
rewriting a stale lane worktree's gate to the shim. Self-contained per project
conventions (no shared conftest).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCTOR = REPO_ROOT / "hooks" / "scripts" / "hooks-doctor.sh"
SHIM = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.sh"
IMPL = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.impl.sh"

SHIM_MARKER = "HAPAX-GATE-SHIM"
STALE_GATE = "#!/usr/bin/env bash\n# old 427-line gate, no cognition carve-out\nexit 2\n"
DRIFTED_GATE_WITH_COGNITION = (
    "#!/usr/bin/env bash\n# a full gate copy that DOES carry the carve-out\n"
    "is_cognition_path() { return 1; }\nexit 2\n"
)
IMPL_WITHOUT_COGNITION = "#!/usr/bin/env bash\n# a gate impl missing the carve-out\nexit 2\n"


def _run(*args: str, env: dict[str, str] | None = None, timeout: int = 60):
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        ["bash", str(DOCTOR), *args],
        capture_output=True,
        text=True,
        check=False,
        env=merged,
        timeout=timeout,
    )


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


# --- classify --------------------------------------------------------------


def test_classify_repo_shim_is_clean():
    result = _run("--classify", str(SHIM))
    assert result.returncode == 0
    assert result.stdout.strip() == "shim"


def test_classify_stale_gate_is_critical(tmp_path):
    gate = tmp_path / "cc-task-gate.sh"
    _write(gate, STALE_GATE)
    result = _run("--classify", str(gate))
    assert result.returncode == 3
    assert result.stdout.strip() == "drift-critical"


def test_classify_drifted_gate_with_cognition_is_warn(tmp_path):
    gate = tmp_path / "cc-task-gate.sh"
    _write(gate, DRIFTED_GATE_WITH_COGNITION)
    result = _run("--classify", str(gate))
    assert result.returncode == 2
    assert result.stdout.strip() == "drift-warn"


def test_classify_missing_gate(tmp_path):
    result = _run("--classify", str(tmp_path / "nope.sh"))
    assert result.returncode == 4
    assert result.stdout.strip() == "missing"


# --- check (the CI refusal gate) -------------------------------------------


def _seed_repo(root: Path, *, gate_body: str, impl_body: str | None) -> None:
    _write(root / "hooks" / "scripts" / "cc-task-gate.sh", gate_body)
    if impl_body is not None:
        _write(root / "hooks" / "scripts" / "cc-task-gate.impl.sh", impl_body)


def test_check_clean_repo_passes(tmp_path):
    _seed_repo(
        tmp_path,
        gate_body=SHIM.read_text(encoding="utf-8"),
        impl_body=IMPL.read_text(encoding="utf-8"),
    )
    result = _run(
        "--check",
        "--root",
        str(tmp_path),
        env={"HAPAX_CANONICAL_HOOKS": str(tmp_path / "no-canon")},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "clean" in result.stdout


def test_check_refuses_regressed_gate(tmp_path):
    # Committed cc-task-gate.sh regressed to a full gate copy (no shim marker).
    _seed_repo(tmp_path, gate_body=STALE_GATE, impl_body=IMPL.read_text(encoding="utf-8"))
    result = _run(
        "--check",
        "--root",
        str(tmp_path),
        env={"HAPAX_CANONICAL_HOOKS": str(tmp_path / "no-canon")},
    )
    assert result.returncode == 1
    assert "NOT a shim" in result.stdout


def test_check_refuses_impl_without_cognition(tmp_path):
    _seed_repo(
        tmp_path, gate_body=SHIM.read_text(encoding="utf-8"), impl_body=IMPL_WITHOUT_COGNITION
    )
    result = _run(
        "--check",
        "--root",
        str(tmp_path),
        env={"HAPAX_CANONICAL_HOOKS": str(tmp_path / "no-canon")},
    )
    assert result.returncode == 1
    assert "is_cognition_path" in result.stdout


# --- deploy ----------------------------------------------------------------


def test_deploy_canonical_lands_healthy_closure(tmp_path):
    canon = tmp_path / "canon"
    bindir = tmp_path / "bin"
    result = _run(
        "--deploy-canonical",
        env={"HAPAX_CANONICAL_HOOKS": str(canon), "HAPAX_LOCAL_BIN": str(bindir)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    deployed = canon / "cc-task-gate.sh"
    assert deployed.exists()
    body = deployed.read_text(encoding="utf-8")
    assert "is_cognition_path()" in body  # INV-5 present in canonical
    assert SHIM_MARKER not in body  # canonical holds the impl, not a shim
    for sibling in (
        "agent-role.sh",
        "escape-grant.sh",
        "cc-task-gate-bootstrap.py",
        "hooks-doctor.sh",
    ):
        assert (canon / sibling).exists()
    assert (canon / "MANIFEST.sha256").exists()
    assert (bindir / "hapax-hooks-doctor").is_symlink()


def test_deploy_refuses_impl_without_cognition(tmp_path):
    src = tmp_path / "src"
    _write(src / "hooks" / "scripts" / "cc-task-gate.impl.sh", IMPL_WITHOUT_COGNITION)
    result = _run(
        "--deploy-canonical",
        "--from",
        str(src),
        env={
            "HAPAX_CANONICAL_HOOKS": str(tmp_path / "canon"),
            "HAPAX_LOCAL_BIN": str(tmp_path / "bin"),
        },
    )
    assert result.returncode == 1
    assert "REFUSING" in result.stderr


def test_canonical_closure_covers_all_impl_dependencies(tmp_path):
    # Regression guard for the cc-task-gate-bootstrap.py omission incident: EVERY
    # file the impl resolves via $SCRIPT_DIR (sources OR invokes) must land in the
    # deployed canonical closure. A missing one makes the gate exit 2 on every
    # mutation. This test parses the impl directly, so a NEW impl dependency that
    # is not added to the closure fails here instead of breaking the live fleet.
    impl_text = IMPL.read_text(encoding="utf-8")
    refs = set(re.findall(r"\$\{?SCRIPT_DIR\}?/([A-Za-z0-9._-]+)", impl_text))
    assert "cc-task-gate-bootstrap.py" in refs, "expected the impl to invoke the bootstrap"
    canon = tmp_path / "canon"
    result = _run(
        "--deploy-canonical",
        env={"HAPAX_CANONICAL_HOOKS": str(canon), "HAPAX_LOCAL_BIN": str(tmp_path / "bin")},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    missing = sorted(ref for ref in refs if not (canon / ref).exists())
    assert not missing, f"canonical closure is missing impl dependencies: {missing}"


# --- fanout (the one-shot that fixes stale lanes) --------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def test_fanout_shims_stale_lane_worktree(tmp_path):
    # A real git repo named hapax-council with a lane worktree carrying a STALE
    # full gate; --fanout must rewrite the lane gate to the shim (and be idempotent).
    repo = tmp_path / "hapax-council"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _write(repo / "hooks" / "scripts" / "cc-task-gate.sh", SHIM.read_text(encoding="utf-8"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")

    lane = tmp_path / "hapax-council--lane1"
    _git(repo, "worktree", "add", "-q", str(lane), "-b", "lane1")
    lane_gate = lane / "hooks" / "scripts" / "cc-task-gate.sh"
    _write(lane_gate, STALE_GATE)
    assert SHIM_MARKER not in lane_gate.read_text(encoding="utf-8")

    result = _run("--fanout", "--root", str(repo))
    assert result.returncode == 0, result.stdout + result.stderr
    assert SHIM_MARKER in lane_gate.read_text(encoding="utf-8")

    again = _run("--fanout", "--root", str(repo))
    assert "0 gate(s) updated" in again.stdout
