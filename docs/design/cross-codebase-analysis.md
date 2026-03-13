# Cross-Codebase Analysis: Council and Officium

**Status**: Draft
**Date**: 2026-03-13
**Author**: Operator + Claude

---

## 1. Overview

Three repositories implement the hapax system:

- **constitution** — The spec. Axioms, implications, governance rules, acceptance criteria. No runtime code.
- **council** — Primary implementation. 26+ agents, voice daemon, React dashboard, VS Code extension, 14 systemd timers, OpenTelemetry tracing. Domain: executive function infrastructure for a single operator.
- **officium** — Secondary implementation. Management-practice domain. Reactive engine, self-demo capability, temporal simulator. Containerized deployment.

Council and officium share infrastructure (Qdrant, LiteLLM, Ollama, PostgreSQL) on the same host but at different ports to allow co-location. They share ~18 modules in `shared/` with varying degrees of divergence. Some divergence is intentional (different domains). Some is accidental (copy-paste drift). Some represents one repo having a better version the other should adopt.

This document categorizes every shared module, identifies port candidates, and proposes a prioritized action plan.

---

## 2. Methodology

Each shared module is categorized as one of:

| Category | Definition | Action |
|---|---|---|
| **Intentional divergence** | Different by design. Domain-specific adaptations, different port assignments, different model preferences. | Document why. Do not consolidate. |
| **Accidental drift** | Started from the same code, diverged without reason. Minor API differences, missing safety checks, inconsistent env var handling. | Align to the better version. |
| **Port candidate** | One repo has a clearly better version. The other should adopt it. | Port with adaptation. |
| **Consolidation candidate** | Both repos need the same thing. Should be extracted to a shared package (`hapax-sdlc` or new). | Extract and depend. |

---

## 3. Module-by-Module Analysis

### `shared/config.py` — Intentional Divergence

| Aspect | Council | Officium |
|---|---|---|
| Lines | 248 | 195 |
| LiteLLM port | `4000` | `4100` |
| Qdrant port | `6333` | `6433` |
| Ollama port | default (11434) | `11534` (explicit env var) |
| ntfy port | `8090` (in notify.py) | `8190` |
| Data dir | Fixed path constants (17 paths) | Mutable `_Config` class with `set_data_dir()` |
| Model aliases | `fast`=gemini-flash, `reasoning`=qwen3.5:27b | `fast`=claude-haiku, `reasoning`=deepseek-r1:14b |
| OTel tracing | Yes — `_rag_tracer`, spans on embed/embed_batch | No |

**Why intentional**: Port offsets allow both systems to run on the same host without conflicts. Model aliases reflect different cost/quality tradeoffs per domain. Council's 17 path constants serve its broader agent surface.

**Exception — `_Config` pattern**: Officium's `_Config` class with `set_data_dir()` is a port candidate (see below). Council's fixed paths make testing harder — tests must mock individual constants or manipulate environment variables.

### `shared/frontmatter.py` — Port Candidate (Officium → Council)

| Aspect | Council (`vault_utils.py`) | Officium (`frontmatter.py`) |
|---|---|---|
| Lines | 36 | 67 |
| Module name | `vault_utils` | `frontmatter` |
| Parser | Naive string search (`text.find("---", 3)`) | Regex-based (`_FM_RE`) |
| Return type | `dict` (frontmatter only) | `tuple[dict, str]` (frontmatter + body) |
| Body extraction | Not supported | Supported |
| Edge cases | Breaks on `---` in body text | Regex handles correctly |

**Port recommendation**: Adopt officium's `frontmatter.py` as council's canonical parser. The reactive engine needs `(dict, body)` tuples for event enrichment. Council's `vault_utils.py` is insufficient — it can't extract body text and its naive parser breaks on edge cases. CLAUDE.md already references `shared/frontmatter.py` as the canonical parser; the module just doesn't exist yet.

**Migration**: Rename `vault_utils.py` → `frontmatter.py`, adopt regex parser, update return type. Audit callers that expect dict-only returns (likely only need the first element of the tuple).

### `shared/axiom_registry.py` — Intentional Divergence (with one port candidate)

