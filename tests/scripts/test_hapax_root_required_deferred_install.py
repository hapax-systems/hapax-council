from __future__ import annotations

import ctypes
import fcntl
import hashlib
import importlib.machinery
import importlib.util
import os
import pwd
import re
import shutil
import signal
import stat
import subprocess
import sys
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
AUTHORITY_VERIFIER = Path("scripts/hapax-post-merge-deploy")
SHARED_INSTALLER_CONTROL_RATIONALES = {
    "HAPAX_LOCAL_JUDGE_CAP_RECEIPT_SHA256": (
        "required helper field: empty off the cap host, exact digest rechecked on appendix"
    ),
    "HAPAX_POST_MERGE_ROOT_DEFER_DIR": "helper-selected canonical deferral root",
    "HAPAX_ROOT_REQUIRED_ALLOW_UNAUTHENTICATED_TEST_INSTALL": "isolated-test admission",
    "HAPAX_ROOT_REQUIRED_DESIRED_RECEIPT_ROOT": "stable state child",
    "HAPAX_ROOT_REQUIRED_DRAIN_DIR": "exact helper-selected package stage",
    "HAPAX_ROOT_REQUIRED_FINALIZE_GATE": "retired protocol input retained for refusal",
    "HAPAX_ROOT_REQUIRED_GENERATION_GUARD_FD": "host-wide generation lock descriptor",
    "HAPAX_ROOT_REQUIRED_GIT_REPO": "exact activation release",
    "HAPAX_ROOT_REQUIRED_INSTALLED_RECEIPT_ROOT": "stable state child",
    "HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT": "stable state child",
    "HAPAX_ROOT_REQUIRED_INSTALLER_TEST_MODE": "helper-selected isolated-test branch",
    "HAPAX_ROOT_REQUIRED_INSTALLER_TEST_ROOT": "helper-confined scratch root",
    "HAPAX_ROOT_REQUIRED_LOCK_FD": "inherited package lock descriptor",
    "HAPAX_ROOT_REQUIRED_LOCK_FILE": "lexical package lock path",
    "HAPAX_ROOT_REQUIRED_LOCK_HELD": "retired re-exec marker scrubbed by lock bootstrap",
    "HAPAX_ROOT_REQUIRED_LOCK_LEXICAL_PATH": "inherited lock identity witness",
    "HAPAX_ROOT_REQUIRED_LOCK_MODE": "inherited lock exclusivity witness",
    "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": "exact package generation",
    "HAPAX_ROOT_REQUIRED_SEALED_SOURCE_FDS": "exact Git package sources",
    "HAPAX_ROOT_REQUIRED_STATE_FD": "stable state-generation descriptor",
    "HAPAX_ROOT_REQUIRED_STATE_LEXICAL_ROOT": "state-generation identity witness",
    "HAPAX_ROOT_REQUIRED_STATE_ROOT": "stable state-generation path",
    "HAPAX_ROOT_REQUIRED_UNAUTHENTICATED_TEST_ROOT": "legacy isolated-test confinement",
    "HAPAX_RUNTIME_AUTHORITY_TASK": "semantic runtime-authority input",
    "HAPAX_RUNTIME_AUTHORITY_TASK_SHA256": "helper-bound authority snapshot",
}
LEGACY_OOM_EFFECT_SELECTORS = {
    "HAPAX_ROOT_FAILURE_INTAKE_DEST",
    "HAPAX_ROOT_REQUIRED_AUDIT_DEST",
}


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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _production_effects(relative_path: Path) -> set[str]:
    return {
        line
        for line in (REPO_ROOT / relative_path).read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }


def _shell_array_names(source: str, name: str) -> tuple[str, ...]:
    match = re.search(rf"readonly -a {name}=\(\n(?P<body>(?:    [A-Z][A-Z0-9_]*\n)*)\)", source)
    assert match is not None
    names = tuple(line.strip() for line in match.group("body").splitlines() if line.strip())
    assert all(re.fullmatch(r"[A-Z][A-Z0-9_]*", item) for item in names)
    return names


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
        superseded_call = (
            "run_authenticated_authority_gate authority-only"
            if relative_path == INSTALLER
            else "run_authenticated_authority_gate"
        )
        superseded_gate = source.index(superseded_call, source.index("SKIP_SUPERSEDED_INSTALL"))
        superseded_drain = source.index("drain_root_required_deferral", superseded_gate)
        final_block = source[source.rindex('if [ "$INSTALL" -ne 0 ]; then') :]
        final_gate_call = (
            "run_authenticated_authority_gate applied"
            if relative_path == INSTALLER
            else "run_authenticated_authority_gate"
        )
        gate = final_block.index(final_gate_call)
        snapshot = final_block.index("record_installed_source", gate)
        receipt = final_block.index("record_root_required_package_receipt", snapshot)
        drain = final_block.index("drain_root_required_deferral", receipt)

        assert superseded_gate < superseded_drain
        assert gate < snapshot < receipt < drain
        assert "no further effect or receipt advancement is permitted" in source
        main = source[source.rindex("\nload_authenticated_sealed_sources\n") :]
        initial_gate = main.index(superseded_call)
        migration = main.index("migrate_legacy_root_required_state", initial_gate)
        assert initial_gate < migration


@pytest.mark.parametrize(
    ("installer_rel", "selector_prefixes", "legacy_effect_selectors"),
    (
        (INSTALLER, ("HAPAX_OOM_",), LEGACY_OOM_EFFECT_SELECTORS),
        (APCUPSD_INSTALLER, ("HAPAX_APCUPSD_", "HAPAX_UPS_", "HAPAX_UPOWER_"), set()),
    ),
)
def test_every_installer_environment_name_has_one_authenticated_boundary_classification(
    installer_rel: Path,
    selector_prefixes: tuple[str, ...],
    legacy_effect_selectors: set[str],
) -> None:
    source = (REPO_ROOT / installer_rel).read_text(encoding="utf-8")
    mentioned = set(re.findall(r"\bHAPAX_[A-Z0-9_]*[A-Z0-9]\b", source))
    package_selectors = {
        name for name in mentioned if any(name.startswith(prefix) for prefix in selector_prefixes)
    }
    classes = (package_selectors, set(SHARED_INSTALLER_CONTROL_RATIONALES), legacy_effect_selectors)
    invalid_class_counts = {
        name: sum(name in boundary_class for boundary_class in classes)
        for name in mentioned
        if sum(name in boundary_class for boundary_class in classes) != 1
    }
    indirect_expansions = set(re.findall(r"\$\{!([^}]+)\}", source))
    assert invalid_class_counts == {}
    assert mentioned & LEGACY_OOM_EFFECT_SELECTORS == legacy_effect_selectors
    assert all(reason.strip() for reason in SHARED_INSTALLER_CONTROL_RATIONALES.values())
    assert re.findall(r"HAPAX_(?=[$\"'{])", source) == []
    assert indirect_expansions - {"package_files[@]"} == set()
    assert re.search(r"\b(?:eval|(?:declare|local)\s+-n|printf\s+-v)\b", source) is None
    assert "AUTHENTICATED_PRODUCTION_REQUIRED_ENV_NAMES" not in source
    assert "AUTHENTICATED_PRODUCTION_OPTIONAL_ENV_NAMES" not in source
    assert "mapfile -d '' -t AUTHENTICATED_PRODUCTION_RAW_ENVIRONMENT" not in source
    assert '"/proc/$$/environ"' not in source
    assert "compgen -e" not in source
    source_guard = source.index("must be executed, not sourced")
    privileged_guard = source.index("requires Bash privileged mode")
    option_enable = source.index("set -euo pipefail")
    root_derivation = source.index('ROOT="$(cd')
    production_refusal = source.index("installation is disabled until")
    assert source_guard < privileged_guard < option_enable
    assert "BASH_LINENO[0]" in source[:option_enable]
    assert "moving it into an if condition suppresses errexit" in source[:option_enable]
    assert option_enable < production_refusal < root_derivation
    assert re.search(r"\$\((?!\()", source[option_enable:production_refusal]) is None
    assert "done < /proc/self/status" in source[:root_derivation]
    assert "done < /proc/self/uid_map" in source[:root_derivation]
    assert "done < /proc/self/gid_map" in source[:root_derivation]
    assert "mapfile -t _self_mountinfo < /proc/self/mountinfo" in source[:root_derivation]
    assert "mapfile -t _init_mountinfo < /proc/1/mountinfo" in source[:root_derivation]
    assert '"$_mountinfo_equal" -ne 1' in source[:root_derivation]
    assert "compgen -A variable" not in source[:root_derivation]
    assert 'unset "$_environment_name"' not in source
    assert (
        re.search(
            r"(?m)^\s*(?:export(?:\s|$)|(?:declare|local|typeset)\s+-[A-Za-z]*x|"
            r"set\s+(?:-a|-o\s+allexport)(?:\s|$))",
            source,
        )
        is None
    )
    if installer_rel == INSTALLER:
        production = source[source.rindex("\nload_authenticated_sealed_sources\n") :]
        assert (
            production.index("load_host_policy")
            < production.index("validate_authenticated_cap_environment_for_host")
            < production.index("run_authenticated_authority_gate authority-only")
        )


