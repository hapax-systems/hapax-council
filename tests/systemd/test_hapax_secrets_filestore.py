"""Council hapax-secrets unit and watchdog copies use FileStore, not pass show."""

import json
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
REQUIRED_VALUES = {
    "litellm-master-key": b"synthetic-litellm",  # pragma: allowlist secret
    "langfuse-public-key": b"synthetic-langfuse-public",  # pragma: allowlist secret
    "langfuse-secret-key": b"synthetic-langfuse-secret",  # pragma: allowlist secret
    "api-huggingface": b"synthetic-huggingface",  # pragma: allowlist secret
    "api-mistral": b"synthetic-mistral",  # pragma: allowlist secret
    "api-openai": b"synthetic-openai",  # pragma: allowlist secret
}
OPTIONAL_ENTRIES = (
    "soundcloud-client-id",
    "soundcloud-client-secret",
    "soundcloud-banked-url-canonical",
    "mastadon-access-token",
    "bluesky-operator-app-password",
    "bluesky-operator-did",
    "ia-access-key",
    "ia-secret-key",
    "osf-api-token",
    "philarchive-session-cookie",
    "philarchive-author-id",
    "zenodo-api-token",
    "orcid-orcid",
    "kofi-verification-token",
)
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
        timeout=30,
    )


@pytest.fixture(autouse=True)
def producer_sandbox(tmp_path, monkeypatch):
    """Every producer invocation is isolated from live stores, helpers and ssh."""
    monkeypatch.delenv("HAPAX_SECRETS_SOURCE", raising=False)
    monkeypatch.delenv("HAPAX_SECRET_HELPER", raising=False)
    monkeypatch.setenv("REINS_SECRET_STORE", str(tmp_path / "secrets"))
    monkeypatch.setenv("HAPAX_REINS_API", str(tmp_path / "unavailable-api"))
    monkeypatch.setenv("HAPAX_SECRETS_ENV_PATH", str(tmp_path / "hapax-secrets.env"))
    monkeypatch.setenv("HAPAX_LITELLM_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("HAPAX_LANGFUSE_HOST", "http://127.0.0.1:10")
    monkeypatch.setenv("HAPAX_SOUNDCLOUD_USERNAME", "synthetic-operator")
    monkeypatch.setenv("HAPAX_MASTODON_INSTANCE_URL", "https://mastodon.invalid")
    monkeypatch.setenv("HAPAX_BLUESKY_HANDLE", "synthetic.invalid")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("hapax-secret", "ssh"):
        shim = bin_dir / name
        marker = tmp_path / f"unexpected-{name}"
        shim.write_text(
            f"#!{sys.executable}\nfrom pathlib import Path\n"
            f"Path({str(marker)!r}).touch()\nraise SystemExit(99)\n"
        )
        shim.chmod(0o700)
    # A non-executable shim must not let lookup continue to an installed helper.
    monkeypatch.setenv("PATH", str(bin_dir))
    yield
    assert not (tmp_path / "unexpected-hapax-secret").exists()
    assert not (tmp_path / "unexpected-ssh").exists()


@pytest.fixture
def helper_source(tmp_path, monkeypatch):
    helper = tmp_path / "bin" / "hapax-secret"
    helper.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys, time\n"
        "from pathlib import Path\n"
        "operation = 'where' if sys.argv[1] == '--where' else 'get'\n"
        "name = sys.argv[-1]\n"
        "with Path(os.environ['SYNTHETIC_HELPER_CALLS']).open('a') as log:\n"
        "    log.write(('--where ' if operation == 'where' else '') + name + '\\n')\n"
        "entry = json.loads(os.environ['SYNTHETIC_HELPER_TABLE']).get(name, {})\n"
        "default = entry if operation == 'get' else {'action': "
        "'absent' if entry.get('action', 'absent') == 'absent' else 'present'}\n"
        "entry = entry.get(operation, default)\n"
        "action = entry.get('action', 'absent')\n"
        "if action == 'store':\n"
        "    sys.path.insert(0, os.environ['HAPAX_REINS_API'])\n"
        "    from k0.key_capture import FileStore\n"
        "    store = FileStore(root=Path(os.environ['REINS_SECRET_STORE']))\n"
        "    if operation == 'where':\n"
        "        action = 'present' if store.has(name) else 'absent'\n"
        "    else:\n"
        "        value = store.get(name)\n"
        "        action = 'absent' if value is None else 'value'\n"
        "        if value is not None:\n"
        "            entry['hex'] = value.hex()\n"
        "if action == 'present':\n"
        "    print('filestore')\n"
        "    sys.exit(0)\n"
        "if action == 'absent':\n"
        "    if operation == 'where':\n"
        "        print(f'not found: {name}')\n"
        "        sys.exit(1)\n"
        "    sys.stderr.write(f'not found in FileStore: {name}. legal_next: '"
        "'run hapax-secret (TTY put) via reins.\\n')\n"
        "    sys.exit(1)\n"
        "if action == 'hang':\n"
        "    time.sleep(22)\n"
        "if action == 'remove-helper':\n"
        "    Path(sys.argv[0]).unlink()\n"
        "    print('filestore')\n"
        "    sys.exit(0)\n"
        "if action == 'exit':\n"
        "    sys.stderr.write('synthetic-private-error-detail\\n')\n"  # pragma: allowlist secret
        "    sys.exit(entry['code'])\n"
        "if action == 'bad-absence':\n"
        "    sys.stderr.write('not found in FileStore: wrong-name. legal_next: '"
        "'run hapax-secret (TTY put) via reins.\\n')\n"
        "    sys.exit(1)\n"
        "sys.stdout.buffer.write(bytes.fromhex(entry['hex']))\n"
        "sys.exit(entry.get('code', 0))\n"
    )
    helper.chmod(0o700)
    monkeypatch.setenv("HAPAX_SECRETS_SOURCE", "helper")
    monkeypatch.setenv("SYNTHETIC_HELPER_CALLS", str(tmp_path / "helper-calls"))
    values = {
        **REQUIRED_VALUES,
        "orcid-orcid": b"0000-0000-0000-0000",  # pragma: allowlist secret
        AUTHORITY_ENTRY: AUTHORITY_VALUE,
    }
    table = {name: {"action": "value", "hex": value.hex()} for name, value in values.items()}
    return table, helper, tmp_path / "hapax-secrets.env"


