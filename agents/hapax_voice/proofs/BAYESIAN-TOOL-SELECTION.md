# Bayesian Mode/Tool Selection: Design and Research

## Origin

Phase B session 4 (2026-03-19): operator and Hapax co-developed the idea
during a conversation about cognitive load and context switching:

> "Couldn't we use Bayesian calculations to arrive at the proper role
> and then also arrive at decomposed tools that could be pulled in out
> of a RAG system that could supply you with the needed role context
> in the moment?"

This connects three threads: the tool-call-as-epistemic-act research
(TOOL-CALLS.md), alpha's Bayesian integration map (5 probabilistic
systems underutilized by the voice pipeline), and the operator's
lived experience of ADHD mode-switching difficulty.

## Core Idea

Instead of a fixed tool inventory available at all times, the system
computes a **posterior probability over operational modes** from all
available signals, then composes a **mode-specific tool palette and
knowledge context** fitted to the conversational moment.

```
Signals (16 sources, 2.5s tick)
  → Bayesian mode posterior P(mode | signals)
  → Mode-specific tool palette (atomic primitives, not monolithic)
  → Mode-specific knowledge context (from RAG, not hardcoded)
  → Injected into system prompt alongside conversation thread
  → Tool execution gated by conversational fitness
```

The mode selection IS the tool selection. Studio mode doesn't just
change the personality — it changes what the system can DO and what
it KNOWS about in that moment.

## Prior Research

### Directly Relevant

**MACLA (AAMAS 2025)**: Hierarchical procedural memory with Beta
posteriors over success rates. Frozen LLM + external memory that
tracks procedure reliability via Bayesian updates. Selects actions
through expected-utility scoring balancing relevance, success
probability, failure risk, and information gain. 78.1% average
across 4 benchmarks. Key insight: **decouple reasoning from learning
by maintaining posteriors in external memory, not in the model.**

**ToolTree (ICLR 2026)**: Pre-execution scoring predicts tool utility
before invocation. Post-execution scoring assesses actual contribution.
Monte Carlo tree search over tool trajectories with bidirectional
pruning. Key insight: **evaluate tool fitness before executing, not
just after.**

**LLM Bayesian Meta-Reasoning (2025)**: Position paper arguing LLMs
need a Bayesian framework with task-level and meta-level components.
Bi-level updates for reasoning strategy (task) and knowledge priors
(meta). Key insight: **the model should reason about its own reasoning
strategy, not just apply one.**

### Adjacent

**ADHD and attentional set shifting**: Adults with ADHD show selective
impairment in shifting attention between task sets. The difficulty is
not in performing tasks but in transitioning between them. A Bayesian
mode system that handles transitions for the operator directly
addresses this — the system does the set-shifting, not the person.

**MCP (Model Context Protocol)**: Defines primitives for tool
integration — Tools (callable), Resources (contextual data), Prompts
(behavioral templates). The composability model maps to our atomic
primitives, but MCP has no concept of fitness-based selection.

### Gap

Nobody combines:
1. Bayesian posterior over operational modes
2. Mode-dependent tool composition from atomic primitives
3. Conversational fitness gating (when to invoke, not just what)
4. Grounding-aware measurement (did the tool serve the conversation?)

## Available Signals (16 sources)

All available at 2.5s perception tick cadence:

| Signal | Type | Source | Mode Relevance |
|--------|------|--------|---------------|
| activation_score | float 0-1 | Salience router | High activation → complex mode |
| novelty | float 0-1 | Concern graph | High novelty → exploration mode |
| concern_overlap | float 0-1 | Concern graph | What domain the operator cares about |
| dialog_feature_score | float 0-1 | Utterance analysis | Complexity of the request |
| conversation_temperature | float 0-1 | Cognitive loop | Engagement level |
| presence_probability | float 0-1 | Bayesian presence engine | Confidence operator is present |
| interruptibility_score | float 0-1 | Composite | Can the operator be interrupted? |
| activity_mode | str | Local LLM classifier | coding/production/meeting/browsing/idle |
| flow_state | str | Temporal bands | idle/warming/active |
| stimmung_stance | str | System self-state | nominal/cautious/degraded/critical |
| resource_pressure | float 0-1 | GPU/system load | System can afford heavy tools? |
| cost_pressure | float 0-1 | LLM cost tracking | Budget allows cloud calls? |
| BOCPD_change_points | list | Change point detector | Recent activity transitions |
| heart_rate | int | Watch backend | Physiological state |
| active_window | str | Hyprland | What app is focused |
| turn_depth | int | Conversation pipeline | How deep in the conversation |

