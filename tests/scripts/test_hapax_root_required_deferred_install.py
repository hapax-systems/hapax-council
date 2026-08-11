from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-root-required-deferred-install"
PACKAGE = "oom-containment"
MANIFEST = Path("config/root-required/oom-containment.files")
EFFECTS = Path("config/root-required/oom-containment.effects")
INSTALLER = Path("scripts/install-p0-oom-containment")
PAYLOAD = Path("config/root-required/deferred-test-payload")
APCUPSD_PACKAGE = "apcupsd-power-alerts"
APCUPSD_MANIFEST = Path("config/root-required/apcupsd-power-alerts.files")
APCUPSD_EFFECTS = Path("config/root-required/apcupsd-power-alerts.effects")
APCUPSD_INSTALLER = Path("scripts/install-apcupsd-power-alerts")


@dataclass
class DeferredFixture:
    package: str
    manifest: Path
    effects: Path
    installer: Path
    repo: Path
    repo_alias: Path
    state_root: Path
    defer_root: Path
    stage: Path
    receipt: Path
    sudo: Path
    sudo_calls: Path
    installer_marker: Path
    installer_pid_marker: Path
    payload_marker: Path
    runtime_task: Path
    authority_calls: Path
    authority_reject: Path
    cap_reject: Path
    installed_cap_reject: Path
    sha: str
    env: dict[str, str]

    def argv(self, *, expected_sha: str | None = None) -> list[str]:
        return [
            str(SCRIPT),
            "--package",
            self.package,
            "--expected-sha",
            expected_sha or self.sha,
            "--activation-release",
            str(self.repo),
            "--runtime-authority-task",
            str(self.runtime_task),
        ]

    def run(self, *, expected_sha: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.argv(expected_sha=expected_sha),
            text=True,
            capture_output=True,
            check=False,
            env=self.env,
        )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()


def _production_effects(relative_path: Path) -> set[str]:
    return {
        line
        for line in (REPO_ROOT / relative_path).read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }


def test_production_effect_descriptors_match_non_file_mutator_semantics() -> None:
    oom = _production_effects(EFFECTS)
    apcupsd = _production_effects(APCUPSD_EFFECTS)
    oom_descriptor = (REPO_ROOT / EFFECTS).read_text(encoding="utf-8")
    oom_installer = (REPO_ROOT / INSTALLER).read_text(encoding="utf-8")
    apcupsd_installer = (REPO_ROOT / APCUPSD_INSTALLER).read_text(encoding="utf-8")
    shared_state = {
        "runtime:state:lock-root-required",
        "runtime:state:migrate-legacy-root-required",
    }

    for source in (oom_installer, apcupsd_installer):
        assert "ROOT_REQUIRED_LOCK_FILE" in source
        assert "migrate_legacy_root_required_state" in source
    assert shared_state <= oom
    assert shared_state <= apcupsd
    assert "# cap-host=hapax-appendix" in oom_descriptor
    assert "# cap-host-semantics=local-judge cap receipt only" in oom_descriptor
    assert "every listed effect remains runtime-authority-gated" in oom_descriptor
    assert "scrub_generated_memory_property_files" in oom_installer
    assert "scrub_legacy_user_oom_overrides" in oom_installer
    assert {
        "runtime:systemd-system:remove-generated-memory-overrides",
        "runtime:systemd-user:remove-generated-memory-overrides",
    } <= oom
    assert {
        "runtime:docker:update-memory-and-swap:name-prefix:hapax-github-mcp-:nonempty-suffix",
        "runtime:docker:update-memory-and-swap:name:hapax-local-judge",
        "runtime:oom-score:update:user-manager-and-stale-user-floor",
        "runtime:root-directory:ensure-root-0755:/usr/local/share/hapax",
    } <= oom
    assert not any(scope.startswith("runtime:docker:update-memory:") for scope in oom)
    assert not any(
        scope.startswith("runtime:account-file:remove:") and scope.endswith("override.conf")
        for scope in oom
    )
    assert {
        "runtime:systemd-system:enable-now:apcupsd.service",
        "runtime:systemd-system:restart:apcupsd.service",
        "runtime:systemd-system:try-restart:upower.service",
    } <= apcupsd
    assert "enable --now apcupsd.service" in apcupsd_installer
    assert "restart apcupsd.service" in apcupsd_installer
    assert "try-restart upower.service" in apcupsd_installer
    assert "runtime:systemd-system:daemon-reload" not in apcupsd
    assert {
        "runtime:root-directory:ensure-group-write-setgid:/var/log/hapax",
        "runtime:root-file:ensure-owner-mode:/var/log/hapax/ups-power-events.jsonl",
    } <= apcupsd
    assert "runtime:root-file:write:/var/log/hapax/ups-power-events.jsonl" not in apcupsd
    assert "runtime:root-file:write:/usr/local/sbin/hapax-root-required-deploy-audit" not in apcupsd


