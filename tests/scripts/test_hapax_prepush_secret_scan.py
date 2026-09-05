"""The scan-before-push hook refuses secret-shaped strings and home paths, passes clean pushes,
and honours only an explicit local exemption. Runs detect-secrets for real (via PATH or uvx)."""

from __future__ import annotations

import hashlib
import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-prepush-secret-scan"
HOOK_INSTALLER = Path(__file__).resolve().parents[2] / "scripts" / "install-git-hooks.sh"
PRE_PUSH_HOOK = Path(__file__).resolve().parents[2] / "scripts" / "pre-push"
ZERO = "0" * 40

pytestmark = pytest.mark.skipif(
    not (shutil.which("detect-secrets") or shutil.which("uvx")),
    reason="needs detect-secrets or uvx on PATH",
)


@pytest.fixture(autouse=True)
def isolated_git(tmp_path, monkeypatch):
    """Never inherit the operator's hooks, signing, Git directory, or config."""
    for key in tuple(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    template = tmp_path / "empty-template"
    template.mkdir()
    monkeypatch.setenv("GIT_TEMPLATE_DIR", str(template))


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
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
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


def test_intermediate_commit_finding_is_scanned_even_when_tip_removes_it(tmp_path):
    """Every commit transferred by the push is scanned, not only the base-to-tip diff."""
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    fake = "AKIA" + "QWERASDFZXCV1234"  # AWS access-key shape; obviously not a real key
    _commit(repo, "transient.txt", f"AWS_ACCESS_KEY_ID={fake}\n")
    tip = _commit(repo, "transient.txt", "redacted before branch tip\n")

    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert r.returncode == 1, r.stderr
    assert "secret-shaped: transient.txt" in r.stderr
    assert fake not in r.stderr and fake not in r.stdout


def test_detect_secrets_scans_a_filename_containing_whitespace(tmp_path):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    fake = "AKIA" + "MNBVCXZLKJHG1234"  # AWS access-key shape; obviously not a real key
    tip = _commit(repo, "leak file.txt", f"AWS_ACCESS_KEY_ID={fake}\n")

    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert r.returncode == 1, r.stderr
    assert "secret-shaped: leak file.txt" in r.stderr
    assert fake not in r.stderr and fake not in r.stdout


def test_detect_secrets_staging_preserves_distinct_repository_paths(tmp_path):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    fake = "AKIA" + "POIUYTREWQLK1234"  # AWS access-key shape; obviously not a real key
    (repo / "a").mkdir()
    (repo / "a" / "b").write_text(f"AWS_ACCESS_KEY_ID={fake}\n")
    (repo / "a__b").write_text("benign content that must not overwrite a/b\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add collision pair")
    tip = _git(repo, "rev-parse", "HEAD")

    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert r.returncode == 1, r.stderr
    assert "secret-shaped: a/b" in r.stderr
    assert fake not in r.stderr and fake not in r.stdout


def test_git_binary_classification_refuses_and_names_unscannable_file(tmp_path, monkeypatch):
    """A binary diff has no added-line hunks, so the hook must refuse it explicitly."""
    fake_bin = tmp_path / "detector-bin"
    fake_bin.mkdir()
    fake_detector = fake_bin / "detect-secrets"
    fake_detector.write_text("#!/bin/sh\nprintf '%s\\n' '{\"results\": {}}'\n")
    fake_detector.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")

    repo = _repo(tmp_path)
    base = _commit(repo, ".gitattributes", "*.bin binary\n")
    payload = (  # pragma: allowlist secret
        "path " + "/".join(("", "home", "someone", "private"))
    ).encode() + b"\0"
    (repo / "payload.bin").write_bytes(payload)
    _git(repo, "add", "payload.bin")
    _git(repo, "commit", "-q", "-m", "add binary-classified payload")
    tip = _git(repo, "rev-parse", "HEAD")

    assert _git(repo, "diff", "--numstat", base, tip) == "-\t-\tpayload.bin"
    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert r.returncode == 1, r.stderr
    assert "unscannable binary content: payload.bin" in r.stderr
    assert payload.decode(errors="ignore") not in r.stderr


def test_vendor_key_prefix_cannot_be_allowlisted_by_inline_pragma(tmp_path, monkeypatch):
    """The independent vendor predicate still refuses keys detect-secrets does not flag."""
    fake_bin = tmp_path / "detector-bin"
    fake_bin.mkdir()
    fake_detector = fake_bin / "detect-secrets"
    fake_detector.write_text("#!/bin/sh\nprintf '%s\\n' '{\"results\": {}}'\n")
    fake_detector.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")

    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    fake = "sk-ant-" + "api03-" + "Q" * 40  # shape only; not a key
    tip = _commit(repo, "env.txt", f"ANTHROPIC_API_KEY={fake}\n")
    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert r.returncode == 1, r.stderr
    assert "vendor-key-shaped in 1 added line(s): env.txt" in r.stderr
    assert fake not in r.stderr
    # A detect-secrets pragma must not bypass the independent vendor-prefix predicate.
    tip2 = _commit(repo, "env.txt", f"EXAMPLE={fake}  # pragma: allowlist secret\n")
    r2 = _run(repo, "origin", f"refs/heads/main {tip2} refs/heads/main {tip}\n")
    assert r2.returncode == 1, r2.stderr
    assert "vendor-key-shaped in 1 added line(s): env.txt" in r2.stderr
    assert fake not in r2.stderr and fake not in r2.stdout


def test_detector_nonzero_exit_with_valid_json_refuses_push(tmp_path, monkeypatch):
    """A parseable detector payload is not a completed scan when the process failed."""
    fake_bin = tmp_path / "detector-bin"
    fake_bin.mkdir()
    fake_detector = fake_bin / "detect-secrets"
    fake_detector.write_text("#!/bin/sh\nprintf '%s\\n' '{\"results\": {}}'\nexit 9\n")
    fake_detector.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")

    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    tip = _commit(repo, "scan-me.txt", "ordinary content\n")

    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert r.returncode == 3, r.stderr
    assert "detect-secrets failed with exit status 9" in r.stderr


def test_detector_json_without_results_refuses_push(tmp_path, monkeypatch):
    """A successful process must still return the documented results object."""
    fake_bin = tmp_path / "detector-bin"
    fake_bin.mkdir()
    fake_detector = fake_bin / "detect-secrets"
    fake_detector.write_text("#!/bin/sh\nprintf '%s\\n' '{}'\n")
    fake_detector.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")

    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    tip = _commit(repo, "scan-me.txt", "ordinary content\n")

    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert r.returncode == 3, r.stderr
    assert "detect-secrets response has no results object" in r.stderr


def test_new_branch_scans_everything_not_nothing(tmp_path):
    """Remote sha all-zero and no remote default branch known → base is the empty tree."""
    repo = _repo(tmp_path)
    tip = _commit(repo, "leak.txt", "path /home/other/secret-store\n")
    r = _run(repo, "origin", f"refs/heads/feature {tip} refs/heads/feature {ZERO}\n")
    assert r.returncode == 1, r.stderr
    assert "home path" in r.stderr


def test_new_branch_to_foreign_remote_does_not_inherit_origin_base(tmp_path, monkeypatch):
    """A target with no known base must not borrow an unrelated remote's branch tip."""
    fake_bin = tmp_path / "detector-bin"
    fake_bin.mkdir()
    fake_detector = fake_bin / "detect-secrets"
    fake_detector.write_text("#!/bin/sh\nprintf '%s\\n' '{\"results\": {}}'\n")
    fake_detector.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")

    repo = _repo(tmp_path)
    line = "path " + "/".join(("", "home", "someone", "secret-store")) + "\n"
    tip = _commit(repo, "leak.txt", line)
    _git(repo, "update-ref", "refs/remotes/origin/main", tip)

    r = _run(repo, "mirror", f"refs/heads/feature {tip} refs/heads/feature {ZERO}\n")

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


def test_scripts_dir_carries_only_the_versioned_pre_push_hook():
    """The installer copies the sole versioned hook into Git's shared hook directory."""
    present = {p.name for p in SCRIPT.parent.iterdir()} & GIT_HOOK_NAMES
    assert present == {"pre-push"}, present


def test_hook_installer_composes_pre_commit_and_pre_push_in_common_dir(tmp_path, monkeypatch):
    """Installing pre-push must preserve pre-commit in the shared common Git hook directory."""
    repo = _repo(tmp_path)
    scripts = repo / "scripts"
    scripts.mkdir()
    shutil.copy2(HOOK_INSTALLER, scripts / HOOK_INSTALLER.name)
    shutil.copy2(PRE_PUSH_HOOK, scripts / PRE_PUSH_HOOK.name)
    (repo / ".pre-commit-config.yaml").write_text("repos: []\n")

    # Stand in for pre-commit itself so this test checks our composition without installing tools.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_pre_commit = fake_bin / "pre-commit"
    fake_pre_commit.write_text(
        """#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

if sys.argv[1] == "validate-config":
    raise SystemExit(0)
if sys.argv[1:3] == ["install", "--install-hooks"]:
    common = Path(subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], text=True
    ).strip())
    hook = common / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\\nexit 0\\n")
    hook.chmod(0o755)
    raise SystemExit(0)
raise SystemExit(2)
"""
    )
    fake_pre_commit.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")

    run = subprocess.run(
        ["bash", str(scripts / HOOK_INSTALLER.name)],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    assert run.returncode == 0, run.stderr
    common_hooks = (
        Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "hooks"
    )
    assert (common_hooks / "pre-commit").stat().st_mode & 0o111
    assert (common_hooks / "pre-push").stat().st_mode & 0o111
    assert (common_hooks / "pre-push").read_bytes() == (scripts / "pre-push").read_bytes()
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "config", "--get", "core.hooksPath"],
            capture_output=True,
            text=True,
        ).returncode
        == 1
    )


