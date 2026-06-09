"""Wiring-assertion health probe (segment-audio-hosting-readiness AC#6).

The recurring failure mode for this subsystem is a hardware/topology migration
that renames a node and silently leaves an executor writing to a dead node (the
exact way the L-12 -> mk5 migration broke this daemon). This probe pins the
WIRING so the next migration can't re-break it without a red test:

  1. the ducker's target node EXISTS in the topology SSOT;
  2. the music bed is actually ROUTED through that node in the generated link map
     (so hapax-audio-reconciler wires it);
  3. the music gain actually MOVES when a trigger fires;
  4. the director's fail-closed broadcast route RESOLVES (the #4029 seam exists).

These run without the live PipeWire graph (they assert the source-of-truth
wiring, which is what a migration breaks). A live-graph smoke is alpha's.
"""

from __future__ import annotations

from agents.audio_ducker.__main__ import (
    MUSIC_DUCK_NODE,
    RODE_CAPTURE_NODE,
    UNITY,
    compute_targets,
)
from shared.audio_routing_policy import (
    DEFAULT_POLICY_PATH,
    generated_route_map_texts,
    load_audio_routing_policy,
    load_audio_topology_descriptor,
)


def _topology_pipewire_names() -> set[str]:
    d = load_audio_topology_descriptor()
    return {n.pipewire_name for n in d.nodes}


def test_ducker_music_node_exists_in_topology() -> None:
    """The node the daemon writes its music duck gain to must be a real topology
    node — not a dead/renamed literal."""
    assert MUSIC_DUCK_NODE in _topology_pipewire_names()


def test_ducker_operator_mic_node_exists_in_topology() -> None:
    """The operator-VAD input the daemon reads must be a real topology node."""
    assert RODE_CAPTURE_NODE in _topology_pipewire_names()


def test_music_bed_is_routed_through_the_duck_in_link_map() -> None:
    """The generated reconciler link map must route music THROUGH the duck node
    (music-loudnorm -> duck -> livestream), proving the reconciler wires it.
    A migration that drops the duck node would fail this."""
    policy = load_audio_routing_policy(DEFAULT_POLICY_PATH)
    topology = load_audio_topology_descriptor()
    desired, _forbidden = generated_route_map_texts(topology, policy)

    assert f"hapax-music-loudnorm-playback:output_FL|{MUSIC_DUCK_NODE}:playback_FL" in desired
    assert f"{MUSIC_DUCK_NODE}-playback:output_FL|hapax-livestream-tap:playback_FL" in desired
    # the old direct music -> livestream link must be gone (else the duck is bypassed).
    assert "hapax-music-loudnorm-playback:output_FL|hapax-livestream-tap:playback_FL" not in desired


def test_music_gain_moves_when_any_trigger_fires() -> None:
    """The duck gain must actually MOVE off unity for each trigger class."""
    assert compute_targets(True, False)[0] < UNITY  # operator voice
    assert compute_targets(False, True)[0] < UNITY  # TTS on broadcast
    assert compute_targets(False, False, segment_active=True)[0] < UNITY  # hosting segment
    # ...and stay at unity when nothing fires (no spurious duck).
    assert compute_targets(False, False)[0] == UNITY


def test_director_broadcast_route_resolves() -> None:
    """The director's fail-closed broadcast decision seam (#4029) must exist and
    be importable — the route host narration takes onto broadcast."""
    from agents.hapax_daimonion.cpal.destination_channel import resolve_playback_decision

    assert callable(resolve_playback_decision)
