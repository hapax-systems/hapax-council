"""Audio Graph SSOT — compiler.

``compile_descriptor(graph: AudioGraph) -> CompiledArtefacts`` is the
single authorised producer of derived artefacts (PipeWire confs,
``pactl load-module`` invocations, post-apply probes, rollback plans).

Per spec §3, the compiler emits a five-tuple wrapped in
``CompiledArtefacts``:

* ``confs_to_write`` — ``filename → conf body`` (PipeWire conf fragments).
* ``pactl_loadmodule_invocations`` — one per ``LoopbackTopology`` with
  ``apply_via_pactl_load=True``. Mirrors the
  ``~/.local/bin/hapax-obs-monitor-load`` pattern.
* ``preflight_checks`` — invariant violations from the 9 pre-apply
  checkers in ``invariants.INVARIANT_REGISTRY``. Empty list ⇒ apply may
  proceed; non-empty ⇒ refuse.
* ``postapply_probes`` — one ``PostApplyProbe`` per egress / boundary
  surface. Drives the §4.2 circuit breaker in P5.
* ``rollback_plan`` — content-addressed snapshot strategy + the recovery
  steps the daemon executes if any post-apply probe fails.

Determinism contract (spec §3.1): the same ``AudioGraph`` input must
produce a byte-identical ``CompiledArtefacts.model_dump_json(...)``. The
compiler is a pure function — no global state, no env-var reads, no
filesystem, no wall-clock reads. Rollback plan IDs are content-derived
(SHA-256 of the descriptor) rather than time-stamped so two compiles
of the same input produce identical artefacts.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.audio_graph.invariants import (
    InvariantKind,
    InvariantSeverity,
    InvariantViolation,
    check_all_invariants,
)
from shared.audio_graph.schema import (
    AudioGraph,
    AudioNode,
    LoopbackTopology,
    NodeKind,
)

# ---------------------------------------------------------------------------
# Output models (§3 — five-tuple of artefacts)
# ---------------------------------------------------------------------------


class PactlLoad(BaseModel):
    """Idempotent ``pactl load-module module-loopback ...`` invocation.

    Matches the pattern in ``~/.local/bin/hapax-obs-monitor-load``:

    1. ``wait_for_sink(target_sink, timeout_s=60)``
    2. ``find_existing_module_id(source, sink)`` — if present, no-op.
    3. ``pactl load-module module-loopback source=... sink=... ``
       ``source_dont_move=true sink_dont_move=true latency_msec=20``
    4. Verify the new module's bound source/sink match the request.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    sink: str
    source_dont_move: bool = True
    sink_dont_move: bool = True
    latency_msec: int = 20
    expected_source_port_pattern: str | None = None
    expected_sink_port_pattern: str | None = None


