"""Council hapax-secrets unit and watchdog copies use FileStore, not pass show."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT = REPO_ROOT / "systemd" / "units" / "hapax-secrets.service"
WATCHDOGS = REPO_ROOT / "systemd" / "watchdogs"
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


def _run_producer(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    producer = REPO_ROOT / "scripts" / "secret_env_from_filestore.py"
    return subprocess.run(
        [sys.executable, str(producer)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_producer_writes_env_from_filestore(tmp_path, monkeypatch) -> None:
    pin = _require_reins_pin()
    store_root = tmp_path / "secrets"
    env_path = tmp_path / "hapax-secrets.env"
    monkeypatch.setenv("REINS_SECRET_STORE", str(store_root))
    monkeypatch.setenv("HAPAX_SECRETS_ENV_PATH", str(env_path))
    monkeypatch.setenv("HAPAX_LITELLM_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("HAPAX_REINS_API", str(pin))
    sys.path.insert(0, str(pin))
    from k0.key_capture import FileStore

    store = FileStore(root=store_root)
    for name, value in (
        ("litellm-master-key", b"lk"),
        ("langfuse-public-key", b"pk"),
        ("langfuse-secret-key", b"sk"),
        ("api-huggingface", b"hf"),
        ("api-mistral", b"mi"),
        ("api-openai", b"oa"),
        ("orcid-orcid", b"0000-0000-0000-0000"),
    ):
        store.put(name, value)
    result = _run_producer(os.environ.copy())
    assert result.returncode == 0, result.stderr
    text = env_path.read_text(encoding="utf-8")
    assert "LITELLM_API_KEY=lk" in text
    assert "HAPAX_OPERATOR_ORCID=0000-0000-0000-0000" in text
    assert "LITELLM_BASE_URL=http://127.0.0.1:9" in text
    assert oct(env_path.stat().st_mode)[-3:] == "600"


def test_producer_missing_key_does_not_clobber_env(tmp_path, monkeypatch) -> None:
    pin = _require_reins_pin()
    store_root = tmp_path / "secrets"
    store_root.mkdir()
    env_path = tmp_path / "hapax-secrets.env"
    env_path.write_text("LITELLM_API_KEY=keep-me\n")
    os.chmod(env_path, 0o600)
    monkeypatch.setenv("REINS_SECRET_STORE", str(store_root))
    monkeypatch.setenv("HAPAX_SECRETS_ENV_PATH", str(env_path))
    monkeypatch.setenv("HAPAX_REINS_API", str(pin))
    result = _run_producer(os.environ.copy())
    assert result.returncode == 2
    assert "missing" in result.stderr or ".key" in result.stderr
    assert env_path.read_text(encoding="utf-8") == "LITELLM_API_KEY=keep-me\n"
    assert not (store_root / ".key").exists()


def test_producer_missing_required_secret_keeps_prior_env(tmp_path, monkeypatch) -> None:
    pin = _require_reins_pin()
    store_root = tmp_path / "secrets"
    env_path = tmp_path / "hapax-secrets.env"
    env_path.write_text("LITELLM_API_KEY=keep-me\n")
    monkeypatch.setenv("REINS_SECRET_STORE", str(store_root))
    monkeypatch.setenv("HAPAX_SECRETS_ENV_PATH", str(env_path))
    monkeypatch.setenv("HAPAX_REINS_API", str(pin))
    sys.path.insert(0, str(pin))
    from k0.key_capture import FileStore

    store = FileStore(root=store_root)
    store.put("litellm-master-key", b"lk")
    result = _run_producer(os.environ.copy())
    assert result.returncode == 2
    assert "missing" in result.stderr
    assert env_path.read_text(encoding="utf-8") == "LITELLM_API_KEY=keep-me\n"


def test_systemd_watchdogs_use_hapax_secret_not_pass_show() -> None:
    for name in MIGRATED_WATCHDOGS:
        path = WATCHDOGS / name
        assert path.is_file(), f"missing watchdog: {name}"
        text = path.read_text(encoding="utf-8")
        assert "pass show" not in text, f"{path.name} still contains pass show"
        assert "hapax-secret" in text, f"{path.name} does not call hapax-secret"
