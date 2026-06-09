"""Tests for the recruited-media egress gate.

This gate is the FIRST real consumer of agentgov ``Labeled[A]`` in the media
dispatch path: a recruited image/YT ref is wrapped in a ``Labeled`` carrying
its consent label, and may only be unwrapped for broadcast when the label can
flow to the public broadcast sink. On top of that information-flow check it
enforces the stream-mode + fortress egress gates. Fail-closed throughout: any
error refuses.
"""

from __future__ import annotations

from agentgov.consent_label import ConsentLabel

from agents.studio_compositor.media_egress_gate import (
    MediaEgressOutcome,
    gate_media_egress,
)
from shared.stream_mode import StreamMode


def _public() -> StreamMode:
    return StreamMode.PUBLIC


def _off() -> StreamMode:
    return StreamMode.OFF


def test_public_media_allowed_in_fortress_public_stream() -> None:
    decision = gate_media_egress(
        "object:yt:abc123",
        is_fortress_fn=lambda: True,
        stream_mode_fn=_public,
    )
    assert decision.outcome is MediaEgressOutcome.ALLOWED
    assert decision.media_ref == "object:yt:abc123"


def test_protected_media_refused_by_consent_label() -> None:
    """A non-public label cannot flow to broadcast — the Labeled consumer."""

    protected = ConsentLabel(frozenset({("guest", frozenset({"guest", "operator"}))}))
    decision = gate_media_egress(
        "object:image:guest-photo.png",
        label=protected,
        is_fortress_fn=lambda: True,
        stream_mode_fn=_public,
    )
    assert decision.outcome is MediaEgressOutcome.REFUSED_CONSENT
    assert decision.media_ref is None


def test_media_refused_when_stream_off() -> None:
    decision = gate_media_egress(
        "object:yt:abc123",
        is_fortress_fn=lambda: True,
        stream_mode_fn=_off,
    )
    assert decision.outcome is MediaEgressOutcome.REFUSED_STREAM_OFF
    assert decision.media_ref is None


def test_media_refused_when_not_fortress() -> None:
    decision = gate_media_egress(
        "object:yt:abc123",
        is_fortress_fn=lambda: False,
        stream_mode_fn=_public,
    )
    assert decision.outcome is MediaEgressOutcome.REFUSED_NOT_FORTRESS
    assert decision.media_ref is None


def test_gate_fails_closed_on_error() -> None:
    def _boom() -> StreamMode:
        raise RuntimeError("stream mode read failed")

    decision = gate_media_egress(
        "object:yt:abc123",
        is_fortress_fn=lambda: True,
        stream_mode_fn=_boom,
    )
    assert decision.outcome is MediaEgressOutcome.REFUSED_ERROR
    assert decision.media_ref is None
