"""Council hapax-secrets unit and watchdog copies use FileStore, not pass show."""

from pathlib import Path

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
    assert "LITELLM_BASE_URL" in producer.read_text(encoding="utf-8")
    assert "pass show" not in text
    assert "PASSWORD_STORE_DIR" not in text
    assert "source-activation/worktree/scripts/secret_env_from_filestore.py" in text
    assert "OnFailure=notify-failure@%n.service" in text
    assert "/run/user/%U/hapax-secrets.env" in text
    assert "/run/user/1000/" not in text


def test_migrated_watchdogs_pin_activation_worktree() -> None:
    for name in MIGRATED_WATCHDOGS:
        text = (WATCHDOGS / name).read_text(encoding="utf-8")
        assert "/home/hapax/" not in text, f"{name} still bakes an operator home path"
        assert "source-activation/worktree" in text or "SOURCE_ACTIVATION" in text
        assert "hapax-secret" in text


def test_systemd_watchdogs_use_hapax_secret_not_pass_show() -> None:
    for name in MIGRATED_WATCHDOGS:
        path = WATCHDOGS / name
        assert path.is_file(), f"missing watchdog: {name}"
        text = path.read_text(encoding="utf-8")
        assert "pass show" not in text, f"{path.name} still contains pass show"
        assert "hapax-secret" in text, f"{path.name} does not call hapax-secret"