| Aspect | Council | Officium |
|---|---|---|
| Lines | 298 | 239 |
| `SchemaVer` class | Yes (MODEL-REVISION-ADDITION format) | No |
| `ImplicationScope` | Yes (E-1 enumerable scope) | No |
| `supersedes` field | No | Yes |
| Payload null safety | `pt.payload.get(...)` | `(pt.payload or {}).get(...)` — safer |
| AXIOMS_PATH | Env var or relative path | Imports from `config.AXIOMS_DIR` |

**Why intentional**: Council's axiom system is more mature (schema versioning, scoped implications). Officium's is simpler because it doesn't need the same governance depth.

**Port candidate**: Officium's `supersedes` field for axiom renames. Officium's `registry.yaml` has evolved axiom names (`single_user` → `single_operator`, `executive_function` → `decision_support`, `management_governance` → `management_safety`). The `supersedes` field allows the registry to track these renames. Council should adopt this pattern for axiom evolution without breaking existing references.

**Also port**: The `(pt.payload or {}).get(...)` null safety pattern. Council's version will NPE on Qdrant points with null payloads.

### `shared/profile_store.py` — Accidental Drift

| Aspect | Council | Officium |
|---|---|---|
| Lines | 242 | 249 |
| Dimension filtering | All dimensions | Management-only (`MANAGEMENT_DIMENSIONS` frozenset, 6 dims) |
| OTel tracing | Yes (spans on index + search) | No |
| Payload null safety | No | Yes (`pt.payload or {}`) |

**Why drift**: Both query Qdrant `profile-facts`. Council indexes all 11 dimensions (5 trait + 6 behavioral) because it serves the full executive-function domain. Officium filters to 6 management dimensions because that's its domain. This filtering difference is intentional.

**Accidental parts**: The null safety difference is accidental. Council should adopt officium's `(pt.payload or {}).get(...)` pattern.

### `shared/notify.py` — Accidental Drift

| Aspect | Council | Officium |
|---|---|---|
| Lines | 305 | 307 |
| ntfy port | `8090` | `8190` |
| Desktop notification | No display check | Checks `DISPLAY` and `WAYLAND_DISPLAY` env vars |
| Public API | Identical | Identical |

**Port recommendation**: Adopt officium's `DISPLAY`/`WAYLAND_DISPLAY` check. Council runs on a Hyprland desktop so the check currently passes, but it's the right defensive pattern for headless contexts (Docker containers, CI).

### `shared/cycle_mode.py` — Accidental Drift

| Aspect | Council | Officium |
|---|---|---|
| Lines | 27 | 29 |
| Cache dir | Hardcoded `~/.cache/hapax` | `XDG_CACHE_HOME` with fallback |

**Port recommendation**: Adopt officium's XDG Base Directory compliance. Two-line change, zero risk, correct behavior.

### `shared/operator.py` — Intentional Divergence

| Aspect | Council | Officium |
|---|---|---|
| Lines | 264 | 280 |
| System identity | "Externalized executive function" | "Management decision support" |
| Axiom names | `single_user`, `executive_function` | `single_operator`, `decision_support` |
| `get_goals()` | Returns all goals | `management_only: bool = True` kwarg |
| `get_neurocognitive_profile()` | Returns data | Deprecated, returns `{}` |
| Constraint categories | Includes "music" | No "music" |

**Why intentional**: Different domains produce different operator profiles. Council's broader scope includes neurocognitive data and music (ambient audio processing). Officium's management focus narrows the API surface.

### `shared/context_tools.py` — Accidental Drift

| Aspect | Council | Officium |
|---|---|---|
| Lines | 244 | 247 |
| Docstring | "operator context tools" | "management context tools" |
| Categories | Includes "music" | No "music" |

**Minor drift**: Docstring wording and music category reflect domain differences. Not worth aligning — the tools serve different agent populations.

### `shared/dimensions.py` — Council-Only

Council: 147 lines defining 11 dimensions (5 trait + 6 behavioral) with `DimensionDef` dataclass, registry, and `validate_behavioral_write()`.

Officium: No equivalent. Management dimensions are a hardcoded frozenset in `profile_store.py`.

**Assessment**: Council's dimension system is more sophisticated and appropriate for its broader domain. Officium's inline frozenset is sufficient for its narrower scope. No consolidation needed.

### `shared/audit.py` and `shared/sdlc_log.py` — Consolidation Candidate

Both repos have 3-line modules that re-export from `hapax-sdlc`:

```python
from sdlc.audit import *
from sdlc.log import *
```

