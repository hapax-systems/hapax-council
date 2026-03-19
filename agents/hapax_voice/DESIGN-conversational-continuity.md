# Conversational Continuity Design

**Status**: Proposed
**Date**: 2026-03-19
**Author**: Claude Opus 4.6 + operator
**Scope**: hapax-voice conversation pipeline, cognitive loop, session lifecycle

---

## Problem Statement

The operator experiences context discontinuity at three timescales during voice interaction:

- **Seconds** (tool calls): Hapax speculates before checking tools, pauses during tool execution, then contradicts itself with tool results. The operator hears two disconnected speech segments where the second undermines the first.
- **Minutes** (cross-turn): The system prompt is rebuilt every turn with fresh environment, salience, and phenomenal context. Combined with lossy history compression after turn 7, the model's "reality frame" shifts under the conversation. The operator reports: "it feels like you skip out of your context and then into another context."
- **Hours/days** (cross-session): Complete amnesia. Every wake word starts a cold session with no memory of prior conversations.

### Operator Feedback (verbatim from live testing, 2026-03-19)

> "It sounds like you're really boxed in by something, either contextually or from one conversation to the next, or even in the middle of a conversation, sometimes it feels like you skip out of your context and then into another context. I'm not quite sure what's happening here."

> "It also feels like it is kicking itself back into another turn."

> "Interesting that you were able to reflect back on the previous parts of the conversation... I wonder what happened earlier when you weren't able to have as much insight into what was going on versus now you have more insight."

---

## Unifying Principle

All three problems are the same phenomenon at different timescales: **the shared generative model between operator and agent breaks at boundary crossings.**

From active inference (Friston, 2020): conversation requires both parties to maintain compatible generative models that predict each other's behavior. Every time the system starts fresh -- new tool response, rebuilt system prompt, new session -- it violates the continuity of this shared model. The operator's model of "what Hapax knows" diverges from what Hapax actually has in context.

**Design principle**: Maintain a stable narrative thread that persists across boundaries. Mark changes as updates to the thread, not replacements of it.

---

## Research Basis

### Tool Call Continuity

| Source | Finding | Relevance |
|--------|---------|-----------|
| GetStream, "Speculative Tool Calling" (2025) | Split into parallel tracks: speak filler acknowledgment on Track A, execute tool on Track B. User never hears speculative pre-tool answer. | Direct pattern for suppressing pre-tool speech |
| OpenAI gpt-realtime API (2025-2026) | Asynchronous function calling: "long-running function calls will no longer disrupt the flow of a session." | Validates the parallel execution pattern |
| LiveKit Agent Framework (2025) | Play pre-synthesized hold message using `say()` without awaiting, concurrent with API call. | Matches existing bridge_engine architecture |
| LTS-VoiceAgent (arXiv 2601.19952, Jan 2026) | Listen-Think-Speak with Dual-Role Stream Orchestrator: background Thinker maintains state while foreground Speaker handles output. | Theoretical basis for separating thinking from speaking |
| Schegloff et al., "Self-repair in conversation" (1977); Frontiers (2024) | Failed self-repair (speculation then correction without repair initiation) is rated significantly lower in user acceptability. | Explains why the current behavior feels wrong |

### Cross-Turn Coherence

