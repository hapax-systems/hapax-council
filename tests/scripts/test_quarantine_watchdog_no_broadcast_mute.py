"""Regression suite: ``hapax-daimonion-quarantine-watchdog`` must NEVER mute broadcast.

The 2026-05-02 broadcast-chain-silence incident was caused by the watchdog's
``REQUIRED_MUTED_SINKS`` / ``REQUIRED_MUTED_SOURCES`` lists carrying broadcast
egress nodes — every 30 s the timer fired and re-muted the OBS livestream
chain. This test file pins the architectural fix:

1. Both lists name only private-voice surfaces (operator monitor side).
2. No name in either list contains a broadcast/livestream/duck/loudnorm/
   master/normalized/remap/tap token (regression fence).
3. Every retained entry matches an explicit ``hapax-private*`` /
   ``hapax-notification-private*`` / ``role.assistant`` pattern.
4. The defensive validator rejects any future attempt to inject a
   broadcast-chain name into either list.
5. Runtime regression: with ``quarantine_active=true`` the watchdog mutes
   the private-voice surfaces but never touches a broadcast egress node.
6. Runtime regression: with ``quarantine_active=false`` the watchdog
   takes no mute actions at all (operator-chosen normal broadcast state).
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import re
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-daimonion-quarantine-watchdog"
SERVICE = "hapax-daimonion.service"

# Patterns the mute set must never match — every one of these is a broadcast
# egress concept and belongs to the public chain, not the quarantine set.
FORBIDDEN_TOKEN_PATTERN = re.compile(
    r"broadcast|livestream|loudnorm|duck|master|normalized|remap|tap",
    re.IGNORECASE,
)

# Patterns every retained entry MUST match — sanity-checks that the set
# stays anchored to the operator's private-voice surfaces.
PRIVATE_TOKEN_PATTERN = re.compile(
    r"hapax-private|hapax-notification-private|role\.assistant",
    re.IGNORECASE,
)

# Sample of broadcast-chain names the validator must reject when injected.
SAMPLE_FORBIDDEN_NODES = (
    "hapax-broadcast-master",
    "hapax-broadcast-normalized",
    "hapax-obs-broadcast-remap",
    "hapax-livestream",
    "hapax-livestream-tap",
    "hapax-livestream-duck",
    "hapax-tts-duck",
    "hapax-music-duck",
    "hapax-music-loudnorm",
    "hapax-pc-loudnorm",
    "hapax-voice-fx-capture",
    "hapax-loudnorm-capture",
    "input.loopback.sink.role.broadcast",
    "input.loopback.sink.role.broadcast.monitor",
)


def _load_watchdog_module() -> types.ModuleType:
    """Import the watchdog script as a module so we can introspect constants."""
    loader = importlib.machinery.SourceFileLoader(
        "daimonion_quarantine_watchdog_no_broadcast_under_test", str(SCRIPT)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


def _entry(
    argv: list[str],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> dict[str, Any]:
    return {
        "argv": argv,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
    }


def _short_listing(names: tuple[str, ...]) -> str:
    return "".join(
        f"{idx}\t{name}\tPipeWire\tfloat32le 2ch 48000Hz\n" for idx, name in enumerate(names)
    )


def _systemd_show_cmd() -> list[str]:
    return [
        "systemctl",
        "--user",
        "show",
        SERVICE,
        "-p",
        "LoadState",
        "-p",
        "UnitFileState",
        "-p",
        "ActiveState",
        "-p",
        "SubState",
        "--value",
    ]


def _pgrep_cmd() -> list[str]:
    return [
        "pgrep",
        "-af",
        r"agents\.hapax_daimonion|hapax-daimonion\.service|rebuild-service\.sh.*hapax-daimonion",
    ]


def _run_watchdog(
    tmp_path: Path,
    commands: list[dict[str, Any]],
    *,
    enforce: bool = False,
    quarantine: dict[str, Any] | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    fixture = tmp_path / "fixture.json"
    witness_path = tmp_path / "witness.json"
    bypass_path = tmp_path / "restore-bypass.json"
    quarantine_path = tmp_path / "quarantine.json"
    fixture.write_text(json.dumps({"commands": commands}), encoding="utf-8")
    if quarantine is not None:
        quarantine_path.write_text(json.dumps(quarantine), encoding="utf-8")
    args = [
        sys.executable,
        str(SCRIPT),
        "--fixture",
        str(fixture),
        "--witness-path",
        str(witness_path),
        "--restore-bypass-file",
        str(bypass_path),
        "--quarantine-state-file",
        str(quarantine_path),
    ]
    if enforce:
        args.append("--enforce")
    completed = subprocess.run(args, capture_output=True, text=True, timeout=10, check=False)
    witness = json.loads(witness_path.read_text(encoding="utf-8")) if witness_path.exists() else {}
    return completed, witness


# ---------------------------------------------------------------------------
# Static structural pins
# ---------------------------------------------------------------------------


def test_required_muted_sources_excludes_broadcast_chain_tokens() -> None:
    """No source-side mute target may name broadcast/livestream/duck/etc."""
    module = _load_watchdog_module()
    offenders = [
        name for name in module.REQUIRED_MUTED_SOURCES if FORBIDDEN_TOKEN_PATTERN.search(name)
    ]
    assert offenders == [], (
        "REQUIRED_MUTED_SOURCES regressed and contains broadcast-chain nodes: "
        f"{offenders}. See module docstring on the 2026-05-02 incident."
    )


def test_required_muted_sinks_excludes_broadcast_chain_tokens() -> None:
    """No sink-side mute target may name broadcast/livestream/duck/etc."""
    module = _load_watchdog_module()
    offenders = [
        name for name in module.REQUIRED_MUTED_SINKS if FORBIDDEN_TOKEN_PATTERN.search(name)
    ]
    assert offenders == [], (
        "REQUIRED_MUTED_SINKS regressed and contains broadcast-chain nodes: "
        f"{offenders}. See module docstring on the 2026-05-02 incident."
    )


def test_every_retained_source_matches_private_pattern() -> None:
    """Every retained source-side entry must read as a private-voice surface."""
    module = _load_watchdog_module()
    non_private = [
        name for name in module.REQUIRED_MUTED_SOURCES if not PRIVATE_TOKEN_PATTERN.search(name)
    ]
    assert non_private == [], (
        f"REQUIRED_MUTED_SOURCES contains non-private surfaces: {non_private}. "
        "Every entry must match hapax-private*/hapax-notification-private*/role.assistant."
    )


def test_every_retained_sink_matches_private_pattern() -> None:
    """Every retained sink-side entry must read as a private-voice surface."""
    module = _load_watchdog_module()
    non_private = [
        name for name in module.REQUIRED_MUTED_SINKS if not PRIVATE_TOKEN_PATTERN.search(name)
    ]
    assert non_private == [], (
        f"REQUIRED_MUTED_SINKS contains non-private surfaces: {non_private}. "
        "Every entry must match hapax-private*/hapax-notification-private*/role.assistant."
    )


def test_required_mute_lists_are_non_empty() -> None:
    """The lists exist and are non-empty — the bug is overreach, not absence."""
    module = _load_watchdog_module()
    assert module.REQUIRED_MUTED_SOURCES, "private-voice quarantine source list cannot be empty"
    assert module.REQUIRED_MUTED_SINKS, "private-voice quarantine sink list cannot be empty"


# ---------------------------------------------------------------------------
# Defensive validator pins
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("forbidden_node", SAMPLE_FORBIDDEN_NODES)
def test_validator_rejects_injected_broadcast_node_in_sources(forbidden_node: str) -> None:
    """The defensive validator must catch any future attempt to add a broadcast node."""
    module = _load_watchdog_module()
    polluted = (*module.REQUIRED_MUTED_SOURCES, forbidden_node)
    with pytest.raises(ValueError, match=r"forbidden broadcast-chain"):
        module._validate_mute_set(polluted, kind="source")


@pytest.mark.parametrize("forbidden_node", SAMPLE_FORBIDDEN_NODES)
def test_validator_rejects_injected_broadcast_node_in_sinks(forbidden_node: str) -> None:
    """Same regression fence on the sink side."""
    module = _load_watchdog_module()
    polluted = (*module.REQUIRED_MUTED_SINKS, forbidden_node)
    with pytest.raises(ValueError, match=r"forbidden broadcast-chain"):
        module._validate_mute_set(polluted, kind="sink")


def test_validator_rejects_unknown_non_private_name() -> None:
    """A name that's not broadcast but also not private must still be rejected.

    This catches a future drift scenario where someone adds a node that
    bypasses the broadcast-token regex but isn't actually a private surface
    either — the allowlist denies anything that's neither.
    """
    module = _load_watchdog_module()
    polluted = (*module.REQUIRED_MUTED_SINKS, "some-random-sink")
    with pytest.raises(ValueError, match=r"does not match any private-surface allowlist"):
        module._validate_mute_set(polluted, kind="sink")


def test_validator_accepts_current_lists_as_legal() -> None:
    """Sanity: the live lists must pass the validator they're enforced against."""
    module = _load_watchdog_module()
    module._validate_mute_set(module.REQUIRED_MUTED_SOURCES, kind="source")
    module._validate_mute_set(module.REQUIRED_MUTED_SINKS, kind="sink")


