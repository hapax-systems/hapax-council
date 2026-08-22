import json
import os
import shlex
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

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


def _fake_tool_bin(tmp_path: Path, name: str, body: str) -> Path:
    fake_bin = tmp_path / f"fake-{name}-bin"
    fake_bin.mkdir(exist_ok=True)
    real_tool = shutil.which(name)
    assert real_tool is not None
    _write(
        fake_bin / name,
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            {body.rstrip()}
            exec {shlex.quote(real_tool)} "$@"
            """
        ),
        executable=True,
    )
    return fake_bin


def _bash_env_fail_nul_mapfile(tmp_path: Path, array_name: str, reason: str) -> Path:
    bash_env = tmp_path / f"fail-{array_name}-mapfile.bash"
    _write(
        bash_env,
        textwrap.dedent(
            f"""\
            mapfile() {{
                if [[ "$1" == "-d" && "$2" == "" && "$3" == "-t" && "$4" == {shlex.quote(array_name)} ]]; then
                    printf '%s\\n' {shlex.quote(f"forced {reason} read failure")} >&2
                    return 76
                fi
                builtin mapfile "$@"
            }}
            """
        ),
    )
    return bash_env


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
    _write(seed / "profiles" / ".gitkeep", "")
    _write(
        seed / "scripts" / "hapax-post-merge-deploy",
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            # Record the deploy TARGET (last positional arg) so assertions stay
            # stable whether invoked as `<sha>` or `--since <from> <to>`. The
            # full argv goes to HAPAX_FAKE_DEPLOY_ARGS_RECORD when requested, so
            # the cumulative-range test can assert the --since flag is passed.
            printf '%s\\n' "${@: -1}" >> "$HAPAX_FAKE_DEPLOY_RECORD"
            if [ -n "${HAPAX_FAKE_DEPLOY_ARGS_RECORD:-}" ]; then
                printf '%s\\n' "$*" >> "$HAPAX_FAKE_DEPLOY_ARGS_RECORD"
            fi
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


def _advance_origin(tmp_path: Path, origin: Path, message: str = "advance again") -> str:
    updater = tmp_path / f"updater-{message.replace(' ', '-')}"
    _git(tmp_path, "clone", str(origin), str(updater))
    _git(updater, "config", "user.email", "source-activate@example.test")
    _git(updater, "config", "user.name", "Source Activate")
    _write(updater / "README.md", f"base\n{message}\n")
    _git(updater, "add", "README.md")
    _git(updater, "commit", "-m", message)
    _git(updater, "push", "origin", "main")
    return _git(updater, "rev-parse", "HEAD")


def _run_activate(
    tmp_path: Path,
    canonical: Path,
    *,
    extra_args: list[str] | None = None,
    deploy_exit: int = 0,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["HAPAX_SOURCE_ACTIVATE_CANONICAL"] = str(canonical)
    env["HAPAX_SOURCE_ACTIVATE_WORKTREE"] = str(tmp_path / "active-source")
    env["HAPAX_SOURCE_ACTIVATE_STATE_DIR"] = str(tmp_path / "state")
    env["HAPAX_SOURCE_ACTIVATE_SYSTEMD_PROBES"] = "0"
    env["HAPAX_FAKE_DEPLOY_RECORD"] = str(tmp_path / "deploy-record.txt")
    env["HAPAX_FAKE_DEPLOY_EXIT"] = str(deploy_exit)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [str(SCRIPT), *(extra_args or [])],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _path_with_failing_launcher_cp(tmp_path: Path, *, phase: str) -> str:
    fake_bin = tmp_path / f"failing-cp-{phase}"
    fake_bin.mkdir()
    fake_cp = fake_bin / "cp"
    _write(
        fake_cp,
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            source_path="${{@: -2:1}}"
            dest_path="${{@: -1}}"
            if [[ "{phase}" == "snapshot" && "$dest_path" == *"/launcher-rollback."*"/present/"* ]]; then
                exit 73
            fi
            if [[ "{phase}" == "restore" && "$source_path" == *"/launcher-rollback."*"/present/hapax-post-merge-deploy" ]]; then
                exit 74
            fi
            exec /usr/bin/cp "$@"
            """
        ),
        executable=True,
    )
    return f"{fake_bin}:{os.environ['PATH']}"


def _path_with_failing_predeploy_command(
    tmp_path: Path,
    *,
    command: str,
    launcher_name: str = "",
) -> str:
    fake_bin = tmp_path / f"failing-predeploy-{command}"
    fake_bin.mkdir()
    fake_command = fake_bin / command
    if command == "ln":
        body = textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            destination="${{@: -1}}"
            if [[ "$destination" == */.local/bin/{launcher_name} ]]; then
                exit 75
            fi
            exec /usr/bin/ln "$@"
            """
        )
    elif command == "install":
        body = textwrap.dedent(
            """\
            #!/usr/bin/env bash
            destination="${@: -1}"
            if [[ "$destination" == */.config/hapax/.usb-topology-policy.json.activate.* ]]; then
                exit 76
            fi
            exec /usr/bin/install "$@"
            """
        )
    else:
        raise ValueError(f"unsupported predeploy failure command: {command}")
    _write(fake_command, body, executable=True)
    return f"{fake_bin}:{os.environ['PATH']}"


def _path_with_failing_config_restore_command(tmp_path: Path, *, command: str) -> str:
    fake_bin = tmp_path / f"failing-config-restore-{command}"
    fake_bin.mkdir()
    fake_command = fake_bin / command
    if command == "cp":
        body = textwrap.dedent(
            """\
            #!/usr/bin/env bash
            source_path="${@: -2:1}"
            if [[ "$source_path" == *"/launcher-rollback."*"/config-present" ]]; then
                exit 77
            fi
            exec /usr/bin/cp "$@"
            """
        )
    elif command == "mv":
        body = textwrap.dedent(
            """\
            #!/usr/bin/env bash
            source_path="${@: -2:1}"
            if [[ "$source_path" == *"/.usb-topology-policy.json.restore."* ]]; then
                exit 78
            fi
            exec /usr/bin/mv "$@"
            """
        )
    else:
        raise ValueError(f"unsupported config restore failure command: {command}")
    _write(fake_command, body, executable=True)
    return f"{fake_bin}:{os.environ['PATH']}"


def _current_receipt(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "state" / "current.json").read_text(encoding="utf-8"))


def _active_source_with_readme_drift(tmp_path: Path) -> tuple[Path, Path, str]:
    canonical, _origin, new_sha = _make_repos(tmp_path)
    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr
    active_source = tmp_path / "active-source"
    _write(active_source / "README.md", "tracked drift before refusal\n")
    return canonical, active_source, new_sha


def _candidate_with_head_mismatch(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    canonical, _origin, new_sha = _make_repos(tmp_path)
    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr
    active_source = tmp_path / "active-source"
    previous_target = active_source.resolve()
    previous_sha = _git(previous_target, "rev-parse", "HEAD~1")
    _git(previous_target, "checkout", "--detach", previous_sha)
    assert _git(previous_target, "rev-parse", "HEAD") != new_sha
    return canonical, active_source, previous_target, new_sha


def _assert_tracked_quarantine_failed(
    result: subprocess.CompletedProcess[str],
    tmp_path: Path,
    *,
    message: str,
    stderr_fragment: str,
) -> None:
    assert result.returncode == 2
    assert stderr_fragment in result.stderr
    assert "next action:" in result.stderr
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["exit_code"] == 2
    assert receipt["message"] == message
    assert receipt["source_hygiene"]["tracked_quarantine_count"] == 0
    assert receipt["source_hygiene"]["tracked_quarantine_status"] == "failed"


def _assert_untracked_quarantine_failed(
    result: subprocess.CompletedProcess[str],
    tmp_path: Path,
    *,
    message: str,
    stderr_fragment: str,
) -> None:
    assert result.returncode == 2
    assert stderr_fragment in result.stderr
    assert "next action:" in result.stderr
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["exit_code"] == 2
    assert receipt["message"] == message
    assert receipt["source_hygiene"]["untracked_quarantine_count"] == 0
    assert receipt["source_hygiene"]["untracked_quarantine_status"] == "failed"


def _seed_quarantine_root(quarantine_root: Path, name: str) -> Path:
    path = quarantine_root / name
    _write(path / "payload.txt", name)
    return path


def _extract_bash_function(name: str) -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    start = source.index(f"{name}() {{")
    end = source.index("\n}\n", start) + 3
    return source[start:end]


def test_quarantine_path_uses_unknown_when_origin_sha_is_unset(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    driver = tmp_path / "call-ensure-source-quarantine-path"
    _write(
        driver,
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            STATE_DIR={shlex.quote(str(state_dir))}
            source_quarantine_path=""
            origin_sha="unknown"
            {_extract_bash_function("ensure_source_quarantine_path")}
            ensure_source_quarantine_path
            printf '%s\\n' "$source_quarantine_path"
            """
        ),
        executable=True,
    )

    result = subprocess.run(
        ["bash", str(driver)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    quarantine_path = Path(result.stdout.strip())
    assert quarantine_path.is_dir()
    assert quarantine_path.parent == state_dir / "drift-quarantine"
    assert "-unknown." in quarantine_path.name


def test_activation_uses_clean_worktree_without_touching_dirty_canonical(tmp_path: Path) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)
    before_head = _git(canonical, "rev-parse", "HEAD")
    before_status = _git(canonical, "status", "--porcelain=v1")

    result = _run_activate(tmp_path, canonical)

    assert result.returncode == 0, result.stderr
    assert _git(canonical, "rev-parse", "HEAD") == before_head
    assert _git(canonical, "status", "--porcelain=v1") == before_status
    assert (tmp_path / "active-source").is_symlink()
    assert (tmp_path / "active-source").resolve() == tmp_path / "state" / "releases" / new_sha
    assert _git(tmp_path / "active-source", "rev-parse", "HEAD") == new_sha
    assert (tmp_path / "deploy-record.txt").read_text(encoding="utf-8").splitlines() == [new_sha]
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "completed"
    assert receipt["deploy_status"] == "success"
    assert receipt["origin_main_sha"] == new_sha
    assert receipt["active_source_head"] == new_sha
    assert receipt["active_source_target"] == str(tmp_path / "state" / "releases" / new_sha)
    assert receipt["candidate_source_path"] == str(tmp_path / "state" / "releases" / new_sha)
    assert receipt["canonical"]["dirty_count"] == 1
    assert receipt["health_probes"]["status"] == "success"
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


def test_audio_critical_active_drift_holds_before_reset_or_deploy(tmp_path: Path) -> None:
    canonical, origin, active_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr
    active_source = tmp_path / "active-source"
    _write(
        active_source / "config" / "voice-output-routes.yaml",
        "schema_version: 1\nroles:\n  private_monitor:\n    sink_name: hapax-private\n",
    )
    latest_sha = _advance_origin(tmp_path, origin, "advance after audio drift")
    assert latest_sha != active_sha

    second = _run_activate(tmp_path, canonical)

    assert second.returncode == 0, second.stderr
    assert "audio-critical drift" in second.stderr
    assert "config/voice-output-routes.yaml" in second.stderr
    assert _git(active_source, "rev-parse", "HEAD") == active_sha
    assert active_source.resolve() == tmp_path / "state" / "releases" / active_sha
    assert (active_source / "config" / "voice-output-routes.yaml").exists()
    assert (tmp_path / "deploy-record.txt").read_text(encoding="utf-8").splitlines() == [active_sha]
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "held"
    assert receipt["deploy_status"] == "skipped_audio_critical_drift"
    assert receipt["origin_main_sha"] == latest_sha
    assert receipt["active_source_head"] == active_sha
    assert "config/voice-output-routes.yaml" in receipt["message"]


def test_force_requires_governed_authority_for_audio_critical_drift(tmp_path: Path) -> None:
    canonical, origin, active_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr
    active_source = tmp_path / "active-source"
    _write(active_source / "config" / "voice-output-routes.yaml", "schema_version: 1\n")
    latest_sha = _advance_origin(tmp_path, origin, "advance before unaudited force")

    second = _run_activate(tmp_path, canonical, extra_args=["--force"])

    assert second.returncode == 2
    assert "--force requires governed release authority" in second.stderr
    assert _git(active_source, "rev-parse", "HEAD") == active_sha
    assert (tmp_path / "deploy-record.txt").read_text(encoding="utf-8").splitlines() == [active_sha]
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["origin_main_sha"] == latest_sha
    assert receipt["active_source_head"] == active_sha
    assert receipt["force"] == {"requested": True, "authority": None}


def test_force_authority_allows_governed_audio_drift_cutover(tmp_path: Path) -> None:
    canonical, origin, active_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr
    active_source = tmp_path / "active-source"
    _write(active_source / "config" / "voice-output-routes.yaml", "schema_version: 1\n")
    latest_sha = _advance_origin(tmp_path, origin, "advance before governed force")
    authority = "cc-task:audio-mk5-private-monitor-source-activation-unblock-20260605"

    second = _run_activate(tmp_path, canonical, extra_args=["--force-authority", authority])

    assert second.returncode == 0, second.stderr
    assert _git(active_source, "rev-parse", "HEAD") == latest_sha
    assert (tmp_path / "deploy-record.txt").read_text(encoding="utf-8").splitlines() == [
        active_sha,
        latest_sha,
    ]
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "completed"
    assert receipt["force"] == {"requested": True, "authority": authority}


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
    assert (tmp_path / "active-source").is_symlink()
    assert (tmp_path / "deploy-record.txt").read_text(encoding="utf-8").splitlines() == [new_sha]
    assert os.readlink(local_bin / "cc-claim") == str(
        tmp_path / "active-source" / "scripts" / "cc-claim"
    )
    assert os.readlink(local_bin / "cc-close") == str(
        tmp_path / "active-source" / "scripts" / "cc-close"
    )
    assert installed_policy.exists()
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "no_op"
    assert receipt["deploy_status"] == "skipped_already_active"
    assert receipt["source_hygiene"]["tracked_quarantine_count"] == 0
    assert receipt["source_hygiene"]["tracked_quarantine_path"] == ""
    assert receipt["source_hygiene"]["tracked_quarantine_status"] == "none"
    assert not (tmp_path / "state" / "drift-quarantine").exists()
    history = (tmp_path / "state" / "source-activation.jsonl").read_text(encoding="utf-8")
    assert '"status": "completed"' in history
    assert '"status": "no_op"' in history


def test_candidate_release_path_refuses_non_git_directory(tmp_path: Path) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)
    candidate_path = tmp_path / "state" / "releases" / new_sha
    _write(candidate_path / "stray.txt", "not a worktree\n")

    result = _run_activate(tmp_path, canonical)

    assert result.returncode == 2
    assert "candidate release path exists but is not a git worktree" in result.stderr
    assert not (tmp_path / "active-source").exists()
    assert not (tmp_path / "deploy-record.txt").exists()
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "candidate release path exists but is not a git worktree"
    assert receipt["candidate_source_path"] == str(candidate_path)


def test_activation_quarantines_tracked_drift_before_candidate_reset(tmp_path: Path) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    drift = active_source / "README.md"
    _write(drift, "tracked drift that reset would destroy\n")

    second = _run_activate(tmp_path, canonical)

    assert second.returncode == 0, second.stderr
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    payloads = list(
        (tmp_path / "state" / "drift-quarantine").glob("*/.hapax-tracked/worktree/README.md")
    )
    assert len(payloads) == 1
    assert payloads[0].read_text(encoding="utf-8") == ("tracked drift that reset would destroy\n")
    assert drift.read_text(encoding="utf-8") == "base\nnew origin main\n"
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "no_op"
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    assert hygiene["tracked_quarantine_status"] == "complete"
    quarantine_path = Path(hygiene["tracked_quarantine_path"])
    assert "drift-quarantine" in str(quarantine_path)
    assert payloads[0] == quarantine_path / "worktree" / "README.md"
    assert "recover tracked drift from worktree/ and index/ payloads" in second.stderr