def _run_helper(table, setup=""):
    env = os.environ.copy()
    env["SYNTHETIC_HELPER_TABLE"] = json.dumps(table)
    return _run_producer(env, setup)


def _expected_helper_calls():
    return [
        call
        for name in (*REQUIRED_VALUES, *OPTIONAL_ENTRIES, AUTHORITY_ENTRY)
        for call in (f"--where {name}", name)
    ]


def _prior_files(common):
    authority = common.with_name(AUTHORITY_FILE)
    common.write_bytes(COMMON_BASELINE)
    authority.write_bytes(AUTHORITY_VALUE)
    return authority, (common.stat().st_ino, authority.stat().st_ino)


def _assert_read_refusal(result, common, authority, inodes, name, diagnostic):
    assert result.returncode == 2, "failed read must refuse before publishing either file"
    assert common.read_bytes() == COMMON_BASELINE
    assert authority.is_file(), "failed authority read must never delete the prior authority file"
    assert authority.read_bytes() == AUTHORITY_VALUE
    assert (common.stat().st_ino, authority.stat().st_ino) == inodes
    assert name in result.stderr and diagnostic in result.stderr
    assert "Next action:" in result.stderr
    assert not result.stdout
    assert "Traceback" not in result.stderr
    assert AUTHORITY_VALUE.decode() not in result.stderr
    assert "synthetic-private-error-detail" not in result.stderr  # pragma: allowlist secret
    assert not list(common.parent.glob(".*.tmp"))


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

    store_root.mkdir(mode=0o700)
    key = store_root / ".key"
    key.write_bytes(b"synthetic-filestore-test-key-0000")  # pragma: allowlist secret
    key.chmod(0o600)
    store = FileStore(root=store_root)
    for name, value in REQUIRED_VALUES.items():
        store.put(name, value)
    store.put("orcid-orcid", b"0000-0000-0000-0000")  # pragma: allowlist secret
    return store, env_path