class PostApplyProbe(BaseModel):
    """A signal-flow probe that runs after apply.

    Re-uses the existing ``agents.broadcast_audio_health_producer``
    inject+capture primitive (17.5 kHz tone + FFT detection); P1 carries
    the probe descriptor as data, P5 turns each into a runtime probe.

    For egress probes, the daemon also measures continuous RMS + crest
    after apply and refuses commit if outside band. The egress band is
    a tuple ``(rms_lo, rms_hi)`` in dBFS; ``max_crest`` is the crest
    threshold above which the apply is treated as failed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    sink_to_inject: str
    source_to_capture: str
    inject_channels: int = Field(..., ge=1, le=64)
    expected_outcome: Literal["detected", "not_detected"]
    egress_rms_band_dbfs: tuple[float, float] | None = None
    egress_max_crest: float | None = None


class RollbackPlan(BaseModel):
    """Content-addressed snapshot strategy + recovery steps.

    Per spec §4.4, the daemon:

    1. Snapshots ``~/.config/{pipewire,wireplumber}/.../*.conf``,
       ``pw-dump`` and ``pactl list modules`` to an incident dir.
    2. On post-apply probe failure, restores the snapshot atomically
       (tmpfile + rename), tears down daemon-loaded ``module-loopback``
       instances, restarts pipewire / wireplumber / pipewire-pulse,
       waits 10 s settling, re-runs probes against the rolled-back
       state.

    P1 carries the plan as data — content-addressed by ``snapshot_id``
    (sha256 of the descriptor JSON) so two compiles of the same input
    produce byte-identical plans. P4 turns this into a runtime
    ``attempt_rollback()`` call.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str  # sha256(graph.model_dump_json())
    snapshot_paths: tuple[str, ...]
    pactl_modules_to_unload: tuple[str, ...]
    services_to_restart: tuple[str, ...] = (
        "pipewire.service",
        "wireplumber.service",
        "pipewire-pulse.service",
    )
    settling_seconds: float = 10.0


class CompiledArtefacts(BaseModel):
    """Five-tuple of artefacts emitted by ``compile_descriptor``.

    Pydantic-frozen so subsequent code cannot accidentally mutate the
    artefacts during apply (transactional safety, spec §4.4). Every
    field is order-stable: ``confs_to_write`` keys are sorted, the
    ``pactl_loadmodule_invocations`` and ``postapply_probes`` lists are
    sorted by canonical key, and ``rollback_plan`` is content-addressed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    confs_to_write: dict[str, str] = Field(default_factory=dict)
    pactl_loadmodule_invocations: tuple[PactlLoad, ...] = Field(default_factory=tuple)
    preflight_checks: tuple[InvariantViolation, ...] = Field(default_factory=tuple)
    postapply_probes: tuple[PostApplyProbe, ...] = Field(default_factory=tuple)
    rollback_plan: RollbackPlan


# ---------------------------------------------------------------------------
# Compiler entry-point
# ---------------------------------------------------------------------------


def compile_descriptor(graph: AudioGraph) -> CompiledArtefacts:
    """Pure function. Compile an ``AudioGraph`` into ``CompiledArtefacts``.

    Steps (spec §3.1):

    1. Run all 9 pre-apply invariants. If any returns a ``BLOCKING``
       violation, return artefacts with empty conf/pactl/probe lists
       and the violations in ``preflight_checks``.
    2. Otherwise emit per-node confs (sorted by filename for byte
       determinism).
    3. Emit pactl invocations for every ``LoopbackTopology`` with
       ``apply_via_pactl_load=True``.
    4. Build post-apply probes per spec §3.1: one egress probe, one
       per private-broadcast crossing (assert silence), one per
       channel-count change (assert detection).
    5. Build a content-addressed rollback plan.
    """

    # 1. Pre-apply invariants
    violations = check_all_invariants(graph)
    blocking = [v for v in violations if v.severity == InvariantSeverity.BLOCKING]

    if blocking:
        # Refuse to emit any side-effecting artefacts. Probes, confs,
        # pactl loads are all empty. Carry an empty rollback plan
        # (content-addressed snapshot id is still well-defined).
        return CompiledArtefacts(
            confs_to_write={},
            pactl_loadmodule_invocations=(),
            preflight_checks=tuple(_sort_violations(violations)),
            postapply_probes=(),
            rollback_plan=_build_rollback_plan(graph, modules_to_unload=()),
        )

    # 2. Emit per-node confs (deterministic order)
    confs_to_write = _emit_confs(graph)

    # 3. pactl invocations
    pactl_loads = _emit_pactl_loads(graph)

    # 4. Post-apply probes
    probes = _build_postapply_probes(graph)

    # 5. Rollback plan
    rollback_plan = _build_rollback_plan(
        graph,
        modules_to_unload=tuple(f"{p.source}->{p.sink}" for p in pactl_loads),
    )

    return CompiledArtefacts(
        confs_to_write=confs_to_write,
        pactl_loadmodule_invocations=tuple(pactl_loads),
        preflight_checks=tuple(_sort_violations(violations)),
        postapply_probes=tuple(probes),
        rollback_plan=rollback_plan,
    )


# ---------------------------------------------------------------------------
# Conf emission — kind-specific templates
# ---------------------------------------------------------------------------


def _emit_confs(graph: AudioGraph) -> dict[str, str]:
    """Emit one conf per node that needs one, keyed by filename.

    Filenames follow the operator's existing pattern:
    ``hapax-{kebab-id}.conf`` for hapax-prefixed nodes and ``{id}.conf``
    otherwise. ALSA endpoints don't get conf files (they're hardware-
    discovered); only ``filter_chain``, ``loopback``, ``null_sink``
    nodes do.

    Filter-graph internals are emitted from ``AudioNode.filter_graph``
    (an opaque blob) verbatim — P1 does not regenerate filter graph
    syntax from descriptor; it round-trips what the validator captured.
    """

    out: dict[str, str] = {}

    # Sort nodes by id for byte-deterministic emission.
    nodes_sorted = sorted(graph.nodes, key=lambda n: n.id)

    for node in nodes_sorted:
        if node.kind in (NodeKind.ALSA_SOURCE, NodeKind.ALSA_SINK, NodeKind.TAP):
            # Hardware endpoints / model-only descriptors don't emit conf
            continue

        filename = _conf_filename_for(node)
        body = _emit_conf_body(graph, node)
        out[filename] = body

    return out


def _conf_filename_for(node: AudioNode) -> str:
    """Map a node to its conf filename.

    ``hapax-livestream-tap`` → ``hapax-livestream-tap.conf``
    ``broadcast-master`` → ``hapax-broadcast-master.conf`` (we always
    prefix hapax- in conf naming so the operator's confs all sort
    together in ``ls``).
    """
    base = node.id if node.id.startswith("hapax-") else f"hapax-{node.id}"
    return f"{base}.conf"


def _emit_conf_body(graph: AudioGraph, node: AudioNode) -> str:
    """Emit the conf body for a node. Kind-specific."""
    if node.kind == NodeKind.NULL_SINK:
        return _emit_null_sink(node)
    if node.kind == NodeKind.LOOPBACK:
        return _emit_loopback(graph, node)
    if node.kind == NodeKind.FILTER_CHAIN:
        return _emit_filter_chain(node)
    return f"# {node.id}: kind={node.kind.value} (no template)\n"


def _emit_null_sink(node: AudioNode) -> str:
    """Emit ``factory.name = support.null-audio-sink`` block."""
    pos = " ".join(node.channels.positions) if node.channels.positions else "FL FR"
    description = node.description or node.pipewire_name
    extra_params = _emit_extra_params(node, indent=12)
    extra_block = "\n" + extra_params if extra_params else ""
    return (
        f"# {description}\n"
        "context.objects = [\n"
        "    {   factory = adapter\n"
        "        args = {\n"
        "            factory.name     = support.null-audio-sink\n"
        f'            node.name        = "{node.pipewire_name}"\n'
        f'            node.description = "{description}"\n'
        "            media.class      = Audio/Sink\n"
        f"            audio.position   = [ {pos} ]\n"
        f"{extra_block}"
        "        }\n"
        "    }\n"
        "]\n"
    )


def _emit_loopback(graph: AudioGraph, node: AudioNode) -> str:
    """Emit ``libpipewire-module-loopback`` block.

    The capture/playback target_object is read from the
    ``LoopbackTopology`` descriptor when one is paired with this node;
    otherwise we fall back to the ``AudioNode.target_object``.
    """
    lb = next(
        (lb for lb in graph.loopbacks if lb.node_id == node.id),
        None,
    )
    target_object = (lb.sink if lb is not None else node.target_object) or ""
    capture_source = lb.source if lb is not None else node.target_object or ""

    pos = " ".join(node.channels.positions) if node.channels.positions else "FL FR"
    description = node.description or node.pipewire_name
    return (
        f"# {description}\n"
        "context.modules = [\n"
        "    {   name = libpipewire-module-loopback\n"
        "        args = {\n"
        f'            node.description = "{description}"\n'
        "            capture.props = {\n"
        f'                node.name      = "{node.pipewire_name}-capture"\n'
        f'                target.object  = "{capture_source}"\n'
        f"                audio.channels = {node.channels.count}\n"
        f"                audio.position = [ {pos} ]\n"
        "            }\n"
        "            playback.props = {\n"
        f'                node.name      = "{node.pipewire_name}"\n'
        f'                target.object  = "{target_object}"\n'
        f"                audio.channels = {node.channels.count}\n"
        f"                audio.position = [ {pos} ]\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "]\n"
    )


def _emit_filter_chain(node: AudioNode) -> str:
    """Emit ``libpipewire-module-filter-chain`` block.

    P1 does not emit filter-graph internals from scratch — when the
    validator captured a ``filter_graph`` blob, the compiler echoes it
    inside the ``args.filter.graph`` block verbatim. When no blob is
    available (a synthetic descriptor without prior validation), the
    conf is emitted with empty graph; the compiler does NOT silently
    skip the filter chain (the operator gets visible TODO marker).
    """
    pos = " ".join(node.channels.positions) if node.channels.positions else "FL FR"
    description = node.description or node.pipewire_name
    target_clause = (
        f'                target.object = "{node.target_object}"\n' if node.target_object else ""
    )
    if node.filter_graph is None:
        graph_clause = (
            "            filter.graph = {\n"
            "                # TODO: P1 compiler did not regenerate filter "
            "graph from descriptor.\n"
            "                # The validator did not capture a filter_graph "
            "blob, and P1 does not\n"
            "                # synthesise one from gain stages alone. The "
            "graph below is a stub.\n"
            "                nodes = []\n"
            "                inputs = []\n"
            "                outputs = []\n"
            "            }\n"
        )
    else:
        # Echo the captured opaque blob; the validator stored it as a
        # text representation we can inline.
        graph_text = node.filter_graph.get("__raw_text__", "")
        if graph_text:
            graph_clause = f"            filter.graph = {graph_text}\n"
        else:
            graph_clause = (
                "            filter.graph = {\n"
                "                # captured blob lacked __raw_text__\n"
                "                nodes = []\n"
                "                inputs = []\n"
                "                outputs = []\n"
                "            }\n"
            )

    return (
        f"# {description}\n"
        "context.modules = [\n"
        "    {   name = libpipewire-module-filter-chain\n"
        "        args = {\n"
        f'            node.description = "{description}"\n'
        f"            audio.channels = {node.channels.count}\n"
        f"            audio.position = [ {pos} ]\n"
        f"{graph_clause}"
        "            capture.props = {\n"
        f'                node.name = "{node.pipewire_name}"\n'
        f"{target_clause}"
        f"                audio.channels = {node.channels.count}\n"
        f"                audio.position = [ {pos} ]\n"
        "            }\n"
        "            playback.props = {\n"
        f'                node.name = "{node.pipewire_name}-playback"\n'
        f"                audio.channels = {node.channels.count}\n"
        f"                audio.position = [ {pos} ]\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "]\n"
    )


def _emit_extra_params(node: AudioNode, indent: int = 0) -> str:
    """Emit non-template ``params`` keys as ``key = value`` lines.

    The compiler pre-determines a small set of keys it owns (kind-template
    fields like ``audio.channels``, ``audio.position``, ``target.object``)
    and emits everything else verbatim. Keys are sorted for byte
    determinism.
    """
    skip_keys = {
        "audio.channels",
        "audio.position",
        "target.object",
        "node.name",
        "node.description",
        "factory.name",
        "media.class",
    }
    pad = " " * indent
    lines: list[str] = []
    for k in sorted(node.params.keys()):
        if k in skip_keys:
            continue
        v = node.params[k]
        if isinstance(v, bool):
            lit = "true" if v else "false"
        elif isinstance(v, int | float):
            lit = str(v)
        else:
            lit = f'"{v}"'
        lines.append(f"{pad}{k} = {lit}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# pactl emission
# ---------------------------------------------------------------------------


def _emit_pactl_loads(graph: AudioGraph) -> list[PactlLoad]:
    """Emit one ``PactlLoad`` per loopback with ``apply_via_pactl_load=True``.

    Sorted by ``(source, sink)`` for byte-deterministic output.
    """
    pactl_loops = [lb for lb in graph.loopbacks if lb.apply_via_pactl_load]
    pactl_loops.sort(key=lambda lb: (lb.source, lb.sink))
    return [
        PactlLoad(
            source=lb.source,
            sink=lb.sink,
            source_dont_move=lb.source_dont_move,
            sink_dont_move=lb.sink_dont_move,
            latency_msec=lb.latency_msec,
            expected_source_port_pattern=lb.expected_source_port_pattern,
            expected_sink_port_pattern=lb.expected_sink_port_pattern,
        )
        for lb in pactl_loops
    ]


# ---------------------------------------------------------------------------
# Post-apply probes
# ---------------------------------------------------------------------------


def _build_postapply_probes(graph: AudioGraph) -> list[PostApplyProbe]:
    """One probe per egress + every private-broadcast crossing + every
    channel-count change with declared downmix.

    Spec §3.1:

    * Egress probe → assert detection + RMS in [-40, -10] + crest < 5.
    * Private-broadcast crossings → assert silence at OBS terminus.
    * Channel-count changes → assert detection at downmix target.

    Sorted by name for byte-deterministic output.
    """
    probes: list[PostApplyProbe] = []
    obs_terminus = next(
        (n for n in graph.nodes if "obs-broadcast-remap" in n.id),
        None,
    )
    livestream_tap = next((n for n in graph.nodes if n.id == "livestream-tap"), None)
    if obs_terminus is not None and livestream_tap is not None:
        probes.append(
            PostApplyProbe(
                name="obs-egress-band",
                sink_to_inject=livestream_tap.pipewire_name,
                source_to_capture=f"{obs_terminus.pipewire_name}.monitor",
                inject_channels=2,
                expected_outcome="detected",
                egress_rms_band_dbfs=(-40.0, -10.0),
                egress_max_crest=5.0,
            )
        )

    # Private-broadcast crossing probes
    private_nodes = [
        n
        for n in graph.nodes
        if any(n.params.get(k) is True for k in ("private_monitor_endpoint", "fail_closed"))
    ]
    if obs_terminus is not None:
        for src in sorted(private_nodes, key=lambda n: n.id):
            probes.append(
                PostApplyProbe(
                    name=f"private-{src.id}-leak-check",
                    sink_to_inject=src.pipewire_name,
                    source_to_capture=f"{obs_terminus.pipewire_name}.monitor",
                    inject_channels=2,
                    expected_outcome="not_detected",
                )
            )

    # Channel-count change probes
    for gs in sorted(graph.gain_stages, key=lambda gs: (gs.edge_source, gs.edge_target)):
        if gs.downmix_strategy is None:
            continue
        src = next((n for n in graph.nodes if n.id == gs.edge_source), None)
        tgt = next((n for n in graph.nodes if n.id == gs.edge_target), None)
        if src is None or tgt is None:
            continue
        probes.append(
            PostApplyProbe(
                name=f"downmix-{gs.edge_source}-to-{gs.edge_target}",
                sink_to_inject=src.pipewire_name,
                source_to_capture=f"{tgt.pipewire_name}.monitor",
                inject_channels=src.channels.count,
                expected_outcome="detected",
            )
        )

    probes.sort(key=lambda p: p.name)
    return probes


# ---------------------------------------------------------------------------
# Rollback plan
# ---------------------------------------------------------------------------


def _build_rollback_plan(graph: AudioGraph, modules_to_unload: tuple[str, ...]) -> RollbackPlan:
    """Content-addressed snapshot strategy.

    The ``snapshot_id`` is sha256 of the descriptor JSON; the snapshot
    paths follow the operator's convention under
    ``~/.cache/hapax/pipewire-graph/snapshots/{snapshot_id}/``. P1 does
    not actually create the snapshot — that's P4. The plan is data so
    the daemon's apply path can read it deterministically.
    """
    payload = graph.model_dump_json(exclude_none=False)
    snapshot_id = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    snapshot_paths = (
        f"~/.cache/hapax/pipewire-graph/snapshots/{snapshot_id}/pipewire.conf.d/",
        f"~/.cache/hapax/pipewire-graph/snapshots/{snapshot_id}/wireplumber.conf.d/",
        f"~/.cache/hapax/pipewire-graph/snapshots/{snapshot_id}/pw-dump.json",
        f"~/.cache/hapax/pipewire-graph/snapshots/{snapshot_id}/pactl-modules.txt",
    )
    return RollbackPlan(
        snapshot_id=snapshot_id,
        snapshot_paths=snapshot_paths,
        pactl_modules_to_unload=tuple(sorted(modules_to_unload)),
    )


# ---------------------------------------------------------------------------
# Sort helpers (deterministic emission)
# ---------------------------------------------------------------------------


def _sort_violations(
    violations: list[InvariantViolation],
) -> list[InvariantViolation]:
    """Sort violations by (kind, node_id, edge, message) for byte-determinism."""

    def key(v: InvariantViolation) -> tuple[str, str, str, str]:
        return (
            v.kind.value,
            v.node_id or "",
            "".join(v.edge) if v.edge else "",
            v.message,
        )

    return sorted(violations, key=key)


# Suppress unused-import warning for downstream importers
__all__ = [
    "CompiledArtefacts",
    "InvariantKind",
    "LoopbackTopology",
    "PactlLoad",
    "PostApplyProbe",
    "RollbackPlan",
    "compile_descriptor",
]