def test_activation_rotates_dirty_candidate_without_reset_race(tmp_path: Path) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    previous_target = active_source.resolve()
    _write(active_source / "README.md", "tracked drift before candidate rotation\n")
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" && "$3" == "reset" && "$4" == "--hard" ]]; then
            printf 'late drift that reset would destroy\\n' > "$2/LATE.md"
            echo reset must not run for dirty reusable candidates >&2
            exit 60
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert second.returncode == 0, second.stderr
    assert active_source.resolve() == previous_target
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    assert (active_source / "README.md").read_text(encoding="utf-8") == ("base\nnew origin main\n")
    assert not (previous_target / "LATE.md").exists()
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    assert hygiene["tracked_quarantine_status"] == "complete"
    assert Path(receipt["candidate_source_path"]) == previous_target
    retired_target = Path(receipt["source_cutover"]["previous_active_target"])
    assert retired_target != previous_target
    assert (retired_target / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before candidate rotation\n"
    )

    third = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert third.returncode == 0, third.stderr
    assert active_source.resolve() == previous_target
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert receipt["status"] == "no_op"
    assert hygiene["tracked_quarantine_count"] == 0
    assert hygiene["tracked_quarantine_status"] == "none"


def test_clean_candidate_head_mismatch_uses_reset_path(tmp_path: Path) -> None:
    canonical, active_source, previous_target, new_sha = _candidate_with_head_mismatch(tmp_path)
    reset_record = tmp_path / "reset-record.txt"
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" \
            && "$3" == "reset" \
            && "$4" == "--hard" ]]; then
            if [[ "$2" == "$HAPAX_TEST_FORBIDDEN_RESET_TARGET" ]]; then
                echo reusable candidate path must not be reset in place >&2
                exit 60
            fi
            printf '%s\\n' "$*" >> "$HAPAX_TEST_RESET_RECORD"
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_TEST_FORBIDDEN_RESET_TARGET": str(previous_target),
            "HAPAX_TEST_RESET_RECORD": str(reset_record),
        },
    )

    assert second.returncode == 0, second.stderr
    assert "reset private candidate worktree" in second.stderr
    reset_record_text = reset_record.read_text(encoding="utf-8")
    assert "reset --hard" in reset_record_text
    assert str(previous_target) not in reset_record_text
    assert active_source.resolve() == previous_target
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    assert not (tmp_path / "state" / "drift-quarantine").exists()
    assert (tmp_path / "state" / "candidate-retirement").exists()
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 0
    assert hygiene["tracked_quarantine_status"] == "none"


def test_initial_candidate_head_command_failure_writes_receipt(tmp_path: Path) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)
    candidate = tmp_path / "state" / "releases" / new_sha
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" \
            && "$2" == "$HAPAX_TEST_CANDIDATE_TARGET" \
            && "$3" == "rev-parse" \
            && "$4" == "HEAD" ]]; then
            echo forced candidate head failure >&2
            exit 68
        fi
        """,
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_TEST_CANDIDATE_TARGET": str(candidate),
        },
    )

    assert result.returncode == 2
    assert "failed to read candidate source head" in result.stderr
    assert "next action:" in result.stderr
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "candidate source head check failed"
    assert receipt["candidate_source_path"] == str(candidate)
    assert receipt["source_hygiene"]["tracked_quarantine_count"] == 0


def test_late_tracked_drift_before_clean_reset_is_quarantined(
    tmp_path: Path,
) -> None:
    canonical, active_source, previous_target, new_sha = _candidate_with_head_mismatch(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" \
            && "$2" == "$HAPAX_TEST_RESET_TARGET" \
            && "$3" == "ls-files" \
            && "$4" == "--others" ]]; then
            if [[ -f "$HAPAX_TEST_LATE_DRIFT_MARKER" ]]; then
                exit 0
            fi
            touch "$HAPAX_TEST_LATE_DRIFT_MARKER"
            printf 'late drift before reset\\n' > "$2/README.md"
        fi
        if [[ "$1" == "-C" \
            && "$3" == "reset" \
            && "$4" == "--hard" ]]; then
            echo reset must not run after late tracked drift >&2
            exit 60
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_TEST_RESET_TARGET": str(previous_target),
            "HAPAX_TEST_LATE_DRIFT_MARKER": str(tmp_path / "late-drift-injected"),
        },
    )

    assert second.returncode == 0, second.stderr
    assert "quarantined 1 tracked activation files" in second.stderr
    assert "reset must not run after late tracked drift" not in second.stderr
    assert active_source.resolve() == previous_target
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    assert (active_source / "README.md").read_text(encoding="utf-8") == ("base\nnew origin main\n")
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    assert hygiene["tracked_quarantine_status"] == "complete"
    quarantine_path = Path(hygiene["tracked_quarantine_path"])
    assert (quarantine_path / "worktree" / "README.md").read_text(
        encoding="utf-8"
    ) == "late drift before reset\n"


def test_private_reset_target_tracked_drift_is_quarantined_before_reset(
    tmp_path: Path,
) -> None:
    canonical, active_source, previous_target, new_sha = _candidate_with_head_mismatch(tmp_path)
    real_git = shutil.which("git")
    assert real_git is not None
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" \
            && "$3" == "worktree" \
            && "$4" == "add" \
            && "$5" == "--detach" \
            && "$6" == *"/.reset-"* ]]; then
            if [[ "${GIT_CONFIG_KEY_0:-}" != "core.hooksPath" \
                || "${GIT_CONFIG_VALUE_0:-}" != "/dev/null" ]]; then
                echo private reset worktree add did not suppress hooks >&2
                exit 72
            fi
            "$HAPAX_TEST_REAL_GIT" "$@"
            rc=$?
            if [[ "$rc" == "0" ]]; then
                printf 'private reset target tracked drift\\n' > "$6/README.md"
            fi
            exit "$rc"
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_TEST_REAL_GIT": real_git,
        },
    )

    assert second.returncode == 0, second.stderr
    assert "quarantined 1 tracked activation files" in second.stderr
    assert active_source.resolve() == previous_target
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    assert (active_source / "README.md").read_text(encoding="utf-8") == ("base\nnew origin main\n")
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    assert hygiene["tracked_quarantine_status"] == "complete"
    quarantine_path = Path(hygiene["tracked_quarantine_path"])
    assert (quarantine_path / "worktree" / "README.md").read_text(
        encoding="utf-8"
    ) == "private reset target tracked drift\n"


def test_private_reset_target_untracked_drift_is_quarantined_before_reset(
    tmp_path: Path,
) -> None:
    canonical, active_source, previous_target, new_sha = _candidate_with_head_mismatch(tmp_path)
    real_git = shutil.which("git")
    assert real_git is not None
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" \
            && "$3" == "worktree" \
            && "$4" == "add" \
            && "$5" == "--detach" \
            && "$6" == *"/.reset-"* ]]; then
            if [[ "${GIT_CONFIG_KEY_0:-}" != "core.hooksPath" \
                || "${GIT_CONFIG_VALUE_0:-}" != "/dev/null" ]]; then
                echo private reset worktree add did not suppress hooks >&2
                exit 72
            fi
            "$HAPAX_TEST_REAL_GIT" "$@"
            rc=$?
            if [[ "$rc" == "0" ]]; then
                mkdir -p "$6/notes"
                printf 'private reset target untracked drift\\n' > "$6/notes/post-add.txt"
            fi
            exit "$rc"
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_TEST_REAL_GIT": real_git,
        },
    )

    assert second.returncode == 0, second.stderr
    assert active_source.resolve() == previous_target
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    assert not (active_source / "notes" / "post-add.txt").exists()
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 0
    assert hygiene["tracked_quarantine_status"] == "none"
    assert hygiene["untracked_quarantine_count"] == 1
    assert hygiene["untracked_quarantine_status"] == "complete"
    quarantine_path = Path(hygiene["untracked_quarantine_path"])
    assert (quarantine_path / "notes" / "post-add.txt").read_text(
        encoding="utf-8"
    ) == "private reset target untracked drift\n"


def test_private_reset_untracked_sweeps_namespace_same_relative_paths(
    tmp_path: Path,
) -> None:
    canonical, active_source, previous_target, new_sha = _candidate_with_head_mismatch(tmp_path)
    _write(active_source / "notes" / "collision.txt", "old candidate untracked drift\n")
    real_git = shutil.which("git")
    assert real_git is not None
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" \
            && "$3" == "worktree" \
            && "$4" == "add" \
            && "$5" == "--detach" \
            && "$6" == *"/.reset-"* ]]; then
            "$HAPAX_TEST_REAL_GIT" "$@"
            rc=$?
            if [[ "$rc" == "0" ]]; then
                mkdir -p "$6/notes"
                printf 'private reset post-add untracked drift\\n' > "$6/notes/collision.txt"
            fi
            exit "$rc"
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_TEST_REAL_GIT": real_git,
        },
    )

    assert second.returncode == 0, second.stderr
    assert active_source.resolve() == previous_target
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    assert not (active_source / "notes" / "collision.txt").exists()
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["untracked_quarantine_count"] == 2
    assert hygiene["untracked_quarantine_status"] == "complete"
    quarantine_root = Path(hygiene["untracked_quarantine_path"])
    assert (quarantine_root / ".hapax-untracked" / "notes" / "collision.txt").read_text(
        encoding="utf-8"
    ) == "old candidate untracked drift\n"
    assert (
        quarantine_root / ".hapax-untracked-sweeps" / "1" / "notes" / "collision.txt"
    ).read_text(encoding="utf-8") == "private reset post-add untracked drift\n"


def test_private_reset_untracked_scan_failure_refuses_before_reset(
    tmp_path: Path,
) -> None:
    canonical, active_source, previous_target, _new_sha = _candidate_with_head_mismatch(tmp_path)
    real_git = shutil.which("git")
    assert real_git is not None
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" \
            && "$3" == "worktree" \
            && "$4" == "add" \
            && "$5" == "--detach" \
            && "$6" == *"/.reset-"* ]]; then
            "$HAPAX_TEST_REAL_GIT" "$@"
            rc=$?
            if [[ "$rc" == "0" ]]; then
                mkdir -p "$6/notes"
                printf 'private reset untracked scan failure payload\\n' > "$6/notes/post-add.txt"
            fi
            exit "$rc"
        fi
        if [[ "$1" == "-C" \
            && "$2" == *"/.reset-"* \
            && "$3" == "ls-files" \
            && "$4" == "--others" ]]; then
            echo forced private reset untracked scan failure >&2
            exit 73
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_TEST_REAL_GIT": real_git,
        },
    )

    assert second.returncode == 2
    assert "untracked drift scan failed" in second.stderr
    assert "next action:" in second.stderr
    assert active_source.resolve() == previous_target
    reset_worktrees = list((tmp_path / "state" / "releases").glob(".reset-*"))
    assert len(reset_worktrees) == 1
    assert (reset_worktrees[0] / "notes" / "post-add.txt").read_text(
        encoding="utf-8"
    ) == "private reset untracked scan failure payload\n"
    _assert_untracked_quarantine_failed(
        second,
        tmp_path,
        message="untracked drift scan failed before sweep",
        stderr_fragment="untracked drift scan failed for",
    )


def test_clean_candidate_post_reset_head_command_failure_writes_receipt(
    tmp_path: Path,
) -> None:
    canonical, active_source, previous_target, _new_sha = _candidate_with_head_mismatch(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" \
            && "$2" == *"/.reset-"* \
            && "$3" == "rev-parse" \
            && "$4" == "HEAD" ]]; then
            echo forced post-reset head failure >&2
            exit 68
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
    )

    assert second.returncode == 2
    assert "failed to read candidate source head after reset" in second.stderr
    assert "next action:" in second.stderr
    assert active_source.resolve() == previous_target
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "candidate source head check failed after reset"
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 0
    assert hygiene["tracked_quarantine_status"] == "none"


def test_clean_candidate_post_reset_head_mismatch_writes_receipt(
    tmp_path: Path,
) -> None:
    canonical, active_source, previous_target, _new_sha = _candidate_with_head_mismatch(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" \
            && "$2" == *"/.reset-"* \
            && "$3" == "rev-parse" \
            && "$4" == "HEAD" ]]; then
            echo 0000000000000000000000000000000000000000
            exit 0
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
    )

    assert second.returncode == 2
    assert "after reset" in second.stderr
    assert "next action:" in second.stderr
    assert active_source.resolve() == previous_target
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "candidate source head does not match origin/main after reset"
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 0
    assert hygiene["tracked_quarantine_status"] == "none"


def test_dirty_candidate_rotation_respects_live_window(tmp_path: Path) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    previous_target = active_source.resolve()
    _write(active_source / "README.md", "tracked drift during live window\n")
    live_flag = tmp_path / "livestream-active"
    _write(live_flag, "on\n")

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"HAPAX_SOURCE_ACTIVATE_LIVE_FLAG": str(live_flag)},
    )

    assert second.returncode == 0, second.stderr
    assert "unsafe live window is active" in second.stderr
    assert active_source.resolve() == previous_target
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift during live window\n"
    )
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "held"
    assert receipt["deploy_status"] == "skipped_live_window"
    assert receipt["candidate_source_path"] == str(previous_target)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 0
    assert hygiene["tracked_quarantine_status"] == "none"
    assert not (tmp_path / "state" / "drift-quarantine").exists()

    third = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"HAPAX_SOURCE_ACTIVATE_LIVE_FLAG": str(live_flag)},
    )

    assert third.returncode == 0, third.stderr
    assert active_source.resolve() == previous_target
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift during live window\n"
    )
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "held"
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 0
    assert hygiene["tracked_quarantine_status"] == "none"
    assert not (tmp_path / "state" / "drift-quarantine").exists()


def test_dirty_candidate_replacement_failure_writes_receipt(tmp_path: Path) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    previous_target = active_source.resolve()
    _write(active_source / "README.md", "tracked drift before add failure\n")
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" \
            && "$3" == "worktree" \
            && "$4" == "add" \
            && "$5" == "--detach" \
            && "$6" == "$HAPAX_TEST_REPLACEMENT_TARGET" ]]; then
            echo forced replacement worktree add failure >&2
            exit 61
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_TEST_REPLACEMENT_TARGET": str(previous_target),
        },
    )

    assert second.returncode == 2
    assert "failed to create fresh candidate worktree" in second.stderr
    assert "retired candidate remains" in second.stderr
    assert "next action:" in second.stderr
    assert active_source.resolve() != previous_target
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before add failure\n"
    )
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "candidate replacement worktree creation failed"
    assert receipt["active_source_target"] == str(active_source.resolve())
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    assert hygiene["tracked_quarantine_status"] == "complete"


def test_dirty_candidate_replacement_hook_drift_fails_before_promotion(
    tmp_path: Path,
) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr
    deploy_record = tmp_path / "deploy-record.txt"
    deploy_record_before = deploy_record.read_text(encoding="utf-8")

    active_source = tmp_path / "active-source"
    previous_target = active_source.resolve()
    _write(active_source / "README.md", "tracked drift before replacement hook drift\n")
    real_git = shutil.which("git")
    assert real_git is not None
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" \
            && "$3" == "worktree" \
            && "$4" == "add" \
            && "$5" == "--detach" \
            && "$6" == "$HAPAX_TEST_REPLACEMENT_TARGET" ]]; then
            if [[ "${GIT_CONFIG_KEY_0:-}" != "core.hooksPath" \
                || "${GIT_CONFIG_VALUE_0:-}" != "/dev/null" ]]; then
                echo replacement worktree add did not suppress hooks >&2
                exit 72
            fi
            "$HAPAX_TEST_REAL_GIT" "$@"
            rc=$?
            if [[ "$rc" == "0" ]]; then
                printf 'replacement hook tracked drift\\n' > "$6/README.md"
            fi
            exit "$rc"
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_TEST_REAL_GIT": real_git,
            "HAPAX_TEST_REPLACEMENT_TARGET": str(previous_target),
        },
    )

    assert second.returncode == 2
    assert "replacement candidate has tracked drift after creation" in second.stderr
    assert "next action:" in second.stderr
    assert active_source.resolve() != previous_target
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before replacement hook drift\n"
    )
    assert previous_target.exists()
    assert (previous_target / "README.md").read_text(encoding="utf-8") == (
        "replacement hook tracked drift\n"
    )
    assert deploy_record.read_text(encoding="utf-8") == deploy_record_before
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "replacement candidate tracked drift detected after creation"
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    assert hygiene["tracked_quarantine_status"] == "complete"


def test_dirty_candidate_replacement_untracked_drift_is_quarantined_before_promotion(
    tmp_path: Path,
) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    previous_target = active_source.resolve()
    _write(active_source / "README.md", "tracked drift before replacement untracked drift\n")
    real_git = shutil.which("git")
    assert real_git is not None
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" \
            && "$3" == "worktree" \
            && "$4" == "add" \
            && "$5" == "--detach" \
            && "$6" == "$HAPAX_TEST_REPLACEMENT_TARGET" ]]; then
            if [[ "${GIT_CONFIG_KEY_0:-}" != "core.hooksPath" \
                || "${GIT_CONFIG_VALUE_0:-}" != "/dev/null" ]]; then
                echo replacement worktree add did not suppress hooks >&2
                exit 72
            fi
            "$HAPAX_TEST_REAL_GIT" "$@"
            rc=$?
            if [[ "$rc" == "0" ]]; then
                mkdir -p "$6/notes"
                printf 'replacement candidate untracked drift\\n' > "$6/notes/post-add.txt"
            fi
            exit "$rc"
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_TEST_REAL_GIT": real_git,
            "HAPAX_TEST_REPLACEMENT_TARGET": str(previous_target),
        },
    )

    assert second.returncode == 0, second.stderr
    assert active_source.resolve() == previous_target
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    assert not (previous_target / "notes" / "post-add.txt").exists()
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "no_op"
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    assert hygiene["tracked_quarantine_status"] == "complete"
    assert hygiene["untracked_quarantine_count"] == 1
    assert hygiene["untracked_quarantine_status"] == "complete"
    quarantine_path = Path(hygiene["untracked_quarantine_path"])
    assert (quarantine_path / "notes" / "post-add.txt").read_text(
        encoding="utf-8"
    ) == "replacement candidate untracked drift\n"


def test_dirty_candidate_replacement_untracked_sweeps_namespace_same_relative_paths(
    tmp_path: Path,
) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    previous_target = active_source.resolve()
    _write(active_source / "README.md", "tracked drift before replacement collision\n")
    _write(active_source / "notes" / "collision.txt", "old replacement untracked drift\n")
    real_git = shutil.which("git")
    assert real_git is not None
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" \
            && "$3" == "worktree" \
            && "$4" == "add" \
            && "$5" == "--detach" \
            && "$6" == "$HAPAX_TEST_REPLACEMENT_TARGET" ]]; then
            "$HAPAX_TEST_REAL_GIT" "$@"
            rc=$?
            if [[ "$rc" == "0" ]]; then
                mkdir -p "$6/notes"
                printf 'fresh replacement untracked drift\\n' > "$6/notes/collision.txt"
            fi
            exit "$rc"
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_TEST_REAL_GIT": real_git,
            "HAPAX_TEST_REPLACEMENT_TARGET": str(previous_target),
        },
    )

    assert second.returncode == 0, second.stderr
    assert active_source.resolve() == previous_target
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    assert not (previous_target / "notes" / "collision.txt").exists()
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    assert hygiene["tracked_quarantine_status"] == "complete"
    assert hygiene["untracked_quarantine_count"] == 2
    assert hygiene["untracked_quarantine_status"] == "complete"
    quarantine_root = Path(hygiene["untracked_quarantine_path"])
    assert (quarantine_root / ".hapax-untracked" / "notes" / "collision.txt").read_text(
        encoding="utf-8"
    ) == "old replacement untracked drift\n"
    assert (
        quarantine_root / ".hapax-untracked-sweeps" / "1" / "notes" / "collision.txt"
    ).read_text(encoding="utf-8") == "fresh replacement untracked drift\n"


def test_dirty_candidate_replacement_untracked_scan_failure_refuses_before_promotion(
    tmp_path: Path,
) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    previous_target = active_source.resolve()
    _write(active_source / "README.md", "tracked drift before replacement scan failure\n")
    real_git = shutil.which("git")
    assert real_git is not None
    scan_fail_marker = tmp_path / "replacement-worktree-added"
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" \
            && "$3" == "worktree" \
            && "$4" == "add" \
            && "$5" == "--detach" \
            && "$6" == "$HAPAX_TEST_REPLACEMENT_TARGET" ]]; then
            "$HAPAX_TEST_REAL_GIT" "$@"
            rc=$?
            if [[ "$rc" == "0" ]]; then
                touch "$HAPAX_TEST_REPLACEMENT_SCAN_FAIL_MARKER"
                mkdir -p "$6/notes"
                printf 'replacement untracked scan failure payload\\n' > "$6/notes/post-add.txt"
            fi
            exit "$rc"
        fi
        if [[ "$1" == "-C" \
            && "$2" == "$HAPAX_TEST_REPLACEMENT_TARGET" \
            && "$3" == "ls-files" \
            && "$4" == "--others" \
            && -f "$HAPAX_TEST_REPLACEMENT_SCAN_FAIL_MARKER" ]]; then
            echo forced replacement untracked scan failure >&2
            exit 74
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_TEST_REAL_GIT": real_git,
            "HAPAX_TEST_REPLACEMENT_TARGET": str(previous_target),
            "HAPAX_TEST_REPLACEMENT_SCAN_FAIL_MARKER": str(scan_fail_marker),
        },
    )

    assert second.returncode == 2
    assert "untracked drift scan failed" in second.stderr
    assert "next action:" in second.stderr
    assert active_source.resolve() != previous_target
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before replacement scan failure\n"
    )
    assert (previous_target / "notes" / "post-add.txt").read_text(
        encoding="utf-8"
    ) == "replacement untracked scan failure payload\n"
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    assert hygiene["tracked_quarantine_status"] == "complete"
    assert hygiene["untracked_quarantine_count"] == 0
    assert hygiene["untracked_quarantine_status"] == "failed"
    assert receipt["message"] == "untracked drift scan failed before sweep"


def test_clean_candidate_reset_failure_writes_receipt(tmp_path: Path) -> None:
    canonical, active_source, previous_target, _new_sha = _candidate_with_head_mismatch(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" \
            && "$3" == "reset" \
            && "$4" == "--hard" ]]; then
            echo forced reset failure >&2
            exit 63
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
    )

    assert second.returncode == 2
    assert "failed to reset private candidate worktree" in second.stderr
    assert "next action:" in second.stderr
    assert active_source.resolve() == previous_target
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "candidate source reset failed after clean drift scan"
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 0
    assert hygiene["tracked_quarantine_status"] == "none"


def test_clean_candidate_reset_worktree_allocation_failure_writes_receipt(
    tmp_path: Path,
) -> None:
    canonical, active_source, previous_target, _new_sha = _candidate_with_head_mismatch(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "mktemp",
        """
        if [[ "$1" == "-d" && "$2" == *"/.reset-"* ]]; then
            echo forced reset worktree allocation failure >&2
            exit 66
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert second.returncode == 2
    assert "failed to allocate private reset worktree" in second.stderr
    assert "next action:" in second.stderr
    assert active_source.resolve() == previous_target
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "candidate reset worktree allocation failed"
    assert receipt["source_hygiene"]["tracked_quarantine_count"] == 0