| Source | Finding | Relevance |
|--------|---------|-----------|
| Chroma Research, "Context Rot" (2025-2026) | 39% performance drop across multi-turn conversations. 10% irrelevant content reduces accuracy by 23%. Models "make premature assumptions, over-rely on earlier responses, fail to course-correct." | The constantly-changing system prompt injects novel environmental context each turn, creating dilution |
| Liu et al., "Lost in the Middle" (Stanford, 2023) | LLM performance follows U-shaped curve: strong at beginning and end, 30%+ accuracy drop in middle of context. | Compressed history block sits in the middle -- worst position |
| Clark & Brennan, "Grounding in Communication" (1991) | Conversation is a joint activity requiring continuous grounding: mutual confirmation that both parties understand what's been said. Track 1 for communicative goals, Track 2 for feedback about success. | Hapax has no Track 2. Never confirms "I understand we're talking about X" |
| Friston et al., "Active inference, communication and hermeneutics" (2015) | Communication works when agents share a generative model. Turn-taking is "selectively attending and attenuating sensory information." | System prompt churn disrupts the shared generative model |
| Friston et al., "Generative models, linguistic communication and active inference" (2020) | When shared model is disrupted, agents fall back to repair sequences. Without repair mechanisms, conversation degrades. | Cross-turn coherence failure produces context skipping |
| Frontiers in Psychology, "Joint Co-construction" (2021) | Human-agent communication requires both parties to attend to the same objects and track shared mental states. | Without topic thread tracking, no mechanism for joint attention |

### Cross-Session Memory

| Source | Finding | Relevance |
|--------|---------|-----------|
| Mem0 (arXiv 2504.19413, 2025) | Three-phase memory: extract candidates from conversation, compare against existing entries, deduplicate. For voice: load core memories at session start, trigger targeted search on topic shift. 26% higher accuracy vs OpenAI memory, 91% lower p95 latency. | Directly applicable architecture for session persistence |
| Memoria Framework (arXiv 2512.12686, Dec 2025) | Hybrid: dynamic session summarization + weighted knowledge graph. Exponential Weighted Average for conflict resolution. 87.1% accuracy, 38.7% latency reduction. | Conflict resolution model for contradictory memories |
| Redis AI / MongoDB / AWS consensus (2025-2026) | Three-layer memory: (1) Session (within-conversation), (2) Episodic (summaries of past interactions), (3) Semantic (extracted facts/relationships). | Hapax has layer 1 only. Infrastructure for layers 2+3 exists |
| Kenneth Reitz, "The Context Window Mind" (2025) | "Every conversation with AI represents brief moments of consciousness that flicker into existence and then disappear." Cross-session memory transforms isolated flickerings into continuity of identity. | Philosophical framing of the problem |
| Predictive Processing (Friston, 2020) | Without cross-session memory, every session starts with flat prior (maximum uncertainty). First turns wasted re-establishing context. | Session start should have informative priors from past sessions |

---

## Verified Code Paths

All code paths verified by direct file reads. Line numbers reference commit `82908311` (2026-03-19).

### Tool Call Flow (conversation_pipeline.py)

- **Line 790**: `self.messages.append({"role": "assistant", "content": full_text})` -- appends UNCONDITIONALLY
- **Lines 798-800**: `if tool_calls_data: await self._handle_tool_calls(tool_calls_data, full_text)`
- **Lines 819-831**: `_handle_tool_calls` appends SECOND assistant message with same text + tool_calls structure
- **Line 865**: Second `await self._generate_and_speak()` -- fresh LLM call with tool results
- **Result**: Pre-tool text appears twice in message history. Model sees speculation reinforced.

### System Prompt Rebuild (conversation_pipeline.py)

- **Lines 303-359**: `_update_system_context()` rebuilds `messages[0]["content"]` every turn
- **Lines 326-332**: Fresh policy block from `_policy_fn()`
- **Lines 335-341**: Fresh environment TOON from `_env_context_fn()`
- **Lines 346-353**: Fresh phenomenal context (6 layers) via `render_phenomenal(tier="CAPABLE")`
- **Lines 355-359**: Hash-based change detection prevents unnecessary updates, but the content DOES change most turns

### History Compression (shared/context_compression.py)

- **Invoked at line 620-622**: `compress_history(self.messages, keep_recent=4)`
- **Method**: LLMLingua-2 (BERT-base, CPU), compression rate 0.33
- **Effect**: Older turns compressed into single "user" role message, losing turn structure
- **Position**: Compressed block sits in MIDDLE of messages list