## Proposed Modes

Each mode is a **tool palette + knowledge context + behavioral priors**:

### Studio Mode
**Signals**: activity_mode=production OR music detected OR MIDI active
**Tools**: sample_search, track_status, tempo_check, session_notes
**Knowledge**: sample library index, recent session history, genre preferences
**Behavioral**: brief, technical, don't interrupt flow

### Scheduling Mode
**Signals**: calendar mention OR time-related dialog OR morning routine
**Tools**: calendar_today, calendar_week, set_reminder, check_meeting
**Knowledge**: calendar data, recurring patterns, commute time
**Behavioral**: proactive about upcoming events, time-aware

### System Mode
**Signals**: activity_mode=coding OR system-related dialog OR error detected
**Tools**: check_health, search_logs, check_service, git_status
**Knowledge**: system architecture, recent PRs, service map
**Behavioral**: technical, diagnostic, offer to investigate

### Social Mode
**Signals**: low activation + casual dialog features + evening time
**Tools**: minimal — maybe weather, time
**Knowledge**: recent conversations, personal context
**Behavioral**: warm, elaborative, willing to wander

### Research Mode
**Signals**: high novelty + high activation + meta-questions
**Tools**: search_documents, web_search, check_references
**Knowledge**: research documents, prior findings, methodology
**Behavioral**: thorough, citations, build on prior discussion

## Mode Posterior Computation

Using the same conjugate update pattern as the presence engine:

```
P(mode | signals) ∝ P(signals | mode) × P(mode | recent_history)
```

