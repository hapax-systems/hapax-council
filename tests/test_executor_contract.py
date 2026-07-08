"""Tests for the Executor adapter contract (reform §6 P1).

The capability registry is the machine-legible surface the dispatcher consumes
instead of a hard ``(platform, mode)`` if-ladder, and that
``hapax-executor-capabilities`` emits as JSON.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import executor_contract as ec  # noqa: E402

ALL_PLATFORMS = {"agy", "api", "glmcp", "claude", "codex", "vibe", "local_tool"}


def test_registry_covers_all_runtimes() -> None:
    assert set(ec.EXECUTOR_REGISTRY) == ALL_PLATFORMS


def test_headless_flag_matches_modes() -> None:
    # headless capability is true iff a headless mode is launchable.
    for caps in ec.EXECUTOR_REGISTRY.values():
        assert caps.headless == ("headless" in caps.modes), caps.platform


def test_read_only_implies_no_mutation() -> None:
    for caps in ec.EXECUTOR_REGISTRY.values():
        if caps.read_only:
            assert not caps.mutates, caps.platform


def test_supports_route_for_known_routes() -> None:
    assert ec.supports_route("codex", "headless")
    assert ec.supports_route("claude", "headless")
    assert ec.supports_route("vibe", "headless")


def test_supports_route_rejects_unlaunchable_routes() -> None:
    assert not ec.supports_route("gemini", "headless")
    assert not ec.supports_route("gemini", "interactive")
    assert not ec.supports_route("agy", "review")
    assert not ec.supports_route("agy", "headless")
    assert not ec.supports_route("antigrav", "interactive")
    assert not ec.supports_route("antigrav", "headless")
    assert not ec.supports_route("vibe", "interactive")
    assert not ec.supports_route("api", "headless")  # receipt metadata, not a launcher
    assert not ec.supports_route("codex", "interactive")  # tmux pane, not a dispatch route
    assert not ec.supports_route("unknown", "headless")
    # receipt-only is a dispatch validation mode, not an executor capability.
    assert not ec.supports_route("codex", "receipt-only")


def test_codex_has_a_genuine_headless_path() -> None:
    codex = ec.capabilities("codex")
    assert codex is not None
    assert codex.headless is True
    assert "hapax-codex-headless" in codex.notes


def test_antigrav_is_excised_from_executor_registry() -> None:
    assert ec.capabilities("antigrav") is None


def test_agy_is_read_only_review_surface_not_launcher() -> None:
    agy = ec.capabilities("agy")
    assert agy is not None
    assert agy.read_only is True
    assert agy.modes == ()
    assert agy.profiles == ("direct",)
    assert "hapax-agy-reviewer" in agy.notes


def test_capabilities_unknown_is_none() -> None:
    assert ec.capabilities("nope") is None


def test_adapter_cli_contract_has_canonical_flags() -> None:
    for flag in ("--lane", "--task", "--mode", "--prompt", "--no-claim", "--force"):
        assert flag in ec.ADAPTER_CLI_CONTRACT


def test_capabilities_payload_is_json_serialisable_and_sorted() -> None:
    payload = ec.capabilities_payload()
    text = json.dumps(payload)  # must not raise
    assert set(payload) == ALL_PLATFORMS
    assert list(payload) == sorted(payload)
    assert "hooks_wired" in text


def test_standalone_capabilities_cli_emits_json() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "hapax-executor-capabilities")],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert set(payload) == ALL_PLATFORMS
    assert payload["codex"]["modes"] == ["headless"]


def test_standalone_capabilities_cli_rejects_retired_gemini_platform() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "hapax-executor-capabilities"), "gemini"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 1
    assert "unknown executor" in result.stderr


def test_executor_profiles_cover_every_required_route() -> None:
    # gap-8 regression: every route in REQUIRED_ROUTE_IDS must have its profile
    # declared in its platform's executor profiles, or the declared capability
    # surface diverges from the required-route contract. The originating defect:
    # `api.headless.provider_gateway` was REQUIRED but api profiles only listed
    # ("api_frontier",), so the executor contract under-declared a required route.
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from shared.platform_capability_registry import REQUIRED_ROUTE_IDS

    uncovered: list[tuple[str, str, tuple[str, ...]]] = []
    for route_id in sorted(REQUIRED_ROUTE_IDS):
        platform, _mode, profile = route_id.split(".", 2)
        caps = ec.capabilities(platform)
        assert caps is not None, f"no executor capabilities for platform {platform!r} ({route_id})"
        if profile not in caps.profiles:
            uncovered.append((route_id, profile, caps.profiles))
    assert not uncovered, (
        f"required routes whose profile is missing from executor profiles: {uncovered}"
    )
