"""Phase 6 audio routing policy contract helpers."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from shared import audio_loudness
from shared.audio_topology import Node, TopologyDescriptor

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = REPO_ROOT / "config" / "audio-routing.yaml"
DEFAULT_TOPOLOGY_PATH = REPO_ROOT / "config" / "audio-topology.yaml"
DEFAULT_LINK_MAP_PATH = REPO_ROOT / "config" / "hapax" / "audio-link-map.conf"
DEFAULT_FORBIDDEN_LINKS_PATH = REPO_ROOT / "config" / "hapax" / "audio-forbidden-links.conf"
DEFAULT_WIREPLUMBER_DENY_CONF_PATH = (
    REPO_ROOT / "config" / "wireplumber" / "98-hapax-link-deny.conf"
)
DEFAULT_WIREPLUMBER_DENY_SCRIPT_PATH = (
    REPO_ROOT / "config" / "wireplumber" / "scripts" / "hapax" / "link-deny.lua"
)

type RouteClass = Literal[
    "private",
    "notification",
    "broadcast_voice",
    "broadcast_content",
    "default_multimedia",
    "default_multimedia_fail_closed",
    "instrument",
    "monitor_bridge",
]
type ArtifactStatus = Literal["generated", "hand_mirrored", "non_round_trippable"]
type EligibilityBasis = Literal[
    "explicit_policy",
    "private_refused",
    "blocked_until_smoke",
    "non_round_trippable",
    "disabled_pc_usb56_2026_05_20",
]

PRIVATE_ROUTE_CLASSES: frozenset[RouteClass] = frozenset(
    {"private", "notification", "monitor_bridge"}
)


class AudioRoutingPolicyError(ValueError):
    """Raised when audio route policy violates fail-closed invariants."""


class PolicyModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GeneratedOutput(PolicyModel):
    output_dir: str
    manifest_path: str
    # Audit F#8 (2026-05-02): generator gained LADSPA loudnorm / duck /
    # usb-bias chain templates so generated_conf_writes_allowed = true
    # is now a supported (and live) configuration. live_reload_allowed
    # + dry_run_only stay locked — host-side PipeWire reload is still
    # operator-driven, the generator is no longer.
    generated_conf_writes_allowed: bool
    live_reload_allowed: Literal[False]
    dry_run_only: Literal[True]


class ConstantValue(PolicyModel):
    constant_ref: str
    value: float


class DuckConstantValue(PolicyModel):
    constant_ref: str
    value_db: float


class LoudnessConstants(PolicyModel):
    module: Literal["shared/audio_loudness.py"]
    pre_norm_target_lufs_i: ConstantValue
    pre_norm_true_peak_dbtp: ConstantValue
    egress_target_lufs_i: ConstantValue
    egress_true_peak_dbtp: ConstantValue


class DuckingConstants(PolicyModel):
    module: Literal["shared/audio_loudness.py"]
    operator_voice: DuckConstantValue
    tts: DuckConstantValue


class FailClosedPolicy(PolicyModel):
    unknown_source_broadcast_eligible: Literal[False]
    default_sink_fallback_broadcast_eligible: Literal[False]
    private_route_broadcast_eligible: Literal[False]
    notification_route_broadcast_eligible: Literal[False]
    missing_rights_broadcast_eligible: Literal[False]
    missing_provenance_broadcast_eligible: Literal[False]
    missing_generated_artifact_owner_broadcast_eligible: Literal[False]


class PreNormalizationPolicy(PolicyModel):
    target_lufs_i: float | None
    constant_ref: str | None


class RoutePolicy(PolicyModel):
    source_id: str
    producer: str
    role: str
    pipewire_node: str
    target_chain: tuple[str, ...]
    route_class: RouteClass
    broadcast_eligible: bool
    public_claim_allowed: bool
    broadcast_eligibility_basis: EligibilityBasis
    default_fallback_allowed: Literal[False]
    rights_required: bool
    provenance_required: bool
    provenance_refs: tuple[str, ...] = Field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    pre_normalization: PreNormalizationPolicy
    ducked_by: tuple[Literal["operator_voice", "tts"], ...] = Field(default_factory=tuple)
    generated_artifact_owner: ArtifactStatus
    artifact_refs: tuple[str, ...]


class ArtifactMapping(PolicyModel):
    path: str
    status: ArtifactStatus
    owner: str
    reason: str


class FollowOn(PolicyModel):
    id: str
    reason: str


class AudioRoutingPolicy(PolicyModel):
    schema_version: Literal[1]
    policy_id: str
    description: str
    generated_output: GeneratedOutput
    loudness_constants: LoudnessConstants
    ducking_constants: DuckingConstants
    fail_closed_policy: FailClosedPolicy
    routes: tuple[RoutePolicy, ...]
    artifacts: tuple[ArtifactMapping, ...]
    follow_ons: tuple[FollowOn, ...]

    def broadcast_eligible_source_ids(self) -> tuple[str, ...]:
        return tuple(route.source_id for route in self.routes if route.broadcast_eligible)

    def artifact_paths(self) -> set[str]:
        return {artifact.path for artifact in self.artifacts}


def load_audio_routing_policy(path: Path | None = None) -> AudioRoutingPolicy:
    source = path or DEFAULT_POLICY_PATH
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    policy = AudioRoutingPolicy.model_validate(payload)
    assert_audio_routing_policy(policy)
    return policy


def assert_audio_routing_policy(policy: AudioRoutingPolicy) -> None:
    errors = list(audio_routing_policy_errors(policy))
    if errors:
        raise AudioRoutingPolicyError("; ".join(errors))


def audio_routing_policy_errors(policy: AudioRoutingPolicy) -> tuple[str, ...]:
    errors: list[str] = []
    seen_sources: set[str] = set()
    artifact_paths = policy.artifact_paths()

    for route in policy.routes:
        if route.source_id in seen_sources:
            errors.append(f"duplicate source_id: {route.source_id}")
        seen_sources.add(route.source_id)

        if route.default_fallback_allowed:
            errors.append(f"{route.source_id}: default fallback is not allowed")

        if route.route_class in PRIVATE_ROUTE_CLASSES and route.broadcast_eligible:
            errors.append(f"{route.source_id}: private route cannot be broadcast eligible")

        if route.broadcast_eligible:
            if route.broadcast_eligibility_basis != "explicit_policy":
                errors.append(f"{route.source_id}: broadcast eligibility must be explicit")
            if not route.rights_required:
                errors.append(f"{route.source_id}: broadcast eligibility requires rights gate")
            if not route.provenance_required:
                errors.append(f"{route.source_id}: broadcast eligibility requires provenance")
            if not route.provenance_refs:
                errors.append(f"{route.source_id}: broadcast eligibility needs provenance refs")
            if not route.evidence_refs:
                errors.append(f"{route.source_id}: broadcast eligibility needs evidence refs")

        missing_artifacts = set(route.artifact_refs) - artifact_paths
        if missing_artifacts:
            errors.append(
                f"{route.source_id}: artifact refs lack ownership rows: {sorted(missing_artifacts)}"
            )

        if route.pre_normalization.constant_ref is not None:
            expected = _constant_value(route.pre_normalization.constant_ref)
            if route.pre_normalization.target_lufs_i != expected:
                errors.append(
                    f"{route.source_id}: pre-normalization target does not match "
                    f"{route.pre_normalization.constant_ref}"
                )

    for name, constant in {
        "pre_norm_target_lufs_i": policy.loudness_constants.pre_norm_target_lufs_i,
        "pre_norm_true_peak_dbtp": policy.loudness_constants.pre_norm_true_peak_dbtp,
        "egress_target_lufs_i": policy.loudness_constants.egress_target_lufs_i,
        "egress_true_peak_dbtp": policy.loudness_constants.egress_true_peak_dbtp,
    }.items():
        if constant.value != _constant_value(constant.constant_ref):
            errors.append(f"{name}: value does not match {constant.constant_ref}")

    for name, constant in {
        "operator_voice": policy.ducking_constants.operator_voice,
        "tts": policy.ducking_constants.tts,
    }.items():
        if constant.value_db != _constant_value(constant.constant_ref):
            errors.append(f"{name}: value_db does not match {constant.constant_ref}")

    return tuple(errors)


def audio_routing_manifest(policy: AudioRoutingPolicy) -> dict[str, object]:
    artifact_status_counts = Counter(artifact.status for artifact in policy.artifacts)
    blocked_source_ids = sorted(
        route.source_id for route in policy.routes if not route.broadcast_eligible
    )
    private_source_ids = sorted(
        route.source_id for route in policy.routes if route.route_class in PRIVATE_ROUTE_CLASSES
    )

    return {
        "schema_version": 1,
        "policy_id": policy.policy_id,
        "generated_from": "config/audio-routing.yaml",
        "dry_run_only": policy.generated_output.dry_run_only,
        "generated_conf_writes_allowed": policy.generated_output.generated_conf_writes_allowed,
        "live_reload_allowed": policy.generated_output.live_reload_allowed,
        "broadcast_eligible_source_ids": sorted(policy.broadcast_eligible_source_ids()),
        "blocked_source_ids": blocked_source_ids,
        "private_source_ids": private_source_ids,
        "unknown_source_broadcast_eligible": False,
        "default_sink_fallback_broadcast_eligible": False,
        "artifact_status_counts": dict(sorted(artifact_status_counts.items())),
        "artifact_paths": sorted(policy.artifact_paths()),
    }


def audio_routing_manifest_json(policy: AudioRoutingPolicy) -> str:
    return json.dumps(audio_routing_manifest(policy), indent=2, sort_keys=True) + "\n"


def load_audio_topology_descriptor(path: Path | None = None) -> TopologyDescriptor:
    return TopologyDescriptor.from_yaml(path or DEFAULT_TOPOLOGY_PATH)


def generated_route_map_texts(
    topology: TopologyDescriptor,
    policy: AudioRoutingPolicy,
) -> tuple[str, str]:
    """Generate reconciler desired and forbidden link-map artifacts.

    The output is intentionally conservative and exact-port. It compiles the
    current v3 topology descriptor plus route policy into the reconciler's line
    format so PC AUX4/AUX5 fail-closed and private/non-livestream isolation are
    generated, not hand-mirrored prose.
    """
    _assert_pc_route_fail_closed(policy)
    desired = _desired_links(topology, policy)
    forbidden = _forbidden_links(topology)
    _assert_no_route_map_contradictions(desired, forbidden)
    return _link_map_text(desired), _forbidden_link_map_text(forbidden)


def generated_desired_route_map_text(
    topology: TopologyDescriptor,
    policy: AudioRoutingPolicy,
) -> str:
    return generated_route_map_texts(topology, policy)[0]


def generated_forbidden_route_map_text(
    topology: TopologyDescriptor,
    policy: AudioRoutingPolicy,
) -> str:
    return generated_route_map_texts(topology, policy)[1]


def _boundary_node_pairs(forbidden: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    """Extract unique source_node|target_node boundary pairs from forbidden links."""
    pairs: dict[str, None] = {}
    for source_port, target_port in forbidden:
        source_node = source_port.split(":")[0]
        target_node = target_port.split(":")[0]
        pairs[f"{source_node}|{target_node}"] = None
    return tuple(pairs)


def generated_wireplumber_deny_policy_texts(
    topology: TopologyDescriptor | None = None,
) -> tuple[str, str]:
    """Generate WirePlumber source artifacts for fail-closed link denial.

    Embeds the generated forbidden port-link and node-pair policy directly in
    the Lua. WirePlumber 0.5's Lua sandbox does not expose file I/O globals, so
    external runtime policy reads fail open unless the generated artifact is
    self-contained.
    """
    if topology is None:
        topology = load_audio_topology_descriptor()
    forbidden = _forbidden_links(topology)
    node_pairs = _boundary_node_pairs(forbidden)
    return (_wireplumber_deny_conf_text(), _wireplumber_deny_script_text(forbidden, node_pairs))


def _node(topology: TopologyDescriptor, node_id: str) -> Node:
    return topology.node_by_id(node_id)


def _playback_name(node: Node) -> str:
    playback_node = node.params.get("playback_node")
    if isinstance(playback_node, str) and playback_node:
        return playback_node
    if node.pipewire_name.endswith("-capture"):
        return node.pipewire_name.removesuffix("-capture") + "-playback"
    if node.pipewire_name.endswith("-playback"):
        return node.pipewire_name
    return f"{node.pipewire_name}-playback"


def _role_output_name(node: Node) -> str:
    return node.pipewire_name.replace("input.", "output.", 1)


def _words(value: str | int | float | bool | None) -> tuple[str, ...]:
    return tuple(value.split()) if isinstance(value, str) else ()


def _policy_route(policy: AudioRoutingPolicy, source_id: str) -> RoutePolicy:
    route = next((route for route in policy.routes if route.source_id == source_id), None)
    if route is None:
        raise AudioRoutingPolicyError(f"{source_id} route missing from audio-routing policy")
    return route


def _broadcast_route_enabled(policy: AudioRoutingPolicy, source_id: str) -> bool:
    route = _policy_route(policy, source_id)
    return route.broadcast_eligible and route.broadcast_eligibility_basis == "explicit_policy"


def _private_tts_route_enabled(policy: AudioRoutingPolicy) -> bool:
    route = _policy_route(policy, "assistant-private")
    return (
        route.route_class == "private"
        and route.broadcast_eligible is False
        and route.broadcast_eligibility_basis == "private_refused"
    )


def _pair_links(
    source: str,
    target: str,
    *,
    source_ports: tuple[str, str] = ("output_FL", "output_FR"),
    target_ports: tuple[str, str] = ("playback_FL", "playback_FR"),
) -> list[tuple[str, str]]:
    return [
        (f"{source}:{source_ports[0]}", f"{target}:{target_ports[0]}"),
        (f"{source}:{source_ports[1]}", f"{target}:{target_ports[1]}"),
    ]


def _loudnorm_to_mpc_links(node: Node, mpc: Node) -> list[tuple[str, str]]:
    pair = _words(node.params.get("mpc_usb_input_pair") or node.params.get("playback_positions"))
    if pair == ("disabled",):
        return []
    if len(pair) != 2:
        raise AudioRoutingPolicyError(f"{node.id}: expected two MPC playback positions, got {pair}")
    source_positions = node.channels.positions or ["FL", "FR"]
    source_ports = tuple(f"output_{position}" for position in source_positions[:2])
    return _pair_links(
        _playback_name(node),
        mpc.pipewire_name,
        source_ports=(source_ports[0], source_ports[1]),
        target_ports=(f"playback_{pair[0]}", f"playback_{pair[1]}"),
    )


def _desired_links(
    topology: TopologyDescriptor,
    policy: AudioRoutingPolicy,
) -> tuple[tuple[str, str], ...]:
    # Interim MPC-only baseline (2026-05-29, L-12 removed): the broadcast
    # return runs entirely over the MPC's own 24-ch USB return. The orphaned
    # L-12 evilpet / wet-return legs are intentionally NOT emitted into the
    # desired map — the reconciler must never enforce links to absent L-12
    # hardware. Restore them only if the L-12 returns before the MOTU/FadeFox
    # migration lands.
    mpc_return = _node(topology, "mpc-usb-return")
    mpc_wet = _node(topology, "mpc-usb-return-capture")
    livestream = _node(topology, "livestream-tap")
    master = _node(topology, "broadcast-master-capture")
    voice_fx = _node(topology, "voice-fx")
    tts = _node(topology, "tts-loudnorm")
    music = _node(topology, "music-loudnorm")
    youtube = _node(topology, "yt-loudnorm")
    mpc = _node(topology, "mpc-usb-output")
    private_sink = _node(topology, "private-sink")
    private_capture = _node(topology, "private-monitor-capture")
    private_output = _node(topology, "private-monitor-output")
    notification_sink = _node(topology, "notification-private-sink")
    role_assistant = _node(topology, "role-assistant")
    role_notification = _node(topology, "role-notification")
    role_broadcast = _node(topology, "role-broadcast")

    links: list[tuple[str, str]] = []

    # MPC USB return: the public mix (music + voice + YouTube, pre-summed inside
    # the MPC) lands on pro-input-0 capture_AUX0/1, is captured by
    # mpc-usb-return-capture, and summed into livestream-tap. The private monitor
    # pair capture_AUX2/3 is NOT captured here (fenced in _forbidden_links).
    for position in _words(mpc_wet.params.get("capture_positions")):
        links.append(
            (
                f"{mpc_return.pipewire_name}:capture_{position}",
                f"{mpc_wet.pipewire_name}:input_{position}",
            )
        )
    links.extend(_pair_links(_playback_name(mpc_wet), livestream.pipewire_name))
    links.extend(
        _pair_links(
            livestream.pipewire_name,
            master.pipewire_name,
            source_ports=("monitor_FL", "monitor_FR"),
            target_ports=("input_FL", "input_FR"),
        )
    )

    if _broadcast_route_enabled(policy, "broadcast-tts"):
        links.extend(
            _pair_links(
                _playback_name(voice_fx),
                tts.pipewire_name,
                target_ports=("playback_FL", "playback_FR"),
            )
        )
        links.extend(_loudnorm_to_mpc_links(tts, mpc))

    if _broadcast_route_enabled(policy, "music-bed"):
        links.extend(_loudnorm_to_mpc_links(music, mpc))

    # YouTube send to MPC AUX6/7. Emitted whenever the topology enables the send
    # (yt-loudnorm playback_positions != disabled). Broadcast eligibility of the
    # youtube-bed route is a separate policy gate (blocked_until_smoke); the MPC
    # mixer — operator-owned — decides whether YouTube reaches the public return.
    links.extend(_loudnorm_to_mpc_links(youtube, mpc))

    if _private_tts_route_enabled(policy):
        links.extend(
            _pair_links(
                private_sink.pipewire_name,
                private_capture.pipewire_name,
                source_ports=("monitor_FL", "monitor_FR"),
                target_ports=("input_FL", "input_FR"),
            )
        )
        links.extend(_loudnorm_to_mpc_links(private_output, mpc))
        links.extend(_pair_links(_role_output_name(role_assistant), private_sink.pipewire_name))

    # Notifications are deliberately dead-ended at their null sink until
    # notification-private monitoring has its own route authority. They must
    # not share the private TTS MPC ingress by default.
    links.extend(_pair_links(_role_output_name(role_notification), notification_sink.pipewire_name))
    links.extend(_pair_links(_role_output_name(role_broadcast), voice_fx.pipewire_name))
    return tuple(links)


def _forbidden_links(topology: TopologyDescriptor) -> tuple[tuple[str, str], ...]:
    l12_return = _node(topology, "l12-usb-return")
    mpc = _node(topology, "mpc-usb-output")
    livestream = _node(topology, "livestream-tap")
    legacy_livestream = _node(topology, "livestream-legacy")
    master = _node(topology, "broadcast-master-capture")
    pc = _node(topology, "pc-loudnorm")
    tts = _node(topology, "tts-loudnorm")
    private_output = _node(topology, "private-monitor-output")
    notification_output = _node(topology, "notification-private-monitor-output")
    m8 = _node(topology, "m8-loudnorm")
    s4 = _node(topology, "s4-loopback")
    role_assistant = _node(topology, "role-assistant")
    role_notification = _node(topology, "role-notification")
    role_multimedia = _node(topology, "role-multimedia")

    links: list[tuple[str, str]] = []
    l12_ports = ("playback_FL", "playback_FR", "playback_RL", "playback_RR")
    for source in (
        private_output.pipewire_name,
        notification_output.pipewire_name,
        _playback_name(pc),
        _playback_name(tts),
    ):
        for source_port in ("output_FL", "output_FR"):
            for target_port in l12_ports:
                links.append(
                    (f"{source}:{source_port}", f"{l12_return.pipewire_name}:{target_port}")
                )

    mpc_forbidden_targets = (mpc.pipewire_name, *_words(mpc.params.get("legacy_pipewire_names")))
    for mpc_target in mpc_forbidden_targets:
        links.extend(
            _pair_links(
                _playback_name(pc),
                mpc_target,
                target_ports=("playback_AUX4", "playback_AUX5"),
            )
        )
        # NOTE: YouTube AUX6/7 is no longer forbidden — the interim MPC-only
        # baseline (2026-05-29) enables the YouTube send to MPC AUX6/7 (see
        # _desired_links + yt-loudnorm). Broadcast eligibility stays gated in
        # policy (blocked_until_smoke), not by a link-time deny.
        links.extend(
            _pair_links(
                _playback_name(notification_output),
                mpc_target,
                target_ports=("playback_AUX8", "playback_AUX9"),
            )
        )
        m8_positions = m8.channels.positions or ["FL", "FR"]
        links.extend(
            _pair_links(
                _playback_name(m8),
                mpc_target,
                source_ports=(f"output_{m8_positions[0]}", f"output_{m8_positions[1]}"),
                target_ports=("playback_AUX10", "playback_AUX11"),
            )
        )
    m8_positions = m8.channels.positions or ["FL", "FR"]
    links.extend(
        _pair_links(
            _playback_name(m8),
            l12_return.pipewire_name,
            source_ports=(f"output_{m8_positions[0]}", f"output_{m8_positions[1]}"),
            target_ports=("playback_FL", "playback_FR"),
        )
    )
    links.extend(_pair_links("hapax-tts-broadcast-playback", livestream.pipewire_name))
    links.extend(_pair_links(_playback_name(s4), livestream.pipewire_name))
    links.extend(
        _pair_links(
            legacy_livestream.pipewire_name,
            master.pipewire_name,
            source_ports=("monitor_FL", "monitor_FR"),
            target_ports=("input_FL", "input_FR"),
        )
    )
    for role in (role_assistant, role_notification):
        for role_source in (
            _role_output_name(role),
            f"{role.pipewire_name}-output",
        ):
            links.extend(_pair_links(role_source, role_multimedia.pipewire_name))

    # Private monitor fence (interim MPC-only, 2026-05-29). The MPC returns the
    # private monitor mix on pro-input-0 capture_AUX2/3; it must NEVER reach any
    # broadcast node. Defense-in-depth — the MPC public mix (capture_AUX0/1) must
    # already exclude private (operator-owned MPC mixer); this cross-product
    # makes any stray capture_AUX2/3 -> broadcast link a hard WirePlumber deny
    # (both as an exact port link and as a source|target node-boundary pair).
    mpc_return = _node(topology, "mpc-usb-return")
    broadcast_normalized = _node(topology, "broadcast-normalized-capture")
    obs_remap = _node(topology, "obs-broadcast-remap-capture")
    private_fence_sinks: tuple[tuple[str, tuple[str, str]], ...] = (
        (livestream.pipewire_name, ("playback_FL", "playback_FR")),
        (master.pipewire_name, ("input_FL", "input_FR")),
        (broadcast_normalized.pipewire_name, ("input_FL", "input_FR")),
        (obs_remap.pipewire_name, ("input_FL", "input_FR")),
    )
    for capture_position in _words(mpc_return.params.get("private_return_positions")):
        source_port = f"{mpc_return.pipewire_name}:capture_{capture_position}"
        for sink_name, sink_ports in private_fence_sinks:
            for sink_port in sink_ports:
                links.append((source_port, f"{sink_name}:{sink_port}"))

    return tuple(dict.fromkeys(links))


def _assert_pc_route_fail_closed(policy: AudioRoutingPolicy) -> None:
    route = next(
        (route for route in policy.routes if route.source_id == "multimedia-default"), None
    )
    if route is None:
        raise AudioRoutingPolicyError("multimedia-default route missing from audio-routing policy")
    if route.route_class != "default_multimedia_fail_closed":
        raise AudioRoutingPolicyError("multimedia-default must be default_multimedia_fail_closed")
    if route.broadcast_eligible or route.default_fallback_allowed:
        raise AudioRoutingPolicyError("multimedia-default must be fail-closed and non-broadcast")
    if route.broadcast_eligibility_basis != "disabled_pc_usb56_2026_05_20":
        raise AudioRoutingPolicyError("multimedia-default must cite disabled_pc_usb56_2026_05_20")


def _assert_no_route_map_contradictions(
    desired: tuple[tuple[str, str], ...],
    forbidden: tuple[tuple[str, str], ...],
) -> None:
    overlap = sorted(set(desired) & set(forbidden))
    if overlap:
        rendered = ", ".join(f"{source}|{target}" for source, target in overlap)
        raise AudioRoutingPolicyError(f"desired/forbidden route contradiction: {rendered}")


def _render_links(links: tuple[tuple[str, str], ...]) -> str:
    return "\n".join(f"{source}|{target}" for source, target in links)


def _link_map_text(links: tuple[tuple[str, str], ...]) -> str:
    return (
        "# GENERATED: hapax-audio-reconciler desired-state link map\n"
        "# Source: config/audio-topology.yaml + config/audio-routing.yaml\n"
        "# Format: source_port|target_port\n"
        "# Do not hand-edit; run scripts/generate-pipewire-audio-confs.py --write-route-maps.\n"
        "# MPC AUX4/AUX5 is fail-closed/reserved; no desired links may target it.\n"
        "\n" + _render_links(links) + "\n"
    )


def _forbidden_link_map_text(links: tuple[tuple[str, str], ...]) -> str:
    return (
        "# GENERATED: hapax-audio-reconciler forbidden links\n"
        "# Source: config/audio-topology.yaml + config/audio-routing.yaml\n"
        "# Format: source_port|target_port\n"
        "# Do not hand-edit; run scripts/generate-pipewire-audio-confs.py --write-route-maps.\n"
        "# Private/default/non-livestream lanes must never enter livestream-bound lanes.\n"
        "\n" + _render_links(links) + "\n"
    )


def _wireplumber_deny_conf_text() -> str:
    return """# GENERATED: Hapax WirePlumber link-time deny hook.
