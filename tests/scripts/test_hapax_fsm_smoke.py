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
    default_start = result.stdout.index("[default] claim")
    killswitch_start = result.stdout.index("[killswitch] claim")
    default_output = result.stdout[default_start:killswitch_start]
    killswitch_output = result.stdout[killswitch_start:]
    assert "manual claim binding issued" in default_output
    assert "Gate-0B claim-publication root installed for first use" in default_output
    assert "admitted publication applied" in default_output
    assert "[default] claim after close" in default_output
    assert "archived terminal dispatch-only claim residue" not in default_output
    assert "HAPAX_GATE0B_CLAIM_PUBLICATION_OFF=1" not in default_output
    assert "HAPAX_GATE0B_CLAIM_PUBLICATION_OFF=1" in killswitch_output
    assert "admitted publication applied" not in killswitch_output
    assert "[default] ok\n" in result.stdout
    assert "[killswitch] ok (close refused as designed)\n" in result.stdout