@pytest.mark.parametrize("source", ["filestore", "helper"])
@pytest.mark.parametrize("name", ["api-openai", "soundcloud-client-id", AUTHORITY_ENTRY])
@pytest.mark.parametrize("damage", ["truncate", "mac"])
def test_corrupt_blob_refuses_without_deleting_authority(
    producer_store, helper_source, monkeypatch, source, name, damage
):
    store, common = producer_store
    table, _, _ = helper_source
    store.put(name, AUTHORITY_VALUE)
    blob = store.root / f"{name}.bin"
    raw = blob.read_bytes()
    blob.write_bytes(
        raw[:8] if damage == "truncate" else raw[:16] + bytes([raw[16] ^ 1]) + raw[17:]
    )
    assert store.has(name) and store.get(name) is None
    table[name] = {"where": {"action": "store"}, "get": {"action": "store"}}
    authority, inodes = _prior_files(common)
    monkeypatch.setenv("HAPAX_SECRETS_SOURCE", source)
    result = _run_helper(table) if source == "helper" else _run_producer(os.environ.copy())
    _assert_read_refusal(result, common, authority, inodes, name, "present-but-unreadable")


@pytest.mark.parametrize("source", ["filestore", "helper"])
@pytest.mark.parametrize("name", ["api-openai", "soundcloud-client-id", AUTHORITY_ENTRY])
@pytest.mark.parametrize(
    ("raw", "diagnostic"),
    [
        (b"synthetic-\xff", "decoding"),  # pragma: allowlist secret
        (b"synthetic\n\xff", "decoding"),  # pragma: allowlist secret
        (b"synthetic\0", "control"),  # pragma: allowlist secret
        (b"synthetic\t", "control"),  # pragma: allowlist secret
        (b"synthetic\r\n", "control"),  # pragma: allowlist secret
        (b"synthetic\x7f", "control"),  # pragma: allowlist secret
        (b"synthetic\xc2\x85", "control"),  # pragma: allowlist secret
        (b"synthetic\nsynthetic-tail", "control"),  # pragma: allowlist secret
    ],
    ids=["utf8", "utf8-tail", "nul", "tab", "crlf", "del", "c1", "embedded-newline"],
)
def test_invalid_value_refuses_before_publication(
    producer_store, helper_source, monkeypatch, source, name, raw, diagnostic
):
    store, common = producer_store
    table, _, _ = helper_source
    store.put(name, raw)
    table[name] = {"action": "value", "hex": raw.hex()}
    authority, inodes = _prior_files(common)
    monkeypatch.setenv("HAPAX_SECRETS_SOURCE", source)
    result = _run_helper(table) if source == "helper" else _run_producer(os.environ.copy())
    _assert_read_refusal(result, common, authority, inodes, name, diagnostic)


@pytest.mark.parametrize("present", [False, True])
@pytest.mark.parametrize("name", ["api-openai", "soundcloud-client-id", AUTHORITY_ENTRY])
def test_helper_where_and_get_classify_absence(helper_source, name, present):
    table, _, common = helper_source
    authority, inodes = _prior_files(common)
    table[name] = {
        "where": {"action": "present" if present else "absent"},
        "get": {"action": "absent"},
    }
    result = _run_helper(table)
    if present:
        _assert_read_refusal(result, common, authority, inodes, name, "present-but-unreadable")
    elif name in REQUIRED_VALUES:
        _assert_read_refusal(result, common, authority, inodes, name, "missing")
    else:
        assert result.returncode == 0, result.stderr
        assert common.read_bytes() == COMMON_BASELINE
        assert common.stat().st_ino != inodes[0], "successful optional absence refreshes common"
        assert authority.exists() == (name != AUTHORITY_ENTRY)
    calls = (common.parent / "helper-calls").read_text().splitlines()
    index = calls.index(name)
    assert calls[index - 1] == f"--where {name}"
    assert calls.count(name) == 1 and calls.count(f"--where {name}") == 1


@pytest.mark.parametrize("name", ["api-openai", "soundcloud-client-id", AUTHORITY_ENTRY])
@pytest.mark.parametrize("code", [255, 2, 1])
def test_where_transport_failure_alone_refuses(helper_source, name, code):
    table, _, common = helper_source
    authority, inodes = _prior_files(common)
    table[name] = {
        "where": {"action": "exit", "code": code},
        "get": {"action": "value", "hex": AUTHORITY_VALUE.hex()},
    }
    result = _run_helper(table)
    _assert_read_refusal(result, common, authority, inodes, name, f"transport exit {code}")
    calls = (common.parent / "helper-calls").read_text().splitlines()
    assert calls[-1] == f"--where {name}"
    assert name not in calls