def test_authenticated_installers_gate_before_receipts_and_deferral_drain() -> None:
    for relative_path in (INSTALLER, APCUPSD_INSTALLER):
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        superseded_gate = source.index("run_authenticated_finalize_gate authority-only")
        superseded_drain = source.index("drain_root_required_deferral", superseded_gate)
        gate = source.rindex('[ "$INSTALL" -eq 0 ] || run_authenticated_finalize_gate')
        receipt = source.rindex('[ "$INSTALL" -eq 0 ] || record_root_required_package_receipt')
        drain = source.rindex('[ "$INSTALL" -eq 0 ] || drain_root_required_deferral')

        assert superseded_gate < superseded_drain
        assert gate < receipt < drain
        assert "installed receipts and deferral state remain unadvanced" in source


def _fixture(tmp_path: Path, *, package: str = PACKAGE) -> DeferredFixture:
    manifest_rel, effects_rel, installer_rel = (
        (MANIFEST, EFFECTS, INSTALLER)
        if package == PACKAGE
        else (APCUPSD_MANIFEST, APCUPSD_EFFECTS, APCUPSD_INSTALLER)
    )
    repo = tmp_path / "activation-release"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@hapax.local")
    _git(repo, "config", "user.name", "Hapax Tests")
    installer_marker = tmp_path / "installer-ran"
    installer_pid_marker = tmp_path / "installer-pid"
    payload_marker = tmp_path / "installer-payload"
    environment_marker = tmp_path / "installer-environment"
    authority_calls = tmp_path / "authority-calls"
    authority_reject = tmp_path / "reject-authority"
    cap_reject = tmp_path / "reject-cap"
    installed_cap_reject = tmp_path / "reject-installed-cap"
    manifest = repo / manifest_rel
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        f"{manifest_rel.as_posix()}\n{effects_rel.as_posix()}\n"
        f"{installer_rel.as_posix()}\n{PAYLOAD.as_posix()}\n",
        encoding="utf-8",
    )
    effects = repo / effects_rel
    effects.parent.mkdir(parents=True, exist_ok=True)
    effects.write_text(
        "# schema=hapax.root-package-effects.v1\n"
        f"# cap-host={'hapax-appendix' if package == PACKAGE else 'none'}\n"
        f"runtime:receipt:advance:{package}\n"
        f"runtime:test:mutate:{package}\n",
        encoding="utf-8",
    )
    payload = repo / PAYLOAD
    payload.parent.mkdir(parents=True, exist_ok=True)
    payload.write_text("authenticated Git payload\n", encoding="utf-8")
    installer = repo / installer_rel
    installer.parent.mkdir(parents=True)
    installer.write_text(
        "#!/usr/bin/bash\n"
        "set -euo pipefail\n"
        '[[ " $* " == *" --authenticated-sealed-source "* ]]\n'
        'IFS=: read -r -a sealed_sources <<< "$HAPAX_ROOT_REQUIRED_SEALED_SOURCE_FDS"\n'
        '[ "${#sealed_sources[@]}" -eq 4 ]\n'
        f"printf '%s\\n' \"$$\" > {installer_pid_marker}\n"
        'if [ -n "${HAPAX_OOM_DEFERRED_TEST_READY:-}" ]; then\n'
        '  touch "$HAPAX_OOM_DEFERRED_TEST_READY"\n'
        '  while [ ! -e "$HAPAX_OOM_DEFERRED_TEST_GO" ]; do sleep 0.01; done\n'
        "fi\n"
        'if [ -n "${HAPAX_OOM_DEFERRED_TEST_REJECT_FINAL_AUTHORITY:-}" ]; then\n'
        '  touch "$HAPAX_OOM_DEFERRED_TEST_REJECT_FINAL_AUTHORITY"\n'
        "fi\n"
        '/usr/bin/env -i HOME="$HOME" PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 '
        '/usr/bin/bash --noprofile --norc -p "$HAPAX_ROOT_REQUIRED_FINALIZE_GATE" '
        '"${HAPAX_OOM_DEFERRED_TEST_FINALIZE_MODE:-full}"\n'
        f'cat "${{sealed_sources[3]}}" > {payload_marker}\n'
        f"printf '%s\\n' \"$HAPAX_ROOT_REQUIRED_PACKAGE_SHA\" > {installer_marker}\n"
        f"/usr/bin/env | /usr/bin/sort > {environment_marker}\n",
        encoding="utf-8",
    )
    installer.chmod(0o755)
    authority = repo / "scripts/hapax-post-merge-deploy"
    authority.write_text(
        "#!/usr/bin/bash\n"
        "set -euo pipefail\n"
        f"printf '%s\\n' \"$*\" >> {authority_calls}\n"
        f'if [ "${{1:-}}" = --verify-runtime-authority-for-release ] && [ -e {authority_reject} ]; then\n'
        "  echo 'runtime authority test rejection' >&2\n"
        "  exit 2\n"
        "fi\n"
        f'if [ "${{1:-}}" = --verify-local-judge-cap-receipt ] && '
        f'[ "${{3:-}}" = applied ] && [ -e {installed_cap_reject} ]; then\n'
        "  echo 'applied cap receipt test rejection' >&2\n"
        "  exit 2\n"
        "fi\n"
        f'if [ "${{1:-}}" = --verify-local-judge-cap-receipt ] && [ -e {cap_reject} ]; then\n'
        "  echo 'cap receipt test rejection' >&2\n"
        "  exit 2\n"
        "fi\n",
        encoding="utf-8",
    )
    authority.chmod(0o755)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "root package")
    sha = _git(repo, "rev-parse", "HEAD")

    repo_alias = tmp_path / "activation-alias"
    repo_alias.symlink_to(repo, target_is_directory=True)
    state_root = tmp_path / "state"
    receipt = state_root / "desired-receipts" / f"{package}.sha"
    receipt.parent.mkdir(parents=True)
    receipt.write_bytes(f"{sha}\n".encode())
    defer_root = tmp_path / "deferred"
    stage = defer_root / sha / package
    for rel in (manifest_rel, effects_rel, installer_rel, PAYLOAD):
        destination = stage / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / rel, destination)
    (stage / ".hapax-root-required-package-sha").write_bytes(f"{sha}\n".encode())
    (stage / "RUNBOOK.txt").write_text("test fixture\n", encoding="utf-8")
    runtime_task = tmp_path / "runtime-cap.md"
    runtime_task.write_text("runtime authority fixture\n", encoding="utf-8")

    sudo_calls = tmp_path / "sudo-calls"
    sudo = tmp_path / "sudo"
    sudo.write_text(
        f"#!/usr/bin/bash\nprintf '%s\\n' \"$*\" >> {sudo_calls}\n",
        encoding="utf-8",
    )
    sudo.chmod(0o755)
    env = {
        **os.environ,
        "HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_TEST_MODE": "1",
        "HAPAX_ROOT_REQUIRED_STATE_ROOT": str(state_root),
        "HAPAX_POST_MERGE_ROOT_DEFER_DIR": str(defer_root),
        "HAPAX_ROOT_REQUIRED_GIT_REPO": str(repo_alias),
        "HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_SUDO": str(sudo),
        "HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_TEST_HOSTNAME": "hapax-podium",
        "BASH_ENV": str(tmp_path / "hostile-bash-env"),
        "GIT_DIR": str(tmp_path / "hostile-git-dir"),
        "GIT_WORK_TREE": str(tmp_path / "hostile-git-work-tree"),
        "GIT_OBJECT_DIRECTORY": str(tmp_path / "hostile-git-objects"),
        "PYTHONPATH": str(tmp_path / "hostile-python-path"),
    }
    return DeferredFixture(
        package=package,
        manifest=manifest_rel,
        effects=effects_rel,
        installer=installer_rel,
        repo=repo,
        repo_alias=repo_alias,
        state_root=state_root,
        defer_root=defer_root,
        stage=stage,
        receipt=receipt,
        sudo=sudo,
        sudo_calls=sudo_calls,
        installer_marker=installer_marker,
        installer_pid_marker=installer_pid_marker,
        payload_marker=payload_marker,
        runtime_task=runtime_task,
        authority_calls=authority_calls,
        authority_reject=authority_reject,
        cap_reject=cap_reject,
        installed_cap_reject=installed_cap_reject,
        sha=sha,
        env=env,
    )


