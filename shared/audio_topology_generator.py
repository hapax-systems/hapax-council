"""Topology descriptor → PipeWire conf generator (CLI Phase 2).

Emits PipeWire context.objects / context.modules fragments for each
node in a ``TopologyDescriptor`` so the live ``.conf`` files become a
deterministic artifact of the descriptor instead of a hand-authored
collection.

Current workstation confs the generator has to match:

- ``hapax-l6-evilpet-capture.conf`` — filter-chain with builtin mixer
  for +12 dB makeup gain on the L6 Main Mix AUX10+11 tap
- ``hapax-stream-split.conf`` — loopback pair (hapax-livestream +
  hapax-private) → Ryzen
- ``hapax-voice-fx-chain.conf`` — biquad-chain filter-chain targeting Ryzen

LADSPA chain templates (schema v3, audit F#8):

- ``loudnorm`` — single ``fast_lookahead_limiter_1913`` LADSPA stage
  with ``Input gain (dB) = 0``, configurable ``Limit (dB)`` and
  ``Release time (s)``. Matches the live shape of
  ``hapax-music-loudnorm.conf`` / ``hapax-voice-fx-loudnorm.conf``.
- ``duck`` — paired-mono ``builtin mixer`` (``duck_l`` / ``duck_r``)
  with ``Gain 1 = 1.0`` default. The audio-ducker daemon writes
  runtime gain via ``pw-cli``. Matches ``hapax-music-duck.conf`` /
  ``hapax-tts-duck.conf``.
- ``usb-bias`` — ``fast_lookahead_limiter_1913`` configured as a
  USB-IN line-driver: non-zero ``Input gain (dB)`` (clamped to the
  LADSPA ``[-20, +20]`` range; overshoot raises ``ConfigError``)
  with optional FL/FR → RL/RR remap on the playback side so the
  L-12 surround40 sink picks up the bias-driven stream on the rear
  pair. Matches ``hapax-music-usb-line-driver.conf``.

Scope:

- Phase 2 = per-node conf-fragment emission. ``node_to_conf_fragment``
  returns the text for one node; ``generate_confs`` groups them into
  descriptor-level ``{filename: content}`` dict.
- Out of scope: writing to disk, hot-reloading PipeWire (Phase 3 CLI),
  live-graph inspection (Phase 4).
- No Jinja dependency — f-string templates per kind keep the dep
  surface flat.

Round-trip guarantee: ``generate_confs(d)`` output captures enough to
reconstruct ``d`` when paired with Phase 4's ``pw_dump_to_descriptor``.
The confs themselves are not human-authored — operators edit the YAML
descriptor and regenerate.

Reference:
    - docs/superpowers/plans/2026-04-20-unified-audio-architecture-plan.md §2
"""

from __future__ import annotations

from collections.abc import Iterable

from shared.audio_topology import (
    Edge,
    Node,
    NodeKind,
    TopologyDescriptor,
)


class ConfigError(ValueError):
    """Generator-side configuration error (e.g. LADSPA range violation).

    Subclasses ``ValueError`` so existing callers that catch
    ``ValueError`` (the CLI's ``_load`` for example) still surface
    these as configuration errors. Distinct type so tests can assert
    range-clamp behaviour without false-positive matches against
    pydantic ``ValidationError`` messages.
    """


# LADSPA fast_lookahead_limiter_1913 ``Input gain (dB)`` is bounded by
# the upstream plugin to ``[-20, +20]``. Beyond that, the plugin
# silently saturates and the operator loses headroom budget without
# warning. The generator clamps explicitly so misconfigurations fail
# at codegen time, not at PipeWire-load time.
LADSPA_INPUT_GAIN_MIN_DB = -20.0
LADSPA_INPUT_GAIN_MAX_DB = 20.0


def _gain_db_to_linear(db: float) -> float:
    """Convert dB to PipeWire ``builtin mixer`` ``Gain`` linear scalar."""
    return 10 ** (db / 20.0)