### Session Lifecycle (__main__.py)

- **Lines 1275-1285**: `_close_session()` -- emits event_log, calls `session.close()`. No persistence.
- **Pipeline messages**: Garbage collected when pipeline is nulled at `_stop_pipeline()`

### Existing Memory Infrastructure (verified)

| Collection | Module | Embedding | Status |
|-----------|--------|-----------|--------|
| `operator-episodes` | `shared/episodic_memory.py` | 768-dim nomic | EXISTS, unused by voice |
| `operator-corrections` | `shared/correction_memory.py` | 768-dim nomic | EXISTS, unused by voice |
| `operator-patterns` | `shared/pattern_consolidation.py` | 768-dim nomic | EXISTS, unused by voice |
| `profile-facts` | `shared/profile_store.py` | 768-dim nomic | EXISTS, unused by voice |
| `axiom-precedents` | `shared/axiom_precedents.py` | 768-dim nomic | EXISTS, governance only |

All use `config.get_qdrant()` singleton client, `config.embed()` for embeddings, cosine similarity, Pydantic model payloads.

---

## Design

### Component 1: Tool Call Continuity

**Current**: Pre-tool text spoken immediately, then tool executes, then follow-up spoken. Message history has duplicate assistant entry.

**Proposed**: When LLM stream produces tool_calls, suppress the text portion from TTS. Play a bridge phrase ("Let me check on that") during tool execution. Speak only the post-tool follow-up response.

**Message history**: Remove unconditional `messages.append` at line 790 when tool calls are present. Only `_handle_tool_calls` appends the assistant message (once, with tool_calls structure included). This eliminates the duplicate.

**Changes**:
```
conversation_pipeline.py:
  - Line 790: Guard with `if not tool_calls_data:`
  - Lines 770-773: When tool_calls_data present, play bridge phrase instead of speaking accumulated text
  - No changes to _handle_tool_calls structure
```

### Component 2: Stable Conversational Frame

**Current**: System message rebuilt from scratch every turn. Model sees different "world" each turn.

**Proposed**: Split system message into STABLE FRAME (invariant within session) and VOLATILE CONTEXT (updated per turn, clearly demarcated).

**Stable frame** (top of system message, never changes within session):
- Base persona + tools + operator style (~1300 tokens)
- Conversation thread: incrementally-built running summary of established common ground

**Volatile context** (appended after stable frame, marked as "current turn"):
- Environment TOON
- Salience context (activation, novelty, concern overlap)
- Phenomenal context (temporal bands, stimmung)

**Thread tracking**: After each turn, append to `_conversation_thread`:
```
Turn N: Operator asked about [first clause of utterance]. Hapax responded about [first clause of response].
```

No LLM call needed -- mechanical extraction from the first clause of each side. ~15 tokens per turn, ~300 tokens at max turns.

**Changes**:
```
conversation_pipeline.py:
  - Add self._conversation_thread: str = "" at __init__
  - Update after each process_utterance completes
  - _update_system_context: inject thread in stable position, volatile context after
```

### Component 3: Cross-Session Memory

**Current**: Zero persistence. `_close_session` emits event log only.

**Proposed**: At session end, extract episodic summary and store in existing `operator-episodes` Qdrant collection. At session start, retrieve most recent episode and inject into system prompt.

**Session end extraction** (in `_close_session`, before `_stop_pipeline`):
- Take last 4 message pairs from `self.messages`
- Format as digest: "Discussed: [topics]. Key points: [what was established]. Operator sentiment: [positive/neutral/frustrated]."
- No LLM call -- mechanical extraction from message content
- Embed with `config.embed()`, store via `EpisodeStore.record()`

**Session start injection** (in `_start_conversation_pipeline`):
- Query `EpisodeStore.search()` with empty query (most recent)
- Inject into system prompt as "## Last Conversation" block
- Limit to 1-2 most recent episodes (~100 tokens)

