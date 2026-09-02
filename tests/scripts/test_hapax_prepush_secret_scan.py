"""The scan-before-push hook refuses secret-shaped strings and home paths, passes clean pushes,
and honours only an explicit local exemption. Runs detect-secrets for real (via PATH or uvx)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-prepush-secret-scan"
ZERO = "0" * 40

pytestmark = pytest.mark.skipif(
    not (shutil.which("detect-secrets") or shutil.which("uvx")),
    reason="needs detect-secrets or uvx on PATH",
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("clean\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _commit(repo: Path, name: str, text: str) -> str:
    (repo / name).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"add {name}")
    return _git(repo, "rev-parse", "HEAD")


def _run(repo: Path, remote: str, refs: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), remote, "https://example.invalid/x.git"],
        cwd=repo,
        input=refs,
        capture_output=True,
        text=True,
        timeout=900,
    )


def test_refuses_secret_and_home_path_and_names_types_only(tmp_path):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    key = "AKIA" + "ZZZZAAAAQQQQ1234"  # AWS access-key shape; not a real key
    tip = _commit(repo, "cfg.py", f'AWS_KEY = "{key}"\nLOG = "/home/someone/.cache/x.log"\n')
    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert r.returncode == 1, r.stderr
    assert "secret-shaped: cfg.py" in r.stderr
    assert "home path in 1 added line(s): cfg.py" in r.stderr
    assert key not in r.stderr and key not in r.stdout  # types and counts only, never values
    assert "Remedy:" in r.stderr


def test_clean_push_passes(tmp_path):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    tip = _commit(repo, "notes.md", "nothing secret here; relative paths only: ~/.cache/x\n")
    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert r.returncode == 0, r.stderr


def test_vendor_key_prefixes_detect_secrets_does_not_know(tmp_path):
    """Anthropic-shaped keys are not in detect-secrets 1.5.0's plugin set; the hook's own regex is."""
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    fake = "sk-ant-" + "api03-" + "Q" * 40  # shape only; not a key
    tip = _commit(repo, "env.txt", f"ANTHROPIC_API_KEY={fake}\n")
    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert r.returncode == 1, r.stderr
    assert "vendor-key-shaped in 1 added line(s): env.txt" in r.stderr
    assert fake not in r.stderr
    # the allowlist pragma is honoured for the regex detector too
    tip2 = _commit(repo, "env.txt", f"EXAMPLE={fake}  # pragma: allowlist secret\n")
    r2 = _run(repo, "origin", f"refs/heads/main {tip2} refs/heads/main {tip}\n")
    assert r2.returncode == 0, r2.stderr


def test_new_branch_scans_everything_not_nothing(tmp_path):
    """Remote sha all-zero and no remote default branch known → base is the empty tree."""
    repo = _repo(tmp_path)
    tip = _commit(repo, "leak.txt", "path /home/other/secret-store\n")
    r = _run(repo, "origin", f"refs/heads/feature {tip} refs/heads/feature {ZERO}\n")
    assert r.returncode == 1, r.stderr
    assert "home path" in r.stderr


def test_exemption_only_by_explicit_local_config(tmp_path):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    tip = _commit(repo, "leak.txt", "path /home/other/secret-store\n")
    refs = f"refs/heads/main {tip} refs/heads/main {base}\n"
    assert _run(repo, "mirror", refs).returncode == 1
    _git(repo, "config", "--add", "hapax.prepushScan.skipRemote", "mirror")
    assert _run(repo, "mirror", refs).returncode == 0
    assert _run(repo, "origin", refs).returncode == 1  # exemption is per remote name, not global


GIT_HOOK_NAMES = {
    "applypatch-msg",
    "pre-applypatch",
    "post-applypatch",
    "pre-commit",
    "pre-merge-commit",
    "prepare-commit-msg",
    "commit-msg",
    "post-commit",
    "pre-rebase",
    "post-checkout",
    "post-merge",
    "pre-push",
    "pre-receive",
    "update",
    "proc-receive",
    "post-receive",
    "post-update",
    "push-to-checkout",
    "pre-auto-gc",
    "post-rewrite",
    "sendemail-validate",
    "fsmonitor-watchman",
    "reference-transaction",
    "post-index-change",
}


def test_scripts_dir_carries_no_other_git_hook_name():
    """`core.hooksPath scripts` makes git execute ANY file in scripts/ that carries a hook name.
    Only pre-push may exist there; a future scripts/post-merge would silently become a hook."""
    present = {p.name for p in SCRIPT.parent.iterdir()} & GIT_HOOK_NAMES
    assert present == {"pre-push"}, present


def test_deletion_pushes_nothing_and_passes(tmp_path):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    r = _run(repo, "origin", f"(delete) {ZERO} refs/heads/old {base}\n")
    assert r.returncode == 0, r.stderr