def test_pre_existing_finding_in_a_changed_file_is_not_new_exposure(tmp_path):
    """A keyword-shaped line the remote already has must not make an unrelated edit unpushable;
    a NEW keyword-shaped line in the same file must. Measured 2026-09-02: the first real push
    through this hook was refused for a test fixture that has been on main for weeks."""
    repo = _repo(tmp_path)
    # The keyword names are assembled at runtime so THIS file carries no keyword-shaped line
    # (the hook scans its own pull request's diff; the fixture must exist only inside tmp_path).
    keyword_a = "OPENAI_" + "API_" + "KEY"
    keyword_b = "CODEX_" + "API_" + "KEY"
    fixture = f'env["{keyword_a}"] = "test-key-value-not-real"\n'
    base = _commit(repo, "fixture.py", fixture + "x = 1\n")
    # Unrelated edit below the pre-existing line: passes.
    tip = _commit(repo, "fixture.py", fixture + "x = 2\n")
    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert r.returncode == 0, r.stderr
    # A second keyword-shaped line ADDED: refused, and the file is named.
    tip2 = _commit(
        repo, "fixture.py", fixture + "x = 2\n" + f'env["{keyword_b}"] = "another-test-value"\n'
    )
    r2 = _run(repo, "origin", f"refs/heads/main {tip2} refs/heads/main {tip}\n")
    assert r2.returncode == 1, r2.stderr
    assert "secret-shaped: fixture.py" in r2.stderr