def test_clean_candidate_reset_worktree_path_prepare_failure_writes_receipt(
    tmp_path: Path,
) -> None:
    canonical, active_source, previous_target, _new_sha = _candidate_with_head_mismatch(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "rmdir",
        """
        if [[ "$1" == *"/.reset-"* ]]; then
            echo forced reset worktree path prepare failure >&2
            exit 67
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert second.returncode == 2
    assert "failed to prepare private reset worktree path" in second.stderr
    assert "next action:" in second.stderr
    assert active_source.resolve() == previous_target
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "candidate reset worktree allocation failed"
    assert receipt["source_hygiene"]["tracked_quarantine_count"] == 0


def test_clean_candidate_reset_worktree_add_failure_writes_receipt(
    tmp_path: Path,
) -> None:
    canonical, active_source, previous_target, _new_sha = _candidate_with_head_mismatch(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" \
            && "$3" == "worktree" \
            && "$4" == "add" \
            && "$5" == "--detach" \
            && "$6" == *"/.reset-"* ]]; then
            echo forced private reset worktree add failure >&2
            exit 68
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert second.returncode == 2
    assert "failed to create private reset worktree" in second.stderr
    assert "next action:" in second.stderr
    assert active_source.resolve() == previous_target
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "candidate reset worktree creation failed"
    assert receipt["source_hygiene"]["tracked_quarantine_count"] == 0


def test_clean_candidate_reset_retirement_date_failure_writes_receipt(
    tmp_path: Path,
) -> None:
    canonical, active_source, previous_target, _new_sha = _candidate_with_head_mismatch(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "date",
        """
        if [[ "$1" == "-u" ]]; then
            echo forced retirement timestamp failure >&2
            exit 70
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert second.returncode == 2
    assert "failed to create clean candidate retirement root" in second.stderr
    assert "next action:" in second.stderr
    assert active_source.resolve() == previous_target
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "candidate clean retirement setup failed"
    assert receipt["source_hygiene"]["tracked_quarantine_count"] == 0


def test_clean_candidate_reset_retirement_root_failure_writes_receipt(
    tmp_path: Path,
) -> None:
    canonical, active_source, previous_target, _new_sha = _candidate_with_head_mismatch(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "mkdir",
        """
        for arg in "$@"; do
            if [[ "$arg" == *"/candidate-retirement" ]]; then
                echo forced retirement root failure >&2
                exit 71
            fi
        done
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert second.returncode == 2
    assert "failed to create clean candidate retirement root" in second.stderr
    assert "next action:" in second.stderr
    assert active_source.resolve() == previous_target
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "candidate clean retirement setup failed"
    assert receipt["source_hygiene"]["tracked_quarantine_count"] == 0


def test_clean_candidate_reset_retirement_allocation_failure_writes_receipt(
    tmp_path: Path,
) -> None:
    canonical, active_source, previous_target, _new_sha = _candidate_with_head_mismatch(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "mktemp",
        """
        if [[ "$1" == "-d" && "$2" == *"/candidate-retirement/"* ]]; then
            echo forced retirement allocation failure >&2
            exit 72
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert second.returncode == 2
    assert "failed to create clean candidate retirement root" in second.stderr
    assert "next action:" in second.stderr
    assert active_source.resolve() == previous_target
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "candidate clean retirement setup failed"
    assert receipt["source_hygiene"]["tracked_quarantine_count"] == 0


def test_clean_candidate_reset_retirement_move_failure_writes_receipt(
    tmp_path: Path,
) -> None:
    canonical, active_source, previous_target, _new_sha = _candidate_with_head_mismatch(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" \
            && "$3" == "worktree" \
            && "$4" == "move" \
            && "$5" == "$HAPAX_TEST_REPLACEMENT_TARGET" ]]; then
            echo forced reset-path retirement move failure >&2
            exit 69
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_TEST_REPLACEMENT_TARGET": str(previous_target),
        },
    )

    assert second.returncode == 2
    assert "failed to retire reusable candidate" in second.stderr
    assert "next action:" in second.stderr
    assert active_source.resolve() == previous_target
    assert previous_target.exists()
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "candidate retirement failed"
    assert receipt["source_hygiene"]["tracked_quarantine_count"] == 0


def test_clean_candidate_reset_active_retarget_failure_writes_receipt(
    tmp_path: Path,
) -> None:
    canonical, active_source, previous_target, _new_sha = _candidate_with_head_mismatch(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "ln",
        """
        if [[ "$1" == "-s" && "$2" == *"/.hapax-retired-candidate" ]]; then
            echo forced reset-path active retarget failure >&2
            exit 70
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert second.returncode == 2
    assert "failed to retarget active source to retired candidate" in second.stderr
    assert "next action:" in second.stderr
    assert active_source.resolve() == previous_target
    assert previous_target.exists()
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "active source retired-candidate retarget failed"
    assert receipt["source_cutover"]["rollback_status"] == "restored_worktree"
    assert receipt["source_hygiene"]["tracked_quarantine_count"] == 0


def test_clean_candidate_reset_final_placement_failure_writes_receipt(
    tmp_path: Path,
) -> None:
    canonical, active_source, previous_target, _new_sha = _candidate_with_head_mismatch(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" \
            && "$3" == "worktree" \
            && "$4" == "move" \
            && "$5" == *"/.reset-"* ]]; then
            echo forced reset worktree final placement failure >&2
            exit 71
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert second.returncode == 2
    assert "failed to move private reset worktree" in second.stderr
    assert "retired candidate remains" in second.stderr
    assert "next action:" in second.stderr
    assert active_source.resolve() != previous_target
    assert not previous_target.exists()
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "candidate reset worktree placement failed"
    assert receipt["source_hygiene"]["tracked_quarantine_count"] == 0


def test_dirty_candidate_worktree_move_failure_writes_receipt(tmp_path: Path) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    previous_target = active_source.resolve()
    _write(active_source / "README.md", "tracked drift before move failure\n")
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" \
            && "$3" == "worktree" \
            && "$4" == "move" \
            && "$5" == "$HAPAX_TEST_REPLACEMENT_TARGET" ]]; then
            echo forced candidate worktree move failure >&2
            exit 64
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_TEST_REPLACEMENT_TARGET": str(previous_target),
        },
    )

    assert second.returncode == 2
    assert "failed to retire reusable candidate" in second.stderr
    assert "next action:" in second.stderr
    assert active_source.resolve() == previous_target
    assert previous_target.exists()
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "candidate retirement failed"
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    assert hygiene["tracked_quarantine_status"] == "complete"


def test_candidate_retirement_setup_failure_after_disappearing_drift_writes_receipt(
    tmp_path: Path,
) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    previous_target = active_source.resolve()
    scan_count = tmp_path / "tracked-scan-count.txt"
    fake_git = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" \
            && "$2" == "$HAPAX_TEST_REPLACEMENT_TARGET" \
            && "$3" == "ls-files" \
            && "$4" == "-z" \
            && "$5" == "--modified" \
            && "$6" == "--deleted" ]]; then
            count=0
            if [[ -f "$HAPAX_TEST_SCAN_COUNT" ]]; then
                count="$(cat "$HAPAX_TEST_SCAN_COUNT")"
            fi
            printf '%s\\n' "$((count + 1))" > "$HAPAX_TEST_SCAN_COUNT"
            if [[ "$count" == "0" ]]; then
                printf 'README.md\\0'
                exit 0
            fi
        fi
        """,
    )
    fake_date = _fake_tool_bin(
        tmp_path,
        "date",
        """
        if [[ "$1" == "-u" && "$2" == "+%Y%m%dT%H%M%SZ" ]]; then
            echo forced retirement date failure >&2
            exit 63
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_git}:{fake_date}:{os.environ['PATH']}",
            "HAPAX_TEST_REPLACEMENT_TARGET": str(previous_target),
            "HAPAX_TEST_SCAN_COUNT": str(scan_count),
        },
    )

    assert second.returncode == 2
    assert "failed to create candidate retirement quarantine root" in second.stderr
    assert "next action:" in second.stderr
    assert active_source.resolve() == previous_target
    assert previous_target.exists()
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "candidate retirement quarantine setup failed"
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 0
    assert hygiene["tracked_quarantine_status"] == "none"


def test_dirty_candidate_active_retarget_failure_writes_receipt(tmp_path: Path) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    previous_target = active_source.resolve()
    _write(active_source / "README.md", "tracked drift before retarget failure\n")
    _write(active_source / "LOCAL.txt", "untracked payload before retarget failure\n")
    fake_bin = _fake_tool_bin(
        tmp_path,
        "ln",
        """
        if [[ "$1" == "-s" && "$2" == *"/.hapax-retired-candidate" ]]; then
            echo forced active retarget failure >&2
            exit 62
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert second.returncode == 2
    assert "failed to retarget active source to retired candidate" in second.stderr
    assert "restored active source target to previous candidate" in second.stderr
    assert "untracked payloads remain quarantined" in second.stderr
    assert "next action:" in second.stderr
    assert active_source.is_symlink()
    assert active_source.resolve() == previous_target
    assert previous_target.exists()
    assert _git(active_source, "rev-parse", "HEAD")
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before retarget failure\n"
    )
    assert not (active_source / "LOCAL.txt").exists()
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "active source retired-candidate retarget failed"
    assert receipt["active_source_target"] == str(previous_target)
    assert receipt["source_cutover"]["rollback_status"] == "restored_worktree"
    assert "untracked payloads remain quarantined" in receipt["source_cutover"]["rollback_message"]
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    assert hygiene["tracked_quarantine_status"] == "complete"
    assert hygiene["untracked_quarantine_count"] == 1
    assert hygiene["untracked_quarantine_status"] == "complete"
    assert (
        Path(hygiene["untracked_quarantine_path"], "LOCAL.txt").read_text(encoding="utf-8")
        == "untracked payload before retarget failure\n"
    )


def test_dirty_candidate_active_retarget_rollback_retarget_failure_writes_receipt(
    tmp_path: Path,
) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    previous_target = active_source.resolve()
    _write(active_source / "README.md", "tracked drift before rollback retarget failure\n")
    fake_bin = _fake_tool_bin(
        tmp_path,
        "ln",
        """
        if [[ "$1" == "-s" && "$2" == *"/.hapax-retired-candidate" ]]; then
            echo forced active retarget failure >&2
            exit 62
        fi
        if [[ "$1" == "-s" && "$2" == "$HAPAX_TEST_REPLACEMENT_TARGET" ]]; then
            echo forced rollback retarget failure >&2
            exit 66
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_TEST_REPLACEMENT_TARGET": str(previous_target),
        },
    )

    assert second.returncode == 2
    assert "active source retarget rollback failed" in second.stderr
    assert "moved retired candidate back but failed to retarget" in second.stderr
    assert "next action:" in second.stderr
    assert active_source.is_symlink()
    assert active_source.resolve() == previous_target
    assert previous_target.exists()
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "active source retired-candidate retarget failed"
    assert receipt["source_cutover"]["rollback_status"] == "failed"
    assert (
        "moved retired candidate back but failed to retarget"
        in receipt["source_cutover"]["rollback_message"]
    )
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    assert hygiene["tracked_quarantine_status"] == "complete"


def test_dirty_candidate_active_retarget_rollback_move_failure_writes_receipt(
    tmp_path: Path,
) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    previous_target = active_source.resolve()
    _write(active_source / "README.md", "tracked drift before rollback move failure\n")
    fake_ln = _fake_tool_bin(
        tmp_path,
        "ln",
        """
        if [[ "$1" == "-s" && "$2" == *"/.hapax-retired-candidate" ]]; then
            echo forced active retarget failure >&2
            exit 62
        fi
        """,
    )
    fake_git = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" \
            && "$3" == "worktree" \
            && "$4" == "move" \
            && "$5" == *"/.hapax-retired-candidate" ]]; then
            echo forced rollback worktree move failure >&2
            exit 67
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_ln}:{fake_git}:{os.environ['PATH']}"},
    )

    assert second.returncode == 2
    assert "active source retarget rollback failed" in second.stderr
    assert "failed to move retired candidate back" in second.stderr
    assert "next action:" in second.stderr
    assert active_source.is_symlink()
    assert not previous_target.exists()
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "active source retired-candidate retarget failed"
    assert receipt["source_cutover"]["rollback_status"] == "failed"
    assert "failed to move retired candidate back" in receipt["source_cutover"]["rollback_message"]
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    assert hygiene["tracked_quarantine_status"] == "complete"


def test_replacement_candidate_head_mismatch_writes_receipt(tmp_path: Path) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    previous_target = active_source.resolve()
    _write(active_source / "README.md", "tracked drift before replacement head mismatch\n")
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" \
            && "$2" == "$HAPAX_TEST_REPLACEMENT_TARGET" \
            && "$3" == "rev-parse" \
            && "$4" == "HEAD" ]]; then
            echo 0000000000000000000000000000000000000000
            exit 0
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_TEST_REPLACEMENT_TARGET": str(previous_target),
        },
    )

    assert second.returncode == 2
    assert "replacement candidate source" in second.stderr
    assert "next action:" in second.stderr
    assert active_source.is_symlink()
    assert active_source.resolve() != previous_target
    assert previous_target.exists()
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before replacement head mismatch\n"
    )
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "replacement candidate source head does not match origin/main"
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    assert hygiene["tracked_quarantine_status"] == "complete"


def test_replacement_candidate_head_command_failure_writes_receipt(
    tmp_path: Path,
) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    previous_target = active_source.resolve()
    _write(active_source / "README.md", "tracked drift before replacement head failure\n")
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "$1" == "-C" \
            && "$2" == "$HAPAX_TEST_REPLACEMENT_TARGET" \
            && "$3" == "rev-parse" \
            && "$4" == "HEAD" ]]; then
            echo forced replacement head failure >&2
            exit 65
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_TEST_REPLACEMENT_TARGET": str(previous_target),
        },
    )

    assert second.returncode == 2
    assert "failed to read replacement candidate source head" in second.stderr
    assert "next action:" in second.stderr
    assert active_source.is_symlink()
    assert active_source.resolve() != previous_target
    assert previous_target.exists()
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before replacement head failure\n"
    )
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "replacement candidate source head check failed"
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    assert hygiene["tracked_quarantine_status"] == "complete"


def test_activation_quarantines_tracked_deletion_before_candidate_reset(tmp_path: Path) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    drift = active_source / "README.md"
    drift.unlink()

    second = _run_activate(tmp_path, canonical)

    assert second.returncode == 0, second.stderr
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    assert drift.read_text(encoding="utf-8") == "base\nnew origin main\n"
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "no_op"
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    quarantine_path = Path(hygiene["tracked_quarantine_path"])
    assert (quarantine_path / "deleted" / "README.md").read_text(
        encoding="utf-8"
    ) == "deleted tracked path: README.md\n"


def test_activation_quarantines_executable_mode_drift_before_candidate_reset(
    tmp_path: Path,
) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    drift = active_source / "README.md"
    _git(active_source, "config", "core.filemode", "true")
    drift.chmod(drift.stat().st_mode | 0o111)
    assert "README.md" in _git(active_source, "ls-files", "--modified")

    second = _run_activate(tmp_path, canonical)

    assert second.returncode == 0, second.stderr
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    quarantine_path = Path(hygiene["tracked_quarantine_path"])
    quarantined = quarantine_path / "worktree" / "README.md"
    assert quarantined.stat().st_mode & 0o111
    assert not drift.stat().st_mode & 0o111


def test_activation_quarantines_staged_tracked_drift_before_candidate_reset(
    tmp_path: Path,
) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    drift = active_source / "README.md"
    _write(drift, "staged drift that ls-files modified misses\n")
    _git(active_source, "add", "README.md")
    assert _git(active_source, "ls-files", "--modified", "--deleted") == ""
    assert _git(active_source, "diff", "--cached", "--name-only") == "README.md"

    second = _run_activate(tmp_path, canonical)

    assert second.returncode == 0, second.stderr
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    assert drift.read_text(encoding="utf-8") == "base\nnew origin main\n"
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    quarantine_path = Path(hygiene["tracked_quarantine_path"])
    assert (quarantine_path / "index" / "README.md").read_text(
        encoding="utf-8"
    ) == "staged drift that ls-files modified misses\n"


def test_activation_quarantines_staged_path_containing_tab_before_candidate_reset(
    tmp_path: Path,
) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    rel = Path("notes") / "tab\tpath.txt"
    _write(active_source / rel, "staged tab path drift\n")
    _git(active_source, "add", str(rel))

    second = _run_activate(tmp_path, canonical)

    assert second.returncode == 0, second.stderr
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    assert hygiene["tracked_quarantine_status"] == "complete"
    quarantine_path = Path(hygiene["tracked_quarantine_path"])
    assert (quarantine_path / "index" / rel).read_text(encoding="utf-8") == (
        "staged tab path drift\n"
    )


def test_activation_quarantines_staged_symlink_before_candidate_reset(
    tmp_path: Path,
) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    rel = Path("config") / "readme-link"
    (active_source / rel).symlink_to("../README.md")
    _git(active_source, "add", str(rel))

    second = _run_activate(tmp_path, canonical)

    assert second.returncode == 0, second.stderr
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    assert hygiene["tracked_quarantine_status"] == "complete"
    quarantine_path = Path(hygiene["tracked_quarantine_path"])
    index_payload = quarantine_path / "index" / rel
    worktree_payload = quarantine_path / "worktree" / rel
    assert index_payload.is_symlink()
    assert os.readlink(index_payload) == "../README.md"
    assert worktree_payload.is_symlink()
    assert os.readlink(worktree_payload) == "../README.md"


def test_activation_quarantines_staged_deletion_before_candidate_reset(
    tmp_path: Path,
) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    drift = active_source / "README.md"
    _git(active_source, "rm", "README.md")
    assert _git(active_source, "ls-files", "--modified", "--deleted") == ""
    assert _git(active_source, "diff", "--cached", "--name-only") == "README.md"

    second = _run_activate(tmp_path, canonical)

    assert second.returncode == 0, second.stderr
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    assert drift.read_text(encoding="utf-8") == "base\nnew origin main\n"
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    quarantine_path = Path(hygiene["tracked_quarantine_path"])
    assert (quarantine_path / "deleted" / "README.md").read_text(
        encoding="utf-8"
    ) == "deleted tracked path: README.md\n"
    assert (quarantine_path / "index-deleted" / "README.md").read_text(
        encoding="utf-8"
    ) == "deleted staged path: README.md\n"


def test_activation_quarantines_tabbed_staged_deletion_before_candidate_reset(
    tmp_path: Path,
) -> None:
    canonical, origin, _new_sha = _make_repos(tmp_path)
    updater = tmp_path / "tabbed-path-updater"
    _git(tmp_path, "clone", str(origin), str(updater))
    _git(updater, "config", "user.email", "source-activate@example.test")
    _git(updater, "config", "user.name", "Source Activate")
    rel = Path("notes") / "tab\ttracked.txt"
    _write(updater / rel, "tracked tab path\n")
    _git(updater, "add", str(rel))
    _git(updater, "commit", "-m", "add tabbed tracked path")
    _git(updater, "push", "origin", "main")
    new_sha = _git(updater, "rev-parse", "HEAD")

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    _git(active_source, "rm", str(rel))

    second = _run_activate(tmp_path, canonical)

    assert second.returncode == 0, second.stderr
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    assert (active_source / rel).read_text(encoding="utf-8") == "tracked tab path\n"
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    quarantine_path = Path(hygiene["tracked_quarantine_path"])
    assert (quarantine_path / "deleted" / rel).read_text(encoding="utf-8") == (
        f"deleted tracked path: {rel}\n"
    )
    assert (quarantine_path / "index-deleted" / rel).read_text(encoding="utf-8") == (
        f"deleted staged path: {rel}\n"
    )


def test_activation_quarantines_both_sides_of_staged_rename_before_candidate_reset(
    tmp_path: Path,
) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    _git(active_source, "config", "diff.renames", "true")
    _git(active_source, "mv", "README.md", "RENAMED.md")
    assert _git(active_source, "ls-files", "--modified", "--deleted") == ""
    assert _git(active_source, "diff", "--cached", "--name-only").splitlines() == ["RENAMED.md"]
    assert set(
        _git(active_source, "diff", "--cached", "--no-renames", "--name-only").splitlines()
    ) == {"README.md", "RENAMED.md"}

    second = _run_activate(tmp_path, canonical)

    assert second.returncode == 0, second.stderr
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    assert (active_source / "README.md").read_text(encoding="utf-8") == ("base\nnew origin main\n")
    assert not (active_source / "RENAMED.md").exists()
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 2
    quarantine_path = Path(hygiene["tracked_quarantine_path"])
    assert (quarantine_path / "deleted" / "README.md").read_text(
        encoding="utf-8"
    ) == "deleted tracked path: README.md\n"
    assert (quarantine_path / "index-deleted" / "README.md").read_text(
        encoding="utf-8"
    ) == "deleted staged path: README.md\n"
    assert (quarantine_path / "worktree" / "RENAMED.md").read_text(
        encoding="utf-8"
    ) == "base\nnew origin main\n"
    assert (quarantine_path / "index" / "RENAMED.md").read_text(
        encoding="utf-8"
    ) == "base\nnew origin main\n"


def test_activation_quarantines_staged_file_to_directory_replacement_before_reset(
    tmp_path: Path,
) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    (active_source / "README.md").unlink()
    _write(active_source / "README.md" / "child.txt", "replacement directory payload\n")
    _git(active_source, "add", "-A", "README.md")
    assert set(
        _git(active_source, "diff", "--cached", "--no-renames", "--name-only").splitlines()
    ) == {"README.md", "README.md/child.txt"}

    second = _run_activate(tmp_path, canonical)

    assert second.returncode == 0, second.stderr
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    assert (active_source / "README.md").read_text(encoding="utf-8") == ("base\nnew origin main\n")
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 2
    quarantine_path = Path(hygiene["tracked_quarantine_path"])
    assert (quarantine_path / "index-deleted" / "README.md").read_text(
        encoding="utf-8"
    ) == "deleted staged path: README.md\n"
    assert (quarantine_path / "index" / "README.md" / "child.txt").read_text(
        encoding="utf-8"
    ) == "replacement directory payload\n"


def test_tracked_quarantine_refuses_symlink_ancestor_escape_before_reset(
    tmp_path: Path,
) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    (active_source / "README.md").unlink()
    _write(active_source / "README.md" / "child.txt", "staged child payload\n")
    _git(active_source, "add", "-A", "README.md")
    assert set(
        _git(active_source, "diff", "--cached", "--no-renames", "--name-only").splitlines()
    ) == {"README.md", "README.md/child.txt"}

    shutil.rmtree(active_source / "README.md")
    (active_source / "README.md").symlink_to("../..")
    _write(tmp_path / "state" / "child.txt", "source payload through symlink\n")

    second = _run_activate(tmp_path, canonical)

    assert second.returncode == 2
    assert "refusing to write tracked drift README.md/child.txt through symlink ancestor" in (
        second.stderr
    )
    assert "partial tracked quarantine payloads:" in second.stderr
    assert (active_source / "README.md").is_symlink()
    assert os.readlink(active_source / "README.md") == "../.."
    assert (tmp_path / "state" / "child.txt").read_text(encoding="utf-8") == (
        "source payload through symlink\n"
    )
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert receipt["status"] == "failed"
    assert receipt["message"] == "tracked drift quarantine write failed before reset"
    assert hygiene["tracked_quarantine_count"] == 1
    assert hygiene["tracked_quarantine_status"] == "partial"
    quarantine_path = Path(hygiene["tracked_quarantine_path"])
    worktree_payload = quarantine_path / "worktree" / "README.md"
    assert worktree_payload.is_symlink()
    assert os.readlink(worktree_payload) == "../.."
    assert not (quarantine_path.parent / "child.txt").exists()
    assert not (quarantine_path / "worktree" / "README.md" / "child.txt").exists()


def test_tracked_quarantine_refuses_newline_symlink_ancestor_escape_before_reset(
    tmp_path: Path,
) -> None:
    canonical, origin, _new_sha = _make_repos(tmp_path)
    updater = tmp_path / "newline-symlink-updater"
    _git(tmp_path, "clone", str(origin), str(updater))
    _git(updater, "config", "user.email", "source-activate@example.test")
    _git(updater, "config", "user.name", "Source Activate")
    tracked_rel = Path("line\nbreak")
    child_rel = tracked_rel / "child.txt"
    _write(updater / tracked_rel, "tracked newline ancestor\n")
    _git(updater, "add", str(tracked_rel))
    _git(updater, "commit", "-m", "add newline ancestor")
    _git(updater, "push", "origin", "main")

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    (active_source / tracked_rel).unlink()
    _write(active_source / child_rel, "staged child payload\n")
    _git(active_source, "add", "-A", ".")
    shutil.rmtree(active_source / tracked_rel)
    (active_source / tracked_rel).symlink_to("../..")
    _write(tmp_path / "state" / "child.txt", "source payload through newline symlink\n")

    second = _run_activate(tmp_path, canonical)

    assert second.returncode == 2
    assert "refusing to write tracked drift" in second.stderr
    assert "through symlink ancestor" in second.stderr
    assert "partial tracked quarantine payloads:" in second.stderr
    assert (active_source / tracked_rel).is_symlink()
    assert os.readlink(active_source / tracked_rel) == "../.."
    assert (tmp_path / "state" / "child.txt").read_text(encoding="utf-8") == (
        "source payload through newline symlink\n"
    )
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert receipt["status"] == "failed"
    assert receipt["message"] == "tracked drift quarantine write failed before reset"
    assert hygiene["tracked_quarantine_count"] == 1
    assert hygiene["tracked_quarantine_status"] == "partial"
    quarantine_path = Path(hygiene["tracked_quarantine_path"])
    worktree_payload = quarantine_path / "worktree" / tracked_rel
    assert worktree_payload.is_symlink()
    assert os.readlink(worktree_payload) == "../.."
    assert not (quarantine_path.parent / "child.txt").exists()
    assert not (quarantine_path / "worktree" / child_rel).exists()


def test_activation_quarantines_unstaged_file_to_directory_replacement_before_reset(
    tmp_path: Path,
) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    (active_source / "README.md").unlink()
    _write(active_source / "README.md" / "child.txt", "unstaged replacement payload\n")
    assert "README.md" in _git(active_source, "ls-files", "--modified", "--deleted")

    second = _run_activate(tmp_path, canonical)

    assert second.returncode == 0, second.stderr
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    assert (active_source / "README.md").read_text(encoding="utf-8") == ("base\nnew origin main\n")
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    assert hygiene["tracked_quarantine_status"] == "complete"
    quarantine_path = Path(hygiene["tracked_quarantine_path"])
    assert (quarantine_path / "worktree" / "README.md" / "child.txt").read_text(
        encoding="utf-8"
    ) == "unstaged replacement payload\n"


def test_activation_counts_multiple_tracked_drift_paths(tmp_path: Path) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    _write(active_source / "README.md", "unstaged tracked drift\n")
    _write(
        active_source / "config" / "usb-topology-policy.json",
        '{"known_absences": {"staged": true}}\n',
    )
    _git(active_source, "add", "config/usb-topology-policy.json")

    second = _run_activate(tmp_path, canonical)

    assert second.returncode == 0, second.stderr
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 2
    quarantine_path = Path(hygiene["tracked_quarantine_path"])
    assert (quarantine_path / "worktree" / "README.md").read_text(
        encoding="utf-8"
    ) == "unstaged tracked drift\n"
    assert (quarantine_path / "index" / "config" / "usb-topology-policy.json").read_text(
        encoding="utf-8"
    ) == '{"known_absences": {"staged": true}}\n'


def test_tracked_quarantine_uses_bytewise_sort_for_distinct_cached_paths(
    tmp_path: Path,
) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    _write(active_source / "Alpha.txt", "uppercase staged addition\n")
    _write(active_source / "alpha.txt", "lowercase staged addition\n")
    _git(active_source, "add", "Alpha.txt", "alpha.txt")
    fake_bin = _fake_tool_bin(
        tmp_path,
        "sort",
        """
        if [[ "$1" == "-zu" && "${LC_ALL:-}" != "C" ]]; then
            python3 - "$@" <<'PY'
import sys
from pathlib import Path

records = []
for arg in sys.argv[2:]:
    for record in Path(arg).read_bytes().split(b"\\0"):
        if record:
            records.append(record)

collapsed = {}
for record in sorted(records, key=lambda item: item.lower()):
    collapsed.setdefault(record.lower(), record)

if collapsed:
    sys.stdout.buffer.write(b"\\0".join(collapsed.values()) + b"\\0")
PY
            exit 0
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert second.returncode == 0, second.stderr
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 2
    quarantine_path = Path(hygiene["tracked_quarantine_path"])
    assert (quarantine_path / "worktree" / "Alpha.txt").read_text(
        encoding="utf-8"
    ) == "uppercase staged addition\n"
    assert (quarantine_path / "worktree" / "alpha.txt").read_text(
        encoding="utf-8"
    ) == "lowercase staged addition\n"
    assert (quarantine_path / "index" / "Alpha.txt").read_text(
        encoding="utf-8"
    ) == "uppercase staged addition\n"
    assert (quarantine_path / "index" / "alpha.txt").read_text(
        encoding="utf-8"
    ) == "lowercase staged addition\n"


def test_activation_counts_partially_staged_path_once_while_preserving_both_payloads(
    tmp_path: Path,
) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    _write(active_source / "README.md", "staged payload\n")
    _git(active_source, "add", "README.md")
    _write(active_source / "README.md", "worktree payload\n")

    second = _run_activate(tmp_path, canonical)

    assert second.returncode == 0, second.stderr
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    quarantine_path = Path(hygiene["tracked_quarantine_path"])
    assert (quarantine_path / "worktree" / "README.md").read_text(
        encoding="utf-8"
    ) == "worktree payload\n"
    assert (quarantine_path / "index" / "README.md").read_text(
        encoding="utf-8"
    ) == "staged payload\n"


def test_tracked_detection_refuses_when_scan_tempfile_allocation_fails(
    tmp_path: Path,
) -> None:
    canonical, active_source, _new_sha = _active_source_with_readme_drift(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "mktemp",
        """
        if [[ "$1" == *"tracked-drift-detect."* ]]; then
            echo forced detection scan tempfile failure >&2
            exit 1
        fi
        """,
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    _assert_tracked_quarantine_failed(
        result,
        tmp_path,
        message="tracked drift scan failed before reset",
        stderr_fragment="failed to allocate tracked drift scan file",
    )
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before refusal\n"
    )


def test_tracked_detection_refuses_when_index_scan_tempfile_allocation_fails(
    tmp_path: Path,
) -> None:
    canonical, active_source, _new_sha = _active_source_with_readme_drift(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "mktemp",
        """
        if [[ "$1" == *"tracked-index-drift-detect."* ]]; then
            echo forced detection index scan tempfile failure >&2
            exit 1
        fi
        """,
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    _assert_tracked_quarantine_failed(
        result,
        tmp_path,
        message="tracked drift scan failed before reset",
        stderr_fragment="failed to allocate tracked index drift scan file",
    )
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before refusal\n"
    )


def test_tracked_quarantine_refuses_when_scan_tempfile_allocation_fails(
    tmp_path: Path,
) -> None:
    canonical, active_source, _new_sha = _active_source_with_readme_drift(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "mktemp",
        """
        if [[ "$*" == *"tracked-drift."* ]]; then
            echo forced scan tempfile failure >&2
            exit 1
        fi
        """,
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    _assert_tracked_quarantine_failed(
        result,
        tmp_path,
        message="tracked drift scan failed before reset",
        stderr_fragment="failed to allocate tracked drift scan file",
    )
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before refusal\n"
    )


def test_tracked_quarantine_refuses_when_index_scan_tempfile_allocation_fails(
    tmp_path: Path,
) -> None:
    canonical, active_source, _new_sha = _active_source_with_readme_drift(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "mktemp",
        """
        if [[ "$*" == *"tracked-index-drift."* ]]; then
            echo forced index scan tempfile failure >&2
            exit 1
        fi
        """,
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    _assert_tracked_quarantine_failed(
        result,
        tmp_path,
        message="tracked drift scan failed before reset",
        stderr_fragment="failed to allocate tracked index drift scan file",
    )
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before refusal\n"
    )


def test_tracked_quarantine_refuses_when_index_entry_tempfile_allocation_fails(
    tmp_path: Path,
) -> None:
    canonical, active_source, _new_sha = _active_source_with_readme_drift(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "mktemp",
        """
        if [[ "$*" == *"tracked-index-entries."* ]]; then
            echo forced index entry tempfile failure >&2
            exit 1
        fi
        """,
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    _assert_tracked_quarantine_failed(
        result,
        tmp_path,
        message="tracked drift scan failed before reset",
        stderr_fragment="failed to allocate tracked index entry scan file",
    )
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before refusal\n"
    )


def test_tracked_quarantine_refuses_when_sorted_tempfile_allocation_fails(
    tmp_path: Path,
) -> None:
    canonical, active_source, _new_sha = _active_source_with_readme_drift(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "mktemp",
        """
        if [[ "$*" == *"tracked-drift-sorted."* ]]; then
            echo forced sorted tempfile failure >&2
            exit 1
        fi
        """,
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    _assert_tracked_quarantine_failed(
        result,
        tmp_path,
        message="tracked drift scan failed before reset",
        stderr_fragment="failed to allocate tracked drift normalization file",
    )
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before refusal\n"
    )


def test_tracked_quarantine_refuses_when_git_worktree_scan_fails(
    tmp_path: Path,
) -> None:
    canonical, active_source, _new_sha = _active_source_with_readme_drift(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "${HAPAX_TEST_SOURCE_ROOT:-}" != "" \
            && "$1" == "-C" \
            && "$2" == "$HAPAX_TEST_SOURCE_ROOT" \
            && "$3" == "ls-files" \
            && "$4" == "-z" \
            && "$5" == "--modified" \
            && "$6" == "--deleted" ]]; then
            echo forced worktree scan failure >&2
            exit 41
        fi
        """,
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_TEST_SOURCE_ROOT": str(active_source.resolve()),
        },
    )

    _assert_tracked_quarantine_failed(
        result,
        tmp_path,
        message="tracked drift scan failed before reset",
        stderr_fragment="tracked drift scan failed",
    )
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before refusal\n"
    )


def test_tracked_quarantine_refuses_when_git_index_scan_fails(
    tmp_path: Path,
) -> None:
    canonical, active_source, _new_sha = _active_source_with_readme_drift(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "${HAPAX_TEST_SOURCE_ROOT:-}" != "" \
            && "$1" == "-C" \
            && "$2" == "$HAPAX_TEST_SOURCE_ROOT" \
            && "$3" == "diff" \
            && "$4" == "--cached" \
            && "$5" == "--no-renames" \
            && "$6" == "--name-only" \
            && "$7" == "-z" ]]; then
            echo forced index scan failure >&2
            exit 42
        fi
        """,
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_TEST_SOURCE_ROOT": str(active_source.resolve()),
        },
    )

    _assert_tracked_quarantine_failed(
        result,
        tmp_path,
        message="tracked drift scan failed before reset",
        stderr_fragment="tracked index drift scan failed",
    )
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before refusal\n"
    )


