# Hapax-Daimonion Full Treatment

**Date:** 2026-03-29
**Status:** Design
**Context:** Reverie received end-to-end treatment (dynamic shader pipeline, 51 WGSL nodes, content textures, temporal feedback). Daimonion needs the same — every capability online, formally modeled, verified end-to-end.

## Problem

Daimonion is running healthy but incomplete. Tool execution disabled. Grounding system behind experiment flag. No explicit TPN↔DMN signaling. Tools are a flat list of ad-hoc handlers — not modeled as capabilities in the Hapax meta-structure. The system works but does not cohere.

## Principle

Every tool is a capability. Capabilities in Hapax follow a universal recruitment protocol: Submission → Selection → Gating. Speech is recruited by salience. Visual expression is recruited by stimmung. Perception backends register with a formal protocol (name, provides, tier, available, contribute). Tools must conform to the same meta-structure.

This pass (queue #016) establishes formal capability registration, gating, and degradation for tools. A subsequent pass (queue #015, deferred until validation sprint telemetry) will replace LLM-menu selection with full affordance-based recruitment.

## Workstream 1: Tool Capability Model

### ToolCapability Interface

```python
class ToolCategory(enum.Enum):
    INFORMATION = "information"   # reads state, no side effects
    ACTION = "action"             # side effects (send, generate)
    CONTROL = "control"           # desktop/device manipulation

class ResourceTier(enum.Enum):
    INSTANT = "instant"   # <100ms, no external calls
    LIGHT = "light"       # <3s, API call or local query
    HEAVY = "heavy"       # >3s or GPU-intensive


@dataclass
class ToolCapability:
    name: str
    description: str
    schema: dict                        # OpenAI function-calling format
    handler: Callable                   # async (args: dict) -> str

    category: ToolCategory
    resource_tier: ResourceTier
    requires_consent: list[str]         # axiom IDs (e.g., ["interpersonal_transparency"])
    requires_backends: list[str]        # backend names (e.g., ["vision", "phone"])
    requires_confirmation: bool         # two-step execution
    timeout_s: float = 3.0

    def available(self, ctx: ToolContext) -> bool:
        """Check all preconditions."""
        if ctx.stimmung_stance in ("degraded", "critical") and self.resource_tier == ResourceTier.HEAVY:
            return False
        if ctx.guest_present and self.requires_consent:
            return False
        if self.requires_backends and not all(b in ctx.active_backends for b in self.requires_backends):
            return False
        if ctx.working_mode == "research" and not ctx.experiment_tools_enabled:
            return False
        return True

    def degrade(self) -> str:
        """Fallback message when unavailable."""
        return f"The {self.name} capability is not available right now."
```

### ToolContext

```python
@dataclass
class ToolContext:
    stimmung_stance: str            # nominal/cautious/degraded/critical
    consent_state: dict             # active consent contracts
    guest_present: bool
    active_backends: set[str]       # currently available perception backends
    working_mode: str               # research/rnd
    experiment_tools_enabled: bool  # from experiment flags
```

### ToolRegistry

```python
class ToolRegistry:
    """Manages tool capabilities with dynamic availability filtering."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolCapability] = {}

    def register(self, tool: ToolCapability) -> None:
        self._tools[tool.name] = tool

    def available_tools(self, ctx: ToolContext) -> list[ToolCapability]:
        return [t for t in self._tools.values() if t.available(ctx)]

    def schemas_for_llm(self, ctx: ToolContext) -> list[dict]:
        return [t.schema for t in self.available_tools(ctx)]

    def handler_map(self, ctx: ToolContext) -> dict[str, Callable]:
        return {t.name: t.handler for t in self.available_tools(ctx)}
```

### Tool Classification (26 tools)

| Tool | Category | Resource | Consent | Backends | Confirm |
|------|----------|----------|---------|----------|---------|
| get_current_time | INFORMATION | INSTANT | — | — | No |
| get_weather | INFORMATION | LIGHT | — | — | No |
| get_briefing | INFORMATION | LIGHT | — | — | No |
| get_system_status | INFORMATION | LIGHT | — | — | No |
| get_calendar_today | INFORMATION | LIGHT | — | — | No |
| get_desktop_state | INFORMATION | INSTANT | — | hyprland | No |
| search_documents | INFORMATION | LIGHT | — | — | No |
| search_drive | INFORMATION | LIGHT | corporate_boundary | — | No |
| search_emails | INFORMATION | LIGHT | corporate_boundary | — | No |
| check_consent_status | INFORMATION | INSTANT | — | — | No |
| describe_consent_flow | INFORMATION | INSTANT | — | — | No |
| check_governance_health | INFORMATION | LIGHT | — | — | No |
| analyze_scene | INFORMATION | HEAVY | interpersonal_transparency | vision | No |
| query_scene_inventory | INFORMATION | LIGHT | interpersonal_transparency | vision | No |
| generate_image | ACTION | HEAVY | — | — | No |
| send_sms | ACTION | LIGHT | — | phone | Yes |
| highlight_detection | CONTROL | INSTANT | — | vision | No |
| set_detection_layers | CONTROL | INSTANT | — | vision | No |
| focus_window | CONTROL | INSTANT | — | hyprland | No |
| switch_workspace | CONTROL | INSTANT | — | hyprland | No |
| open_app | CONTROL | LIGHT | — | hyprland | Yes |
| close_window | CONTROL | INSTANT | — | hyprland | No |
| move_window | CONTROL | INSTANT | — | hyprland | No |
| resize_window | CONTROL | INSTANT | — | hyprland | No |
| phone tools (5+) | INFORMATION/ACTION | LIGHT | — | phone | Varies |

### Async Tool Execution

The existing `_handle_tool_calls()` method in conversation_pipeline.py is complete: bridge phrase playback, consent filtering, tool result formatting, follow-up generation. Three changes enable it:

1. **Un-comment tool schema passing** (line 1233-1234): `kwargs["tools"] = tools` — but `tools` is now the dynamically filtered list from `ToolRegistry.schemas_for_llm(ctx)`.
2. **Replace skip block** (lines 1428-1436): call `await self._handle_tool_calls(tool_calls_data, full_text)` instead of logging and skipping.
3. **Add per-tool timeout** inside `_handle_tool_calls`: wrap each handler call with `asyncio.wait_for(handler(args), timeout=tool.timeout_s)`.

These three changes touch frozen code. File DEVIATION-026 (functional change: enables existing tool execution path with timeout safety).

**Async flow:**
1. LLM response streams. If it contains tool calls, pipeline extracts them.
2. Pipeline speaks the natural language portion immediately (bridge phrase from BridgeEngine if no text).
3. Tools execute sequentially with per-tool timeout (existing handler loop).
4. Results fold into messages as tool role entries.
5. Follow-up `_generate_and_speak()` incorporates results.
6. Timeout or failure → dead-letter log + "tool unavailable" message in results.

**Dynamic tool list construction** happens in `__main__.py` (not frozen) where the pipeline is created. The `ToolContext` is built from current system state at pipeline construction time and refreshed at each `_process_utterance` call.

### Tool XML Hallucination

With tools re-enabled via function-calling, the LLM should use proper tool_calls instead of hallucinating XML tags in text. The existing XML detection (lines 1305-1330) remains as a safety net but should fire rarely. Monitor via Langfuse scoring.

## Workstream 2: Grounding Activation (Mode-Driven)

### Current State

Grounding ledger, evaluator, DU state machine, GQI, and effort calibration are fully implemented. Gated behind `enable_grounding` flag in experiment config. Gate check is in conversation_pipeline.py (frozen).

### Design

Mode-driven activation in `__main__.py` (not frozen). Before passing experiment flags to the pipeline, inject grounding flag based on working mode:

```python
# In __main__.py, pipeline construction
from shared.working_mode import working_mode

flags = load_experiment_flags()
if working_mode() == "rnd":
    flags["enable_grounding"] = True
# Research mode: flags file controls (Phase A = off, Phase B = on)
```

Pipeline code unchanged — still reads `enable_grounding` from the flags dict. The flag is just set upstream based on mode.

### Verification

When grounding is active in R&D:
- DU tracking: each response creates a PENDING DU, acceptance classification advances state
- GQI computation: EWMA over acceptance history, feeds stimmung 10th dimension
- Effort calibration: activation × GQI → word_limit + effort_level directive in VOLATILE band
- Strategy directives: advance/rephrase/elaborate/move_on appear in system prompt

## Workstream 3: TPN_ACTIVE Signaling

### Signal File

```
/dev/shm/hapax-dmn/tpn_active
```

Simple text file: `"1"` when TPN active, `"0"` when idle. This matches the existing DMN consumer implementation.

### DMN Consumer (Already Implemented)

DMN already reads this file. In `agents/dmn/__main__.py` (lines 116-120, 176-181):
- Reads `tpn_active` on each loop iteration
- Calls `pulse.set_tpn_active(active)` and `imagination.set_tpn_active(active)`
- `pulse.py` (line 140-141): doubles `sensory_rate` and `evaluative_rate` when TPN active

**No changes needed on the DMN side.**

### Write Points (Daimonion Side — New)

In `cognitive_loop.py` (not frozen), at state transitions:

| State | Write | Trigger |
|-------|-------|---------|
| TRANSCRIBING | `"1"` | STT started |
| THINKING | `"1"` | LLM generation started |
| SPEAKING | `"1"` | TTS playback started |
| LISTENING | `"0"` | Ready for input |
| IDLE | `"0"` | Session ended or silence timeout |

Write is atomic (tmp + rename). On daemon shutdown (`stop()`), write `"0"`.

### Staleness Guard

DMN already handles missing file gracefully (OSError caught, lines 119-120). If daimonion crashes without cleanup, file persists but DMN continues reading. On next daimonion start, file is overwritten. Worst case: DMN runs at half-speed for one daemon restart cycle — acceptable.

## Workstream 4: End-to-End Verification

Seven-point checklist. Each item gets pass/fail. Failures become targeted fixes.

1. **Ambient classification** — live capture via pw-record targeting default sink, PANNs classification, result reaches context gate. Pass: classification result logged within 10s.

2. **All 25 backends** — iterate registered backends, confirm `available()` == true, confirm `contribute()` produces behaviors with fresh timestamps. Pass: zero unavailable backends that should be available.

3. **Proactive speech** — write a synthetic impingement to `/dev/shm/hapax-dmn/impingements.jsonl`, verify it flows through affordance pipeline → proactive gate → spontaneous speech → TTS → audio. Pass: speech heard within 60s.

4. **Context enrichment** — during a live turn, log the assembled system prompt. Verify goals, health, nudges, dmn, imagination sections are present and non-empty. Pass: all 5 enrichment sections populated.

5. **Echo cancellation** — during TTS playback, verify echo canceller reference is fed. Confirm STT does not transcribe the system's own speech. Pass: no self-transcription in 5 consecutive turns.

6. **Grounding system** — in R&D mode, run a 5-turn conversation. Verify DU entries created, GQI computed, effort directives appear in prompt. Pass: grounding_state logged per turn.

7. **Tool execution** — in conversation, ask something that triggers a tool (e.g., "what time is it?"). Verify bridge phrase, tool execution within timeout, follow-up response with result. Pass: tool result appears in conversation.

## Files Changed

### New Files
- `agents/hapax_daimonion/tool_capability.py` — ToolCapability, ToolCategory, ResourceTier, ToolContext, ToolRegistry
- `agents/hapax_daimonion/tool_definitions.py` — 26 ToolCapability instances migrated from tools_openai.py
- `research/protocols/deviations/DEVIATION-026.md` — tool execution enable in frozen code

### Modified Files (Not Frozen)
- `agents/hapax_daimonion/__main__.py` — grounding mode-driven activation, ToolRegistry construction, ToolContext refresh per utterance
- `agents/hapax_daimonion/cognitive_loop.py` — TPN_ACTIVE write at state transitions
- `agents/dmn/` — no changes needed (already reads tpn_active and modulates tick interval)
- `agents/hapax_daimonion/tools_openai.py` — adapter: `get_openai_tools()` delegates to ToolRegistry

### Modified Files (Frozen — DEVIATION-026)
- `agents/hapax_daimonion/conversation_pipeline.py` — 3 changes:
  1. Line 1233-1234: un-comment `kwargs["tools"] = self.tools` (tools now dynamically filtered)
  2. Lines 1428-1436: replace skip block with `await self._handle_tool_calls(tool_calls_data, full_text)`
  3. Inside `_handle_tool_calls`: wrap handler with `asyncio.wait_for(handler(args), timeout=self._tool_timeout)`

## Dependencies

- Queue #015 (full recruitment model) depends on this work + validation sprint telemetry
- DEVIATION-025 (salience signal telemetry) is separate, filed for Day 1
- DEVIATION-026 (tool execution enable) filed as part of this work
- Bayesian validation sprint starts Day 1 (2026-03-30) — this work should complete before or not block it

## Non-Goals

- Telemetry instrumentation (separate, Day 1 sprint schedule)
- New tool creation (26 existing tools are sufficient)
- Tool recruitment model (queue #015, deferred)
- Changes to Reverie/visual pipeline (beta's workstream)
