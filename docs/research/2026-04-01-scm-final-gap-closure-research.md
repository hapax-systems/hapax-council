# SCM Final Gap Closure: Research and Design Specifications

**Date:** 2026-04-01
**Status:** Design specifications ready for implementation
**Depends on:** [Honest spec revision](stigmergic-cognitive-mesh.md), [PoC implementations](PR #522)

---

## 1. Fortress-Daimonion Decoupling

### Finding

The governance types (VetoChain, FallbackChain, Candidate, Selected, Veto, VetoResult) are already in `agents/_governance/primitives.py`. The file `agents/hapax_daimonion/governance.py` is a re-export shim. The coupling violation is that all 7 Fortress chain files import from `agents.hapax_daimonion.governance` instead of `agents._governance`.

### Design

Mechanical import path change: 10 files in `agents/fortress/` change their import source from `agents.hapax_daimonion.governance` to `agents._governance`. No behavioral change. ResourceArbiter (zero daimonion dependencies) moves to `agents/_governance/arbiter.py`. SuppressionField needs Behavior — either move Behavior to shared/ or have SuppressionField accept a duck-typed object.

**Effort:** ~2 hours. Mechanical.

---

## 2. Sheaf Health: Honest Rename

### Finding

Current `sheaf_health.py` computes 6 pairwise residuals via RMS — not actual coboundary matrices. Actual coboundary is infeasible because only ~21% of the claimed 168-dim stalk space is reliably populated at runtime. The SVD would measure "which stalks are offline" rather than genuine topological obstructions.

### Design

Rename only (no behavioral change):

| Current | New |
|---------|-----|
| `compute_sheaf_health()` | `compute_restriction_consistency()` |
| `consistency_radius` | `restriction_residual_rms` |
| `h1_dimension` | `inconsistent_edge_count` |
| Module docstring | "Restriction map consistency monitor" |

Keep Robinson (2017) reference but note: "Inspired by sheaf consistency radius, without full coboundary computation."

**Effort:** ~30 minutes. Documentation.

---

## 3. Consent Ingestion Gate

### Finding

14 egress gates exist but 0 ingestion gates. Person-adjacent data from IR cameras enters the system through `logos/api/routes/pi.py` → state files → perception backends with no consent check. The consent state tracker already detects guests. The perception state writer already curtails person-adjacent fields at the /dev/shm write boundary. What's missing is filtering at the behavior level before EnvironmentState construction.

### Design

New `ConsentIngestionFilter` in `agents/hapax_daimonion/consent_filter.py`:
- 15 person-adjacent behavior names defined in PERSON_ADJACENT_BEHAVIORS frozenset
- Applied in PerceptionEngine.tick() after backend contributions, before EnvironmentState
- Phase-gated: NO_GUEST and CONSENT_GRANTED → pass through; all others → suppress person-adjacent behaviors
- `ir_person_detected` flows unconditionally (tracker needs it for state transitions)
- Audio capture continues regardless (VAD needed); output suppression at speaker_id and speech_emotion levels

**Effort:** ~1 day. Requires perception engine modification.

---

## 4. Control Laws for All 14 Components

### Finding

The control law research produced specifications for all 14 components with:
- Asymmetric hysteresis (3:5 — degrade after 3 error ticks, recover after 5 ok ticks)
- Three degradation levels (mild, moderate, severe)
- Safe corrective actions that prevent cascading failures
- Escalation paths

Full specifications in `docs/research/2026-03-31-scm-control-law-specifications.md`.

### Design Summary

| Component | Controlled variable | Corrective action (mild) | Corrective action (severe) |
|-----------|-------------------|--------------------------|---------------------------|
| IR Perception | Pi freshness ratio | Request retransmission | Fall back to single-Pi mode |
| Contact Mic | Audio buffer occupancy | Increase buffer | Disable onset detection |
| Voice Daemon | Backend freshness ratio | Skip stale backends | Reduce to FAST-only |
| DMN Pulse | Ollama response success | Increase tick interval | Switch to cached observations |
| Imagination | Tick success rate | Double cadence (IMPLEMENTED) | Pause entirely |
| Content Resolver | Resolution success rate | Increase skip-until duration | Disable non-text resolution |
| Stimmung | Dimension freshness | Force cautious stance | Force critical + notify |
| Temporal Bonds | Ring occupancy | Reduce retention depth | Return empty bands |
| Apperception | Coherence | Increase trigger sensitivity | Gate all non-correction sources |
| Reactive Engine | Rule success rate | Disable Phase 2 rules | Disable Phase 1 (GPU) rules |
| Compositor | Camera availability | Reduce tiling layout | Fall back to single camera |
| Reverie | Frame production rate | Simplify shader pipeline | Fall back to solid color |
| Voice Pipeline | ASR confidence | Increase silence threshold | Disable wake word, hotkey only |
| Consent Engine | Contract load success | Force cautious stance | Force critical + block all person writes |

**Effort:** ~3 days for all 14. Each is a ~30-line control law block added to the component's tick/contribute method.

---

## Implementation Priority

| # | Gap | Effort | Impact |
|---|-----|--------|--------|
| 1 | Fortress decoupling | 2h | P1 → 95% stigmergic |
| 2 | Sheaf honest rename | 30m | Spec integrity |
| 3 | Consent ingestion gate | 1 day | P5 ingestion coverage |
| 4 | 13 more control laws | 3 days | P4 from 1/14 → 14/14 closed loops |