def test_tracked_quarantine_refuses_when_git_index_entry_scan_fails(
    tmp_path: Path,
) -> None:
    canonical, active_source, _new_sha = _active_source_with_readme_drift(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "${HAPAX_TEST_SOURCE_ROOT:-}" != "" \
            && "$1" == "-C" \
            && "$2" == "$HAPAX_TEST_SOURCE_ROOT" \
            && "$3" == "ls-files" \
            && "$4" == "-z" \
            && "$5" == "--stage" ]]; then
            echo forced index entry scan failure >&2
            exit 43
        fi
        """,
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_TEST_SOURCE_ROOT": str(active_source.resolve()),
        },
    )

    _assert_tracked_quarantine_failed(
        result,
        tmp_path,
        message="tracked drift scan failed before reset",
        stderr_fragment="tracked index entry scan failed",
    )
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before refusal\n"
    )


def test_tracked_quarantine_refuses_when_checkout_index_fails(tmp_path: Path) -> None:
    canonical, active_source, _new_sha = _active_source_with_readme_drift(tmp_path)
    _git(active_source, "add", "README.md")
    _write(active_source / "README.md", "worktree payload after staged drift\n")
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "${HAPAX_TEST_SOURCE_ROOT:-}" != "" \
            && "$1" == "-C" \
            && "$2" == "$HAPAX_TEST_SOURCE_ROOT" \
            && "$3" == "checkout-index" ]]; then
            echo forced checkout-index failure >&2
            exit 44
        fi
        """,
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_TEST_SOURCE_ROOT": str(active_source.resolve()),
        },
    )

    _assert_tracked_quarantine_failed(
        result,
        tmp_path,
        message="tracked drift quarantine write failed before reset",
        stderr_fragment="failed to preserve tracked index drift README.md",
    )
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "worktree payload after staged drift\n"
    )


