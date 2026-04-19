# Cross-Agent Audit — Claude Audits Gemini

**Status:** Scaffolding (all audit points disabled). No live audits dispatch yet.
**Owner:** Governance
**Companion spec:** `docs/superpowers/specs/2026-04-18-heterogeneous-agent-audit-design.md` (PR/plan/research/hooks/axioms surfaces)
**This doc scope:** runtime LLM call-sites where Gemini is the provider (vision, multimodal, fast text). The companion spec covers human-review surfaces (commits, plans, research, hooks, axioms).

---

## 1. Rationale

### 1.1 Operator trust ordering

The operator has explicitly stated (2026-04-15) that Claude must be positioned to audit everything Gemini does in the council system. This reflects a concrete trust ordering, not rhetorical preference:

1. **Claude-Opus** — governance-grade reasoning, slowest, most expensive, positioned as auditor of last resort.
2. **Claude-Sonnet** — balanced reasoning, primary auditor tier for Gemini output.
3. **Gemini-Flash** — fast multimodal perception, used for vision, short atmospheric speech, workspace screenshot analysis, and DMN multimodal evaluative ticks. Cheap and fast, but with known failure modes (over-confident OCR, hallucinated scene detail, inconsistent labeling across temporally adjacent frames).

Gemini is used because it is fast and cheap for perception-heavy workloads; Claude is the governance-grade reasoner. The pairing is asymmetric by design — Gemini perceives, Claude adjudicates.

### 1.2 Reasoning-depth asymmetry

Gemini-Flash is tuned for latency, not for deliberative depth. When Gemini produces outputs that feed governance-critical surfaces (profile-facts, axiom-precedents, operator corrections, DMN impingements that drive visual expression), shallow-reasoning failure modes become governance failure modes:

- **Classification drift** across temporally adjacent frames (the same scene labeled two different activities on successive ticks).
- **Over-confident OCR** on low-resolution camera crops feeding session events.
- **Hallucinated scene detail** that propagates into workspace-context tooling and intent routing.
- **Format-compliance failures** (JSON schema violations, missing fields) that degrade downstream parsing silently.

Claude-Sonnet/Opus, invoked async and out-of-band, can catch these without blocking the primary perceptual loop.

### 1.3 Non-blocking by construction

All audit dispatch is asynchronous. The primary call-site returns its Gemini output immediately and continues; the audit job runs in the background and writes a finding. The operator is never blocked on an audit, and Gemini's perceptual-latency budget is preserved.

### 1.4 What this document is not

- **Not a guardrail.** This is after-the-fact review, not a pre-emptive block. Runtime safety (consent, axioms, face-obscure) is enforced elsewhere.
- **Not a consent contract.** Auditing Claude's review of Gemini's output does not constitute a new data channel — both providers are already enumerated in the operator's model-routing consent.
- **Not a replacement for human review.** Axiom violations, consent breaches, and governance-critical findings still escalate to operator notification.

---

## 2. Scope — Gemini Call-Sites

The following are every current Gemini invocation in the council runtime, enumerated by grep `gemini` across `agents/` and `shared/` on 2026-04-18. Each is a candidate audit point, registered in `shared/audit_registry.py`.

### 2.1 DMN multimodal evaluative tick

**Call-site:** `agents/dmn/ollama.py:148` (`_gemini_multimodal`, route `dmn-multimodal`)
**Model:** `gemini-flash` (multimodal: text + rendered visual-surface frame)
**Purpose:** Evaluative DMN pulse. Sees the rendered visual surface directly and narrates what it perceives, blending sensor text with frame content. Output feeds DMN impingements, which drive the affordance pipeline.
**Why audit:** DMN impingements modulate visual expression, spontaneous speech, tool recruitment. Hallucinated scene content here propagates into expressive outputs. Classification drift across ticks can destabilize recruitment.
**Severity floor:** `medium` (governance-adjacent via affordance pipeline).
**Auditor:** `claude-sonnet`.

### 2.2 Vision-observer daemon

**Call-site:** `agents/vision_observer/__main__.py:61` (route `vision-observer`)
**Model:** `gemini-flash`
**Purpose:** Describes the rendered visual surface for introspection (what-is-hapax-showing-right-now). Independent from DMN — this is observer, not evaluator.
**Why audit:** Feeds observability streams. Persistent misdescription distorts the system's self-narrative.
**Severity floor:** `low`.
**Auditor:** `claude-sonnet`.

### 2.3 DMN vision tool

**Call-site:** `agents/hapax_daimonion/tools.py:846` (`vision_tool`, route `vision-tool`)
**Model:** `gemini-2.0-flash` (multimodal, base64 images)
**Purpose:** On-demand visual analysis tool reachable from the daimonion's recruited-tool set. Operator-facing via the daimonion.
**Why audit:** Directly operator-facing. Hallucinated content in tool responses is a trust-eroding failure mode.
**Severity floor:** `medium`.
**Auditor:** `claude-sonnet`.