# Source: shared.audio_routing_policy.generated_wireplumber_deny_policy_texts
# Policy data: embedded in hapax/link-deny.lua from generated forbidden links
# Do not hand-edit; run scripts/generate-pipewire-audio-confs.py --write-wireplumber-deny-policy.
#
# Install this conf under ~/.config/wireplumber/wireplumber.conf.d and the Lua
# script under ~/.local/share/wireplumber/scripts/hapax with
# scripts/hapax-wireplumber-link-deny-policy --install.

wireplumber.profiles = {
  main = {
    hapax.audio.link-deny = required
  }
}

wireplumber.components = [
  {
    name = hapax/link-deny.lua, type = script/lua
    provides = hapax.audio.link-deny
    requires = [ hooks.linking.target.prepare-link ]
  }
]
"""


def _wireplumber_deny_script_text(
    forbidden_links: tuple[tuple[str, str], ...],
    boundary_node_pairs: tuple[str, ...],
) -> str:
    link_entries = "\n".join(
        f"  [{json.dumps(f'{source}|{target}')}] = true," for source, target in forbidden_links
    )
    pair_entries = "\n".join(f"  [{json.dumps(pair)}] = true," for pair in boundary_node_pairs)
    return f"""-- GENERATED: Hapax WirePlumber link-time deny hook.
