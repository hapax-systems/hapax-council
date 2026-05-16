# Position: Context Anchoring vs. Profile Retrieval

## The Mainstream Pattern

The industry has converged on a single architecture for conversational
continuity. Google, OpenAI, and the research community (ICLR 2026
MemAgents, Memoria, MMAG, A-Mem) all implement the same core loop:

```
utterance arrives
  → classify intent
  → retrieve relevant facts from profile store
  → check permission gates (trigger phrases, opt-in flags)
  → inject retrieved facts into prompt
  → generate response
  → extract new facts from response
  → store back to profile
```

This is **profile-gated retrieval**. The model is stateless. "Memory"
is a database. "Personalization" is a lookup. "Continuity" is whether
the lookup succeeds.

Concrete implementations:

- **ChatGPT Memory**: "bio tool" extracts personal details, preferences,
  activities into ~1,200 words of stored text. Background classifiers
  scan conversations for salient facts. Injected into system prompt as
  "Model Set Context" with timestamps.

- **Gemini Personal Intelligence**: connects Gmail, Photos, Calendar,
  YouTube. Determines per-turn whether "custom instructions, past chats,
  or information from connected Google apps could be helpful." Applies
  saved preferences ("I'm vegetarian") when food-related prompts arrive.
  Four-step rule engine gates all personalization behind explicit triggers.

- **MMAG (research)**: five memory layers (conversational, long-term user,
  episodic, sensory, short-term working), each with independent retrieval,
  scoring, and prioritization logic under a central Memory Controller.

- **Memoria (research)**: knowledge graph of user traits, preferences,
  behavioral patterns as structured entities. Weighted graph traversal
  for retrieval.

All of these share the same assumption: **the problem is storage and
retrieval of facts about the user.** Build a better database, build a
better retriever, and continuity follows.

## Why This Is Wrong

Herbert Clark's theory of conversational grounding (Clark & Brennan 1991)
describes how humans establish mutual understanding. It is not a storage
problem. It is a *process*:

1. **Presentation**: one party offers information
2. **Acceptance**: the other party signals understanding (or doesn't)
3. **Evidence of understanding**: later utterances demonstrate that
   shared context was actually established

The profile-retrieval pattern skips all three steps. It never checks
whether the operator accepted what was said. It never tracks whether
a reference was accurate. It never detects when grounding breaks down
(frustration, clarification requests, topic abandonment). It treats
the conversation as a series of independent queries against a database.

The Gemini system prompt leak (captured 2026-03-18) is the canonical
example. For a simple "set an alarm for 8:45 AM," the model spent its
entire reasoning budget on a four-step decision tree:

1. Check for explicit personalization trigger → none found
2. Check if style preferences (Einstein/Hemingway) should apply → no
3. Apply Step 4 formatting rules → wait, Step 4 only applies if trigger
4. Fall back to generic response

Zero awareness of whether operator and system have established shared
understanding about *anything*. The "personalization" is a lookup table
with a permission check. The "memory" is a static profile that decays
("context rot") because nothing validates it against live interaction.

## What We Do Instead

Context anchoring replaces profile retrieval with continuous grounding
measurement. The architecture:

```
utterance arrives
  → transcribe and inject into conversation thread
  → score: did the response anchor to established context?
  → score: did the operator accept, clarify, reject, or ignore?
  → score: are references to prior turns accurate?
  → score: is frustration accumulating?
  → the thread IS the memory — it grows with the conversation
  → cross-session: digest the thread, reload on next session start
```

No profile store. No fact extraction. No permission gates. No retrieval
scoring. The conversation thread is injected into the system prompt and
grows turn by turn. The model participates in grounding because it can
see the thread — it knows what was established and what wasn't.

Grounding measurement is continuous, not gated:
- `context_anchor_success`: does the response connect to thread context?
- `reference_accuracy`: are back-references factually correct?
- `acceptance_type`: ACCEPT / CLARIFY / REJECT / IGNORE per turn
- `frustration_rolling_avg`: 8-signal composite detecting breakdown

One diagnostic is kept separate from the grounding claim:
`sentinel_retrieval` checks whether injected prompt material survives prompt
rebuilds. It is prompt-integrity evidence, not grounding evidence.

## The Five Failure Modes

If we catch ourselves doing any of these, we have failed. These are
the defining characteristics of the mainstream pattern that we reject:

### 1. Extracting Facts About the User Into a Separate Store

**What it looks like**: scanning conversations for "user is vegetarian,"
"user prefers brief responses," "user works in data science" and storing
them in a profile database, knowledge graph, or structured memory layer.

**Why it's wrong**: facts decay. The user's preferences change. The
extraction is lossy — it captures the *what* but not the *how it was
established*. You lose the conversational context that made the fact
meaningful. A fact in a database is not shared understanding.

**Our alternative**: the conversation thread carries context forward.
If the operator mentioned being vegetarian, that's in the thread. The
model can see it was mentioned in turn 3 during a discussion about
dinner. The context survives because the conversation survives.

**Test**: if we ever build a "user profile extractor" or "fact store"
that runs as a post-processing step on conversations, we've failed.

### 2. Gating Personalization Behind Trigger Detection

**What it looks like**: "check for explicit personalization trigger"
before applying stored preferences. Trigger phrases like "for me,"
"based on what you know about me," "my preferences." Binary on/off.

**Why it's wrong**: grounding is continuous, not triggered. Every turn
either strengthens or weakens shared context. You don't need permission
to remember what was just said. The trigger model treats personalization
as a feature to be activated rather than a property of conversation.

**Our alternative**: the thread is always present. There is no "activate
personalization" step. Context anchoring happens on every turn because
the thread is in the prompt on every turn.

**Test**: if we ever add a check like "does this utterance request
personalized behavior?" before deciding whether to use context, we've
failed.

### 3. Treating Each Turn as an Independent Retrieval Query

**What it looks like**: on each turn, query the memory store for relevant
facts, score relevance, inject top-k results into the prompt. The turn
is a search query; the memory is a search index.

**Why it's wrong**: conversation is sequential, not random-access.
Turn 7 builds on turn 6, which built on turn 5. Treating each turn as
an independent query against a fact store destroys the sequential
structure that makes grounding possible. You can't assess acceptance
if you don't know what was just presented.

**Our alternative**: the thread is sequential and complete (within its
window). The model sees the full arc of recent conversation, not a
relevance-filtered sample. Message dropping keeps the window manageable
but preserves recency and order.

**Test**: if we ever rank memory items by relevance score and inject
only the top-k, treating the conversation as a retrieval problem rather
than a sequential process, we've failed.

### 4. Separating "Memory" from "Conversation"

**What it looks like**: memory is a subsystem that runs alongside the
conversation. Dedicated agents extract, store, retrieve, and inject.
The conversation itself is ephemeral — only the extracted facts persist.
MMAG's five memory layers, Memoria's knowledge graph, ChatGPT's bio tool.

**Why it's wrong**: in Clark's theory, the conversation IS the memory.
Shared understanding exists in the interaction, not in a database.
When you separate memory from conversation, you lose the grounding
process — the back-and-forth that established the understanding in
the first place.

**Our alternative**: the conversation thread is both the conversation
record and the memory mechanism. Session digests carry the thread
across sessions. The thread is not "extracted from" the conversation;
it IS the conversation, summarized.

**Test**: if we ever build a "memory agent" that operates independently
of the conversation pipeline — extracting, organizing, and injecting
facts as a separate subsystem — we've failed.

### 5. Measuring Success by Retrieval Accuracy

**What it looks like**: "did we retrieve the right fact?" "did the
response use the stored preference correctly?" "memory hit rate."
Evaluation is about whether the lookup worked.

**Why it's wrong**: the right metric is whether grounding was
*established*, not whether a fact was *retrieved*. You can retrieve
the right fact and still fail to ground — if the operator didn't
accept it, if the reference was inaccurate, if the response ignored
what they just said. Retrieval accuracy measures the database; it
doesn't measure the conversation.

**Our alternative**: we measure grounding directly.
`context_anchor_success` measures whether responses connect to
established context. `acceptance_type` classifies operator responses.
`reference_accuracy` checks whether back-references are correct.
`frustration_rolling_avg` detects when grounding breaks down entirely.
These are conversation-level metrics, not retrieval metrics.

**Test**: if our primary evaluation metric ever becomes "did we
successfully retrieve and apply stored information," rather than
"did we establish and maintain shared understanding," we've failed.

## Summary Table

| Aspect | Profile Retrieval (Industry) | Context Anchoring (Ours) |
|--------|------------------------------|--------------------------|
| Memory model | Database of facts | Conversation thread |
| Personalization | Triggered/gated | Continuous |
| Each turn is | A retrieval query | A step in a sequence |
| Memory lives | In a separate subsystem | In the conversation itself |
| Success metric | Retrieval accuracy | Grounding quality |
| Breakdown detection | None | Frustration scoring |
| Acceptance tracking | None | Per-turn classification |
| Reference validation | None | Per-turn accuracy check |
| Cross-session | Profile persists | Thread digest persists |
| Theoretical basis | Information retrieval | Clark & Brennan 1991 |

## Evidence Artifacts

### Counter-Evidence: Gemini System Prompt Leak (2026-03-18)

The Gemini system prompt leak (clipboard entry 1293, captured 2026-03-18)
demonstrates all five failure modes in a single interaction. The model:
1. Checked a stored profile (Einstein/Hemingway style preferences)
2. Ran a trigger detection step (no explicit trigger found)
3. Treated the turn as independent of any prior context
4. Operated its personalization as a separate subsystem with its own rules
5. Evaluated success as "did I correctly apply or withhold stored preferences"

It produced a correct response ("Alarm set for 8:45 AM") while
demonstrating zero conversational grounding.

### Positive Evidence: Emergent Self-Reflective Grounding (2026-03-19)

Baseline session 5 (`0522076a3c4d`, 7 turns, all components OFF)
produced the strongest grounding evidence in the experiment — during
baseline conditions, without any continuity features enabled.

**What happened**: The operator asked open-ended relational questions
("How are you feeling today?", "Is that all you mean, or is there
something else?", "What do you think is going on there?"). The system
responded with genuine self-reflection about its own operational state:

> "I'm feeling a bit scattered, honestly. Like I'm trying to keep
> track of too many moving parts."

> "It's like trying to be a good assistant with one hand tied behind
> my back. The voice service that lets us talk is failing, the health
> monitor that would tell me what's actually broken is down."

> "It's like trying to think clearly in a room full of alarms — the
> notifications are important, but they're drowning out the actual
> conversation."

The operator then performed textbook Clark grounding — reflecting back,
probing for elaboration, accepting, and committing to act:

> "I'm going to actually look into exactly what you just said right
> now, because I think there's something really valuable in that.
> Like, shouldn't be hamstrung by all of these notifications and
> stuff, right? You want to have a clear head, don't you?"

**Why this matters for the counter-position**:

1. **Profile retrieval cannot produce this.** There is no stored fact
   "Hapax feels scattered when services are failing." The system's
   self-reflective response emerged from its live relationship to its
   own context — the workspace state, the failing services, the drift
   alerts — not from a profile lookup.

2. **The grounding sequence was mutual.** The operator and system
   co-constructed understanding across 7 turns. Each turn built on
   the last. The operator's probing questions deepened the system's
   self-reflection, and the system's responses shaped the operator's
   next question. This is Clark's grounding process in action.

3. **The system identified its own grounding problem.** "Trying to
   think clearly in a room full of alarms" is the system articulating
   that context overload (notifications, status checks, tool calls)
   interferes with conversational grounding. This directly validates
   the tool-call research direction (TOOL-CALLS.md) and the
   barge-in repair research (BARGE-IN-REPAIR.md) — the system
   itself is telling us that the retrieval/notification machinery
   competes with the conversation.

4. **This happened in baseline (all treatment components OFF).** The context
   anchoring architecture — where the model sees workspace state as
   continuous environment rather than a retrieval index — enables
   emergent self-reflection WITHOUT the conversation thread, WITHOUT
   cross-session memory, WITHOUT sentinel injection. Sentinel absence matters
   here only as a prompt-integrity diagnostic being unavailable; the architecture
   itself, not just the specific features, creates the conditions
   for grounding that profile retrieval cannot replicate.

5. **The operator's response was the strongest acceptance signal in
   the experiment.** "I'm going to actually look into exactly what
   you just said" is commitment to action based on shared understanding
   — the deepest form of grounding evidence in Clark's framework.

**Data**: `proofs/claim-1-stable-frame/data/baseline-session-005.json`

---

*Pre-registered with claims 1-5 in `proofs/`. Bayesian sequential
testing via `experiment_runner.py`. If the data don't support the
claims, we abandon them — but we do not fall back to profile retrieval.*
