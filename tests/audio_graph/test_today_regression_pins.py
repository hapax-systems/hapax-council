"""Regression pins for the four ``today's #N`` failures listed in the
P1 cc-task ``audio-graph-ssot-p1-compiler-validator`` (§ Concrete
deliverables, item 4).

Each test name matches the cc-task spec verbatim so an operator
running ``pytest -k test_today_`` sees exactly the four failures the
P1 compiler+validator was commissioned to prevent. The underlying
invariant assertions are also covered by ``test_invariants.py``;
these pins exist as **operator-readable provenance** that links the
spec's "today's #N" labels to live regression coverage.

The four failures pinned here:

* **today's #3** — private→L-12 leak. A pre-fix descriptor that links
  ``hapax-private`` (a ``private_monitor_endpoint``, fail-closed)
  directly into a livestream-tap node must yield a
  ``PRIVATE_NEVER_BROADCASTS`` violation. Caught BLOCKING pre-apply.
* **today's #5** — 14-channel L-12 capture connected to a 2-channel
  consumer without a declared :class:`ChannelDownmix` must yield a
  ``FORMAT_COMPATIBILITY`` violation. Catches the silent-downmix
  class.
* **today's #6** — declared ``GainStage`` whose net gain (base +
  per-channel override − declared bleed) exceeds zero must yield a
  ``HARDWARE_BLEED_GUARD`` violation. Surfaces the missing
  ``declared_bleed_db`` data the operator must supply.
* **today's #8** — two distinct nodes claiming the same
  ``pipewire_name`` must fail Pydantic validation at AudioGraph
  construction time (caught by the schema validator before any
  invariant runs).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.audio_graph import (
    AudioGraph,
    AudioLink,
    AudioNode,
    ChannelMap,
    GainStage,
    NodeKind,
)
from shared.audio_graph.invariants import (
    InvariantKind,
    InvariantSeverity,
    check_format_compatibility,
    check_hardware_bleed_guard,
    check_private_never_broadcasts,
)


def _node(
    node_id: str,
    *,
    kind: NodeKind = NodeKind.FILTER_CHAIN,
    fail_closed: bool = False,
    private_monitor_endpoint: bool = False,
    channels_count: int = 2,
    pipewire_name: str | None = None,
) -> AudioNode:
    return AudioNode(
        id=node_id,
        kind=kind,
        pipewire_name=pipewire_name or node_id,
        channels=ChannelMap(
            count=channels_count,
            positions=(
                ["FL", "FR"] if channels_count == 2 else [f"AUX{i}" for i in range(channels_count)]
            ),
        ),
        fail_closed=fail_closed,
        private_monitor_endpoint=private_monitor_endpoint,
    )


# ---------------------------------------------------------------------------
# today's #3 — private → L-12 leak (PRIVATE_NEVER_BROADCASTS)
# ---------------------------------------------------------------------------


def test_today_3_private_l12_leak_yaml() -> None:
    """Synthesised pre-fix YAML: private taps directly into livestream.

    Invariant: ``PRIVATE_NEVER_BROADCASTS`` must catch this BLOCKING
    pre-apply. The inspector already enforces this post-fix at runtime;
    the P1 compiler escalates to apply-time blocking.
    """
    graph = AudioGraph(
        nodes=[
            _node(
                "hapax-private",
                kind=NodeKind.TAP,
                fail_closed=True,
                private_monitor_endpoint=True,
            ),
            _node("hapax-livestream-tap", kind=NodeKind.TAP),
        ],
        links=[
            AudioLink(source="hapax-private", target="hapax-livestream-tap"),
        ],
    )
    violations = check_private_never_broadcasts(graph)
    assert any(v.kind == InvariantKind.PRIVATE_NEVER_BROADCASTS for v in violations), (
        "PRIVATE_NEVER_BROADCASTS must catch a private tap linked to a livestream-tap"
    )
    assert all(v.severity == InvariantSeverity.BLOCKING for v in violations)


# ---------------------------------------------------------------------------
# today's #5 — 14ch L-12 capture into 2ch consumer without declared downmix
# ---------------------------------------------------------------------------


def test_today_5_format_compat_14ch_to_2ch() -> None:
    """Silent-downmix class: capture format change without an explicit
    :class:`ChannelDownmix` declaration. ``FORMAT_COMPATIBILITY`` must
    catch this BLOCKING pre-apply.
    """
    graph = AudioGraph(
        nodes=[
            _node("hapax-l12-capture", channels_count=14, kind=NodeKind.LOOPBACK),
            _node("hapax-l12-evilpet-capture", channels_count=2),
        ],
        links=[
            AudioLink(source="hapax-l12-capture", target="hapax-l12-evilpet-capture"),
        ],
    )
    violations = check_format_compatibility(graph)
    assert any(v.kind == InvariantKind.FORMAT_COMPATIBILITY for v in violations), (
        "FORMAT_COMPATIBILITY must catch a 14→2 channel-count change with no ChannelDownmix"
    )


# ---------------------------------------------------------------------------
# today's #6 — gain_samp overshoots declared bleed (HARDWARE_BLEED_GUARD)
# ---------------------------------------------------------------------------


def test_today_6_hardware_bleed_guard() -> None:
    """``gain_samp=1.0`` (i.e., +0 dB amplification) on a stage whose
    declared bleed is -27 dB sums to a net path that exceeds zero on
    one channel — ``HARDWARE_BLEED_GUARD`` must catch this BLOCKING
    pre-apply. The model surfaces the missing data the operator must
    declare; an undeclared bleed cannot be silently passed.
    """
    graph = AudioGraph(
        nodes=[_node("hapax-l12-capture")],
        gain_stages=[
            GainStage(
                edge_source="hapax-l12-capture",
                edge_target="gain_samp",
                base_gain_db=0.0,
                declared_bleed_db=27.0,
                per_channel_overrides={"AUX3": 30.0},
            )
        ],
    )
    violations = check_hardware_bleed_guard(graph)
    assert any(v.kind == InvariantKind.HARDWARE_BLEED_GUARD for v in violations), (
        "HARDWARE_BLEED_GUARD must catch a per-channel override that exceeds declared bleed"
    )


# ---------------------------------------------------------------------------
# today's #8 — two nodes share a pipewire_name (NO_DUPLICATE_PIPEWIRE_NAMES)
# ---------------------------------------------------------------------------


def test_today_8_no_duplicate_pipewire_names() -> None:
    """Two distinct nodes claiming the same ``pipewire_name`` must
    fail Pydantic validation at AudioGraph construction time. The
    schema validator catches this before any invariant runs, so the
    BLOCKING violation surfaces as a ``ValidationError`` rather than
    an ``InvariantViolation`` — same blast radius (refuse to compile),
    different exception class.
    """
    n1 = _node("hapax-evilpet-a", pipewire_name="hapax-evilpet")
    n2 = _node("hapax-evilpet-b", pipewire_name="hapax-evilpet")
    with pytest.raises(ValidationError):
        AudioGraph(nodes=[n1, n2])