def test_tracked_quarantine_refuses_when_sort_fails(tmp_path: Path) -> None:
    canonical, active_source, _new_sha = _active_source_with_readme_drift(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "sort",
        """
        if [[ "$1" == "-zu" ]]; then
            echo forced sort failure >&2
            exit 43
        fi
        """,
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    _assert_tracked_quarantine_failed(
        result,
        tmp_path,
        message="tracked drift scan failed before reset",
        stderr_fragment="tracked drift path normalization failed",
    )
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before refusal\n"
    )


def test_tracked_quarantine_refuses_when_sorted_scan_file_read_fails(
    tmp_path: Path,
) -> None:
    canonical, active_source, _new_sha = _active_source_with_readme_drift(tmp_path)
    bash_env = _bash_env_fail_nul_mapfile(
        tmp_path,
        "tracked_paths",
        "tracked drift normalization",
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"BASH_ENV": str(bash_env)},
    )

    _assert_tracked_quarantine_failed(
        result,
        tmp_path,
        message="tracked drift scan failed before reset",
        stderr_fragment="failed to read tracked drift normalization file",
    )
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before refusal\n"
    )


def test_tracked_quarantine_refuses_when_index_scan_file_read_fails(
    tmp_path: Path,
) -> None:
    canonical, active_source, _new_sha = _active_source_with_readme_drift(tmp_path)
    _git(active_source, "add", "README.md")
    bash_env = _bash_env_fail_nul_mapfile(
        tmp_path,
        "cached_paths",
        "tracked index drift scan",
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"BASH_ENV": str(bash_env)},
    )

    _assert_tracked_quarantine_failed(
        result,
        tmp_path,
        message="tracked drift scan failed before reset",
        stderr_fragment="failed to read tracked index drift scan file",
    )
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before refusal\n"
    )
    assert _git(active_source, "diff", "--cached", "--name-only") == "README.md"


