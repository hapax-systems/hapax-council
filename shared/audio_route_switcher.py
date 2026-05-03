"""PipeWire route switcher — apply voice-path decisions to the live graph.

Phase 4 of docs/superpowers/plans/2026-04-20-dual-fx-routing-plan.md.
Composes pactl commands to move the default sink and active sink-inputs
to a new target sink so a ``VoicePath`` switch takes effect without
restarting daimonion.

Surface:

- ``switch_to_sink(target, sink_inputs=None)`` — builds the pactl
  command sequence that sets the new default sink and moves any
  active sink-inputs onto it. Returns the list of command-arg lists;
  callers run them via ``apply_switch()`` or subprocess directly.
  Splitting build-from-run keeps the core logic testable without
  a live PipeWire.

- ``apply_switch(target, ...)`` — executes the commands. Propagates
  CalledProcessError if pactl isn't available or the target sink
  doesn't exist.

- ``list_sink_inputs()`` — queries pactl for current sink-input IDs;
  used by ``switch_to_sink`` callers that want to move *every*
  active input, not just a specific set.

Scope: Phase 4 is the mechanism. The caller (VocalChainCapability
Phase 5, not yet shipped) decides WHEN to switch — e.g. on tier
change that crosses a path boundary (DRY → EVIL_PET).

Reference:
    - docs/research/2026-04-20-dual-fx-routing-design.md §5 routing
      semantics
    - man 1 pactl
"""

from __future__ import annotations

import subprocess

from shared.audio_working_mode_couplings import current_audio_constraints


class DefaultSinkChangeBlocked(RuntimeError):
    """Raised when the working-mode coupling forbids default-sink swaps.

    Fortress mode forbids ``pactl set-default-sink`` because a sink
    swap can break the live OBS broadcast feed mid-air. Callers that
    encounter this should log + emit a metric, NOT silently fall back.
    """


def build_switch_commands(
    target_sink: str, sink_input_ids: list[str] | None = None
) -> list[list[str]]:
    """Build the pactl command sequence for switching to ``target_sink``.

    Args:
        target_sink: PipeWire sink name (e.g.
            ``alsa_output.usb-Torso_Electronics_S-4``).
        sink_input_ids: Optional list of active sink-input IDs to move.
            When ``None``, only the default-sink is updated; callers
            that want to move current inputs pass IDs from
            ``list_sink_inputs()``.

    Returns:
        List of argv lists. Empty target_sink raises ValueError.
    """
    if not target_sink:
        raise ValueError("target_sink must be non-empty")
    commands: list[list[str]] = [
        ["pactl", "set-default-sink", target_sink],
    ]
    if sink_input_ids:
        for input_id in sink_input_ids:
            commands.append(["pactl", "move-sink-input", str(input_id), target_sink])
    return commands


def list_sink_inputs() -> list[str]:
    """Return active sink-input IDs from ``pactl list short sink-inputs``.

    One column per input: the first whitespace-separated token is the
    input ID. Returns empty list when pactl output is empty or the
    command isn't available.
    """
    try:
        result = subprocess.run(
            ["pactl", "list", "short", "sink-inputs"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    ids: list[str] = []
    for line in result.stdout.splitlines():
        token = line.split()[0] if line.strip() else ""
        if token:
            ids.append(token)
    return ids


def apply_switch(
    target_sink: str,
    sink_input_ids: list[str] | None = None,
    *,
    dry_run: bool = False,
    constraints: dict[str, object] | None = None,
) -> list[subprocess.CompletedProcess[str]]:
    """Execute the pactl command sequence to switch audio routing.

    Args:
        target_sink: PipeWire sink name to make default.
        sink_input_ids: Optional active input IDs to move; when
            ``None``, queries them via ``list_sink_inputs()`` and
            moves every active input. Pass an empty list to move
            nothing (default-sink change only).
        dry_run: When True, returns empty list — no execution.
            Tests + operator "what would this do" use it.
        constraints: Optional working-mode constraint dict. When
            ``default_sink_change_allowed`` is ``False`` (fortress
            mode), the swap is refused with
            :class:`DefaultSinkChangeBlocked`. Defaults to a live
            mode read so callers do not have to thread the mode
            through their call sites.

    Returns the ``CompletedProcess`` for each command in order. Raises
    ``subprocess.CalledProcessError`` on any non-zero exit, aborting
    mid-sequence — callers that need to tolerate partial application
    should catch + inspect.
    """
    active = constraints if constraints is not None else current_audio_constraints()
    if not active.get("default_sink_change_allowed", True):
        raise DefaultSinkChangeBlocked(
            f"default-sink change to {target_sink!r} blocked by working-mode "
            f"coupling (fortress freezes routing)"
        )
    input_ids = sink_input_ids if sink_input_ids is not None else list_sink_inputs()
    commands = build_switch_commands(target_sink, input_ids)
    if dry_run:
        return []
    results: list[subprocess.CompletedProcess[str]] = []
    for cmd in commands:
        results.append(subprocess.run(cmd, capture_output=True, text=True, check=True))
    return results
