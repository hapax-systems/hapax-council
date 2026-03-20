# Claim 6: Bayesian Mode/Tool Selection
# Formal Research Document

**Status**: Pre-registration draft. Not yet active. Dependent on
completion of Claim 1 experiment cycle.

**Prepared**: 2026-03-20
**Authors**: Operator (the operator), Claude Opus 4.6 (beta session)

---

## 1. Abstract

We propose that Bayesian mode/tool selection — where a posterior
probability over operational modes determines a composed tool palette
and knowledge context per turn — produces better conversational
grounding than monolithic tool access. Current voice AI systems
provide all tools on every turn regardless of conversational context.
We decompose monolithic tools into atomic epistemic primitives and
compose mode-specific palettes from environmental signals using
conjugate Bayesian updates, gated by a conversational fitness function
that prevents tool execution from interrupting grounding.

## 2. Background and Motivation

### 2.1 The Tool Problem in Voice Conversation

Tools in voice AI systems are monolithic retrieval operations: each
tool is a complete round-trip to an external system (database, API,
inference service) that returns a blob of information. In the Hapax
voice pipeline, 20+ tools each add 1-10 seconds of latency per call,
with tool execution plus a second LLM round-trip consuming the entire
20-second turn budget.

This architecture is structurally identical to the profile-retrieval
pattern identified in POSITION.md as the industry's convergent
approach to conversational continuity — and identified as a failure
mode of that approach. The model leaves the conversation to query an
external system. The operator waits in silence. The returned data has
no grounding history.

Empirically, during baseline and Phase B data collection for Claim 1
(40 sessions total), the following tool-related phenomena were observed:

- **Tool hallucination**: With tools disabled, Opus generated tool-call
  XML as plain text in at least 5 tag variants (`<tool_use>`,
  `<tool_calls>`, `<invoke>`, `<Tool>`, `<use_tool>`)
- **Result fabrication**: Opus fabricated plausible but false tool
  results (fake calendar events, fake visual descriptions, fake
  system status data) when tools were disabled
- **Follow-through failure**: When tool calls were attempted, the
  model repeatedly announced it would check something and then
  went silent (sessions 14, 16)
- **Confabulation escalation**: Visual perception claims that were
  entirely fabricated (hat on/off/beanie sequence in session 7,
  fake office description in session 12)

These observations indicate that the model has a strong prior toward
tool use that manifests destructively when tools are unavailable, and
that when tools are available, they dominate the conversation's
temporal budget.

### 2.2 The Operator's Framing

During Phase B session 4 (2026-03-19), the operator articulated the
core insight:

> "Couldn't we use Bayesian calculations to arrive at the proper role
> and then also arrive at decomposed tools that could be pulled in out
> of a RAG system that could supply you with the needed role context
> in the moment?"

In a prior exchange about tool design, the operator described tools as:

> "Cognitive-epistemic-valent juice cans that you can decide to squeeze
> whenever you want regardless of what they contain regardless of how
> many hands you have or how big your stomach is."

And offered the doctor analogy:

> "Doctor diagnoses a patient, understands diagnostic procedures, the
> whole background of things that supports the ACTION OF LOOKING UP
> CONTRAINDICATIONS IN A RELIABLE WAY."

These framings establish that the problem is not tool selection or
tool routing — it is the epistemic character of the tools themselves.
A tool call is not a free database query. It is an epistemic act that
must cohere with the conversational moment.

### 2.3 Prior Work

