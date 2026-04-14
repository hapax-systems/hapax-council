# Phase 5 — Cognitive-loop T3 formulation redesign scoping

**Queue item:** 026
**Phase:** 5 of 6
**Date:** 2026-04-13 CDT
**Register:** scientific, neutral (per `feedback_scientific_register.md`)

## Headline

**Recommendation: Pattern 3 (rolling context cache with
provider-side prompt caching) is the lowest-friction retrofit**
for making T3 formulation feel continuous without multiplying
LLM cost. It does not require a new always-running LLM call (which
the request-response LLM API cannot support). It reduces the
per-turn cold-start cost from "assemble + send full context" to
"send cache-hit markers + the new turn's delta." Anthropic's
prompt cache gives 90% latency reduction on cache hits; LiteLLM
passes `cache_control` through for providers that support it.

Pattern 1 (streaming always-on LLM) is **structurally incompatible**
with the existing LLM client layer — LLM APIs are call/response.
Pattern 2 (speculative formulation) is viable but multiplies LLM
cost by the impingement rate (20–50x), which makes it only
appropriate as a narrow enhancement for high-salience impingement
windows, not a general continuous-formulation replacement.

Pattern 3 is the cheapest retrofit, aligns with the existing
`self.messages` message list + `litellm.acompletion(stream=True)`
surface, and delivers the operator-visible "warm cognitive loop"
feeling without re-architecting the pipeline.

## Current cold-start path (evidence)

`agents/hapax_daimonion/conversation_pipeline.py`:

### Entry

```text
ConversationPipeline.process_utterance(audio_bytes)  at line 471
  → _process_utterance_inner(audio_bytes, _utt_trace, _t_start)  at line 501
    → STT: self.stt.transcribe(audio_bytes)
    → echo rejection
    → consent filter (post-PR #761)
    → salience router (output structurally rewritten to CAPABLE)
    → _generate_and_speak()  at line 929
```

### The LLM call

```python
# conversation_pipeline.py:929-1013
async def _generate_and_speak(self) -> None:
    import litellm

    # Message history bounding (line 941-952):
    #   drop old turns, keep system + last 5 exchanges
    if self._experiment_flags.get("message_drop", True) and len(self.messages) > 12:
        system_msg = self.messages[0]
        user_count = 0
        cut_idx = len(self.messages)
        for i in range(len(self.messages) - 1, 0, -1):
            if self.messages[i].get("role") == "user":
                user_count += 1
                if user_count >= 5:
                    cut_idx = i
                    break
        recent = self.messages[cut_idx:]
        self.messages = [system_msg] + recent

    # Phenomenal context for LOCAL tier (line 957-982)
    # ... (identity + orientation overlay)

    kwargs = {
        "model": f"openai/{_model}",
        "messages": _messages,
        "stream": True,
        "max_tokens": ...,
        "temperature": 0.7,
        "api_base": _voice_litellm_base,
        "api_key": os.environ.get("LITELLM_API_KEY", "not-set"),
        "timeout": 15,
    }
    if self.tools:
        kwargs["tools"] = [...]  # recruitment-gated

    response = await litellm.acompletion(**kwargs)  # line 1013

    # stream loop consumes chunks, synthesizes TTS, plays audio
    ...
```

**Key observations:**

1. **`self.messages` is persistent across turns** within a session.
   The message list is bounded (system + last 5 exchanges) but
   not rebuilt from scratch. The LLM sees the ongoing conversation
   history on every call.
2. **The acompletion call is request/response**, not a
   long-running generator. `stream=True` streams the RESPONSE
   tokens (as they arrive), but the prompt side is a single-shot
   send.
3. **Timeout is 15 seconds**. Short enough that a blocked LLM call
   doesn't wedge the daimonion but long enough for most
   completions.
4. **Three litellm.acompletion call sites** in conversation_pipeline.py:
   line 231 (grounding evaluator), line 1013 (main formulation),
   line 1759 (another formulation path — needs investigation).
   None of them runs continuously.
5. **No background LLM call between turns.** The daimonion's
   continuous work (CPAL tick, impingement consumer, perception
   updates) happens in coroutines that never call the LLM. The
   LLM is purely turn-bounded.

## Idle window characterization

Between utterance N and utterance N+1, the system does:

**Continuous (control-layer cognition, from queue 025 Phase 3):**
- CPAL ticks at 150 ms
- Gain controller updates
- Grounding snapshot reads
- Stimmung reads
- Impingement consumer polls and surfaces notifications