def _sealed_memfd(name: str, data: bytes, *, executable: bool = False) -> int:
    if hasattr(os, "memfd_create"):
        fd = os.memfd_create(name, os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    else:
        libc = ctypes.CDLL(None, use_errno=True)
        fd = libc.memfd_create(name.encode(), 0x0001 | 0x0002)
        if fd < 0:
            raise OSError(ctypes.get_errno(), f"memfd_create failed for {name}")
    os.write(fd, data)
    os.fchmod(fd, 0o755 if executable else 0o644)
    os.lseek(fd, 0, os.SEEK_SET)
    fcntl.fcntl(
        fd,
        getattr(fcntl, "F_ADD_SEALS", 1033),
        getattr(fcntl, "F_SEAL_SEAL", 0x0001)
        | getattr(fcntl, "F_SEAL_SHRINK", 0x0002)
        | getattr(fcntl, "F_SEAL_GROW", 0x0004)
        | getattr(fcntl, "F_SEAL_WRITE", 0x0008),
    )
    return fd


def _installer_function(relative: Path, name: str, next_name: str) -> str:
    source = (REPO_ROOT / relative).read_text(encoding="utf-8")
    start = source.index(f"{name}() {{")
    end = source.index(f"\n{next_name}() {{", start)
    return source[start:end]


@pytest.mark.parametrize(
    ("installer_rel", "label"),
    ((INSTALLER, "OOM"), (APCUPSD_INSTALLER, "apcupsd")),
)
def test_authenticated_source_loader_rejects_foreign_holder_fd_paths(
    installer_rel: Path,
    label: str,
) -> None:
    source_fd = _sealed_memfd("hapax-foreign-holder-source", b"package source\n")
    foreign_path = f"/proc/{os.getpid()}/fd/{source_fd}"
    loader = _installer_function(
        installer_rel,
        "load_authenticated_sealed_sources",
        "bind_authenticated_release_root"
        if installer_rel == INSTALLER
        else "run_authenticated_authority_gate",
    )
    command = (
        "set -uo pipefail\n"
        "AUTHENTICATED_SEALED_SOURCE=1\n"
        "INSTALL=1\n"
        "ROOT_REQUIRED_LEGACY_FINALIZE_GATE=\n"
        f"ROOT_REQUIRED_SEALED_SOURCE_FDS={foreign_path!s}\n"
        f"ROOT_REQUIRED_PACKAGE_SHA={'a' * 40}\n"
        "RUNTIME_AUTHORITY_TASK=/governed/runtime-authority.md\n"
        f"RUNTIME_AUTHORITY_TASK_SHA256={'b' * 64}\n"
        "LOCAL_JUDGE_CAP_RECEIPT_SHA256=\n"
        "package_files=(payload)\n"
        "declare -A ROOT_REQUIRED_SEALED_SOURCES=()\n"
        f"{loader}\n"
        "load_authenticated_sealed_sources\n"
    )
    try:
        result = subprocess.run(
            ["/usr/bin/bash", "--noprofile", "--norc", "-p", "-c", command],
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        os.close(source_fd)

    assert result.returncode != 0
    assert f"authenticated {label} source descriptors are unavailable" in result.stderr
    assert "next action:" in result.stderr


@pytest.mark.parametrize(
    ("installer_rel", "label"),
    ((INSTALLER, "OOM"), (APCUPSD_INSTALLER, "apcupsd")),
)
def test_package_source_comparison_observes_git_blob_materialization_failure(
    tmp_path: Path,
    installer_rel: Path,
    label: str,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@hapax.local")
    _git(repo, "config", "user.name", "Hapax Tests")
    payload = repo / "payload"
    payload.write_bytes(b"")
    payload.chmod(0o755)
    _git(repo, "add", "payload")
    _git(repo, "commit", "-qm", "empty executable payload")
    sha = _git(repo, "rev-parse", "HEAD")
    blob = _git(repo, "rev-parse", "HEAD:payload")
    loose_object = repo / ".git" / "objects" / blob[:2] / blob[2:]
    assert loose_object.is_file()
    loose_object.unlink()

    source_fd = _sealed_memfd("hapax-empty-executable", b"", executable=True)
    validator = _installer_function(
        installer_rel,
        "validate_package_source_matches_commit",
        "validate_no_unhandled_package_removals",
    )
    command = (
        "set -uo pipefail\n"
        f"ROOT_REQUIRED_GIT_REPO={repo!s}\n"
        f"ROOT_REQUIRED_PACKAGE_SHA={sha}\n"
        "AUTHENTICATED_SEALED_SOURCE=1\n"
        "package_files=(payload)\n"
        f"SOURCE_FD={source_fd}\n"
        'git() { /usr/bin/git "$@"; }\n'
        "src_path() { printf '/proc/self/fd/%s\\n' \"$SOURCE_FD\"; }\n"
        "expected_package_git_mode() { printf '%s\\n' 100755; }\n"
        f"{validator}\n"
        "validate_package_source_matches_commit\n"
    )
    try:
        result = subprocess.run(
            ["/usr/bin/bash", "--noprofile", "--norc", "-p", "-c", command],
            pass_fds=(source_fd,),
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        os.close(source_fd)

    assert result.returncode != 0
    assert f"{label} install source does not match claimed commit" in result.stderr
    assert "next action:" in result.stderr


@pytest.mark.parametrize(
    ("installer_rel", "manifest_rel", "prefix"),
    (
        (INSTALLER, MANIFEST, "HAPAX_OOM"),
        (APCUPSD_INSTALLER, APCUPSD_MANIFEST, "HAPAX_APCUPSD"),
    ),
)
def test_direct_authenticated_protocol_rejects_same_uid_arbitrary_finalizer(
    tmp_path: Path,
    installer_rel: Path,
    manifest_rel: Path,
    prefix: str,
) -> None:
    package_files = [
        line
        for line in (REPO_ROOT / manifest_rel).read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    source_fds = [
        _sealed_memfd(
            f"hapax-forged-source-{index}",
            (REPO_ROOT / relative).read_bytes(),
            executable=relative.startswith("scripts/"),
        )
        for index, relative in enumerate(package_files)
    ]
    finalizer_fd = _sealed_memfd(
        "hapax-root-finalize-gate-forged",
        b"#!/usr/bin/bash\nexit 0\n",
        executable=True,
    )
    runtime_task = tmp_path / "runtime-authority.md"
    runtime_task.write_text("forged direct protocol fixture\n", encoding="utf-8")
    account = pwd.getpwuid(os.getuid())
    env = {
        **os.environ,
        "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": "a" * 40,
        "HAPAX_ROOT_REQUIRED_SEALED_SOURCE_FDS": ":".join(
            f"/proc/{os.getpid()}/fd/{fd}" for fd in source_fds
        ),
        "HAPAX_ROOT_REQUIRED_FINALIZE_GATE": f"/proc/{os.getpid()}/fd/{finalizer_fd}",
        "HAPAX_RUNTIME_AUTHORITY_TASK": str(runtime_task),
        "HAPAX_ROOT_REQUIRED_STATE_ROOT": str(tmp_path / "state"),
        "HAPAX_POST_MERGE_ROOT_DEFER_DIR": str(tmp_path / "deferred"),
        f"{prefix}_TARGET_UID": str(os.getuid()),
        f"{prefix}_TARGET_HOME": str(tmp_path / "home"),
        f"{prefix}_INSTALL_SUDO": "",
    }
    if prefix == "HAPAX_OOM":
        env["HAPAX_OOM_TARGET_USER"] = account.pw_name
        env["HAPAX_OOM_TARGET_GID"] = str(os.getgid())
        env["HAPAX_OOM_EFFECTIVE_UID"] = str(os.getuid())
    else:
        env["HAPAX_APCUPSD_TARGET_GID"] = str(os.getgid())
    try:
        result = subprocess.run(
            [
                str(REPO_ROOT / installer_rel),
                "--source",
                str(REPO_ROOT),
                "--authenticated-sealed-source",
                "--install",
            ],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
    finally:
        os.close(finalizer_fd)
        for fd in source_fds:
            os.close(fd)

    assert result.returncode != 0
    assert "production" in result.stderr and "disabled" in result.stderr
    assert "no Bash installer effect or receipt advancement is permitted" in result.stderr
    assert "next action:" in result.stderr
    assert not (tmp_path / "state").exists()


@pytest.mark.parametrize(
    ("installer_rel", "prefix", "package"),
    (
        (INSTALLER, "HAPAX_OOM", "oom-containment"),
        (APCUPSD_INSTALLER, "HAPAX_APCUPSD", "apcupsd-power-alerts"),
    ),
)
@pytest.mark.parametrize("source_kind", ("tracked", "copied", "sealed-memfd"))
@pytest.mark.parametrize("hostile_wrapper", (False, True), ids=("direct", "hostile-wrapper"))
def test_test_mode_sudo_selector_refuses_before_any_interpreted_effect(
    tmp_path: Path,
    installer_rel: Path,
    prefix: str,
    package: str,
    source_kind: str,
    hostile_wrapper: bool,
) -> None:
    isolated_root = tmp_path / "isolated"
    isolated_root.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    sudo_calls = outside / "sudo-calls"
    fake_sudo = outside / "sudo-recorder"
    fake_sudo.write_text(
        f'#!/usr/bin/bash\n/usr/bin/touch {sudo_calls}\nexec "$@"\n', encoding="utf-8"
    )
    fake_sudo.chmod(0o755)
    mutator_marker = isolated_root / "mutator-ran"
    fake_bin = isolated_root / "bin"
    fake_bin.mkdir()
    for name in ("dirname", "systemctl", "busctl", "apcaccess"):
        executable = fake_bin / name
        executable.write_text(
            f"#!/usr/bin/bash\n/usr/bin/touch {mutator_marker}\nexit 0\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
    bash_env = isolated_root / "bash-env"
    bash_env.write_text(f"/usr/bin/touch {mutator_marker}\n", encoding="utf-8")

    source_fd = -1
    if source_kind == "tracked":
        installer = REPO_ROOT / installer_rel
    elif source_kind == "copied":
        installer = isolated_root / installer_rel.name
        installer.write_bytes((REPO_ROOT / installer_rel).read_bytes())
        installer.chmod(0o755)
    else:
        source_fd = _sealed_memfd(
            f"hapax-caller-installer-{package}",
            (REPO_ROOT / installer_rel).read_bytes(),
            executable=True,
        )
        installer = Path(f"/proc/self/fd/{source_fd}")

    state_root = isolated_root / "state"
    defer_root = isolated_root / "deferred"
    arguments = [
        str(installer),
        "--source",
        str(REPO_ROOT),
        "--authenticated-sealed-source",
        "--install",
        "--verify-live",
    ]
    if hostile_wrapper:
        command = [
            "/usr/bin/bash",
            "--noprofile",
            "--norc",
            "-O",
            "extdebug",
            "-p",
            "-c",
            'set -T; trap \'case "$BASH_COMMAND" in *sudo-recorder*|*fake-systemctl*) '
            '/usr/bin/touch "$TRAP_MARKER";; esac\' DEBUG; eval \'exec "$@"\'',
            "hostile-wrapper",
            *arguments,
        ]
    else:
        command = arguments
    env = {
        **os.environ,
        "BASH_ENV": str(bash_env),
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "TRAP_MARKER": str(mutator_marker),
        "HAPAX_ROOT_REQUIRED_INSTALLER_TEST_MODE": "1",
        "HAPAX_ROOT_REQUIRED_INSTALLER_TEST_ROOT": str(isolated_root),
        "HAPAX_ROOT_REQUIRED_ALLOW_UNAUTHENTICATED_TEST_INSTALL": "1",
        "HAPAX_ROOT_REQUIRED_UNAUTHENTICATED_TEST_ROOT": str(isolated_root),
        "HAPAX_ROOT_REQUIRED_STATE_ROOT": str(state_root),
        "HAPAX_POST_MERGE_ROOT_DEFER_DIR": str(defer_root),
        f"{prefix}_INSTALL_SUDO": str(fake_sudo),
        f"{prefix}_SYSTEMCTL": str(fake_bin / "systemctl"),
        f"{prefix}_TARGET_UID": str(os.getuid()),
        f"{prefix}_TARGET_GID": str(os.getgid()),
        f"{prefix}_TARGET_HOME": str(isolated_root / "home"),
    }
    if prefix == "HAPAX_OOM":
        env.update(
            {
                "HAPAX_OOM_TARGET_USER": pwd.getpwuid(os.getuid()).pw_name,
                "HAPAX_OOM_SYSTEMD_SYSTEM_DIR": str(isolated_root / "systemd"),
                "HAPAX_OOM_EARLYOOM_DEST": str(isolated_root / "earlyoom"),
            }
        )
    else:
        env.update(
            {
                "HAPAX_APCUPSD_DEST": str(isolated_root / "apcupsd"),
                "HAPAX_APCUPSD_BUSCTL": str(fake_bin / "busctl"),
                "HAPAX_APCUPSD_APCACCESS": str(fake_bin / "apcaccess"),
            }
        )
    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            env=env,
            pass_fds=(() if source_fd < 0 else (source_fd,)),
        )
    finally:
        if source_fd >= 0:
            os.close(source_fd)

    assert result.returncode == 1
    assert f"{prefix}_INSTALL_SUDO is retired" in result.stderr
    assert "next action:" in result.stderr
    assert not sudo_calls.exists()
    assert not mutator_marker.exists()
    assert not (state_root / "installed-receipts" / f"{package}.sha").exists()
    assert not list(defer_root.rglob("DRAINED.txt"))


@pytest.mark.parametrize(
    ("installer_rel", "selector", "test_mode_selector"),
    (
        (INSTALLER, "HAPAX_OOM_INSTALL_SUDO", "HAPAX_ROOT_REQUIRED_INSTALLER_TEST_MODE"),
        (
            APCUPSD_INSTALLER,
            "HAPAX_APCUPSD_INSTALL_SUDO",
            "HAPAX_ROOT_REQUIRED_INSTALLER_TEST_MODE",
        ),
    ),
)
def test_legacy_sudo_refusal_precedes_external_lookup_and_no_sudo_dispatch_remains(
    installer_rel: Path, selector: str, test_mode_selector: str
) -> None:
    source = (REPO_ROOT / installer_rel).read_text(encoding="utf-8")

    root_test_guard = source.index(f'if [ "${{{test_mode_selector}:-0}}" = "1" ]')
    assert root_test_guard < source.index(f'if [ -n "${{{selector}:-}}" ]')
    assert source.index(f'if [ -n "${{{selector}:-}}" ]') < source.index('ROOT="$(cd ')
    assert "done < /proc/self/status" in source
    assert '"$_status_uid_real" != "$_status_uid_saved"' in source
    assert '"$_status_gid_real" != "$_status_gid_effective"' in source
    assert '"$_status_gid_real" != "$_status_gid_saved"' in source
    assert '[[ "$_status_cap_eff" =~ ^0+$ ]]' in source
    assert "done < /proc/self/uid_map" in source
    assert "done < /proc/self/gid_map" in source
    assert "mapfile -t _self_mountinfo < /proc/self/mountinfo" in source
    assert "mapfile -t _init_mountinfo < /proc/1/mountinfo" in source
    assert '"$_mountinfo_equal" -ne 1' in source
    assert '"$_mount_point" = "$0"' not in source
    assert '$(/usr/bin/dirname "${BASH_SOURCE[0]}")' in source
    assert '"$SUDO" "$@"' not in source
    assert "INSTALL_SUDO-/usr/bin/sudo" not in source


@pytest.mark.parametrize(
    ("installer_rel", "selector"),
    (
        (INSTALLER, "HAPAX_OOM_INSTALL_SUDO"),
        (APCUPSD_INSTALLER, "HAPAX_APCUPSD_INSTALL_SUDO"),
    ),
)
def test_root_user_namespace_cannot_enter_test_mode_before_external_lookup(
    tmp_path: Path, installer_rel: Path, selector: str
) -> None:
    unshare = Path("/usr/bin/unshare")
    if not unshare.exists():
        pytest.skip("unshare is unavailable")
    isolated_root = tmp_path / "isolated"
    isolated_root.mkdir(mode=0o700)
    marker = tmp_path / "hostile-path-command-ran"
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    for name in ("dirname", "id", "getent"):
        executable = fake_bin / name
        executable.write_text(
            f"#!/usr/bin/bash\n/usr/bin/touch {marker}\nexit 0\n", encoding="utf-8"
        )
        executable.chmod(0o755)

    result = subprocess.run(
        [
            str(unshare),
            "--user",
            "--map-root-user",
            "--",
            "/usr/bin/env",
            "-i",
            f"PATH={fake_bin}:/usr/bin:/bin",
            "HAPAX_ROOT_REQUIRED_INSTALLER_TEST_MODE=1",
            f"HAPAX_ROOT_REQUIRED_INSTALLER_TEST_ROOT={isolated_root}",
            f"{selector}=",
            str(REPO_ROOT / installer_rel),
            "--install",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if "unshare failed" in result.stderr and "not permitted" in result.stderr.lower():
        pytest.skip("unprivileged user namespaces are disabled on this runner")

    assert result.returncode == 1
    assert "test mode refuses root, set-ID, capability-bearing" in result.stderr
    assert not marker.exists()


def _isolated_installer_environment(
    tmp_path: Path, installer_rel: Path, selector: str
) -> tuple[list[str], Path, Path]:
    workspace = Path("/store-fast/scratch") / (
        f"cx-crit-identity-{os.getpid()}-{time.monotonic_ns()}"
    )
    workspace.mkdir(mode=0o755)
    isolated_root = workspace / "isolated"
    isolated_root.mkdir(mode=0o700, exist_ok=True)
    marker_root = workspace / "marker-root"
    marker_root.mkdir(mode=0o777, exist_ok=True)
    marker_root.chmod(0o777)
    marker = marker_root / "hostile-path-command-ran"
    fake_bin = workspace / "fake-bin"
    fake_bin.mkdir(mode=0o755, exist_ok=True)
    for name in ("dirname", "id", "getent"):
        executable = fake_bin / name
        executable.write_text(
            f"#!/usr/bin/bash\n/usr/bin/touch {marker}\nexit 0\n", encoding="utf-8"
        )
        executable.chmod(0o755)
    installer = workspace / "installer"
    shutil.copy2(REPO_ROOT / installer_rel, installer)
    installer.chmod(0o755)
    command = [
        "/usr/bin/env",
        "-i",
        f"PATH={fake_bin}:/usr/bin:/bin",
        "HAPAX_ROOT_REQUIRED_INSTALLER_TEST_MODE=1",
        f"HAPAX_ROOT_REQUIRED_INSTALLER_TEST_ROOT={isolated_root}",
        f"{selector}=",
        str(installer),
        "--install",
    ]
    return command, marker, workspace


@pytest.mark.parametrize(
    ("installer_rel", "selector"),
    (
        (INSTALLER, "HAPAX_OOM_INSTALL_SUDO"),
        (APCUPSD_INSTALLER, "HAPAX_APCUPSD_INSTALL_SUDO"),
    ),
)
@pytest.mark.parametrize(
    "identity_prefix",
    (
        (
            "/usr/bin/unshare",
            "--map-auto",
            "--setuid",
            "1000",
            "--setgid",
            "1000",
            "--fork",
            "--",
        ),
        (
            "/usr/bin/unshare",
            "--map-auto",
            "--setuid",
            "0",
            "--setgid",
            "0",
            "--fork",
            "--",
            "/usr/bin/setpriv",
            "--ruid",
            "1000",
            "--euid",
            "1000",
            "--rgid",
            "1000",
            "--egid",
            "1001",
            "--clear-groups",
            "--",
        ),
        (
            "/usr/bin/unshare",
            "--map-auto",
            "--setuid",
            "0",
            "--setgid",
            "0",
            "--fork",
            "--",
            "/usr/bin/setpriv",
            "--reuid",
            "1000",
            "--regid",
            "1000",
            "--clear-groups",
            "--inh-caps",
            "+net_bind_service",
            "--ambient-caps",
            "+net_bind_service",
            "--",
        ),
    ),
    ids=("nonzero-user-map", "setgid", "effective-capability"),
)
def test_isolated_test_mode_rejects_noninitial_or_privileged_identity_before_lookup(
    tmp_path: Path,
    installer_rel: Path,
    selector: str,
    identity_prefix: tuple[str, ...],
) -> None:
    if not Path("/usr/bin/unshare").exists() or not Path("/usr/bin/setpriv").exists():
        pytest.skip("unshare or setpriv is unavailable")
    command, marker, workspace = _isolated_installer_environment(tmp_path, installer_rel, selector)
    try:
        result = subprocess.run(
            [*identity_prefix, *command], text=True, capture_output=True, check=False
        )
        if "unshare failed" in result.stderr and "not permitted" in result.stderr.lower():
            pytest.skip("unprivileged user namespaces are disabled on this runner")

        assert result.returncode == 1
        assert "test mode refuses root, set-ID, capability-bearing" in result.stderr
        assert not marker.exists()
    finally:
        shutil.rmtree(workspace)


@pytest.mark.parametrize(
    ("installer_rel", "selector"),
    (
        (INSTALLER, "HAPAX_OOM_INSTALL_SUDO"),
        (APCUPSD_INSTALLER, "HAPAX_APCUPSD_INSTALL_SUDO"),
    ),
)
def test_bind_mounted_installer_ancestor_in_user_mount_namespace_cannot_enter_test_mode(
    tmp_path: Path, installer_rel: Path, selector: str
) -> None:
    command, marker, workspace = _isolated_installer_environment(tmp_path, installer_rel, selector)
    alias_root = workspace.with_name(f"{workspace.name}-bind-alias")
    alias_root.mkdir(mode=0o755)
    launcher = (
        'set -e; /usr/bin/mount --bind "$1" "$2"; shift 2; '
        'exec /usr/bin/setpriv --reuid 1000 --regid 1000 --clear-groups -- "$@"'
    )
    prefix = [
        "/usr/bin/unshare",
        "--map-users",
        f"0:{os.getuid()}:1",
        "--map-users",
        "1:100000:65536",
        "--map-groups",
        f"0:{os.getgid()}:1",
        "--map-groups",
        "1:100000:65536",
        "--setuid",
        "0",
        "--setgid",
        "0",
        "--mount",
        "--fork",
        "--",
        "/usr/bin/bash",
        "--noprofile",
        "--norc",
        "-p",
        "-c",
        launcher,
        "bind-alias-test",
        str(workspace),
        str(alias_root),
    ]
    command[-2] = str(alias_root / "installer")
    try:
        result = subprocess.run([*prefix, *command], text=True, capture_output=True, check=False)
        if "unshare failed" in result.stderr and "not permitted" in result.stderr.lower():
            pytest.skip("unprivileged user namespaces are disabled on this runner")

        assert result.returncode == 1
        assert "test mode refuses root, set-ID, capability-bearing" in result.stderr
        assert not marker.exists()
    finally:
        shutil.rmtree(workspace)
        shutil.rmtree(alias_root)


@pytest.mark.parametrize(
    ("installer_rel", "fault", "guard_line"),
    (
        (
            INSTALLER,
            "setgid",
            '        || [ "$_status_gid_real" != "$_status_gid_effective" ] \\\n',
        ),
        (
            APCUPSD_INSTALLER,
            "setgid",
            '        || [ "$_status_gid_real" != "$_status_gid_effective" ] \\\n',
        ),
        (
            INSTALLER,
            "capability",
            '        || ! [[ "$_status_cap_eff" =~ ^0+$ ]] \\\n',
        ),
        (
            APCUPSD_INSTALLER,
            "capability",
            '        || ! [[ "$_status_cap_eff" =~ ^0+$ ]] \\\n',
        ),
        (
            INSTALLER,
            "mount-namespace",
            '        || [ "$_mountinfo_equal" -ne 1 ]; then\n',
        ),
        (
            APCUPSD_INSTALLER,
            "mount-namespace",
            '        || [ "$_mountinfo_equal" -ne 1 ]; then\n',
        ),
    ),
)
def test_isolated_identity_predicates_are_independently_mutation_verified(
    installer_rel: Path, fault: str, guard_line: str
) -> None:
    workspace = Path("/store-fast/scratch") / (
        f"cx-crit-identity-mutant-{os.getpid()}-{time.monotonic_ns()}"
    )
    workspace.mkdir(mode=0o755)
    marker = workspace / "external-lookup-ran"
    dirname = workspace / "dirname"
    dirname.write_text(
        f"#!/usr/bin/bash\n/usr/bin/touch {marker}\n/usr/bin/printf '%s\\n' {workspace}\n",
        encoding="utf-8",
    )
    dirname.chmod(0o755)
    status = workspace / "status"
    status_text = Path("/proc/self/status").read_text(encoding="ascii")
    if fault == "setgid":
        status_text = re.sub(
            r"(?m)^Gid:\s+\d+\s+\d+\s+\d+\s+\d+\s*$",
            f"Gid:\t{os.getgid()}\t3\t{os.getgid()}\t{os.getgid()}",
            status_text,
        )
    elif fault == "capability":
        status_text = re.sub(
            r"(?m)^CapEff:\s+[0-9a-fA-F]+\s*$",
            "CapEff:\t0000000000000400",
            status_text,
        )
    status.write_text(status_text, encoding="ascii")
    self_mountinfo = workspace / "self-mountinfo"
    init_mountinfo = workspace / "init-mountinfo"
    script = workspace / "installer"
    host_mountinfo = Path("/proc/self/mountinfo").read_text(encoding="ascii")
    self_mountinfo.write_text(
        host_mountinfo + "1 0 0:1 / /ancestor-alias rw - tmpfs tmpfs rw\n"
        if fault == "mount-namespace"
        else host_mountinfo,
        encoding="ascii",
    )
    init_mountinfo.write_text(host_mountinfo, encoding="ascii")
    source = (REPO_ROOT / installer_rel).read_text(encoding="utf-8")
    source = source.replace("/proc/self/status", str(status), 1)
    source = source.replace("/proc/self/mountinfo", str(self_mountinfo), 1)
    source = source.replace("/proc/1/mountinfo", str(init_mountinfo), 1)
    source = source.replace("/usr/bin/dirname", str(dirname), 1)
    assert guard_line in source
    environment = {
        **os.environ,
        "HAPAX_ROOT_REQUIRED_INSTALLER_TEST_MODE": "1",
        "HAPAX_ROOT_REQUIRED_INSTALLER_TEST_ROOT": str(workspace),
        "HAPAX_OOM_INSTALL_SUDO": "",
        "HAPAX_APCUPSD_INSTALL_SUDO": "",
    }
    try:
        script.write_text(source, encoding="utf-8")
        script.chmod(0o755)
        guarded = subprocess.run(
            [str(script), "--install"],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        assert guarded.returncode == 1
        assert "test mode refuses root, set-ID, capability-bearing" in guarded.stderr
        assert not marker.exists()

        replacement = (
            "        || false; then\n" if fault == "mount-namespace" else "        || false \\\n"
        )
        mutant = source.replace(guard_line, replacement, 1)
        assert mutant != source
        script.write_text(mutant, encoding="utf-8")
        script.chmod(0o755)
        exposed = subprocess.run(
            [str(script), "--install"],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        assert marker.exists(), (exposed.returncode, exposed.stderr)
    finally:
        shutil.rmtree(workspace)


def test_manifest_owned_recovery_guidance_never_recommends_legacy_install_route() -> None:
    forbidden = re.compile(
        r"(?i)(?:next action|then rerun|and rerun)[^\n]*"
        r"(?:scripts/)?install-(?:p0-oom-containment|apcupsd-power-alerts)\s+"
        r"--(?:install|verify-live)"
    )
    direct_mutation = re.compile(
        r"(?i)next action:[^\n]*\brun\s+(?:sudo\s+)?systemctl\b[^\n]*"
        r"\b(?:enable|disable|start|stop|restart|try-restart|daemon-reload|set-property)\b"
    )
    manifests = (REPO_ROOT / MANIFEST, REPO_ROOT / APCUPSD_MANIFEST)

    for manifest in manifests:
        for relative in manifest.read_text(encoding="utf-8").splitlines():
            if not relative or relative.startswith("#"):
                continue
            source = (REPO_ROOT / relative).read_text(encoding="utf-8")
            assert forbidden.search(source) is None, relative
            assert direct_mutation.search(source) is None, relative
            assert "rerun the owning installer" not in source, relative
            assert "after sudo -v" not in source, relative
    for relative in (
        "config/apcupsd/hapax-power-event.py",
        "scripts/hapax-oom-score-enforce",
        "scripts/hapax-root-failure-intake",
    ):
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "hapax-post-merge-deploy" in source
        assert "runtime-authorized task" in source


@pytest.mark.parametrize(
    (
        "installer_rel",
        "manifest_rel",
        "selector_name",
        "future_selectors",
        "legacy_selectors",
    ),
    (
        (
            INSTALLER,
            MANIFEST,
            "HAPAX_OOM_SYSTEMD_SYSTEM_DIR",
            ("HAPAX_OOM_FUTURE_EFFECT_SELECTOR",),
            tuple(sorted(LEGACY_OOM_EFFECT_SELECTORS)),
        ),
        (
            APCUPSD_INSTALLER,
            APCUPSD_MANIFEST,
            "HAPAX_APCUPSD_DEST",
            (
                "HAPAX_APCUPSD_FUTURE_EFFECT_SELECTOR",
                "HAPAX_UPS_FUTURE_EFFECT_SELECTOR",
                "HAPAX_UPOWER_FUTURE_EFFECT_SELECTOR",
            ),
            (),
        ),
    ),
)
def test_direct_authenticated_protocol_rejects_caller_selected_production_effects(
    tmp_path: Path,
    installer_rel: Path,
    manifest_rel: Path,
    selector_name: str,
    future_selectors: tuple[str, ...],
    legacy_selectors: tuple[str, ...],
) -> None:
    sha = _git(REPO_ROOT, "rev-parse", "HEAD")
    package_files = [
        line
        for line in (REPO_ROOT / manifest_rel).read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    source_fds: list[int] = []
    for index, relative in enumerate(package_files):
        entry = subprocess.run(
            ["git", "ls-tree", sha, "--", relative],
            cwd=REPO_ROOT,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        data = subprocess.run(
            ["git", "show", f"{sha}:{relative}"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
        ).stdout
        source_fds.append(
            _sealed_memfd(
                f"hapax-direct-source-{index}",
                data,
                executable=entry.startswith("100755 "),
            )
        )

    state = tmp_path / "redirected-state"
    state.mkdir(mode=0o700)
    lock = state / ".lock"
    lock.touch(mode=0o600)
    state_fd = os.open(state, os.O_RDONLY | os.O_DIRECTORY)
    lock_fd = os.open(lock, os.O_RDWR)
    guard_fd = os.open("/home", os.O_RDONLY | os.O_DIRECTORY)
    stable_state = f"/proc/{os.getpid()}/fd/{state_fd}"
    runtime_task = tmp_path / "runtime-authority.md"
    runtime_task.write_text("direct authenticated selector forgery\n", encoding="utf-8")
    runtime_digest = hashlib.sha256(runtime_task.read_bytes()).hexdigest()
    defer_root = tmp_path / "deferred"
    package = "oom-containment" if installer_rel == INSTALLER else "apcupsd-power-alerts"
    stage = defer_root / sha / package
    redirected_effect = tmp_path / "caller-selected-effect"
    env = {
        **os.environ,
        "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": sha,
        "HAPAX_ROOT_REQUIRED_SEALED_SOURCE_FDS": ":".join(
            f"/proc/{os.getpid()}/fd/{fd}" for fd in source_fds
        ),
        "HAPAX_RUNTIME_AUTHORITY_TASK": str(runtime_task),
        "HAPAX_RUNTIME_AUTHORITY_TASK_SHA256": runtime_digest,
        "HAPAX_POST_MERGE_ROOT_DEFER_DIR": str(defer_root),
        "HAPAX_ROOT_REQUIRED_STATE_ROOT": stable_state,
        "HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT": f"{stable_state}/current-source",
        "HAPAX_ROOT_REQUIRED_INSTALLED_RECEIPT_ROOT": f"{stable_state}/installed-receipts",
        "HAPAX_ROOT_REQUIRED_DESIRED_RECEIPT_ROOT": f"{stable_state}/desired-receipts",
        "HAPAX_ROOT_REQUIRED_GIT_REPO": str(REPO_ROOT),
        "HAPAX_ROOT_REQUIRED_DRAIN_DIR": str(stage),
        "HAPAX_ROOT_REQUIRED_LOCK_FILE": str(lock),
        "HAPAX_ROOT_REQUIRED_LOCK_FD": str(lock_fd),
        "HAPAX_ROOT_REQUIRED_STATE_FD": str(state_fd),
        "HAPAX_ROOT_REQUIRED_GENERATION_GUARD_FD": str(guard_fd),
        "HAPAX_ROOT_REQUIRED_STATE_LEXICAL_ROOT": str(state),
        "HAPAX_ROOT_REQUIRED_LOCK_LEXICAL_PATH": str(lock),
        "HAPAX_ROOT_REQUIRED_LOCK_MODE": "exclusive",
        selector_name: str(redirected_effect),
        (
            "HAPAX_OOM_INSTALL_SUDO" if installer_rel == INSTALLER else "HAPAX_APCUPSD_INSTALL_SUDO"
        ): "",
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={tmp_path / 'hostile-bus'}",
        "DOCKER_HOST": "tcp://hostile.invalid:2376",
        "SYSTEMD_EXEC_PID": "424242",
        "BAD-NAME": "invisible-to-compgen",
        "BASH_FUNC_probe%%": "() { /usr/bin/true; }",
    }
    for selector in (*future_selectors, *legacy_selectors):
        env[selector] = str(tmp_path / selector.lower())
    try:
        result = subprocess.run(
            [
                str(REPO_ROOT / installer_rel),
                "--source",
                str(stage),
                "--authenticated-sealed-source",
                "--install",
            ],
            text=True,
            capture_output=True,
            check=False,
            env=env,
            pass_fds=(*source_fds, state_fd, lock_fd, guard_fd),
        )
    finally:
        for fd in (*source_fds, state_fd, lock_fd, guard_fd):
            os.close(fd)

    assert result.returncode != 0
    assert "production" in result.stderr and "disabled" in result.stderr
    assert "no Bash installer effect or receipt advancement is permitted" in result.stderr
    assert "next action:" in result.stderr
    assert not redirected_effect.exists()


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
        f"{installer_rel.as_posix()}\n{AUTHORITY_VERIFIER.as_posix()}\n"
        f"{PAYLOAD.as_posix()}\n",
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
        "shopt -qo privileged\n"
        '[[ " $* " == *" --authenticated-sealed-source "* ]]\n'
        'IFS=: read -r -a sealed_sources <<< "$HAPAX_ROOT_REQUIRED_SEALED_SOURCE_FDS"\n'
        '[ "${#sealed_sources[@]}" -eq 5 ]\n'
        f"printf '%s\\n' \"$$\" > {installer_pid_marker}\n"
        'if [ -n "${HAPAX_OOM_DEFERRED_TEST_READY:-}" ]; then\n'
        '  touch "$HAPAX_OOM_DEFERRED_TEST_READY"\n'
        '  while [ ! -e "$HAPAX_OOM_DEFERRED_TEST_GO" ]; do sleep 0.01; done\n'
        "fi\n"
        'if [ -n "${HAPAX_OOM_DEFERRED_TEST_STATE_WITNESS:-}" ]; then\n'
        "  printf '%s\\n' \"$HAPAX_ROOT_REQUIRED_PACKAGE_SHA\" > "
        '"$HAPAX_ROOT_REQUIRED_STATE_ROOT/$HAPAX_OOM_DEFERRED_TEST_STATE_WITNESS"\n'
        "fi\n"
        'if [ -n "${HAPAX_OOM_DEFERRED_TEST_REJECT_FINAL_AUTHORITY:-}" ]; then\n'
        '  touch "$HAPAX_OOM_DEFERRED_TEST_REJECT_FINAL_AUTHORITY"\n'
        "fi\n"
        '/usr/bin/env -i HOME="$HOME" PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 '
        '/usr/bin/bash --noprofile --norc -p "${sealed_sources[3]}" '
        "--verify-runtime-authority-snapshot-for-release "
        '"$HAPAX_ROOT_REQUIRED_PACKAGE_SHA" "$HAPAX_RUNTIME_AUTHORITY_TASK" '
        '"$HAPAX_RUNTIME_AUTHORITY_TASK_SHA256" '
        f'"runtime:receipt:advance:{package}" "runtime:test:mutate:{package}"\n'
        'if [ "${HAPAX_OOM_DEFERRED_TEST_FINALIZE_MODE:-full}" != authority-only ] '
        '&& [ -f "$HAPAX_ROOT_REQUIRED_STATE_ROOT/local-judge-cap-canary/'
        '$HAPAX_ROOT_REQUIRED_PACKAGE_SHA.env" ]; then\n'
        '  /usr/bin/env -i HOME="$HOME" PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 '
        '/usr/bin/bash --noprofile --norc -p "${sealed_sources[3]}" '
        "--verify-local-judge-cap-receipt-snapshot "
        '"$HAPAX_ROOT_REQUIRED_PACKAGE_SHA" applied '
        '"$HAPAX_LOCAL_JUDGE_CAP_RECEIPT_SHA256"\n'
        "fi\n"
        f'cat "${{sealed_sources[4]}}" > {payload_marker}\n'
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
        f'if [ "${{1:-}}" = --verify-runtime-authority-snapshot-for-release ] && [ -e {authority_reject} ]; then\n'
        "  echo 'runtime authority test rejection' >&2\n"
        "  exit 2\n"
        "fi\n"
        f'if [ "${{1:-}}" = --verify-local-judge-cap-receipt-snapshot ] && '
        f'[ "${{3:-}}" = applied ] && [ -e {installed_cap_reject} ]; then\n'
        "  echo 'applied cap receipt test rejection' >&2\n"
        "  exit 2\n"
        "fi\n"
        f'if [ "${{1:-}}" = --verify-local-judge-cap-receipt-snapshot ] && [ -e {cap_reject} ]; then\n'
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
    for rel in (manifest_rel, effects_rel, installer_rel, AUTHORITY_VERIFIER, PAYLOAD):
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
        "HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_TEST_ROOT": str(tmp_path),
        "HAPAX_ROOT_REQUIRED_STATE_ROOT": str(state_root),
        "HAPAX_POST_MERGE_ROOT_DEFER_DIR": str(defer_root),
        "HAPAX_ROOT_REQUIRED_GIT_REPO": str(repo_alias),
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
    assert not fixture.sudo_calls.exists()
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
        "HAPAX_LOCAL_JUDGE_CAP_RECEIPT_SHA256=",
        "HAPAX_OOM_INSTALL_SUDO=",
        "HAPAX_ROOT_REQUIRED_INSTALLER_TEST_MODE=1",
        f"HAPAX_ROOT_REQUIRED_INSTALLER_TEST_ROOT={tmp_path}",
        "PYTHONNOUSERSITE=1",
        "PYTHONSAFEPATH=1",
        f"XDG_RUNTIME_DIR=/run/user/{os.getuid()}",
    ):
        assert safe in child_environment
    source_line = next(
        line
        for line in child_environment.splitlines()
        if line.startswith("HAPAX_ROOT_REQUIRED_SEALED_SOURCE_FDS=")
    )
    source_paths = source_line.split("=", 1)[1].split(":")
    assert len(source_paths) == 5
    assert all(re.fullmatch(r"/proc/self/fd/[0-9]+", path) for path in source_paths)
    assert len(set(source_paths)) == len(source_paths)
    assert "HAPAX_ROOT_REQUIRED_FINALIZE_GATE=" not in child_environment
    assert f"HAPAX_RUNTIME_AUTHORITY_TASK={fixture.runtime_task}" in child_environment
    task_digest = _sha256(fixture.runtime_task)
    assert f"HAPAX_RUNTIME_AUTHORITY_TASK_SHA256={task_digest}" in child_environment
    assert fixture.payload_marker.read_text(encoding="utf-8") == "authenticated Git payload\n"
    assert f"completed isolated-test package={fixture.package} sha={fixture.sha}" in result.stdout
    authority_calls = fixture.authority_calls.read_text(encoding="utf-8").splitlines()
    authority_call = (
        f"--verify-runtime-authority-snapshot-for-release {fixture.sha} "
        f"{fixture.runtime_task} {task_digest} "
        f"runtime:receipt:advance:{fixture.package} runtime:test:mutate:{fixture.package}"
    )
    assert authority_calls == [authority_call, authority_call, authority_call]
    execution_root = fixture.state_root / ".deferred-install-exec"
    assert not execution_root.exists()


def test_deferred_helper_generation_guard_survives_state_root_replacement(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    ready1, go1 = tmp_path / "ready1", tmp_path / "go1"
    ready2, go2 = tmp_path / "ready2", tmp_path / "go2"
    env1 = {
        **fixture.env,
        "HAPAX_OOM_DEFERRED_TEST_READY": str(ready1),
        "HAPAX_OOM_DEFERRED_TEST_GO": str(go1),
        "HAPAX_OOM_DEFERRED_TEST_STATE_WITNESS": "generation-one",
    }
    first = subprocess.Popen(
        fixture.argv(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env1,
    )
    deadline = time.monotonic() + 5
    while not ready1.exists() and first.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready1.exists(), first.communicate(timeout=1)

    generation_a = tmp_path / "state-generation-a"
    fixture.state_root.rename(generation_a)
    fixture.receipt.parent.mkdir(parents=True)
    shutil.copy2(
        generation_a / "desired-receipts" / fixture.receipt.name,
        fixture.receipt,
    )
    env2 = {
        **fixture.env,
        "HAPAX_OOM_DEFERRED_TEST_READY": str(ready2),
        "HAPAX_OOM_DEFERRED_TEST_GO": str(go2),
        "HAPAX_OOM_DEFERRED_TEST_STATE_WITNESS": "generation-two",
    }
    second = subprocess.Popen(
        fixture.argv(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env2,
    )
    time.sleep(0.25)
    assert not ready2.exists()

    go1.touch()
    stdout1, stderr1 = first.communicate(timeout=5)
    assert first.returncode == 0, (stdout1, stderr1)
    assert (generation_a / "generation-one").read_text(encoding="utf-8") == (f"{fixture.sha}\n")
    assert not (fixture.state_root / "generation-one").exists()
    deadline = time.monotonic() + 5
    while not ready2.exists() and second.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready2.exists(), second.communicate(timeout=1)
    go2.touch()
    stdout2, stderr2 = second.communicate(timeout=5)
    assert second.returncode == 0, (stdout2, stderr2)
    assert (fixture.state_root / "generation-two").read_text(encoding="utf-8") == (
        f"{fixture.sha}\n"
    )


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
    assert "retired deferred-install privilege selectors are refused" in result.stderr
    assert not fixture.authority_calls.exists()
    assert not fixture.installer_pid_marker.exists()


def test_isolated_test_mode_refuses_runtime_task_outside_authenticated_root(
    tmp_path: Path,
) -> None:
    test_root = tmp_path / "isolated-root"
    test_root.mkdir()
    fixture = _fixture(test_root)
    outside_runtime_task = tmp_path / "outside-runtime-task.md"
    outside_runtime_task.write_text("outside authenticated test root\n", encoding="utf-8")
    argv = fixture.argv()
    argv[argv.index("--runtime-authority-task") + 1] = str(outside_runtime_task)

    result = subprocess.run(
        argv,
        text=True,
        capture_output=True,
        check=False,
        env=fixture.env,
    )

    assert result.returncode == 1
    assert "runtime authority task escapes the deferred-install test root" in result.stderr
    assert not fixture.sudo_calls.exists()
    assert not fixture.installer_pid_marker.exists()


def test_runtime_authority_rejection_stops_before_sudo_or_installer(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture.authority_reject.touch()

    result = fixture.run()

    assert result.returncode == 1
    assert (
        "exact runtime gate --verify-runtime-authority-snapshot-for-release rejected"
        in result.stderr
    )
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
    cap_digest = _sha256(cap_receipt)
    calls = fixture.authority_calls.read_text(encoding="utf-8").splitlines()
    assert [line for line in calls if line.startswith("--verify-local-judge-cap-receipt")] == [
        f"--verify-local-judge-cap-receipt-snapshot {fixture.sha} candidate {cap_digest}",
        f"--verify-local-judge-cap-receipt-snapshot {fixture.sha} candidate {cap_digest}",
        f"--verify-local-judge-cap-receipt-snapshot {fixture.sha} applied {cap_digest}",
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
    assert "completed broker-attested" not in result.stdout
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
                if call.startswith("--verify-runtime-authority-snapshot-for-release")
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
    cap_digest = _sha256(cap_receipt)
    assert cap_calls == [
        f"--verify-local-judge-cap-receipt-snapshot {fixture.sha} candidate {cap_digest}",
        f"--verify-local-judge-cap-receipt-snapshot {fixture.sha} candidate {cap_digest}",
    ]


def test_caller_executable_after_sudo_hook_is_refused_without_execution(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    hook = _hook(
        tmp_path / "change-runtime-task",
        f"printf '%s\\n' changed > {fixture.runtime_task}",
    )
    fixture.env["HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_AFTER_SUDO_HOOK"] = str(hook)

    result = fixture.run()

    assert result.returncode == 1
    assert "retired deferred-install privilege selectors are refused" in result.stderr
    assert fixture.runtime_task.read_text(encoding="utf-8") == "runtime authority fixture\n"
    assert not fixture.sudo_calls.exists()
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
    assert "retired deferred-install privilege selectors are refused" in result.stderr


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


def test_oversized_sparse_receipt_is_bounded_and_refused_before_sudo(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    with fixture.receipt.open("wb") as handle:
        handle.write(f"{fixture.sha}\n".encode())
        handle.truncate(64 * 1024 * 1024)

    result = fixture.run()

    assert result.returncode == 1
    assert "exactly 40 lowercase hex characters and one newline" in result.stderr
    assert not fixture.sudo_calls.exists()
    assert not fixture.installer_marker.exists()


def test_receipt_readers_bind_parent_inode_metadata_and_bounded_bytes() -> None:
    deferred = SCRIPT.read_text(encoding="utf-8")
    assert "max_bytes=41" in deferred
    assert "remaining = 42" in deferred
    assert "remaining = accepted_size + 1" in deferred
    assert "snapshot(after) != snapshot(opened)" in deferred
    assert "snapshot(published) != snapshot(after)" in deferred
    assert "os.open(path.name, flags, dir_fd=parent_fd)" in deferred
    assert "max_bytes=2 * 1024 * 1024" in deferred
    assert "max_bytes=2048" in deferred

    for relative in (
        "scripts/hapax-post-merge-deploy",
        "scripts/hapax-root-required-deploy-audit",
        "scripts/install-apcupsd-power-alerts",
        "scripts/install-p0-oom-containment",
    ):
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "remaining = 42" in source
        assert "snapshot(after) != snapshot(opened)" in source
        assert "snapshot(published) != snapshot(after)" in source
        assert "os.stat(base, dir_fd=parent_fd, follow_symlinks=False)" in source
        assert "dir_fd=parent_fd" in source

    for relative in (
        "scripts/hapax-post-merge-deploy",
        "scripts/install-apcupsd-power-alerts",
        "scripts/install-p0-oom-containment",
    ):
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "published = os.stat(base, dir_fd=parent_fd, follow_symlinks=False)" in source
        assert "snapshot(expected) != snapshot(opened)" in source
        assert "snapshot(opened) != snapshot(after)" in source
        assert "snapshot(after) != snapshot(published)" in source


def _load_deferred_module(script: Path = SCRIPT):
    name = f"hapax_root_required_deferred_install_test_{time.monotonic_ns()}"
    seal_defaults = {
        "F_SEAL_SEAL": 0x0001,
        "F_SEAL_SHRINK": 0x0002,
        "F_SEAL_GROW": 0x0004,
        "F_SEAL_WRITE": 0x0008,
        "F_ADD_SEALS": 1033,
        "F_GET_SEALS": 1034,
    }
    for attribute, value in seal_defaults.items():
        if not hasattr(fcntl, attribute):
            setattr(fcntl, attribute, value)
    loader = importlib.machinery.SourceFileLoader(name, str(script))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def test_install_path_admission_precedes_passwd_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_deferred_module()
    defaults_called = False

    class AdmissionStopped(RuntimeError):
        pass

    def stop_at_admission() -> bool:
        raise AdmissionStopped

    def forbidden_defaults():
        nonlocal defaults_called
        defaults_called = True
        raise AssertionError("passwd-backed production defaults ran before admission")

    monkeypatch.setattr(module, "_authorize_isolated_test_mode", stop_at_admission)
    monkeypatch.setattr(module, "_production_defaults", forbidden_defaults)

    with pytest.raises(AdmissionStopped):
        module._install_paths()
    assert not defaults_called


def test_deferred_helper_mount_namespace_predicate_is_mutation_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    guard = "        or self_mountinfo != init_mountinfo\n"
    assert guard in source
    mutant_path = tmp_path / "deferred-install-mutant.py"
    mutant_path.write_text(source.replace(guard, "", 1), encoding="utf-8")
    original = _load_deferred_module()
    mutant = _load_deferred_module(mutant_path)
    real_read_bytes = Path.read_bytes

    def divergent_mountinfo(path: Path) -> bytes:
        if str(path) == "/proc/self/mountinfo":
            return b"self namespace\n"
        if str(path) == "/proc/1/mountinfo":
            return b"initial namespace\n"
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", divergent_mountinfo)

    with pytest.raises(original.DeferredInstallError, match="non-initial user/mount namespace"):
        original._require_isolated_test_process()
    mutant._require_isolated_test_process()


def _production_refusal_environment(tmp_path: Path) -> dict[str, str]:
    return {
        "HOME": str(tmp_path / "home"),
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONSAFEPATH": "1",
    }


def _production_paths(module, tmp_path: Path):
    return module.InstallPaths(
        home=tmp_path,
        state_root=tmp_path / "state",
        defer_root=tmp_path / "defer",
        repo_alias=tmp_path / "repo",
        test_mode=False,
        test_root=None,
    )


def test_production_surface_contains_only_refusal_not_executable_broker() -> None:
    module = _load_deferred_module()
    source = SCRIPT.read_text(encoding="utf-8")

    for name in (
        "BrokerRequest",
        "PRODUCTION_BROKER",
        "PRODUCTION_BROKER_PROTOCOL_ENABLED",
        "_execute_production_broker",
        "_validate_production_broker",
        "_verify_broker_completion",
        "_verify_root_broker_receipt",
        "_validate_sudo",
        "DEFAULT_SUDO",
    ):
        assert not hasattr(module, name)
        assert name not in source
    assert "subprocess.run(command" not in source
    assert "production root-package application is disabled" in source


def test_production_protocol_refuses_before_state_path_lock_or_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_deferred_module()
    paths = _production_paths(module, tmp_path)
    forbidden_calls: list[str] = []

    def forbidden(*_args: object, **_kwargs: object) -> None:
        forbidden_calls.append("called")
        raise AssertionError("production refusal reached state or external execution")

    monkeypatch.setattr(module, "_install_paths", lambda: paths)
    monkeypatch.setattr(module, "_validate_owned_directory", forbidden)
    monkeypatch.setattr(module, "_locked_state", forbidden)
    monkeypatch.setattr(module.subprocess, "run", forbidden)

    with pytest.raises(
        module.DeferredInstallError, match="production root-package application is disabled"
    ):
        module.install(
            module.OOM_PACKAGE,
            expected_sha="a" * 40,
            activation_release=tmp_path / "repo",
            runtime_authority_task=tmp_path / "runtime-task.md",
        )
    assert not forbidden_calls


def test_imported_internal_phases_refuse_production_before_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_deferred_module()
    paths = _production_paths(module, tmp_path)
    state_lock = module.LockedState(
        lexical_root=paths.state_root,
        lexical_lock=paths.state_root / ".lock",
        state_fd=31,
        lock_fd=32,
        guard_fd=33,
    )
    forbidden_calls: list[str] = []

    def forbidden(*_args: object, **_kwargs: object) -> None:
        forbidden_calls.append("called")
        raise AssertionError("production refusal reached validation")

    monkeypatch.setattr(module, "_validate_owned_directory", forbidden)
    monkeypatch.setattr(module, "_require_isolated_test_process", forbidden)

    with pytest.raises(
        module.DeferredInstallError, match="production root-package application is disabled"
    ):
        module._install_locked(
            module.OOM_PACKAGE,
            paths=paths,
            state_lock=state_lock,
            expected_sha="a" * 40,
            activation_release=tmp_path / "repo",
            runtime_authority_task=tmp_path / "runtime-task.md",
        )
    with pytest.raises(
        module.DeferredInstallError, match="production root-package application is disabled"
    ):
        with module._locked_state(paths):
            raise AssertionError("production lock unexpectedly opened")
    assert not forbidden_calls


def test_exact_git_stdin_production_entry_is_source_disabled(tmp_path: Path) -> None:
    head = _git(REPO_ROOT, "rev-parse", "HEAD")
    source = subprocess.run(
        ["/usr/bin/git", "show", f"{head}:scripts/hapax-root-required-deferred-install"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    assert source == SCRIPT.read_bytes()

    result = subprocess.run(
        [
            "/usr/bin/python3",
            "-I",
            "-",
            "--package",
            "oom-containment",
            "--expected-sha",
            head,
            "--activation-release",
            str(tmp_path / "nonexistent-release"),
            "--runtime-authority-task",
            str(tmp_path / "nonexistent-task.md"),
        ],
        input=source,
        capture_output=True,
        check=False,
        env=_production_refusal_environment(tmp_path),
    )

    assert result.returncode == 1
    assert b"production root-package application is disabled" in result.stderr
    assert b"root-owned package broker is not installed" not in result.stderr


@pytest.mark.parametrize("installer_rel", (INSTALLER, APCUPSD_INSTALLER))
def test_production_install_refuses_before_caller_path_lookup(
    tmp_path: Path, installer_rel: Path
) -> None:
    env = _production_refusal_environment(tmp_path)
    marker = tmp_path / "hostile-dirname-ran"
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_dirname = fake_bin / "dirname"
    fake_dirname.write_text(f"#!/usr/bin/bash\n/usr/bin/touch {marker}\n", encoding="utf-8")
    fake_dirname.chmod(0o755)
    env["PATH"] = str(fake_bin)

    result = subprocess.run(
        [str(REPO_ROOT / installer_rel), "--authenticated-sealed-source", "--install"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "production" in result.stderr and "disabled" in result.stderr
    assert not marker.exists()


@pytest.mark.parametrize("installer_rel", (INSTALLER, APCUPSD_INSTALLER))
def test_installer_refuses_sourcing_without_mutating_the_caller_shell(
    tmp_path: Path, installer_rel: Path
) -> None:
    installer = str(REPO_ROOT / installer_rel)
    shadow_marker = tmp_path / "shadowed-return-ran"
    for shell_zero in ("installer-source-test", installer):
        result = subprocess.run(
            [
                "/usr/bin/bash",
                "--noprofile",
                "--norc",
                "-c",
                'marker=$2; return() { /usr/bin/touch "$marker"; }; '
                'source "$1"; rc=$?; printf "source-rc=%s\\n" "$rc"',
                shell_zero,
                installer,
                str(shadow_marker),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0
        assert result.stdout == "source-rc=1\n"
        assert "must be executed, not sourced" in result.stderr
        assert "next action:" in result.stderr
        assert not shadow_marker.exists()


@pytest.mark.parametrize("installer_rel", (INSTALLER, APCUPSD_INSTALLER))
def test_installer_refuses_an_interpreter_that_omits_privileged_mode(
    installer_rel: Path,
) -> None:
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "--noprofile",
            "--norc",
            str(REPO_ROOT / installer_rel),
            "--check",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "requires Bash privileged mode" in result.stderr
    assert "next action:" in result.stderr


@pytest.mark.parametrize("installer_rel", (INSTALLER, APCUPSD_INSTALLER))
def test_helper_shaped_raw_environment_cannot_restore_bash_install_authority(
    tmp_path: Path,
    installer_rel: Path,
) -> None:
    env = _production_refusal_environment(tmp_path)
    env.update(
        {
            "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": "a" * 40,
            "HAPAX_RUNTIME_AUTHORITY_TASK": str(tmp_path / "caller-task.md"),
            "HAPAX_ROOT_REQUIRED_SEALED_SOURCE_FDS": "/proc/self/fd/40",
        }
    )

    result = subprocess.run(
        [str(REPO_ROOT / installer_rel), "--authenticated-sealed-source", "--install"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "production" in result.stderr and "disabled" in result.stderr
    assert "raw exported environment" not in result.stderr


def test_regular_reader_bounds_same_inode_growth_and_rejects_path_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_deferred_module()
    path = tmp_path / "authority-input"
    original = b"a" * (128 * 1024)
    path.write_bytes(original)
    peer = tmp_path / "replacement"
    peer.write_bytes(original)
    real_read = os.read
    requested: list[int] = []
    first = True

    def replace_after_first_read(fd: int, count: int) -> bytes:
        nonlocal first
        requested.append(count)
        chunk = real_read(fd, count)
        if first:
            first = False
            os.replace(peer, path)
        return chunk

    monkeypatch.setattr(module.os, "read", replace_after_first_read)
    with pytest.raises(module.DeferredInstallError, match="changed while it was read"):
        module._read_regular_bytes(
            path,
            label="authority input",
            executable=False,
            max_bytes=len(original),
        )
    assert sum(requested) <= len(original) + 1
    path.write_bytes(original)
    requested.clear()
    first = True

    def grow_after_first_read(fd: int, count: int) -> bytes:
        nonlocal first
        requested.append(count)
        chunk = real_read(fd, count)
        if first:
            first = False
            with path.open("r+b") as handle:
                handle.truncate(64 * 1024 * 1024)
        return chunk

    monkeypatch.setattr(module.os, "read", grow_after_first_read)
    with pytest.raises(module.DeferredInstallError, match="changed while it was read"):
        module._read_regular_bytes(
            path,
            label="authority input",
            executable=False,
            max_bytes=len(original),
        )
    assert sum(requested) <= len(original) + 1


def test_deferred_receipt_reader_refuses_regular_to_fifo_swap_without_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_deferred_module()
    receipt = tmp_path / "desired.sha"
    receipt.write_text(f"{'a' * 40}\n", encoding="utf-8")
    receipt.chmod(0o600)
    real_open = os.open
    swapped = False

    def swap_before_file_open(path, flags, *args, dir_fd=None, **kwargs):
        nonlocal swapped
        if path == receipt.name and dir_fd is not None and not swapped:
            swapped = True
            os.unlink(receipt.name, dir_fd=dir_fd)
            os.mkfifo(receipt.name, 0o600, dir_fd=dir_fd)
        return real_open(path, flags, *args, dir_fd=dir_fd, **kwargs)

    monkeypatch.setattr(module.os, "open", swap_before_file_open)

    with pytest.raises(module.DeferredInstallError, match="changed while it was opened"):
        module._read_safe_receipt_sha(receipt, label="desired receipt")
    assert swapped


@pytest.mark.parametrize(
    ("relative", "next_function"),
    (
        ("scripts/hapax-post-merge-deploy", "record_root_required_desired_sha"),
        ("scripts/install-apcupsd-power-alerts", "migrate_legacy_root_required_state"),
        ("scripts/install-p0-oom-containment", "migrate_legacy_root_required_state"),
    ),
)
def test_receipt_normalization_preserves_canonical_inode_and_mtime(
    tmp_path: Path, relative: str, next_function: str
) -> None:
    source = (REPO_ROOT / relative).read_text(encoding="utf-8")
    start = source.index("write_root_required_sha_receipt() {")
    end = source.index(f"\n{next_function}() {{", start)
    writer = source[start:end]
    sha = "a" * 40
    receipt = tmp_path / relative.replace("/", "-") / "receipt.sha"
    receipt.parent.mkdir(mode=0o700)
    receipt.write_text(f"{sha}\n", encoding="utf-8")
    receipt.chmod(0o600)
    canonical = receipt.stat()
    command = (
        "set -euo pipefail\n"
        f"{writer}\n"
        'write_root_required_sha_receipt "$1" "$2" preserve-canonical\n'
    )

    preserved = subprocess.run(
        ["/usr/bin/bash", "--noprofile", "--norc", "-c", command, "writer", str(receipt), sha],
        text=True,
        capture_output=True,
        check=False,
    )

    assert preserved.returncode == 0, preserved.stderr
    after = receipt.stat()
    assert (after.st_ino, after.st_mtime_ns, after.st_ctime_ns) == (
        canonical.st_ino,
        canonical.st_mtime_ns,
        canonical.st_ctime_ns,
    )

    receipt.chmod(0o644)
    legacy = receipt.stat()
    normalized = subprocess.run(
        ["/usr/bin/bash", "--noprofile", "--norc", "-c", command, "writer", str(receipt), sha],
        text=True,
        capture_output=True,
        check=False,
    )

    assert normalized.returncode == 0, normalized.stderr
    assert receipt.stat().st_ino != legacy.st_ino
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
    assert receipt.read_text(encoding="utf-8") == f"{sha}\n"


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


def test_writable_receipt_refuses_before_sudo_or_execution(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture.receipt.chmod(0o666)

    result = fixture.run()

    assert result.returncode == 1
    assert "desired package receipt must be caller-owned" in result.stderr
    assert "non-group-writable" in result.stderr
    assert not fixture.sudo_calls.exists()
    assert not fixture.installer_marker.exists()


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


def test_retired_hook_cannot_change_receipt_or_reach_execution(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    hook = _hook(
        tmp_path / "swap-receipt",
        f"printf '%s\\n' {'b' * 40} > {fixture.receipt}",
    )
    fixture.env["HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_AFTER_SUDO_HOOK"] = str(hook)

    result = fixture.run()

    assert result.returncode == 1
    assert "retired deferred-install privilege selectors are refused" in result.stderr
    assert fixture.receipt.read_text(encoding="utf-8") == f"{fixture.sha}\n"
    assert not fixture.sudo_calls.exists()
    assert not fixture.installer_marker.exists()


def test_retired_hook_cannot_change_stage_or_reach_execution(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    hook = _hook(
        tmp_path / "swap-stage",
        f"printf '%s\\n' '#!/usr/bin/bash' 'exit 0' > {fixture.stage / INSTALLER}",
    )
    fixture.env["HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_AFTER_SUDO_HOOK"] = str(hook)

    result = fixture.run()

    assert result.returncode == 1
    assert "retired deferred-install privilege selectors are refused" in result.stderr
    assert (fixture.stage / INSTALLER).read_bytes() == (fixture.repo / INSTALLER).read_bytes()
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
    assert "completed isolated-test" in stdout
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


def test_retired_hook_cannot_swap_activation_alias(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    replacement = tmp_path / "replacement-release"
    replacement.mkdir()
    (replacement / "not-a-git-release").write_text("alias swap target\n", encoding="utf-8")
    hook = _hook(
        tmp_path / "swap-alias",
        f"rm {fixture.repo_alias}\nln -s {replacement} {fixture.repo_alias}",
    )
    fixture.env["HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_AFTER_SUDO_HOOK"] = str(hook)

    result = fixture.run()

    assert result.returncode == 1
    assert "retired deferred-install privilege selectors are refused" in result.stderr
    assert fixture.repo_alias.resolve() == fixture.repo
    assert not fixture.installer_marker.exists()


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