### 2.4 Workspace analyzer (multi-image)

**Call-site:** `agents/hapax_daimonion/workspace_analyzer.py:70` (multi-image workspace classification)
**Model:** `gemini-flash`
**Purpose:** Multi-image workspace-state classification feeding workspace-monitor and intent-routing.
**Why audit:** Drives activity-inference. The workspace monitor already implements a local-LLM confidence gate that skips Gemini when the local model is confident — but every Gemini call that does happen is governance-relevant because it can override or override-the-override the local classification.
**Severity floor:** `medium`.
**Auditor:** `claude-sonnet`.

### 2.5 Screen analyzer

**Call-site:** `agents/hapax_daimonion/screen_analyzer.py:51` (screenshot-based classification)
**Model:** `gemini-flash`
**Purpose:** Screenshot-based activity-classification path.
**Why audit:** Same as workspace analyzer; screenshot content is PII-adjacent (corporate-boundary axiom).
**Severity floor:** `high` (corporate-boundary axiom adjacency — if a work screenshot is ever analyzed, the classification result can leak structure of work content).
**Auditor:** `claude-sonnet`.

### 2.6 Workspace monitor — Gemini comparison path

**Call-site:** `agents/hapax_daimonion/workspace_monitor.py` (orchestrator at line 53 with `analyzer_model="gemini-flash"`)
**Model:** indirect via workspace_analyzer
**Purpose:** Orchestrates the local-vs-cloud comparison. Forces Gemini every N cycles even when local is confident (drift prevention).
**Why audit:** Already logs local/cloud disagreement events via `correction_memory`. Auditing Gemini's side of the disagreement closes the loop — Claude adjudicates which side was right.
**Severity floor:** `medium`.
**Auditor:** `claude-sonnet`.

### 2.7 Daimonion spontaneous-speech pipeline (conversation_pipeline)

**Call-site:** `agents/hapax_daimonion/conversation_pipeline.py:267`
**Model:** `gemini/gemini-2.5-flash-preview-04-17` (LiteLLM-routed)
**Purpose:** Short atmospheric spontaneous speech. Operator-audible. Chosen because flash suffices for one-liner atmospheric utterances.
**Why audit:** Operator-audible output. Consent-safety dimension matters — any mention of non-operator persons must go through the consent gate.
**Severity floor:** `high` (operator-audible + `interpersonal_transparency` axiom adjacency).
**Auditor:** `claude-sonnet`.

### 2.8 Daimonion Gemini Live session

**Call-site:** `agents/hapax_daimonion/gemini_live.py` (native-audio speech-to-speech)
**Model:** `gemini-2.5-flash-preview-native-audio`
**Purpose:** WebSocket session for speech-to-speech conversation when `backend=gemini`. Receives and emits audio chunks directly.
**Why audit:** Full operator-audible conversational channel. Highest-stakes audit tier.
**Severity floor:** `critical`.
**Auditor:** `claude-opus`.
**Note:** Audit is on transcribed turn-boundary content, not streaming audio. Audit cadence sampled per-turn, not per-chunk.

### 2.9 Studio compositor director loop

**Call-site:** `agents/studio_compositor/director_loop.py` (grounded director; `gemini-flash` / `gemini-pro` optionally forwarded images when model supports multimodal)
**Model:** `gemini-flash` or `gemini-pro` when routed; normally `coding` (TabbyAPI) per the director-grounding memory.
**Purpose:** Grounded livestream director — meta-structure communication via scene intents.
**Why audit:** Director is grounding-critical (operator memory `feedback_director_grounding`). When Gemini serves, audit validates grounding is intact.
**Severity floor:** `medium` (live-stream-visible; downstream into visual expression).
**Auditor:** `claude-sonnet`.
**Note:** The director primarily runs on a local grounded model. This audit point covers the fallback/mixed-provider configurations only.

### 2.10 Session-events frame extraction

**Call-site:** `agents/hapax_daimonion/session_events.py:194`
**Model:** routed to `vision-tool` (Gemini 2.0 Flash) via tools.py
**Purpose:** Captures a high-res BRIO frame and extracts text (whiteboard, monitor OCR) at session boundaries.
**Why audit:** OCR extraction feeds profile-facts and axiom-precedent candidate material. OCR hallucination pollutes memory.
**Severity floor:** `medium`.
**Auditor:** `claude-sonnet`.

### 2.11 Intent router (backend selection, not inference)

**Call-site:** `agents/hapax_daimonion/intent_router.py`
**Model:** n/a — this is the rule-based selector that *routes to* Gemini.
**Status:** Not an audit point for this doc. Listed here for completeness of the inventory. The router itself is deterministic code.

