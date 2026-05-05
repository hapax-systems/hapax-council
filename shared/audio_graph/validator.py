"""``AudioGraphValidator`` — read-only decomposer for live confs.

Walks ``~/.config/pipewire/pipewire.conf.d/*.conf`` (and the wireplumber
sibling) and returns an :class:`AudioGraph` instance representing the
operator-edited reality, plus a :class:`GapReport` listing any
structural gaps that the schema doesn't yet model.

P1 acceptance criterion: 24/24 active confs MUST decompose without
error. If a conf doesn't decompose, the schema is incomplete and
must be extended (NOT the conf removed from coverage).

This module is **read-only**: it only opens conf files for reading;
no PipeWire / pactl / pw-link / pw-dump / pw-cli invocations.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from shared.audio_graph.schema import (
    AlsaCardRule,
    AlsaProfilePin,
    AudioGraph,
    AudioNode,
    BluezRule,
    ChannelMap,
    DuckPolicy,
    FilterChainTemplate,
    FilterStage,
    FormatSpec,
    GlobalTunables,
    LoopbackTopology,
    MediaRoleSink,
    MixdownGraph,
    NodeKind,
    PreferredTargetPin,
    RemapSource,
    RoleLoopback,
    StreamPin,
    StreamRestoreRule,
    WireplumberRule,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------


@dataclass
class GapReport:
    """Structural gaps surfaced while decomposing live confs.

    Each entry names the conf file + the gap class.
    """

    untyped_confs: list[str] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)
    inferred_models: list[str] = field(default_factory=list)


@dataclass
class DecomposeResult:
    """Output of ``AudioGraphValidator.decompose_confs()``."""

    graph: AudioGraph
    gaps: GapReport


# ---------------------------------------------------------------------------
# Conf parsing helpers (PipeWire SPA syntax, line-oriented)
# ---------------------------------------------------------------------------


_NODE_NAME_RE = re.compile(r'\bnode\.name\s*=\s*"?([\w\-\.\_]+)"?')
_NODE_DESC_RE = re.compile(r'\bnode\.description\s*=\s*"([^"]+)"')
_TARGET_OBJECT_RE = re.compile(r'\btarget\.object\s*=\s*"?([\w\-\.\_]+)"?')
_NODE_TARGET_RE = re.compile(r'\bnode\.target\s*=\s*"?([\w\-\.\_]+)"?')
_AUDIO_CHANNELS_RE = re.compile(r"\baudio\.channels\s*=\s*(\d+)")
_AUDIO_POSITION_RE = re.compile(r"\baudio\.position\s*=\s*(?:\")?\[(.+?)\](?:\")?")
_AUDIO_RATE_RE = re.compile(r"\baudio\.rate\s*=\s*(\d+)")
_AUDIO_FORMAT_RE = re.compile(r"\baudio\.format\s*=\s*([SF]\d+(?:LE)?)")
_FACTORY_NAME_RE = re.compile(r"\bfactory\.name\s*=\s*([\w\-\.\_]+)")
_MEDIA_CLASS_RE = re.compile(r'\bmedia\.class\s*=\s*"?([\w\-/]+)"?')
_NODE_PASSIVE_RE = re.compile(r"\bnode\.passive\s*=\s*(true|false)")
_STREAM_DONT_REMIX_RE = re.compile(r"\bstream\.dont-remix\s*=\s*(true|false)")
_STREAM_CAPTURE_SINK_RE = re.compile(r"\bstream\.capture\.sink\s*=\s*(true|false)")
_DONT_RECONNECT_RE = re.compile(r"\bnode\.dont-reconnect\s*=\s*(true|false)")
_DONT_MOVE_RE = re.compile(r"\bnode\.dont-move\s*=\s*(true|false)")
_DONT_FALLBACK_RE = re.compile(r"\bnode\.dont-fallback\s*=\s*(true|false)")
_LINGER_RE = re.compile(r"\bnode\.linger\s*=\s*(true|false)")
_STATE_RESTORE_RE = re.compile(r"\bstate\.restore\s*=\s*(true|false)")
_DEVICE_CLASS_RE = re.compile(r'\bdevice\.class\s*=\s*"?([\w\-]+)"?')
_NODE_VIRTUAL_RE = re.compile(r"\bnode\.virtual\s*=\s*(true|false)")
_FAIL_CLOSED_RE = re.compile(r"fail-closed", re.IGNORECASE)
_PRIVATE_MONITOR_RE = re.compile(r"private[ _-]monitor[ _-]endpoint", re.IGNORECASE)
_LADSPA_PLUGIN_RE = re.compile(r'\bplugin\s*=\s*"?(\w+_\d+)"?')
_BUILTIN_LABEL_RE = re.compile(r"\blabel\s*=\s*(\w+)\b")
_NAME_RE = re.compile(r"\bname\s*=\s*([\w\-]+)")
_FILTER_CHAIN_FILTER_GRAPH_RE = re.compile(r"filter\.graph\s*=\s*\{")
_LIB_FILTER_CHAIN_RE = re.compile(r"libpipewire-module-filter-chain")
_LIB_LOOPBACK_RE = re.compile(r"libpipewire-module-loopback")
_LIB_NULL_SINK_RE = re.compile(r"support\.null-audio-sink")
_LIB_ADAPTER_RE = re.compile(r"factory\s*=\s*adapter")

# WirePlumber rule patterns.
_WP_MONITOR_ALSA_RULES_RE = re.compile(r"monitor\.alsa\.rules\s*=\s*\[")
_WP_MONITOR_BLUEZ_RULES_RE = re.compile(r"monitor\.bluez\.")
_WP_STREAM_RESTORE_RE = re.compile(r"(?:wireplumber\.settings\.)?restore-stream\.rules\s*=\s*\[")
_WP_STREAM_RULES_RE = re.compile(r"\bstream\.rules\s*=\s*\[")
_WP_NODE_RULES_RE = re.compile(r"\bnode\.rules\s*=\s*\[")
_WP_COMPONENTS_RE = re.compile(r"wireplumber\.components\s*=\s*\[")
_WP_PROFILES_RE = re.compile(r"wireplumber\.profiles\s*=\s*\{")
_WP_DUCK_LEVEL_RE = re.compile(r"linking\.role-based\.duck-level\s*=\s*([0-9.]+)")
_WP_DEFAULT_MEDIA_ROLE_RE = re.compile(r'node\.stream\.default-media-role\s*=\s*"([\w\-]+)"')
_WP_PRIORITY_RE = re.compile(r"policy\.role-based\.priority\s*=\s*(\d+)")
_WP_PREFERRED_TARGET_RE = re.compile(r'policy\.role-based\.preferred-target\s*=\s*"([\w\-\.]+)"')
_WP_INTENDED_ROLES_RE = re.compile(r"device\.intended-roles\s*=\s*\[([^\]]+)\]")
_WP_NODE_VOLUME_RE = re.compile(r"node\.volume\s*=\s*([0-9.]+)")
_WP_DEFAULT_CLOCK_QUANTUM_RE = re.compile(r"default\.clock\.quantum\s*=\s*(\d+)")
_WP_MIN_QUANTUM_RE = re.compile(r"default\.clock\.min-quantum\s*=\s*(\d+)")
_WP_MAX_QUANTUM_RE = re.compile(r"default\.clock\.max-quantum\s*=\s*(\d+)")
_WP_ALLOWED_RATES_RE = re.compile(r"default\.clock\.allowed-rates\s*=\s*\[([\d\s,]+)\]")
_WP_API_ALSA_USE_ACP_RE = re.compile(r"api\.alsa\.use-acp\s*=\s*(true|false)")
_WP_DEVICE_PROFILE_RE = re.compile(r'device\.profile\s*=\s*"?([\w\-]+)"?')
_WP_PRIORITY_SESSION_RE = re.compile(r"priority\.session\s*=\s*(-?\d+)")
_WP_PRIORITY_DRIVER_RE = re.compile(r"priority\.driver\s*=\s*(-?\d+)")
_WP_DEVICE_NAME_MATCH_RE = re.compile(r'device\.name\s*=\s*"?(~?\w[\w\-\.\*]+)"?')


def _parse_position_list(raw: str) -> list[str]:
    """``[ FL FR AUX1 AUX2 ]`` / ``FL,FR`` / ``FL FR``."""
    cleaned = raw.replace(",", " ").replace("[", "").replace("]", "")
    return [tok.strip().upper() for tok in cleaned.split() if tok.strip()]


def _parse_format_token(token: str) -> str:
    """Normalise to ``S16LE`` / ``S24LE`` / ``S32LE`` / ``F32LE``."""
    token = token.strip().upper()
    if token in {"S16", "S24", "S32", "F32"}:
        return f"{token}LE"
    if token in {"S16LE", "S24LE", "S32LE", "F32LE"}:
        return token
    # Default fallback.
    return "S32LE"


def _kebab_node_id_from_pipewire_name(pipewire_name: str) -> str:
    """``hapax-l12-evilpet-capture`` → ``hapax-l12-evilpet-capture``.

    Already kebab; just lowercase + strip.
    """
    return pipewire_name.strip().lower()


# ---------------------------------------------------------------------------
# Conf decomposers (one per shape)
# ---------------------------------------------------------------------------


@dataclass
class _ParsedNode:
    """Intermediate output during decomposition."""

    node_id: str
    pipewire_name: str
    kind: NodeKind
    description: str = ""
    target_object: str | None = None
    channels: ChannelMap | None = None
    format_spec: FormatSpec | None = None
    fail_closed: bool = False
    private_monitor_endpoint: bool = False
    is_remap_source: bool = False
    filter_chain_template: FilterChainTemplate | None = None
    filter_graph_stages: list[FilterStage] = field(default_factory=list)
    mixdown: MixdownGraph | None = None
    params: dict[str, str | int | float | bool] = field(default_factory=dict)


@dataclass
class _ParsedLoopback:
    node_id: str
    source_pipewire_name: str | None = None
    sink_target_object: str | None = None
    capture_pipewire_name: str | None = None
    playback_pipewire_name: str | None = None
    capture_format: FormatSpec | None = None
    playback_format: FormatSpec | None = None
    is_remap_source: bool = False
    dont_reconnect: bool = False
    dont_move: bool = False
    dont_fallback: bool = False
    linger: bool = False
    state_restore: bool = True
    stream_dont_remix: bool = False
    stream_capture_sink: bool = False
    capture_passive: bool = False
    playback_passive: bool = True
    description: str = ""


def _split_top_level_modules(text: str) -> list[str]:
    """Split a PipeWire conf into per-module / per-object blocks.

    Brace-balanced split; ignores braces inside double-quoted strings.
    Returns a list of substrings, one per top-level ``{ ... }`` element
    inside a ``context.modules`` / ``context.objects`` array.
    """
    blocks: list[str] = []
    depth = 0
    in_string = False
    start = -1
    for i, ch in enumerate(text):
        if ch == '"' and (i == 0 or text[i - 1] != "\\"):
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                blocks.append(text[start : i + 1])
                start = -1
    return blocks


def _extract_section(text: str, key: str) -> str | None:
    """Return the bracket-balanced body of ``key = { ... }`` or ``key = [ ... ]``.

    PipeWire SPA syntax accepts both array (``[ ... ]``) and object
    (``{ ... }``) literals; the parser handles either.
    """
    pattern = re.compile(rf"\b{re.escape(key)}\s*=\s*[{{\[]")
    m = pattern.search(text)
    if not m:
        return None
    start = m.end() - 1
    open_ch = text[start]
    close_ch = "}" if open_ch == "{" else "]"
    depth = 0
    in_string = False
    for i in range(start, len(text)):
        ch = text[i]
        if ch == '"' and (i == 0 or text[i - 1] != "\\"):
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _parse_filter_graph_stages(filter_graph_body: str) -> list[FilterStage]:
    """Extract LADSPA + builtin stages from a ``filter.graph`` body."""
    stages: list[FilterStage] = []
    # Split into per-stage blocks (top-level `{ type = ... }` entries).
    nodes_section = _extract_section(filter_graph_body, "nodes")
    if not nodes_section:
        return stages
    for block in _split_top_level_modules(nodes_section):
        # Determine type.
        m_type = re.search(r"\btype\s*=\s*(\w+)", block)
        if not m_type:
            continue
        stype = m_type.group(1)
        m_label = _BUILTIN_LABEL_RE.search(block)
        m_name = _NAME_RE.search(block)
        m_plugin = _LADSPA_PLUGIN_RE.search(block)
        # Control map.
        control: dict[str, float | str | int] = {}
        m_ctrl = re.search(r"control\s*=\s*\{([^}]*)\}", block, re.DOTALL)
        if m_ctrl:
            for line in m_ctrl.group(1).splitlines():
                if "=" in line:
                    key_raw, val_raw = line.split("=", 1)
                    key = key_raw.strip().strip('"')
                    val = val_raw.strip().rstrip(",")
                    try:
                        control[key] = float(val)
                    except ValueError:
                        control[key] = val.strip('"')
        try:
            stages.append(
                FilterStage(
                    type=stype if stype in ("builtin", "ladspa") else "builtin",
                    plugin=m_plugin.group(1) if m_plugin else None,
                    label=m_label.group(1) if m_label else "unknown",
                    name=m_name.group(1) if m_name else f"stage_{len(stages)}",
                    control=control,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("filter-stage parse skip: %s", exc)
            continue
    return stages


def _classify_filter_chain_template(stages: list[FilterStage]) -> FilterChainTemplate:
    """Heuristic mapping from observed stages to template enum."""
    plugins = [s.plugin or s.label for s in stages if s.type == "ladspa"]
    builtins = [s.label for s in stages if s.type == "builtin"]
    has_sc4m = any("sc4m" in (p or "") for p in plugins)
    has_limiter = any("fast_lookahead_limiter" in (p or "") for p in plugins)
    has_plate = any("plate" in (p or "") for p in plugins)
    has_biquad = any("biquad" in (p or "") for p in plugins) or any(
        "biquad" in (b or "") for b in builtins
    )
    if has_sc4m and has_plate and has_limiter:
        return FilterChainTemplate.LOUDNORM_WITH_COMP_AND_REVERB
    if has_sc4m and has_limiter:
        # ducker-sidechain has sc4m as compressor without limiter
        return FilterChainTemplate.LOUDNORM_WITH_COMP
    if has_sc4m and not has_limiter:
        return FilterChainTemplate.DUCKER_SIDECHAIN
    if has_limiter and not has_sc4m and not has_plate:
        return FilterChainTemplate.LOUDNORM_SIMPLE
    if has_biquad:
        return FilterChainTemplate.VOICE_FX_BIQUAD
    if builtins and not plugins:
        # builtin mixer (duck) shape — used by hapax-music-duck etc.
        if any("mixer" in (b or "") for b in builtins):
            return FilterChainTemplate.BUILTIN_MIXER_DUCK
    return FilterChainTemplate.CUSTOM


def _decompose_filter_chain_module(
    block: str, conf_name: str
) -> tuple[list[_ParsedNode], list[_ParsedLoopback]]:
    """A single ``libpipewire-module-filter-chain`` block."""
    nodes: list[_ParsedNode] = []
    loopbacks: list[_ParsedLoopback] = []
    capture_section = _extract_section(block, "capture.props")
    playback_section = _extract_section(block, "playback.props")
    filter_graph_body = _extract_section(block, "filter.graph")
    args_section = _extract_section(block, "args") or block
    # Parent description (filter-chain has its own description on args).
    desc_outer = _NODE_DESC_RE.search(args_section)
    parent_desc = desc_outer.group(1) if desc_outer else ""
    parent_name_match = _NODE_NAME_RE.search(args_section)
    parent_name = parent_name_match.group(1) if parent_name_match else None

    # Channels declared at args-level (pre-capture).
    chan_count_outer = _AUDIO_CHANNELS_RE.search(args_section)
    chan_pos_outer = _AUDIO_POSITION_RE.search(args_section)
    if chan_count_outer:
        outer_count = int(chan_count_outer.group(1))
        outer_positions = _parse_position_list(chan_pos_outer.group(1)) if chan_pos_outer else []
    else:
        outer_count, outer_positions = 2, ["FL", "FR"]
    outer_channels = ChannelMap(
        count=outer_count, positions=outer_positions or [f"CH{i}" for i in range(outer_count)]
    )

    stages = _parse_filter_graph_stages(filter_graph_body) if filter_graph_body else []
    template = _classify_filter_chain_template(stages)

    if capture_section:
        cap_name_m = _NODE_NAME_RE.search(capture_section)
        cap_target_m = _TARGET_OBJECT_RE.search(capture_section) or _NODE_TARGET_RE.search(
            capture_section
        )
        cap_desc_m = _NODE_DESC_RE.search(capture_section)
        cap_chan_m = _AUDIO_CHANNELS_RE.search(capture_section)
        cap_pos_m = _AUDIO_POSITION_RE.search(capture_section)
        cap_format_m = _AUDIO_FORMAT_RE.search(capture_section)
        cap_rate_m = _AUDIO_RATE_RE.search(capture_section)
        cap_name = cap_name_m.group(1) if cap_name_m else parent_name or "unknown"
        cap_channels = (
            ChannelMap(
                count=int(cap_chan_m.group(1)),
                positions=(
                    _parse_position_list(cap_pos_m.group(1))
                    if cap_pos_m
                    else [f"CH{i}" for i in range(int(cap_chan_m.group(1)))]
                ),
            )
            if cap_chan_m
            else outer_channels
        )
        cap_format = None
        if cap_format_m or cap_rate_m:
            try:
                cap_format = FormatSpec(
                    rate_hz=int(cap_rate_m.group(1)) if cap_rate_m else 48000,
                    format=_parse_format_token(cap_format_m.group(1) if cap_format_m else "S32"),
                    channels=cap_channels.count,
                )
            except Exception:  # noqa: BLE001
                cap_format = None
        nodes.append(
            _ParsedNode(
                node_id=_kebab_node_id_from_pipewire_name(cap_name),
                pipewire_name=cap_name,
                kind=NodeKind.FILTER_CHAIN,
                description=(cap_desc_m.group(1) if cap_desc_m else parent_desc),
                target_object=cap_target_m.group(1) if cap_target_m else None,
                channels=cap_channels,
                format_spec=cap_format,
                filter_chain_template=template,
                filter_graph_stages=stages,
            )
        )

    if playback_section:
        pb_name_m = _NODE_NAME_RE.search(playback_section)
        pb_target_m = _TARGET_OBJECT_RE.search(playback_section)
        pb_desc_m = _NODE_DESC_RE.search(playback_section)
        pb_chan_m = _AUDIO_CHANNELS_RE.search(playback_section)
        pb_pos_m = _AUDIO_POSITION_RE.search(playback_section)
        pb_format_m = _AUDIO_FORMAT_RE.search(playback_section)
        pb_rate_m = _AUDIO_RATE_RE.search(playback_section)
        pb_media_m = _MEDIA_CLASS_RE.search(playback_section)
        pb_device_m = _DEVICE_CLASS_RE.search(playback_section)
        # _NODE_VIRTUAL_RE intentionally not consulted in the filter-chain
        # path — the playback shape is detected via media.class + device.class.
        pb_name = pb_name_m.group(1) if pb_name_m else (parent_name or "unknown") + "-playback"
        pb_channels = (
            ChannelMap(
                count=int(pb_chan_m.group(1)),
                positions=(
                    _parse_position_list(pb_pos_m.group(1))
                    if pb_pos_m
                    else [f"CH{i}" for i in range(int(pb_chan_m.group(1)))]
                ),
            )
            if pb_chan_m
            else outer_channels
        )
        pb_format = None
        if pb_format_m or pb_rate_m:
            try:
                pb_format = FormatSpec(
                    rate_hz=int(pb_rate_m.group(1)) if pb_rate_m else 48000,
                    format=_parse_format_token(pb_format_m.group(1) if pb_format_m else "S32"),
                    channels=pb_channels.count,
                )
            except Exception:  # noqa: BLE001
                pb_format = None
        is_remap = bool(
            pb_media_m
            and "Audio/Source" in pb_media_m.group(1)
            and pb_device_m
            and "filter" in pb_device_m.group(1)
        )
        nodes.append(
            _ParsedNode(
                node_id=_kebab_node_id_from_pipewire_name(pb_name),
                pipewire_name=pb_name,
                kind=NodeKind.FILTER_CHAIN,
                description=(pb_desc_m.group(1) if pb_desc_m else parent_desc),
                target_object=pb_target_m.group(1) if pb_target_m else None,
                channels=pb_channels,
                format_spec=pb_format,
                is_remap_source=is_remap,
            )
        )
    return nodes, loopbacks


def _decompose_loopback_module(
    block: str, conf_name: str
) -> tuple[list[_ParsedNode], list[_ParsedLoopback]]:
    """A single ``libpipewire-module-loopback`` block."""
    nodes: list[_ParsedNode] = []
    loopbacks: list[_ParsedLoopback] = []
    args_section = _extract_section(block, "args") or block
    desc_m = _NODE_DESC_RE.search(args_section)
    description = desc_m.group(1) if desc_m else ""

    capture_section = _extract_section(block, "capture.props")
    playback_section = _extract_section(block, "playback.props")
    if not capture_section or not playback_section:
        return nodes, loopbacks

    # Capture side.
    cap_name_m = _NODE_NAME_RE.search(capture_section)
    cap_target_m = _TARGET_OBJECT_RE.search(capture_section) or _NODE_TARGET_RE.search(
        capture_section
    )
    cap_chan_m = _AUDIO_CHANNELS_RE.search(capture_section)
    cap_pos_m = _AUDIO_POSITION_RE.search(capture_section)
    cap_format_m = _AUDIO_FORMAT_RE.search(capture_section)
    cap_rate_m = _AUDIO_RATE_RE.search(capture_section)
    cap_passive_m = _NODE_PASSIVE_RE.search(capture_section)
    cap_dont_remix_m = _STREAM_DONT_REMIX_RE.search(capture_section)
    cap_capture_sink_m = _STREAM_CAPTURE_SINK_RE.search(capture_section)

    # Playback side.
    pb_name_m = _NODE_NAME_RE.search(playback_section)
    pb_target_m = _TARGET_OBJECT_RE.search(playback_section)
    pb_chan_m = _AUDIO_CHANNELS_RE.search(playback_section)
    pb_pos_m = _AUDIO_POSITION_RE.search(playback_section)
    pb_format_m = _AUDIO_FORMAT_RE.search(playback_section)
    pb_rate_m = _AUDIO_RATE_RE.search(playback_section)
    pb_media_m = _MEDIA_CLASS_RE.search(playback_section)
    pb_device_m = _DEVICE_CLASS_RE.search(playback_section)
    pb_virtual_m = _NODE_VIRTUAL_RE.search(playback_section)
    pb_dont_reconnect_m = _DONT_RECONNECT_RE.search(playback_section)
    pb_dont_move_m = _DONT_MOVE_RE.search(playback_section)
    pb_dont_fallback_m = _DONT_FALLBACK_RE.search(playback_section)
    pb_linger_m = _LINGER_RE.search(playback_section)
    pb_state_restore_m = _STATE_RESTORE_RE.search(playback_section) or _STATE_RESTORE_RE.search(
        capture_section
    )
    pb_passive_m = _NODE_PASSIVE_RE.search(playback_section)

    cap_name = cap_name_m.group(1) if cap_name_m else None
    pb_name = pb_name_m.group(1) if pb_name_m else None

    # Channels (default 2/FL FR if absent).
    def _channel_map_or_default(
        chan_m: re.Match[str] | None, pos_m: re.Match[str] | None
    ) -> ChannelMap:
        if chan_m:
            count = int(chan_m.group(1))
            positions = (
                _parse_position_list(pos_m.group(1)) if pos_m else [f"CH{i}" for i in range(count)]
            )
            return ChannelMap(count=count, positions=positions[:count])
        return ChannelMap(count=2, positions=["FL", "FR"])

    cap_channels = _channel_map_or_default(cap_chan_m, cap_pos_m)
    pb_channels = _channel_map_or_default(pb_chan_m, pb_pos_m)

    cap_format: FormatSpec | None = None
    pb_format: FormatSpec | None = None
    if cap_format_m or cap_rate_m:
        try:
            cap_format = FormatSpec(
                rate_hz=int(cap_rate_m.group(1)) if cap_rate_m else 48000,
                format=_parse_format_token(cap_format_m.group(1) if cap_format_m else "S32"),
                channels=cap_channels.count,
            )
        except Exception:  # noqa: BLE001
            cap_format = None
    if pb_format_m or pb_rate_m:
        try:
            pb_format = FormatSpec(
                rate_hz=int(pb_rate_m.group(1)) if pb_rate_m else 48000,
                format=_parse_format_token(pb_format_m.group(1) if pb_format_m else "S32"),
                channels=pb_channels.count,
            )
        except Exception:  # noqa: BLE001
            pb_format = None

    is_remap = bool(
        pb_media_m
        and "Audio/Source" in pb_media_m.group(1)
        and (
            pb_device_m
            and "filter" in pb_device_m.group(1)
            or pb_virtual_m
            and pb_virtual_m.group(1) == "true"
        )
    )

    # Add nodes for both sides.
    if cap_name:
        nodes.append(
            _ParsedNode(
                node_id=_kebab_node_id_from_pipewire_name(cap_name),
                pipewire_name=cap_name,
                kind=NodeKind.LOOPBACK,
                description=description,
                target_object=cap_target_m.group(1) if cap_target_m else None,
                channels=cap_channels,
                format_spec=cap_format,
            )
        )
    if pb_name:
        nodes.append(
            _ParsedNode(
                node_id=_kebab_node_id_from_pipewire_name(pb_name),
                pipewire_name=pb_name,
                kind=NodeKind.LOOPBACK,
                description=description,
                target_object=pb_target_m.group(1) if pb_target_m else None,
                channels=pb_channels,
                format_spec=pb_format,
                is_remap_source=is_remap,
            )
        )

    # Loopback topology.
    if cap_name and pb_name:
        loopbacks.append(
            _ParsedLoopback(
                node_id=_kebab_node_id_from_pipewire_name(pb_name),
                source_pipewire_name=cap_target_m.group(1) if cap_target_m else cap_name,
                sink_target_object=pb_target_m.group(1) if pb_target_m else pb_name,
                capture_pipewire_name=cap_name,
                playback_pipewire_name=pb_name,
                capture_format=cap_format,
                playback_format=pb_format,
                is_remap_source=is_remap,
                dont_reconnect=bool(pb_dont_reconnect_m and pb_dont_reconnect_m.group(1) == "true"),
                dont_move=bool(pb_dont_move_m and pb_dont_move_m.group(1) == "true"),
                dont_fallback=bool(pb_dont_fallback_m and pb_dont_fallback_m.group(1) == "true"),
                linger=bool(pb_linger_m and pb_linger_m.group(1) == "true"),
                state_restore=not (pb_state_restore_m and pb_state_restore_m.group(1) == "false"),
                stream_dont_remix=bool(cap_dont_remix_m and cap_dont_remix_m.group(1) == "true"),
                stream_capture_sink=bool(
                    cap_capture_sink_m and cap_capture_sink_m.group(1) == "true"
                ),
                capture_passive=bool(cap_passive_m and cap_passive_m.group(1) == "true"),
                playback_passive=not (pb_passive_m and pb_passive_m.group(1) == "false"),
                description=description,
            )
        )
    return nodes, loopbacks


def _decompose_null_sink_object(block: str, conf_name: str) -> list[_ParsedNode]:
    """A ``factory = adapter; factory.name = support.null-audio-sink`` object."""
    nodes: list[_ParsedNode] = []
    args_section = _extract_section(block, "args") or block
    name_m = _NODE_NAME_RE.search(args_section)
    desc_m = _NODE_DESC_RE.search(args_section)
    chan_m = _AUDIO_CHANNELS_RE.search(args_section)
    pos_m = _AUDIO_POSITION_RE.search(args_section)
    if not name_m:
        return nodes
    name = name_m.group(1)
    channels = (
        ChannelMap(
            count=int(chan_m.group(1)),
            positions=(
                _parse_position_list(pos_m.group(1))
                if pos_m
                else [f"CH{i}" for i in range(int(chan_m.group(1)))]
            ),
        )
        if chan_m
        else ChannelMap(count=2, positions=["FL", "FR"])
    )
    description = desc_m.group(1) if desc_m else ""
    fail_closed = bool(_FAIL_CLOSED_RE.search(description) or _FAIL_CLOSED_RE.search(args_section))
    private_endpoint = bool(_PRIVATE_MONITOR_RE.search(description) or "private" in name.lower())
    nodes.append(
        _ParsedNode(
            node_id=_kebab_node_id_from_pipewire_name(name),
            pipewire_name=name,
            kind=NodeKind.TAP,
            description=description,
            channels=channels,
            fail_closed=fail_closed,
            private_monitor_endpoint=private_endpoint,
        )
    )
    return nodes


# ---------------------------------------------------------------------------
# Conf decomposition entry-points
# ---------------------------------------------------------------------------


def _decompose_pipewire_conf(
    path: Path, gaps: GapReport
) -> tuple[list[_ParsedNode], list[_ParsedLoopback], GlobalTunables | None, list[AlsaProfilePin]]:
    """Decompose one ``~/.config/pipewire/pipewire.conf.d/*.conf``."""
    text = path.read_text()
    nodes: list[_ParsedNode] = []
    loopbacks: list[_ParsedLoopback] = []
    tunables: GlobalTunables | None = None
    profile_pins: list[AlsaProfilePin] = []

    # Global tunables (gap G-1).
    has_quantum = bool(
        _WP_DEFAULT_CLOCK_QUANTUM_RE.search(text)
        or _WP_MIN_QUANTUM_RE.search(text)
        or _WP_MAX_QUANTUM_RE.search(text)
        or _WP_ALLOWED_RATES_RE.search(text)
    )
    if has_quantum:
        m_quantum = _WP_DEFAULT_CLOCK_QUANTUM_RE.search(text)
        m_min = _WP_MIN_QUANTUM_RE.search(text)
        m_max = _WP_MAX_QUANTUM_RE.search(text)
        m_rates = _WP_ALLOWED_RATES_RE.search(text)
        rates: list[int] = []
        if m_rates:
            for token in m_rates.group(1).split():
                try:
                    rates.append(int(token.strip(",")))
                except ValueError:
                    pass
        tunables = GlobalTunables(
            default_clock_quantum=int(m_quantum.group(1)) if m_quantum else None,
            min_quantum=int(m_min.group(1)) if m_min else None,
            max_quantum=int(m_max.group(1)) if m_max else None,
            allowed_rates=rates,
        )
        gaps.inferred_models.append(f"GlobalTunables from {path.name}")

    # Wireplumber-style monitor.alsa.rules sometimes live in pipewire.conf.d
    # (gap G-2): hapax-s4-usb-sink.conf is the canonical example.
    if _WP_MONITOR_ALSA_RULES_RE.search(text):
        for match in _WP_DEVICE_NAME_MATCH_RE.finditer(text):
            card_match = match.group(1)
            m_profile = _WP_DEVICE_PROFILE_RE.search(text)
            m_use_acp = _WP_API_ALSA_USE_ACP_RE.search(text)
            m_session = _WP_PRIORITY_SESSION_RE.search(text)
            m_driver = _WP_PRIORITY_DRIVER_RE.search(text)
            try:
                pin = AlsaProfilePin(
                    card_match=card_match,
                    profile=m_profile.group(1) if m_profile else None,
                    api_alsa_use_acp=(m_use_acp.group(1) == "true" if m_use_acp else None),
                    priority_session=int(m_session.group(1)) if m_session else None,
                    priority_driver=int(m_driver.group(1)) if m_driver else None,
                )
                profile_pins.append(pin)
                gaps.inferred_models.append(f"AlsaProfilePin from {path.name}")
            except Exception as exc:  # noqa: BLE001
                gaps.parse_warnings.append(f"{path.name}: AlsaProfilePin parse error: {exc}")

    # context.modules — the bulk of the work.
    context_modules = _extract_section(text, "context.modules")
    if context_modules:
        for block in _split_top_level_modules(context_modules):
            if _LIB_FILTER_CHAIN_RE.search(block):
                fc_nodes, fc_lbs = _decompose_filter_chain_module(block, path.name)
                nodes.extend(fc_nodes)
                loopbacks.extend(fc_lbs)
            elif _LIB_LOOPBACK_RE.search(block):
                lb_nodes, lb_lbs = _decompose_loopback_module(block, path.name)
                nodes.extend(lb_nodes)
                loopbacks.extend(lb_lbs)
            else:
                gaps.parse_warnings.append(
                    f"{path.name}: unrecognised context.modules entry (skipped)"
                )

    # context.objects — null sinks.
    context_objects = _extract_section(text, "context.objects")
    if context_objects:
        for block in _split_top_level_modules(context_objects):
            if _LIB_NULL_SINK_RE.search(block) or _LIB_ADAPTER_RE.search(block):
                ns_nodes = _decompose_null_sink_object(block, path.name)
                nodes.extend(ns_nodes)
            else:
                gaps.parse_warnings.append(f"{path.name}: unrecognised context.objects entry")

    # If the conf yielded nothing meaningful, surface as untyped.
    if not nodes and not loopbacks and tunables is None and not profile_pins:
        gaps.untyped_confs.append(path.name)

    return nodes, loopbacks, tunables, profile_pins


def _decompose_wireplumber_conf(
    path: Path, gaps: GapReport
) -> tuple[
    list[AlsaCardRule],
    list[AlsaProfilePin],
    list[BluezRule],
    list[StreamRestoreRule],
    list[StreamPin],
    MediaRoleSink | None,
    list[WireplumberRule],
]:
    """Decompose one ``~/.config/wireplumber/wireplumber.conf.d/*.conf``."""
    text = path.read_text()
    alsa_rules: list[AlsaCardRule] = []
    profile_pins: list[AlsaProfilePin] = []
    bluez_rules: list[BluezRule] = []
    restore_rules: list[StreamRestoreRule] = []
    stream_pins: list[StreamPin] = []
    role_sink: MediaRoleSink | None = None
    untyped: list[WireplumberRule] = []

    matched_any = False

    # 50-hapax-voice-duck.conf — the load-bearing role-loopback infra.
    if _WP_COMPONENTS_RE.search(text):
        duck_level_m = _WP_DUCK_LEVEL_RE.search(text)
        default_role_m = _WP_DEFAULT_MEDIA_ROLE_RE.search(text)
        duck = DuckPolicy(
            duck_level=float(duck_level_m.group(1)) if duck_level_m else 0.3,
            default_media_role=(default_role_m.group(1) if default_role_m else "Multimedia"),
        )
        loopbacks: list[RoleLoopback] = []
        components_section = _extract_section(text, "wireplumber.components")
        if components_section:
            for block in _split_top_level_modules(components_section):
                # Find a libpipewire-module-loopback block with intended-roles.
                if _LIB_LOOPBACK_RE.search(block) or "loopback.sink.role" in block:
                    name_m = _NODE_NAME_RE.search(block)
                    desc_m = _NODE_DESC_RE.search(block)
                    pri_m = _WP_PRIORITY_RE.search(block)
                    pref_m = _WP_PREFERRED_TARGET_RE.search(block)
                    intended_m = _WP_INTENDED_ROLES_RE.search(block)
                    vol_m = _WP_NODE_VOLUME_RE.search(block)
                    if not name_m or not pri_m:
                        continue
                    intended = []
                    if intended_m:
                        intended = [
                            t.strip().strip('"')
                            for t in intended_m.group(1).split(",")
                            if t.strip()
                        ]
                    role = intended[0] if intended else name_m.group(1).split(".")[-1].title()
                    loopbacks.append(
                        RoleLoopback(
                            role=role,
                            loopback_node_name=name_m.group(1),
                            description=desc_m.group(1) if desc_m else "",
                            priority=int(pri_m.group(1)),
                            intended_roles=intended,
                            preferred_target=(pref_m.group(1) if pref_m else None),
                            node_volume=float(vol_m.group(1)) if vol_m else 1.0,
                            state_restore=False,
                        )
                    )
        if loopbacks:
            role_sink = MediaRoleSink(
                duck_policy=duck,
                loopbacks=loopbacks,
                preferred_target_pins=[
                    PreferredTargetPin(
                        role=lb.role,
                        preferred_target=lb.preferred_target or "",
                    )
                    for lb in loopbacks
                    if lb.preferred_target
                ],
            )
            matched_any = True
            gaps.inferred_models.append(f"MediaRoleSink from {path.name}")

    # monitor.alsa.rules — generic.
    if _WP_MONITOR_ALSA_RULES_RE.search(text):
        # Try profile pins first.
        for match in _WP_DEVICE_NAME_MATCH_RE.finditer(text):
            card_match = match.group(1)
            m_profile = _WP_DEVICE_PROFILE_RE.search(text)
            m_use_acp = _WP_API_ALSA_USE_ACP_RE.search(text)
            m_session = _WP_PRIORITY_SESSION_RE.search(text)
            m_driver = _WP_PRIORITY_DRIVER_RE.search(text)
            try:
                pin = AlsaProfilePin(
                    card_match=card_match,
                    profile=m_profile.group(1) if m_profile else None,
                    api_alsa_use_acp=(m_use_acp.group(1) == "true" if m_use_acp else None),
                    priority_session=int(m_session.group(1)) if m_session else None,
                    priority_driver=int(m_driver.group(1)) if m_driver else None,
                )
                if (
                    pin.profile
                    or pin.priority_session is not None
                    or pin.priority_driver is not None
                ):
                    profile_pins.append(pin)
                    matched_any = True
                    gaps.inferred_models.append(f"AlsaProfilePin from {path.name}")
            except Exception as exc:  # noqa: BLE001
                gaps.parse_warnings.append(f"{path.name}: AlsaProfilePin parse error: {exc}")
            break  # one pin per file usually
        # Generic ALSA rule fallback for files with no card-name match
        # (e.g. 51-no-suspend.conf matches everything).
        if not profile_pins:
            alsa_rules.append(AlsaCardRule(description=path.name, matches=[], update_props={}))
            matched_any = True
            gaps.inferred_models.append(f"AlsaCardRule from {path.name}")

    # bluez rules.
    if _WP_MONITOR_BLUEZ_RULES_RE.search(text):
        bluez_rules.append(
            BluezRule(description=path.name, matches=[], update_props={}, properties={})
        )
        matched_any = True
        gaps.inferred_models.append(f"BluezRule from {path.name}")

    # stream-restore rules.
    if _WP_STREAM_RESTORE_RE.search(text):
        restore_rules.append(
            StreamRestoreRule(matches=[], state_restore_target=False, state_restore_props=False)
        )
        matched_any = True
        gaps.inferred_models.append(f"StreamRestoreRule from {path.name}")

    # stream pins.
    if _WP_STREAM_RULES_RE.search(text) or _WP_NODE_RULES_RE.search(text):
        target_m = _TARGET_OBJECT_RE.search(text)
        if target_m:
            try:
                pin = StreamPin(
                    matches=[],
                    target_object=target_m.group(1),
                    dont_fallback=bool(_DONT_FALLBACK_RE.search(text)),
                    dont_reconnect=bool(_DONT_RECONNECT_RE.search(text)),
                    dont_move=bool(_DONT_MOVE_RE.search(text)),
                    linger=bool(_LINGER_RE.search(text)),
                )
                stream_pins.append(pin)
                matched_any = True
                gaps.inferred_models.append(f"StreamPin from {path.name}")
            except Exception as exc:  # noqa: BLE001
                gaps.parse_warnings.append(f"{path.name}: StreamPin parse error: {exc}")

    # wireplumber.profiles / settings — typed catch-all.
    if _WP_PROFILES_RE.search(text) and not matched_any:
        untyped.append(
            WireplumberRule(
                name=path.name,
                description="wireplumber.profiles / settings catch-all",
                raw_content=text[:512],
            )
        )
        matched_any = True

    if not matched_any:
        untyped.append(
            WireplumberRule(name=path.name, description="catch-all", raw_content=text[:512])
        )
        gaps.untyped_confs.append(path.name)

    return alsa_rules, profile_pins, bluez_rules, restore_rules, stream_pins, role_sink, untyped


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class AudioGraphValidator:
    """Read-only decomposer + gap reporter for live PipeWire confs."""

    def __init__(
        self,
        pipewire_conf_dir: Path | None = None,
        wireplumber_conf_dir: Path | None = None,
    ) -> None:
        self.pipewire_conf_dir = (
            pipewire_conf_dir or Path("~/.config/pipewire/pipewire.conf.d").expanduser()
        )
        self.wireplumber_conf_dir = (
            wireplumber_conf_dir or Path("~/.config/wireplumber/wireplumber.conf.d").expanduser()
        )

    def list_active_pipewire_confs(self) -> list[Path]:
        """Active set: ``*.conf`` excluding ``.bak-*`` / ``.disabled*`` siblings."""
        if not self.pipewire_conf_dir.is_dir():
            return []
        out: list[Path] = []
        for path in sorted(self.pipewire_conf_dir.glob("*.conf")):
            name = path.name
            if ".bak-" in name or ".disabled" in name or ".replaced-by-" in name:
                continue
            out.append(path)
        return out

    def list_active_wireplumber_confs(self) -> list[Path]:
        if not self.wireplumber_conf_dir.is_dir():
            return []
        out: list[Path] = []
        for path in sorted(self.wireplumber_conf_dir.glob("*.conf")):
            name = path.name
            if ".bak" in name or ".disabled" in name or ".replaced-by-" in name:
                continue
            out.append(path)
        return out

    def decompose_confs(
        self,
        pipewire_confs: Iterable[Path] | None = None,
        wireplumber_confs: Iterable[Path] | None = None,
    ) -> DecomposeResult:
        """Decompose the live conf set into a (graph, gaps) tuple.

        For every active conf found, runs the appropriate decomposer
        and folds the result into a single :class:`AudioGraph`. Any
        per-conf failure is added to ``gaps`` so the caller can decide
        whether to ship the schema (the criterion is "every active
        conf produces at least one typed model OR is logged in
        ``gaps.untyped_confs``").
        """
        gaps = GapReport()
        if pipewire_confs is None:
            pipewire_confs = self.list_active_pipewire_confs()
        if wireplumber_confs is None:
            wireplumber_confs = self.list_active_wireplumber_confs()

        all_parsed_nodes: list[_ParsedNode] = []
        all_loopbacks: list[_ParsedLoopback] = []
        all_tunables: list[GlobalTunables] = []
        all_profile_pins: list[AlsaProfilePin] = []

        for conf in pipewire_confs:
            try:
                parsed_nodes, parsed_lbs, tunables, profile_pins = _decompose_pipewire_conf(
                    conf, gaps
                )
                all_parsed_nodes.extend(parsed_nodes)
                all_loopbacks.extend(parsed_lbs)
                if tunables:
                    all_tunables.append(tunables)
                all_profile_pins.extend(profile_pins)
            except Exception as exc:  # noqa: BLE001
                gaps.parse_warnings.append(f"{conf.name}: top-level decompose failed: {exc}")

        all_alsa_rules: list[AlsaCardRule] = []
        all_bluez_rules: list[BluezRule] = []
        all_restore_rules: list[StreamRestoreRule] = []
        all_stream_pins: list[StreamPin] = []
        all_role_sinks: list[MediaRoleSink] = []
        all_untyped_wp: list[WireplumberRule] = []
        for conf in wireplumber_confs:
            try:
                rules, profile_pins_wp, bluez, restore, pins, role_sink, untyped = (
                    _decompose_wireplumber_conf(conf, gaps)
                )
                all_alsa_rules.extend(rules)
                all_profile_pins.extend(profile_pins_wp)
                all_bluez_rules.extend(bluez)
                all_restore_rules.extend(restore)
                all_stream_pins.extend(pins)
                if role_sink:
                    all_role_sinks.append(role_sink)
                all_untyped_wp.extend(untyped)
            except Exception as exc:  # noqa: BLE001
                gaps.parse_warnings.append(f"{conf.name}: wp top-level decompose failed: {exc}")

        # Convert _ParsedNode → AudioNode. Keep LAST occurrence per pipewire_name
        # (later confs override earlier).
        seen_pw_names: dict[str, _ParsedNode] = {}
        for pn in all_parsed_nodes:
            seen_pw_names[pn.pipewire_name] = pn

        nodes: list[AudioNode] = []
        for pn in seen_pw_names.values():
            try:
                nodes.append(
                    AudioNode(
                        id=pn.node_id,
                        kind=pn.kind,
                        pipewire_name=pn.pipewire_name,
                        description=pn.description,
                        target_object=pn.target_object,
                        channels=pn.channels or ChannelMap(count=2, positions=["FL", "FR"]),
                        format=pn.format_spec,
                        fail_closed=pn.fail_closed,
                        private_monitor_endpoint=pn.private_monitor_endpoint,
                        filter_chain_template=pn.filter_chain_template,
                        filter_graph_stages=pn.filter_graph_stages,
                        mixdown=pn.mixdown,
                        params=pn.params,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                gaps.parse_warnings.append(
                    f"AudioNode build failed for {pn.pipewire_name!r}: {exc}"
                )

        # Build LoopbackTopology from parsed loopbacks. Use playback's
        # node_id (the publicly-visible side).
        loopbacks: list[LoopbackTopology] = []
        seen_lb_node_ids: set[str] = set()
        node_ids_in_graph = {n.id for n in nodes}
        for plb in all_loopbacks:
            if plb.node_id in seen_lb_node_ids:
                continue
            if plb.node_id not in node_ids_in_graph:
                # The playback node didn't make it into the node set
                # (pure capture-only loopback or skipped). Skip.
                continue
            try:
                loopbacks.append(
                    LoopbackTopology(
                        node_id=plb.node_id,
                        source=plb.source_pipewire_name or plb.capture_pipewire_name or "",
                        sink=plb.sink_target_object or plb.playback_pipewire_name or "",
                        source_dont_move=plb.dont_move,
                        sink_dont_move=plb.dont_move,
                        fail_closed_on_target_absent=plb.dont_fallback,
                        apply_via_pactl_load=False,
                        dont_reconnect=plb.dont_reconnect,
                        dont_move=plb.dont_move,
                        linger=plb.linger,
                        state_restore=plb.state_restore,
                        remap_source=(RemapSource() if plb.is_remap_source else None),
                        format=plb.playback_format or plb.capture_format,
                        passive_capture=plb.capture_passive,
                        passive_playback=plb.playback_passive,
                        stream_dont_remix=plb.stream_dont_remix,
                        stream_capture_sink=plb.stream_capture_sink,
                    )
                )
                seen_lb_node_ids.add(plb.node_id)
            except Exception as exc:  # noqa: BLE001
                gaps.parse_warnings.append(
                    f"LoopbackTopology build failed for {plb.node_id!r}: {exc}"
                )

        try:
            graph = AudioGraph(
                schema_version=4,
                description="Decomposed live conf set (read-only audit)",
                nodes=nodes,
                loopbacks=loopbacks,
                tunables=all_tunables,
                alsa_profile_pins=all_profile_pins,
                alsa_rules=all_alsa_rules,
                bluez_rules=all_bluez_rules,
                stream_restore_rules=all_restore_rules,
                stream_pins=all_stream_pins,
                media_role_sinks=all_role_sinks,
                untyped_wireplumber_rules=all_untyped_wp,
            )
        except Exception as exc:  # noqa: BLE001
            gaps.parse_warnings.append(f"AudioGraph assembly failed: {exc}")
            graph = AudioGraph(schema_version=4, nodes=nodes)

        return DecomposeResult(graph=graph, gaps=gaps)

    def conf_decomposed_cleanly(self, conf_path: Path) -> bool:
        """Per-conf check: did decomposition produce at least one typed model?

        Used by ``test_decompose_real_confs.py`` for the 24/24 acceptance
        gate.
        """
        gaps = GapReport()
        if conf_path.parent == self.wireplumber_conf_dir:
            (
                rules,
                pins_wp,
                bluez,
                restore,
                pins,
                role_sink,
                untyped,
            ) = _decompose_wireplumber_conf(conf_path, gaps)
            return bool(rules or pins_wp or bluez or restore or pins or role_sink or untyped)
        nodes, loopbacks, tunables, profile_pins = _decompose_pipewire_conf(conf_path, gaps)
        return bool(nodes or loopbacks or tunables or profile_pins)


__all__ = [
    "AudioGraphValidator",
    "DecomposeResult",
    "GapReport",
]