def test_tracked_quarantine_refuses_when_index_entry_scan_file_read_fails(
    tmp_path: Path,
) -> None:
    canonical, active_source, _new_sha = _active_source_with_readme_drift(tmp_path)
    bash_env = _bash_env_fail_nul_mapfile(
        tmp_path,
        "index_records",
        "tracked index entry scan",
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"BASH_ENV": str(bash_env)},
    )

    _assert_tracked_quarantine_failed(
        result,
        tmp_path,
        message="tracked drift scan failed before reset",
        stderr_fragment="failed to read tracked index entry scan file",
    )
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before refusal\n"
    )


def test_tracked_quarantine_refuses_when_quarantine_timestamp_fails(
    tmp_path: Path,
) -> None:
    canonical, active_source, _new_sha = _active_source_with_readme_drift(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "date",
        """
        if [[ "$1" == "-u" ]]; then
            echo forced date failure >&2
            exit 50
        fi
        """,
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    _assert_tracked_quarantine_failed(
        result,
        tmp_path,
        message="tracked drift quarantine setup failed before reset",
        stderr_fragment="failed to create tracked drift quarantine root",
    )
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before refusal\n"
    )


def test_tracked_quarantine_refuses_when_quarantine_root_cannot_be_created(
    tmp_path: Path,
) -> None:
    canonical, active_source, _new_sha = _active_source_with_readme_drift(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "mkdir",
        """
        for arg in "$@"; do
            if [[ "$arg" == *"/drift-quarantine"* ]]; then
                echo forced quarantine root failure >&2
                exit 44
            fi
        done
        """,
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    _assert_tracked_quarantine_failed(
        result,
        tmp_path,
        message="tracked drift quarantine setup failed before reset",
        stderr_fragment="failed to create tracked drift quarantine root",
    )
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before refusal\n"
    )


def test_tracked_quarantine_refuses_when_quarantine_directory_allocation_fails(
    tmp_path: Path,
) -> None:
    canonical, active_source, _new_sha = _active_source_with_readme_drift(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "mktemp",
        """
        if [[ "$1" == "-d" && "$2" == *"/drift-quarantine/"* ]]; then
            echo forced quarantine directory allocation failure >&2
            exit 51
        fi
        """,
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    _assert_tracked_quarantine_failed(
        result,
        tmp_path,
        message="tracked drift quarantine setup failed before reset",
        stderr_fragment="failed to create tracked drift quarantine root",
    )
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before refusal\n"
    )


def test_tracked_quarantine_refuses_when_worktree_copy_fails(tmp_path: Path) -> None:
    canonical, active_source, _new_sha = _active_source_with_readme_drift(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "cp",
        """
        for arg in "$@"; do
            if [[ "$arg" == *"/.hapax-tracked/worktree/"* ]]; then
                echo forced tracked copy failure >&2
                exit 45
            fi
        done
        """,
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    _assert_tracked_quarantine_failed(
        result,
        tmp_path,
        message="tracked drift quarantine write failed before reset",
        stderr_fragment="failed to preserve tracked drift README.md",
    )
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before refusal\n"
    )


def test_tracked_quarantine_marks_later_copy_failure_partial(tmp_path: Path) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)
    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr
    active_source = tmp_path / "active-source"
    _write(active_source / "README.md", "first tracked drift before refusal\n")
    _write(
        active_source / "config" / "usb-topology-policy.json",
        '{"known_absences": {"later": true}}\n',
    )
    fake_bin = _fake_tool_bin(
        tmp_path,
        "cp",
        """
        destination="${@: -1}"
        if [[ "$destination" == *"/.hapax-tracked/worktree/config/usb-topology-policy.json" ]]; then
            echo forced later tracked copy failure >&2
            exit 56
        fi
        """,
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert result.returncode == 2
    assert "failed to preserve tracked drift config/usb-topology-policy.json" in result.stderr
    assert "partial tracked quarantine payloads:" in result.stderr
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "first tracked drift before refusal\n"
    )
    assert (active_source / "config" / "usb-topology-policy.json").read_text(
        encoding="utf-8"
    ) == '{"known_absences": {"later": true}}\n'
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    assert hygiene["tracked_quarantine_status"] == "partial"
    quarantine_path = Path(hygiene["tracked_quarantine_path"])
    assert (quarantine_path / "worktree" / "README.md").read_text(
        encoding="utf-8"
    ) == "first tracked drift before refusal\n"
    assert not (quarantine_path / "worktree" / "config" / "usb-topology-policy.json").exists()


def test_tracked_quarantine_refuses_when_worktree_payload_destination_collides(
    tmp_path: Path,
) -> None:
    canonical, active_source, _new_sha = _active_source_with_readme_drift(tmp_path)
    fake_bin = _fake_tool_bin(
        tmp_path,
        "cp",
        """
        destination="${@: -1}"
        if [[ "$destination" == *"/.hapax-tracked/worktree/README.md" ]]; then
            mkdir -p "$destination/child"
            echo forced tracked nested destination collision >&2
            exit 45
        fi
        """,
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    _assert_tracked_quarantine_failed(
        result,
        tmp_path,
        message="tracked drift quarantine write failed before reset",
        stderr_fragment="failed to preserve tracked drift README.md",
    )
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "tracked drift before refusal\n"
    )


def test_tracked_quarantine_refuses_when_deletion_marker_write_fails(
    tmp_path: Path,
) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)
    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr
    active_source = tmp_path / "active-source"
    (active_source / "README.md").unlink()
    fake_bin = _fake_tool_bin(
        tmp_path,
        "mkdir",
        """
        for arg in "$@"; do
            if [[ "$arg" == *"/.hapax-tracked/deleted"* ]]; then
                echo forced deletion marker failure >&2
                exit 46
            fi
        done
        """,
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    _assert_tracked_quarantine_failed(
        result,
        tmp_path,
        message="tracked drift quarantine write failed before reset",
        stderr_fragment="failed to preserve tracked deletion marker README.md",
    )
    assert not (active_source / "README.md").exists()


def test_tracked_quarantine_refuses_when_index_checkout_fails(tmp_path: Path) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)
    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr
    active_source = tmp_path / "active-source"
    _write(active_source / "README.md", "staged drift before refusal\n")
    _git(active_source, "add", "README.md")
    fake_bin = _fake_tool_bin(
        tmp_path,
        "git",
        """
        if [[ "${HAPAX_TEST_SOURCE_ROOT:-}" != "" \
            && "$1" == "-C" \
            && "$2" == "$HAPAX_TEST_SOURCE_ROOT" \
            && "$3" == "checkout-index" ]]; then
            echo forced index checkout failure >&2
            exit 47
        fi
        """,
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_TEST_SOURCE_ROOT": str(active_source.resolve()),
        },
    )

    _assert_tracked_quarantine_failed(
        result,
        tmp_path,
        message="tracked drift quarantine write failed before reset",
        stderr_fragment="failed to preserve tracked index drift README.md",
    )
    assert (active_source / "README.md").read_text(encoding="utf-8") == (
        "staged drift before refusal\n"
    )


def test_tracked_quarantine_refuses_when_index_deletion_marker_write_fails(
    tmp_path: Path,
) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)
    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr
    active_source = tmp_path / "active-source"
    _git(active_source, "rm", "README.md")
    fake_bin = _fake_tool_bin(
        tmp_path,
        "mkdir",
        """
        for arg in "$@"; do
            if [[ "$arg" == *"/.hapax-tracked/index-deleted"* ]]; then
                echo forced index deletion marker failure >&2
                exit 48
            fi
        done
        """,
    )

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    _assert_tracked_quarantine_failed(
        result,
        tmp_path,
        message="tracked drift quarantine write failed before reset",
        stderr_fragment="failed to preserve tracked index deletion marker README.md",
    )
    assert not (active_source / "README.md").exists()


def test_activation_uses_one_quarantine_root_for_tracked_and_untracked_drift(
    tmp_path: Path,
) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    _write(active_source / "README.md", "tracked drift before reset\n")
    _write(active_source / "notes" / "rogue.txt", "untracked drift before reset\n")

    second = _run_activate(tmp_path, canonical)

    assert second.returncode == 0, second.stderr
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    assert hygiene["untracked_quarantine_count"] == 1
    tracked_path = Path(hygiene["tracked_quarantine_path"])
    untracked_path = Path(hygiene["untracked_quarantine_path"])
    assert tracked_path.parent == untracked_path.parent
    assert tracked_path.name == ".hapax-tracked"
    assert untracked_path.name == ".hapax-untracked"
    assert (tracked_path / "worktree" / "README.md").read_text(
        encoding="utf-8"
    ) == "tracked drift before reset\n"
    assert (untracked_path / "notes" / "rogue.txt").read_text(encoding="utf-8") == (
        "untracked drift before reset\n"
    )


def test_activation_keeps_untracked_reserved_paths_from_overwriting_tracked_quarantine(
    tmp_path: Path,
) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    _write(active_source / "README.md", "tracked recovery payload\n")
    _write(
        active_source / ".hapax-tracked" / "worktree" / "README.md",
        "untracked collision payload\n",
    )

    second = _run_activate(tmp_path, canonical)

    assert second.returncode == 0, second.stderr
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    assert hygiene["untracked_quarantine_count"] == 1
    tracked_path = Path(hygiene["tracked_quarantine_path"])
    untracked_path = Path(hygiene["untracked_quarantine_path"])
    assert (tracked_path / "worktree" / "README.md").read_text(
        encoding="utf-8"
    ) == "tracked recovery payload\n"
    assert (untracked_path / ".hapax-tracked" / "worktree" / "README.md").read_text(
        encoding="utf-8"
    ) == "untracked collision payload\n"


def test_activation_preserves_existing_drift_quarantine_roots(tmp_path: Path) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    quarantine_root = tmp_path / "state" / "drift-quarantine"
    old_root = _seed_quarantine_root(quarantine_root, "old-recovery-root")
    active_source = tmp_path / "active-source"
    _write(active_source / "README.md", "tracked drift before reset\n")

    second = _run_activate(tmp_path, canonical)

    assert second.returncode == 0, second.stderr
    assert old_root.exists()
    receipt = _current_receipt(tmp_path)
    current_root = Path(receipt["source_hygiene"]["tracked_quarantine_path"]).parent
    assert current_root.exists()


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
        (tmp_path / "state" / "drift-quarantine").glob(
            "*/.hapax-untracked/scripts/hapax-rogue-untracked"
        )
    )
    assert len(quarantined) == 1
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "no_op"
    assert receipt["source_hygiene"]["untracked_quarantine_count"] == 1
    assert receipt["source_hygiene"]["untracked_symlink_removed_count"] == 1
    assert "drift-quarantine" in receipt["source_hygiene"]["untracked_quarantine_path"]


def test_untracked_quarantine_refuses_when_quarantine_setup_fails(
    tmp_path: Path,
) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    rogue = active_source / "notes" / "rogue.txt"
    _write(rogue, "untracked drift before refusal\n")
    fake_bin = _fake_tool_bin(
        tmp_path,
        "date",
        """
        if [[ "$1" == "-u" ]]; then
            echo forced date failure >&2
            exit 52
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert second.returncode == 2
    assert "failed to create untracked drift quarantine root" in second.stderr
    assert "next action:" in second.stderr
    assert rogue.read_text(encoding="utf-8") == "untracked drift before refusal\n"
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["message"] == "untracked drift quarantine setup failed before sweep"
    assert receipt["source_hygiene"]["untracked_quarantine_count"] == 0


def test_untracked_quarantine_refuses_when_scan_tempfile_allocation_fails(
    tmp_path: Path,
) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    rogue = active_source / "notes" / "rogue.txt"
    _write(rogue, "untracked drift before scan allocation refusal\n")
    fake_bin = _fake_tool_bin(
        tmp_path,
        "mktemp",
        """
        if [[ "$1" == *"/untracked-drift."* ]]; then
            echo forced untracked scan allocation failure >&2
            exit 75
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    _assert_untracked_quarantine_failed(
        second,
        tmp_path,
        message="untracked drift scan failed before sweep",
        stderr_fragment="failed to allocate untracked drift scan file",
    )
    assert rogue.read_text(encoding="utf-8") == ("untracked drift before scan allocation refusal\n")


def test_untracked_quarantine_refuses_when_scan_file_read_fails(
    tmp_path: Path,
) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    rogue = active_source / "notes" / "rogue.txt"
    _write(rogue, "untracked drift before scan read refusal\n")
    bash_env = tmp_path / "fail-untracked-mapfile.bash"
    _write(
        bash_env,
        textwrap.dedent(
            """\
            mapfile() {
                if [[ "$1" == "-t" && "$2" == "untracked_paths" ]]; then
                    echo forced untracked scan read failure >&2
                    return 76
                fi
                builtin mapfile "$@"
            }
            """
        ),
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"BASH_ENV": str(bash_env)},
    )

    _assert_untracked_quarantine_failed(
        second,
        tmp_path,
        message="untracked drift scan failed before sweep",
        stderr_fragment="failed to read untracked drift scan file",
    )
    assert rogue.read_text(encoding="utf-8") == "untracked drift before scan read refusal\n"


