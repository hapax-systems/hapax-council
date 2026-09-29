"""The Kimi child cannot start without its selected canonical binding."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, dict[str, str]]:
    release = tmp_path / "release"
    (release / "scripts").mkdir(parents=True)
    (release / "shared").mkdir()
    (release / "config/agent-instructions").mkdir(parents=True)
    for name in ("hapax-kimi", "hapax-kimi-instruction-preflight"):
        shutil.copy2(ROOT / "scripts" / name, release / "scripts" / name)
    shutil.copy2(
        ROOT / "shared/canonical_instruction_ingestion.py",
        release / "shared/canonical_instruction_ingestion.py",
    )
    source = release / "config/agent-instructions/AGENTS.md"
    source.write_bytes(b"# Current shared instructions\nFollow the governed claim.\n")
    home = tmp_path / "home"
    neutral = home / ".config/hapax/agent-instructions/AGENTS.md"
    native = home / ".kimi-code/AGENTS.md"
    neutral.parent.mkdir(parents=True)
    native.parent.mkdir(parents=True)
    neutral.write_bytes(source.read_bytes())
    native.write_bytes(b"# Kimi binding\n" + source.read_bytes())
    receipt = neutral.parent / "current.json"
    receipt.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "binding": binding,
                        "path": str(path),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                    for binding, path in (("shared", neutral), ("kimi", native))
                ]
            }
        ),
        encoding="utf-8",
    )
    bins = tmp_path / "bin"
    bins.mkdir()
    tmux = bins / "tmux"
    tmux.write_text("#!/bin/sh\nexit 1\n")
    tmux.chmod(0o755)
    child = bins / "kimi-child"
    child.write_text("#!/bin/sh\nprintf 'launched\\n' > \"$KIMI_CHILD_MARKER\"\n")
    child.chmod(0o755)
    marker = tmp_path / "child-launched"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": str(bins) + os.pathsep + os.environ["PATH"],
        "KIMI_BIN": str(child),
        "KIMI_CHILD_MARKER": str(marker),
        "HAPAX_COUNCIL_DIR": str(release),
        "HAPAX_KIMI_WORKDIR": str(tmp_path),
    }
    env.pop("KIMI_CODE_HOME", None)
    return release, home, native, receipt, env


def _launch(release: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(release / "scripts/hapax-kimi"), "proof", "--terminal", "none"],
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


def test_exact_binding_allows_kimi_child(tmp_path: Path) -> None:
    release, _, _, _, env = _fixture(tmp_path)
    result = _launch(release, env)
    assert result.returncode == 0, result.stderr
    assert Path(env["KIMI_CHILD_MARKER"]).read_text() == "launched\n"


@pytest.mark.parametrize(
    "failure", ["missing", "stale", "wrong-home", "stale-source", "override-home"]
)
def test_invalid_binding_refuses_before_kimi_child(tmp_path: Path, failure: str) -> None:
    release, _, native, receipt, env = _fixture(tmp_path)
    if failure == "missing":
        native.unlink()
    elif failure == "stale":
        native.write_bytes(b"old instructions")
    elif failure == "wrong-home":
        data = json.loads(receipt.read_text())
        data["files"][1]["path"] = str(tmp_path / "other/AGENTS.md")
        receipt.write_text(json.dumps(data))
    elif failure == "stale-source":
        (release / "config/agent-instructions/AGENTS.md").write_bytes(b"new release")
    else:
        env["KIMI_CODE_HOME"] = str(tmp_path / "other-kimi-home")
    result = _launch(release, env)
    assert result.returncode != 0
    assert "instruction" in result.stderr
    assert not Path(env["KIMI_CHILD_MARKER"]).exists()