def test_generated_hash_bearing_artifacts_are_exempt_from_entropy_only_findings(tmp_path):
    """A re-materialized architecture map adds fresh hex digests; those are not secrets. The same
    digest in any other path is still refused, and a keyword on the generated path still is."""
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    # Computed, not literal: this file's own push must not carry a high-entropy hex line.
    digest = hashlib.sha256(b"content digest, not a secret").hexdigest()
    line = f'{{"digest": "{digest}"}}\n'
    generated = "docs/architecture/system-dynamics-map.lock.json"
    (repo / "docs" / "architecture").mkdir(parents=True)
    tip = _commit(repo, generated, line)
    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert r.returncode == 0, r.stderr

    tip2 = _commit(repo, "notes/digest.json", line)  # same content, ordinary path: refused
    r2 = _run(repo, "origin", f"refs/heads/main {tip2} refs/heads/main {tip}\n")
    assert r2.returncode == 1, r2.stderr
    assert "secret-shaped: notes/digest.json" in r2.stderr

    keyword = "OPENAI_" + "API_" + "KEY"
    tip3 = _commit(repo, generated, line + f'{{"{keyword}": "not-a-real-value-either"}}\n')
    r3 = _run(repo, "origin", f"refs/heads/main {tip3} refs/heads/main {tip2}\n")
    assert r3.returncode == 1, r3.stderr  # the exemption is entropy-only; keywords still count


