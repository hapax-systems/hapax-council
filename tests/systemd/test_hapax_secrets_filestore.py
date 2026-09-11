"""Council hapax-secrets unit and watchdog copies use FileStore, not pass show."""

import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT = REPO_ROOT / "systemd" / "units" / "hapax-secrets.service"
WATCHDOGS = REPO_ROOT / "systemd" / "watchdogs"
PRODUCER = REPO_ROOT / "scripts" / "secret_env_from_filestore.py"
AUTHORITY_ENV = "HAPAX_PUBLIC_GATE_AUTHORITY_HMAC_KEY"
AUTHORITY_ENTRY = "hapax-public-gate-authority-hmac-key"
AUTHORITY_FILE = "hapax-public-gate-authority.env"
AUTHORITY_VALUE = b"synthetic-public-gate-authority-key"  # pragma: allowlist secret
COMMON_BASELINE = (
    b"LITELLM_API_KEY=synthetic-litellm\n"  # pragma: allowlist secret
    b"LANGFUSE_PUBLIC_KEY=synthetic-langfuse-public\n"  # pragma: allowlist secret
    b"LANGFUSE_SECRET_KEY=synthetic-langfuse-secret\n"  # pragma: allowlist secret
    b"HF_TOKEN=synthetic-huggingface\n"  # pragma: allowlist secret
    b"MISTRAL_API_KEY=synthetic-mistral\n"  # pragma: allowlist secret
    b"OPENAI_API_KEY=synthetic-openai\n"  # pragma: allowlist secret
    b"HAPAX_OPERATOR_ORCID=0000-0000-0000-0000\n"
    b"LITELLM_BASE_URL=http://127.0.0.1:9\n"
    b"LITELLM_API_BASE=http://127.0.0.1:9\n"
    b"ANTHROPIC_API_KEY=synthetic-litellm\n"  # pragma: allowlist secret
    b"ANTHROPIC_BASE_URL=http://127.0.0.1:9\n"
    b"ANTHROPIC_AUTH_TOKEN=synthetic-litellm\n"  # pragma: allowlist secret
    b"LANGFUSE_HOST=http://127.0.0.1:10\n"
    b"HAPAX_SOUNDCLOUD_USERNAME=synthetic-operator\n"  # pragma: allowlist secret (synthetic literal; entropy false positive)
    b"HAPAX_MASTODON_INSTANCE_URL=https://mastodon.invalid\n"
    b"HAPAX_BLUESKY_HANDLE=synthetic.invalid\n"
)
MIGRATED_WATCHDOGS = (
    "briefing-watchdog",
    "digest-watchdog",
    "drift-watchdog",
    "health-watchdog",
    "knowledge-maint-watchdog",
    "meeting-prep-watchdog",
    "scout-watchdog",
)


def test_hapax_secrets_unit_uses_filestore_not_pass() -> None:
    text = UNIT.read_text(encoding="utf-8")
    producer = REPO_ROOT / "scripts" / "secret_env_from_filestore.py"
    assert producer.is_file()
    producer_text = producer.read_text(encoding="utf-8")
    assert "LITELLM_BASE_URL" in producer_text
    assert "HAPAX_OPERATOR_ORCID" in producer_text
    assert ".local/share/reins/current/api" in producer_text
    assert "projects/reins/api" not in producer_text
    assert "os.replace" in producer_text
    assert 'store.root / ".key"' in producer_text
    assert "pass show" not in text
    assert "PASSWORD_STORE_DIR" not in text
    assert "source-activation/worktree/scripts/secret_env_from_filestore.py" in text
    assert "OnFailure=notify-failure@%n.service" in text
    assert "/run/user/%U/hapax-secrets.env" in text
    assert "/run/user/1000/" not in text
    assert "install -m 600 /dev/null" not in text
    assert "ExecStartPre=" not in text
    assert "ExecStopPost=" not in text
    assert "ExecStop=" not in text
    assert "/bin/rm" not in text


def test_migrated_watchdogs_pin_activation_worktree() -> None:
    for name in MIGRATED_WATCHDOGS:
        text = (WATCHDOGS / name).read_text(encoding="utf-8")
        assert "/home/hapax/" not in text, f"{name} still bakes an operator home path"
        assert "source-activation/worktree" in text or "SOURCE_ACTIVATION" in text
        assert "HAPAX_SECRET:-${HOME}/.local/bin/hapax-secret" in text
        assert '"${HAPAX_SECRET}"' in text
        assert "hapax-secret litellm/" not in text


def _reins_pin() -> Path:
    return Path.home() / ".local/share/reins/current/api"