Council adds a backward-compat `SDLC_LOG` constant. Both delegate to the same external package.

**Assessment**: Already effectively consolidated via `hapax-sdlc`. The re-export wrappers exist for import convenience. Minor: council's extra constant should be removed if unused.

### `shared/embedding.py` / embedding in `config.py` — Accidental Drift

Both repos implement `embed()` and `embed_batch()` in `config.py` (not a separate module). API is functionally identical: call Ollama's `nomic-embed-text-v2-moe` model, return 768-dimensional vectors.

| Aspect | Council | Officium |
|---|---|---|
| OTel tracing | Yes — captures parent span, logs attributes | No |
| Ollama client | `Client(timeout=120)` | `Client(host=OLLAMA_URL, timeout=120)` — supports remote |

**Port recommendation**: Council should adopt officium's `OLLAMA_URL` env var pattern. Currently hardcoded to localhost, which is fine for single-host but fragile.

---

## 4. Council-Only Capabilities

These exist only in council and are not candidates for porting to officium (different domain or architectural scope):

| Capability | Scale | Notes |
|---|---|---|
| Voice daemon | 20+ modules, FRP pipeline | Real-time audio processing, requires GPU/CUDA |
| OpenTelemetry tracing | Instrumented across 25+ agents | Spans in `shared/config.py` + agent modules, Langfuse export |
| Consent system | `shared/consent.py`, 168 lines | `interpersonal_transparency` axiom enforcement |
| Sufficiency probes | `shared/sufficiency_probes.py`, 1151 lines, 40+ probes | Deterministic constitution compliance checks |
| Hooks/scripts | `hooks/`, `scripts/` | Axiom scanning, SDLC pipeline stages |
| Systemd timers | 14 units | Scheduled agent execution |
| council-web | React SPA, Vite, :5173 | Dashboard for all cockpit data |
| VS Code extension | `vscode/` | Chat, RAG, management commands |
| Fix capabilities | `shared/fix_capabilities/` | Docker, Ollama, systemd, filesystem remediation |
| Capability protocols | `shared/capabilities/` | 9 typed protocols with registry |

### What Officium Could Learn

- **Sufficiency probes**: Deterministic compliance checking without LLM calls. Officium relies on hapax-sdlc's axiom judge (LLM-based); probes would add a fast, cheap first pass.
- **Consent system**: If officium ever models non-operator persons (it currently tracks people by name for management purposes), it needs consent contracts.
- **OpenTelemetry**: Council's OTel instrumentation provides end-to-end trace correlation that Langfuse alone cannot. Officium intentionally stripped this — worth revisiting as the system grows.
- **Voice perception architecture**: The FRP pipeline (Behavior/Event, VetoChain, FallbackChain) is a reusable reactive pattern beyond audio. The reactive engine could adopt similar abstractions for rule composition.

---

## 5. Officium-Only Capabilities

| Capability | Scale | Notes |
|---|---|---|
| Reactive engine | 8 modules, ~1,600 lines | **Primary port candidate** — see `docs/design/reactive-engine.md` |
| Self-demo | `demo/`, `demo_pipeline/`, `demo_eval/` | Self-demonstrating capability for stakeholder presentations |
| Temporal simulator | Standalone module | Simulates time-dependent agent behavior |
| `_Config` pattern | In `config.py` | Mutable data dir for testing |
| `supersedes` field | In axiom registry | Axiom rename tracking |
| Containerized deployment | Docker Compose only | No systemd dependency |

### What Council Could Learn

- **Reactive engine**: Primary gap. Design documented separately.
- **`_Config` pattern**: Council tests currently mock individual path constants or set env vars. A mutable config object with `set_data_dir()` would simplify test setup significantly. Small, low-risk port.
- **`supersedes` for axioms**: Council's axiom names are stable today but will evolve. Having rename tracking avoids breaking references in implications, precedents, and audit logs.
- **Self-demo**: Council has a `demos.py` route but no pipeline for generating, running, and evaluating demos end-to-end. Lower priority — council's dashboard serves most demonstration needs.

---

## 6. Infrastructure Divergences

### Port Assignments

| Service | Council | Officium | Offset |
|---|---|---|---|
| LiteLLM | 4000 | 4100 | +100 |
| Qdrant | 6333 | 6433 | +100 |
| ntfy | 8090 | 8190 | +100 |
| Ollama | 11434 (default) | 11534 | +100 |
| Cockpit API | 8051 | 8051 | same |