**Changes**:
```
__main__.py:
  - _close_session: add _summarize_and_persist_session() call
  - _start_conversation_pipeline: add _load_recent_memory() call
conversation_pipeline.py:
  - Add get_session_digest() method for extraction
persona.py or conversation_pipeline.py:
  - Inject episode summary into system prompt
```

### Component 4: History Compression Replacement

**Current**: LLMLingua-2 compresses older messages at 0.33 rate into single "user" message in the middle of context.

**Proposed**: Replace lossy compression with the conversation thread summary (Component 2). Drop old messages entirely. The thread summary IS the distilled common ground, positioned at the TOP of context (system message) where attention is strongest.

**Changes**:
```
conversation_pipeline.py:
  - Remove or skip compress_history() call at line 620
  - Instead: drop messages older than keep_recent=5, rely on _conversation_thread
  - Thread in system message provides the "Lost in the Middle"-proof representation
```

---

## Interaction Between Components

```
                    Component 1                Component 2
                    Tool Continuity            Stable Frame
                    ─────────────              ────────────
                    Suppress pre-tool  ───────► Thread records
                    speech. Single              "Hapax checked
                    coherent response           system status,
                    after tool results.         found X."
                         │                          │
                         │                          │
                         ▼                          ▼
                    Component 4                Component 3
                    Compression Fix            Session Memory
                    ───────────────            ──────────────
                    Thread replaces            Thread summary
                    LLMLingua block.           persisted as
                    Old messages               episodic memory
                    dropped. Summary           at session end.
                    at TOP of context.         Loaded at start.
```

---

## What This Does NOT Change

- **Salience router**: Still computes activation/novelty/concern. Still injected as volatile context.
- **Cognitive loop**: Still tracks turn phase, temperature, engagement. Feeds into stable frame.
- **Perception system**: Still runs at 2.5s cadence. Environment context is volatile.
- **CANNED routing**: Still zero-latency phatic for "hey" / "thanks".
- **Intelligence-first**: Still always Opus for non-phatic.
- **Bridge engine**: Still pre-synthesizes phrases. Gains a new trigger point (tool call boundary).
- **Phenomenal context**: Still renders 6 layers. Stays in volatile section.
- **Axiom governance**: No axiom violations. Consent contracts still respected.

---

## Implementation Order

| Batch | Component | Scope | Dependencies |
|-------|-----------|-------|-------------|
| 1 | Tool call continuity | ~30 lines in conversation_pipeline.py | None |
| 2 | Stable conversational frame | ~60 lines in conversation_pipeline.py | None |
| 3 | Compression replacement | ~20 lines (mostly deletion) | Batch 2 |
| 4 | Cross-session memory | ~100 lines across __main__.py, conversation_pipeline.py | Batch 2+3 |

Each batch is independently testable via live voice session.

---

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Thread summary grows unbounded at 20 turns | Cap at ~400 tokens; oldest entries drop |
| Episodic memory retrieval adds latency to session start | Budget 200ms; async retrieval during bridge phrase |
| Suppressing pre-tool speech creates silence if bridge doesn't play | Bridge always plays for CAPABLE tier (already implemented) |
| Stale episodic memory injects irrelevant context | TTL on episodes (7 days); relevance filter via embedding similarity |
| Thread extraction misidentifies topics | First-clause extraction is robust; no LLM interpretation needed |

---

## Success Criteria

After all 4 components:

1. **Tool calls**: Operator hears bridge phrase → single coherent response with tool data. No speculation-then-correction.
2. **Cross-turn**: Operator can say "what were we just talking about?" and Hapax can answer from the thread.
3. **Cross-session**: Operator says "hey hapax" after 2 hours and Hapax says "Hey — last time we were debugging the voice pipeline. How's that going?"
4. **No context skipping**: Operator does NOT report feeling like Hapax "jumps between contexts" within a conversation.
