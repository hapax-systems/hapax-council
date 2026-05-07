---
title: Audio Graph SSOT + Router Daemon — End the Audio Routing Churn
date: 2026-05-03
author: alpha (architectural design, operator-commissioned)
audience: operator + alpha + beta + delta + cx-* + epsilon
register: scientific, engineering-normative
status: phased implementation in progress; Phase 3 lock/CLI dispatched; NO PipeWire / config changes in this PR
operator-directive-load-bearing: |
  "We have complicated use cases, but the fundamental constraints are well known
   and well understood. There is SOMETHING REALLY FUCKING WRONG with our
   implementation or our abstractions if we can NEVER EVER GET IT RIGHT FOR
   LONGER THAN 2 STRAIGHT MINUTES." — operator, 2026-05-03

  "I don't care if audio restarts. I don't care if compositor restarts. I don't
   care about restarts at all. BUT WHAT I CARE ABOUT IS SUDDENLY 20db of CLIPPING
   NOISE BEING PUMPED INTO THE LIVESTREAM or ABSOLUTE SILENCE." — operator, 2026-05-03

related:
  - docs/research/2026-05-03-audio-config-hardening-unthought-of-solutions.md (the H1–H5 hardenings ranked by impact-per-effort — informs Phase 0 + threshold reconciliation; confirms PipeWire upstream issue #2791 as the empirical basis for the conf-vs-pactl asymmetry)
  - docs/research/2026-04-23-livestream-audio-unified-architecture.md (the source of the descriptor model)
  - docs/superpowers/plans/2026-04-20-unified-audio-architecture-plan.md (the descriptor schema phases — this spec is the productionisation phase)
  - shared/audio_topology.py (Pydantic schema, schema_version=3, frozen Node/Edge models)
  - shared/audio_topology_generator.py (compiler — already emits per-node confs and LADSPA chain templates)
  - shared/audio_topology_inspector.py (live-graph reader — already has L-12 forward invariant + TTS broadcast path checks)
  - shared/audio_topology_switcher.py (current switcher; will be folded into the daemon's apply API)
  - scripts/hapax-audio-topology (CLI — already wraps describe / generate / diff / verify / audit / l12-forward-check / watchdog / pin-check)
  - scripts/hapax-audio-topology-assertion-runner (boot-time + recurring assertion)
  - scripts/audio-leak-guard.sh (private→broadcast static + runtime guard)
  - agents/broadcast_audio_health_producer/producer.py (17.5 kHz marker-tone probe with FFT detection — exists; needs coupling to apply)
  - agents/broadcast_orchestrator/ (existing YouTube-egress orchestration; coexists, does NOT own graph)
  - agents/audio_router/dynamic_router.py (existing 5 Hz Evil-Pet/S-4 MIDI arbiter — DIFFERENT DOMAIN; daemon name reserved, this spec uses `hapax-pipewire-graph` instead)
  - config/audio-topology.yaml (current descriptive YAML — becomes generative with §1 changes)
  - ~/.local/bin/hapax-obs-monitor-load (the precedent for idempotent pactl-load patterns)
  - hooks/scripts/work-resolution-gate.sh (the only currently-existing edit gate; this design adds a graph-edit gate)

constraint: |
  Design only. NO PipeWire mutation, NO config edits, NO runtime restarts.
  Implementation is split across 5 phases (§5); each phase ships behind an
  observable gate so rollback cost is bounded.

---

# §0. Verdict — Quote-worthy

> The audio graph is a database with no transaction log. Every conf in `~/.config/pipewire/pipewire.conf.d/`
> is a row; every `pactl load-module` invocation is an UPDATE; every WirePlumber rule and `target.object`
> directive is a TRIGGER. There is no schema, no constraint check, no rollback, and at least five writers
> who have never met. The proposed architecture treats it as the database it always was: one Pydantic-typed
> schema, one applier (`hapax-pipewire-graph` daemon), one transaction lock, atomic apply with snapshot+rollback,
> and a two-pronged circuit breaker that detects the only two unacceptable steady states (clipping noise / silence)
> at the egress sink and auto-mutes within 2 seconds. After this lands, "twenty minutes between failures"
> stops being a metric — it becomes the boring property the system has by construction.

---

# §1. Problem statement (what today's 11 failures share)

Today, between 07:00 and 13:00 local, the broadcast graph produced one of these outcomes every ~30 minutes:

| # | Symptom | Failure class |
|---|---|---|
| 1 | FL/FR ↔ RL/RR mismatch (music silent on broadcast) | port-compat decision distributed across confs |
| 2 | 8-second probe contending with L-12 capture (20–30 s dropouts) | a probe that didn't know it was on the live path |
| 3 | private → L-12 leak (constitutional violation, fixed by Option C) | invariant not expressible across multiple writers |
| 4 | conf-file loopback established but signal didn't flow | apply succeeded, signal didn't — no post-apply verify |
| 5 | conf says `audio.channels=2`, capture is 14 ch (silent downmix) | format declared per-conf, no topology-wide validation |
| 6 | `gain_samp=1.0` on AUX3 with -27 dB hardware bleed (white-noise signature) | gain stage assumes hardware bleed, no cross-check |
| 7 | pipewire restart breaks music links (auto-link order changes) | links are runtime-only state; not in declarative graph |
| 8 | concurrent session edit → BT hijack of OBS-monitor loopback | no lock or transaction on `~/.config/pipewire/` |
| 9 | pro-audio profile + HP-pin codec mux re-route → silent at jack | profile + pin state is across systemd, conf, and `hda-verb` |
| 10 | service-restart cascade breaks the chain | no pre-flight gate to snapshot+verify post-restart |
| 11 | conf-file loopback links established but no signal flowed | apply-then-verify-signal pattern absent |

**The unifying defect:** the audio graph has FIVE concurrent writers and ZERO single source of truth.

| Writer | What it writes | Coordinates with others? |
|---|---|---|
| Operator-edited `~/.config/pipewire/pipewire.conf.d/*.conf` | Filter-chain / loopback / null-sink modules | No |
| Operator-edited `~/.config/wireplumber/wireplumber.conf.d/*.conf` | `target.object` decisions, role-based pinning | No |
| `pactl load-module` invocations (e.g. `~/.local/bin/hapax-obs-monitor-load`) | Runtime-only loopbacks | No (idempotency by-script, not system-wide) |
| Sessions (alpha/beta/cx-*/etc.) editing `~/.config/` to fix issues | Anything | No |
| `chat_reactor` and other agents triggering preset routing changes | preset-driven `pw-cli` / `pw-link` | No |
| `audio-topology.yaml` (today *descriptive*) | nothing — only audited | N/A |

The constitutional invariants (private must not reach broadcast; OBS sink RMS must be in livestream-safe band;
L-12 capture must be 14 ch s32le or chain rejects it) are **distributed across files** — there is no place
where a process can ask "does this proposed change violate any invariant?" and get a yes/no answer.

The operator's reframing of unacceptable behaviour ("clipping noise OR silence — not restarts")
maps cleanly onto the data model: the graph has only two **post-apply egress invariants** that matter,
and we have never measured against either of them at apply time.

---

# §2. Pydantic schema for the audio graph

## 2.1 Existing schema (already shipped — schema_version=3)

`shared/audio_topology.py` already defines `NodeKind`, `ChannelMap`, `Node`, `Edge`, and `TopologyDescriptor`,
all `frozen=True` Pydantic models. The descriptor at `config/audio-topology.yaml` decomposes the live graph
into 30+ nodes and 14+ edges. **Reuse this; do not re-author.**

What's missing — the four model classes this spec adds:

```python
# shared/audio_topology_invariants.py — NEW

from __future__ import annotations
from enum import StrEnum
from typing import Literal, Protocol
from pydantic import BaseModel, Field, model_validator
from shared.audio_topology import TopologyDescriptor, Node, Edge


class InvariantSeverity(StrEnum):
    """How a violation should be handled at apply time."""
    BLOCKING = "blocking"       # apply MUST refuse
    WARNING = "warning"         # apply proceeds, ntfy operator
    INFORMATIONAL = "info"      # logged only


class InvariantKind(StrEnum):
    """Taxonomy of constitutional + operational invariants."""
    PRIVATE_NEVER_BROADCASTS = "private-never-broadcasts"           # axiom-grade
    L12_DIRECTIONALITY = "l12-directionality"                        # AUX0..AUX13 in only; RL/RR out only
    PORT_COMPATIBILITY = "port-compatibility"                        # FL→RL is a config bug, not a remap
    FORMAT_COMPATIBILITY = "format-compatibility"                    # 14 ch capture cannot feed 2 ch sink without explicit downmix node
    CHANNEL_COUNT_TOPOLOGY_WIDE = "channel-count-topology-wide"      # if any node downstream of capture declares 2 ch, capture node must be 2-ch or pass through a downmix node
    GAIN_BUDGET = "gain-budget"                                      # cumulative makeup_gain_db along any path ≤ +24 dB
    MASTER_BUS_SOLE_PATH = "master-bus-sole-path"                    # everything reaching OBS goes through hapax-broadcast-master
    NO_DUPLICATE_PIPEWIRE_NAMES = "no-duplicate-pipewire-names"      # two nodes can't claim the same node.name
    HARDWARE_BLEED_GUARD = "hardware-bleed-guard"                    # AUX channels with declared bleed_db must not have gain_samp > clamp_db
    EGRESS_SAFETY_BAND = "egress-safety-band"                        # post-apply: RMS at OBS sink in [-40, -10] dBFS during livestream


class BroadcastInvariant(BaseModel, frozen=True):
    """One invariant the topology must satisfy.

    The applier checks every BroadcastInvariant before writing any
    artefact and after applying. Violations of severity=BLOCKING refuse
    the apply atomically. Violations of severity=WARNING land in the
    daemon's audit log and trigger an ntfy.
    """
    kind: InvariantKind
    severity: InvariantSeverity = InvariantSeverity.BLOCKING
    description: str
    # Pure-function predicate — receives the descriptor and returns the
    # set of (node_id, edge_idx, message) tuples for any violations. The
    # registry below maps each kind to a concrete checker.
    check_fn_name: str  # name of a function in audio_topology_invariants_checkers.py


class ChannelDownmix(BaseModel, frozen=True):
    """Explicit declaration of a channel-count change at a node boundary.

    If absent and the descriptor introduces a count change between
    `source.channels.count != target.channels.count`, the FORMAT_COMPATIBILITY
    invariant fails (this is the failure that produced today's #5 silent
    downmix bug).
    """
    source_node: str
    target_node: str
    strategy: Literal["channel-pick", "mixdown", "broadcast-fan-out"]
    # When `strategy=channel-pick`, which source positions feed which
    # target positions. Example: `{"FL": "AUX1", "FR": "AUX3"}` for the
    # 14ch L-12 capture → 2ch livestream-tap path.
    map: dict[str, str] = Field(default_factory=dict)


class GainStage(BaseModel, frozen=True):
    """A declarative gain stage attached to an edge.

    Today edges carry `makeup_gain_db: float` directly (already shipped
    in `audio_topology.py`). This model adds the per-channel and bleed-
    aware variants so today's #6 (gain_samp=1.0 with -27 dB bleed) is
    expressible as data instead of as a hand-tuned conf line.
    """
    edge_source: str
    edge_target: str
    edge_source_port: str | None = None
    # Linear-domain (PipeWire `Gain 1`) for builtin mixer; convert from dB
    # at compile time. -inf for "fully attenuated" / mute.
    base_gain_db: float = Field(default=0.0, ge=-90.0, le=30.0)
    # Per-channel deltas — `{"AUX1": +12.0}` overrides base_gain_db on
    # that single capture position. The applier validates that the
    # resulting per-channel gain ≤ headroom budget.
    per_channel_overrides: dict[str, float] = Field(default_factory=dict)
    # Hardware bleed declaration for this edge's source. If the source
    # is `l12-capture` and the channel is AUX3, declared_bleed_db is
    # the analog hardware crosstalk we observed. The
    # HARDWARE_BLEED_GUARD invariant checks that
    # base_gain_db + per_channel_overrides[ch] - declared_bleed_db ≤ 0
    # (so a bleeding channel can never amplify its bleed source above
    # its own signal).
    declared_bleed_db: float | None = None


class LoopbackTopology(BaseModel, frozen=True):
    """Explicit model of a `module-loopback` instance.

    Today loopbacks live as nodes with `kind=NodeKind.LOOPBACK` plus a
    free-form `params` dict. This model lifts the loopback's required
    fields into typed properties so the applier can reason about them
    (today's #8: BT hijack happened because no model declared
    `source_dont_move=true` on the OBS-monitor loopback).
    """
    node_id: str  # must match a Node with kind=NodeKind.LOOPBACK
    source: str   # PipeWire node.name or descriptor node id
    sink: str
    source_dont_move: bool = True   # default = pin to declared source
    sink_dont_move: bool = True
    fail_closed_on_target_absent: bool = True
    # When True, the applier prefers `pactl load-module module-loopback`
    # over a conf-file declaration. Reason: per the operator's own
    # comment in hapax-obs-monitor-load, "the conf-file approach via
    # pipewire.conf.d/ was demonstrably broken: pipewire would link the
    # capture and playback ports correctly but no signal flowed." This
    # field captures that empirical decision per-loopback so the
    # compiler can emit the right artefact (§3).
    apply_via_pactl_load: bool = False
```

## 2.2 How current confs decompose

The 30+ existing confs in `~/.config/pipewire/pipewire.conf.d/` map onto exactly four `NodeKind` instances
plus a small set of `Edge` and `LoopbackTopology` instances. Concrete examples:

```python
# hapax-l12-evilpet-capture.conf  →  Node(kind=FILTER_CHAIN, ...) +
#                                   Edge(source="l12-capture", target="l12-evilpet-capture", source_port="AUX1") + ...
Node(
    id="l12-evilpet-capture",
    kind=NodeKind.FILTER_CHAIN,
    pipewire_name="hapax-l12-evilpet-capture",
    target_object="alsa_input.usb-ZOOM_Corporation_L-12_...",
    channels=ChannelMap(count=2, positions=["FL", "FR"]),
    # Today's #5 root cause was `audio.channels=2` declared at top-level
    # without a downmix node when the capture is 14ch. The
    # FORMAT_COMPATIBILITY invariant requires:
    params={
        "capture_channels": 4,
        "capture_positions": "AUX1 AUX3 AUX4 AUX5",
        "forbidden_capture_positions": "AUX8 AUX9 AUX10 AUX11 AUX12 AUX13",
        "playback_target": "hapax-livestream-tap",
    },
)

# AND a partner ChannelDownmix that makes the 14→2 transition explicit:
ChannelDownmix(
    source_node="l12-capture",        # 14 ch
    target_node="l12-evilpet-capture", # 2 ch
    strategy="channel-pick",
    map={"FL": "AUX1+AUX3", "FR": "AUX4+AUX5"},  # mixdown of two AUX → one position
)
```

## 2.3 Constitutional invariant as data — `private-never-broadcasts`

```python
# Already enforced today by:
#  - shared/audio_topology_inspector.py::check_l12_forward_invariant
#  - scripts/audio-leak-guard.sh (static + runtime)
# This spec lifts both into a single BroadcastInvariant that the daemon
# checks pre-apply AND continuously post-apply.

PRIVATE_NEVER_BROADCASTS = BroadcastInvariant(
    kind=InvariantKind.PRIVATE_NEVER_BROADCASTS,
    severity=InvariantSeverity.BLOCKING,
    description=(
        "Any node tagged private_monitor_endpoint=True or fail_closed=True must "
        "have no path (in the closure of the descriptor's edges) to any node in "
        "the broadcast family: livestream-tap, broadcast-master-capture, "
        "broadcast-normalized-capture, obs-broadcast-remap-capture, l12-evilpet-capture."
    ),
    check_fn_name="check_private_never_broadcasts",
)


# Concrete checker (in audio_topology_invariants_checkers.py):
def check_private_never_broadcasts(d: TopologyDescriptor) -> list[InvariantViolation]:
    """Reachability check: BFS from every private-tagged node; violations
    are any private node from which a broadcast-family node is reachable."""
    private_node_ids = {
        n.id for n in d.nodes
        if n.params.get("private_monitor_endpoint") is True
        or n.params.get("fail_closed") is True
        or n.id in PRIVATE_ONLY_ROOTS  # imported from inspector
    }
    broadcast_family_ids = BROADCAST_FAMILY_NODE_IDS  # constant from inspector
    adj: dict[str, list[str]] = defaultdict(list)
    for e in d.edges:
        adj[e.source].append(e.target)
    violations: list[InvariantViolation] = []
    for src in private_node_ids:
        reachable = bfs_descendants(adj, src)
        crossings = reachable & broadcast_family_ids
        if crossings:
            violations.append(InvariantViolation(
                kind=InvariantKind.PRIVATE_NEVER_BROADCASTS,
                node_id=src,
                message=f"private node {src} reaches broadcast-family nodes: {sorted(crossings)}",
            ))
    return violations
```

## 2.4 The 11 invariants the daemon checks

| Invariant | Source-of-record | Severity | Pre-apply / Post-apply |
|---|---|---|---|
| PRIVATE_NEVER_BROADCASTS | `audio_topology_inspector` (already there) | BLOCKING | both |
| L12_DIRECTIONALITY | `inspector.check_l12_forward_invariant` (already there) | BLOCKING | pre-apply |
| PORT_COMPATIBILITY | new — channel position match per edge | BLOCKING | pre-apply |
| FORMAT_COMPATIBILITY | new — channel count change requires `ChannelDownmix` | BLOCKING | pre-apply |
| CHANNEL_COUNT_TOPOLOGY_WIDE | new — global format check | BLOCKING | pre-apply |
| GAIN_BUDGET | new — cumulative gain along path ≤ +24 dB | BLOCKING | pre-apply |
| MASTER_BUS_SOLE_PATH | new — every broadcast-bound stream traverses `hapax-broadcast-master` | BLOCKING | pre-apply |
| NO_DUPLICATE_PIPEWIRE_NAMES | new — `pipewire_name` uniqueness across descriptor | BLOCKING | pre-apply |
| HARDWARE_BLEED_GUARD | new — `gain.declared_bleed_db` constraint | BLOCKING | pre-apply |
| EGRESS_SAFETY_BAND_RMS | continuous — RMS at OBS in [-40, -10] dBFS | BLOCKING (auto-mute) | post-apply (continuous) |
| EGRESS_SAFETY_BAND_CREST | continuous — crest factor not in clipping-noise band | BLOCKING (auto-mute) | post-apply (continuous) |

The first nine are **pre-apply guards**. The last two are the operator's two failure modes — they are
**continuous post-apply invariants** that drive the circuit breaker (§4).

---

# §3. Compiler — `AudioGraph.compile()`

The existing `shared/audio_topology_generator.py::generate_confs()` already emits per-node confs.
The compiler in this spec is a **superset** that emits four artefact classes from one descriptor:

## 3.1 Compiler output (pseudocode)

```python
# shared/audio_topology_compiler.py — NEW (superset of generate_confs)

@dataclass(frozen=True)
class CompiledArtefacts:
    # (a) PipeWire confs — keys are file paths under
    # `~/.config/pipewire/pipewire.conf.d/`. The daemon writes these
    # atomically via tmpfile + rename.
    pipewire_confs: dict[str, str]
    # (b) WirePlumber confs — same shape, target dir
    # `~/.config/wireplumber/wireplumber.conf.d/`.
    wireplumber_confs: dict[str, str]
    # (c) pactl load-module commands — one per LoopbackTopology with
    # apply_via_pactl_load=True. Daemon executes idempotently
    # (unload+reload pattern matching ~/.local/bin/hapax-obs-monitor-load).
    pactl_loads: list[PactlLoad]
    # (d) Pre-apply invariant violations — list[InvariantViolation].
    # Empty list means apply may proceed; non-empty means refuse and
    # surface the list to the operator.
    pre_apply_violations: list[InvariantViolation]
    # (e) Post-apply verification probes — one per egress / boundary.
    # Each is a callable that returns a probe result; the daemon
    # invokes them after apply and rolls back if any returns failure.
    post_apply_probes: list[PostApplyProbe]


@dataclass(frozen=True)
class PactlLoad:
    """Idempotent `pactl load-module module-loopback ...` invocation.

    Pattern matches `~/.local/bin/hapax-obs-monitor-load`:
      1. wait_for_sink(target_sink, timeout_s=60)
      2. find_existing_module_id(source, sink) → if present, no-op
      3. pactl load-module module-loopback source=... sink=...
         source_dont_move=true sink_dont_move=true latency_msec=20
      4. verify the new module's bound source/sink match the request
    """
    source: str
    sink: str
    source_dont_move: bool = True
    sink_dont_move: bool = True
    latency_msec: int = 20
    expected_source_port_pattern: str | None = None  # for verify
    expected_sink_port_pattern: str | None = None


@dataclass(frozen=True)
class PostApplyProbe:
    """A signal-flow probe that runs after apply and decides commit/rollback.

    Reuses the existing `agents.broadcast_audio_health_producer`
    inject+capture pattern (17.5 kHz tone + FFT detection) but binds
    one probe per CRITICAL boundary in the descriptor (egress, every
    private/broadcast crossing, every channel-count change).
    """
    name: str
    sink_to_inject: str
    source_to_capture: str
    inject_channels: int
    expected_outcome: Literal["detected", "not_detected"]
    # Audio-band RMS / crest gate for the egress probe specifically:
    # for the OBS-bound probe, the daemon ALSO measures continuous
    # RMS + crest after apply and refuses commit if outside band.
    egress_rms_band_dbfs: tuple[float, float] | None = None  # e.g. (-40, -10)
    egress_max_crest: float | None = None  # e.g. 5.0


def compile_descriptor(d: TopologyDescriptor) -> CompiledArtefacts:
    """Single entry-point. Returns immutable artefacts.

    Pure function. No side-effects. The daemon's `apply()` is the only
    thing that turns CompiledArtefacts into filesystem mutations and
    pactl invocations.
    """
    violations = check_all_invariants(d)
    if any(v.severity == InvariantSeverity.BLOCKING for v in violations):
        return CompiledArtefacts(
            pipewire_confs={}, wireplumber_confs={},
            pactl_loads=[],
            pre_apply_violations=violations,
            post_apply_probes=[],
        )
    pipewire_confs = generate_confs(d)              # existing fn
    wireplumber_confs = generate_wireplumber(d)     # NEW — emits role retargets, preferred-target pins
    pactl_loads = [emit_pactl_load(lb) for lb in d.loopbacks_apply_via_pactl()]
    probes = build_post_apply_probes(d)
    return CompiledArtefacts(
        pipewire_confs=pipewire_confs,
        wireplumber_confs=wireplumber_confs,
        pactl_loads=pactl_loads,
        pre_apply_violations=[],
        post_apply_probes=probes,
    )


def build_post_apply_probes(d: TopologyDescriptor) -> list[PostApplyProbe]:
    """One probe per egress + every private/broadcast crossing + every
    channel-count change (the boundaries where today's failures live).

    Egress probe is the ONE that drives the continuous circuit breaker.
    Private-broadcast crossing probes assert `not_detected` (silence
    expected). Channel-count change probes assert `detected` with
    expected level (catch silent-downmix class today's #5).
    """
    probes: list[PostApplyProbe] = []
    # Egress — the spec's most important probe. Drives §4 circuit breaker.
    probes.append(PostApplyProbe(
        name="obs-egress-band",
        sink_to_inject="hapax-livestream-tap",
        source_to_capture="hapax-obs-broadcast-remap.monitor",
        inject_channels=2,
        expected_outcome="detected",
        egress_rms_band_dbfs=(-40.0, -10.0),  # operator-defined safe band
        egress_max_crest=5.0,                  # > this = clipping noise signature
    ))
    # Private/broadcast crossings — assert silence on broadcast.
    for src in PRIVATE_ONLY_ROOTS:
        probes.append(PostApplyProbe(
            name=f"private-{src}-leak-check",
            sink_to_inject=src,
            source_to_capture="hapax-obs-broadcast-remap.monitor",
            inject_channels=2,
            expected_outcome="not_detected",
        ))
    # Channel-count change probes — assert signal flows after downmix.
    for cdm in d.channel_downmixes:
        probes.append(PostApplyProbe(
            name=f"downmix-{cdm.source_node}-to-{cdm.target_node}",
            sink_to_inject=cdm.source_node,
            source_to_capture=f"{cdm.target_node}.monitor",
            inject_channels=2,
            expected_outcome="detected",
        ))
    return probes
```

## 3.2 Where the compiler diverges from `generate_confs()` today

| Aspect | Today (`generate_confs`) | This spec |
|---|---|---|
| WirePlumber confs | NOT emitted (operator hand-edits `~/.config/wireplumber/`) | Emitted from descriptor (`wireplumber_confs` block) |
| pactl load-module | NOT modelled (one-off scripts like `hapax-obs-monitor-load`) | First-class artefact (`PactlLoad`) |
| Pre-apply invariants | Run by the assertion-runner script after the fact | Run BEFORE compile returns; refuses to emit on BLOCKING |
| Post-apply probes | Run by `hapax-broadcast-audio-health-producer.timer` (60 s cycle, decoupled from apply) | Run inline as part of apply; rollback on failure |
| Output | Just `pipewire_confs: dict[str, str]` | Five-tuple `CompiledArtefacts` (above) |

---

# §4. Daemon — `hapax-pipewire-graph` (renamed to avoid `hapax-audio-router` collision)

> **Naming note.** `hapax-audio-router.service` already exists as the 5 Hz Evil-Pet/S-4 MIDI arbiter. That
> daemon owns *MIDI routing* of preset programs — a different domain. This spec's daemon owns the *PipeWire
> audio graph* and is named `hapax-pipewire-graph` to prevent confusion.

## 4.1 Responsibilities

1. **Sole writer** to `~/.config/pipewire/pipewire.conf.d/` and `~/.config/wireplumber/wireplumber.conf.d/`
   for files in the daemon's manifest. Files NOT in the manifest are operator-owned escape hatches; they
   are shadowed during apply (renamed to `*.disabled-by-graph-router-{ts}`) and the operator must
   explicitly opt-in to re-enable.
2. **Sole caller** of `pactl load-module` for the broadcast graph. The runtime loopbacks
   that the operator's existing scripts (`hapax-obs-monitor-load`) created move into the daemon.
3. **Lock + transaction.** Acquires a `flock(2)` on `~/.cache/hapax/pipewire-graph/applier.lock` for the
   full apply lifecycle. Other sessions / scripts get a permission denied if they try to write the
   manifested files concurrently.
4. **Atomic apply** with snapshot+rollback. Before any change:
   - Snapshot current `~/.config/{pipewire,wireplumber}/.../*.conf` to `~/.cache/hapax/pipewire-graph/snapshots/{ts}/`.
   - Snapshot current `pw-dump` to `{ts}/pw-dump.json`.
   - Snapshot current `pactl list modules` to `{ts}/pactl-modules.txt`.
5. **Continuous post-apply verification** — runs the §4.2 circuit breaker in its own thread.
6. **Read-only API** for everyone else: `current()` (returns the applied descriptor),
   `verify_live()` (returns a HealthReport), `query_invariant(kind)`.
7. **Sole `pw-link` mutator** for the manifested graph (gap **G-spec-3** reconciliation,
   2026-05-03 alignment audit). Today three call-sites mutate live `pw-link`
   state outside the daemon:
   - `scripts/audio-leak-guard.sh` (tears down forbidden private→broadcast links).
   - `scripts/usb-router.py` (creates and destroys task-specific links).
   - `agents/local_music_player/player.py` (creates per-track stereo cross-links).
   Phase 4 transitions all three into daemon-mediated calls:
   - **leak-guard** becomes an internal emergency rollback path inside the
     daemon's continuous verification loop. The bash script is deprecated
     (replaced by an internal `EmergencyLinkSweep` function called by the
     breaker on engagement).
   - **usb-router** becomes a daemon API caller — its create/destroy
     operations route through `daemon.create_link()` / `daemon.destroy_link()`
     while it retains its scheduling logic.
   - **local_music_player** keeps its per-track link semantics but routes
     them through `daemon.ensure_link(source, target)`, which idempotently
     creates the link if absent and is a no-op if present.
   Control-plane writes (filter-chain `pw-cli set-param` for runtime gain
   knobs) remain owned by their domain agents per §4.6 and are NOT
   considered `pw-link` mutations.

## 4.2 The two-failure-mode circuit breaker

> **Auto-mute reconciliation (G-spec-2 — 2026-05-03 alignment audit).** The new
> `hapax-audio-signal-assertion` daemon (shipped on the parallel
> `alpha/audio-safe-restart-pre-flight-gate` branch) explicitly forbids auto-mute on
> false-positive grounds. **This spec wins the design tension.** The SSOT egress circuit
> breaker (§4.2) is the authoritative auto-mute surface; the assertion daemon's role
> narrows to signal-flow stage classification (not egress band breaker). The follow-on
> cc-task `h1-signal-flow-daemon-add-auto-mute-flag-aligning-with-ssot-p5` adds a
> `--auto-mute-on-clipping` opt-in flag to the assertion daemon (default OFF). When P5
> hardens the breaker the flag flips ON and the daemons consolidate into a single
> auto-mute path (the daemon becomes the breaker proxy for the signal-flow side and
> the SSOT breaker handles the egress side; both engage safe-mute through the same
> `SafeMuteRail` instance). Operator's framing rationale: "silence is better than noise
> on stream" — the spec's BLOCKING-on-detection behaviour stays load-bearing.


This is where the operator's reframing lands directly in code.

```python
# agents/pipewire_graph/circuit_breaker.py — NEW

@dataclass(frozen=True)
class EgressHealth:
    rms_dbfs: float
    crest_factor: float
    zcr: float          # zero-crossing rate (clipping noise = high ZCR)
    timestamp_utc: str
    sample_window_s: float = 0.5


class EgressFailureMode(StrEnum):
    NOMINAL = "nominal"
    CLIPPING_NOISE = "clipping-noise"   # crest > THRESHOLD AND rms > -40 dBFS sustained 2s
    SILENCE = "silence"                 # rms < -60 dBFS sustained 5s during livestream


# Thresholds — pinned constants, not env-tunable, because their drift is
# itself a class of failure. Override only via a deploy-time PR.
CLIPPING_CREST_THRESHOLD: Final[float] = 5.0    # white-noise has crest ≈ 1.4; voice ≈ 3-4; clipping noise ≈ 5+
CLIPPING_RMS_THRESHOLD_DBFS: Final[float] = -40.0
CLIPPING_SUSTAINED_S: Final[float] = 2.0
SILENCE_RMS_THRESHOLD_DBFS: Final[float] = -60.0
SILENCE_SUSTAINED_S: Final[float] = 5.0
SAMPLE_WINDOW_S: Final[float] = 0.5             # reads at 2 Hz
HYSTERESIS_RECOVERY_S: Final[float] = 3.0       # exit failure state only after 3s of NOMINAL


class EgressCircuitBreaker:
    """Continuous probe of `hapax-obs-broadcast-remap.monitor` and
    `hapax-broadcast-normalized.monitor`.

    Reads 0.5 s windows of int16 PCM at 48 kHz via parec (same primitive
    as broadcast_audio_health_producer). Computes RMS + crest factor +
    ZCR. State machine:
      NOMINAL → CLIPPING_NOISE  (crest > 5.0 AND rms > -40 dBFS for 2s)
      NOMINAL → SILENCE          (rms < -60 dBFS for 5s, gated on
                                   livestream_active probe)
      CLIPPING_NOISE → NOMINAL   (crest < 4.0 AND rms in [-40,-10] for 3s)
      SILENCE → NOMINAL          (rms in [-40,-10] for 3s)

    On entry to CLIPPING_NOISE OR SILENCE:
      1. Engage safe-mute path (§4.3 — silence is preferred over noise).
      2. ntfy operator (red).
      3. Snapshot pw-dump.json + pactl-modules.txt to incident dir.
      4. Begin rollback to last NOMINAL snapshot.
      5. After rollback, run egress probe again. If still failed, STAY
         on safe-mute and surface a maintenance card.

    The breaker is NOT triggered by:
      - Brief excursions during track changes (< 2 s for clipping,
        < 5 s for silence — this is the hysteresis budget).
      - Service restarts that clearly emit a SIGTERM-then-SIGKILL window.
      - Explicit operator-driven mute (the safe-mute path itself).
    """

    def __init__(self, daemon: PipewireGraphDaemon) -> None:
        self.daemon = daemon
        self.state: EgressFailureMode = EgressFailureMode.NOMINAL
        self.failure_entered_at: float | None = None
        self.recovery_entered_at: float | None = None
        self._stop_evt = threading.Event()

    def run_forever(self) -> None:
        while not self._stop_evt.is_set():
            health = self._probe_egress()
            self._update_state(health, time.monotonic())
            time.sleep(SAMPLE_WINDOW_S)

    def _probe_egress(self) -> EgressHealth:
        # parec hapax-obs-broadcast-remap.monitor for 0.5s, compute
        # RMS + crest + ZCR. See producer.py::_default_capture for the
        # subprocess pattern.
        pcm = capture_short_window("hapax-obs-broadcast-remap.monitor", SAMPLE_WINDOW_S, 48000)
        rms = 20 * math.log10(max(rms_linear(pcm), 1e-10))
        crest = peak_linear(pcm) / max(rms_linear(pcm), 1e-10)
        zcr = zero_crossings(pcm) / len(pcm)
        return EgressHealth(rms_dbfs=rms, crest_factor=crest, zcr=zcr, timestamp_utc=...)

    def _update_state(self, h: EgressHealth, t: float) -> None:
        if self.state == EgressFailureMode.NOMINAL:
            if h.crest_factor > CLIPPING_CREST_THRESHOLD and h.rms_dbfs > CLIPPING_RMS_THRESHOLD_DBFS:
                self.failure_entered_at = self.failure_entered_at or t
                if t - self.failure_entered_at > CLIPPING_SUSTAINED_S:
                    self._enter_failure(EgressFailureMode.CLIPPING_NOISE)
            elif h.rms_dbfs < SILENCE_RMS_THRESHOLD_DBFS and self._livestream_active():
                self.failure_entered_at = self.failure_entered_at or t
                if t - self.failure_entered_at > SILENCE_SUSTAINED_S:
                    self._enter_failure(EgressFailureMode.SILENCE)
            else:
                self.failure_entered_at = None
        else:  # in failure state
            if -40.0 <= h.rms_dbfs <= -10.0 and h.crest_factor < 4.0:
                self.recovery_entered_at = self.recovery_entered_at or t
                if t - self.recovery_entered_at > HYSTERESIS_RECOVERY_S:
                    self._exit_failure()
            else:
                self.recovery_entered_at = None

    def _enter_failure(self, mode: EgressFailureMode) -> None:
        self.state = mode
        self.daemon.engage_safe_mute(reason=mode)
        self.daemon.snapshot_incident(mode)
        self.daemon.notify_operator(mode, severity="red")
        self.daemon.attempt_rollback(mode)

    def _exit_failure(self) -> None:
        self.state = EgressFailureMode.NOMINAL
        self.recovery_entered_at = None
        self.failure_entered_at = None
        self.daemon.disengage_safe_mute()
        self.daemon.notify_operator(EgressFailureMode.NOMINAL, severity="green")
```

### 4.2.1 Why these thresholds — and the disagreement to resolve

| Threshold | Justification |
|---|---|
| `crest > 5.0` (this spec's choice for clipping-noise gate) | This spec frames clipping noise as gain-feedback / amplified-bleed noise, where crest factor is HIGH (5–8) because the noise is uncorrelated. Voice 3–4. Music 4–6. Digital clipping > 10. |
| `rms > -40 dBFS sustained 2s` (clipping gate) | Below -40 dBFS, even high crest is "silent enough that the operator wouldn't call it a noise complaint." The 2 s sustain rules out track-change transients (typically < 1 s of crossfade with high crest). |
| `rms < -60 dBFS sustained 5s` (silence gate) | Real broadcast averages around -18 to -24 dBFS RMS. -60 dBFS is the "system is actually silent" floor. 5 s sustain ignores brief gaps during stream restarts (the operator explicitly accepted these). Gated on `livestream_active` so the breaker doesn't fire when the operator simply isn't streaming. |
| `HYSTERESIS_RECOVERY_S = 3` | After auto-mute, the rollback completes in 1–2 s; we wait 3 s of clean NOMINAL audio before declaring recovered to prevent flap. |

**Threshold disagreement with the H1 predicate proposal in `docs/research/2026-05-03-audio-config-hardening-unthought-of-solutions.md`:**
the research doc proposes `crest_band: tuple[float, float] = (2.5, 5.0)` as the **NOISE band — crest INSIDE this
range == noise**, on the basis of the prior agent's white-noise signature finding (white noise from
PipeWire format-conversion artefacts has tight crest 3.5–4.5; real broadcast has crest 5.5+ post-limiter).
This spec uses `crest > 5.0` as the clipping-noise gate (crest ABOVE this == noise) on the basis that the
operator's framing was "20 dB clipping noise" — which is the +20 dB amplified-bleed class, not the format-
conversion class. **Both classes exist.** The Phase 2 shadow-window observation period must surface false-
positive / false-negative counts for BOTH thresholds and the `EgressCircuitBreaker` should be configured
with TWO predicates running in parallel:

- `clipping-noise-amplified-bleed`: `crest > 5.0 AND rms > -40 dBFS` sustained 2 s
- `noise-format-conversion-artefact`: `2.5 ≤ crest ≤ 5.0 AND sigma_db < 4.0` sustained 2 s (steady drone +
  format-artefact crest signature)

Either predicate firing engages safe-mute. The thresholds are pinned but the predicate count is open;
P2's 24 h shadow window is the empirical surface that decides whether to ship both, one, or other.

### 4.2.2 Why the breaker reads `hapax-obs-broadcast-remap.monitor`

That node is the **closest probe point to OBS** in the existing graph. `hapax-broadcast-normalized.monitor`
is one stage upstream and lacks the final remap, so a remap-stage failure would not be observed there.
The breaker reads BOTH (`obs-broadcast-remap` is primary; `broadcast-normalized` is a corroborator) so a
failure at the remap stage is distinguishable from a failure further upstream.

## 4.3 Safe-mute path

The operator's framing puts silence above clipping noise. This means: when the breaker fires, the daemon
must *guarantee* silence on the OBS-bound monitor while it rolls back. The safe-mute mechanism:

```python
class SafeMuteRail:
    """A pre-loaded silence loopback that takes over the OBS-bound monitor
    when the circuit breaker engages.

    Implementation: the daemon at start time loads (via pactl) a
    `module-pipe-source` reading from /dev/zero into a virtual sink
    `hapax-egress-safe-mute`. A `module-loopback` connects this virtual
    sink to `hapax-obs-broadcast-remap` on demand. The loopback is
    NOT linked at idle — `node.dont-fallback=true` and no
    `target.object` — so it consumes zero bandwidth.

    On engage:
      pw-link hapax-egress-safe-mute:output_FL hapax-obs-broadcast-remap:input_FL
    On disengage:
      pw-link --disconnect ...
    """
    def engage(self) -> None: ...
    def disengage(self) -> None: ...
```

Crucial property: the safe-mute rail is loaded **at daemon start**, not at engage time. Loading at engage
time would be racing against the failure that triggered it. At engage, only the (cheap, atomic) `pw-link`
is performed.

## 4.4 Rollback semantics

```python
def attempt_rollback(self, mode: EgressFailureMode) -> RollbackResult:
    """Restore last known-NOMINAL snapshot atomically.

    1. Identify last snapshot dir whose post-apply probes passed
       (snapshot dirs carry a `nominal=true|false` marker file written
       by the apply path AFTER post-apply probes succeed).
    2. Acquire applier lock.
    3. Replace `~/.config/pipewire/pipewire.conf.d/{manifested}` and
       `~/.config/wireplumber/wireplumber.conf.d/{manifested}`
       with snapshot contents (atomic via tmpfile + rename).
    4. Tear down all daemon-loaded `module-loopback` instances and
       reload from snapshot's `pactl-modules-snapshot.txt`.
    5. systemctl --user restart pipewire wireplumber pipewire-pulse
       (in that order, with WatchdogSec).
    6. After 10 s settling, run post-apply probes against the rolled-
       back state. If passes, declare ROLLBACK_OK; if fails,
       STAY_MUTED.

    The whole rollback should take ≤ 10 s typical. Safe-mute remains
    engaged throughout.
    """
```

## 4.5 API surface

```python
class PipewireGraphDaemon:
    """Sole writer for the manifested PipeWire graph."""

    def apply(self, target: TopologyDescriptor) -> ApplyResult:
        """Atomic apply.

        Steps:
          1. Acquire flock(applier.lock).
          2. compile_descriptor(target) → CompiledArtefacts.
          3. If pre_apply_violations → return ApplyResult.refused.
          4. Snapshot current state.
          5. Diff against current; minimize the change set.
          6. Write conf changes (atomic tmpfile + rename per file).
          7. Execute pactl loads (idempotent unload+reload).
          8. systemctl restart pipewire/wireplumber if any conf changed.
          9. Wait 5 s settling.
         10. Run post-apply probes. Each must pass within 10 s.
         11. If all pass, mark snapshot nominal=true and return ApplyResult.ok.
         12. If any fails, run attempt_rollback() and return ApplyResult.rolled_back.
        Releases applier.lock on return.
        """

    def current(self) -> TopologyDescriptor:
        """Returns the descriptor most recently applied (read from
        ~/.cache/hapax/pipewire-graph/current.yaml)."""

    def validate(self, target: TopologyDescriptor) -> list[InvariantViolation]:
        """Pure check — no side effects. Subset of compile()."""

    def verify_live(self) -> HealthReport:
        """Read pw-dump + pactl, compare against current(), return drift."""

    def lock(self, owner: str, ttl_s: int = 300) -> LockHandle:
        """Acquire the applier lock for a held edit. Releases on
        context-manager exit OR after ttl_s. Owner is logged."""
```

## 4.6 Coexistence with existing services

| Service | Continues to exist? | Relationship to daemon |
|---|---|---|
| `hapax-audio-router.service` (Evil-Pet/S-4 5 Hz MIDI arbiter) | Yes — different domain | Reads `current()` for hardware-presence awareness; never writes graph |
| `hapax-broadcast-orchestrator.service` (YouTube egress lifecycle) | Yes | Reads `current()` to know broadcast-master is wired; never writes graph |
| `hapax-broadcast-audio-health-producer.timer` (17.5 kHz probe) | Yes — but **moves to in-process callee** | The §4.2 breaker re-uses producer.py primitives. The timer becomes a **daily evidence dump**, not the live safety mechanism. The 60 s timer-driven probe is the source of today's #2 failure (probe contention with capture). The daemon's in-process probe is gated on `livestream_active` and never runs while the breaker is in failure state. |
| `hapax-audio-topology-assertion.timer` | Yes | Calls `daemon.verify_live()` instead of running standalone. |
| `hapax-music-loudnorm-driver.service` | Yes | `pw-cli` writes to filter-chain controls live; daemon does not own per-control runtime values. |
| `hapax-audio-ducker.service` | Yes | Same — writes runtime gain to existing duck nodes. |
| `hapax-content-resolver.service` | Yes | Reads `current()` to discover which content sinks exist. |
| Operator scripts in `~/.local/bin/hapax-obs-monitor-load` | DEPRECATED, daemon takes over | The pactl load-module pattern moves into `PactlLoad` artefacts. |

The daemon **does not** assert ownership over filter-chain runtime controls (gain knobs, ducker mixer
values, LADSPA parameters that change at runtime). Those remain owned by their domain agents. The daemon
owns *graph topology*, not *control plane*.

---

# §5. Migration plan — phased, observable

Six phases (Phase 0 + five). Each phase has: a sole observable that proves it works, a bounded blast
radius, and a clean rollback. No phase ships until the previous one has been live for ≥ 24 h with zero
new failure-mode incidents.

## Phase 0 — Migrate `hapax-livestream-tap.conf` to systemd-driven pactl-load (immediate-ship)

**What ships:** apply the §6 immediate-ship recommendation from
`docs/research/2026-05-03-audio-config-hardening-unthought-of-solutions.md` directly. This is the
"prove the H3 conf→pactl migration on the highest-risk single chain" experiment, before the daemon
arrives. Specifically:

1. Disable `~/.config/pipewire/pipewire.conf.d/hapax-livestream-tap.conf` by renaming to
   `.disabled-by-p0-migration-{ts}`.
2. Create `~/.local/bin/hapax-livestream-tap-load` modeled on `hapax-obs-monitor-load`: wait for the
   pre-tap source + the L-12 capture source; idempotent module check (skip if already loaded);
   `source_dont_move=true sink_dont_move=true`; post-load verification.
3. `systemd/units/hapax-livestream-tap-loopback.service` — `Type=oneshot RemainAfterExit=yes`,
   `After=pipewire.service pipewire-pulse.service wireplumber.service`, `WantedBy=default.target`.

**Observable that proves it works:** during a 7 d livestream window post-P0, zero "audio links established
but no signal flowed" incidents involving `hapax-livestream-tap` (this incident class accounted for 3 of
6 in the pre-design session). The existing `hapax-broadcast-audio-health-producer.timer` + assertion
are the verification surfaces.

**Rollback cost:** `mv hapax-livestream-tap.conf{.disabled-by-p0-migration-{ts},}` and disable the
systemd unit. Returns to pre-P0 conf-file load. Zero descriptor changes.

**Bounded by:** one loopback. Does NOT touch the descriptor format, the daemon, the lock, or the
breaker. Pure migration of one conf-shaped artefact to one pactl-shaped artefact.

**Why P0 not Phase 1:** the research doc identifies this as the single highest-impact, lowest-effort,
lowest-risk action on the path. Shipping it BEFORE the architectural changes (a) gives operator one
week of fewer incidents while P1+ ships, (b) validates the systemd-pactl-loopback template that P4
will use for the rest of the loopbacks, (c) is independently revertible.

## Phase 1 — Compiler + passive validator (CI-only)

**What ships:**

1. `shared/audio_topology_compiler.py` — `compile_descriptor()` returning `CompiledArtefacts`.
2. `shared/audio_topology_invariants.py` + `..._invariants_checkers.py` — the 11 invariants.
3. `tests/test_audio_topology_compiler.py` — feeds today's `config/audio-topology.yaml` and
   asserts that `compile_descriptor()` returns zero BLOCKING violations.
4. CI job `audio-topology-validate` — runs on every PR that touches `config/audio-topology.yaml`,
   `~/.config/pipewire/pipewire.conf.d/`, or `~/.config/wireplumber/`.

**Observable that proves it works:** `compile_descriptor(config/audio-topology.yaml)` returns zero
BLOCKING violations AND `compile_descriptor(today's pre-fix yaml)` would have returned a
PRIVATE_NEVER_BROADCASTS violation (regression test for today's #3).

**No runtime changes.** No PipeWire mutation. No conf edits.

**Rollback cost:** delete the new files. Zero blast radius.

**Bounded by:** the existing tests in `tests/test_audio_topology*.py` already cover descriptor parsing
and inspector logic. The compiler is purely additive — failing tests would block CI but not affect runtime.

## Phase 2 — Daemon in shadow mode

**What ships:**

1. `agents/pipewire_graph/__init__.py`, `daemon.py`, `circuit_breaker.py`.
2. `systemd/units/hapax-pipewire-graph-shadow.service` — daemon runs but `apply()` is replaced with
   `apply_dry_run()` that diffs target against runtime and writes a report to
   `~/hapax-state/pipewire-graph/shadow-runs/{ts}.json` instead of writing.
3. The §4.2 circuit breaker runs **in observe-only mode**: probes egress, computes RMS/crest/ZCR,
   logs to `~/hapax-state/pipewire-graph/egress-health.jsonl`, but **does not auto-mute**. ntfy fires
   on first observed CLIPPING_NOISE / SILENCE state with body "shadow-mode would have engaged safe-mute".
4. A waybar widget polls the egress-health.jsonl every 5 s and shows green / yellow / red.

**Observable that proves it works:** during a 24 h livestream window, the shadow breaker accurately
fires on every operator-perceived audio problem and does NOT false-positive on legitimate restarts /
track changes. The shadow runs report shows daemon-vs-runtime drift (this is the discovery surface for
the descriptor's own gaps).

**Rollback cost:** `systemctl --user disable --now hapax-pipewire-graph-shadow`. Zero impact on the
running graph.

**Bounded by:** read-only. No file writes outside `~/hapax-state/`. No `pactl load-module`.

## Phase 3 — Lock + transaction layer

> **2026-05-07 P3 dispatch note.** The shipped P3 slice is the edit-lock
> and read-only CLI coordination surface only. It intentionally does not
> apply live graph mutations, write PipeWire/WirePlumber confs, invoke
> `pactl load-module`, or restart services. Active apply and
> snapshot/rollback remain Phase 4 surfaces.

**What ships:**

1. The session-scoped applier lease
   (`~/.cache/hapax/pipewire-graph/applier.lock`) is created/refreshed by
   `scripts/hapax-pipewire-graph lock`. The lease is JSON so hooks can
   read owner, expiry, and mutation mode directly; lock writes are
   serialized with `flock(2)`.
2. PreToolUse hook `hooks/scripts/pipewire-graph-edit-gate.sh` blocks Edit/Write tool calls
   targeting `~/.config/pipewire/pipewire.conf.d/*.conf` or
   `~/.config/wireplumber/wireplumber.conf.d/*.conf` UNLESS the calling session holds the applier lock
   (the hook reads the JSON lease and rejects missing, expired, malformed, or wrong-owner locks). The
   hook prints an actionable error:
   "graph editing is now daemon-mediated; use `hapax-pipewire-graph apply <descriptor> --dry-run` or
   `hapax-pipewire-graph lock --owner $CLAUDE_ROLE` to hold the lock for a session-scoped edit."
3. `scripts/hapax-pipewire-graph` CLI — wraps the safe P3 surfaces. `validate` runs compiler/invariants
   read-only, `current` decomposes the currently deployed conf set read-only, `verify` checks either the
   current graph or a supplied descriptor, `lock`/`unlock` manage the lease, `lock-status` prints the
   lease, `apply <yaml> --dry-run` writes only the P2 shadow report, and active `apply <yaml>` is refused
   until Phase 4.

**Observable that proves it works:** a deliberate concurrent-edit test from two terminals shows one wins,
one fails with an actionable error. No edit to a manifested file proceeds without the lock.

**Rollback cost:** disable the hook (`hooks/scripts/pipewire-graph-edit-gate.sh` removed from the
PreToolUse list in `~/.claude/settings.json`). Concurrent edits resume. Risk: pre-Phase-3 collision class
returns. Document the manual recovery script in case the lock file gets stuck.

**Bounded by:** does NOT write any conf yet — only blocks others from writing.

## Phase 4 — Daemon takes over write path

> **Phase boundary clarification (G-spec-4 — 2026-05-03 alignment audit).** The
> "post-apply probes are P5" framing in §7 #11 was tightened during the audit. P4
> ships the daemon-orchestrated write path PLUS a basic post-apply settling probe
> (single-shot, runs immediately after `systemctl restart` and signals failure if no
> signal flow is detected within 10 s; this is what catches today's #7 "PipeWire
> restart breaks links" class). P5 hardens this into the continuous breaker thread
> AND the pre-loaded `SafeMuteRail` AND the integration test for the deliberate-
> failure injection. **What "post-apply probe" means in P4 vs P5 differs:** P4 is
> "did the apply produce signal flow", P5 is "is the live broadcast egress within
> safe band continuously". Operator-facing rule: P4 catches restart breakage, P5
> catches drift / sustained noise / silence.

**What ships:**

1. The daemon transitions from shadow to active. `apply()` writes confs and runs pactl loads.
2. The §4.2 circuit breaker transitions from observe-only to enforcement (auto-mute on engage)
   — see G-spec-4 phase boundary clarification above for the P4-vs-P5 split on the
   distinct "post-apply settling probe" and "continuous breaker" surfaces.
3. All operator scripts that used to write `~/.config/pipewire/` are converted to invoke
   `hapax-pipewire-graph apply` against the descriptor. `~/.local/bin/hapax-obs-monitor-load` is
   deprecated; its loopback moves into the descriptor as a `LoopbackTopology(apply_via_pactl_load=True)`.
4. The daemon's `apply()` is invoked once on activation against the current `config/audio-topology.yaml`
   to produce a "we own this" baseline. The previous confs (those NOT in the manifest) are renamed to
   `*.disabled-by-graph-router-{ts}` and the operator is notified with a list.
5. A bypass envvar `HAPAX_PIPEWIRE_GRAPH_BYPASS=1` exists for incident-response (read by the hook).
   Setting it logs an immediate ntfy red (the operator wants to know if the safety is bypassed).
6. **`config/pipewire/` becomes legacy snapshot post-P4 (G-11 reconciliation,
   2026-05-03 alignment audit).** The in-tree git copy remains for git history /
   review-by-grep, but the daemon owns the deployed `~/.config/pipewire/...` only.
   A README in `config/pipewire/` is updated to declare the directory "frozen
   post-P4 — operator-edited examples preserved for spec review; the runtime
   source-of-truth is the AudioGraph YAML descriptor + the daemon".

**Observable that proves it works:** during a 24 h livestream window, every conf change goes through
the daemon, and the egress-health log shows zero CLIPPING_NOISE / SILENCE state entries (because the
daemon's pre-apply checks would have refused any change that introduced one).

**Rollback cost:** revert to Phase 3 state by stopping the daemon and re-enabling the disabled confs
from `*.disabled-by-graph-router-{latest}`. The snapshot directory under `~/.cache/hapax/pipewire-graph/snapshots/`
is the recovery surface. Document the rollback as a script: `scripts/hapax-pipewire-graph-rollback-to-phase-3`.
Risk on rollback: descriptor-and-runtime drift, but bounded by the snapshot.

**Bounded by:** rollback returns to Phase 3 state — descriptor still authoritative, but the safety net
is no longer enforced.

## Phase 5 — Continuous verification + circuit breaker hardening

**What ships:**

1. The §4.2 circuit breaker's auto-mute path (`SafeMuteRail`) is tested via a deliberate-failure
   integration test: inject a high-crest noise into `hapax-livestream-tap`, assert the breaker engages
   within 2 s, assert OBS receives silence within 200 ms of engagement.
2. The `hapax-broadcast-audio-health-producer.timer` is reduced from a 60 s livestream-contending probe
   to a 30 min boot-and-recover probe — the live safety is the daemon's in-process breaker.
3. `hapax-broadcast-audio-health.service` (the consumer side) reads from the daemon's egress-health
   stream (Prometheus exporter on `:9489`) instead of running its own parec capture.
4. Grafana dashboard `audio-graph-health` — shows: applier lock status, egress RMS/crest/ZCR
   trace at 2 Hz, last apply timestamp + outcome, last incident snapshot, current `nominal=true` snapshot
   age.

**Observable that proves it works:** A deliberate-failure test (e.g. inject a -10 dBFS white-noise burst
into `hapax-livestream-tap` for 5 s) results in: safe-mute engages within ≤ 2.5 s, ntfy fires red,
rollback to last nominal completes within ≤ 10 s, NOMINAL state re-entry within ≤ 15 s of injection start.

**Rollback cost:** disable `EgressCircuitBreaker.run_forever()` in the daemon (an envvar
`HAPAX_PIPEWIRE_GRAPH_BREAKER_DISABLED=1`). Apply path stays active, only the continuous
verification stops. The 60 s timer-based probe stays as a fallback.

**Bounded by:** the breaker can be disabled without disabling the apply path.

---

# §6. Filing the work — cc-task notes

Each phase becomes a cc-task note in `~/Documents/Personal/20-projects/hapax-cc-tasks/active/`. WSJF
references: today's #1 (private-playback L-12 leak, WSJF 14) and #2 (ducker daemon dead, WSJF 13)
anchor the SSOT epic at WSJF 14 (matches #1) for the parent epic and 11–13 for the phases.

## Task slugs

| Slug | Phase | WSJF | Dependencies |
|---|---|---|---|
| `audio-graph-ssot-epic` | parent | 14 | (none) |
| `audio-graph-ssot-p0-livestream-tap-pactl-migration` | Phase 0 | 14 (parallel to parent) | (none — immediate-ship) |
| `audio-graph-ssot-p1-compiler-validator` | Phase 1 | 13 | parent |
| `audio-graph-ssot-p2-daemon-shadow` | Phase 2 | 12 | p1 |
| `audio-graph-ssot-p3-lock-transaction` | Phase 3 | 12 | p2 |
| `audio-graph-ssot-p4-daemon-takeover` | Phase 4 | 13 | p3 |
| `audio-graph-ssot-p5-circuit-breaker-harden` | Phase 5 | 11 | p4 |

Each task carries `kind: build`, `created_at: 2026-05-03T...Z`, and a one-paragraph evidence block
citing today's failure log and this spec.

---

# §7. Honest assessment — does this prevent today's 11 failures?

| # | Today's failure | Phase that prevents it | Class of prevention | Confidence |
|---|---|---|---|---|
| 1 | FL/FR vs RL/RR mismatch | P1 | PORT_COMPATIBILITY invariant pre-apply | high |
| 2 | 8 s probe contending with L-12 | P5 | breaker becomes in-process; timer probe is 30 min not 60 s | high |
| 3 | private→L-12 leak | P1 | PRIVATE_NEVER_BROADCASTS invariant pre-apply | very high (already enforced today by inspector — P1 makes it apply-time blocking) |
| 4 | conf-file loopback fails / pactl-load works | P1 | LoopbackTopology.apply_via_pactl_load expressible per-loopback | high |
| 5 | audio.channels=2 vs 14 ch capture | P1 | FORMAT_COMPATIBILITY + CHANNEL_COUNT_TOPOLOGY_WIDE invariants | very high |
| 6 | gain_samp=1.0 with -27 dB hardware bleed | P1 | HARDWARE_BLEED_GUARD invariant + GainStage.declared_bleed_db | medium-high (depends on operator declaring the bleed values; the model surfaces the missing data) |
| 7 | pipewire restart breaks links | P4 | apply path includes settling + post-apply probes; rollback if links fail to flow | high |
| 8 | concurrent session edit → BT hijack | P3 | applier lock | very high |
| 9 | pro-audio + HP pin codec mux re-route | P4 | descriptor includes profile/pin state; verify_live diffs against current | medium (this is the failure class most adjacent to "things outside the descriptor's reach"; partial coverage at best) |
| 10 | service-restart cascade | P5 | snapshot before restart, post-restart verify, rollback if drift | high |
| 11 | conf-file links established but no signal | P5 | post-apply probes assert detection; rollback on not_detected | very high |

**Coverage:** 9 of 11 are caught at high+ confidence. #6 depends on operator declaring hardware bleed
characteristics in the descriptor (the model SURFACES the missing data — but the operator must populate
it; this is a known step-function reduction in expected value once measured). #9 is partial — codec
profile/pin state lives partly in `hda-verb` invocations and `WirePlumber` rules; the descriptor can
model what reaches PipeWire, but the kernel codec layer below is partially out-of-band.

## Failure modes that escape this architecture

These are the residual failure classes the operator should be aware of:

1. **Kernel codec / driver state.** The HD-audio pin mux state lives in the kernel and is partially
   visible to PipeWire as profile changes. A pin glitch (today's `pin-check` watchdog handles a known
   subset) can mute the analog jack without any PipeWire-visible event. Mitigation: the existing
   `hapax-audio-topology pin-check` + watchdog stays in the loop; the daemon invokes it on apply.
2. **USB bandwidth / scheduling.** The L-12, S-4, M8, BRIO cameras all share USB host controller
   bandwidth. The daemon does not model USB — a bandwidth exhaustion shows as a probe failure (which
   triggers rollback) but the cause is invisible to it.
3. **PipeWire / WirePlumber bugs.** A bug in libpipewire's filter-chain implementation (e.g. the
   `apply_via_pactl_load` empirical finding) is captured as a per-loopback opt-in flag, not as an
   invariant. New bugs in different module types would require descriptor-schema additions.
4. **External processes ignoring the lock.** `pactl load-module` from any process bypasses the file-lock
   gate (the lock guards `~/.config/`, not pactl). Mitigation: P4 transitions all daemon-known pactl
   loads into the manifest; rogue pactl loads land as drift in `verify_live()` and ntfy fire.
5. **Operator-driven analog patching** (e.g. the Cortado MKIII XLR cable, the L-12 channel trims).
   The descriptor captures the *expected* hardware — a misplugged cable produces a probe failure
   (which rollback cannot fix because the prior state is the same misplugged state). Mitigation: this
   is a correct surfacing — the breaker engages safe-mute and the operator is notified; the system
   stays silent until the cable is fixed.

## Where the architecture deliberately does NOT promise prevention

- **Operator deliberately edits the descriptor with a violation.** P1's pre-apply check refuses, so the
  operator can't apply such a descriptor. But if the operator then runs `HAPAX_PIPEWIRE_GRAPH_BYPASS=1`,
  the system trusts them; ntfy fires red but the apply proceeds. This is the conscious trade-off
  between "a system the operator can override in an emergency" and "a system that makes itself
  inviolable" — operator-sovereign-by-default wins, and the bypass is auditable.
- **Drift inside the daemon's own state.** If the daemon's `current.yaml` falls out of sync with the
  filesystem (e.g. someone manually edited a manifested conf and bypassed the lock), `verify_live()`
  surfaces the drift, but the daemon does not auto-repair. It refuses the next apply until drift is
  resolved (ntfy + maintenance card). The operator does the reconcile.
- **CPU contention causing parec / pw-cat hangs during probes.** The breaker has a 0.5 s window with
  graceful degradation (treats hang as a probe-failure → conservative rollback). If the system is so
  loaded that probes can't run at all, the system enters a known-degraded state and stays on the last
  nominal snapshot.

## The aesthetic claim

"One time forever" is too strong. The honest claim is "one well-defined boundary, after which the only
remaining failure modes are explicit hardware/kernel-layer events that this architecture surfaces but
cannot prevent." The audio churn between sessions and operator-aimed at level tuning ends. The hardware
+ kernel envelope of remaining failures is finite, observable, and not the operator's daily problem.

---

# §8. Open questions for operator review

(Spec ships even with these open; they affect Phase 4 / 5 timing.)

1. **Bypass envvar policy.** `HAPAX_PIPEWIRE_GRAPH_BYPASS=1` should it be operator-only, or session-author-only?
   Recommendation: any caller can set it, but it's logged with the calling process's executable path and
   ntfy fires red. The operator is the only one who would intentionally set it.
2. **Manifest scope.** Phase 4 asks: which confs are "manifested"? The conservative answer is "everything
   in `config/audio-topology.yaml` plus its compiled outputs." But three operator-edited confs today
   (`10-voice-quantum.conf`, `99-hapax-quantum.conf`, `s4-usb-sink.conf`) are quantum/profile knobs that
   may want to stay operator-owned. Recommendation: those become first-class descriptor fields
   (`schema_version=4`) so they're in the manifest but typed as "global tunables".
3. **Rollback after operator-explicit bypass.** If the operator bypasses and then a failure occurs, does
   the breaker still try to roll back? Recommendation: yes — rollback to the last *nominal* snapshot
   regardless of how the current state was applied. The bypass is a one-shot, not a sticky flag.
4. **Phase order.** Should P3 (lock) ship before P2 (shadow daemon)? Recommendation: NO. The shadow daemon
   informs the manifest scope, and shipping the lock without a daemon to coordinate against would just
   block all edits. P2 → P3 → P4 in that order.

5. **H5 hardware-as-sum (L-12 hardware bus replaces software broadcast chain).** Per the research doc §1.5,
   the most aggressive structural simplification is to retire the four-stage software broadcast chain
   (`broadcast-master` → `broadcast-normalized` → `obs-broadcast-remap` → `livestream-tap`) and let the
   L-12 hardware mixer do the sum. PipeWire becomes a per-source pre-processor only. This is OUT OF
   SCOPE for this spec — but the daemon architecture proposed here is COMPATIBLE with it: an H5 future
   migration would be expressed as a descriptor update (most software broadcast nodes deleted; OBS
   capture target moves to L-12 USB IN main-mix slot) and applied through the same daemon. Recommendation:
   ship P0–P5 as designed; revisit H5 after P5 has been live ≥ 30 days, on the basis of "is the residual
   software-broadcast-chain failure rate still operator-perceivable, or has the architecture absorbed
   it?" The research doc's argument-for ("six P0s in one session") would no longer apply post-P5; the
   argument-for would shift to "stimmung-driven gain rides are routed elsewhere; PipeWire summing adds
   no value over hardware summing".

6. **Threshold-reconciliation between this spec and the research doc's H1 predicates.** §4.2.1 ships
   BOTH predicate forms in parallel; P2's 24 h shadow window decides which one(s) survive into P4. Open
   for operator input on whether parallel predicates is acceptable, or whether to choose one before P2.

7. **CLI naming reconciliation (G-spec-5 — 2026-05-03 alignment audit).** The audit
   surfaced a naming ambiguity between `scripts/hapax-audio-topology` (existing,
   1100 LOC) and `scripts/hapax-pipewire-graph` (new in P3). **Resolution: two
   distinct binaries, distinct surfaces.** `hapax-audio-topology` stays the
   read/diff/audit CLI for the descriptor-vs-runtime delta (it is tested,
   documented, and operator-known). `hapax-pipewire-graph` is the new
   write/lock/apply CLI for the daemon. P3 ships the new binary as
   `scripts/hapax-pipewire-graph`; the existing CLI keeps its surface
   unchanged. P1 ships a third, narrower CLI `scripts/hapax-audio-graph-validate`
   as the read-only pre-P3 validator (no daemon dependency, JSON output,
   CI-runnable). Operator runs whichever the immediate task needs:
   - `hapax-audio-topology verify`     — diff descriptor vs live `pw-dump`
   - `hapax-audio-graph-validate`      — passive schema decomposition + invariants (P1)
   - `hapax-pipewire-graph apply`       — daemon-mediated apply (P3+)

8. **`config/pipewire/` post-P4 status (G-11 — 2026-05-03 alignment audit).**
   Resolved in §5 Phase 4 step 6 above: `config/pipewire/` becomes a frozen
   legacy snapshot post-P4. The deployed `~/.config/pipewire/...` is
   daemon-owned; the in-tree `config/` copy stays for git-history review only.

9. **Acknowledged-punt: ALSA card pin / kernel codec state (G-17 — 2026-05-03
   alignment audit).** Per §7 #9 + §7 residual-failure #1, the kernel-side
   HD-audio pin mux state is partially out-of-band for the descriptor. The
   schema can model the *user-space configurable* part (card profile pin via
   WirePlumber rule, surfaced as :class:`AlsaProfilePin` in P1's audio_graph
   module) but cannot model the kernel codec layer below. P1 includes
   `AlsaProfilePin` (gap G-2 fold) — that's the user-space surface. The kernel
   codec layer stays out of scope; the existing `hapax-audio-topology
   pin-check` watchdog handles the runtime detection side, and the daemon's
   continuous breaker catches the audible failure post-hoc. Recommendation
   (deferred to a Phase 6 tracking note): if a kernel-side codec API surfaces
   that lets us declaratively pin the pin mux state, revisit. Until then,
   acknowledge the gap explicitly here rather than promise coverage we
   cannot deliver.

---

# §9. References to existing assets re-used (not re-authored)

| Asset | Role in this design |
|---|---|
| `shared/audio_topology.py` | Pydantic schema (Node, Edge, ChannelMap, TopologyDescriptor) — reused unchanged. |
| `shared/audio_topology_generator.py` | `generate_confs()` becomes an internal function called by `compile_descriptor()`. |
| `shared/audio_topology_inspector.py` | All `check_*` functions become `BroadcastInvariant` checker implementations. |
| `shared/audio_topology_switcher.py` | Folded into the daemon's `apply()` entry-point. |
| `agents/broadcast_audio_health_producer/producer.py` | The `_default_inject` / `_default_capture` / FFT detector primitives drive both the §4.2 circuit breaker and the §3 PostApplyProbe. |
| `scripts/hapax-audio-topology` | Stays as a CLI; subcommands `apply`/`lock`/`current` added (replaces today's `switch`). |
| `scripts/audio-leak-guard.sh` | Folded into the PRIVATE_NEVER_BROADCASTS checker. |
| `~/.local/bin/hapax-obs-monitor-load` | Pattern lifted into `PactlLoad` artefact emission; script deprecated in P4. |
| `config/audio-topology.yaml` | Becomes generative — every conf and pactl-load is derived from it. |

The implementation budget for the daemon is therefore much smaller than a greenfield design: the
schema, generator, inspector, and probe primitives all exist. The new code is the apply transaction
(snapshot+lock+rollback), the circuit breaker thread, the safe-mute rail, the WirePlumber emitter,
and the edit hook. Estimated 1 500–2 000 LOC across the daemon + tests.

---

# §10. Summary

Five concurrent writers, no schema, no transactions, and an invariant ("private never broadcasts") that
is enforced post hoc by a script that's checked manually by a 24-h auditor. The architecture proposed
here turns the audio graph into a database with a schema, a single applier, a transaction lock, and an
egress invariant continuously enforced by a circuit breaker that respects the operator's only two
unacceptable failure modes (clipping noise, silence) while ignoring the noise of legitimate restarts and
brief gaps.

After P5, the audio graph stops being a thing the operator and Claude tune from above. It becomes a
declarative artefact whose well-formedness is verified at every edit and whose egress safety is verified
at 2 Hz on the live broadcast monitor. The 30-minute failure cadence ends — not by virtue of better
tuning, but because the configuration space the operator and sessions can navigate is restricted to
states the system has proven to be safe.
