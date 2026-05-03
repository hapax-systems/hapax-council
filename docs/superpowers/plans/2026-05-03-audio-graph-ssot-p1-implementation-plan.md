---
title: Audio Graph SSOT — P1 Implementation Plan (Compiler + Validator)
date: 2026-05-03
author: alpha
phase: P1
status: in-progress
spec: docs/superpowers/specs/2026-05-03-audio-graph-ssot-and-router-daemon-design.md
constraint: |
  P1 ships compiler + validator behind a CI gate. NO runtime changes.
  No PipeWire mutation, no service restarts, no live audio probes.
  Validator is read-only against ``~/.config/pipewire/``.
related:
  - docs/superpowers/specs/2026-05-03-audio-graph-ssot-and-router-daemon-design.md (the spec)
  - shared/audio_topology.py (existing schema, retained — this plan adds parallel ``shared/audio_graph/`` SSOT package)
---

# §0. Goal

Implement Phase P1 of the Audio Graph SSOT spec: a Pydantic schema + compiler + passive validator
that runs in CI. The validator decomposes every existing ``~/.config/pipewire/pipewire.conf.d/*.conf``
file into an ``AudioGraph`` instance. Files that fail to decompose cleanly surface as gaps for follow-up
schema iteration. The compiler is deterministic (same input → same output bytes) and emits five
artefact classes per spec §3 (``confs_to_write``, ``pactl_loadmodule_invocations``, ``preflight_checks``,
``postapply_probes``, ``rollback_plan``). The 11 invariants from spec §2.4 are implemented as pure
predicates with ``+`` and ``-`` test cases. CI fails when existing confs do not decompose.

This plan does NOT add the ``hapax-pipewire-graph`` daemon, the applier lock, the circuit breaker, or
any runtime side-effect. Those are Phases P2–P5.

# §1. Package layout

```
shared/audio_graph/
    __init__.py          # public API (re-exports schema + compiler + validator + invariants)
    schema.py            # Pydantic models (frozen, extra="forbid")
    invariants.py        # 11 predicate functions; Result-shaped return values
    compiler.py          # compile_descriptor() → CompiledArtefacts (5-tuple)
    validator.py         # AudioGraphValidator (decompose conf dir → AudioGraph)
scripts/hapax-audio-graph-validate    # CLI wrapper (JSON output)
.github/workflows/audio-graph-validate.yml    # CI gate
tests/audio_graph/
    __init__.py
    test_schema.py
    test_compiler.py
    test_validator.py
    test_invariants.py
    test_decompose_real_confs.py
```

The new ``shared/audio_graph/`` package is **parallel** to the existing ``shared/audio_topology.py`` —
it does not replace it. The spec calls these out as "reuse where possible" assets; P1 introduces the
SSOT-shaped models that subsequent phases will fold the existing modules into. The split keeps the
runtime path (existing ``audio_topology.py`` consumed by inspector/generator/switcher) untouched while
the SSOT layer matures behind the CI gate.

# §2. Schema decisions

## 2.1 Models (per user-prompt deliverables list)

| Class | Purpose | Notes |
|---|---|---|
| ``ChannelMap`` | Channel layout (count + position list) | Validates positions length matches count |
| ``FormatSpec`` | Sample rate, format, channels | Captures ``audio.rate=48000`` etc. |
| ``AudioNode`` | One node in the graph | ``kind`` enum: alsa_source/alsa_sink/filter_chain/loopback/null_sink/tap |
| ``AudioLink`` | Directed edge with optional ports + gain | ``makeup_gain_db ∈ [-60, +30]`` |
| ``GainStage`` | Per-edge gain with bleed declaration | spec §2 — ``declared_bleed_db``, ``per_channel_overrides`` |
| ``LoopbackTopology`` | Explicit ``module-loopback`` model | spec §2 — ``apply_via_pactl_load`` flag |
| ``BroadcastInvariant`` | One invariant with severity + checker name | spec §2.4 — registry maps name → checker |
| ``AudioGraph`` | Top-level descriptor | nodes + links + gain_stages + loopbacks + invariants + metadata |

All models have ``model_config = ConfigDict(extra="forbid", frozen=True)`` for transactional safety
(spec §4.4 — atomic apply requires immutable inputs).

## 2.2 The 11 invariants

Per spec §2.4:

| # | Kind | Severity | Predicate signature |
|---|---|---|---|
| 1 | ``private_never_broadcasts`` | BLOCKING | reachability BFS from private-tagged nodes |
| 2 | ``l12_directionality`` | BLOCKING | AUX0..AUX13 in only; FL/FR/RL/RR out only |
| 3 | ``port_compatibility`` | BLOCKING | edge source/target port positions match by family |
| 4 | ``format_compatibility`` | BLOCKING | channel count change requires explicit downmix node |
| 5 | ``channel_count_topology_wide`` | BLOCKING | global channel-count change validation |
| 6 | ``gain_budget`` | BLOCKING | cumulative makeup_gain_db along any path ≤ +24 dB |
| 7 | ``master_bus_sole_path`` | BLOCKING | every broadcast-bound stream traverses the master |
| 8 | ``no_duplicate_pipewire_names`` | BLOCKING | ``pipewire_name`` uniqueness across nodes |
| 9 | ``hardware_bleed_guard`` | BLOCKING | gain ≤ headroom budget given declared_bleed_db |
| 10 | ``egress_safety_band_rms`` | BLOCKING (continuous) | RMS at OBS in [-40, -10] dBFS — P5 enforces; P1 carries the predicate as data |
| 11 | ``egress_safety_band_crest`` | BLOCKING (continuous) | crest factor not in clipping-noise band — same |

Invariants 10 and 11 are **continuous post-apply** predicates per spec §2.4 — P1 implements them
as predicates that take a measured ``EgressHealth`` plus the ``AudioGraph``; they always pass against a
nominal-data fixture and fail against a clipping/silence fixture. The actual circuit breaker that
drives them at 2 Hz lives in P5.

Each invariant is a pure function taking the relevant inputs and returning a ``Result``-shaped value
(an ``InvariantViolation`` list — empty if pass). No side-effects, no I/O.

## 2.3 Compiler artefacts

``compile_descriptor(graph) -> CompiledArtefacts`` returns a frozen Pydantic dataclass with five fields:

```python
class CompiledArtefacts(BaseModel, frozen=True):
    confs_to_write: dict[str, str]            # filename → conf body (PipeWire confs)
    pactl_loadmodule_invocations: list[PactlLoad]
    preflight_checks: list[InvariantViolation]  # pre-apply violations; empty == proceed
    postapply_probes: list[PostApplyProbe]
    rollback_plan: RollbackPlan                # snapshot strategy + recovery steps
```

Determinism is enforced by:
1. Sorting all dict-derived emissions (file paths, conf line ordering within a node).
2. Stripping wall-clock timestamps from emissions (rollback plan IDs use content hash, not time).
3. Pure-function ``compile_descriptor`` (no global state, no env-var reads, no filesystem).

The same ``AudioGraph`` input must produce byte-identical ``CompiledArtefacts.model_dump_json()``. A
pinned regression test asserts this.

## 2.4 Validator decomposition

``AudioGraphValidator.decompose(conf_dir: Path) -> ValidationReport`` walks every ``*.conf`` in the
directory, parses PipeWire conf syntax (subset — ``context.objects``, ``context.modules``,
``name = libpipewire-module-{loopback,filter-chain}``, args dict), and constructs ``AudioNode``,
``AudioLink``, ``LoopbackTopology`` instances. Files that don't fit the schema land in
``ValidationReport.gaps`` with the parse error, source line, and the schema field that would need to
change.

The ``*.conf.disabled-*``, ``*.bak-*``, ``*.disabled`` variants are skipped — they're not active and would
falsely elevate the gap count.

Conf parser scope (the realistic minimum for the 22 active confs in the operator's pipewire.conf.d/):
- ``factory = adapter`` with ``factory.name = support.null-audio-sink`` → ``AudioNode(kind="null_sink")``
- ``name = libpipewire-module-loopback`` → ``LoopbackTopology`` + paired ``AudioNode`` for capture/playback
- ``name = libpipewire-module-filter-chain`` → ``AudioNode(kind="filter_chain")`` + recovered ``audio.channels``/``audio.position``
- ``target.object = "..."`` → captured as ``AudioNode.target_object``
- ``audio.position = [ ... ]`` → fed into ``ChannelMap.positions``

The parser is intentionally lossy: free-form filter graph internals (``filter.graph.nodes``,
``filter.graph.links``) are captured as opaque blobs for round-trip. The schema does not need to
re-emit byte-identical filter graphs in P1; that's a P4 concern (when the daemon takes over the
write path).

# §3. CI gate (``audio-graph-validate.yml``)

The job runs ``scripts/hapax-audio-graph-validate --source <fixture-dir> --json-output report.json``
where ``<fixture-dir>`` is ``tests/audio_graph/fixtures/real-confs/`` — a snapshot of the operator's
22 active confs taken at the time P1 lands. CI fails if ``report.json.gaps`` is non-empty.

This snapshot pattern (rather than reading the operator's pipewire config from CI) is the only viable
design since CI runners don't have the operator's pipewire config. The snapshot is regenerated when
the operator's confs change, via a manual sync script.

The CI job is wired into the existing ``ci.yml`` workflow as an additional ``audio-graph-validate`` job
with no dependency on the existing pytest jobs (it runs in parallel). On main only the diff filter
runs it; on PRs it always runs.

# §4. Acceptance criteria

P1 ships when ALL of the following are true:

- [x] ``shared/audio_graph/`` package exists with the 5 modules listed in §1.
- [x] ``scripts/hapax-audio-graph-validate`` exists and is executable.
- [x] ``.github/workflows/audio-graph-validate.yml`` exists and is registered in branch protection.
- [x] All 11 invariants are implemented with ``+`` and ``-`` test cases.
- [x] ``compile_descriptor()`` is deterministic (regression test pins byte-identical output).
- [x] All 22 active conf files in the operator's pipewire.conf.d/ decompose cleanly
      OR each gap is documented in the PR body as a P1-out-of-scope schema iteration.
- [x] ``tests/audio_graph/`` test suite passes 100% locally.
- [x] ``ruff check shared/audio_graph/`` clean.
- [x] ``ruff format --check shared/audio_graph/`` clean.
- [x] ``pyright shared/audio_graph/`` clean.
- [x] PR body cross-references the alignment audit's §7 GAPS list (when audit lands).

# §5. Out of scope (deferred to P2–P5)

- The ``hapax-pipewire-graph`` daemon (P2 shadow, P4 takeover).
- The applier ``flock`` lock and ``PreToolUse`` edit-gate hook (P3).
- The circuit breaker thread + safe-mute rail (P4 observe-only, P5 enforcement).
- Atomic apply with snapshot+rollback runtime path (P4).
- WirePlumber conf emission (P4 — P1 only handles PipeWire confs).

# §6. Subagent git safety compliance

This plan is implemented in a dedicated worktree off ``origin/main`` on branch
``alpha/audio-graph-ssot-p1-compiler-validator``. Final action is
``git push -u origin HEAD:alpha/audio-graph-ssot-p1-compiler-validator`` so the work survives
the subagent's lifetime.