def test_systemd_unit_files_have_no_home_path_exemption(tmp_path):
    """The configured private-mirror exception is the only home-path bypass."""
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    # Built at runtime so this fixture line is not itself a home path in an added line.
    line = (
        "ExecStart=" + "/".join(("", "home", "someone", "projects", "x", "scripts", "job")) + "\n"
    )
    tip = _commit(repo, "systemd/units/job.service", "[Service]\n" + line)
    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert r.returncode == 1
    assert "home path in 1 added line(s): systemd/units/job.service" in r.stderr


def test_deletion_pushes_nothing_and_passes(tmp_path):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    r = _run(repo, "origin", f"(delete) {ZERO} refs/heads/old {base}\n")
    assert r.returncode == 0, r.stderr


def _executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


@pytest.fixture
def clean_detector(tmp_path, monkeypatch):
    bin_dir = tmp_path / "clean-detector"
    bin_dir.mkdir()
    _executable(bin_dir / "detect-secrets", "#!/bin/sh\nprintf '%s\\n' '{\"results\": {}}'\n")
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    return bin_dir


def _publish_base(repo: Path, tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", "-q", "-b", "main", str(remote))
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "-u", "origin", "main")
    assert _git(repo, "rev-parse", "refs/remotes/origin/main") == _git(remote, "rev-parse", "main")
    return remote


@pytest.mark.parametrize("binary", [False, True], ids=["text", "binary"])
def test_symlink_type_change_is_scanned(tmp_path, clean_detector, binary):
    repo = _repo(tmp_path)
    path = repo / "replacement.txt"
    path.symlink_to("README.md")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "remote symlink")
    _publish_base(repo, tmp_path)
    base = _git(repo, "rev-parse", "refs/remotes/origin/main")
    home = "/".join(("", "home", "example", "private"))
    key = "sk-ant-" + "Q" * 40
    path.unlink()
    path.write_bytes(f"{home}\n{key}\n".encode() + (b"\0" if binary else b""))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "replace symlink")
    tip = _git(repo, "rev-parse", "HEAD")
    assert _git(repo, "diff", "--name-status", base, tip) == "T\treplacement.txt"

    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert result.returncode == 1, result.stderr
    if binary:
        assert "unscannable binary content: replacement.txt" in result.stderr
    else:
        assert "home path in 1 added line(s): replacement.txt" in result.stderr
        assert "vendor-key-shaped in 1 added line(s): replacement.txt" in result.stderr
    assert "Remedy:" in result.stderr
    assert home not in result.stderr and key not in result.stderr


SEPARATORS = ["\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029", "\r"]
SEPARATOR_IDS = ["vt", "ff", "fs", "gs", "rs", "nel", "ls", "ps", "cr"]


@pytest.mark.parametrize("separator", SEPARATORS, ids=SEPARATOR_IDS)
def test_git_line_boundaries_preserve_findings(tmp_path, clean_detector, monkeypatch, separator):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    home = "/".join(("", "home", "example", "private"))
    key = "sk-ant-" + "Q" * 40
    lines = [f"prefix{separator}{home}", f"prefix{separator}{key}", "last\r"]
    tip = _commit(repo, "controls.txt", "\n".join(lines) + "\n")
    scanner = runpy.run_path(str(SCRIPT))
    monkeypatch.chdir(repo)

    added = scanner["added_lines"](base, tip, ["controls.txt"])

    assert added == {"controls.txt": list(enumerate(lines, 1))}
    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert result.returncode == 1, result.stderr
    assert "home path in 1 added line(s): controls.txt" in result.stderr
    assert "vendor-key-shaped in 1 added line(s): controls.txt" in result.stderr
    assert home not in result.stderr and key not in result.stderr