-- Source: shared.audio_routing_policy.generated_wireplumber_deny_policy_texts
-- Policy data: embedded from generated forbidden route policy.
-- Do not hand-edit; run scripts/generate-pipewire-audio-confs.py --write-wireplumber-deny-policy.
--
-- Four-layer fail-closed behavior:
--   1. Reject forbidden node-pair auto-targets before WirePlumber link-target.
--   2. Remove exact forbidden port links if a client creates one directly.
--   3. Deny optional-device fallback into Polyend capture unless source is Polyend.
--   4. Carry the generated forbidden policy inside the Lua artifact so
--      WirePlumber's sandbox cannot lose the policy through missing file I/O.

lutils = require ("linking-utils")
log = Log.open_topic ("s-linking.hapax-deny")

local FAIL_CLOSED_FORBIDDEN_LINKS = {{
{link_entries}
}}

local FAIL_CLOSED_BOUNDARY_PAIRS = {{
{pair_entries}
}}

local function load_forbidden_policy ()
  return {{
    links = FAIL_CLOSED_FORBIDDEN_LINKS,
    node_pairs = FAIL_CLOSED_BOUNDARY_PAIRS,
    degraded = false,
  }}
end

local function lookup_bound (source, manager_name, bound_id)
  if source == nil or bound_id == nil then
    return nil
  end
  local om = source:call ("get-object-manager", manager_name)
  if om == nil then
    return nil
  end
  return om:lookup {{
    Constraint {{ "bound-id", "=", tonumber (bound_id), type = "gobject" }},
  }}
