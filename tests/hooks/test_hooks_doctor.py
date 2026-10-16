"""Tests for hooks/scripts/hooks-doctor.sh — the gate-drift detector (reform FM-6).

Pins: classify (shim / drift-warn / drift-critical / missing), --check refusal on
a regressed committed gate or an INV-5-less impl, --deploy-canonical landing a
healthy closure (and refusing an impl without the carve-out), and --fanout
rewriting a stale lane worktree's gate to the shim. Self-contained per project
conventions (no shared conftest).
"""

from __future__ import annotations

import configparser
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS = REPO_ROOT / "hooks" / "scripts"
DOCTOR = REPO_ROOT / "hooks" / "scripts" / "hooks-doctor.sh"
SHIM = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.sh"
IMPL = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.impl.sh"
# The closure siblings hooks-doctor deploys alongside the impl (cc-task-gate.sh).
CLOSURE_SIBLINGS = (
    "agent-role.sh",
    "escape-grant.sh",
    "cc-task-root.sh",
    "cc-task-gate-bootstrap.py",
    "hooks-doctor.sh",
)

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


@pytest.mark.parametrize(
    "doctor_dir",
    [
        ".local/lib/hapax/hooks",
        ".cache/hapax/rebuild/worktree/hooks/scripts",
        ".cache/hapax/source-activation/worktree/hooks/scripts",
    ],
    ids=["canonical", "rebuild", "activated"],
)
def test_service_execstart_passes_activation_root(tmp_path: Path, doctor_dir: str) -> None:
    """Every executable source must inspect the activated tree, not a lane branch."""
    unit = configparser.ConfigParser(interpolation=None, strict=False)
    unit.read(REPO_ROOT / "systemd" / "units" / "hapax-hooks-doctor.service")
    fixture_home = tmp_path / "home with spaces"
    args_path = tmp_path / "doctor-args"
    _write(
        fixture_home / doctor_dir / "hooks-doctor.sh",
        '#!/bin/bash\nprintf "%s\\n" "$@" > "$DOCTOR_ARGS_CAPTURE"\n',
    )

    result = subprocess.run(
        shlex.split(unit["Service"]["ExecStart"]),
        env={**os.environ, "HOME": str(fixture_home), "DOCTOR_ARGS_CAPTURE": str(args_path)},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert args_path.read_text().splitlines() == [
        "--session",
        "--notify",
        "--root",
        str(fixture_home / ".cache/hapax/source-activation/worktree"),
    ]


def test_service_prefers_activated_doctor_before_canonical_refresh(tmp_path: Path) -> None:
    unit = configparser.ConfigParser(interpolation=None, strict=False)
    unit.read(REPO_ROOT / "systemd" / "units" / "hapax-hooks-doctor.service")
    for directory, label in (
        (".local/lib/hapax/hooks", "canonical"),
        (".cache/hapax/rebuild/worktree/hooks/scripts", "rebuild"),
        (".cache/hapax/source-activation/worktree/hooks/scripts", "activated"),
    ):
        _write(tmp_path / directory / "hooks-doctor.sh", f"#!/bin/sh\necho {label}\n")
    result = subprocess.run(
        shlex.split(unit["Service"]["ExecStart"]),
        env={**os.environ, "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "activated"


def _notification_fixture(tmp_path: Path):
    root = tmp_path / "hapax-council"
    _seed_repo(root, gate_body=SHIM.read_text(), impl_body=IMPL.read_text())
    _write(root / "shared" / "__init__.py", "")
    _write(root / "shared" / "cc_task_root.py", (REPO_ROOT / "shared/cc_task_root.py").read_text())
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture")
    canonical = tmp_path / "canonical"
    mailbox = tmp_path / "vault/30-areas/hapax/lanebus/dev1"
    mailbox.mkdir(parents=True)
    tools = tmp_path / "tools"
    _write(tools / "hapax-notify", '#!/bin/sh\ntouch "$NOTIFY_CAPTURE"\n')
    env = {
        "HOME": str(tmp_path / "home"),
        "PATH": f"{tools}:{os.defpath}",
        "PYTHONPATH": "",
        "PERSONAL_VAULT_PATH": str(tmp_path / "vault"),
        "HAPAX_CANONICAL_HOOKS": str(canonical),
        "HAPAX_LOCAL_BIN": str(tmp_path / "bin"),
        "NOTIFY_CAPTURE": str(tmp_path / "legacy-notify-called"),
    }
    deployed = _run("--deploy-canonical", env=env)
    assert deployed.returncode == 0, deployed.stdout + deployed.stderr
    return root, canonical, mailbox, env


@pytest.mark.parametrize("mode,expected_rc", [("--session", 0), ("--check", 1)])
def test_notify_delivers_real_drift_and_provenance(tmp_path: Path, mode: str, expected_rc: int):
    root, canonical, mailbox, env = _notification_fixture(tmp_path)
    (canonical / "agent-role.sh").unlink()
    result = _run(mode, "--notify", "--root", str(root), env=env)
    assert result.returncode == expected_rc
    drops = list(mailbox.glob("*.md"))
    assert len(drops) == 1, result.stdout + result.stderr
    body = drops[0].read_text()
    diagnostic = f"CRITICAL canonical closure missing sibling: {canonical}/agent-role.sh"
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    for value in (diagnostic, str(root), str(canonical), head, f'mode: "{mode[2:]}"'):
        assert value in body
    assert re.search(r'created_at: "\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+Z"', body)
    assert "Next action:" in body
    assert "drift delivered" in result.stdout
    assert not Path(env["NOTIFY_CAPTURE"]).exists()


def test_notify_preserves_prior_drops_and_refuses_timestamp_collision(tmp_path: Path):
    root, canonical, mailbox, env = _notification_fixture(tmp_path)
    (canonical / "agent-role.sh").unlink()
    date = tmp_path / "tools/date"
    _write(date, '#!/bin/sh\necho "2026-10-16T18:00:00.000000001Z"\n')
    first = _run("--session", "--notify", "--root", str(root), env=env)
    assert first.returncode == 0
    drops = list(mailbox.glob("*.md"))
    assert len(drops) == 1, first.stdout + first.stderr
    before = drops[0].read_bytes(), drops[0].stat().st_mtime_ns
    collided = _run("--session", "--notify", "--root", str(root), env=env)
    assert collided.returncode == 0
    assert "drift delivery FAILED" in collided.stderr
    assert (drops[0].read_bytes(), drops[0].stat().st_mtime_ns) == before
    _write(date, '#!/bin/sh\necho "2026-10-16T18:00:00.000000002Z"\n')
    second = _run("--session", "--notify", "--root", str(root), env=env)
    assert second.returncode == 0
    assert "drift delivered" in second.stdout
    assert len(list(mailbox.glob("*.md"))) == 2
    assert (drops[0].read_bytes(), drops[0].stat().st_mtime_ns) == before
    assert not Path(env["NOTIFY_CAPTURE"]).exists()


@pytest.mark.parametrize("mode,expected_rc", [("--session", 0), ("--check", 1)])
@pytest.mark.parametrize("failure", ["missing-mailbox", "relative-vault"])
def test_notify_failure_is_loud_without_fallback(
    tmp_path: Path, mode: str, expected_rc: int, failure: str
):
    root, canonical, mailbox, env = _notification_fixture(tmp_path)
    (canonical / "agent-role.sh").unlink()
    if failure == "missing-mailbox":
        mailbox.rmdir()
    else:
        env["PERSONAL_VAULT_PATH"] = "relative-vault"
    result = _run(mode, "--notify", "--root", str(root), env=env)
    assert result.returncode == expected_rc
    assert "drift delivery FAILED" in result.stderr
    assert "Next action:" in result.stderr
    assert not list(mailbox.glob("*.md"))
    assert not Path(env["NOTIFY_CAPTURE"]).exists()
    assert not (Path(env["HOME"]) / "Documents").exists()


@pytest.mark.parametrize("mode", ["--session", "--check"])
@pytest.mark.parametrize("drift", [False, True], ids=["clean-notify", "drift-no-notify"])
def test_clean_or_unrequested_notification_writes_nothing(tmp_path: Path, mode: str, drift: bool):
    root, canonical, mailbox, env = _notification_fixture(tmp_path)
    args = [mode, "--root", str(root)]
    if drift:
        (canonical / "agent-role.sh").unlink()
    else:
        args.append("--notify")
    result = _run(*args, env=env)
    assert result.returncode == (1 if drift and mode == "--check" else 0)
    assert not list(mailbox.glob("*.md"))
    assert not Path(env["NOTIFY_CAPTURE"]).exists()


def test_session_missing_canonical_delivers_its_actual_diagnostic(tmp_path: Path):
    root, _, mailbox, env = _notification_fixture(tmp_path)
    env["HAPAX_CANONICAL_HOOKS"] = str(tmp_path / "absent-canonical")
    result = _run("--session", "--notify", "--root", str(root), env=env)
    assert result.returncode == 0
    drops = list(mailbox.glob("*.md"))
    assert len(drops) == 1, result.stdout + result.stderr
    assert f"no deployed canonical gate at {env['HAPAX_CANONICAL_HOOKS']}" in drops[0].read_text()


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
        "cc-task-root.sh",
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


# --- atomic deploy (reform — bootstrap-failopen-atomic-swap) ----------------
# The old deploy installed the impl FIRST and each closure file via `install`
# (unlinkat+create), so during a redeploy a sibling was briefly absent and the
# new impl could go live before its closure — a concurrent PreToolUse exec then
# sourced a half-written sibling / opened an absent helper and fail-closed. The
# fix stages the whole closure into a temp dir on the same filesystem and
# rename(2)s each file into place, publishing the impl LAST.


def _seed_incomplete_source(tmp_path: Path) -> Path:
    """A --from source whose impl DIFFERS from the deployed one but is missing a
    closure sibling (escape-grant.sh) — so an impl-first install would be visibly
    detectable, while a staged deploy must refuse without touching the canonical."""
    src = tmp_path / "src" / "hooks" / "scripts"
    src.mkdir(parents=True)
    _write(src / "cc-task-gate.impl.sh", IMPL.read_text(encoding="utf-8") + "\n# v2 divergence\n")
    for sib in ("agent-role.sh", "cc-task-gate-bootstrap.py", "hooks-doctor.sh"):
        _write(src / sib, (HOOKS / sib).read_text(encoding="utf-8"))
    # escape-grant.sh deliberately OMITTED → incomplete closure.
    return tmp_path / "src"


def test_deploy_from_incomplete_source_leaves_canonical_untouched(tmp_path):
    # Land a healthy v1 from the real repo, snapshot it, then attempt a deploy from
    # an incomplete (different-impl, missing-sibling) source. The refused deploy must
    # be a NO-OP on the live canonical — not a half-swapped closure.
    canon = tmp_path / "canon"
    bindir = tmp_path / "bin"
    env = {"HAPAX_CANONICAL_HOOKS": str(canon), "HAPAX_LOCAL_BIN": str(bindir)}
    r1 = _run("--deploy-canonical", env=env)
    assert r1.returncode == 0, r1.stdout + r1.stderr
    before = {p.name: p.read_bytes() for p in canon.iterdir() if p.is_file()}
    assert "cc-task-gate.sh" in before

    src_root = _seed_incomplete_source(tmp_path)
    r2 = _run("--deploy-canonical", "--from", str(src_root), env=env)
    assert r2.returncode == 1
    assert "REFUSING" in r2.stderr

    after = {p.name: p.read_bytes() for p in canon.iterdir() if p.is_file()}
    assert after == before, (
        "an incomplete-source deploy must not mutate the live canonical "
        "(staging + up-front refusal), not a half-swapped closure"
    )


def test_deploy_publishes_via_atomic_rename_impl_last(tmp_path):
    # strace evidence (the AC's named method): every closure file is published via a
    # rename(2) (atomic, no absent window) and the impl (cc-task-gate.sh) is renamed
    # LAST, after every sibling, from a staging temp dir.
    strace = shutil.which("strace")
    if strace is None:
        pytest.skip("strace unavailable")
    canon = tmp_path / "canon"
    bindir = tmp_path / "bin"
    env = {**os.environ, "HAPAX_CANONICAL_HOOKS": str(canon), "HAPAX_LOCAL_BIN": str(bindir)}
    # Pre-deploy v1 so the traced deploy REPLACES existing files (the redeploy case).
    r0 = _run(
        "--deploy-canonical",
        env={"HAPAX_CANONICAL_HOOKS": str(canon), "HAPAX_LOCAL_BIN": str(bindir)},
    )
    assert r0.returncode == 0, r0.stdout + r0.stderr

    trace = tmp_path / "trace.log"
    proc = subprocess.run(
        [
            strace,
            "-f",
            "-s",
            "4096",
            "-e",
            "trace=rename,renameat,renameat2",
            "-o",
            str(trace),
            "bash",
            str(DOCTOR),
            "--deploy-canonical",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0 and "ptrace" in (proc.stderr or "").lower():
        pytest.skip("strace cannot ptrace in this sandbox")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = [
        ln
        for ln in trace.read_text(encoding="utf-8", errors="replace").splitlines()
        if "= 0" in ln and "rename" in ln
    ]
    if not lines:
        pytest.skip("strace captured no rename syscalls (restricted)")

    def dest_idx(name: str) -> int:
        needle = f'"{canon / name}"'  # the DEST appears as a fully-quoted abs path
        for i, ln in enumerate(lines):
            if needle in ln:
                return i
        return -1

    impl_idx = dest_idx("cc-task-gate.sh")
    sib_idxs = {name: dest_idx(name) for name in CLOSURE_SIBLINGS}
    assert impl_idx >= 0, f"impl must be published via rename; renames={lines}"
    for name, idx in sib_idxs.items():
        assert idx >= 0, f"sibling {name} must be published via rename; renames={lines}"
    assert impl_idx > max(sib_idxs.values()), (
        "the impl (cc-task-gate.sh) must be renamed into place LAST, after every "
        "sibling, so a concurrent gate exec never sees a new impl ahead of its closure"
    )
    assert ".deploy.tmp" in lines[impl_idx], (
        f"impl must be published FROM a staging temp dir (atomic): {lines[impl_idx]}"
    )


def test_concurrent_redeploy_never_exposes_incomplete_closure(tmp_path):
    # AC4: under concurrent redeploy stress, the canonical must never present an impl
    # without its full, non-empty closure (the window that made the gate open an
    # absent bootstrap helper and fail closed). rename(2) never removes a file, so a
    # sibling is never momentarily absent; impl-last keeps the impl behind its closure.
    canon = tmp_path / "canon"
    env = {"HAPAX_CANONICAL_HOOKS": str(canon), "HAPAX_LOCAL_BIN": str(tmp_path / "bin")}
    r0 = _run("--deploy-canonical", env=env)
    assert r0.returncode == 0, r0.stdout + r0.stderr

    closure = ("cc-task-gate.sh", *CLOSURE_SIBLINGS)
    violations: list[str] = []
    stop = threading.Event()
    run_env = {**os.environ, **env}

    def redeployer() -> None:
        for _ in range(30):
            if stop.is_set():
                break
            subprocess.run(
                ["bash", str(DOCTOR), "--deploy-canonical"],
                capture_output=True,
                text=True,
                env=run_env,
                check=False,
            )

    worker = threading.Thread(target=redeployer)
    worker.start()
    probes = 0
    try:
        deadline = time.monotonic() + 10.0
        while worker.is_alive() and time.monotonic() < deadline:
            if (canon / "cc-task-gate.sh").exists():
                for name in closure:
                    try:
                        size = (canon / name).stat().st_size
                    except FileNotFoundError:
                        # The TOCTOU window itself: a sibling vanished mid-deploy
                        # while the impl was present (old install-based unlinkat).
                        violations.append(f"missing {name} while impl present")
                        continue
                    if size == 0:
                        violations.append(f"empty {name} while impl present")
            probes += 1
    finally:
        stop.set()
        worker.join(timeout=60)

    assert probes > 0
    assert not violations, (
        f"closure was incomplete during redeploy ({len(violations)} probes): {violations[:5]}"
    )
