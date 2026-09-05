"""The manual review-dispatch launcher delivers the public-gate signing key, or refuses."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = REPO_ROOT / "scripts" / "hapax-pr-review-dispatch-signed"
KEY_ENV = "HAPAX_PUBLIC_GATE_AUTHORITY_HMAC_KEY"
ENTRY = "hapax-public-gate-authority-hmac-key"
SYNTHETIC = "synthetic-public-gate-launcher-value"  # pragma: allowlist secret


def _run(tmp_path: Path, secret_body: str, *args: str) -> tuple[subprocess.CompletedProcess, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    seen = tmp_path / "uv-seen.txt"
    fake_secret = bin_dir / "hapax-secret"
    fake_secret.write_text("#!/usr/bin/env bash\n" + secret_body)
    fake_secret.chmod(0o755)
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'argv=%s\\n' \"$*\" > {seen}\n"
        f'if [ "${{{KEY_ENV}:-}}" = "{SYNTHETIC}" ]; then echo key=delivered >> {seen}; '
        f"else echo key=missing >> {seen}; fi\n"
    )
    fake_uv.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != KEY_ENV}
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    result = subprocess.run(
        ["bash", str(LAUNCHER), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    return result, seen


def test_launcher_is_valid_executable_bash() -> None:
    assert subprocess.run(["bash", "-n", str(LAUNCHER)], check=False).returncode == 0
    mode = subprocess.run(
        ["git", "ls-files", "-s", "--", str(LAUNCHER.relative_to(REPO_ROOT))],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split(" ", 1)[0]
    assert mode == "100755"


def test_launcher_delivers_key_by_environment_only(tmp_path: Path) -> None:
    result, seen = _run(
        tmp_path,
        f'[ "$1" = "{ENTRY}" ] && {{ printf "%s\\n" "{SYNTHETIC}"; exit 0; }}\nexit 1\n',
        "--pr",
        "4642",
    )
    assert result.returncode == 0, result.stderr
    observed = seen.read_text()
    assert "key=delivered" in observed
    assert "run python scripts/cc-pr-review-dispatch.py --pr 4642" in observed
    assert SYNTHETIC not in observed.split("key=")[0]
    assert SYNTHETIC not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "secret_body",
    [
        "exit 1\n",  # unresolvable
        'printf "\\n"; exit 0\n',  # present but empty
    ],
)
def test_launcher_refuses_instead_of_dispatching_unsigned(tmp_path: Path, secret_body) -> None:
    result, seen = _run(tmp_path, secret_body, "--all")
    assert result.returncode == 2
    assert not seen.exists()
    assert "refusing to dispatch unsigned" in result.stderr
    assert "FileStore" in result.stderr
    assert "Next action:" in result.stderr
    assert "from pass" not in result.stderr
    assert "pass show" not in result.stderr