end

local function node_name (source, node_id)
  local node = lookup_bound (source, "node", node_id)
  if node == nil then
    return nil
  end
  return node.properties ["node.name"]
end

local function port_name (source, port_id)
  local port = lookup_bound (source, "port", port_id)
  if port == nil then
    return nil
  end
  return port.properties ["port.name"]
end

local function is_polyend_source (source_node)
  return source_node ~= nil and string.match (source_node, "^alsa_input%.usb%-Polyend_") ~= nil
end

local function optional_device_fallback_denied (source_node, target_node)
  return target_node == "hapax-polyend-instrument-capture" and not is_polyend_source (source_node)
end

local function anonymous_loopback_to_multimedia_denied (source_node, target_node)
  return source_node ~= nil
      and target_node == "input.loopback.sink.role.multimedia"
      and string.match (source_node, "^output%.loopback%-%d+%-%d+$") ~= nil
end

local function link_key (source, link)
  local props = link.properties
  local source_node = node_name (source, props ["link.output.node"])
  local target_node = node_name (source, props ["link.input.node"])
  local source_port = port_name (source, props ["link.output.port"])
  local target_port = port_name (source, props ["link.input.port"])
  if source_node == nil or target_node == nil or source_port == nil or target_port == nil then
    return nil, source_node, target_node
  end
  return source_node .. ":" .. source_port .. "|" .. target_node .. ":" .. target_port,
      source_node, target_node
