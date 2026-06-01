"""Cumulative ``--since`` deploy + ``last-deployed-sha`` receipt for
``scripts/hapax-post-merge-deploy``.

reform-deploy-chain-repair-20260601 (CASE-SDLC-REFORM-001): the single-merge
first-parent diff silently skips intermediate merges' units/confs/scripts when
origin/main jumps several merges between deploy cycles — the mechanism behind
the "merged but never realized" deploy backlog. ``--since <sha>`` deploys the
CUMULATIVE union diff so one run realizes the whole backlog, and every real
deploy stamps a ``last-deployed-sha`` receipt that the staleness alarm and the
acceptance ``rev-list <last-deployed>..origin/main`` check read.

The script shells out to ``systemctl --user``; these tests intercept it with a
fake on PATH and run the real script against throwaway git repos so commit-time
content is read exactly the way production reads it.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-post-merge-deploy"


def _git(repo: Path, *args: str) -> str:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
    )
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()


def _fake_systemctl(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    calls = tmp_path / "systemctl-calls.txt"
    stub = bin_dir / "systemctl"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >> "$HAPAX_SYSTEMCTL_CALLS"\n'
        'case "$*" in\n'
        '  *"is-active --quiet"*) exit 1 ;;\n'
        "  *) exit 0 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return bin_dir, calls


def _unit(name: str) -> str:
    return f"[Unit]\nDescription={name}\n\n[Service]\nType=oneshot\nExecStart=/bin/true\n"


def _repo_with_three_unit_commits(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """base → c1 (adds unit-a) → c2 (adds unit-b) → c3 (adds unit-c), linear."""
    repo = tmp_path / "repo"
    (repo / "systemd" / "units").mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    shas = {"base": _git(repo, "rev-parse", "HEAD")}
    for key, unit in (
        ("c1", "hapax-unit-a.service"),
        ("c2", "hapax-unit-b.service"),
        ("c3", "hapax-unit-c.service"),
    ):
        (repo / "systemd" / "units" / unit).write_text(_unit(unit), encoding="utf-8")
        _git(repo, "add", f"systemd/units/{unit}")
        _git(repo, "commit", "-m", f"add {unit}")
        shas[key] = _git(repo, "rev-parse", "HEAD")
    return repo, shas


def _env(repo: Path, bin_dir: Path, tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(tmp_path / "systemctl-calls.txt"),
            "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "traces" / "post-merge-traces.jsonl"),
        }
    )
    env.pop("GITHUB_WORKSPACE", None)
    return env


def _run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), *args], text=True, capture_output=True, check=False, env=env
    )


def _installed(tmp_path: Path, unit: str) -> Path:
    return tmp_path / "home" / ".config" / "systemd" / "user" / unit


def _receipt(tmp_path: Path) -> Path:
    return tmp_path / "traces" / "last-deployed-sha"


def test_since_deploys_cumulative_union_not_just_tip(tmp_path: Path) -> None:
    """`--since base tip` installs every unit across the range, not only the
    tip merge's first-parent diff (which would be unit-c alone)."""
    repo, shas = _repo_with_three_unit_commits(tmp_path)
    bin_dir, _calls = _fake_systemctl(tmp_path)
    env = _env(repo, bin_dir, tmp_path)

    result = _run(["--since", shas["base"], shas["c3"]], env)

    assert result.returncode == 0, result.stderr
    for unit in ("hapax-unit-a.service", "hapax-unit-b.service", "hapax-unit-c.service"):
        assert _installed(tmp_path, unit).is_file(), (
            f"{unit} should be installed by cumulative --since"
        )
    record = json.loads(
        (tmp_path / "traces" / "post-merge-traces.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert sorted(record["deploy_groups"]["systemd_units"]) == [
        "systemd/units/hapax-unit-a.service",
        "systemd/units/hapax-unit-b.service",
        "systemd/units/hapax-unit-c.service",
    ]
    assert record["sha"] == shas["c3"]


def test_plain_tip_deploy_only_covers_first_parent_diff(tmp_path: Path) -> None:
    """Contrast: a plain `<tip>` deploy on a linear history covers only the tip
    commit's own diff — proving --since is what closes the multi-merge gap."""
    repo, shas = _repo_with_three_unit_commits(tmp_path)
    bin_dir, _calls = _fake_systemctl(tmp_path)
    env = _env(repo, bin_dir, tmp_path)

    result = _run([shas["c3"]], env)

    assert result.returncode == 0, result.stderr
    assert _installed(tmp_path, "hapax-unit-c.service").is_file()
    assert not _installed(tmp_path, "hapax-unit-a.service").exists()
    assert not _installed(tmp_path, "hapax-unit-b.service").exists()


def test_last_deployed_sha_receipt_written_on_completed(tmp_path: Path) -> None:
    repo, shas = _repo_with_three_unit_commits(tmp_path)
    bin_dir, _calls = _fake_systemctl(tmp_path)
    env = _env(repo, bin_dir, tmp_path)

    result = _run([shas["c3"]], env)

    assert result.returncode == 0, result.stderr
    assert _receipt(tmp_path).read_text(encoding="utf-8").strip() == shas["c3"]


def test_last_deployed_sha_receipt_written_on_no_changes(tmp_path: Path) -> None:
    """A deploy of a commit with no deployable files still advances the receipt
    so the staleness alarm does not false-positive on a quiet merge."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    (repo / "docs.md").write_text("docs only — nothing deployable\n", encoding="utf-8")
    _git(repo, "add", "docs.md")
    _git(repo, "commit", "-m", "docs only")
    sha = _git(repo, "rev-parse", "HEAD")
    bin_dir, _calls = _fake_systemctl(tmp_path)
    env = _env(repo, bin_dir, tmp_path)

    result = _run([sha], env)

    assert result.returncode == 0, result.stderr
    assert "no files changed" in result.stdout or _receipt(tmp_path).exists()
    assert _receipt(tmp_path).read_text(encoding="utf-8").strip() == sha


def test_dry_run_does_not_write_last_deployed_sha(tmp_path: Path) -> None:
    repo, shas = _repo_with_three_unit_commits(tmp_path)
    bin_dir, _calls = _fake_systemctl(tmp_path)
    env = _env(repo, bin_dir, tmp_path)

    result = _run(["--dry-run", "--since", shas["base"], shas["c3"]], env)

    assert result.returncode == 0, result.stderr
    assert not _receipt(tmp_path).exists(), "dry-run must not stamp the last-deployed receipt"
    # ...but the dry-run trace must still reflect the cumulative file set.
    record = json.loads(
        (tmp_path / "traces" / "post-merge-traces.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert record["mode"] == "dry_run"
    assert sorted(record["deploy_groups"]["systemd_units"]) == [
        "systemd/units/hapax-unit-a.service",
        "systemd/units/hapax-unit-b.service",
        "systemd/units/hapax-unit-c.service",
    ]


def test_since_rejects_invalid_base_commit(tmp_path: Path) -> None:
    repo, shas = _repo_with_three_unit_commits(tmp_path)
    bin_dir, _calls = _fake_systemctl(tmp_path)
    env = _env(repo, bin_dir, tmp_path)

    result = _run(["--since", "0000000000000000000000000000000000000000", shas["c3"]], env)

    assert result.returncode == 2
    assert "not a valid commit" in result.stderr


def test_custom_last_deployed_sha_path_override(tmp_path: Path) -> None:
    """The receipt path is overridable so the .service / rebuild-service can
    point all readers/writers at one canonical file."""
    repo, shas = _repo_with_three_unit_commits(tmp_path)
    bin_dir, _calls = _fake_systemctl(tmp_path)
    env = _env(repo, bin_dir, tmp_path)
    custom = tmp_path / "custom-last-deployed-sha"
    env["HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH"] = str(custom)

    result = _run([shas["c3"]], env)

    assert result.returncode == 0, result.stderr
    assert custom.read_text(encoding="utf-8").strip() == shas["c3"]
    assert not _receipt(tmp_path).exists()
