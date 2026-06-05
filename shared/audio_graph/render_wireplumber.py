"""Candidate WirePlumber renderer for the mk5 port graph."""

from __future__ import annotations

from shared.audio_graph.model import PortAudioGraph
from shared.audio_graph.proof import generated_forbidden_edges


def render_wireplumber_candidates(graph: PortAudioGraph) -> dict[str, str]:
    """Render deterministic candidate WirePlumber snippets."""
    rendered: dict[str, str] = {}
    mk5 = graph.devices.get("motu_mk5")
    if mk5 is not None:
        rendered["wireplumber/14-hapax-mk5-pro-audio.conf"] = "\n".join(
            [
                "# Generated candidate by shared.audio_graph.render_wireplumber",
                "# DO NOT HAND-EDIT; not installed by this renderer",
                "monitor.alsa.rules = [",
                "  {",
                "    matches = [",
                f'      {{ device.name = "{mk5.match.get("device.name", "~alsa_card.*")}" }}',
                "    ]",
                "    actions = { update-props = {",
                f"      api.alsa.use-acp = {str(mk5.api_alsa_use_acp).lower()}",
                f'      device.profile = "{mk5.profile}"',
                "      api.acp.auto-profile = false",
                "      api.acp.auto-port = false",
                f"      default.clock.allowed-rates = [ {graph.clock.rate} ]",
                "      session.suspend-timeout-seconds = 0",
                "    } }",
                "  }",
                "]",
                "",
            ]
        )

    rendered["wireplumber/98-hapax-link-deny.lua"] = render_link_deny_lua(graph)
    return rendered


def render_link_deny_lua(graph: PortAudioGraph) -> str:
    """Render embedded forbidden policy for WirePlumber link-deny."""
    forbidden = {edge.key for edge in graph.forbidden_links}
    forbidden.update(edge.key for edge in generated_forbidden_edges(graph))
    forbidden.update(edge.key for edge in graph.fence.known_blocked_links)
    lines = [
        "-- Generated candidate by scripts/generate-audio-graph",
        "-- Embedded policy: no runtime file reads.",
        "local forbidden = {",
    ]
    for key in sorted(forbidden):
        lines.append(f'  ["{key}"] = true,')
    lines.extend(
        [
            "}",
            "",
            "return forbidden",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = ["render_link_deny_lua", "render_wireplumber_candidates"]
