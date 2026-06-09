"""Tests for shared.audio_node_resolver — SSOT node-name resolution + fail-open."""

from __future__ import annotations

import shared.audio_routing_policy as routing_policy
from shared.audio_node_resolver import resolve_audio_node


def test_resolves_known_duck_node() -> None:
    """The mk5 music duck resolves to its live pipewire_name from the SSOT."""
    assert resolve_audio_node("music-duck-mk5", "FALLBACK") == "hapax-music-duck-mk5"


def test_resolves_operator_mic_node() -> None:
    """The operator mic id resolves to a live hapax-mic-rode-* node."""
    name = resolve_audio_node("mic-rode", "hapax-mic-rode-capture")
    assert name.startswith("hapax-mic-rode")


def test_unknown_id_returns_fallback() -> None:
    """An id with no backing node fails OPEN to the hardcoded literal."""
    assert (
        resolve_audio_node("no-such-node-id-xyz", "hapax-fallback-literal")
        == "hapax-fallback-literal"
    )


def test_topology_load_failure_returns_fallback(monkeypatch) -> None:
    """A topology-read error must never propagate — fail OPEN to the fallback."""

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated topology read failure")

    monkeypatch.setattr(routing_policy, "load_audio_topology_descriptor", _boom)
    assert resolve_audio_node("music-duck-mk5", "hapax-music-duck-mk5") == "hapax-music-duck-mk5"