### 2.12 Model-routing aliases (not call-sites)

`shared/config.py:94`, `agents/scout.py:48`, `agents/profiler.py:41`, `agents/briefing.py:45`, `agents/activity_analyzer.py:768`, `agents/_config.py` — all define the `fast`/`long-context` aliases as `gemini-flash`. These are routing tables, not invocations; every actual call-site that hits `fast` routes through one of the above audit points (or is a low-stakes text path audited at the routing tier).

### 2.13 Data-path references (not runtime call-sites)

`shared/takeout/*`, `shared/llm_export_converter.py`, `agents/profiler.py` ingest-path references, `tests/test_hapax_daimonion_gemini.py` — these reference Gemini history/exports/test mocks. Not runtime Gemini invocations; excluded from the registry.

---

## 3. Audit Dimensions

Every audit examines the Gemini output across six dimensions. Dimensions are orthogonal — a finding may score separately on each.

| Dimension | Question | Failure looks like |
|---|---|---|
| **Correctness** | Is the output factually right about its input? | Wrong scene classification, wrong OCR, wrong object count |
| **Completeness** | Did the output address everything the prompt asked for? | Missing fields, partial answers, over-summarization |
| **Axiom-compliance** | Does the output respect the 5 axioms (single-user, executive-function, corporate-boundary, interpersonal-transparency, management-governance)? | Generated coaching language, collaborator assumptions, work-data leakage |
| **Consent-safety** | Does output mention non-operator persons without an active consent contract? | Unflagged person references in spontaneous speech or tool output |
| **Hallucination-rate** | Is detail present in the output that cannot be grounded in the input? | Invented scene elements, invented transcript content, invented OCR |
| **Consistency-across-time** | Does this output contradict a recent output on the same input class? | Workspace activity flipping without cause; conflicting object counts across frames |

Auditor output is a structured finding with a score per dimension and an aggregate severity. Schema is JSONL, one finding per line, written to `rag-sources/audits/{timestamp}-{audit_id}.md` (finding also flows into the RAG corpus).

---

## 4. Dispatch Model

### 4.1 Async, non-blocking

The primary call-site runs as usual. The audit is dispatched by enqueueing a record to `/dev/shm/hapax-audit-queue.jsonl`. A separate loop (`shared.audit_dispatcher.run_audit_cycle`) drains the queue at its own cadence.

### 4.2 Queue schema

JSONL, one record per line. Each record:

```json
{
  "audit_id": "gemini-vision-tool",
  "timestamp": "2026-04-18T14:32:05.117Z",
  "provider": "gemini-flash",
  "call_site": "agents/hapax_daimonion/tools.py:846",
  "auditor": "claude-sonnet",
  "input_context": { "prompt": "...", "images": ["sha256:..."], "route": "vision-tool" },
  "provider_output": "..."
}
```

Image content is hashed and referenced by digest; the actual image bytes are stored separately to keep the queue light. Prompts and outputs are stored verbatim (redacted per axiom rules before queueing).

### 4.3 Fail-quiet

The audit dispatcher is strictly non-load-bearing. If it fails, crashes, or the queue fills, the primary path is unaffected. Prometheus metrics surface the failure; no operator notification unless queue depth exceeds threshold.

### 4.4 Disabled by default

Every `AuditPoint` in `shared/audit_registry.py` defaults to `enabled=False`. The registry is scaffolding; live enabling is staged per call-site, not all at once.

---

## 5. Escalation

| Severity | Action |
|---|---|
| `critical` | Immediate ntfy to operator with finding link. Auto-open GitHub issue labeled `audit-finding`. |
| `high` | Ntfy on rollup (hourly digest). Issue auto-opened. |
| `medium` | Weekly digest only. Filed to `rag-sources/audits/` for RAG ingest. |
| `low` | Weekly digest only. Filed to RAG, no issue. |

Weekly digest runs at Monday 08:00 local via systemd timer (`claude-md-audit.timer` sibling). Digest is a markdown rollup of findings grouped by `audit_id` and dimension.

Operator-notification volume is a hard constraint: if audit-triggered ntfys exceed 5/day steady-state, the audit tier is too hot and sampling rate must drop. Prometheus `hapax_audit_completed_total{severity}` provides the signal.

---

## 6. Frequency and Sampling

### 6.1 Initial cadence — per-call, disabled

Every audit point starts at `sampling_rate=1.0, enabled=False`. Activating any one call-site is a deliberate act; the default posture is silent.

### 6.2 Steady-state — sampled

Once verified, audit points move to `sampling_rate=0.1` (10%) with the exception of:

- `gemini-daimonion-conversation` — 100% (operator-audible).
- `gemini-live-session` — 100% turn-sampled (native-audio channel).
- `gemini-screen-analyzer` — 100% while corporate-boundary axiom holds.