# ---------------------------------------------------------------------------
# Runtime regression — does the watchdog actually behave correctly end-to-end?
# ---------------------------------------------------------------------------


def test_enforce_with_quarantine_active_mutes_private_does_not_touch_broadcast(
    tmp_path: Path,
) -> None:
    """End-to-end: with quarantine_active=true the watchdog mutes only private nodes."""
    module = _load_watchdog_module()

    # All private nodes start unmuted so we can verify the watchdog issues
    # mute corrections for each. We also include broadcast nodes in the
    # ``pactl list short`` output to model the live system — the watchdog
    # must NOT issue mute commands against them.
    sources_listed = (*module.REQUIRED_MUTED_SOURCES, "hapax-broadcast-normalized.monitor")
    sinks_listed = (*module.REQUIRED_MUTED_SINKS, "hapax-broadcast-normalized")

    commands: list[dict[str, Any]] = [
        _entry(_systemd_show_cmd(), stdout="masked\nmasked\ninactive\ndead\n"),
        _entry(_pgrep_cmd(), returncode=1),
        _entry(["pactl", "list", "short", "sources"], stdout=_short_listing(sources_listed)),
        _entry(["pactl", "list", "short", "sinks"], stdout=_short_listing(sinks_listed)),
    ]
    for name in module.REQUIRED_MUTED_SOURCES:
        commands.append(_entry(["pactl", "get-source-mute", name], stdout="Mute: no\n"))
    for name in module.REQUIRED_MUTED_SINKS:
        commands.append(_entry(["pactl", "get-sink-mute", name], stdout="Mute: no\n"))
    # Mute corrections fire in source-then-sink order, matching build_actions()
    for name in module.REQUIRED_MUTED_SOURCES:
        commands.append(_entry(["pactl", "set-source-mute", name, "1"]))
    for name in module.REQUIRED_MUTED_SINKS:
        commands.append(_entry(["pactl", "set-sink-mute", name, "1"]))

    completed, witness = _run_watchdog(
        tmp_path,
        commands,
        enforce=True,
        quarantine={
            "quarantine_active": True,
            "set_at": "2026-05-02T20:36:00Z",
            "set_by": "regression_test",
            "rationale": "verify watchdog mutes private but not broadcast",
        },
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert witness["success"] is True

    issued_argvs = [tuple(action["command"]) for action in witness["actions"]]
    # Every issued command must reference a private-voice surface.
    for argv in issued_argvs:
        assert FORBIDDEN_TOKEN_PATTERN.search(argv[-2]) is None, (
            f"watchdog issued a mute against a forbidden broadcast-chain node: {argv}"
        )
    # Specifically: hapax-broadcast-normalized must never appear in any action.
    assert not any("hapax-broadcast-normalized" in name for argv in issued_argvs for name in argv)
    # And every required private surface saw a mute correction.
    expected_targets = {*module.REQUIRED_MUTED_SOURCES, *module.REQUIRED_MUTED_SINKS}
    actioned_targets = {argv[-2] for argv in issued_argvs}
    assert expected_targets <= actioned_targets


def test_enforce_with_quarantine_inactive_takes_no_mute_actions(tmp_path: Path) -> None:
    """End-to-end: quarantine_active=false short-circuits — zero pactl mute calls."""
    completed, witness = _run_watchdog(
        tmp_path,
        # No commands are needed because the inactive branch returns before
        # any subprocess fires. If the watchdog regresses and starts probing
        # PipeWire, the empty fixture forces returncode=127 and the test
        # fails loudly.
        commands=[],
        enforce=True,
        quarantine={
            "quarantine_active": False,
            "set_at": "2026-05-02T20:36:00Z",
            "set_by": "operator-directive",
            "rationale": "normal broadcast operation",
        },
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert witness["mode"] == "inactive_quarantine"
    assert witness["quarantine_active"] is False
    assert witness["actions"] == []
    assert witness["operator_notification"]["status"] == "quarantine_inactive_witnessed"