def test_where_timeout_refuses(helper_source):
    table, _, common = helper_source
    authority, inodes = _prior_files(common)
    table[AUTHORITY_ENTRY]["where"] = {"action": "hang"}
    result = _run_helper(table)
    _assert_read_refusal(result, common, authority, inodes, AUTHORITY_ENTRY, "timeout after 20s")
    assert (common.parent / "helper-calls").read_text().splitlines()[-1] == (
        f"--where {AUTHORITY_ENTRY}"
    )


def test_get_launch_oserror_after_where_preserves_files(helper_source):
    table, _, common = helper_source
    authority, inodes = _prior_files(common)
    table[AUTHORITY_ENTRY]["where"] = {"action": "remove-helper"}
    result = _run_helper(table)
    _assert_read_refusal(result, common, authority, inodes, AUTHORITY_ENTRY, "launch OSError")


@pytest.mark.parametrize("operation", ["has", "get"])
@pytest.mark.parametrize("exception", ["OSError", "ValueError", "RuntimeError"])
def test_store_exceptions_preserve_files(producer_store, operation, exception):
    _, common = producer_store
    authority, inodes = _prior_files(common)
    setup = (
        "sys.path.insert(0, os.environ['HAPAX_REINS_API'])\n"
        "from k0.key_capture import FileStore\n"
        f"original = FileStore.{operation}\n"
        "def fail(store, name):\n"
        "    if name == 'api-openai':\n"
        f"        raise {exception}('synthetic-private-error-detail')\n"  # pragma: allowlist secret
        "    return original(store, name)\n"
        f"FileStore.{operation} = fail\n"
    )
    result = _run_producer(os.environ.copy(), setup)
    _assert_read_refusal(result, common, authority, inodes, "api-openai", exception)


def test_store_initialization_exception_preserves_files(producer_store):
    _, common = producer_store
    authority, inodes = _prior_files(common)
    setup = (
        "sys.path.insert(0, os.environ['HAPAX_REINS_API'])\n"
        "import k0.key_capture\n"
        "def fail():\n"
        "    raise ValueError('synthetic-private-error-detail')\n"  # pragma: allowlist secret
        "k0.key_capture.default_store = fail\n"
    )
    result = _run_producer(os.environ.copy(), setup)
    _assert_read_refusal(result, common, authority, inodes, "FileStore", "ValueError")


@pytest.mark.parametrize("mode", [0o750, 0o500, 0o1700])
def test_filestore_root_mode_is_exact(producer_store, mode):
    store, common = producer_store
    authority, inodes = _prior_files(common)
    store.root.chmod(mode)
    try:
        result = _run_producer(os.environ.copy())
    finally:
        store.root.chmod(0o700)
    _assert_read_refusal(result, common, authority, inodes, "FileStore", "chmod 700")


@pytest.mark.parametrize("mode", [0o640, 0o400, 0o1600])
def test_filestore_key_mode_is_exact(producer_store, mode):
    store, common = producer_store
    authority, inodes = _prior_files(common)
    (store.root / ".key").chmod(mode)
    result = _run_producer(os.environ.copy())
    _assert_read_refusal(result, common, authority, inodes, ".key", "chmod 600")