end

SimpleEventHook {{
  name = "linking/hapax-deny-forbidden-target",
  after = "linking/prepare-link",
  before = "linking/link-target",
  interests = {{
    EventInterest {{
      Constraint {{ "event.type", "=", "select-target" }},
    }},
  }},
  execute = function (event)
    local _, _, si, si_props, _, target = lutils:unwrap_select_target_event (event)
    if target == nil then
      return
    end

    local target_props = target.properties
    local source_node = nil
    local target_node = nil
    if si_props ["item.node.direction"] == "output" then
      source_node = si_props ["node.name"]
      target_node = target_props ["node.name"]
    else
      source_node = target_props ["node.name"]
      target_node = si_props ["node.name"]
    end

    if source_node == nil or target_node == nil then
      return
    end

    local pair_key = source_node .. "|" .. target_node
    local policy = load_forbidden_policy ()
    local dynamic_denied = anonymous_loopback_to_multimedia_denied (source_node, target_node)
    if not policy.node_pairs [pair_key]
        and not optional_device_fallback_denied (source_node, target_node)
        and not dynamic_denied then
      return
    end

    local node = si:get_associated_proxy ("node")
    local message = "hapax forbidden audio route: " .. source_node .. " -> " .. target_node
    if dynamic_denied then
      message = message .. " [dynamic anonymous-loopback boundary]"
    end
    if policy.degraded then
      message = message .. " [DEGRADED: runtime policy missing, boundary deny active]"
    end
    log:warning (si, message)
    event:set_data ("target", nil)
    lutils.sendClientError (event, node, -13, message)
    event:stop_processing ()
  end
}}:register ()

