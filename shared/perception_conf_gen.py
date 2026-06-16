"""Generate pipewire source confs from the perception registry (lean SSOT spine).

The cortado contact-mic loopback conf was hand-authored (L-12 edition) with a
hand-typed ``node.target`` that drifted to the retired Zoom L-12, so the live
``contact_mic`` node fell through to mk5 capture_AUX0 (the Rode) = an eavesdrop
class. This module makes the conf a PURE FUNCTION of the registry's typed
``hw_source`` (device + position), so there is no hand-typed channel left to
drift, and emission of a perceptual/quarantine point onto a broadcast-reachable
target is refused at generation time.

REQ-20260616-perception-audio-ssot-program, Phase 1.
"""

from __future__ import annotations

from shared.audio_graph.model import ExposureDomain
from shared.perception_registry import PerceptionRegistry

# Node-name substrings that are broadcast-reachable. A perceptual/quarantine
# point may NEVER bind its capture to one of these (cross-check #3:
# exposure=quarantine ⇒ not broadcast-reachable). Mirrors the routing-check's
# broadcast spine (docs/audio-topology-reference.md).
_BROADCAST_REACHABLE = (
    "livestream-tap",
    "livestream",
    "broadcast-master",
    "broadcast-normalized",
    "obs-broadcast",
    "role.broadcast",
    "voice-fx",
    "voice-wet",
)

_GENERATED_HEADER = (
    "# GENERATED from config/perception-registry.yaml by\n"
    "# scripts/generate-pipewire-audio-confs.py — DO NOT EDIT.\n"
    "# Edit the registry point's hw_source and regenerate; the deployed copy is\n"
    "# byte-diff-gated against this output (REQ-20260616 Phase 1).\n"
)

# LEGACY mixer_master — preserved VERBATIM from the L-12-era conf so regeneration
# does not delete this live, heavily-consumed node (hapax-audio-ducker + audio
# reactivity + compositor read it). Its node.target is still the RETIRED Zoom
# L-12 (falls through at runtime); its correct mk5 source is an unresolved design
# question (the mk5 has no post-fader master mix). NOT yet modelled in the SSOT —
# see memory mixer-master-live-load-bearing + REQ-20260616.
_LEGACY_MIXER_MASTER_MODULE = (
    "    # LEGACY mixer_master (see module docstring) — preserved verbatim,\n"
    "    # pending its correct mk5-era source. Do NOT remove: live consumers.\n"
    "    {\n"
    "        name = libpipewire-module-loopback\n"
    "        args = {\n"
    '            node.description = "Mixer Master Output"\n'
    "            capture.props = {\n"
    "                audio.position = [ aux12 ]\n"
    "                stream.dont-remix = true\n"
    '                node.target = "alsa_input.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.multichannel-input"\n'
    "                node.passive = true\n"
    "                node.dont-reconnect = true\n"
    "            }\n"
    "            playback.props = {\n"
    '                node.name = "mixer_master"\n'
    '                node.description = "Mixer Master Output"\n'
    '                media.class = "Audio/Source"\n'
    "                audio.position = [ MONO ]\n"
    "            }\n"
    "        }\n"
    "    }\n"
)


class PerceptualBroadcastReachError(ValueError):
    """A quarantine/perceptual point's hw_source resolves to a broadcast target."""


def _is_broadcast_reachable(node_target: str) -> bool:
    return any(token in node_target for token in _BROADCAST_REACHABLE)


def _loopback_module(*, description: str, node_target: str, position: str, node_name: str) -> str:
    return (
        "    {\n"
        "        name = libpipewire-module-loopback\n"
        "        args = {\n"
        f'            node.description = "{description}"\n'
        "            capture.props = {\n"
        f"                audio.position = [ {position} ]\n"
        "                stream.dont-remix = true\n"
        f'                node.target = "{node_target}"\n'
        "                node.passive = true\n"
        "                node.dont-reconnect = true\n"
        "            }\n"
        "            playback.props = {\n"
        f'                node.name = "{node_name}"\n'
        f'                node.description = "{description}"\n'
        '                media.class = "Audio/Source"\n'
        "                audio.position = [ MONO ]\n"
        "            }\n"
        "        }\n"
        "    }\n"
    )


def generated_contact_mic_conf_text(
    registry: PerceptionRegistry, *, point_name: str = "cortado"
) -> str:
    """Emit the contact-mic loopback conf from the registry's typed hw_source.

    Cross-checks before emission:
      #1 target ∈ live-devices is enforced downstream by the byte-diff/check
         pass against the actual node set; here we require a non-empty target.
      #2 channel ↔ registry-point: the position + node.name come from the point.
      #3 exposure=quarantine ⇒ not broadcast-reachable (fail-closed here).
    """
    point = registry.points.get(point_name)
    if point is None:
        raise ValueError(
            f"registry has no point {point_name!r}. "
            f"Next: add a point named {point_name!r} to config/perception-registry.yaml, "
            "or pass point_name= matching an existing registry point."
        )
    src = point.hw_source
    if src is None:
        raise ValueError(
            f"point {point_name!r} has no hw_source; cannot generate its conf. "
            "Next: add an hw_source: {node_target: <alsa capture device>, position: <AUXn>} "
            f"block to the {point_name!r} point in config/perception-registry.yaml."
        )
    if not src.node_target:
        raise ValueError(
            f"point {point_name!r} hw_source.node_target is empty. "
            "Next: set hw_source.node_target to the capture device node name "
            "(e.g. alsa_input.usb-MOTU_UltraLite-mk5_...pro-input-0)."
        )
    if point.exposure == ExposureDomain.QUARANTINE and _is_broadcast_reachable(src.node_target):
        raise PerceptualBroadcastReachError(
            f"point {point_name!r} is exposure=quarantine but hw_source.node_target "
            f"{src.node_target!r} is broadcast-reachable — refusing to generate a conf "
            "that would route a perceptual sensor toward broadcast. "
            "Next: point hw_source.node_target at a capture device (e.g. the mk5 "
            "pro-input), OR — only if egress is genuinely intended and authorized "
            "by an AuthorityCase — set exposure='broadcast' on the registry point."
        )
    node_name = point.pipewire_node or point_name
    body = _loopback_module(
        description="Contact Microphone (Cortado)",
        node_target=src.node_target,
        position=src.position,
        node_name=node_name,
    )
    return f"{_GENERATED_HEADER}\ncontext.modules = [\n{body}{_LEGACY_MIXER_MASTER_MODULE}]\n"