@pytest.mark.parametrize("source", ["filestore", "helper"])
@pytest.mark.parametrize("stage", ["replace", "open"])
@pytest.mark.parametrize("prior", [False, True])
def test_second_publication_failure_names_partial_outcome(
    producer_store, helper_source, monkeypatch, source, stage, prior
):
    store, common = producer_store
    table, _, _ = helper_source
    store.put(AUTHORITY_ENTRY, AUTHORITY_VALUE)
    authority, inodes = _prior_files(common)
    if not prior:
        authority.unlink()
    monkeypatch.setenv("HAPAX_SECRETS_SOURCE", source)
    setup = (
        f"original = os.{stage}\n"
        "calls = 0\n"
        "def fail_second(*args, **kwargs):\n"
        "    global calls\n"
        "    calls += 1\n"
        "    if calls == 2:\n"
        "        raise OSError('synthetic-private-error-detail')\n"  # pragma: allowlist secret
        "    return original(*args, **kwargs)\n"
        f"os.{stage} = fail_second\n"
    )
    # FileStore._key also uses os.open; restrict injection to publication temporaries.
    if stage == "open":
        setup = setup.replace(
            "    calls += 1",
            "    if str(args[0]).endswith('.env.tmp'):\n        calls += 1",
        )
    result = (
        _run_helper(table, setup) if source == "helper" else _run_producer(os.environ.copy(), setup)
    )
    assert result.returncode == 2
    assert common.read_bytes() == COMMON_BASELINE
    assert common.stat().st_ino != inodes[0], "first replacement must have succeeded"
    assert authority.exists() == prior
    if prior:
        assert authority.read_bytes() == AUTHORITY_VALUE
        assert authority.stat().st_ino == inodes[1]
    outcome = "retained" if prior else "absent"
    assert (
        f"common refreshed; authority replacement failed at {authority}; prior authority file {outcome}"
        in result.stderr
    )
    assert "Next action:" in result.stderr
    assert "Traceback" not in result.stderr
    assert "synthetic-private-error-detail" not in result.stderr  # pragma: allowlist secret
    assert AUTHORITY_VALUE.decode() not in result.stdout + result.stderr
    assert not list(common.parent.glob(".*.tmp"))


@pytest.mark.parametrize("source", [None, "filestore"])
def test_producer_writes_env_from_filestore(producer_store, monkeypatch, source) -> None:
    _, env_path = producer_store
    if source is not None:
        monkeypatch.setenv("HAPAX_SECRETS_SOURCE", source)
    result = _run_producer(os.environ.copy())
    assert result.returncode == 0, result.stderr
    assert env_path.read_bytes() == COMMON_BASELINE
    assert oct(env_path.stat().st_mode)[-3:] == "600"
    assert "source=filestore backend=file" in result.stdout


@pytest.mark.parametrize("source", ["unknown", "", "HELPER", " helper "])
def test_unknown_source_refuses_before_writing(producer_store, monkeypatch, source) -> None:
    _, common = producer_store
    monkeypatch.setenv("HAPAX_SECRETS_SOURCE", source)
    result = _run_producer(os.environ.copy())
    assert result.returncode == 2, "unknown source must refuse"
    assert "HAPAX_SECRETS_SOURCE" in result.stderr
    assert "filestore" in result.stderr and "helper" in result.stderr
    assert "Next action:" in result.stderr
    assert not common.exists()
    assert not common.with_name(AUTHORITY_FILE).exists()


@pytest.mark.parametrize("override", [False, True])
def test_helper_skips_filestore_prerequisites(helper_source, monkeypatch, override) -> None:
    table, helper, common = helper_source
    if override:
        helper = helper.rename(helper.with_name("synthetic-override"))
        monkeypatch.setenv("HAPAX_SECRET_HELPER", str(helper))
    # Fail even if the module is available through an ambient PYTHONPATH.
    setup = (
        "import builtins\n"
        "real_import = builtins.__import__\n"
        "def no_filestore(name, *args, **kwargs):\n"
        "    if name == 'k0' or name.startswith('k0.'):\n"
        "        raise ImportError('synthetic unavailable FileStore pin')\n"
        "    return real_import(name, *args, **kwargs)\n"
        "builtins.__import__ = no_filestore\n"
    )
    result = _run_helper(table, setup)
    assert result.returncode == 0, result.stderr
    assert common.read_bytes() == COMMON_BASELINE
    assert common.with_name(AUTHORITY_FILE).read_bytes() == (
        AUTHORITY_ENV.encode() + b"=" + AUTHORITY_VALUE + b"\n"
    )
    assert "source=helper backend=filestore-via-helper" in result.stdout
    assert not (common.parent / "secrets").exists()
    assert (common.parent / "helper-calls").read_text().splitlines() == _expected_helper_calls()
    assert AUTHORITY_VALUE.decode() not in result.stdout + result.stderr