@pytest.mark.parametrize("separator", SEPARATORS[5:8], ids=SEPARATOR_IDS[5:8])
def test_unicode_separators_in_ref_and_remote_names(tmp_path, clean_detector, separator):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    branch = f"feature{separator}name"
    _git(repo, "switch", "-c", branch)
    home = "/".join(("", "home", "example", "private"))
    tip = _commit(repo, "ref-content.txt", f"{home}\n")
    # This is one config value, not an exemption for a remote named origin.
    _git(repo, "config", "--add", "hapax.prepushScan.skipRemote", f"origin{separator}other")
    refs = f"refs/heads/{branch} {tip} refs/heads/{branch} {base}\n"

    result = _run(repo, "origin", refs)

    assert result.returncode == 1, result.stderr
    assert "home path in 1 added line(s): ref-content.txt" in result.stderr
    assert _run(repo, f"origin{separator}other", refs).returncode == 0


def _hook_clone(tmp_path: Path, bin_dir: Path) -> tuple[Path, Path]:
    seed = _repo(tmp_path)
    (seed / "scripts").mkdir()
    for source in (SCRIPT, HOOK_INSTALLER, PRE_PUSH_HOOK):
        shutil.copy2(source, seed / "scripts" / source.name)
    _commit(seed, ".pre-commit-config.yaml", "repos: []\n")
    remote = _publish_base(seed, tmp_path)
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(remote), str(clone))
    _git(clone, "config", "user.email", "t@example.invalid")
    _git(clone, "config", "user.name", "t")
    _executable(
        bin_dir / "pre-commit",
        """#!/bin/sh
set -eu
case "$1" in
  validate-config) exit 0 ;;
  install)
    hooks="$(git rev-parse --path-format=absolute --git-common-dir)/hooks"
    mkdir -p "$hooks"
    printf '#!/bin/sh\\nexit 0\\n' > "$hooks/pre-commit"
    chmod +x "$hooks/pre-commit"
    ;;
  *) exit 2 ;;
esac
""",
    )
    return clone, remote


def _install(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(repo / "scripts" / HOOK_INSTALLER.name)],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.fixture(params=["clone", "linked"])
def installed_checkout(tmp_path, clean_detector, request):
    clone, remote = _hook_clone(tmp_path, clean_detector)
    checkout = clone
    if request.param == "linked":
        checkout = tmp_path / "linked"
        _git(clone, "worktree", "add", "-q", "-b", "linked", str(checkout))
        _git(checkout, "push", "-q", "origin", "HEAD")
    result = _install(checkout)
    assert result.returncode == 0, result.stderr
    hooks = Path(_git(checkout, "rev-parse", "--path-format=absolute", "--git-path", "hooks"))
    assert hooks == Path(_git(clone, "rev-parse", "--absolute-git-dir")) / "hooks"
    assert (hooks / "pre-commit").stat().st_mode & 0o111
    return checkout, clone, remote


