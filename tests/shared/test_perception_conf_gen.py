"""TDD for the perception-conf generator — the lean SSOT spine.

The cortado contact-mic conf is currently hand-authored (L-12 edition) with a
hand-typed ``node.target`` that drifted to the retired Zoom L-12, so the live
``contact_mic`` node fell through to mk5 capture_AUX0 (the Rode) = an eavesdrop
class (REQ-20260616-perception-audio-ssot-program, Phase 1).

These tests pin the fix correct-by-construction: the registry declares a TYPED
hardware source (device + position) and the generator EMITS the conf from it, so
there is no hand-typed channel left to drift, and a perceptual/quarantine point
can never be emitted onto a broadcast-reachable target.
"""

from __future__ import annotations

import pytest

from shared.perception_conf_gen import (
    PerceptualBroadcastReachError,
    generated_contact_mic_conf_text,
)
from shared.perception_registry import (
    ExposureDomain,
    GeometryClass,
    HwSource,
    PerceptionPoint,
    PerceptionRegistry,
)

MK5_PRO_INPUT = "alsa_input.usb-MOTU_UltraLite-mk5_UL5LFEC2B0-00.pro-input-0"


def _cortado_registry(
    node_target: str = MK5_PRO_INPUT, position: str = "aux1"
) -> PerceptionRegistry:
    return PerceptionRegistry(
        points={
            "cortado": PerceptionPoint(
                geometry=GeometryClass.CONTACT,
                exposure=ExposureDomain.QUARANTINE,
                pipewire_node="contact_mic",
                voice_source_tag="contact-mic",
                hw_source=HwSource(node_target=node_target, position=position),
            )
        }
    )


def test_contact_mic_conf_emitted_from_registry_targets_mk5_aux1() -> None:
    conf = generated_contact_mic_conf_text(_cortado_registry())
    assert f'node.target = "{MK5_PRO_INPUT}"' in conf
    assert "audio.position = [ aux1 ]" in conf
    assert 'node.name = "contact_mic"' in conf
    # the bug is gone correct-by-construction: no retired L-12 device anywhere.
    assert "ZOOM_Corporation_L-12" not in conf
    # passive + dont-reconnect preserved (the room-mic-hijack guard).
    assert "node.passive = true" in conf
    assert "node.dont-reconnect = true" in conf


def test_cross_check_refuses_broadcast_reachable_target_for_quarantine_point() -> None:
    # A perceptual/quarantine point whose source resolves to the broadcast tap
    # must be refused at generation time (exposure=quarantine ⇒ not broadcast).
    bad = _cortado_registry(node_target="hapax-livestream-tap")
    with pytest.raises(PerceptualBroadcastReachError):
        generated_contact_mic_conf_text(bad)