def test_untracked_quarantine_refuses_when_payload_root_creation_fails(
    tmp_path: Path,
) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    rogue = active_source / "notes" / "rogue.txt"
    _write(rogue, "untracked drift before refusal\n")
    fake_bin = _fake_tool_bin(
        tmp_path,
        "mkdir",
        """
        for arg in "$@"; do
            if [[ "$arg" == *"/.hapax-untracked" ]]; then
                echo forced untracked payload root failure >&2
                exit 57
            fi
        done
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    _assert_untracked_quarantine_failed(
        second,
        tmp_path,
        message="untracked drift quarantine write failed before sweep",
        stderr_fragment="failed to create untracked drift quarantine payload root",
    )
    assert rogue.read_text(encoding="utf-8") == "untracked drift before refusal\n"
    receipt = _current_receipt(tmp_path)
    assert receipt["source_hygiene"]["untracked_quarantine_path"] == ""


def test_untracked_quarantine_refuses_when_parent_creation_fails(
    tmp_path: Path,
) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    rogue = active_source / "notes" / "rogue.txt"
    _write(rogue, "untracked drift before refusal\n")
    fake_bin = _fake_tool_bin(
        tmp_path,
        "mkdir",
        """
        for arg in "$@"; do
            if [[ "$arg" == *"/.hapax-untracked/notes" ]]; then
                echo forced untracked parent failure >&2
                exit 58
            fi
        done
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    _assert_untracked_quarantine_failed(
        second,
        tmp_path,
        message="untracked drift quarantine write failed before sweep",
        stderr_fragment="failed to preserve untracked drift notes/rogue.txt",
    )
    assert rogue.read_text(encoding="utf-8") == "untracked drift before refusal\n"
    receipt = _current_receipt(tmp_path)
    assert receipt["source_hygiene"]["untracked_quarantine_path"] == ""


def test_untracked_quarantine_refuses_when_move_fails(
    tmp_path: Path,
) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    rogue = active_source / "notes" / "rogue.txt"
    _write(rogue, "untracked drift before refusal\n")
    fake_bin = _fake_tool_bin(
        tmp_path,
        "mv",
        """
        destination="${@: -1}"
        if [[ "$destination" == *"/.hapax-untracked/notes/rogue.txt" ]]; then
            echo forced untracked move failure >&2
            exit 55
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    _assert_untracked_quarantine_failed(
        second,
        tmp_path,
        message="untracked drift quarantine write failed before sweep",
        stderr_fragment="failed to preserve untracked drift notes/rogue.txt",
    )
    assert rogue.read_text(encoding="utf-8") == "untracked drift before refusal\n"
    receipt = _current_receipt(tmp_path)
    assert receipt["source_hygiene"]["untracked_quarantine_path"] == ""


def test_untracked_quarantine_marks_later_move_failure_partial(
    tmp_path: Path,
) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    active_source = tmp_path / "active-source"
    first_rogue = active_source / "notes" / "alpha.txt"
    second_rogue = active_source / "notes" / "zeta.txt"
    _write(first_rogue, "first untracked drift before refusal\n")
    _write(second_rogue, "second untracked drift before refusal\n")
    fake_bin = _fake_tool_bin(
        tmp_path,
        "mv",
        """
        destination="${@: -1}"
        if [[ "$destination" == *"/.hapax-untracked/notes/zeta.txt" ]]; then
            echo forced later untracked move failure >&2
            exit 59
        fi
        """,
    )

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert second.returncode == 2
    assert "failed to preserve untracked drift notes/zeta.txt" in second.stderr
    assert "partial untracked quarantine payloads:" in second.stderr
    assert not first_rogue.exists()
    assert second_rogue.read_text(encoding="utf-8") == "second untracked drift before refusal\n"
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["untracked_quarantine_count"] == 1
    assert hygiene["untracked_quarantine_status"] == "partial"
    quarantine_path = Path(hygiene["untracked_quarantine_path"])
    assert (quarantine_path / "notes" / "alpha.txt").read_text(encoding="utf-8") == (
        "first untracked drift before refusal\n"
    )
    assert not (quarantine_path / "notes" / "zeta.txt").exists()


def test_activation_links_canonical_runtime_profiles_without_quarantining_them(
    tmp_path: Path,
) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)
    runtime_profile = canonical / "profiles" / "health-history.jsonl"
    _write(runtime_profile, '{"status":"healthy"}\n')

    first = _run_activate(tmp_path, canonical)
    second = _run_activate(tmp_path, canonical)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    active_profile = tmp_path / "active-source" / "profiles" / "health-history.jsonl"
    assert active_profile.is_symlink()
    assert os.readlink(active_profile) == str(runtime_profile)
    assert _git(tmp_path / "active-source", "rev-parse", "HEAD") == new_sha
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "no_op"
    assert receipt["source_hygiene"]["runtime_profile_link_count"] == 0
    assert receipt["source_hygiene"]["untracked_quarantine_count"] == 0
    assert receipt["source_hygiene"]["untracked_quarantine_path"] == ""
    assert receipt["source_hygiene"]["untracked_quarantine_status"] == "skipped_runtime_profile"
    assert not (tmp_path / "state" / "drift-quarantine").exists()


def test_activation_leaves_untracked_path_empty_when_only_runtime_profile_is_skipped(
    tmp_path: Path,
) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)
    runtime_profile = canonical / "profiles" / "health-history.jsonl"
    _write(runtime_profile, '{"status":"healthy"}\n')

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr
    active_source = tmp_path / "active-source"
    _write(active_source / "README.md", "tracked drift before reset\n")

    second = _run_activate(tmp_path, canonical)

    assert second.returncode == 0, second.stderr
    assert _git(active_source, "rev-parse", "HEAD") == new_sha
    receipt = _current_receipt(tmp_path)
    hygiene = receipt["source_hygiene"]
    assert hygiene["tracked_quarantine_count"] == 1
    assert "drift-quarantine" in hygiene["tracked_quarantine_path"]
    assert hygiene["untracked_quarantine_count"] == 0
    assert hygiene["untracked_quarantine_path"] == ""
    assert hygiene["untracked_quarantine_status"] == "skipped_runtime_profile"


def test_failed_deploy_writes_failed_receipt_without_last_success(tmp_path: Path) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)

    result = _run_activate(tmp_path, canonical, deploy_exit=7)

    assert result.returncode == 7
    assert (tmp_path / "active-source").is_symlink()
    assert _git(tmp_path / "active-source", "rev-parse", "HEAD") == new_sha
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["deploy_status"] == "failed"
    assert receipt["exit_code"] == 7
    assert receipt["source_cutover"]["rollback_status"] == "unavailable"
    assert not (tmp_path / "state" / "last-success-sha").exists()


def test_failed_deploy_rolls_back_active_symlink_to_previous_release(tmp_path: Path) -> None:
    canonical, origin, active_sha = _make_repos(tmp_path)

    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr
    latest_sha = _advance_origin(tmp_path, origin, "advance before failed deploy")

    second = _run_activate(tmp_path, canonical, deploy_exit=7)

    assert second.returncode == 7
    assert latest_sha != active_sha
    assert (tmp_path / "active-source").resolve() == tmp_path / "state" / "releases" / active_sha
    assert _git(tmp_path / "active-source", "rev-parse", "HEAD") == active_sha
    assert (tmp_path / "deploy-record.txt").read_text(encoding="utf-8").splitlines() == [
        active_sha,
        latest_sha,
    ]
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["origin_main_sha"] == latest_sha
    assert receipt["active_source_head"] == active_sha
    assert receipt["source_cutover"]["rollback_status"] == "success"
    assert receipt["source_cutover"]["previous_active_target"] == str(
        tmp_path / "state" / "releases" / active_sha
    )
    assert receipt["source_cutover"]["promoted_active_target"] == str(
        tmp_path / "state" / "releases" / latest_sha
    )
    assert (tmp_path / "state" / "last-success-sha").read_text(
        encoding="utf-8"
    ).strip() == active_sha


def test_failed_deploy_restores_previous_release_launcher(tmp_path: Path) -> None:
    canonical, origin, active_sha = _make_repos(tmp_path)
    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr

    previous_script = tmp_path / "active-source" / "scripts" / "hapax-post-merge-deploy"
    previous_content = previous_script.read_text(encoding="utf-8")
    local_launcher = tmp_path / "home" / ".local" / "bin" / "hapax-post-merge-deploy"
    local_cc_claim = tmp_path / "home" / ".local" / "bin" / "cc-claim"
    previous_cc_claim_target = os.readlink(local_cc_claim)
    failed_only_launcher = tmp_path / "home" / ".local" / "bin" / "hapax-failed-candidate"
    local_launcher.unlink()
    _write(local_launcher, previous_content, executable=True)

    updater = tmp_path / "updater-failed-launcher"
    _git(tmp_path, "clone", str(origin), str(updater))
    _git(updater, "config", "user.email", "source-activate@example.test")
    _git(updater, "config", "user.name", "Source Activate")
    _write(
        updater / "scripts" / "hapax-post-merge-deploy",
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            rm -f "$HOME/.local/bin/hapax-post-merge-deploy"
            printf '#!/usr/bin/env bash\\necho failed candidate\\n' > "$HOME/.local/bin/hapax-post-merge-deploy"
            chmod 0755 "$HOME/.local/bin/hapax-post-merge-deploy"
            rm -f "$HOME/.local/bin/cc-claim"
            printf '#!/usr/bin/env bash\\necho failed cc claim\\n' > "$HOME/.local/bin/cc-claim"
            chmod 0755 "$HOME/.local/bin/cc-claim"
            printf '#!/usr/bin/env bash\\necho failed-only launcher\\n' > "$HOME/.local/bin/hapax-failed-candidate"
            chmod 0755 "$HOME/.local/bin/hapax-failed-candidate"
            exit 7
            """
        ),
        executable=True,
    )
    _write(
        updater / "scripts" / "hapax-failed-candidate",
        "#!/usr/bin/env bash\necho candidate source\n",
        executable=True,
    )
    _git(updater, "add", "scripts/hapax-post-merge-deploy", "scripts/hapax-failed-candidate")
    _git(updater, "commit", "-m", "candidate deploy fails after launcher install")
    _git(updater, "push", "origin", "main")
    failed_sha = _git(updater, "rev-parse", "HEAD")

    second = _run_activate(tmp_path, canonical)

    assert second.returncode == 7
    assert failed_sha != active_sha
    assert _git(tmp_path / "active-source", "rev-parse", "HEAD") == active_sha
    assert local_launcher.is_file()
    assert not local_launcher.is_symlink()
    assert local_launcher.read_text(encoding="utf-8") == previous_content
    assert local_cc_claim.is_symlink()
    assert os.readlink(local_cc_claim) == previous_cc_claim_target
    assert not failed_only_launcher.exists()
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["source_cutover"]["rollback_status"] == "success"


def test_launcher_snapshot_copy_failure_aborts_before_sweep_or_deploy(tmp_path: Path) -> None:
    canonical, origin, active_sha = _make_repos(tmp_path)
    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr
    latest_sha = _advance_origin(tmp_path, origin, "advance before snapshot failure")
    assert latest_sha != active_sha
    launcher = tmp_path / "home" / ".local" / "bin" / "hapax-post-merge-deploy"
    prior_target = os.readlink(launcher)

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": _path_with_failing_launcher_cp(tmp_path, phase="snapshot")},
    )

    assert second.returncode == 2
    assert "unable to snapshot managed launcher" in second.stderr
    assert _git(tmp_path / "active-source", "rev-parse", "HEAD") == active_sha
    assert launcher.is_symlink()
    assert os.readlink(launcher) == prior_target
    assert (tmp_path / "deploy-record.txt").read_text(encoding="utf-8").splitlines() == [active_sha]
    assert list((tmp_path / "state").glob("launcher-rollback.*")) == []
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["deploy_status"] == "not_started"


def test_launcher_publication_failure_rolls_back_before_deploy(tmp_path: Path) -> None:
    canonical, origin, active_sha = _make_repos(tmp_path)
    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr
    local_bin = tmp_path / "home" / ".local" / "bin"
    existing_launcher = local_bin / "hapax-post-merge-deploy"
    existing_target = os.readlink(existing_launcher)
    replaced_name = "hapax-a-publication"
    replaced_launcher = local_bin / replaced_name
    replaced_content = "#!/usr/bin/env bash\necho prior launcher\n"
    _write(replaced_launcher, replaced_content, executable=True)

    updater = tmp_path / "updater-launcher-publication-failure"
    _git(tmp_path, "clone", str(origin), str(updater))
    _git(updater, "config", "user.email", "source-activate@example.test")
    _git(updater, "config", "user.name", "Source Activate")
    failed_name = "hapax-z-publication-failure"
    _write(
        updater / "scripts" / replaced_name,
        "#!/usr/bin/env bash\necho candidate launcher\n",
        executable=True,
    )
    _write(
        updater / "scripts" / failed_name,
        "#!/usr/bin/env bash\nexit 0\n",
        executable=True,
    )
    _git(updater, "add", f"scripts/{replaced_name}", f"scripts/{failed_name}")
    _git(updater, "commit", "-m", "add launcher whose publication fails")
    _git(updater, "push", "origin", "main")
    failed_sha = _git(updater, "rev-parse", "HEAD")

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": _path_with_failing_predeploy_command(
                tmp_path,
                command="ln",
                launcher_name=failed_name,
            )
        },
    )

    assert second.returncode == 2
    assert failed_sha != active_sha
    assert "unable to publish managed launcher" in second.stderr
    assert "deployment was not started" in second.stderr
    assert _git(tmp_path / "active-source", "rev-parse", "HEAD") == active_sha
    assert existing_launcher.is_symlink()
    assert os.readlink(existing_launcher) == existing_target
    assert replaced_launcher.is_file()
    assert not replaced_launcher.is_symlink()
    assert replaced_launcher.read_text(encoding="utf-8") == replaced_content
    assert not (local_bin / failed_name).exists()
    assert (tmp_path / "deploy-record.txt").read_text(encoding="utf-8").splitlines() == [active_sha]
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["deploy_status"] == "not_started"
    assert receipt["source_cutover"]["rollback_status"] == "success"
    assert "managed launcher publication failed" in receipt["message"]


def test_active_config_staging_failure_rolls_back_before_deploy(tmp_path: Path) -> None:
    canonical, origin, active_sha = _make_repos(tmp_path)
    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr
    installed_policy = tmp_path / "home" / ".config" / "hapax" / "usb-topology-policy.json"
    previous_policy = installed_policy.read_text(encoding="utf-8")

    updater = tmp_path / "updater-config-staging-failure"
    _git(tmp_path, "clone", str(origin), str(updater))
    _git(updater, "config", "user.email", "source-activate@example.test")
    _git(updater, "config", "user.name", "Source Activate")
    _write(updater / "config" / "usb-topology-policy.json", '{"known_absences":{"new":true}}\n')
    _git(updater, "add", "config/usb-topology-policy.json")
    _git(updater, "commit", "-m", "change config whose staging fails")
    _git(updater, "push", "origin", "main")
    failed_sha = _git(updater, "rev-parse", "HEAD")

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": _path_with_failing_predeploy_command(tmp_path, command="install")},
    )

    assert second.returncode == 2
    assert failed_sha != active_sha
    assert "unable to stage active config" in second.stderr
    assert "deployment was not started" in second.stderr
    assert _git(tmp_path / "active-source", "rev-parse", "HEAD") == active_sha
    assert installed_policy.read_text(encoding="utf-8") == previous_policy
    assert (tmp_path / "deploy-record.txt").read_text(encoding="utf-8").splitlines() == [active_sha]
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["deploy_status"] == "not_started"
    assert receipt["source_cutover"]["rollback_status"] == "success"
    assert "active config staging failed" in receipt["message"]


def test_postpublication_deploy_failure_restores_prior_active_config_alias(
    tmp_path: Path,
) -> None:
    canonical, origin, active_sha = _make_repos(tmp_path)
    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr
    active_source = tmp_path / "active-source"
    installed_policy = tmp_path / "home" / ".config" / "hapax" / "usb-topology-policy.json"
    prior_target = active_source / "config" / "usb-topology-policy.json"
    prior_content = prior_target.read_text(encoding="utf-8")
    installed_policy.unlink()
    installed_policy.symlink_to(prior_target)

    updater = tmp_path / "updater-config-deploy-failure"
    _git(tmp_path, "clone", str(origin), str(updater))
    _git(updater, "config", "user.email", "source-activate@example.test")
    _git(updater, "config", "user.name", "Source Activate")
    _write(updater / "config" / "usb-topology-policy.json", '{"known_absences":{"new":true}}\n')
    _git(updater, "add", "config/usb-topology-policy.json")
    _git(updater, "commit", "-m", "change config before failed deploy")
    _git(updater, "push", "origin", "main")
    failed_sha = _git(updater, "rev-parse", "HEAD")

    second = _run_activate(tmp_path, canonical, deploy_exit=7)

    assert second.returncode == 7
    assert failed_sha != active_sha
    assert "synced 1 config files" in second.stdout
    assert _git(active_source, "rev-parse", "HEAD") == active_sha
    assert installed_policy.is_symlink()
    assert os.readlink(installed_policy) == str(prior_target)
    assert installed_policy.read_text(encoding="utf-8") == prior_content
    assert (tmp_path / "deploy-record.txt").read_text(encoding="utf-8").splitlines() == [
        active_sha,
        failed_sha,
    ]
    assert list((tmp_path / "state").glob("launcher-rollback.*")) == []
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["deploy_status"] == "failed"
    assert receipt["source_cutover"]["rollback_status"] == "success"