def test_helper_present_matches_filestore_bytes(producer_store, helper_source, monkeypatch):
    store, common = producer_store
    table, _, _ = helper_source
    values = dict(REQUIRED_VALUES)
    for name in OPTIONAL_ENTRIES:
        values[name] = b"synthetic-optional"  # pragma: allowlist secret
    values["api-openai"] = b""  # pragma: allowlist secret
    values[AUTHORITY_ENTRY] = AUTHORITY_VALUE + b"\n"
    for name, value in values.items():
        store.put(name, value)
        table[name] = {"action": "value", "hex": (value.rstrip(b"\n") + b"\n").hex()}
    monkeypatch.setenv("HAPAX_SECRETS_SOURCE", "filestore")
    assert _run_producer(os.environ.copy()).returncode == 0
    authority = common.with_name(AUTHORITY_FILE)
    baseline = (common.read_bytes(), authority.read_bytes())
    monkeypatch.setenv("HAPAX_SECRETS_SOURCE", "helper")
    result = _run_helper(table)
    assert result.returncode == 0, result.stderr
    assert "source=helper" in result.stdout
    assert (common.read_bytes(), authority.read_bytes()) == baseline
    assert common.stat().st_mode & 0o777 == 0o600
    assert authority.stat().st_mode & 0o777 == 0o600
    assert not list(common.parent.glob(".*.tmp"))


def test_helper_absent_optional_and_authority(helper_source):
    table, _, common = helper_source
    assert _run_helper(table).returncode == 0
    authority = common.with_name(AUTHORITY_FILE)
    baseline = common.read_bytes()
    table[AUTHORITY_ENTRY] = {"action": "absent"}
    result = _run_helper(table)
    assert result.returncode == 0, result.stderr
    assert common.read_bytes() == baseline == COMMON_BASELINE
    assert not authority.exists()
    assert b"SOUNDCLOUD_CLIENT_ID=" not in baseline


@pytest.mark.parametrize("name", list(REQUIRED_VALUES))
def test_helper_required_absent_preserves_files(helper_source, name):
    table, _, common = helper_source
    authority = common.with_name(AUTHORITY_FILE)
    common.write_bytes(COMMON_BASELINE)
    authority.write_bytes(AUTHORITY_VALUE)
    inodes = (common.stat().st_ino, authority.stat().st_ino)
    table[name] = {"action": "absent"}
    result = _run_helper(table)
    assert result.returncode == 2
    assert name in result.stderr
    assert "Next action:" in result.stderr and "TTY put" in result.stderr
    assert common.read_bytes() == COMMON_BASELINE
    assert authority.read_bytes() == AUTHORITY_VALUE
    assert (common.stat().st_ino, authority.stat().st_ino) == inodes


@pytest.mark.parametrize("name", ["api-openai", "soundcloud-client-id", AUTHORITY_ENTRY])
@pytest.mark.parametrize(
    ("fault", "diagnostic"),
    [
        ({"action": "exit", "code": 255}, "transport exit 255"),
        ({"action": "exit", "code": 2}, "transport exit 2"),
        ({"action": "exit", "code": 1}, "transport exit 1"),
        ({"action": "bad-absence"}, "transport exit 1"),
        ({"action": "value", "hex": "ff"}, "decoding"),  # pragma: allowlist secret
        ({"action": "value", "hex": "0aff"}, "decoding"),  # pragma: allowlist secret
    ],
    ids=["ssh-255", "exit-2", "exit-1", "wrong-absence", "decode", "decode-second-line"],
)
def test_helper_failure_preserves_both_files(helper_source, name, fault, diagnostic):
    table, _, common = helper_source
    authority = common.with_name(AUTHORITY_FILE)
    common.write_bytes(COMMON_BASELINE)
    authority.write_bytes(AUTHORITY_VALUE)
    inodes = (common.stat().st_ino, authority.stat().st_ino)
    table[name] = fault
    result = _run_helper(table)
    assert common.read_bytes() == COMMON_BASELINE
    assert authority.read_bytes() == AUTHORITY_VALUE
    assert (common.stat().st_ino, authority.stat().st_ino) == inodes, "published before resolution"
    assert result.returncode == 2, "helper failure must refuse without fallback"
    assert name in result.stderr and diagnostic in result.stderr
    assert "Next action:" in result.stderr
    assert "HAPAX_SECRETS_HOST" in result.stderr and "enrollment" in result.stderr
    log = result.stdout + result.stderr
    assert AUTHORITY_VALUE.decode() not in log
    assert "synthetic-private-error-detail" not in log  # pragma: allowlist secret
    assert not list(common.parent.glob(".*.tmp"))
    calls = (common.parent / "helper-calls").read_text().splitlines()
    expected = _expected_helper_calls()
    assert calls == expected[: expected.index(name) + 1]


