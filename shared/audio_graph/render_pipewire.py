"""Candidate PipeWire renderer for the mk5 port graph.

The renderer returns strings only. The CLI may write those strings to an
explicit shadow directory; this module never installs live PipeWire config.
"""

from __future__ import annotations

from shared.audio_graph.model import ModulationPath, PortAudioGraph
from shared.audio_graph.proof import generated_forbidden_edges


def render_pipewire_candidates(graph: PortAudioGraph) -> dict[str, str]:
    """Render deterministic candidate PipeWire snippets."""
    rendered: dict[str, str] = {}
    for node_id, node in sorted(graph.nodes.items()):
        lines = [
            "# Generated candidate by shared.audio_graph.render_pipewire",
            "# DO NOT HAND-EDIT; not installed by this renderer",
            f"# node_id: {node_id}",
            f"# kind: {node.kind}",
            f"# exposure: {node.exposure}",
        ]
        for effect in node.required_effects:
            lines.append(f"# required_effect: {effect}")
        for port_name, port in sorted(node.ports.items()):
            lines.append(
                "# port "
                f"{node_id}:{port_name} direction={port.direction} "
                f"exposure={port.exposure} autoconnect={str(port.autoconnect).lower()} "
                f"dont_reconnect={str(port.dont_reconnect).lower()} "
                f"dont_move={str(port.dont_move).lower()} "
                f"state_restore={str(port.state_restore).lower()}"
            )
        rendered[f"pipewire/{node_id}.conf"] = "\n".join(lines) + "\n"

    for source_id, source in sorted(graph.sources.items()):
        if source.modulation != ModulationPath.SOFTWARE_WET:
            continue
        wet_node_id = _wet_node_id(source_id, graph)
        profile = graph.wet_profiles[source.wet_profile or ""]
        lines = [
            "# Generated candidate hapax-wet profile",
            f"# source: {source_id}",
            f"# node_id: {wet_node_id}",
            f"# profile: {source.wet_profile}",
            f"# wet_mix_min: {profile.wet_mix_min}",
            "# wet/dry crossfade engine: SPA builtin mixer",
        ]
        for control in profile.controls:
            lines.append(
                f"# control {control.plugin}:{control.control} "
                f"default={control.default} range=[{control.min}, {control.max}]"
            )
        rendered[f"pipewire/{wet_node_id}-wet-profile.conf"] = "\n".join(lines) + "\n"
    return rendered


def _wet_node_id(source_id: str, graph: PortAudioGraph) -> str:
    candidate = f"hapax-wet-{source_id.replace('_', '-')}"
    if candidate in graph.nodes:
        return candidate
    return f"hapax-wet-{source_id}"


def render_link_map(graph: PortAudioGraph) -> str:
    """Render reconciler desired links."""
    lines = [
        "# Generated candidate by scripts/generate-audio-graph",
        "# DO NOT INSTALL DIRECTLY; Phase 1+2 shadow artifact only",
    ]
    lines.extend(edge.key for edge in graph.desired_links)
    return "\n".join(lines) + "\n"


def render_forbidden_link_map(graph: PortAudioGraph) -> str:
    """Render reconciler forbidden links."""
    lines = [
        "# Generated candidate by scripts/generate-audio-graph",
        "# DO NOT INSTALL DIRECTLY; Phase 1+2 shadow artifact only",
    ]
    forbidden = {edge.key for edge in graph.forbidden_links}
    forbidden.update(edge.key for edge in generated_forbidden_edges(graph))
    forbidden.update(edge.key for edge in graph.fence.known_blocked_links)
    lines.extend(sorted(forbidden))
    return "\n".join(lines) + "\n"


__all__ = [
    "render_forbidden_link_map",
    "render_link_map",
    "render_pipewire_candidates",
]