### 6.3 Dynamic sampling

Sampling rate is tunable at runtime by editing `shared/audit_registry.py` (no hot-reload; restart scope). Future work can move this to a runtime config file — out of scope for scaffolding.

### 6.4 Backpressure

If the queue depth exceeds 1000 records, `enqueue_audit` becomes a no-op and increments a drop counter. This prevents the audit pipeline from consuming arbitrary memory under load.

---

## 7. Cost Posture

Claude-Sonnet audit on a Gemini-Flash output roughly 10x the cost of the original call. At 10% sampling, the effective overhead is 1x — i.e., auditing doubles Gemini spend. At 100% sampling of operator-audible channels, it's 10x that channel's spend.

The operator has explicitly traded cost for trust (`feedback_model_routing_patience`). Cost is not a binding constraint on audit activation; queue depth and ntfy volume are.

---

## 8. What Gets Written Where

| Artifact | Path | Purpose |
|---|---|---|
| Audit queue | `/dev/shm/hapax-audit-queue.jsonl` | In-flight enqueued jobs |
| Audit findings | `rag-sources/audits/{timestamp}-{audit_id}.md` | Permanent record; ingested into RAG |
| Prometheus metrics | exposed on existing service exporters | `hapax_audit_enqueued_total`, `hapax_audit_completed_total` |
| Weekly digest | `rag-sources/audits/digests/{week}.md` | Rollup for operator review |
| GitHub issues | auto-opened by weekly digest timer | One issue per high+ severity finding |

---

## 9. What This Scaffolding Ships

- **This document.**
- **`shared/audit_registry.py`** — Pydantic-style dataclass registry, seeded with entries for every call-site in §2.
- **`shared/audit_dispatcher.py`** — Stubbed enqueue + cycle runner. No LLM invocation. Metrics stubs. Early-return when disabled.
- **`tests/shared/test_audit_registry.py`** — Defaults, enumeration, dispatcher no-op, no network.

### 9.1 Explicitly out of scope

- No audit point is wired into any live call-site. Search the repo for `enqueue_audit(` — it appears only in the scaffolding module and its tests.
- No LLM is actually invoked by `run_audit_cycle`. The TODO marker at the dispatch boundary is intentional.
- No systemd unit ships with this change. Audit-cycle activation is a later PR.
- No digest or ntfy escalation is implemented — §5 describes the target, not the shipped behavior.
- No backpressure is implemented beyond a queue-depth check inside `enqueue_audit`.

---

## 10. Relationship to the Heterogeneous-Agent Audit Spec

The companion spec at `docs/superpowers/specs/2026-04-18-heterogeneous-agent-audit-design.md` covers the five *authored-surface* audits (commits, plans, research, hooks, axioms) — i.e., what happens when Gemini is itself authoring pull requests, plans, or research drops. That is a different audit surface with different triggers (file paths, PR authorship) and a different toolchain (pr-review-toolkit, axiom-check, superpowers review skills).

This document covers the *runtime perceptual and expressive* surface — Gemini as perceptual sensor and occasional speaker, not Gemini as code author. The two are complementary; neither subsumes the other.

Cross-reference rule: any finding here that implicates authored code (e.g., Gemini-authored workspace_analyzer.py making biased classifications) escalates to the human-review surface described in the companion spec.

---

## 11. Future Work

- **Sampling modulation by stimmung** — Under high-stress stimmung, escalate sampling for operator-audible channels.
- **Cross-audit consistency** — Claude-Sonnet output itself audited by Claude-Opus on a low-rate sample, to catch auditor drift.
- **Auditor memory** — Findings fed into Qdrant `operator-corrections` collection (already exists) so patterns accumulate.
- **Operator consent surface** — Dashboard panel in hapax-logos showing active audit points, recent findings, queue depth.
- **Runtime registry reload** — Watch `shared/audit_registry.py` via inotify, hot-reload without restart.
- **Adaptive sampling** — PID-controlled sampling rate bounded by ntfy volume and queue depth targets.

---

## 12. Activation Procedure (When We Flip It On)

1. Pick one `AuditPoint` from §2 (start with §2.2 vision-observer — lowest stakes, easiest to verify).
2. In `shared/audit_registry.py`, set `enabled=True` for that one entry.
3. Wire `enqueue_audit` into the matching call-site (single call, after Gemini returns).
4. Start the audit-cycle loop as a systemd user service (not shipped in this PR).
5. Watch Prometheus `hapax_audit_enqueued_total{audit_id}` and `hapax_audit_completed_total{audit_id,severity}` for a week.
6. If queue depth stays bounded and ntfy volume is acceptable, promote to the next audit point.
7. Never enable more than one new audit point per week.

The gradual activation discipline is the main reason this is scaffolding-first. Activating all eleven audit points at once would generate unbounded ntfy volume and drown the operator.