The +100 offset pattern is intentional, allowing both systems on the same host. Cockpit API sharing port 8051 works because only one runs at a time (they serve different dashboards).

**Decision**: Do not consolidate ports. Document the offset convention.

### Deployment Model

| Aspect | Council | Officium |
|---|---|---|
| Agent execution | Systemd timers + CLI | Docker Compose |
| Process model | One-shot services | Long-running containers |
| GPU access | Host-native (systemd) | Not needed (no voice) |
| Secrets | `pass` + `direnv` | `pass` + Docker env |
| Lifecycle | `systemctl --user` | `docker compose` |

**Decision**: Different deployment models suit different needs. Council needs host-native GPU access for voice/audio. Officium's containerization works for its LLM-only workload. Do not consolidate.

### Tracing

| Aspect | Council | Officium |
|---|---|---|
| OpenTelemetry | Yes (25+ agents instrumented) | No (intentionally stripped) |
| Langfuse | Yes (LLM observability) | Yes (LLM observability) |
| Trace correlation | OTel trace IDs → Langfuse | Langfuse trace IDs only |

**Decision**: Council's OTel investment is justified by its larger agent surface and voice pipeline. Officium's Langfuse-only approach is simpler and sufficient for its scope. Document the difference, don't force alignment.

### Axiom Evolution

| Axiom | Council | Officium |
|---|---|---|
| single_user / single_operator | `single_user` (weight 100) | `single_operator` (weight 100, supersedes `single_user`) |
| executive_function / decision_support | `executive_function` (weight 95) | `decision_support` (weight 95, supersedes `executive_function`) |
| corporate_boundary | Active | Dormant |
| management_governance / management_safety | `management_governance` (weight 85, domain) | `management_safety` (weight 95, constitutional, supersedes `management_governance`) |
| interpersonal_transparency | Present (weight 88, constitutional) | Absent |
| Schema version | `1-0-0` | Not present |
| Registry version | 2 | 3 |

Officium's axioms have evolved: renamed for clarity, promoted `management_safety` from domain to constitutional weight, made `corporate_boundary` dormant. Council's axioms are stable but behind.

**Decision**: Council should adopt the `supersedes` mechanism but not necessarily the name changes. Council's axiom names (`single_user`, `executive_function`) are referenced throughout hooks, probes, implications, and audit logs. Renaming requires coordinated migration. The `supersedes` field lets officium track the rename history; council can use it when it's ready to evolve.

---

## 7. Prioritized Action Plan

| Priority | Action | Category | Effort | Impact | Risk |
|---|---|---|---|---|---|
| 1 | Port reactive engine to council | Port | Large | Closes primary constitution gap. Enables file-change reactivity for all 7 watch surfaces. | Medium — new subsystem, needs thorough testing |
| 2 | Port `frontmatter.py` from officium | Port | Small | Replaces naive parser, enables `(dict, body)` tuples for engine events. Prerequisite for reactive engine. | Low — drop-in replacement with minor caller updates |
| 3 | Port `_Config` pattern to council | Port | Small | Mutable data dir for testing. Eliminates per-constant mocking in 2700+ tests. | Low — additive change, existing API preserved |
| 4 | Align `cycle_mode.py` (XDG compliance) | Drift fix | Trivial | Correct behavior on non-standard XDG setups. | None |
| 5 | Align `notify.py` (display check) | Drift fix | Trivial | Defensive for headless contexts. | None |
| 6 | Add null safety to `profile_store.py`, `axiom_registry.py` | Drift fix | Trivial | Prevents NPE on Qdrant points with null payloads. | None |
| 7 | Adopt `OLLAMA_URL` env var in `config.py` | Drift fix | Trivial | Supports remote Ollama if needed. | None |
| 8 | Port `supersedes` support to axiom registry | Port | Small | Enables axiom evolution without breaking references. | Low |
| 9 | Extract `sdlc_log.py` to hapax-sdlc | Consolidation | Medium | Single JSONL schema for pipeline events across repos. | Low — already re-exporting |

### Dependency Graph

```
frontmatter.py port (P2)
        ↓
reactive engine port (P1)
        ↓
cockpit API integration (part of P1)

_Config pattern (P3) → independent
cycle_mode / notify / null safety (P4-P7) → independent, can batch
supersedes support (P8) → independent
sdlc_log extraction (P9) → independent
```