SimpleEventHook {{
  name = "linking/hapax-remove-forbidden-port-link",
  interests = {{
    EventInterest {{
      Constraint {{ "event.type", "=", "link-added" }},
    }},
  }},
  execute = function (event)
    local source = event:get_source ()
    local link = event:get_subject ()
    local key, source_node, target_node = link_key (source, link)
    local pair_key = nil
    if source_node ~= nil and target_node ~= nil then
      pair_key = source_node .. "|" .. target_node
    end
    local optional_denied = optional_device_fallback_denied (source_node, target_node)
    local dynamic_denied = anonymous_loopback_to_multimedia_denied (source_node, target_node)
    if key == nil and pair_key == nil and not optional_denied and not dynamic_denied then
      return
    end

    local policy = load_forbidden_policy ()
    local link_denied = key ~= nil and policy.links [key]
    local pair_denied = pair_key ~= nil and policy.node_pairs [pair_key]
    if not link_denied and not pair_denied and not optional_denied and not dynamic_denied then
      return
    end

    local message = "removing hapax forbidden audio link " .. tostring (key)
    if pair_denied and not link_denied then
      message = message .. " (node boundary " .. tostring (pair_key) .. ")"
    end
    if dynamic_denied then
      message = message .. " (dynamic anonymous-loopback boundary)"
    end
    if policy.degraded then
      message = message .. " [DEGRADED: runtime policy missing, boundary deny active]"
    end
    log:warning (link, message)
    link:remove ()
  end
}}:register ()
"""


def _constant_value(name: str) -> float:
    value = getattr(audio_loudness, name)
    if not isinstance(value, int | float):
        raise AudioRoutingPolicyError(f"{name}: loudness constant is not numeric")
    return float(value)