def _channels_line(node: Node) -> str:
    """Format ``audio.channels = N`` / ``audio.position = [...]`` lines."""
    cm = node.channels
    positions = " ".join(cm.positions) if cm.positions else ""
    lines = [f"            audio.channels = {cm.count}"]
    if positions:
        lines.append(f"            audio.position = [ {positions} ]")
    return "\n".join(lines)


def _conf_literal(value: str | int | float | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return f'"{value}"'


def _params_lines(node: Node, indent: int = 12) -> str:
    """Format extra ``params`` as ``key = value`` conf lines.

    Skips keys that the node-kind template emits directly
    (``makeup_gain_linear``, ``audio.position``). Unknown keys
    round-trip verbatim so operator-supplied PipeWire tunables are
    preserved on regeneration.

    Schema-v3 LADSPA-template keys (``audit_role``, ``audit_classification``,
    etc.) are pure descriptor metadata — they belong to the YAML
    audit graph, not to the emitted conf, so they are filtered out
    at the source. Likewise the descriptor-side annotations used by
    the inspector / leak guard (``forbidden_target_family``,
    ``private_monitor_endpoint``, ``audit_role``) never need to land
    in PipeWire's runtime config.
    """
    reserved = {
        "makeup_gain_linear",
        "audio.channels",
        "audio.position",
        # Descriptor-only audit metadata — don't pollute the conf with
        # YAML-side bookkeeping. The inspector + leak guard read these
        # directly off the Node, never through the generated artifact.
        "audit_role",
        "audit_classification",
        "private_monitor_endpoint",
        "private_monitor_track",
        "private_monitor_bridge",
        "forbidden_target_family",
        "forbidden_capture_positions",
        "forbidden_destinations",
        "forbidden_targets",
        "fail_closed",
        "fail_closed_on_target_absent",
        "option_c_route",
        "retired_downstream_loopback",
        "broadcast_forward_path",
        "playback_target",
        "playback_source",
        "playback_node",
        "playback_node_passive",
        "playback_positions",
        "capture_source",
        "capture_channels",
        "capture_positions",
        "bypasses_l12",
        "fallback_to_l12_is_runtime_drift",
        "notification_excluded",
        "l12_return_pair",
        "limiter",
        "limit_db",
    }
    pad = " " * indent
    out: list[str] = []
    for k, v in node.params.items():
        if k in reserved:
            continue
        out.append(f"{pad}{k} = {_conf_literal(v)}")
    return "\n".join(out)


def _selected_params_lines(node: Node, keys: tuple[str, ...], indent: int = 16) -> str:
    pad = " " * indent
    out = []
    for key in keys:
        if key in node.params:
            out.append(f"{pad}{key} = {_conf_literal(node.params[key])}")
    return "\n".join(out)


def _alsa_source_fragment(node: Node) -> str:
    channels = _channels_line(node)
    extra = _params_lines(node)
    extra_block = f"\n{extra}" if extra else ""
    return f"""# {node.description or node.pipewire_name}
context.objects = [
    {{  factory = adapter
        args = {{
            factory.name = api.alsa.pcm.source
            node.name    = "{node.pipewire_name}"
            media.class  = Audio/Source
            audio.format = S32LE
{channels}
            api.alsa.path = "{node.hw}"{extra_block}
        }}
    }}
]
"""


def _alsa_sink_fragment(node: Node) -> str:
    channels = _channels_line(node)
    extra = _params_lines(node)
    extra_block = f"\n{extra}" if extra else ""
    return f"""# {node.description or node.pipewire_name}
context.objects = [
    {{  factory = adapter
        args = {{
            factory.name = api.alsa.pcm.sink
            node.name    = "{node.pipewire_name}"
            media.class  = Audio/Sink
            audio.format = S32LE
{channels}
            api.alsa.path = "{node.hw}"{extra_block}
        }}
    }}
]
"""


def _filter_chain_fragment(node: Node, incoming_edges: list[Edge]) -> str:
    """Emit a filter-chain module with optional per-edge makeup gain.

    If any ``incoming_edge.makeup_gain_db != 0``, a ``builtin mixer``
    node is inserted with ``Gain 1`` set to the linear equivalent.
    Multiple distinct gains on different incoming ports produce
    multiple mixer nodes (one per port).
    """
    cm = node.channels
    target_line = (
        f'            target.object = "{node.target_object}"' if node.target_object else ""
    )
    positions_str = " ".join(cm.positions) if cm.positions else ""
    position_block = f"\n            audio.position = [ {positions_str} ]" if positions_str else ""

    gain_edges = [e for e in incoming_edges if e.makeup_gain_db != 0.0]
    graph_block = ""
    if gain_edges:
        mixer_nodes = []
        inputs = []
        outputs = []
        for i, edge in enumerate(gain_edges):
            linear = _gain_db_to_linear(edge.makeup_gain_db)
            mixer_name = f"gain_{i}"
            mixer_nodes.append(
                f"                    {{ type = builtin label = mixer name = {mixer_name}\n"
                f'                      control = {{ "Gain 1" = {linear:.4f} }} }}'
            )
            inputs.append(f'"{mixer_name}:In 1"')
            outputs.append(f'"{mixer_name}:Out"')
        graph_block = f"""
            filter.graph = {{
                nodes = [
{chr(10).join(mixer_nodes)}
                ]
                inputs  = [ {" ".join(inputs)} ]
                outputs = [ {" ".join(outputs)} ]
            }}"""

    return f"""# {node.description or node.pipewire_name}
context.modules = [
    {{  name = libpipewire-module-filter-chain
        args = {{
            node.description = "{node.description or node.pipewire_name}"
            audio.rate = 44100
            audio.channels = {cm.count}{position_block}{graph_block}
            capture.props = {{
                node.name = "{node.pipewire_name}"
            }}
            playback.props = {{
                node.name = "{node.pipewire_name}-playback"
{target_line}
            }}
        }}
    }}
]
"""


def _format_loudnorm_chain(node: Node, _incoming: list[Edge]) -> str:
    """Emit a single ``fast_lookahead_limiter_1913`` LADSPA stage.

    Output ceiling = ``node.limit_db`` (required for ``loudnorm``
    chains). Release time defaults to 0.20 s when ``node.release_s``
    is None — matches the live ``hapax-music-loudnorm.conf`` /
    ``hapax-voice-fx-loudnorm.conf`` values.

    Input gain is hard-coded to 0 dB on this template — loudnorm is a
    pure ceiling stage; non-zero input gain is the ``usb-bias`` chain
    template's job.
    """
    if node.limit_db is None:
        raise ConfigError(
            f"Node {node.id!r} chain_kind='loudnorm' requires limit_db (LADSPA Limit dB)"
        )
    cm = node.channels
    positions_str = " ".join(cm.positions) if cm.positions else ""
    position_block = f"\n            audio.position = [ {positions_str} ]" if positions_str else ""
    target_line = (
        f'                target.object = "{node.target_object}"' if node.target_object else ""
    )
    release_s = node.release_s if node.release_s is not None else 0.20
    name_token = node.id.replace("-", "_")
    description = node.description or node.pipewire_name
    return f"""# {description}
context.modules = [
    {{  name = libpipewire-module-filter-chain
        args = {{
            node.name = "{node.pipewire_name}"
            node.description = "{description}"
            media.class = "Audio/Sink"
            audio.rate = 44100
            audio.channels = {cm.count}{position_block}

            filter.graph = {{
                nodes = [
                    {{ type = ladspa
                      plugin = "fast_lookahead_limiter_1913"
                      label = "fastLookaheadLimiter"
                      name = "{name_token}"
                      control = {{
                          "Input gain (dB)" = 0.0
                          "Limit (dB)"      = {node.limit_db}
                          "Release time (s)" = {release_s}
                      }}
                    }}
                ]
                inputs  = [ "{name_token}:Input 1"  "{name_token}:Input 2"  ]
                outputs = [ "{name_token}:Output 1" "{name_token}:Output 2" ]
            }}

            capture.props = {{
                node.name = "{node.pipewire_name}"
                media.class = "Audio/Sink"
            }}
            playback.props = {{
                node.name = "{node.pipewire_name}-playback"
{target_line}
                node.passive = false
                stream.dont-remix = true
            }}
        }}
    }}
]
"""


def _format_duck_chain(node: Node, _incoming: list[Edge]) -> str:
    """Emit a paired-mono ``builtin mixer`` ducker.

    ``duck_l`` and ``duck_r`` mono mixers wired as ``In 1 → Out`` so
    the daemon can write a single ``Gain 1`` per channel via
    ``pw-cli``. Default ``Gain 1 = 1.0`` is transparent passthrough;
    the audio-ducker daemon writes the duck depth (≈0.251 for -12 dB
    operator-VAD, ≈0.398 for -8 dB TTS) at runtime.

    Sink shape (``media.class = Audio/Sink``) so upstream filter-chain
    capture sides target it via ``target.object``.
    """
    cm = node.channels
    positions_str = " ".join(cm.positions) if cm.positions else ""
    position_block = f"\n            audio.position = [ {positions_str} ]" if positions_str else ""
    target_line = (
        f'                target.object = "{node.target_object}"' if node.target_object else ""
    )
    description = node.description or node.pipewire_name
    return f"""# {description}
context.modules = [
    {{  name = libpipewire-module-filter-chain
        args = {{
            node.name = "{node.pipewire_name}"
            node.description = "{description}"
            media.class = "Audio/Sink"
            audio.rate = 44100
            audio.channels = {cm.count}{position_block}

            filter.graph = {{
                nodes = [
                    {{ type = builtin name = duck_l label = mixer
                      control = {{ "Gain 1" = 1.0 }} }}
                    {{ type = builtin name = duck_r label = mixer
                      control = {{ "Gain 1" = 1.0 }} }}
                ]
                inputs  = [ "duck_l:In 1" "duck_r:In 1" ]
                outputs = [ "duck_l:Out"  "duck_r:Out"  ]
            }}

            capture.props = {{
                node.name = "{node.pipewire_name}"
                media.class = "Audio/Sink"
            }}
            playback.props = {{
                node.name = "{node.pipewire_name}-playback"
{target_line}
                node.passive = false
                stream.dont-remix = true
            }}
        }}
    }}
]
"""


def _format_usb_bias_chain(node: Node, _incoming: list[Edge]) -> str:
    """Emit a USB-IN line-driver ``fast_lookahead_limiter_1913`` stage.

    ``Input gain (dB)`` carries the bias (typically +9..+12 dB to
    substitute for the missing analog-trim stage on L-12 USB IN);
    the LADSPA plugin caps ``Input gain`` at ``[-20, +20]`` so the
    generator clamps explicitly and raises ``ConfigError`` on
    overshoot rather than silently saturating.

    When ``remap_to_rear=True``, the playback side's
    ``audio.position`` is rewritten to ``[ RL RR ]`` so the L-12
    surround40 sink picks the bias-driven stream up on the rear pair
    (the L-12 USB return convention). The capture side keeps the
    descriptor's declared positions.
    """
    if node.bias_db is None:
        raise ConfigError(
            f"Node {node.id!r} chain_kind='usb-bias' requires bias_db (LADSPA Input gain dB)"
        )
    if not (LADSPA_INPUT_GAIN_MIN_DB <= node.bias_db <= LADSPA_INPUT_GAIN_MAX_DB):
        raise ConfigError(
            f"Node {node.id!r} chain_kind='usb-bias': "
            f"bias_db={node.bias_db!r} outside LADSPA "
            f"fast_lookahead_limiter_1913 Input gain range "
            f"[{LADSPA_INPUT_GAIN_MIN_DB}, {LADSPA_INPUT_GAIN_MAX_DB}] dB. "
            "Beyond this range the LADSPA plugin silently saturates; "
            "fix at descriptor or split the chain into multiple stages."
        )
    cm = node.channels
    positions_str = " ".join(cm.positions) if cm.positions else ""
    position_block = f"\n            audio.position = [ {positions_str} ]" if positions_str else ""
    target_line = (
        f'                target.object = "{node.target_object}"' if node.target_object else ""
    )
    # Limit defaults to -1.0 dBFS true-peak when omitted — matches
    # MASTER_LIMITER_TRUE_PEAK_DBTP convention.
    limit_db = node.limit_db if node.limit_db is not None else -1.0
    # Release defaults to 0.05 s — matches MASTER_LIMITER_RELEASE_MS / 1000
    # for fast transient recovery on a line-driver.
    release_s = node.release_s if node.release_s is not None else 0.05
    name_token = node.id.replace("-", "_")
    description = node.description or node.pipewire_name
    if node.remap_to_rear:
        playback_position_block = "\n                audio.position = [ RL RR ]"
    elif positions_str:
        playback_position_block = f"\n                audio.position = [ {positions_str} ]"
    else:
        playback_position_block = ""
    return f"""# {description}
context.modules = [
    {{  name = libpipewire-module-filter-chain
        args = {{
            node.name = "{node.pipewire_name}"
            node.description = "{description}"
            media.class = "Audio/Sink"
            audio.rate = 44100
            audio.channels = {cm.count}{position_block}

            filter.graph = {{
                nodes = [
                    {{ type = ladspa
                      plugin = "fast_lookahead_limiter_1913"
                      label = "fastLookaheadLimiter"
                      name = "{name_token}"
                      control = {{
                          "Input gain (dB)" = {node.bias_db}
                          "Limit (dB)"      = {limit_db}
                          "Release time (s)" = {release_s}
                      }}
                    }}
                ]
                inputs  = [ "{name_token}:Input 1"  "{name_token}:Input 2"  ]
                outputs = [ "{name_token}:Output 1" "{name_token}:Output 2" ]
            }}

            capture.props = {{
                node.name = "{node.pipewire_name}"
                media.class = "Audio/Sink"
            }}
            playback.props = {{
                node.name = "{node.pipewire_name}-playback"
{target_line}
                node.passive = false{playback_position_block}
                stream.dont-remix = true
            }}
        }}
    }}
]
"""


# Dispatch table for ``chain_kind`` on filter_chain nodes (audit F#8).
_CHAIN_FORMATTERS = {
    "loudnorm": _format_loudnorm_chain,
    "duck": _format_duck_chain,
    "usb-bias": _format_usb_bias_chain,
}


def _loopback_fragment(node: Node) -> str:
    cm = node.channels
    positions_str = " ".join(cm.positions) if cm.positions else ""
    position_block = f"\n            audio.position = [ {positions_str} ]" if positions_str else ""
    target_line = (
        f'                target.object = "{node.target_object}"' if node.target_object else ""
    )
    capture_target = node.params.get("capture_source")
    capture_target_line = (
        f'                target.object = "{capture_target}"'
        if isinstance(capture_target, str) and capture_target
        else ""
    )
    capture_param_block = _selected_params_lines(
        node,
        ("stream.capture.sink", "state.restore", "stream.dont-remix"),
    )
    playback_param_block = _selected_params_lines(
        node,
        (
            "node.autoconnect",
            "node.dont-fallback",
            "node.dont-reconnect",
            "node.dont-move",
            "node.linger",
            "state.restore",
            "stream.dont-remix",
        ),
    )
    capture_extra = f"\n{capture_target_line}" if capture_target_line else ""
    if capture_param_block:
        capture_extra += f"\n{capture_param_block}"
    playback_extra = f"\n{target_line}" if target_line else ""
    if playback_param_block:
        playback_extra += f"\n{playback_param_block}"
    return f"""# {node.description or node.pipewire_name}
context.modules = [
    {{  name = libpipewire-module-loopback
        args = {{
            node.description = "{node.description or node.pipewire_name}"
            audio.rate = 44100
            audio.channels = {cm.count}{position_block}
            capture.props = {{
                node.name = "{node.pipewire_name}"
                media.class = Audio/Sink
{capture_extra}
            }}
            playback.props = {{
                node.name = "{node.pipewire_name}-output"
{playback_extra}
            }}
        }}
    }}
]
"""


def _tap_fragment(node: Node) -> str:
    """Null-sink / virtual sink — no audio processing, just a fan-out point."""
    cm = node.channels
    positions_str = " ".join(cm.positions) if cm.positions else ""
    position_block = (
        f"\n                audio.position = [ {positions_str} ]" if positions_str else ""
    )
    return f"""# {node.description or node.pipewire_name}
context.objects = [
    {{  factory = adapter
        args = {{
            factory.name = support.null-audio-sink
            node.name    = "{node.pipewire_name}"
            media.class  = Audio/Sink
            audio.channels = {cm.count}{position_block}
        }}
    }}
]
"""


def _filter_chain_dispatch(node: Node, incoming: list[Edge]) -> str:
    """Dispatch ``filter_chain`` nodes by ``chain_kind`` (schema v3).

    ``chain_kind`` is None → fall through to the legacy generic
    ``_filter_chain_fragment`` so existing descriptors keep round-
    tripping unchanged. When set, the matching LADSPA / builtin
    template handles the emit (loudnorm, duck, usb-bias).
    """
    if node.chain_kind is None:
        return _filter_chain_fragment(node, incoming)
    formatter = _CHAIN_FORMATTERS[node.chain_kind]
    return formatter(node, incoming)


_FORMATTERS = {
    NodeKind.ALSA_SOURCE: lambda n, _e: _alsa_source_fragment(n),
    NodeKind.ALSA_SINK: lambda n, _e: _alsa_sink_fragment(n),
    NodeKind.FILTER_CHAIN: _filter_chain_dispatch,
    NodeKind.LOOPBACK: lambda n, _e: _loopback_fragment(n),
    NodeKind.TAP: lambda n, _e: _tap_fragment(n),
}


def node_to_conf_fragment(node: Node, descriptor: TopologyDescriptor) -> str:
    """Emit the PipeWire conf fragment for a single node.

    Pulls incoming edges from the descriptor so filter-chain gain
    stages can be emitted correctly; other node kinds ignore edges.
    """
    incoming = descriptor.edges_to(node.id)
    formatter = _FORMATTERS[node.kind]
    return formatter(node, incoming)


def generate_confs(descriptor: TopologyDescriptor) -> dict[str, str]:
    """Emit ``{suggested_filename: conf_content}`` for every node.

    File-naming convention: ``pipewire/<node.id>.conf``. Keeps the
    scope one-node-per-file so a descriptor change regenerates a
    bounded set of files and the git diff is readable.
    """
    out: dict[str, str] = {}
    for node in descriptor.nodes:
        filename = f"pipewire/{node.id}.conf"
        out[filename] = node_to_conf_fragment(node, descriptor)
    return out


def _md(value: object) -> str:
    """Small Markdown table-cell formatter for generated audio reference docs."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value).replace("|", "\\|").replace("\n", " ")


def _table(headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_md(value) for value in row) + " |")
    return "\n".join(lines)


def _require_v4_sections(graph: object, section_names: tuple[str, ...]) -> dict[str, list[object]]:
    missing: list[str] = []
    invalid: list[str] = []
    sections: dict[str, list[object]] = {}
    for name in section_names:
        if not hasattr(graph, name):
            missing.append(name)
            continue
        value = getattr(graph, name)
        if isinstance(value, (str, bytes, dict)) or not isinstance(value, Iterable):
            invalid.append(name)
            continue
        sections[name] = list(value)
    if missing or invalid:
        detail: list[str] = []
        if missing:
            detail.append(f"missing v4 section(s): {', '.join(missing)}")
        if invalid:
            detail.append(f"non-iterable v4 section(s): {', '.join(invalid)}")
        raise ValueError("AudioGraph v4 input required: " + "; ".join(detail))
    return sections


def generate_fail_closed_policy_map(graph: object) -> dict[str, dict[str, object]]:
    """Return executable fail-closed policy input from AudioGraph v4 data.

    The return value is intentionally primitive (dict/list/bool/str) so a
    future conf/link-map generator can consume it without importing Pydantic
    models. The function reads typed v4 schema sections instead of parsing
    descriptor prose from ``params``.
    """
    sections = _require_v4_sections(
        graph,
        ("route_classes", "optional_devices", "hardware_patches"),
    )
    route_classes = {
        route_class.id: {
            "kind": route_class.kind.value,
            "broadcast_allowed": route_class.broadcast_allowed,
            "private_allowed": route_class.private_allowed,
            "default_autoconnect": route_class.default_autoconnect,
            "fail_closed_on_absent": route_class.fail_closed_on_absent,
            "recovery_action": route_class.recovery_action,
        }
        for route_class in sections["route_classes"]
    }
    optional_devices = {
        device.device_id: {
            "node_ids": list(device.node_ids),
            "default_state": device.default_state.value,
            "absent_is_ok": device.absent_is_ok,
            "fail_closed_when_absent": device.fail_closed_when_absent,
            "promotion_gate": device.promotion_gate,
        }
        for device in sections["optional_devices"]
    }
    hardware_patches = {
        patch.id: {
            "route_class": patch.route_class,
            "physical_edges": list(patch.physical_edges),
            "fail_closed_on_absent": patch.fail_closed_on_absent,
            "operator_verified": patch.operator_verified,
        }
        for patch in sections["hardware_patches"]
    }
    return {
        "route_classes": route_classes,
        "optional_devices": optional_devices,
        "hardware_patches": hardware_patches,
    }


def generate_audio_graph_reference_tables(graph: object) -> str:
    """Generate Markdown reference tables from AudioGraph v4 schema data."""
    sections = _require_v4_sections(
        graph,
        (
            "route_classes",
            "port_groups",
            "channel_pairs",
            "physical_edges",
            "hardware_patches",
            "optional_devices",
        ),
    )
    route_rows = [
        (
            route_class.id,
            route_class.kind.value,
            route_class.broadcast_allowed,
            route_class.private_allowed,
            route_class.default_autoconnect,
            route_class.fail_closed_on_absent,
            route_class.recovery_action,
        )
        for route_class in sections["route_classes"]
    ]
    port_group_rows = [
        (
            group.id,
            group.node_id,
            group.role.value,
            group.route_class,
            group.fail_closed,
            group.ports,
        )
        for group in sections["port_groups"]
    ]
    channel_pair_rows = [
        (pair.id, pair.left_port, pair.right_port, pair.route_class, pair.label)
        for pair in sections["channel_pairs"]
    ]
    physical_edge_rows = [
        (
            edge.id,
            edge.source_ports,
            edge.target_ports,
            edge.medium.value,
            edge.route_class,
            edge.channel_pair,
            edge.fail_closed_on_absent,
        )
        for edge in sections["physical_edges"]
    ]
    patch_rows = [
        (
            patch.id,
            patch.source_device,
            patch.target_device,
            patch.route_class,
            patch.fail_closed_on_absent,
            patch.physical_edges,
        )
        for patch in sections["hardware_patches"]
    ]
    optional_rows = [
        (
            device.device_id,
            device.node_ids,
            device.default_state.value,
            device.absent_is_ok,
            device.fail_closed_when_absent,
            device.promotion_gate,
        )
        for device in sections["optional_devices"]
    ]
    return "\n\n".join(
        [
            "### Route Classes\n\n"
            + _table(
                (
                    "ID",
                    "Kind",
                    "Broadcast",
                    "Private",
                    "Autoconnect",
                    "Fail Closed",
                    "Recovery",
                ),
                route_rows,
            ),
            "### Port Groups\n\n"
            + _table(
                ("ID", "Node", "Role", "Route Class", "Fail Closed", "Ports"),
                port_group_rows,
            ),
            "### Channel Pairs\n\n"
            + _table(
                ("ID", "Left Port", "Right Port", "Route Class", "Label"),
                channel_pair_rows,
            ),
            "### Physical Edges\n\n"
            + _table(
                (
                    "ID",
                    "Source Ports",
                    "Target Ports",
                    "Medium",
                    "Route Class",
                    "Channel Pair",
                    "Fail Closed",
                ),
                physical_edge_rows,
            ),
            "### Hardware Patches\n\n"
            + _table(
                (
                    "ID",
                    "Source Device",
                    "Target Device",
                    "Route Class",
                    "Fail Closed",
                    "Physical Edges",
                ),
                patch_rows,
            ),
            "### Optional Device Lifecycle\n\n"
            + _table(
                (
                    "Device",
                    "Nodes",
                    "Default State",
                    "Absent OK",
                    "Fail Closed",
                    "Promotion Gate",
                ),
                optional_rows,
            ),
        ]
    )
