"""The boot restorer and appendix policy must enter the post-merge activation path."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "scripts" / "hapax-post-merge-deploy"
POLICY = ROOT / "systemd" / "units" / "host-recovery" / "appendix"


def test_appendix_policy_paths_are_covered_by_post_merge_dispatch() -> None:
    paths = sorted(str(path.relative_to(ROOT)) for path in POLICY.iterdir() if path.is_file())
    assert len(paths) == 4
    result = subprocess.run(
        ["bash", str(DEPLOY), "--report-coverage-stdin"],
        input="\n".join(paths) + "\n",
        text=True,
        capture_output=True,
        cwd=ROOT,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "all systemd/** paths" in result.stdout


def test_boot_restorer_is_marked_for_auto_enable() -> None:
    service = (ROOT / "systemd/units/hapax-host-recovery-restore.service").read_text()
    assert "# Hapax-Auto-Enable: true" in service
    assert "WantedBy=default.target" in service