**MACLA (AAMAS 2025)**: Learning Hierarchical Procedural Memory for
LLM Agents through Bayesian Selection and Contrastive Refinement.
Maintains Beta posteriors over procedure success rates. Selects actions
through expected-utility scoring that balances relevance, success
probability, failure risk, and information gain. Decouples reasoning
from learning by maintaining adaptation in external memory.
78.1% average performance across 4 benchmarks.
(Forouzandeh et al., https://arxiv.org/abs/2512.18950)

**ToolTree (ICLR 2026)**: Efficient LLM Agent Tool Planning via
Dual-Feedback Monte Carlo Tree Search and Bidirectional Pruning.
Pre-execution scoring predicts tool utility before invocation.
Post-execution scoring assesses actual contribution. ~10% improvement
over state-of-the-art planning paradigms.
(https://arxiv.org/abs/2603.12740)

**LLM Bayesian Meta-Reasoning (2025)**: Position paper arguing LLMs
need a Bayesian framework with task-level and meta-level components.
Bi-level updates for reasoning strategy (task) and knowledge priors
(meta). (https://openreview.net/pdf?id=RrvhbxO2hd)

**ADHD and Attentional Set Shifting**: Adults with ADHD show selective
impairment in shifting attention between task sets. The difficulty is
not in performing tasks but in transitioning between them. A Bayesian
mode system that handles transitions for the operator directly
addresses this — the system performs the set-shifting the operator
cannot.
(Tamm & Nakonezny, https://pmc.ncbi.nlm.nih.gov/articles/PMC6230251/)

**Gap**: No existing work combines Bayesian posterior over operational
modes, mode-dependent tool composition from atomic primitives,
conversational fitness gating, and grounding-aware measurement.

### 2.4 Relationship to Claims 1-5

This claim is independent of but informed by the Claim 1 experiment:

- Claims 1-4 test conversation-internal mechanisms (thread, compression,
  cross-session memory, sentinel). Tools are orthogonal and were
  disabled during those experiments.
- Claim 5 tests salience-response correlation, which tool use may
  confound (noted in TOOL-CALLS.md).
- Claim 6 tests whether tools can participate in grounding rather
  than interrupting it. This requires claims 1-4 infrastructure
  (conversation thread, scoring) as baseline.

## 3. Theoretical Framework

### 3.1 Tools as Epistemic Acts

Clark & Brennan (1991) describe grounding as the collaborative process
of establishing mutual understanding. Every conversational action
either contributes to or disrupts this process. A tool call is not
neutral — it is an epistemic act that the operator observes:

- The operator perceives the silence during tool execution
- The operator interprets the system's choice to look something up
- The operator evaluates whether the returned information was relevant
- The operator's acceptance or rejection of the tool result IS
  grounding data

Current systems treat tool calls as invisible infrastructure. The
Bayesian mode/tool selection system treats them as first-class
conversational acts subject to fitness evaluation.

### 3.2 Mode as Bayesian Posterior

An operational mode is a joint distribution over:
- Which tools are available (palette)
- What knowledge context is loaded (from RAG)
- What behavioral priors apply (response style)

The system maintains a posterior over modes:

```
P(mode_k | signals) ∝ P(signals | mode_k) × P(mode_k | history)
```

Where:
- `signals` = 16 perception signals at 2.5s cadence
- `P(signals | mode_k)` = likelihood ratios per signal per mode
  (same conjugate update pattern as the Bayesian presence engine)
- `P(mode_k | history)` = prior from recent mode selections,
  decaying toward uniform, reset by BOCPD change points

### 3.3 Atomic Epistemic Primitives

Monolithic tools decompose into primitives with known latency profiles:

| Primitive | Latency | Epistemic Character |
|-----------|---------|-------------------|
| check_thread(topic) | 0ms | Can I answer from shared context? |
| recall_episode(query) | 200ms | Have we discussed this before? |
| lookup_fact(query, source) | 500ms | One specific fact from one source |
| read_perception(aspect) | 0ms | What do my senses say right now? |
| read_shm(path, key) | 0ms | What does the system state say? |
| query_api(endpoint) | 1-3s | Hit one specific API endpoint |
| search_external(service, query) | 2-5s | Query an external service |

A mode composes from this pool. Studio mode: `read_perception("audio_energy")`,
`check_thread("sample")`, `recall_episode("studio session")`.
Not `search_documents("*")`.

### 3.4 Conversational Fitness Function

Before executing any tool, evaluate fitness:

```
fitness = value(tool, state) × expectation(tool, utterance) / cost(latency, pacing)
```

Where:
- `value` = P(tool result improves grounding | conversation state)
- `expectation` = P(operator expects this tool use | utterance + acceptance history)
- `cost` = silence duration relative to conversational pacing

Execute only if `fitness > threshold`. The threshold adapts to
conversation pacing (rapid exchange → high threshold, reflective
pause → low threshold).

## 4. Proposed Modes

| Mode | Signal Profile | Tool Palette | Knowledge Context |
|------|---------------|-------------|------------------|
| Studio | production activity, MIDI, audio | sample_search, session_notes, tempo | Sample library, session history, genre |
| Scheduling | calendar mention, morning, time dialog | calendar, reminders, meetings | Calendar data, recurring patterns |
| System | coding activity, error detected, system dialog | health, logs, services, git | Architecture, PRs, service map |
| Social | low activation, casual dialog, evening | weather, time (minimal) | Recent conversations, personal context |
| Research | high novelty, meta-questions, high activation | search_docs, web_search, references | Research docs, methodology, prior findings |

## 5. Architecture

### 5.1 Components

```
ModeSelector
  ├── signal_reader (reads 16 perception signals)
  ├── mode_posterior (conjugate Bayesian update)
  ├── palette_composer (maps mode → atomic tool set)
  ├── knowledge_loader (Qdrant retrieval per mode)
  └── fitness_gate (pre-execution evaluation)
```

### 5.2 Integration Points (existing architecture)

1. **System prompt VOLATILE band** — mode-specific knowledge block
2. **LLM kwargs["tools"]** — mode-filtered tool schemas
3. **Salience context** — mode confidence and transition signals
4. **Bridge phrases** — mode-appropriate framing for tool pauses
5. **Experiment flag** — `components.bayesian_tools` toggle

### 5.3 Signal Sources

All 16 signals already available at 2.5s perception tick:
activation_score, novelty, concern_overlap, dialog_feature_score,
conversation_temperature, presence_probability, interruptibility_score,
activity_mode, flow_state, stimmung_stance, resource_pressure,
cost_pressure, BOCPD_change_points, heart_rate, active_window,
turn_depth.

No new infrastructure required. The mode selector reads from
existing perception state and writes to existing context injection
points.

## 6. Experimental Design

### 6.1 Hypothesis

Bayesian mode/tool selection improves `context_anchor_success` on
tool-invoked turns by ≥0.20 compared to monolithic tool access.

### 6.2 Prior

Beta(1, 1) — uninformative. No prior evidence exists for this
specific mechanism.

### 6.3 ROPE

[-0.1, 0.1] — wider than Claim 1 due to higher variance on
tool-invoked turns.

### 6.4 Phases

- **Phase A (control)**: Monolithic tools re-enabled. All 20+ tools
  available on every turn. Existing `_handle_tool_calls()` path
  active. `components.bayesian_tools = false`.
- **Phase B (intervention)**: Bayesian mode selector active. Atomic
  primitives replace monolithic tools. Mode-specific palettes.
  Fitness gating. `components.bayesian_tools = true`.

### 6.5 Metrics

**Primary (per-turn, tool-invoked only)**:
- `context_anchor_success` — does the tool result anchor to context?

**Secondary (per-session)**:
- `tool_fitness_hit_rate` — proportion of tools that passed fitness
  AND improved next turn's anchor
- `mode_stability` — mode transitions per session
- `tool_latency_ms` — per-tool execution time
- `mode_confidence` — posterior confidence at tool invocation time

**Class G (grounding-native)**:
- `acceptance_after_tool` — P(ACCEPT at N+1 | tool invoked at N)
- `frustration_after_tool` — P(frustration at N+1 | tool invoked at N)
- `anchor_trajectory_tool_sessions` — slope of anchor on sessions
  with tool invocations

**Class R (retrieval-native)**:
- `tool_result_accuracy` — factual correctness of tool results
- `tool_relevance` — was the right tool selected for the query?

### 6.6 Sequential Stopping

Bayes Factor > 10 (decisive for or against) or 30 sessions with
≥3 tool-invoked turns each. Run experiment_runner every 5 sessions.

### 6.7 Dependencies

Must complete before starting:
1. Claim 1 experiment cycle (Phase B + Phase A' reversal)
2. Report Claim 1 results
3. Implement atomic tool primitives
4. Implement ModeSelector with experiment flag
5. Add tool fitness scoring to Langfuse
6. Pre-register this document formally

## 7. Implementation Plan

### Phase 1: Atomic Primitives (est. 1 day)
- Decompose current 20+ tools into 7 atomic primitives
- Each primitive: single responsibility, known latency, typed I/O
- Unit tests for each primitive

### Phase 2: Mode Selector (est. 1 day)
- Signal reader from existing EnvironmentState
- Conjugate Bayesian update (same pattern as presence engine)
- Mode-to-palette mapping
- Experiment flag gating

### Phase 3: Knowledge Context (est. 1 day)
- Per-mode Qdrant retrieval queries
- Context formatting for system prompt injection
- Cache with staleness detection

### Phase 4: Fitness Gate (est. 0.5 day)
- Pre-execution scoring function
- Latency budget from conversational pacing
- Operator expectation heuristic
- Langfuse logging of fitness decisions

### Phase 5: Instrumentation (est. 0.5 day)
- Tool fitness scores per turn in Langfuse
- Mode selection logging
- Mode stability metric computation
- Integration with experiment_runner

### Phase 6: Baseline Collection
- Re-enable monolithic tools (Phase A)
- Collect 20+ sessions
- Establish tool-invoked turn anchor baseline

### Phase 7: Intervention Collection
- Enable Bayesian mode selection (Phase B)
- Collect sessions until BF > 10 or 30 sessions

## 8. Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Mode posterior thrashes between modes | Hysteresis: mode can only change every N turns |
| Atomic primitives lose capability vs monolithic | Compose multiple primitives per turn; monitor tool_result_accuracy |
| Fitness gate blocks useful tools | Log all fitness rejections; tune threshold from data |
| Mode-specific context pollutes prompt | Context budget per mode; hash-based staleness |
| Implementation changes confound Claim 1 results | Strict experiment flag gating; no implementation until Claim 1 complete |

## 9. Connection to Broader Research Position

This claim extends the counter-position established in POSITION.md.
The industry's profile-retrieval pattern treats tools as free
lookups against a database. Bayesian mode/tool selection treats
tools as epistemic acts fitted to the conversational moment:

- **Failure Mode #3** (treating turns as retrieval queries): addressed
  by mode-dependent tool access — not every turn triggers all tools
- **Failure Mode #5** (measuring by retrieval accuracy): addressed by
  measuring tool_fitness_hit_rate — did the tool serve grounding,
  not just return correct data?

The measurement framework (OBSERVABILITY.md) extends naturally:
- Class G metrics apply to tool-invoked turns
- Class F detectors watch for regression to monolithic patterns
- Trajectory metrics computed on tool-active sessions specifically

## 10. References

1. Clark, H. H., & Brennan, S. E. (1991). Grounding in communication.
2. Forouzandeh et al. (2025). MACLA: Learning Hierarchical Procedural Memory. https://arxiv.org/abs/2512.18950
3. ToolTree (ICLR 2026). https://arxiv.org/abs/2603.12740
4. LLM Bayesian Meta-Reasoning. https://openreview.net/pdf?id=RrvhbxO2hd
5. Tamm & Nakonezny. ADHD Attentional Set Shifting. https://pmc.ncbi.nlm.nih.gov/articles/PMC6230251/
6. Natural Language Tools. https://arxiv.org/html/2510.14453v1
7. MCP-Zero: Proactive Toolchain Construction. https://arxiv.org/html/2506.01056v2
8. POSITION.md (this repository). Counter-positioning against profile retrieval.
9. TOOL-CALLS.md (this repository). Tool calls as epistemic acts.
10. BARGE-IN-REPAIR.md (this repository). Grounding-aware overlap handling.
11. Phase B Session 4 transcript (this repository). Origin of the Bayesian role/tool idea.

---

*This document will be formally pre-registered after Claim 1 experiment
cycle completes. Implementation and data collection will not begin
until pre-registration is final.*
