"""Resolve audio-topology node ids to their live PipeWire names from the SSOT.

Long-running audio executors (notably ``hapax-audio-ducker``) historically
hardcoded PipeWire node names. The L-12 → mk5 migration renamed those nodes and
silently broke the executors — they kept writing to dead node names. Resolving
from ``config/audio-topology.yaml`` (the routing SSOT) means the NEXT hardware
migration is picked up automatically instead of re-breaking the executor (the
recurring "wiring not code" failure mode).

FAIL-OPEN contract: every resolve takes a hardcoded ``fallback`` used on ANY
failure (topology unreadable, unknown id, empty name). A topology-read error
must never crash or silence a duck daemon — it falls back to the pinned literal
and the caller logs. The duck node itself defaults to transparent passthrough,
so a fallback that points at an absent node simply leaves the bed un-ducked
(music never silenced), never the reverse.
"""

from __future__ import annotations

import logging

log = logging.getLogger("audio_node_resolver")


def resolve_audio_node(topology_id: str, fallback: str) -> str:
    """Return the live ``pipewire_name`` for ``topology_id``, or ``fallback``.

    Reads the static topology SSOT (not the live pw-dump) so resolution does
    not couple the daemon's startup to transient PipeWire graph state.
    """
    try:
        from shared.audio_routing_policy import load_audio_topology_descriptor

        topology = load_audio_topology_descriptor()
        node = topology.node_by_id(topology_id)
        name = getattr(node, "pipewire_name", None)
        if isinstance(name, str) and name:
            return name
        log.warning(
            "audio node %r resolved to empty pipewire_name; using fallback %r",
            topology_id,
            fallback,
        )
        return fallback
    except Exception as exc:  # fail-open — never crash the caller
        log.warning(
            "audio node %r resolve failed (%s); using fallback %r",
            topology_id,
            exc,
            fallback,
        )
        return fallback