@pytest.mark.parametrize("command", ["cp", "mv"])
def test_active_config_restore_failure_preserves_destination_and_snapshot(
    tmp_path: Path,
    command: str,
) -> None:
    canonical, origin, active_sha = _make_repos(tmp_path)
    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr
    installed_policy = tmp_path / "home" / ".config" / "hapax" / "usb-topology-policy.json"
    prior_content = installed_policy.read_text(encoding="utf-8")
    candidate_content = '{"known_absences":{"failed_candidate":true}}\n'

    updater = tmp_path / f"updater-config-restore-{command}-failure"
    _git(tmp_path, "clone", str(origin), str(updater))
    _git(updater, "config", "user.email", "source-activate@example.test")
    _git(updater, "config", "user.name", "Source Activate")
    _write(updater / "config" / "usb-topology-policy.json", candidate_content)
    _git(updater, "add", "config/usb-topology-policy.json")
    _git(updater, "commit", "-m", f"change config before {command} restore failure")
    _git(updater, "push", "origin", "main")

    second = _run_activate(
        tmp_path,
        canonical,
        deploy_exit=7,
        env_overrides={
            "PATH": _path_with_failing_config_restore_command(tmp_path, command=command)
        },
    )

    assert second.returncode == 7
    expected_error = (
        "unable to stage saved active config" if command == "cp" else "unable to atomically restore"
    )
    assert expected_error in second.stderr
    assert _git(tmp_path / "active-source", "rev-parse", "HEAD") == active_sha
    assert installed_policy.is_file()
    assert not installed_policy.is_symlink()
    assert installed_policy.read_text(encoding="utf-8") == candidate_content
    snapshots = list((tmp_path / "state").glob("launcher-rollback.*"))
    assert len(snapshots) == 1
    saved = snapshots[0] / "config-present"
    assert saved.is_file()
    assert saved.read_text(encoding="utf-8") == prior_content
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["source_cutover"]["rollback_status"] == "failed"
    assert "config=1" in receipt["source_cutover"]["rollback_message"]


def test_launcher_restore_copy_failure_is_reported_without_removing_destination(
    tmp_path: Path,
) -> None:
    canonical, origin, active_sha = _make_repos(tmp_path)
    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr
    launcher = tmp_path / "home" / ".local" / "bin" / "hapax-post-merge-deploy"
    prior_target = os.readlink(launcher)

    updater = tmp_path / "updater-restore-copy-failure"
    _git(tmp_path, "clone", str(origin), str(updater))
    _git(updater, "config", "user.email", "source-activate@example.test")
    _git(updater, "config", "user.name", "Source Activate")
    _write(
        updater / "scripts" / "hapax-post-merge-deploy",
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            rm -f "$HOME/.local/bin/hapax-post-merge-deploy"
            printf '#!/usr/bin/env bash\necho failed candidate\n' > "$HOME/.local/bin/hapax-post-merge-deploy"
            chmod 0755 "$HOME/.local/bin/hapax-post-merge-deploy"
            exit 7
            """
        ),
        executable=True,
    )
    _git(updater, "add", "scripts/hapax-post-merge-deploy")
    _git(updater, "commit", "-m", "fail after replacing launcher")
    _git(updater, "push", "origin", "main")

    second = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"PATH": _path_with_failing_launcher_cp(tmp_path, phase="restore")},
    )

    assert second.returncode == 7
    assert "unable to stage saved launcher" in second.stderr
    assert _git(tmp_path / "active-source", "rev-parse", "HEAD") == active_sha
    assert launcher.is_file()
    assert not launcher.is_symlink()
    assert "failed candidate" in launcher.read_text(encoding="utf-8")
    snapshots = list((tmp_path / "state").glob("launcher-rollback.*"))
    assert len(snapshots) == 1
    saved = snapshots[0] / "present" / "hapax-post-merge-deploy"
    assert saved.is_symlink()
    assert os.readlink(saved) == prior_target
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["source_cutover"]["rollback_status"] == "failed"
    assert "active runtime restore failed" in receipt["source_cutover"]["rollback_message"]


def test_failed_deploy_after_legacy_worktree_migration_does_not_self_link(
    tmp_path: Path,
) -> None:
    canonical, origin, latest_sha = _make_repos(tmp_path)
    previous_sha = _git(canonical, "rev-parse", "HEAD")
    active_source = tmp_path / "active-source"
    _git(tmp_path, "clone", str(origin), str(active_source))
    _git(active_source, "checkout", "--detach", previous_sha)

    result = _run_activate(tmp_path, canonical, deploy_exit=7)

    assert result.returncode == 7
    assert latest_sha != previous_sha
    assert active_source.is_symlink()
    assert os.readlink(active_source) != str(active_source)
    assert "legacy-worktree-" in os.readlink(active_source)
    assert _git(active_source, "rev-parse", "HEAD") == previous_sha
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["active_source_head"] == previous_sha
    assert receipt["source_cutover"]["rollback_status"] == "success"
    assert "legacy-worktree-" in receipt["source_cutover"]["previous_active_target"]


def test_live_window_defers_cutover_without_manual_signoff(tmp_path: Path) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)
    live_flag = tmp_path / "livestream-active"
    live_flag.write_text("on\n", encoding="utf-8")

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"HAPAX_SOURCE_ACTIVATE_LIVE_FLAG": str(live_flag)},
    )

    assert result.returncode == 0, result.stderr
    assert "unsafe live window is active" in result.stderr
    assert not (tmp_path / "active-source").exists()
    assert not (tmp_path / "deploy-record.txt").exists()
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "held"
    assert receipt["deploy_status"] == "skipped_live_window"
    assert receipt["origin_main_sha"] == new_sha
    assert receipt["active_source_head"] == "unknown"
    assert receipt["candidate_source_path"] == str(tmp_path / "state" / "releases" / new_sha)
    assert receipt["live_window"]["status"] == "active"
    assert "livestream-active" in receipt["live_window"]["message"]


def test_activation_sweeps_cc_task_tools_into_local_bin(tmp_path: Path) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    result = _run_activate(tmp_path, canonical)

    assert result.returncode == 0, result.stderr
    local_bin = tmp_path / "home" / ".local" / "bin"
    active_source = tmp_path / "active-source"
    assert os.readlink(local_bin / "cc-claim") == str(active_source / "scripts" / "cc-claim")
    assert os.readlink(local_bin / "cc-close") == str(active_source / "scripts" / "cc-close")


def test_activation_preserves_release_pinned_regular_launcher(tmp_path: Path) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)
    local_bin = tmp_path / "home" / ".local" / "bin"
    pinned = local_bin / "hapax-post-merge-deploy"
    release_content = (canonical / "scripts" / "hapax-post-merge-deploy").read_text(
        encoding="utf-8"
    )
    _write(pinned, release_content, executable=True)

    result = _run_activate(tmp_path, canonical)

    assert result.returncode == 0, result.stderr
    assert pinned.is_file()
    assert not pinned.is_symlink()
    assert pinned.read_text(encoding="utf-8") == release_content


def test_activation_replaces_stale_or_unowned_regular_launchers(tmp_path: Path) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)
    local_bin = tmp_path / "home" / ".local" / "bin"
    stale = local_bin / "hapax-post-merge-deploy"
    regular_cc_claim = local_bin / "cc-claim"
    _write(stale, "#!/usr/bin/env bash\necho tampered\n", executable=True)
    _write(
        regular_cc_claim,
        (canonical / "scripts" / "cc-claim").read_text(encoding="utf-8"),
        executable=True,
    )

    result = _run_activate(tmp_path, canonical)

    assert result.returncode == 0, result.stderr
    active_source = tmp_path / "active-source"
    assert stale.is_symlink()
    assert os.readlink(stale) == str(active_source / "scripts" / "hapax-post-merge-deploy")
    assert regular_cc_claim.is_symlink()
    assert os.readlink(regular_cc_claim) == str(active_source / "scripts" / "cc-claim")


def test_activation_replaces_hard_linked_release_launcher(tmp_path: Path) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)
    local_bin = tmp_path / "home" / ".local" / "bin"
    launcher = local_bin / "hapax-post-merge-deploy"
    peer = tmp_path / "launcher-peer"
    release_content = (canonical / "scripts" / "hapax-post-merge-deploy").read_text(
        encoding="utf-8"
    )
    _write(peer, release_content, executable=True)
    local_bin.mkdir(parents=True, exist_ok=True)
    os.link(peer, launcher)

    result = _run_activate(tmp_path, canonical)

    assert result.returncode == 0, result.stderr
    active_source = tmp_path / "active-source"
    assert launcher.is_symlink()
    assert os.readlink(launcher) == str(active_source / "scripts" / "hapax-post-merge-deploy")
    assert peer.is_file()
    assert not peer.is_symlink()
    assert peer.read_text(encoding="utf-8") == release_content
    assert peer.stat().st_nlink == 1


def test_activation_syncs_usb_topology_policy_config(tmp_path: Path) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)

    result = _run_activate(tmp_path, canonical)

    assert result.returncode == 0, result.stderr
    installed_policy = tmp_path / "home" / ".config" / "hapax" / "usb-topology-policy.json"
    active_policy = tmp_path / "active-source" / "config" / "usb-topology-policy.json"
    assert installed_policy.read_text(encoding="utf-8") == active_policy.read_text(encoding="utf-8")
    assert not installed_policy.is_symlink()
    assert installed_policy.stat().st_nlink == 1
    assert installed_policy.stat().st_mode & 0o777 == 0o644


def test_activation_normalizes_matching_active_config_aliases(tmp_path: Path) -> None:
    canonical, _origin, new_sha = _make_repos(tmp_path)
    first = _run_activate(tmp_path, canonical)
    assert first.returncode == 0, first.stderr
    installed_policy = tmp_path / "home" / ".config" / "hapax" / "usb-topology-policy.json"
    active_policy = tmp_path / "active-source" / "config" / "usb-topology-policy.json"

    installed_policy.unlink()
    installed_policy.symlink_to(active_policy)
    second = _run_activate(tmp_path, canonical)

    assert second.returncode == 0, second.stderr
    assert not installed_policy.is_symlink()
    assert installed_policy.read_text(encoding="utf-8") == active_policy.read_text(encoding="utf-8")
    assert installed_policy.stat().st_nlink == 1
    assert installed_policy.stat().st_mode & 0o777 == 0o644

    peer = tmp_path / "matching-policy-peer.json"
    peer.write_text(active_policy.read_text(encoding="utf-8"), encoding="utf-8")
    peer.chmod(0o600)
    installed_policy.unlink()
    os.link(peer, installed_policy)
    assert installed_policy.stat().st_nlink == 2
    third = _run_activate(tmp_path, canonical)

    assert third.returncode == 0, third.stderr
    assert not installed_policy.is_symlink()
    assert installed_policy.stat().st_nlink == 1
    assert installed_policy.stat().st_mode & 0o777 == 0o644
    assert peer.stat().st_nlink == 1
    assert peer.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "deploy-record.txt").read_text(encoding="utf-8").splitlines() == [new_sha]


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
        f"{tmp_path / 'state' / 'releases' / latest_sha}|sync --all-extras --quiet"
    ]
    assert (tmp_path / "deploy-record.txt").read_text(encoding="utf-8").splitlines() == [latest_sha]
    receipt = _current_receipt(tmp_path)
    assert receipt["dependency_sync"]["status"] == "success"


def test_activation_records_configured_frame_freshness_probe(tmp_path: Path) -> None:
    canonical, _origin, _new_sha = _make_repos(tmp_path)
    frame = tmp_path / "latest-frame.jpg"
    frame.write_bytes(b"fresh")

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={"HAPAX_SOURCE_ACTIVATE_FRAME_PROBES": str(frame)},
    )

    assert result.returncode == 0, result.stderr
    receipt = _current_receipt(tmp_path)
    assert receipt["health_probes"]["status"] == "success"
    assert f"frame={frame}" in receipt["health_probes"]["message"]


# ----------------------------------------------------------------------
# reform-deploy-chain-repair-20260601: liveness-probe defer (timer re-arm
# safety) + cumulative --since deploy.
# ----------------------------------------------------------------------


def test_http_health_probe_failure_defers_and_exits_zero(tmp_path: Path) -> None:
    """A failing liveness HTTP probe must NOT exit non-zero (which risked
    wedging the re-arming timer — the "died ~09:10 on a health-probe exit-1 and
    never re-armed" failure). It writes a deferred receipt and exits 0; the
    active source is left untouched (no promote, no deploy) and retried next
    cycle."""
    canonical, _origin, _new_sha = _make_repos(tmp_path)
    probe_bin = tmp_path / "probebin"
    probe_bin.mkdir()
    fake_curl = probe_bin / "curl"
    fake_curl.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    fake_curl.chmod(0o755)

    result = _run_activate(
        tmp_path,
        canonical,
        env_overrides={
            "PATH": f"{probe_bin}:{os.environ['PATH']}",
            "HAPAX_SOURCE_ACTIVATE_HTTP_PROBES": "http://127.0.0.1:1/health",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "deferred" in result.stderr.lower()
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "held"
    assert receipt["deploy_status"] == "skipped_health_probe"
    assert receipt["health_probes"]["status"] == "deferred"
    assert not (tmp_path / "deploy-record.txt").exists(), "deferred activation must not deploy"
    assert not (tmp_path / "state" / "last-success-sha").exists()


def test_cumulative_since_passed_when_previous_success_is_ancestor(tmp_path: Path) -> None:
    """The second activation after origin/main advances must deploy the
    CUMULATIVE `--since <previous_success> <origin>` range so intermediate
    merges are not skipped — while the first (no prior success) deploys the
    single tip SHA."""
    canonical, origin, sha1 = _make_repos(tmp_path)
    args_record = tmp_path / "deploy-args.txt"

    first = _run_activate(
        tmp_path, canonical, env_overrides={"HAPAX_FAKE_DEPLOY_ARGS_RECORD": str(args_record)}
    )
    assert first.returncode == 0, first.stderr

    sha2 = _advance_origin(tmp_path, origin, "advance for cumulative")
    assert sha2 != sha1

    second = _run_activate(
        tmp_path, canonical, env_overrides={"HAPAX_FAKE_DEPLOY_ARGS_RECORD": str(args_record)}
    )
    assert second.returncode == 0, second.stderr

    arg_lines = args_record.read_text(encoding="utf-8").splitlines()
    assert arg_lines[0] == sha1, "first activation deploys the single tip SHA"
    assert arg_lines[1] == f"--since {sha1} {sha2}", (
        "second activation deploys the cumulative range"
    )
    # The recorded deploy *target* (last positional arg) stays the plain SHAs.
    assert (tmp_path / "deploy-record.txt").read_text(encoding="utf-8").splitlines() == [sha1, sha2]
    receipt = _current_receipt(tmp_path)
    assert receipt["status"] == "completed"
    assert receipt["origin_main_sha"] == sha2