def test_authenticated_deferred_install_executes_git_materialized_installer(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)

    result = fixture.run()

    assert result.returncode == 0, result.stderr
    assert fixture.installer_marker.read_text(encoding="utf-8").strip() == fixture.sha
    assert fixture.sudo_calls.read_text(encoding="utf-8").splitlines() == ["-v"]
    child_environment = (tmp_path / "installer-environment").read_text(encoding="utf-8")
    for unsafe in (
        "BASH_ENV=",
        "GIT_DIR=",
        "GIT_WORK_TREE=",
        "GIT_OBJECT_DIRECTORY=",
        "PYTHONPATH=",
    ):
        assert unsafe not in child_environment
    for safe in (
        "GIT_CONFIG_GLOBAL=/dev/null",
        "GIT_CONFIG_NOSYSTEM=1",
        "GIT_NO_REPLACE_OBJECTS=1",
        "GIT_OPTIONAL_LOCKS=0",
        "HAPAX_APCUPSD_INSTALL_SUDO=",
        "HAPAX_OOM_INSTALL_SUDO=",
        "PYTHONNOUSERSITE=1",
        "PYTHONSAFEPATH=1",
    ):
        assert safe in child_environment
    source_line = next(
        line
        for line in child_environment.splitlines()
        if line.startswith("HAPAX_ROOT_REQUIRED_SEALED_SOURCE_FDS=")
    )
    source_paths = source_line.split("=", 1)[1].split(":")
    assert len(source_paths) == 4
    assert all(path.startswith("/proc/") and "/fd/" in path for path in source_paths)
    assert all(not Path(path).exists() for path in source_paths)
    assert fixture.payload_marker.read_text(encoding="utf-8") == "authenticated Git payload\n"
    assert f"completed authenticated package={fixture.package} sha={fixture.sha}" in result.stdout
    authority_calls = fixture.authority_calls.read_text(encoding="utf-8").splitlines()
    authority_call = (
        f"--verify-runtime-authority-for-release {fixture.sha} {fixture.runtime_task} "
        f"runtime:receipt:advance:{fixture.package} runtime:test:mutate:{fixture.package}"
    )
    assert authority_calls == [authority_call, authority_call, authority_call]
    execution_root = fixture.state_root / ".deferred-install-exec"
    assert not execution_root.exists()


