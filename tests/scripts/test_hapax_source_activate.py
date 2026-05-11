import json
import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-source-activate"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _write(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def _make_repos(tmp_path: Path) -> tuple[Path, Path, str]:
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    canonical = tmp_path / "canonical"
    _git(tmp_path, "init", "--bare", "-b", "main", str(origin))

    seed.mkdir()
    _git(seed, "init", "-b", "main")
    _git(seed, "config", "user.email", "source-activate@example.test")
    _git(seed, "config", "user.name", "Source Activate")
    _write(seed / "README.md", "base\n")
    _write(seed / "config" / "usb-topology-policy.json", '{"known_absences": {}}\n')
    _write(
        seed / "scripts" / "hapax-post-merge-deploy",
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            printf '%s\\n' "$1" >> "$HAPAX_FAKE_DEPLOY_RECORD"
            exit "${HAPAX_FAKE_DEPLOY_EXIT:-0}"
            """
        ),
        executable=True,
    )
    _write(seed / "scripts" / "cc-claim", "#!/usr/bin/env bash\nexit 0\n", executable=True)
    _write(seed / "scripts" / "cc-close", "#!/usr/bin/env bash\nexit 0\n", executable=True)
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "base")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "-u", "origin", "main")

    _git(tmp_path, "clone", str(origin), str(canonical))
    _git(canonical, "checkout", "--detach", "HEAD")
    _write(canonical / "operator-wip.txt", "do not touch\n")

    _write(seed / "README.md", "base\nnew origin main\n")
    _git(seed, "add", "README.md")
    _git(seed, "commit", "-m", "advance origin main")
    _git(seed, "push", "origin", "main")
    new_sha = _git(seed, "rev-parse", "HEAD")
    return canonical, origin, new_sha


def _run_activate(
    tmp_path: Path,
    canonical: Path,
    *,
    deploy_exit: int = 0,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["HAPAX_SOURCE_ACTIVATE_CANONICAL"] = str(canonical)
    env["HAPAX_SOURCE_ACTIVATE_WORKTREE"] = str(tmp_path / "active-source")
    env["HAPAX_SOURCE_ACTIVATE_STATE_DIR"] = str(tmp_path / "state")
    env["HAPAX_FAKE_DEPLOY_RECORD"] = str(tmp_path / "deploy-record.txt")
    env["HAPAX_FAKE_DEPLOY_EXIT"] = str(deploy_exit)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [str(SCRIPT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _current_receipt(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "state" / "current.json").read_text(encoding="utf-8"))


def test_activation_uses_clean_worktree_without_touching_dirty_canonical(tmp_path: Path) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)
    before_head = _git(canonical, "rev-parse", "HEAD")
    before_status = _git(canonical, "status", "--porcelain=v1")

    result = _run_activate(tmp_path, canonical)

    assert result.returncode == 0, result.stderr
    assert _git(canonical, "rev-parse", "HEAD") == before_head
    assert _git(canonical, "status", "--porcelain=v1") == before_status
    assert _git(tmp_path / "active-source", "rev-parse", "HEAD") == new_sha
    assert (tmp_path / "deploy-record.txt").read_text(encoding="utf-8").splitlines() == [new_sha]
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "completed"
    assert receipt["deploy_status"] == "success"
    assert receipt["origin_main_sha"] == new_sha
    assert receipt["active_source_head"] == new_sha
    assert receipt["canonical"]["dirty_count"] == 1
    assert (tmp_path / "state" / "last-success-sha").read_text(encoding="utf-8").strip() == new_sha


def test_activation_hold_exits_before_fetch_reset_symlink_sweep_or_deploy(
    tmp_path: Path,
) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"HAPAX_SOURCE_ACTIVATE_HOLD": "1"},
    )

    assert result.returncode == 0, result.stderr
    assert "held before fetch/reset/symlink sweep/deploy" in result.stderr
    assert not (tmp_path / "active-source").exists()
    assert not (tmp_path / "deploy-record.txt").exists()
    assert not (tmp_path / "home" / ".local" / "bin" / "cc-claim").exists()
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "held"
    assert receipt["deploy_status"] == "skipped_hold"
    assert receipt["active_source_head"] == "unknown"


def test_same_sha_rerun_writes_no_op_and_does_not_redeploy(tmp_path: Path) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    local_bin = tmp_path / "home" / ".local" / "bin"
    installed_policy = tmp_path / "home" / ".config" / "hapax" / "usb-topology-policy.json"
    (local_bin / "cc-claim").unlink()
    (local_bin / "cc-close").unlink()
    installed_policy.unlink()
    second = _run_activate(tmp_path, canonical)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert (tmp_path / "deploy-record.txt").read_text(encoding="utf-8").splitlines() == [new_sha]
    assert (local_bin / "cc-claim").resolve() == tmp_path / "active-source" / "scripts" / "cc-claim"
    assert (local_bin / "cc-close").resolve() == tmp_path / "active-source" / "scripts" / "cc-close"
    assert installed_policy.exists()
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "no_op"
    assert receipt["deploy_status"] == "skipped_already_active"
    history = (tmp_path / "state" / "source-activation.jsonl").read_text(encoding="utf-8")
    assert '"status": "completed"' in history
    assert '"status": "no_op"' in history


def test_activation_quarantines_untracked_active_source_before_sweep(tmp_path: Path) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr
    active_source = tmp_path / "active-source"
    rogue = active_source / "scripts" / "hapax-rogue-untracked"
    rogue.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    rogue.chmod(0o755)
    local_bin = tmp_path / "home" / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)
    (local_bin / "hapax-rogue-untracked").symlink_to(rogue)

    second = _run_activate(tmp_path, canonical)

    assert second.returncode == 0, second.stderr
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    assert not rogue.exists()
    assert not (local_bin / "hapax-rogue-untracked").exists()
    quarantined = list(
        (tmp_path / "state" / "untracked-quarantine").glob("*/scripts/hapax-rogue-untracked")
    )
    assert len(quarantined) == 1
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "no_op"
    assert receipt["source_hygiene"]["untracked_quarantine_count"] == 1
    assert receipt["source_hygiene"]["untracked_symlink_removed_count"] == 1
    assert "untracked-quarantine" in receipt["source_hygiene"]["untracked_quarantine_path"]


def test_failed_deploy_writes_failed_receipt_without_last_success(tmp_path: Path) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)

    result = _run_activate(tmp_path, canonical, deploy_exit=7)

    assert result.returncode == 7
    assert _git(tmp_path / "active-source", "rev-parse", "HEAD") == new_sha
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["deploy_status"] == "failed"
    assert receipt["exit_code"] == 7
    assert not (tmp_path / "state" / "last-success-sha").exists()


def test_activation_sweeps_cc_task_tools_into_local_bin(tmp_path: Path) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    result = _run_activate(tmp_path, canonical)

    assert result.returncode == 0, result.stderr
    local_bin = tmp_path / "home" / ".local" / "bin"
    active_source = tmp_path / "active-source"
    assert (local_bin / "cc-claim").resolve() == active_source / "scripts" / "cc-claim"
    assert (local_bin / "cc-close").resolve() == active_source / "scripts" / "cc-close"


def test_activation_syncs_usb_topology_policy_config(tmp_path: Path) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    result = _run_activate(tmp_path, canonical)

    assert result.returncode == 0, result.stderr
    installed_policy = tmp_path / "home" / ".config" / "hapax" / "usb-topology-policy.json"
    active_policy = tmp_path / "active-source" / "config" / "usb-topology-policy.json"
    assert installed_policy.read_text(encoding="utf-8") == active_policy.read_text(encoding="utf-8")


def test_activation_syncs_active_source_dependencies_before_deploy(tmp_path: Path) -> None:
    canonical, origin, new_sha = _make_repos(tmp_path)
    dep_seed = tmp_path / "dep-seed"
    _git(tmp_path, "clone", str(origin), str(dep_seed))
    _git(dep_seed, "config", "user.email", "source-activate@example.test")
    _git(dep_seed, "config", "user.name", "Source Activate")
    _write(dep_seed / "pyproject.toml", '[project]\nname = "activation-fixture"\nversion = "0"\n')
    _write(dep_seed / "uv.lock", "version = 1\n")
    _git(dep_seed, "add", "pyproject.toml", "uv.lock")
    _git(dep_seed, "commit", "-m", "add dependency manifest")
    _git(dep_seed, "push", "origin", "main")
    latest_sha = _git(dep_seed, "rev-parse", "HEAD")
    assert latest_sha != new_sha

    uv_record = tmp_path / "uv-record.txt"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$PWD|$*" >> "$HAPAX_FAKE_UV_RECORD"\nexit 0\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_FAKE_UV_RECORD": str(uv_record),
        },
    )

    assert result.returncode == 0, result.stderr
    assert uv_record.read_text(encoding="utf-8").splitlines() == [
        f"{tmp_path / 'active-source'}|sync --all-extras --quiet"
    ]
    assert (tmp_path / "deploy-record.txt").read_text(encoding="utf-8").splitlines() == [latest_sha]
    receipt = _current_receipt(tmp_path)
    assert receipt["dependency_sync"]["status"] == "success"
