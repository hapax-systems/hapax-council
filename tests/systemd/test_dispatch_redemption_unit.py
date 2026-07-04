from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT = REPO_ROOT / "systemd" / "units" / "hapax-dispatch-redemption.service"
ACTIVATION_DAEMON = (
    "/home/hapax/.cache/hapax/source-activation/worktree/scripts/"
    "hapax-dispatch-redemption-authority"
)


def test_unit_is_system_scoped_governor() -> None:
    body = UNIT.read_text(encoding="utf-8")

    # System scope is load-bearing: only the system manager can provision
    # /run/hapax/coord; a user unit would land in caller-writable /run/user/<uid>.
    assert "Hapax-Install-Scope: system" in body
    assert "WantedBy=multi-user.target" in body
    assert "WantedBy=default.target" not in body


def test_unit_provisions_fixed_namespace_with_deliberate_mode() -> None:
    body = UNIT.read_text(encoding="utf-8")

    assert "RuntimeDirectory=hapax/coord" in body
    assert "RuntimeDirectoryMode=0750" in body
    directives = [
        line for line in body.splitlines() if line.strip() and not line.strip().startswith("#")
    ]
    assert not [line for line in directives if "/run/user" in line]


def test_unit_runs_activated_source_and_fails_closed_pre_activation() -> None:
    body = UNIT.read_text(encoding="utf-8")

    assert f"ExecStart=/usr/bin/python3 {ACTIVATION_DAEMON} --serve" in body
    assert f"ConditionPathExists={ACTIVATION_DAEMON}" in body
    # The governor must not run from a mutable lane worktree.
    assert "/projects/hapax-council" not in body


def test_unit_hardening_baseline() -> None:
    body = UNIT.read_text(encoding="utf-8")

    assert "User=hapax" in body
    assert "NoNewPrivileges=true" in body
    assert "PrivateTmp=true" in body
    assert "Restart=on-failure" in body