def _require_reins_pin() -> Path:
    pin = _reins_pin()
    if not (pin / "k0" / "key_capture.py").is_file():
        pytest.skip("reins FileStore pin not installed at ~/.local/share/reins/current/api")
    return pin


def _run_producer(env: dict[str, str], setup: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "import os, runpy, sys\n"
            + setup
            + "\nrunpy.run_path(sys.argv[1], run_name='__main__')",
            str(PRODUCER),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture
def producer_store(tmp_path, monkeypatch):
    pin = _require_reins_pin()
    store_root = tmp_path / "secrets"
    env_path = tmp_path / "hapax-secrets.env"
    monkeypatch.setenv("REINS_SECRET_STORE", str(store_root))
    monkeypatch.setenv("HAPAX_SECRETS_ENV_PATH", str(env_path))
    monkeypatch.setenv("HAPAX_LITELLM_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("HAPAX_LANGFUSE_HOST", "http://127.0.0.1:10")
    monkeypatch.setenv("HAPAX_SOUNDCLOUD_USERNAME", "synthetic-operator")
    monkeypatch.setenv("HAPAX_MASTODON_INSTANCE_URL", "https://mastodon.invalid")
    monkeypatch.setenv("HAPAX_BLUESKY_HANDLE", "synthetic.invalid")
    monkeypatch.setenv("HAPAX_REINS_API", str(pin))
    monkeypatch.syspath_prepend(str(pin))
    from k0.key_capture import FileStore

    store = FileStore(root=store_root)
    for name, value in (
        ("litellm-master-key", b"synthetic-litellm"),  # pragma: allowlist secret
        ("langfuse-public-key", b"synthetic-langfuse-public"),  # pragma: allowlist secret
        ("langfuse-secret-key", b"synthetic-langfuse-secret"),  # pragma: allowlist secret
        ("api-huggingface", b"synthetic-huggingface"),  # pragma: allowlist secret
        ("api-mistral", b"synthetic-mistral"),  # pragma: allowlist secret
        ("api-openai", b"synthetic-openai"),  # pragma: allowlist secret
        ("orcid-orcid", b"0000-0000-0000-0000"),  # pragma: allowlist secret
    ):
        store.put(name, value)
    return store, env_path


def test_producer_writes_env_from_filestore(producer_store) -> None:
    _, env_path = producer_store
    result = _run_producer(os.environ.copy())
    assert result.returncode == 0, result.stderr
    assert env_path.read_bytes() == COMMON_BASELINE
    assert oct(env_path.stat().st_mode)[-3:] == "600"


def test_producer_missing_key_does_not_clobber_env(tmp_path, monkeypatch) -> None:
    pin = _require_reins_pin()
    store_root = tmp_path / "secrets"
    store_root.mkdir()
    env_path = tmp_path / "hapax-secrets.env"
    prior = "LITELLM_API_KEY=synthetic-keep-me\n"  # pragma: allowlist secret
    env_path.write_text(prior)
    os.chmod(env_path, 0o600)
    monkeypatch.setenv("REINS_SECRET_STORE", str(store_root))
    monkeypatch.setenv("HAPAX_SECRETS_ENV_PATH", str(env_path))
    monkeypatch.setenv("HAPAX_REINS_API", str(pin))
    result = _run_producer(os.environ.copy())
    assert result.returncode == 2
    assert "missing" in result.stderr or ".key" in result.stderr
    assert env_path.read_text(encoding="utf-8") == prior
    assert not (store_root / ".key").exists()


def test_producer_missing_required_secret_keeps_prior_env(tmp_path, monkeypatch) -> None:
    pin = _require_reins_pin()
    store_root = tmp_path / "secrets"
    env_path = tmp_path / "hapax-secrets.env"
    prior = "LITELLM_API_KEY=synthetic-keep-me\n"  # pragma: allowlist secret
    env_path.write_text(prior)
    monkeypatch.setenv("REINS_SECRET_STORE", str(store_root))
    monkeypatch.setenv("HAPAX_SECRETS_ENV_PATH", str(env_path))
    monkeypatch.setenv("HAPAX_REINS_API", str(pin))
    monkeypatch.syspath_prepend(str(pin))
    from k0.key_capture import FileStore

    store = FileStore(root=store_root)
    store.put("litellm-master-key", b"synthetic-litellm")  # pragma: allowlist secret
    result = _run_producer(os.environ.copy())
    assert result.returncode == 2
    assert "missing" in result.stderr
    assert env_path.read_text(encoding="utf-8") == prior


def test_producer_authority_file_contains_only_signing_key(producer_store) -> None:
    store, common = producer_store
    store.put(AUTHORITY_ENTRY, AUTHORITY_VALUE)
    result = _run_producer(os.environ.copy())
    assert result.returncode == 0, result.stderr
    authority = common.with_name(AUTHORITY_FILE)
    assert authority.read_bytes() == AUTHORITY_ENV.encode() + b"=" + AUTHORITY_VALUE + b"\n"
    assert authority.stat().st_mode & 0o777 == 0o600
    assert AUTHORITY_VALUE.decode() not in result.stdout + result.stderr


def test_producer_authority_key_does_not_change_common_bytes(producer_store) -> None:
    store, common = producer_store
    assert _run_producer(os.environ.copy()).returncode == 0
    baseline = common.read_bytes()
    assert baseline == COMMON_BASELINE
    store.put(AUTHORITY_ENTRY, AUTHORITY_VALUE)
    result = _run_producer(os.environ.copy())
    assert result.returncode == 0, result.stderr
    assert common.read_bytes() == baseline
    assert AUTHORITY_ENV.encode() not in common.read_bytes()


@pytest.mark.parametrize("stale", [False, True])
def test_producer_absent_authority_removes_stale_file(producer_store, stale) -> None:
    store, common = producer_store
    authority = common.with_name(AUTHORITY_FILE)
    if stale:
        authority.write_bytes(AUTHORITY_VALUE)
    result = _run_producer(os.environ.copy())
    assert result.returncode == 0, result.stderr
    assert not authority.exists()
    assert common.read_bytes() == COMMON_BASELINE
    assert not store.has(AUTHORITY_ENTRY)


@pytest.mark.parametrize(
    ("fault", "diagnostic", "repair"),
    [
        ("missing-root", "FileStore root", "enroll FileStore"),
        ("missing-key", ".key", "enroll FileStore"),
        ("root-mode", "mode", "chmod 700"),
        ("key-mode", ".key", "chmod 600"),
        ("unreadable-root", "mode", "chmod 700"),
        ("unreadable-key", ".key", "chmod 600"),
        ("wrong-owner", "owner", "ownership"),
        ("unreadable-entry", AUTHORITY_ENTRY, "read access"),
        ("missing-required", "api-openai", "FileStore.put"),
    ],
)
def test_producer_prerequisite_failure_preserves_both_files(
    producer_store, fault, diagnostic, repair
) -> None:
    store, common = producer_store
    store.put(AUTHORITY_ENTRY, AUTHORITY_VALUE)
    authority = common.with_name(AUTHORITY_FILE)
    common.write_bytes(COMMON_BASELINE)
    authority.write_bytes(AUTHORITY_VALUE)
    inodes = (common.stat().st_ino, authority.stat().st_ino)
    setup = ""
    if fault == "missing-root":
        store.root.rename(store.root.with_name("missing-store"))
    elif fault == "missing-key":
        (store.root / ".key").unlink()
    elif fault in ("root-mode", "unreadable-root"):
        store.root.chmod(0o755 if fault == "root-mode" else 0o000)
    elif fault in ("key-mode", "unreadable-key"):
        (store.root / ".key").chmod(0o644 if fault == "key-mode" else 0o000)
    elif fault == "wrong-owner":
        setup = "uid = os.getuid()\nos.getuid = lambda: uid + 1"
    elif fault == "unreadable-entry":
        (store.root / f"{AUTHORITY_ENTRY}.bin").chmod(0o000)
    elif fault == "missing-required":
        store.delete("api-openai")
    try:
        result = _run_producer(os.environ.copy(), setup)
    finally:
        if fault in ("root-mode", "unreadable-root"):
            store.root.chmod(0o700)
    assert result.returncode == 2, result.stderr
    assert diagnostic in result.stderr
    assert "Next action:" in result.stderr
    assert repair in result.stderr
    assert common.read_bytes() == COMMON_BASELINE
    assert authority.read_bytes() == AUTHORITY_VALUE
    assert (common.stat().st_ino, authority.stat().st_ino) == inodes
    assert not list(common.parent.glob(".*.tmp"))
    assert AUTHORITY_VALUE.decode() not in result.stdout + result.stderr


@pytest.mark.parametrize("filename", ["hapax-secrets.env", AUTHORITY_FILE])
def test_producer_replaces_files_with_one_atomic_rename(
    producer_store, monkeypatch, filename
) -> None:
    store, common = producer_store
    store.put(AUTHORITY_ENTRY, AUTHORITY_VALUE)
    target = common.with_name(filename)
    target.write_bytes(b"synthetic-prior-env\n")  # pragma: allowlist secret
    target.chmod(0o644)
    prior = target.read_bytes()
    inode = target.stat().st_ino
    replace = os.replace
    replacements = []

    def observe_replace(src, dst):
        if dst == target:
            assert target.read_bytes() == prior
            assert Path(src).stat().st_mode & 0o777 == 0o600
            replacements.append((src, dst))
        replace(src, dst)

    monkeypatch.setattr(os, "replace", observe_replace)
    runpy.run_path(str(PRODUCER), run_name="__main__")
    assert replacements == [(target.with_name(f".{filename}.tmp"), target)]
    assert target.stat().st_ino != inode
    assert target.stat().st_mode & 0o777 == 0o600
    assert not list(common.parent.glob(".*.tmp"))


@pytest.mark.parametrize("filename", ["hapax-secrets.env", AUTHORITY_FILE])
def test_producer_mid_write_failure_preserves_final_file(
    producer_store, monkeypatch, filename
) -> None:
    store, common = producer_store
    store.put(AUTHORITY_ENTRY, AUTHORITY_VALUE)
    target = common.with_name(filename)
    prior = b"synthetic-prior-env\n"  # pragma: allowlist secret
    target.write_bytes(prior)
    inode = target.stat().st_ino
    write = os.write

    def fail_mid_write(fd, data):
        # Observe the real fd without reading any process environment or live file.
        path = Path(os.readlink(f"/proc/self/fd/{fd}"))
        if path in (target, target.with_name(f".{filename}.tmp")):
            write(fd, data[:7])
            assert target.read_bytes() == prior
            raise OSError("synthetic mid-write failure")
        return write(fd, data)

    monkeypatch.setattr(os, "write", fail_mid_write)
    with pytest.raises(OSError, match="synthetic mid-write failure"):
        runpy.run_path(str(PRODUCER), run_name="__main__")
    assert target.read_bytes() == prior
    assert target.stat().st_ino == inode
    assert not list(common.parent.glob(".*.tmp"))


def test_producer_short_writes_do_not_publish_partial_env(producer_store, monkeypatch) -> None:
    store, common = producer_store
    store.put(AUTHORITY_ENTRY, AUTHORITY_VALUE)
    write = os.write
    monkeypatch.setattr(os, "write", lambda fd, data: write(fd, data[:7]))
    runpy.run_path(str(PRODUCER), run_name="__main__")
    assert common.read_bytes() == COMMON_BASELINE
    assert common.with_name(AUTHORITY_FILE).read_bytes() == (
        AUTHORITY_ENV.encode() + b"=" + AUTHORITY_VALUE + b"\n"
    )


def test_produced_authority_is_scrubbed_from_reviewer_child(producer_store, monkeypatch) -> None:
    import importlib.util

    store, common = producer_store
    store.put(AUTHORITY_ENTRY, AUTHORITY_VALUE)
    result = _run_producer(os.environ.copy())
    assert result.returncode == 0, result.stderr
    name, value = common.with_name(AUTHORITY_FILE).read_text().strip().split("=", 1)
    monkeypatch.setenv(name, value)
    task_names = (
        "HAPAX_GLMCP_REVIEW_TASK_ID",
        "HAPAX_CC_TASK_ID",
        "HAPAX_GLMCP_REVIEW_TASK_HASH",
        "HAPAX_CC_TASK_HASH",
    )
    for task_name in task_names:
        monkeypatch.setenv(task_name, "synthetic-parent-task")
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "authority_delivery_dispatch", REPO_ROOT / "scripts" / "cc-pr-review-dispatch.py"
    )
    assert spec and spec.loader
    dispatch = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, dispatch)
    spec.loader.exec_module(dispatch)
    child = dispatch.default_reviewer_runner(
        dispatch.review_team.Seat(id="synthetic-seat", family="glm"),
        {
            "reviewer_command": [
                sys.executable,
                "-c",
                "import os, sys; "
                "assert all(name not in os.environ for name in sys.argv[1:]); "
                "assert os.environ['HAPAX_REVIEW_SEAT_ID'] == 'synthetic-seat'; "
                "assert os.environ['HAPAX_REVIEW_FAMILY'] == 'glm'; print('scrubbed')",
                AUTHORITY_ENV,
                *task_names,
            ],
            "timeout_seconds": 10,
        },
        "synthetic prompt",
    )
    assert child.stdout == "scrubbed\n"


def test_systemd_watchdogs_use_hapax_secret_not_pass_show() -> None:
    for name in MIGRATED_WATCHDOGS:
        path = WATCHDOGS / name
        assert path.is_file(), f"missing watchdog: {name}"
        text = path.read_text(encoding="utf-8")
        assert "pass show" not in text, f"{path.name} still contains pass show"
        assert "hapax-secret" in text, f"{path.name} does not call hapax-secret"
