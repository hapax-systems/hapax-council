"""Council hapax-secrets unit and watchdog copies use FileStore, not pass show."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT = REPO_ROOT / "systemd" / "units" / "hapax-secrets.service"
WATCHDOGS = REPO_ROOT / "systemd" / "watchdogs"


def test_hapax_secrets_unit_uses_filestore_not_pass() -> None:
    text = UNIT.read_text(encoding="utf-8")
    assert "pass show" not in text
    assert "PASSWORD_STORE_DIR" not in text
    assert "secret_env_from_filestore.py" in text
    assert "OnFailure=notify-failure@%n.service" in text
    assert "/run/user/%U/hapax-secrets.env" in text
    assert "/run/user/1000/" not in text


def test_systemd_watchdogs_use_hapax_secret_not_pass_show() -> None:
    paths = sorted(p for p in WATCHDOGS.iterdir() if p.is_file())
    assert paths, "expected watchdog scripts under systemd/watchdogs"
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "pass show" not in text, f"{path.name} still contains pass show"
        assert "hapax-secret" in text, f"{path.name} does not call hapax-secret"
