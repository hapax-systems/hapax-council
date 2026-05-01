"""Tests for ``shared.fix_capabilities.profiles_cap``.

The capability refreshes operator profile data by triggering the
``profile-update.service`` systemd unit. Coverage:

  - ``gather_context`` reads the on-disk state file and surfaces the
    last_run / state_exists fields, with graceful handling for
    missing-file, invalid-JSON, and read-error cases.
  - ``available_actions`` returns the hardcoded action set.
  - ``validate`` accepts the known action and rejects anything else.
  - ``execute`` runs the systemctl command and translates the return
    code into an ``ExecutionResult``.

The tests stub ``shared.fix_capabilities.profiles_cap.run_cmd`` (the
async helper imported from ``agents.health_monitor``) so no real
systemctl call is made. The on-disk state file is replaced with a
``tmp_path`` fixture path via patching.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from shared.fix_capabilities.base import (
    ExecutionResult,
    FixProposal,
    ProbeResult,
    Safety,
)
from shared.fix_capabilities.profiles_cap import ProfilesCapability


@pytest.fixture
def cap() -> ProfilesCapability:
    return ProfilesCapability()


# ── available_actions / validate ──────────────────────────────────────


class TestActionsAndValidate:
    def test_action_set_contains_trigger_profiler(self, cap: ProfilesCapability) -> None:
        actions = cap.available_actions()
        names = {a.name for a in actions}
        assert "trigger_profiler" in names

    def test_only_one_action_in_v1(self, cap: ProfilesCapability) -> None:
        # Locks the action surface; expansion requires an explicit
        # test update so unrelated additions can't sneak in.
        assert len(cap.available_actions()) == 1

    def test_trigger_profiler_is_safe(self, cap: ProfilesCapability) -> None:
        action = next(a for a in cap.available_actions() if a.name == "trigger_profiler")
        assert action.safety == Safety.SAFE

    def test_validate_accepts_trigger_profiler(self, cap: ProfilesCapability) -> None:
        proposal = FixProposal(capability="profiles", action_name="trigger_profiler")
        assert cap.validate(proposal) is True

    def test_validate_rejects_unknown_action(self, cap: ProfilesCapability) -> None:
        proposal = FixProposal(capability="profiles", action_name="trigger_nuclear_codes")
        assert cap.validate(proposal) is False


# ── gather_context: probes the on-disk state file ───────────────────


class TestGatherContext:
    @pytest.mark.asyncio
    async def test_state_file_present_with_last_run(
        self, cap: ProfilesCapability, tmp_path: Path
    ) -> None:
        # Mock the home so the capability points at our tmp file.
        state_dir = tmp_path / "projects" / "hapax-council" / "profiles"
        state_dir.mkdir(parents=True)
        state_file = state_dir / ".state.json"
        state_file.write_text(json.dumps({"last_run": "2026-05-01T12:00:00Z"}))

        with patch.object(Path, "home", return_value=tmp_path):
            result = await cap.gather_context(check=None)

        assert isinstance(result, ProbeResult)
        assert result.capability == "profiles"
        assert result.raw["last_run"] == "2026-05-01T12:00:00Z"
        assert result.raw["state_exists"] is True

    @pytest.mark.asyncio
    async def test_state_file_present_but_no_last_run(
        self, cap: ProfilesCapability, tmp_path: Path
    ) -> None:
        state_dir = tmp_path / "projects" / "hapax-council" / "profiles"
        state_dir.mkdir(parents=True)
        state_file = state_dir / ".state.json"
        # Valid JSON but missing the last_run key.
        state_file.write_text("{}")

        with patch.object(Path, "home", return_value=tmp_path):
            result = await cap.gather_context(check=None)

        assert result.raw["last_run"] == "unknown"
        assert result.raw["state_exists"] is True

    @pytest.mark.asyncio
    async def test_state_file_invalid_json(self, cap: ProfilesCapability, tmp_path: Path) -> None:
        state_dir = tmp_path / "projects" / "hapax-council" / "profiles"
        state_dir.mkdir(parents=True)
        state_file = state_dir / ".state.json"
        state_file.write_text("{not json")

        with patch.object(Path, "home", return_value=tmp_path):
            result = await cap.gather_context(check=None)

        assert "error" in result.raw
        assert result.raw["state_exists"] is True

    @pytest.mark.asyncio
    async def test_state_file_missing(self, cap: ProfilesCapability, tmp_path: Path) -> None:
        # Don't create the state directory at all.
        with patch.object(Path, "home", return_value=tmp_path):
            result = await cap.gather_context(check=None)

        assert result.raw["state_exists"] is False


# ── execute: dispatches to systemctl ─────────────────────────────────


class TestExecute:
    @pytest.mark.asyncio
    async def test_execute_unknown_action_returns_failure(self, cap: ProfilesCapability) -> None:
        proposal = FixProposal(capability="profiles", action_name="bogus")
        result = await cap.execute(proposal)
        assert isinstance(result, ExecutionResult)
        assert result.success is False
        assert "Unknown action: bogus" in result.message

    @pytest.mark.asyncio
    async def test_execute_success_when_systemctl_returns_zero(
        self, cap: ProfilesCapability
    ) -> None:
        proposal = FixProposal(capability="profiles", action_name="trigger_profiler")
        fake_run = AsyncMock(return_value=(0, "started", ""))
        with patch("shared.fix_capabilities.profiles_cap.run_cmd", fake_run):
            result = await cap.execute(proposal)

        assert result.success is True
        assert "Triggered profile-update.service" in result.message
        assert result.output == "started"
        # Confirm we issued the right systemctl command.
        called_cmd = fake_run.call_args[0][0]
        assert called_cmd == [
            "systemctl",
            "--user",
            "start",
            "profile-update.service",
        ]

    @pytest.mark.asyncio
    async def test_execute_failure_when_systemctl_nonzero(self, cap: ProfilesCapability) -> None:
        proposal = FixProposal(capability="profiles", action_name="trigger_profiler")
        fake_run = AsyncMock(return_value=(1, "", "unit not found"))
        with patch("shared.fix_capabilities.profiles_cap.run_cmd", fake_run):
            result = await cap.execute(proposal)

        assert result.success is False
        assert "Failed to trigger profiler" in result.message
        assert "unit not found" in result.message
        assert result.output == "unit not found"


# ── Capability surface contract ──────────────────────────────────────


class TestCapabilitySurface:
    def test_name_is_profiles(self, cap: ProfilesCapability) -> None:
        assert cap.name == "profiles"

    def test_check_groups_match(self, cap: ProfilesCapability) -> None:
        # Check-group routing wires this capability to "profiles" health
        # checks. Pin the contract so check-naming changes surface.
        assert cap.check_groups == {"profiles"}