def _push(repo: Path, hook_status: int) -> subprocess.CompletedProcess:
    """Use Git's real dispatch and check the hook's exit as well as Git's push status."""
    trace = repo.parent / "push-trace.jsonl"
    trace.unlink(missing_ok=True)
    result = subprocess.run(
        ["git", "push", "origin", "HEAD"],
        cwd=repo,
        env={**os.environ, "GIT_TRACE2_EVENT": str(trace)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    events = [json.loads(line) for line in trace.read_text().split("\n") if line]
    hooks = [e for e in events if e["event"] == "child_start" and e.get("hook_name") == "pre-push"]
    assert len(hooks) == 1, "Git did not dispatch the installed pre-push hook"
    hook = hooks[0]
    exits = [
        e["code"]
        for e in events
        if e["event"] == "child_exit"
        and e["sid"] == hook["sid"]
        and e["child_id"] == hook["child_id"]
    ]
    assert exits == [hook_status], result.stderr
    assert result.returncode == (0 if hook_status == 0 else 1), result.stderr
    return result


@pytest.mark.parametrize("dirty", [False, True], ids=["clean", "dirty"])
def test_installed_hook_push(installed_checkout, dirty):
    checkout, _clone, remote = installed_checkout
    branch = _git(checkout, "branch", "--show-current")
    base = _git(remote, "rev-parse", branch)
    home = "/".join(("", "home", "example", "private"))
    key = "sk-ant-" + "Q" * 40
    tip = _commit(checkout, "push-content.txt", f"{home}\n{key}\n" if dirty else "clean\n")

    result = _push(checkout, 1 if dirty else 0)

    assert _git(remote, "rev-parse", branch) == (base if dirty else tip)
    if dirty:
        assert "home path in 1 added line(s): push-content.txt" in result.stderr
        assert "vendor-key-shaped in 1 added line(s): push-content.txt" in result.stderr
        assert "Remedy: remove or redact" in result.stderr
        assert home not in result.stderr and key not in result.stderr


@pytest.mark.parametrize("hooks_path", ["elsewhere", ""], ids=["directory", "empty"])
def test_installer_refuses_conflicting_hooks_path(tmp_path, clean_detector, hooks_path):
    clone, _remote = _hook_clone(tmp_path, clean_detector)
    _git(clone, "config", "core.hooksPath", hooks_path)

    result = _install(clone)

    assert result.returncode == 1, result.stderr
    assert "it would mask the shared hooks" in result.stderr
    assert "git config --unset-all core.hooksPath" in result.stderr
    assert "file:.git/config" in _git(clone, "config", "--show-origin", "core.hooksPath")
    assert _git(clone, "rev-parse", "--git-path", "hooks") == (hooks_path or "./")
    assert not (clone / ".git" / "hooks" / "pre-push").exists()


@pytest.mark.parametrize("dirty", [False, True], ids=["clean", "dirty"])
def test_installed_hook_falls_back_to_main_checkout(tmp_path, clean_detector, dirty):
    clone, remote = _hook_clone(tmp_path, clean_detector)
    assert _install(clone).returncode == 0
    linked = tmp_path / "linked"
    _git(clone, "worktree", "add", "-q", "-b", "linked", str(linked))
    (linked / "scripts" / SCRIPT.name).unlink()
    home = "/".join(("", "home", "example", "private"))
    tip = _commit(linked, "fallback.txt", f"{home}\n" if dirty else "clean\n")
    assert not _git(linked, "ls-tree", "HEAD", f"scripts/{SCRIPT.name}")

    result = _push(linked, 1 if dirty else 0)

    if dirty:
        assert "home path in 1 added line(s): fallback.txt" in result.stderr
        assert "Remedy: remove or redact" in result.stderr
        assert not _git(remote, "for-each-ref", "--format=%(refname)", "refs/heads/linked")
    else:
        assert _git(remote, "rev-parse", "linked") == tip


def test_installed_hook_refuses_missing_scanner(installed_checkout):
    checkout, clone, remote = installed_checkout
    branch = _git(checkout, "branch", "--show-current")
    base = _git(remote, "rev-parse", branch)
    for repo in {checkout, clone}:
        (repo / "scripts" / SCRIPT.name).unlink()
    _commit(checkout, "missing-scanner.txt", "clean\n")

    result = _push(checkout, 3)

    assert "scanner missing at" in result.stderr
    assert "Remedy: restore scripts/hapax-prepush-secret-scan" in result.stderr
    assert _git(remote, "rev-parse", branch) == base


@pytest.mark.parametrize("failure", ["timeout", "invalid-json", "blob-read"])
def test_installed_hook_scan_failure(installed_checkout, clean_detector, failure):
    checkout, _clone, remote = installed_checkout
    branch = _git(checkout, "branch", "--show-current")
    base = _git(remote, "rev-parse", branch)
    _commit(checkout, "scan-me.txt", "ordinary content\n")
    if failure == "invalid-json":
        _executable(clean_detector / "detect-secrets", "#!/bin/sh\nprintf 'invalid json'\n")
        reason = "detect-secrets produced invalid JSON"
        remedy = "repair or reinstall detect-secrets"
    elif failure == "timeout":
        _executable(
            clean_detector / "detect-secrets",
            f"#!{sys.executable}\nimport time\ntime.sleep(60)\n",
        )
        # Run the unchanged installed wrapper/scanner; shorten only the subprocess deadline.
        _executable(
            clean_detector / "python3",
            f"#!{sys.executable}\n"
            "import runpy, subprocess, sys\n"
            "original_run = subprocess.run\n"
            "def short_deadline(*args, **kwargs):\n"
            "    if 'timeout' in kwargs:\n"
            "        assert kwargs['timeout'] == 600\n"
            "        kwargs['timeout'] = 0.05\n"
            "    return original_run(*args, **kwargs)\n"
            "subprocess.run = short_deadline\n"
            "sys.argv = sys.argv[1:]\n"
            "runpy.run_path(sys.argv[0], run_name='__main__')\n",
        )
        reason = "detect-secrets unavailable (TimeoutExpired)"
        remedy = "repair the detector before retrying"
    else:
        # Git prepends its exec path when dispatching hooks, so inject at the Python
        # subprocess boundary instead of relying on a PATH shim named git.
        _executable(
            clean_detector / "python3",
            f"#!{sys.executable}\n"
            "import runpy, subprocess, sys\n"
            "original_run = subprocess.run\n"
            "def unreadable_blob(cmd, *args, **kwargs):\n"
            "    if cmd[:2] == ['git', 'show'] and cmd[2].endswith(':scan-me.txt'):\n"
            "        return subprocess.CompletedProcess(cmd, 128, b'', b'')\n"
            "    return original_run(cmd, *args, **kwargs)\n"
            "subprocess.run = unreadable_blob\n"
            "sys.argv = sys.argv[1:]\n"
            "runpy.run_path(sys.argv[0], run_name='__main__')\n",
        )
        reason = "could not read committed content"
        remedy = "repair or fetch the missing Git object"

    result = _push(checkout, 3)

    assert reason in result.stderr
    assert "unscanned content: scan-me.txt" in result.stderr
    assert "Remedy:" in result.stderr and remedy in result.stderr
    assert _git(remote, "rev-parse", branch) == base


def test_runbook_verification_detects_masked_hooks(installed_checkout):
    checkout, _clone, _remote = installed_checkout
    runbook = SCRIPT.parents[1] / "docs" / "runbooks" / "pre-commit-bootstrap.md"
    commands = runbook.read_text().split("## Verify\n\n```bash\n", 1)[1].split("```", 1)[0]

    def verify():
        return subprocess.run(
            ["bash", "-c", commands], cwd=checkout, capture_output=True, text=True, timeout=30
        )

    assert verify().returncode == 0
    # Both common hooks still exist, but a per-worktree override changes Git's dispatch.
    _git(checkout, "config", "extensions.worktreeConfig", "true")
    _git(checkout, "config", "--worktree", "core.hooksPath", "elsewhere")
    result = verify()
    assert result.returncode == 1, result.stdout
    assert "core.hooksPath masks the shared hooks" in result.stderr
    assert "Clear it at the reported origin" in result.stderr


@pytest.mark.parametrize("operation", ["delete", "copy", "rename"])
def test_content_status_selection(tmp_path, clean_detector, operation):
    repo = _repo(tmp_path)
    home = "/".join(("", "home", "example", "private"))
    base = _commit(repo, "source.txt", f"{home}\n")
    _publish_base(repo, tmp_path)
    _git(repo, "config", "diff.renames", "copies")
    source = repo / "source.txt"
    if operation == "delete":
        source.unlink()
    elif operation == "copy":
        shutil.copy2(source, repo / "destination.txt")
    else:
        source.rename(repo / "destination.txt")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", operation)
    tip = _git(repo, "rev-parse", "HEAD")
    status = _git(repo, "diff", "--name-status", "-C", "--find-copies-harder", base, tip)
    assert status.startswith({"delete": "D\t", "copy": "C100\t", "rename": "R100\t"}[operation])

    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert result.returncode == (0 if operation == "delete" else 1), result.stderr
    if operation != "delete":
        assert "home path in 1 added line(s): destination.txt" in result.stderr
