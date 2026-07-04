from __future__ import annotations

import hashlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT = REPO_ROOT / "systemd" / "units" / "hapax-dispatch-redemption.service"
CLAUDE_LANE_UNIT = REPO_ROOT / "systemd" / "units" / "hapax-claude-lane@.service"
ACTIVATION_DAEMON = (
    "/home/hapax/.cache/hapax/source-activation/worktree/scripts/"
    "hapax-dispatch-redemption-authority"
)
ACTIVATION_DISPATCHER = (
    "/home/hapax/.cache/hapax/source-activation/worktree/scripts/hapax-methodology-dispatch"
)
DISPATCHER = REPO_ROOT / "scripts" / "hapax-methodology-dispatch"
EVENTS_PATH = "/var/lib/hapax/dispatch-redemption/events.jsonl"


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
    assert "StateDirectory=hapax/dispatch-redemption" in body
    assert "StateDirectoryMode=0750" in body
    assert "User=root" in body
    assert "Group=hapax" in body
    assert "Environment=HAPAX_DISPATCH_REDEMPTION_ALLOWED_USER=hapax" in body
    assert (
        "Environment=HAPAX_DISPATCH_REDEMPTION_ALLOWED_REQUESTER=hapax-methodology-dispatch"
    ) in body
    assert (
        f"Environment=HAPAX_DISPATCH_REDEMPTION_ALLOWED_REQUESTER_PATHS={ACTIVATION_DISPATCHER}"
    ) in body
    expected_digest = hashlib.sha256(DISPATCHER.read_bytes()).hexdigest()
    assert (
        f"Environment=HAPAX_DISPATCH_REDEMPTION_ALLOWED_REQUESTER_SHA256={expected_digest}"
    ) in body
    directives = [
        line for line in body.splitlines() if line.strip() and not line.strip().startswith("#")
    ]
    assert not [line for line in directives if "/run/user" in line]


def test_unit_runs_activated_source_and_fails_closed_pre_activation() -> None:
    body = UNIT.read_text(encoding="utf-8")

    assert "canonical single-operator" in body
    assert "`/home/hapax/.cache/hapax/source-activation/worktree`" in body
    assert "Alternate users/hosts must regenerate this unit via the installer" in body
    assert (
        f"ExecStart=/usr/bin/python3 {ACTIVATION_DAEMON} --serve --events-path {EVENTS_PATH}"
        in body
    )
    assert f"ConditionPathExists={ACTIVATION_DAEMON}" in body
    assert "/Documents/Personal/" not in body
    # The governor must not run from a mutable lane worktree.
    runtime_directives = [
        line
        for line in body.splitlines()
        if line.startswith(("ExecStart=", "ConditionPathExists="))
    ]
    assert not [line for line in runtime_directives if "/projects/hapax-council" in line]


def test_claude_lane_dispatcher_matches_governor_allowlist() -> None:
    governor = UNIT.read_text(encoding="utf-8")
    lane = CLAUDE_LANE_UNIT.read_text(encoding="utf-8")

    assert (
        f"Environment=HAPAX_DISPATCH_REDEMPTION_ALLOWED_REQUESTER_PATHS={ACTIVATION_DISPATCHER}"
    ) in governor
    activation_from_home = ACTIVATION_DISPATCHER.replace("/home/hapax", "$HOME", 1)
    assert f'/usr/bin/python3 -I "{activation_from_home}"' in lane
    expected_digest = hashlib.sha256(DISPATCHER.read_bytes()).hexdigest()
    assert (
        f"Environment=HAPAX_DISPATCH_REDEMPTION_ALLOWED_REQUESTER_SHA256={expected_digest}"
    ) in governor


def test_unit_names_governed_activation_installer() -> None:
    body = UNIT.read_text(encoding="utf-8")

    assert "scripts/hapax-dispatch-redemption-service-install --install" in body
    assert "hapax-post-merge-deploy invokes that installer automatically" in body
    assert f"sha256sum {ACTIVATION_DISPATCHER}" in body
    assert "requester/runtime changes" in body
    assert "sudo cp systemd/units/hapax-dispatch-redemption.service" not in body


def test_unit_hardening_baseline() -> None:
    body = UNIT.read_text(encoding="utf-8")

    assert "User=root" in body
    assert "NoNewPrivileges=true" in body
    assert "PrivateTmp=true" in body
    assert "Restart=on-failure" in body
