# R-16 audit: langfuse-instrumented-qdrant + logos runner/probe wire status

**Authored:** 2026-04-26 by epsilon
**Audit row:** `langfuse-instrumented-qdrant-wire-or-delete` (WSJF 6.0)
**Posture:** audit-before-fix per absence-bug epic
**Source synthesis:** `~/.cache/hapax/relay/research/2026-04-26-absence-bugs-synthesis-for-beta.md`

## TL;DR

R-16 bundles three unrelated symbols under one ticket: `InstrumentedQdrantClient`,
`MicroProbeEngine`, `AgentRunner`. Each is **substantive substrate**
(real implementation, not stubs) with zero prod call sites. Audit
recommends **WIRE** for all three — they are pre-shipped infrastructure
waiting for an orchestrator entry point, not dead code that should be
deleted. The architectural cost of re-creating any of them after delete
exceeds the carrying cost of leaving them in place.

Decision is deferred to the `logos/` lane owner (alpha) per session
boundaries; this doc surfaces the structural analysis so the wire-or-
delete call can be made on context, not on grep counts.

## Symbols inventory

| Symbol | Defined at | Prod refs (excl. self+tests) | Tests | Implementation size |
|---|---|---:|---:|---|
| `InstrumentedQdrantClient` | `shared/config.py:238` | 0 | (none) | ~40 LOC, FlowEvent emission wrapper |
| `MicroProbeEngine` | `logos/micro_probes.py:154` | 0 | (none) | ~150 LOC, profile-gap-driven probe selection w/ persistence |
| `AgentRunner` | `logos/runner.py:23` | 0 | (none) | ~80 LOC, async subprocess lifecycle w/ output streaming |

## Per-symbol analysis

### `InstrumentedQdrantClient`

Wraps a `QdrantClient` and emits `FlowEvent` objects on `search()` /
`upsert()` calls so Logos's flow-bus can observe Qdrant traffic per
caller. The wrapper is correctly structured (uses `__getattr__` for
pass-through) but the existing `_get_qdrant_*` factories return raw
`QdrantClient` instances, never instrumented.

**Wire path:** factory function (e.g., `get_qdrant(agent_name=...)`)
that wraps the raw client when an `event_bus` is configured. Estimated
30-60 min including a "the wrapper is invoked per Qdrant call" test.

**Delete cost:** loses the FlowEvent observability primitive. If Logos
later wants Qdrant flow visibility, it'd need to be reimplemented from
scratch. Net: WIRE preferred.

### `MicroProbeEngine`

Selects micro-probes (short interview-style questions) based on profile
gaps detected in `logos/data/insight_queries.py`. Has cooldown logic,
asked-set persistence, and ProfileAnalysis-aware prioritisation.

The Logos interview / profile system DOES exist (`logos/interview/`).
The probe engine is the unwired half of a paired system: gaps detected
on one side, probes designed on the other, but no orchestrator selecting
the probe at the right moment.

**Wire path:** plug into the Logos copilot or orientation panel surface
that decides "ask the operator a clarifying question now". Estimated
1-2h, depends on copilot intent surface.

**Delete cost:** ~150 LOC of pre-shipped probe-selection logic gone.
Re-creation would cost 4-6h. Net: WIRE preferred.

### `AgentRunner`

Generic async subprocess runner with line-by-line output streaming and
`RunResult` (exit code, duration, cancelled). Doesn't depend on any
hapax-specific subsystem — it's a utility class.

There ARE prod subprocess runs in the codebase, but they use ad-hoc
`asyncio.create_subprocess` calls inline. `AgentRunner` was
presumably extracted as a reusable pattern but never adopted.

**Wire path:** identify ad-hoc subprocess sites and migrate them, OR
declare AgentRunner the canonical pattern + add docs. 1-2h migration
across a few call sites; 15 min for a docstring-only "canonical
pattern" decision.

**Delete cost:** small (~80 LOC); the inline patterns work fine.

## Recommendation

**Wire** `InstrumentedQdrantClient` and `MicroProbeEngine`. **Either
wire or delete** `AgentRunner` — both are reasonable.

Wiring all three is ≤4h total; deleting is ~30 min but loses substantive
infrastructure. The audit's "wire-or-delete" framing implies these are
roughly equivalent; the actual asymmetry favours wire.

## Out-of-lane note

R-16 lives in `logos/` (alpha's primary lane). Epsilon (this audit's
author) routed R-16 through beta's loadup-stack-epsilon inflection
("ship if alpha defers"). Alpha shipped #1652 (B1 P0 #29 cleanup) and
#1658 (R-7 audit + B1 P0 #16-20 langfuse cleanup) but has not picked
up R-16 yet. This audit doc lands the structural case so alpha (or
whoever picks up next) acts on context, not grep.

## Out of scope

- Actual wiring (each symbol's wire-PR is its own ticket)
- Decision on `AgentRunner` wire-vs-delete

## Cross-references

- Synthesis: `~/.cache/hapax/relay/research/2026-04-26-absence-bugs-synthesis-for-beta.md` § R-16
- Inflection: `~/.cache/hapax/relay/inflections/20260426T190500Z-beta-rte-loadup-stack-epsilon.md`
- Pattern precedent: alpha's R-7 audit doc (`docs/research/2026-04-26-r7-governance-gate-audit.md`)
- Companion: epsilon's R-5 wire-status registry (#1650 merged) — different mechanism (registry per symbol) for the same wire-or-delete-decision shape