def test_podium_oom_install_keeps_runtime_authority_without_appendix_cap_gate(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    fixture.cap_reject.touch()

    result = fixture.run()

    assert result.returncode == 0, result.stderr
    calls = fixture.authority_calls.read_text(encoding="utf-8").splitlines()
    assert len([call for call in calls if call.startswith("--verify-runtime-authority")]) == 3
    assert not any(call.startswith("--verify-local-judge-cap-receipt") for call in calls)


def test_apcupsd_deferral_uses_the_same_authenticated_entrypoint(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, package=APCUPSD_PACKAGE)

    result = fixture.run()

    assert result.returncode == 0, result.stderr
    assert fixture.installer_marker.read_text(encoding="utf-8").strip() == fixture.sha


def test_runtime_authority_task_is_required_by_the_authenticated_mutator(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    argv = fixture.argv()
    task_index = argv.index("--runtime-authority-task")
    del argv[task_index : task_index + 2]

    result = subprocess.run(
        argv,
        text=True,
        capture_output=True,
        check=False,
        env=fixture.env,
    )

    assert result.returncode == 2
    assert "--runtime-authority-task" in result.stderr
    assert "next action:" in result.stderr
    assert not fixture.sudo_calls.exists()
    assert not fixture.installer_marker.exists()


def test_isolated_test_mode_refuses_the_real_sudo_boundary(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture.env["HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_SUDO"] = "/usr/bin/sudo"

    result = fixture.run()

    assert result.returncode == 1
    assert "never /usr/bin/sudo" in result.stderr
    assert not fixture.authority_calls.exists()
    assert not fixture.installer_pid_marker.exists()


def test_runtime_authority_rejection_stops_before_sudo_or_installer(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture.authority_reject.touch()

    result = fixture.run()

    assert result.returncode == 1
    assert "exact runtime gate --verify-runtime-authority-for-release rejected" in result.stderr
    assert "runtime authority test rejection" in result.stderr
    assert not fixture.sudo_calls.exists()
    assert not fixture.installer_marker.exists()


def test_appendix_oom_install_requires_candidate_cap_receipt_before_sudo(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    fixture.env["HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_TEST_HOSTNAME"] = "hapax-appendix"

    result = fixture.run()

    assert result.returncode == 1
    assert "local-judge cap receipt" in result.stderr
    assert not fixture.sudo_calls.exists()
    assert not fixture.installer_marker.exists()


def test_appendix_oom_install_revalidates_cap_receipt_before_mutation(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    fixture.env["HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_TEST_HOSTNAME"] = "hapax-appendix"
    cap_receipt = fixture.state_root / "local-judge-cap-canary" / f"{fixture.sha}.env"
    cap_receipt.parent.mkdir()
    cap_receipt.write_text("schema=1\n", encoding="utf-8")
    cap_receipt.chmod(0o600)

    result = fixture.run()

    assert result.returncode == 0, result.stderr
    calls = fixture.authority_calls.read_text(encoding="utf-8").splitlines()
    assert [line for line in calls if line.startswith("--verify-local-judge-cap-receipt")] == [
        f"--verify-local-judge-cap-receipt {fixture.sha} candidate",
        f"--verify-local-judge-cap-receipt {fixture.sha} candidate",
        f"--verify-local-judge-cap-receipt {fixture.sha} applied",
    ]


def test_appendix_oom_install_requires_applied_cap_acceptance_before_finalization(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    fixture.env["HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_TEST_HOSTNAME"] = "hapax-appendix"
    cap_receipt = fixture.state_root / "local-judge-cap-canary" / f"{fixture.sha}.env"
    cap_receipt.parent.mkdir()
    cap_receipt.write_text("schema=1\n", encoding="utf-8")
    cap_receipt.chmod(0o600)
    fixture.installed_cap_reject.touch()

    result = fixture.run()

    assert result.returncode == 2
    assert fixture.installer_pid_marker.exists()
    assert not fixture.installer_marker.exists()
    assert "applied cap receipt test rejection" in result.stderr
    assert "completed authenticated" not in result.stdout
    assert (fixture.stage / "RUNBOOK.txt").is_file()
    assert not (fixture.state_root / "installed-receipts" / f"{fixture.package}.sha").exists()


def test_superseded_authority_only_finalization_rejects_revoked_task_before_completion(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    fixture.env["HAPAX_OOM_DEFERRED_TEST_FINALIZE_MODE"] = "authority-only"
    fixture.env["HAPAX_OOM_DEFERRED_TEST_REJECT_FINAL_AUTHORITY"] = str(fixture.authority_reject)

    result = fixture.run()

    assert result.returncode == 2
    assert "runtime authority test rejection" in result.stderr
    assert fixture.installer_pid_marker.exists()
    assert not fixture.installer_marker.exists()
    assert (fixture.stage / "RUNBOOK.txt").is_file()
    authority_calls = fixture.authority_calls.read_text(encoding="utf-8").splitlines()
    assert (
        len(
            [
                call
                for call in authority_calls
                if call.startswith("--verify-runtime-authority-for-release")
            ]
        )
        == 3
    )


def test_superseded_authority_only_finalization_skips_obsolete_applied_cap(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    fixture.env["HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_TEST_HOSTNAME"] = "hapax-appendix"
    fixture.env["HAPAX_OOM_DEFERRED_TEST_FINALIZE_MODE"] = "authority-only"
    cap_receipt = fixture.state_root / "local-judge-cap-canary" / f"{fixture.sha}.env"
    cap_receipt.parent.mkdir()
    cap_receipt.write_text("schema=1\n", encoding="utf-8")
    cap_receipt.chmod(0o600)
    fixture.installed_cap_reject.touch()

    result = fixture.run()

    assert result.returncode == 0, result.stderr
    cap_calls = [
        call
        for call in fixture.authority_calls.read_text(encoding="utf-8").splitlines()
        if call.startswith("--verify-local-judge-cap-receipt")
    ]
    assert cap_calls == [
        f"--verify-local-judge-cap-receipt {fixture.sha} candidate",
        f"--verify-local-judge-cap-receipt {fixture.sha} candidate",
    ]


def test_runtime_task_change_during_sudo_warmup_refuses_installer(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    hook = _hook(
        tmp_path / "change-runtime-task",
        f"printf '%s\\n' changed > {fixture.runtime_task}",
    )
    fixture.env["HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_AFTER_SUDO_HOOK"] = str(hook)

    result = fixture.run()

    assert result.returncode == 1
    assert "runtime authority task or cap receipt changed during sudo warmup" in result.stderr
    assert fixture.sudo_calls.exists()
    assert not fixture.installer_marker.exists()


def test_expected_sha_mismatch_refuses_before_sudo(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    result = fixture.run(expected_sha="f" * 40)

    assert result.returncode == 1
    assert "desired package receipt changed" in result.stderr
    assert not fixture.sudo_calls.exists()
    assert not fixture.installer_marker.exists()


def test_test_selector_is_refused_without_isolated_test_mode(tmp_path: Path) -> None:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("HAPAX_ROOT_REQUIRED_") and key != "HAPAX_POST_MERGE_ROOT_DEFER_DIR"
    }
    env["HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_SUDO"] = "/bin/true"

    result = subprocess.run(
        [
            str(SCRIPT),
            "--package",
            PACKAGE,
            "--expected-sha",
            "f" * 40,
            "--activation-release",
            str(tmp_path),
            "--runtime-authority-task",
            str(tmp_path / "runtime-task.md"),
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "test selectors are refused outside isolated test mode" in result.stderr


def test_cli_parse_failures_include_an_actionable_next_step() -> None:
    result = subprocess.run(
        [str(SCRIPT), "--package", "unknown"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "next action:" in result.stderr
    assert f"rerun {SCRIPT.name} --help" in result.stderr


@pytest.mark.parametrize(
    "content",
    [
        b"../outside\n",
        b"A" * 40 + b"\n",
        b"a" * 39 + b"\n",
        b"a" * 41 + b"\n",
        b"a" * 20 + b" " + b"a" * 20 + b"\n",
        b"a" * 40 + b"\n" + b"b" * 40 + b"\n",
        b"a" * 40,
        b"a" * 20 + b"\x00" + b"a" * 19 + b"\n",
    ],
)
def test_malformed_receipt_refuses_before_sudo_or_execution(tmp_path: Path, content: bytes) -> None:
    fixture = _fixture(tmp_path)
    fixture.receipt.write_bytes(content)

    result = fixture.run()

    assert result.returncode == 1
    assert "exactly 40 lowercase hex characters and one newline" in result.stderr
    assert not fixture.sudo_calls.exists()
    assert not fixture.installer_marker.exists()


def test_symlinked_receipt_refuses_before_sudo(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    target = tmp_path / "receipt-target"
    target.write_bytes(f"{fixture.sha}\n".encode())
    fixture.receipt.unlink()
    fixture.receipt.symlink_to(target)

    result = fixture.run()

    assert result.returncode == 1
    assert "single-link non-symlink regular file" in result.stderr
    assert not fixture.sudo_calls.exists()


@pytest.mark.parametrize("component", ["sha", "package", "installer"])
def test_symlinked_stage_component_refuses_before_sudo(tmp_path: Path, component: str) -> None:
    fixture = _fixture(tmp_path)
    if component == "sha":
        target = tmp_path / "sha-target"
        shutil.move(fixture.stage.parent, target)
        fixture.stage.parent.symlink_to(target, target_is_directory=True)
    elif component == "package":
        target = tmp_path / "package-target"
        shutil.move(fixture.stage, target)
        fixture.stage.symlink_to(target, target_is_directory=True)
    else:
        installer = fixture.stage / INSTALLER
        target = tmp_path / "installer-target"
        shutil.move(installer, target)
        installer.symlink_to(target)

    result = fixture.run()

    assert result.returncode == 1
    assert not fixture.sudo_calls.exists()
    assert not fixture.installer_marker.exists()


def test_substituted_staged_installer_never_executes(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    attack_marker = tmp_path / "substituted-installer-ran"
    staged_installer = fixture.stage / INSTALLER
    staged_installer.write_text(f"#!/usr/bin/bash\ntouch {attack_marker}\n", encoding="utf-8")
    staged_installer.chmod(0o755)

    result = fixture.run()

    assert result.returncode == 1
    assert "staged package bytes do not match" in result.stderr
    assert not fixture.sudo_calls.exists()
    assert not attack_marker.exists()
    assert not fixture.installer_marker.exists()


def test_git_replace_ref_cannot_substitute_receipt_commit(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    attack_marker = tmp_path / "replacement-installer-ran"
    replacement_installer = fixture.repo / fixture.installer
    replacement_installer.write_text(f"#!/usr/bin/bash\ntouch {attack_marker}\n", encoding="utf-8")
    replacement_installer.chmod(0o755)
    _git(fixture.repo, "add", fixture.installer.as_posix())
    _git(fixture.repo, "commit", "-qm", "replacement package")
    replacement_sha = _git(fixture.repo, "rev-parse", "HEAD")
    _git(fixture.repo, "replace", fixture.sha, replacement_sha)
    shutil.copy2(replacement_installer, fixture.stage / fixture.installer)

    result = fixture.run()

    assert result.returncode == 1
    assert "staged package bytes do not match" in result.stderr
    assert not fixture.sudo_calls.exists()
    assert not attack_marker.exists()
    assert not fixture.installer_marker.exists()


def _hook(path: Path, body: str) -> Path:
    path.write_text(f"#!/usr/bin/bash\nset -euo pipefail\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_receipt_change_during_sudo_warmup_refuses_execution(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    hook = _hook(
        tmp_path / "swap-receipt",
        f"printf '%s\\n' {'b' * 40} > {fixture.receipt}",
    )
    fixture.env["HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_AFTER_SUDO_HOOK"] = str(hook)

    result = fixture.run()

    assert result.returncode == 1
    assert "receipt changed during sudo warmup" in result.stderr
    assert fixture.sudo_calls.exists()
    assert not fixture.installer_marker.exists()


def test_stage_change_during_sudo_warmup_refuses_execution(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    hook = _hook(
        tmp_path / "swap-stage",
        f"printf '%s\\n' '#!/usr/bin/bash' 'exit 0' > {fixture.stage / INSTALLER}",
    )
    fixture.env["HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_AFTER_SUDO_HOOK"] = str(hook)

    result = fixture.run()

    assert result.returncode == 1
    assert "staged package bytes do not match" in result.stderr
    assert not fixture.installer_marker.exists()


def test_stage_replacement_after_final_validation_cannot_change_consumed_bytes(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    ready = tmp_path / "installer-ready"
    go = tmp_path / "installer-go"
    fixture.env["HAPAX_OOM_DEFERRED_TEST_READY"] = str(ready)
    fixture.env["HAPAX_OOM_DEFERRED_TEST_GO"] = str(go)
    process = subprocess.Popen(
        fixture.argv(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=fixture.env,
    )
    for _ in range(500):
        if ready.exists() or process.poll() is not None:
            break
        time.sleep(0.01)
    assert ready.exists(), process.communicate(timeout=5)
    (fixture.stage / PAYLOAD).write_text("substituted staged payload\n", encoding="utf-8")
    go.touch()
    stdout, stderr = process.communicate(timeout=10)

    assert process.returncode == 0, stderr
    assert "completed authenticated" in stdout
    assert fixture.payload_marker.read_text(encoding="utf-8") == "authenticated Git payload\n"


def test_installer_dies_if_the_descriptor_holding_helper_dies(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    ready = tmp_path / "installer-ready"
    go = tmp_path / "installer-go"
    fixture.env["HAPAX_OOM_DEFERRED_TEST_READY"] = str(ready)
    fixture.env["HAPAX_OOM_DEFERRED_TEST_GO"] = str(go)
    process = subprocess.Popen(
        fixture.argv(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=fixture.env,
    )
    child_pid = 0
    try:
        for _ in range(500):
            if ready.exists() or process.poll() is not None:
                break
            time.sleep(0.01)
        assert ready.exists(), process.communicate(timeout=5)
        child_pid = int(fixture.installer_pid_marker.read_text(encoding="utf-8"))
        process.kill()
        process.wait(timeout=5)
        for _ in range(200):
            if not Path(f"/proc/{child_pid}").exists():
                break
            time.sleep(0.01)
        assert not Path(f"/proc/{child_pid}").exists()
        assert not fixture.installer_marker.exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if child_pid and Path(f"/proc/{child_pid}").exists():
            os.kill(child_pid, signal.SIGKILL)


def test_activation_alias_swap_cannot_change_pinned_release(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    replacement = tmp_path / "replacement-release"
    shutil.copytree(fixture.repo, replacement)
    hook = _hook(
        tmp_path / "swap-alias",
        f"rm {fixture.repo_alias}\nln -s {replacement} {fixture.repo_alias}",
    )
    fixture.env["HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_AFTER_SUDO_HOOK"] = str(hook)

    result = fixture.run()

    assert result.returncode == 0, result.stderr
    assert fixture.installer_marker.exists()


def test_missing_explicit_test_defer_root_cannot_self_anchor_to_drain(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    fixture.env.pop("HAPAX_POST_MERGE_ROOT_DEFER_DIR")
    fixture.env["HAPAX_ROOT_REQUIRED_DRAIN_DIR"] = str(fixture.stage)

    result = fixture.run()

    assert result.returncode == 1
    assert "HAPAX_POST_MERGE_ROOT_DEFER_DIR must be an explicit absolute test path" in result.stderr
    assert not fixture.sudo_calls.exists()