**Not running:**
- LLM formulation
- KV cache warming (no LLM call → no KV cache touched)
- Message history buildup (self.messages is already built,
  just waiting for the next append)

**Client connection state:**
- litellm uses requests/httpx under the hood
- Connection pool KEEPS HTTP/2 sessions alive across calls
  (litellm does NOT close the underlying transport between
  acompletion calls on the same router)
- Between turns, the TCP + TLS handshake is already done — the
  next acompletion call uses the existing connection

**So "cold start" is actually only in the LLM side:**

- TCP/TLS: warm
- HTTP/2 session: warm
- Client library: warm
- System prompt: already in `self.messages`
- Turn context: already appended over session lifetime
- LLM KV cache: **cold** (the LLM has no memory of the last turn
  unless prompt caching is enabled)
- First token latency: **cold** (new LLM context = full prompt
  processing)

## Candidate pattern survey

### Pattern 1 — Streaming always-on LLM (rejected)

**Idea:** keep one long-running LLM call that accepts new tokens
from the operator as they arrive. The LLM is continuously
"listening" with a streaming input.

**Problem:** LLM APIs (Anthropic, OpenAI, LiteLLM) are
**request-response**. The client sends a prompt, the API streams
the response, the connection closes at response end. There is no
"streaming input while receiving output" primitive in any current
API. The closest is OpenAI's new Realtime API (GPT-4o real-time
audio), which is a bidirectional audio-in/audio-out pipe — but:

- Anthropic doesn't have an equivalent yet
- Realtime API does not fit into the daimonion's existing
  litellm-based architecture without major rewrites
- Realtime API does not support `pydantic-ai` agents
- The operator's `feedback_model_routing_patience` memory says
  "CAPABLE tier = best Claude model" — switching to OpenAI
  Realtime for audio conflicts with the current model choice

**Verdict:** rejected. Not structurally compatible with current
architecture.

### Pattern 2 — Speculative formulation (viable but expensive)

**Idea:** on every new impingement arrival (or every N seconds),
kick off a background LLM call that asks "if the operator spoke
next, what would they most likely say, and what should I say in
response?" The background call uses the current context. If the
next actual utterance matches the prediction, use the prepared
response (warm hand-off). If not, discard.

**Pros:**
- Genuinely reduces turn latency for predicted cases
- Pairs naturally with CPAL's existing impingement surfacing
  (which queue 025 Phase 3 established happens ~150/10 min = 15
  impingements/min)

**Cons:**
- **Cost multiplier: 15–50x LLM calls per conversation** (one
  per impingement vs one per turn). Even with prompt caching, the
  input side is cheap but output generation costs the full token
  rate.
- **Hit rate uncertainty**: matching predicted utterance to
  actual utterance is hard. If the hit rate is <20%, most
  speculations are wasted.
- **Cache pollution**: every speculation writes to the KV cache,
  evicting potentially useful turns
- **Privacy risk**: speculating about the operator's next
  utterance generates LLM output about what the operator might
  say. If the speculation is logged to Langfuse (the default),
  that's a lot of hypothetical operator speech in the trace
  store.

**Verdict:** viable as a narrow enhancement — not a general
replacement. Could be enabled only during high-salience
impingement windows (e.g., when exploration_deficit is high or
stimmung is SEEKING), amortizing the cost. File as a follow-up
ticket.

### Pattern 3 — Rolling context cache with prompt caching (recommended)

**Idea:** use provider-side prompt caching (Anthropic API
`cache_control` markers) to make the system prompt + recent
context cacheable. Between turns, the LLM doesn't run — but when
a turn comes, the cached portion of the prompt is a no-op lookup
on the LLM side, and only the new turn content is actually
processed.

**Anthropic's prompt cache** (as of May 2024+) supports:
- 5-minute TTL cache entries (just enough to cover inter-turn
  idle)
- Read cache: 10% of normal input token cost (90% reduction)
- Write cache: 125% of normal input token cost (one-time upfront)
- Cache control at the message-block level — you mark which
  content is cacheable and which is new per-turn

LiteLLM passes `cache_control` through to Anthropic. The
existing `self.messages` list just needs to be structured to
mark the system prompt + recent messages as cacheable:

```python
# In _generate_and_speak, before the acompletion call:
_messages = self.messages
# Mark the system prompt + last N-2 messages as cacheable.
# The last 2 messages (the new user utterance and the assistant
# response slot) are fresh and don't participate in the cache.
if len(_messages) >= 3 and _messages[0].get("role") == "system":
    _cached_messages = []
    for i, m in enumerate(_messages[:-2]):  # all but the last 2
        new_m = dict(m)
        if i == 0:
            # System prompt: always cache control
            new_m["content"] = [
                {"type": "text", "text": m["content"], "cache_control": {"type": "ephemeral"}}
            ]
        new_m["_cache_hint"] = True  # for telemetry
        _cached_messages.append(new_m)
    _messages = _cached_messages + _messages[-2:]

response = await litellm.acompletion(
    model=f"openai/{_model}",
    messages=_messages,
    stream=True,
    # ... (rest of kwargs)
)
```

**Pros:**
- Zero new LLM calls — the cost model is **lower** than current,
  not higher
- Warm KV cache = faster first-token latency on subsequent
  turns (claim: 90% reduction per Anthropic's docs)
- Already compatible with LiteLLM + Anthropic + the existing
  `self.messages` + `self.tools` surface
- No restructure of the CPAL runner needed
- The "cognitive loop continuity" experience the operator feels
  comes from two things in combination: (a) the existing
  continuous control layer at 150 ms, (b) the now-warm LLM
  formulation layer that feels contextually coherent because
  the cache tracks the session's history

**Cons:**
- Requires Anthropic-backed models (works for Opus, Sonnet,
  Haiku); OpenAI-compatible models may not support the same
  cache markers
- The system prompt has to be stable enough to be cacheable —
  dynamic parts (stimmung, time of day, phenomenal context)
  need to be moved OUT of the system message into a
  lower-priority user message that's NOT cached
- 5-minute TTL means the cache evicts during long idle periods
  — but CPAL already ticks every 150 ms and impingements arrive
  every ~2 s, so the inter-utterance gap is rarely 5+ minutes
  in a live session

**Verdict:** **recommended**. Lowest cost, highest alignment with
the existing architecture, delivers the operator-visible effect
("Hapax remembers what we just talked about, responds fast")
without requiring new LLM call paths.

## Stimmung-driven gating design

Per `project_intelligence_first` memory: *"Always CAPABLE;
salience router becomes context annotator; intelligence is last
thing shed under stimmung."*

Pattern 3 interacts with stimmung as follows:

- **Under nominal / cautious / alert stimmung:** full cache
  active, CAPABLE model, standard latency
- **Under critical stimmung:** consider cache control OFF
  (force fresh context) — critical states may want the LLM to
  re-read the system prompt with fresh attention rather than
  hitting a cached version that might miss a crisis signal.
  **Counter-argument:** stale cache is 5 minutes max, and the
  system prompt itself wouldn't have changed. Re-reading is
  ~10% savings of no value. Keep cache on.
- **Under seeking stimmung:** cache on, but allow Pattern 2
  (speculative formulation) to fire during the seeking window.
  This is where the "speculative" cost multiplier is worth
  paying — the system has decided it wants to explore, so
  spending LLM budget on anticipation is aligned with the
  stance.

**Recommendation: Pattern 3 always on, Pattern 2 gated by
stimmung=SEEKING.** Default cost is lower than today; seeking
windows opt into higher cost.

## Cost model

### Current (cold-start)

Per turn:
- 1 acompletion call
- Full prompt input = system (~1000 tok) + recent messages
  (~500 tok) = 1500 tok input
- Output ~300 tok
- Cost at Opus rates: 1500 × $15/M in + 300 × $75/M out =
  $0.0225 + $0.0225 = **~$0.045 per turn**

### Pattern 3 (cache hit)

Per turn, assuming 2nd+ turn within 5 minutes:
- 1 acompletion call
- Cached input: 1400 tok at 10% = 140 tok equivalent cost
- Fresh input: 100 tok (last user utterance + framing)
- Output ~300 tok
- Cost: 140 × $15/M + 100 × $15/M + 300 × $75/M =
  $0.0021 + $0.0015 + $0.0225 = **~$0.026 per turn**

**Savings: ~42% per turn on input cost.** First-turn write is
125% of normal but amortized over the session lifetime.

### Pattern 2 (speculative, expensive case)

Per conversation cycle (assume 1 turn per 30 s, 15 impingements
per minute):
- 1 acompletion for actual turn = $0.045
- 15 speculation acompletions per minute × 2 minutes idle = 30
  speculation calls at $0.045 = $1.35
- Total per turn: **$1.395 (31x current)**

Amortized by hit rate: if speculation hits 20% of the time,
effective cost is ~$0.28 per turn (6.2x current). Even the
best-case is multiples more expensive than current.

**Pattern 2 only makes sense as a stimmung=SEEKING gate**, and
even then the operator should see the cost tradeoff clearly.

## The recommended shape

Ship three changes, in order:

### Change 1 — system prompt restructure (pre-req for Pattern 3)

The current system prompt likely includes dynamic parts
(stimmung, phenomenal context, timestamp) that would be stripped
from the cache each turn. Restructure:

- **Cacheable system prompt**: identity, instructions, tool
  descriptions, conversation protocol. Stable across turns.
- **Dynamic environment context**: stimmung dimensions, time of
  day, activity mode. Moved into a separate `system` or
  high-priority `user` message AFTER the cacheable block but
  BEFORE the turn messages.

Sketch:

```python
def build_messages(self) -> list[dict]:
    messages = []
    # 1. Cacheable identity + instructions
    messages.append({
        "role": "system",
        "content": [
            {
                "type": "text",
                "text": IDENTITY_PROMPT + INSTRUCTIONS_PROMPT + TOOL_PROTOCOL_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
    })
    # 2. Fresh environment context (NOT cached — changes per turn)
    messages.append({
        "role": "system",
        "content": self.env_context_fn(),  # stimmung, time, activity
    })
    # 3. Rolling message history (bounded to last N turns)
    messages.extend(self._rolling_history())
    # 4. Current user utterance (appended by caller)
    return messages
```

**Effort:** ~50 lines in `conversation_pipeline.py` +
~40 lines in `pipeline_start.py` or wherever the system prompt
is assembled.

### Change 2 — `_generate_and_speak` adds cache_control markers

Wrap the existing `self.messages` with cache markers as shown
above. Verify LiteLLM passes them through to Anthropic.

**Effort:** ~20 lines, localized to `_generate_and_speak`.

### Change 3 — telemetry

- Log `_cache_hint=True` for the cached portion
- Add `hapax_llm_cache_hit_ratio` gauge
- Add `hapax_llm_cache_input_tokens_cached_total` counter
- Langfuse trace metadata includes cache state

**Effort:** ~30 lines. Depends on PR #760 + queue 024 Phase 2
Prometheus scrape fix for visibility.

### Out of scope (later tickets)

- Pattern 2 (speculative formulation under SEEKING stimmung):
  design complete, implementation is a separate PR
- Pattern 1 (streaming always-on LLM): rejected outright
- Long-form conversation memory beyond 5 min cache TTL: use
  `operator-episodes` Qdrant retrieval (already implemented)

## Alpha implementation notes

The recommended change set is **~100 lines across 3 files,
low-risk, reversible**. Alpha should read the design doc,
implement changes 1 + 2 in one PR, add telemetry in a follow-up,
and measure the first-token latency delta on the next voice
session.

**Expected outcome:** first-token latency drops ~40–60% on
cache hits (2nd+ turn within 5 min). The operator feels a
"warm cognitive loop" without any new LLM call paths. Cost
drops ~42% per cached turn. Pattern 2 SEEKING gate remains as
a future enhancement when the operator wants anticipatory
behavior.

## Backlog additions (for round-5 retirement handoff)

156. **`feat(daimonion): system prompt restructure for prompt caching`** [Phase 5 Change 1] — separate cacheable identity+instructions from dynamic env context. ~50 lines. Prerequisite for Pattern 3.
157. **`feat(daimonion): add cache_control markers in _generate_and_speak`** [Phase 5 Change 2] — ~20 lines. Pairs with 156.
158. **`feat(daimonion): hapax_llm_cache_hit_ratio + cache_input_tokens_cached_total telemetry`** [Phase 5 Change 3] — ~30 lines. Depends on FINDING-H scrape fix landing.
159. **`research(daimonion): measure first-token latency delta post-cache`** [Phase 5 validation] — pair with a voice session; compare pre-cache vs post-cache cold-start cost.
160. **`feat(daimonion): Pattern 2 speculative formulation under stimmung=SEEKING`** [Phase 5 deferred] — separate PR after Pattern 3 is proven. Gated by stimmung stance so the cost multiplier is opt-in to the seeking stance.
161. **`docs(feedback_cognitive_loop): refine memory to distinguish control vs formulation`** [Phase 5 memory refinement, carry-over from queue 025 Phase 3] — the feedback memory says "cognition runs continuously not cold-start" — clarify this is partially satisfied (control continuous, formulation now warm-cached but still turn-bounded).
