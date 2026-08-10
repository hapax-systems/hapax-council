from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_hapax_fsm_smoke_is_tracked_isolated_and_executable(tmp_path: Path) -> None:
    script = Path("scripts/hapax-fsm-smoke")
    assert script.is_file()
    assert os.access(script, os.X_OK)

    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "UV_LINK_MODE": "copy",
    }
    result = subprocess.run(
        [str(script), "--mode", "both"],
        cwd=Path.cwd(),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[default] claim-publication install\n" in result.stdout
    assert "admitted publication applied" in result.stdout
    assert "HAPAX_GATE0B_CLAIM_PUBLICATION_OFF=1" in result.stdout
    assert "[default] ok\n" in result.stdout
    assert "[killswitch] ok\n" in result.stdout
