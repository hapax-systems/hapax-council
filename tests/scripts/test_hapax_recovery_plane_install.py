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
    assert {entry["path"] for entry in manifest["files"]} == BUNDLE_FILES

    for relative in BUNDLE_FILES:
        assert (dest / relative).is_file()
    for relative in ("scripts/hapax-p0-incident-intake", "scripts/hapax-coord-deploy"):
        mode = (dest / relative).stat().st_mode
        assert mode & stat.S_IXUSR, f"{relative} must be executable"
    assert (dest / "manifest.json").is_file()


def test_installed_p0_intake_runs_without_source_activation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    dest = home / ".local" / "lib" / "hapax-recovery" / "council"
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
