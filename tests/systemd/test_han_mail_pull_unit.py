"""HAN mail executes only from the governed, activated release."""

import configparser
import os
import shlex
from pathlib import Path

UNIT = Path(__file__).resolve().parents[2] / "systemd/units/han-mail-pull.service"
RELEASE = "%h/.cache/hapax/source-activation/worktree"


def test_service_uses_activated_release():
    text = Path(os.environ.get("HAN_MAIL_UNIT_UNDER_TEST", UNIT)).read_text()
    unit = configparser.ConfigParser(interpolation=None, strict=False)
    unit.optionxform = str
    unit.read_string(text)

    environment = {}
    section = ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("["):
            section = line
            continue
        directive, _, value = line.partition("=")
        # Inspect every assignment: ConfigParser retains only the last repeated
        # directive, while systemd combines Environment/EnvironmentFile entries.
        assert "projects/" not in line, f"development checkout in unit: {line}"
        if section == "[Service]" and directive == "Environment":
            environment.update(assignment.split("=", 1) for assignment in shlex.split(value))

    service = unit["Service"]
    assert service["WorkingDirectory"] == RELEASE
    assert shlex.split(service["ExecStart"]) == [
        f"{RELEASE}/.venv/bin/python",
        f"{RELEASE}/scripts/han_mail_pull.py",
    ]
    assert environment["PYTHONPATH"] == RELEASE
    assert environment["PATH"] == (
        f"{RELEASE}/.venv/bin:%h/.local/bin:/usr/local/bin:/usr/bin:/bin"
    )