**Likelihood**: each signal has a likelihood ratio per mode (like the
presence engine's 10 signal weights). Example:
- P(activity_mode="production" | studio_mode) = 0.9
- P(activity_mode="production" | scheduling_mode) = 0.05
- P(MIDI_active | studio_mode) = 0.95
- P(MIDI_active | social_mode) = 0.1

**Prior**: decays toward uniform, updated by recent mode selections.
BOCPD change points reset the prior (transition = new mode likely).

**Posterior**: computed per perception tick (2.5s). Top mode determines
tool palette. Uncertainty (no mode dominant) → minimal tool set.

## Context Injection Points

The mode and its associated context inject at multiple existing points:

### 1. System Prompt VOLATILE Band
Currently: policy + environment + phenomenal + salience.
**Add**: mode-specific knowledge block.

```python
# In _update_system_context():
if self._mode_selector is not None:
    mode = self._mode_selector.current_mode
    mode_ctx = self._mode_selector.get_knowledge_context()
    updated += f"\n\n## Current Mode: {mode.name}\n{mode_ctx}"
```

### 2. Tool Palette (kwargs to LLM)
Currently: tools disabled entirely.
**Add**: mode-filtered tool schemas.

```python
# In _generate_and_speak():
if self._mode_selector is not None:
    mode_tools = self._mode_selector.get_tool_schemas()
    if mode_tools:
        kwargs["tools"] = mode_tools
```

### 3. Salience Context
Currently: activation + novelty + concern + stimmung.
**Add**: mode confidence and transition signals.

```python
# In _build_salience_context():
if self._mode_selector:
    mode = self._mode_selector.current_mode
    conf = self._mode_selector.confidence
    parts.append(f"Mode: {mode.name} (confidence: {conf:.2f})")
```

### 4. Bridge Phrase Selection
Currently: context-aware but no mode input.
**Add**: mode shapes bridge phrase register.

### 5. Experiment Flag
```json
{"components": {"bayesian_tools": true}}
```

## Tool Decomposition

Each mode's tools are **atomic primitives**, not the current monolithic
functions. A mode composes from a shared pool:

| Primitive | Latency | What It Does |
|-----------|---------|-------------|
| check_thread(topic) | 0ms | Search conversation thread for topic |
| recall_episode(query) | 200ms | Qdrant scroll on operator-episodes |
| lookup_fact(query, source) | 500ms | Single-result Qdrant search |
| read_perception(aspect) | 0ms | Read one behavior from perception state |
| read_shm(path, key) | 0ms | Read one value from /dev/shm state |
| query_api(endpoint) | 1-3s | Hit cockpit API endpoint |
| search_external(service, query) | 2-5s | Google/calendar/email API |

A mode like "studio" would compose: `read_perception("audio_energy")`,
`check_thread("sample")`, `recall_episode("studio session")`. Not
`search_documents("*")`.

## Fitness Gating

Before executing any tool, check conversational fitness:

```python
def should_execute(tool, mode, conversation_state):
    # Time budget: how much silence can this conversation afford?
    budget_ms = _time_budget(conversation_state.pacing)
    if tool.expected_latency_ms > budget_ms:
        return False

    # Operator expectation: was this tool implicitly requested?
    expectation = _operator_expects(tool, conversation_state.last_utterance)
    if expectation < 0.3:
        return False  # surprise tool calls break grounding

    # Value: will the result add to shared understanding?
    value = mode.tool_value_prior(tool, conversation_state)

    return value * expectation > 0.5
```

## Measurement

### How to know if mode selection works

**Class G metrics (grounding-native):**
- Does mode-appropriate context improve `context_anchor_success`?
- Does tool execution during conversation maintain or break
  `acceptance_type` (do tools serve grounding or interrupt it)?
- Does mode switching correlate with `frustration_trajectory`?

**Class R metrics (retrieval-native):**
- Does mode-specific tool access match or exceed monolithic tool
  accuracy? (Can studio mode find samples as well as full search?)
- Does cross-mode transition maintain `reference_accuracy`?

**New metrics:**
- `mode_stability` — how often does the mode flip per session?
  (Too stable = not responsive. Too unstable = thrashing.)
- `tool_fitness_hit_rate` — proportion of tool calls that passed
  fitness gating AND improved the next turn's anchor score.
- `mode_transition_latency` — time from signal change to mode switch.

### Experiment design

Pre-register as a new claim (not retrofit onto claims 1-5):

**Claim 6: Bayesian mode/tool selection improves tool-assisted
grounding over monolithic tool access.**

- Prior: Beta(1,1) — no prior evidence
- Metric: `context_anchor_success` on tool-invoked turns specifically
- ROPE: [-0.1, 0.1]
- Design: A-B with `bayesian_tools` experiment flag
- Phase A: monolithic tools re-enabled (all tools, all turns)
- Phase B: Bayesian mode selection with atomic primitives
- Sequential stopping: BF > 10 or 30 sessions

## Coherency with Research Protocol

This is a **new experiment cycle**, not a modification of the current one.

1. **Finish current cycle** (claim 1, Phase B → Phase A' reversal)
2. **Report results** for claim 1 honestly (BF, effect size, qualitative)
3. **Design claim 6** based on what we learned
4. **Pre-register** before collecting any data
5. **Implement** the mode selector as a new component with experiment flag
6. **Baseline** with monolithic tools re-enabled (Phase A)
7. **Intervention** with Bayesian mode selection (Phase B)

No moving goalposts. No retrofitting. The current experiment informs
the next one.

## Implementation Constraints

- **Must not affect current experiment** — gated by experiment flag,
  default OFF
- **Must compose with existing architecture** — reads from perception
  state, injects into existing prompt bands, uses existing Qdrant
- **Must be measurable** — all mode decisions logged to Langfuse,
  tool fitness scores recorded per turn
- **Must degrade gracefully** — if mode posterior is uncertain,
  fall back to minimal tool set (not full monolithic set)
- **Atomic primitives must be real** — not wrappers around existing
  monolithic tools, but genuinely decomposed operations

## References

- MACLA: https://arxiv.org/abs/2512.18950
- ToolTree (ICLR 2026): https://arxiv.org/abs/2603.12740
- LLM Bayesian Meta-Reasoning: https://openreview.net/pdf?id=RrvhbxO2hd
- ADHD Attentional Set Shifting: https://pmc.ncbi.nlm.nih.gov/articles/PMC6230251/
- MCP Specification: https://en.wikipedia.org/wiki/Model_Context_Protocol
- Phase B Session 4 (origin conversation): proofs/claim-1-stable-frame/data/phase-b-session-004.json

---

*Saved 2026-03-20. Implementation deferred to post-claim-1 experiment cycle.
Pre-register as Claim 6 before any data collection.*