def test_helper_failure_never_uses_available_filestore(producer_store, helper_source):
    # Keep the transport matrix runnable without reins; this separate parity
    # pin makes fallback observable even when the local store could succeed.
    store, common = producer_store
    store.put(AUTHORITY_ENTRY, AUTHORITY_VALUE)
    table, _, _ = helper_source
    table[AUTHORITY_ENTRY] = {"action": "exit", "code": 255}
    result = _run_helper(table)
    assert result.returncode == 2, "helper failure must refuse without fallback"
    assert not common.exists()
    assert not common.with_name(AUTHORITY_FILE).exists()


def test_helper_timeout_preserves_both_files(helper_source):
    table, _, common = helper_source
    authority = common.with_name(AUTHORITY_FILE)
    common.write_bytes(COMMON_BASELINE)
    authority.write_bytes(AUTHORITY_VALUE)
    inodes = (common.stat().st_ino, authority.stat().st_ino)
    table[AUTHORITY_ENTRY]["action"] = "hang"
    result = _run_helper(table)
    assert result.returncode == 2, "helper call must time out before the 22-second hang ends"
    assert AUTHORITY_ENTRY in result.stderr and "timeout" in result.stderr
    assert "20" in result.stderr
    assert "Next action:" in result.stderr
    assert "HAPAX_SECRETS_HOST" in result.stderr and "enrollment" in result.stderr
    assert common.read_bytes() == COMMON_BASELINE
    assert authority.read_bytes() == AUTHORITY_VALUE
    assert (common.stat().st_ino, authority.stat().st_ino) == inodes
    assert not list(common.parent.glob(".*.tmp"))


@pytest.mark.parametrize("fault", ["missing", "not-executable", "launch-oserror"])
def test_helper_executable_failure_preserves_files(helper_source, monkeypatch, fault):
    table, helper, common = helper_source
    if fault == "missing":
        monkeypatch.setenv("HAPAX_SECRET_HELPER", str(helper.with_name("missing")))
    elif fault == "not-executable":
        helper.chmod(0o600)
    else:
        # Executable exists, but its interpreter does not: a real launch OSError.
        helper.write_text(f"#!{helper.parent / 'missing-interpreter'}\n")
    authority = common.with_name(AUTHORITY_FILE)
    common.write_bytes(COMMON_BASELINE)
    authority.write_bytes(AUTHORITY_VALUE)
    inodes = (common.stat().st_ino, authority.stat().st_ino)
    result = _run_helper(table)
    assert result.returncode == 2
    assert "launch" in result.stderr if fault == "launch-oserror" else "executable" in result.stderr
    if fault == "launch-oserror":
        assert "litellm-master-key" in result.stderr
    assert "Next action:" in result.stderr and "HAPAX_SECRET_HELPER" in result.stderr
    assert "HAPAX_SECRETS_HOST" in result.stderr and "enrollment" in result.stderr
    assert common.read_bytes() == COMMON_BASELINE
    assert authority.read_bytes() == AUTHORITY_VALUE
    assert (common.stat().st_ino, authority.stat().st_ino) == inodes
    assert not list(common.parent.glob(".*.tmp"))


@pytest.mark.parametrize("filename", ["hapax-secrets.env", AUTHORITY_FILE])
def test_helper_replaces_files_atomically(helper_source, monkeypatch, filename):
    table, _, common = helper_source
    monkeypatch.setenv("SYNTHETIC_HELPER_TABLE", json.dumps(table))
    target = common.with_name(filename)
    target.write_bytes(b"synthetic-prior-env\n")  # pragma: allowlist secret
    target.chmod(0o644)
    prior = target.read_bytes()
    inode = target.stat().st_ino
    replace = os.replace
    replacements = []

    def observe_replace(src, dst):
        assert (common.parent / "helper-calls").read_text().splitlines() == _expected_helper_calls()
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
    producer_store, monkeypatch, capsys, filename
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
    with pytest.raises(SystemExit) as refusal:
        runpy.run_path(str(PRODUCER), run_name="__main__")
    assert refusal.value.code == 2
    assert "replacement failed at" in capsys.readouterr().err
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
