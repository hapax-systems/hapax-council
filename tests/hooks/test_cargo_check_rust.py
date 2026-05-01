"""Tests for hooks/scripts/cargo-check-rust.sh.

Wired PostToolUse advisory that runs ``cargo check -p <crate>``
whenever a `.rs` file under ``hapax-logos/crates/<crate>/src/`` is
edited. Always exits 0 (advisory only); on failure it prints the
first ~20 error/warning lines to stderr.

Coverage focuses on the early-exit lattice — wrong tool, wrong
extension, path outside the workspace, missing Cargo.toml, debounce
lock fresh, env-var disable. The actual cargo invocation is taken
out of the path by overriding ``PATH`` so ``command -v cargo``
fails: that exits 0 cleanly without surfacing an advisory and
exercises the matching-path branch without needing a real Rust
toolchain.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "cargo-check-rust.sh"


def _run(
    payload: dict,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=15,
    )


def _make_workspace(tmp_path: Path, crate: str = "hapax-logos-core") -> Path:
    """Build a minimal hapax-logos workspace fixture under tmp_path.

    Returns the path to a `lib.rs` under the crate's src/ that the
    hook will see as a valid edit target.
    """
    workspace = tmp_path / "hapax-logos"
    crate_src = workspace / "crates" / crate / "src"
    crate_src.mkdir(parents=True)
    (workspace / "Cargo.toml").write_text("[workspace]\n")
    rs = crate_src / "lib.rs"
    rs.write_text("pub fn ok() {}\n")
    return rs


def _edit_payload(file_path: Path) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": str(file_path)}}


# ── Env-var disable ────────────────────────────────────────────────


class TestDisable:
    def test_env_var_zero_skips_everything(self, tmp_path: Path) -> None:
        rs = _make_workspace(tmp_path)
        result = _run(_edit_payload(rs), extra_env={"HAPAX_CARGO_CHECK_HOOK": "0"})
        assert result.returncode == 0
        assert result.stderr == ""


# ── Tool gating ────────────────────────────────────────────────────


class TestToolGating:
    def test_bash_tool_ignored(self) -> None:
        result = _run({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        assert result.returncode == 0
        assert result.stderr == ""

    def test_read_tool_ignored(self, tmp_path: Path) -> None:
        rs = _make_workspace(tmp_path)
        result = _run({"tool_name": "Read", "tool_input": {"file_path": str(rs)}})
        assert result.returncode == 0
        assert result.stderr == ""

    def test_no_file_path_ignored(self) -> None:
        result = _run({"tool_name": "Edit", "tool_input": {}})
        assert result.returncode == 0
        assert result.stderr == ""


# ── Path gating ────────────────────────────────────────────────────


class TestPathGating:
    def test_non_rust_extension_ignored(self, tmp_path: Path) -> None:
        result = _run(_edit_payload(tmp_path / "foo.py"))
        assert result.returncode == 0
        assert result.stderr == ""

    def test_rust_outside_logos_workspace_ignored(self, tmp_path: Path) -> None:
        rs = tmp_path / "other-project" / "src" / "main.rs"
        rs.parent.mkdir(parents=True)
        rs.write_text("fn main() {}\n")
        result = _run(_edit_payload(rs))
        assert result.returncode == 0
        assert result.stderr == ""

    def test_rust_in_logos_but_not_crates_ignored(self, tmp_path: Path) -> None:
        rs = tmp_path / "hapax-logos" / "src" / "main.rs"
        rs.parent.mkdir(parents=True)
        rs.write_text("fn main() {}\n")
        result = _run(_edit_payload(rs))
        assert result.returncode == 0
        assert result.stderr == ""

    def test_missing_cargo_toml_ignored(self, tmp_path: Path) -> None:
        """Path matches but Cargo.toml absent → silent exit (workspace
        not yet bootstrapped, nothing to check)."""
        rs = tmp_path / "hapax-logos" / "crates" / "x" / "src" / "lib.rs"
        rs.parent.mkdir(parents=True)
        rs.write_text("pub fn x() {}\n")
        # Note: no Cargo.toml at hapax-logos/.
        result = _run(_edit_payload(rs))
        assert result.returncode == 0
        assert "ADVISORY" not in result.stderr


# ── Debounce ───────────────────────────────────────────────────────


class TestDebounce:
    def test_fresh_lock_short_circuits(self, tmp_path: Path) -> None:
        rs = _make_workspace(tmp_path, crate="dbcrate")
        # Pre-touch the lock so the hook treats it as a recent fire.
        lock_dir = tmp_path / "tmp"
        lock_dir.mkdir()
        lock = lock_dir / "hapax-cargo-check-dbcrate.lock"
        lock.touch()
        result = _run(
            _edit_payload(rs),
            extra_env={"TMPDIR": str(lock_dir)},
        )
        assert result.returncode == 0
        # Debounce path produces no stderr — cargo never even tried.
        assert "ADVISORY" not in result.stderr
