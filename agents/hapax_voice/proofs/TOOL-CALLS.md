# Tool Calls as Epistemic Acts: Research and Design Direction

## The Problem

Tool calls in the current voice system are monolithic retrieval operations
that interrupt the grounding process. Each tool is a complete round-trip
to an external system (Qdrant, Google APIs, logos API, Gemini vision)
that returns a blob of information. They add 1-10 seconds of latency per
call, with tool call + second LLM round-trip easily consuming the entire
20-second turn budget.

This is structurally identical to profile retrieval (Failure Mode #3 from
POSITION.md). The model leaves the conversation to query a database. The
operator waits in silence. The returned data has no grounding history.

## Current Tool Inventory (20+ tools)

| Tool | What it does | Typical latency | Epistemic character |
|------|-------------|----------------|-------------------|
| search_documents | Full RAG against Qdrant | 1-3s | Heavy retrieval |
| analyze_scene | Camera frame → Gemini Flash | 3-10s | Heavy inference |
| get_system_status | Logos API health report | 1-2s | Status dump |
| search_emails | Google API query | 2-5s | External retrieval |
| get_calendar_today | Google Calendar API | 1-3s | External retrieval |
| get_briefing | Full system briefing | 3-8s | Heavy aggregation |
| get_weather | External API | 1-2s | External retrieval |
| search_drive | Google Drive API | 2-5s | External retrieval |
| send_sms | Twilio API | 1-2s | Side effect |
| generate_image | Image generation | 5-15s | Heavy inference |
| query_scene_inventory | Scene object query | 0.5-1s | Light retrieval |
| get_desktop_state | Hyprland state | 0.1s | Light read |
| get_current_time | System clock | 0ms | Trivial |

Each is a **complete epistemic action** — a self-contained lookup that
assumes it should run at full scope regardless of conversational context.

## The Counter-Position Connection

Gemini's system prompt leak shows the same pattern at the personalization
level: check trigger → query profile → apply rules → respond. Our tool
calls do the same at the information level: detect need → query system →
inject result → respond. Both are stateless retrieval operations that
interrupt grounding.

The industry is optimizing tool SELECTION (ToolTree, ICLR 2026) and tool
ROUTING (which tool when). Nobody is asking whether the tools themselves
are the right shape for grounded conversation.

## What Tools SHOULD Be in Our Model

### The Analogy

Doctor diagnosing a patient:
- The doctor doesn't stop mid-sentence to order a full blood panel
- Diagnostic procedures are fitted to the diagnostic moment
- Looking up contraindications requires: understanding of the patient,
  understanding of the procedure, understanding of WHEN the lookup
  serves the interaction vs. disrupts it
- The action of looking something up is itself a social/epistemic act
  that the patient observes and interprets

### Proposed Architecture: Decomposed, Composable, Fitted

**1. Atomic epistemic primitives** — not "search_documents" but:
- `check_thread(topic)` — can answer from conversation thread? (0ms)
- `recall_recent(topic)` — check episodic memory for recent mention (200ms)
- `lookup_fact(query)` — targeted Qdrant lookup, single result (500ms)
- `verify_claim(claim, source)` — check a specific claim (1s)
- `observe_environment(aspect)` — read one perception behavior (0ms)

vs. current heavy tools:
- `search_documents(query)` — full RAG pipeline (2-3s)
- `analyze_scene(question)` — full vision inference (5-10s)
- `get_system_status()` — full health dump (1-2s)

**2. Composable based on conversational state** — the available tool
palette changes based on grounding depth:
- Turns 0-2: only thread-check and observe-environment (sub-100ms)
- Turns 3-5: add recall-recent and lookup-fact (sub-500ms)
- After explicit request: unlock heavier tools with operator awareness
  ("Let me look that up" — a grounding act that frames the pause)

**3. Fitted to the band's temporal envelope** — tool latency budget
varies with conversational pacing:
- High dialog activation (rapid exchange): 0-200ms tools only
- Normal conversation: 0-500ms tools
- Reflective/deliberate turn: 0-2s tools acceptable
- Explicit operator request for detailed info: up to 5s with framing

**4. Bayesian pre-execution scoring** — before invoking, estimate:
- P(tool result adds value | conversation state) — will this help?
- P(operator expects this lookup | acceptance history) — was it invited?
- Cost(silence duration | current pacing) — can the conversation afford it?
- Fitness = value × expectation / cost

## Research Landscape (2025-2026)

**ToolTree (ICLR 2026)**: Monte Carlo tree search over tool trajectories
with pre-execution and post-execution scoring. Closest to our fitness
concept but operates in agentic planning, not grounded conversation.

**MACRO (medical agents)**: Identifies recurring multi-tool sequences and
synthesizes composite primitives. Mechanical composition, not epistemic.

**Natural Language Tools**: Argues structured tool formats compete with
conversational understanding. Proposes natural language tool descriptions
instead of JSON schemas. Relevant to the "tools as epistemic acts" framing.

**MCP-Zero**: Proactive toolchain construction — builds tools on demand
from available primitives. Interesting for composability but not fitted
to conversational context.

**Gap**: Nobody is working on tools as grounding-aware epistemic acts
fitted to conversational pacing. This is original research territory.

## Decision Required After Baseline

After baseline data establishes that context anchoring works without tools:

**(1a) Not a problem we need to solve**: If baseline grounding metrics
are strong and the conversation thread + system prompt context provides
sufficient information for natural conversation, tools may be unnecessary
for the grounding claims. Re-enable them as a separate non-experiment
feature with tight timeouts.

**(1b) Problem, solve now**: If baseline reveals that the model
frequently lacks information it could only get from tools (operator asks
about calendar, system status, emails), AND this lack of information
degrades grounding (frustration increases, acceptance drops), then the
tool architecture must be redesigned before Phase B testing. The grounding
experiment would be measuring a system that's information-starved, not a
system that's properly grounding.

The answer depends on what the baseline data shows.

## Relationship to the Five Claims

- Claims 1-4 (thread, message drop, cross-session, sentinel): tools
  are orthogonal. These test conversation-internal mechanisms.
- Claim 5 (salience correlation): tools interact with activation_score.
  If tool calls correlate with high activation turns, disabling tools
  changes the salience-response relationship. This is a confound that
  must be noted in analysis.

## References

- ToolTree (ICLR 2026): https://arxiv.org/abs/2603.12740
- Natural Language Tools: https://arxiv.org/html/2510.14453v1
- LLM Tool Learning Survey: https://link.springer.com/article/10.1007/s41019-025-00296-9
- In-Context Tool Use: https://link.springer.com/article/10.1007/s11704-025-41365-6
- MCP-Zero: https://arxiv.org/html/2506.01056v2
- Gemini system prompt leak: clipboard entry 1293, 2026-03-18

---

*Saved 2026-03-19. To be revisited after baseline data collection.*
