from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-recovery-plane-install"
BUNDLE_FILES = {
    "scripts/hapax-p0-incident-intake",
    "scripts/hapax-coord-deploy",
    "shared/__init__.py",
    "shared/jsonl_append.py",
    "shared/p0_incident_intake.py",
}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _write_minimal_bundle(repo: Path, token: str) -> None:
    files = {
        "scripts/hapax-p0-incident-intake": f"#!/bin/sh\necho intake {token}\n",
        "scripts/hapax-coord-deploy": f"#!/bin/sh\necho coord {token}\n",
        "shared/__init__.py": f"# init {token}\n",
        "shared/jsonl_append.py": f"# jsonl {token}\n",
        "shared/p0_incident_intake.py": f"# intake module {token}\n",
    }
    for relative, body in files.items():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")


def test_recovery_plane_install_materializes_minimal_bundle(tmp_path: Path) -> None:
    dest = tmp_path / "council"

    result = subprocess.run(
        [str(SCRIPT), "--source", str(REPO_ROOT), "--dest", str(dest), "--json"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads(result.stdout)
    assert manifest["schema_version"] == 1
    assert manifest["source_root"] == str(REPO_ROOT.resolve())
    assert manifest["bundle_root"] == str(dest)
    assert Path(manifest["release_root"]).is_dir()
    assert {entry["path"] for entry in manifest["files"]} == BUNDLE_FILES
    assert dest.is_symlink()

    for relative in BUNDLE_FILES:
        assert (dest / relative).is_file()
    for relative in ("scripts/hapax-p0-incident-intake", "scripts/hapax-coord-deploy"):
        mode = (dest / relative).stat().st_mode
        assert mode & stat.S_IXUSR, f"{relative} must be executable"
    assert (dest / "manifest.json").is_file()


def test_recovery_plane_install_source_ref_ignores_dirty_worktree(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.email", "recovery-install-test@example.test")
    _git(source, "config", "user.name", "Recovery Install Test")
    _write_minimal_bundle(source, "committed")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "committed bundle")
    committed_sha = _git(source, "rev-parse", "HEAD")
    (source / "scripts" / "hapax-coord-deploy").write_text(
        "#!/bin/sh\necho coord dirty\n",
        encoding="utf-8",
    )
    dest = tmp_path / "council"

    result = subprocess.run(
        [
            str(SCRIPT),
            "--source",
            str(source),
            "--source-ref",
            committed_sha,
            "--dest",
            str(dest),
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads(result.stdout)
    assert manifest["source_ref"] == committed_sha
    assert (dest / "scripts" / "hapax-coord-deploy").read_text(encoding="utf-8") == (
        "#!/bin/sh\necho coord committed\n"
    )


def test_recovery_plane_install_failed_materialization_keeps_prior_release(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.email", "recovery-install-test@example.test")
    _git(source, "config", "user.name", "Recovery Install Test")
    _write_minimal_bundle(source, "stable")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "stable bundle")
    stable_sha = _git(source, "rev-parse", "HEAD")
    dest = tmp_path / "council" / "current"
    first = subprocess.run(
        [str(SCRIPT), "--source", str(source), "--source-ref", stable_sha, "--dest", str(dest)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert first.returncode == 0, first.stderr
    first_release = dest.resolve()

    failed = subprocess.run(
        [str(SCRIPT), "--source", str(source), "--source-ref", "missing-ref", "--dest", str(dest)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert failed.returncode == 1
    assert dest.resolve() == first_release
    assert (dest / "scripts" / "hapax-coord-deploy").read_text(encoding="utf-8") == (
        "#!/bin/sh\necho coord stable\n"
    )
    manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_ref"] == stable_sha


def test_installed_p0_intake_runs_without_source_activation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    dest = home / ".local" / "lib" / "hapax-recovery" / "council" / "current"
    install = subprocess.run(
        [str(SCRIPT), "--source", str(REPO_ROOT), "--dest", str(dest)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert install.returncode == 0, install.stderr

    source_activation = home / ".cache" / "hapax" / "source-activation" / "worktree"
    assert not source_activation.exists()

    notify_log = tmp_path / "notify.log"
    env = os.environ.copy()
    env.update({"HOME": str(home), "HAPAX_NOTIFY_CAPTURE": str(notify_log)})

    result = subprocess.run(
        [str(dest / "scripts" / "hapax-p0-incident-intake"), "service-failed", "demo.service"],
        cwd=dest,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    task_glob = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    assert list(task_glob.glob("p0-incident-systemd-service-failed-demo-service-*.md"))
    assert not notify_log.exists(), "P0 intake should consume failures without desktop echo"