Priorities 2–7 can proceed in parallel. Priority 1 depends on priority 2 (frontmatter parser).

---

## 8. What Each Can Learn From the Other

### Council → Officium

| Capability | Value to Officium | Effort |
|---|---|---|
| Sufficiency probes | Fast, deterministic compliance checking without LLM calls. First-pass filter before axiom judge. | Medium — probes are domain-specific, need rewriting |
| Consent system | Required if officium ever persists non-operator person state (it currently names people in management contexts). | Medium — needs axiom + contract infrastructure |
| OpenTelemetry | End-to-end trace correlation across agent invocations. Currently Langfuse-only. | Medium — instrumentation across all agents |
| Voice/FRP architecture | Reusable reactive patterns (Behavior/Event, VetoChain) beyond audio domain. | Large — architectural adoption |
| Schema versioning | `SchemaVer` class for axiom registry evolution tracking. | Small |
| Capability protocols | Typed capability abstraction with health checks and remediation. | Medium |

### Officium → Council

| Capability | Value to Council | Effort |
|---|---|---|
| Reactive engine | Primary constitution gap. File-change reactivity for filesystem-as-bus. | Large — see `reactive-engine.md` |
| `_Config` pattern | Testability: mutable data dir eliminates per-constant mocking. | Small |
| `supersedes` field | Axiom evolution without breaking 40+ probes and audit references. | Small |
| Self-demo pipeline | Stakeholder demonstrations with automated evaluation. | Medium |
| Temporal simulator | Testing time-dependent agent behavior without waiting. | Medium |
| Display check in notify | Defensive pattern for headless contexts. | Trivial |
| XDG compliance | Correct cache dir resolution. | Trivial |

---

## 9. Decision Log

Decisions recorded here to prevent future re-analysis of intentional divergences.

### D1: Port offsets (+100) are intentional

**Context**: Council uses ports 4000/6333/8090, officium uses 4100/6433/8190.
**Decision**: Keep separate. Both systems run on the same physical host. Port conflicts would require separate VMs or containers with port mapping.
**Date**: 2026-03-13

### D2: Model aliases differ by design

**Context**: Council's `fast` = gemini-flash; officium's `fast` = claude-haiku.
**Decision**: Keep separate. Each system optimizes for its domain's cost/quality tradeoff. Council uses more Gemini (cheaper for high-volume executive-function work). Officium uses more Claude (higher quality for management-sensitive work).
**Date**: 2026-03-13

### D3: Council keeps all 11 dimensions; officium filters to 6

**Context**: Council's `profile_store.py` indexes all dimensions. Officium filters to `MANAGEMENT_DIMENSIONS`.
**Decision**: Keep separate. Council's executive-function scope requires trait dimensions (openness, conscientiousness, etc.) that officium's management scope does not.
**Date**: 2026-03-13

### D4: Council keeps neurocognitive profile; officium deprecated it

**Context**: Council's `operator.py` returns neurocognitive data. Officium returns `{}` with deprecation note.
**Decision**: Keep separate. Council uses neurocognitive data for voice daemon accommodation and ambient processing. Officium baked it into axiom implications instead.
**Date**: 2026-03-13

### D5: Officium's axiom renames are not adopted by council yet

**Context**: Officium renamed `single_user` → `single_operator`, `executive_function` → `decision_support`.
**Decision**: Defer. Council's axiom names are referenced in 40+ sufficiency probes, hooks, implications, audit logs, and CLAUDE.md. Renaming requires coordinated migration. Adopt `supersedes` mechanism first (Priority 8), then consider renames as a separate project.
**Date**: 2026-03-13

### D6: OpenTelemetry stays council-only

**Context**: Council instruments 25+ agents with OTel spans. Officium intentionally stripped OTel.
**Decision**: Keep separate. Officium's smaller agent surface doesn't justify the instrumentation overhead. Langfuse provides sufficient observability for its needs. Revisit if officium's agent count grows.
**Date**: 2026-03-13

### D7: Deployment models stay different

**Context**: Council uses systemd + host-native. Officium uses Docker Compose.
**Decision**: Keep separate. Council requires host-native GPU access for voice daemon and CUDA workloads. Docker GPU passthrough adds complexity without benefit. Officium's LLM-only workload fits containers well.
**Date**: 2026-03-13
