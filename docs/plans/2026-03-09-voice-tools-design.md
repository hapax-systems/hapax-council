# Voice Assistant Tool Architecture Design

**Goal:** Enable post-wake-word conversational capabilities with real-world tool access — Qdrant search, Google services, SMS, vision analysis, and system status — integrated directly into the Pipecat local pipeline via function calling.

**Decision:** Pipecat-native tool functions registered on the `OpenAILLMService`, with async handlers that execute mid-conversation and return results to the LLM for spoken response.

---

## Architecture Overview

```
Wake word detected
  → Pipecat pipeline starts
    → LocalAudioTransport.input() (mic capture)
    → WhisperSTT (speech → text)
    → context_aggregator.user() (accumulates user turn)
    → OpenAILLMService (Claude via LiteLLM, tools registered)
      → LLM decides: respond directly OR call tool(s)
      → If tool call: async handler executes → result_callback → LLM continues
    → context_aggregator.assistant() (accumulates assistant turn)
    → KokoroTTS (text → speech)
    → LocalAudioTransport.output() (speaker playback)
```

The LLM has full autonomy over tool selection. No routing logic, intent classification, or skill dispatch — the model decides based on the user's natural language and the tool descriptions.

---

## Tool Inventory

Seven tools, grouped by data source:

### 1. `search_documents` — Qdrant semantic search

Searches the `documents` collection (emails, calendar events, Drive files, Obsidian notes, Chrome history, Claude Code transcripts — everything the sync agents index).

| Property | Value |
|----------|-------|
| Source | Qdrant `documents` collection (768d, nomic-embed-text) |
| Latency | ~100ms |
| Auth | None (local Qdrant) |
| Use cases | "What notes do I have about X?", "Find the doc about Y", "What did Z email me about?" |

**Parameters:**
- `query` (string, required): Natural language search query
- `source_filter` (string, optional): Filter by source — `gmail`, `gcalendar`, `gdrive`, `obsidian`, `chrome`, `claude-code`
- `max_results` (integer, optional): Number of results to return (default 5)

**Implementation:** Embed query via Ollama nomic-embed-text with `search_query:` prefix, search Qdrant with optional payload filter on `source_service` or `source_platform`, return top-k chunks with metadata.

### 2. `get_calendar_today` — Google Calendar real-time

Fetches today's and tomorrow's calendar events directly from Google Calendar API for maximum freshness.

| Property | Value |
|----------|-------|
| Source | Google Calendar API (readonly) |
| Latency | ~300ms |
| Auth | OAuth2 via `shared/google_auth.py` (scope already configured) |
| Use cases | "What's my schedule today?", "When's my next meeting?", "Am I free at 3?" |

**Parameters:**
- `days_ahead` (integer, optional): How many days to look ahead (default 2, max 7)

**Implementation:** Use `build_service("calendar", "v3")` from `shared/google_auth.py`. Call `events().list(calendarId="primary", timeMin=now, timeMax=now+days_ahead, singleEvents=True, orderBy="startTime")`. Return structured list of events with time, title, attendees, location.

### 3. `search_emails` — Gmail with Qdrant fallback

Searches recent emails. Prefers Qdrant for semantic queries, falls back to Gmail API for recency-sensitive requests.

| Property | Value |
|----------|-------|
| Source | Gmail API (readonly) + Qdrant `documents` fallback |
| Latency | ~200-400ms |
| Auth | OAuth2 via `shared/google_auth.py` (scope already configured) |
| Use cases | "Any new emails from Sarah?", "What was the last message about the project?", "Summarize my unread emails" |

**Parameters:**
- `query` (string, required): Search query (natural language or Gmail search syntax)
- `max_results` (integer, optional): Number of results (default 5)
- `recent_only` (boolean, optional): If true, hit Gmail API directly for freshest results

**Implementation:** When `recent_only=true`, use `build_service("gmail", "v1")` and `users().messages().list(userId="me", q=query, maxResults=max_results)`. Otherwise, embed and search Qdrant `documents` collection filtered to `source_service=gmail`.

### 4. `search_drive` — Google Drive via Qdrant

Searches Drive documents via Qdrant embeddings. Drive content is synced every 2 hours — sufficient for document search (documents rarely change minute-to-minute).

| Property | Value |
|----------|-------|
| Source | Qdrant `documents` collection filtered to `source_service=gdrive` |
| Latency | ~100ms |
| Auth | None (local Qdrant, already indexed by gdrive_sync) |
| Use cases | "Find the equipment spreadsheet", "What's in the studio inventory doc?" |

**Parameters:**
- `query` (string, required): Natural language search query
- `max_results` (integer, optional): Number of results (default 5)

**Implementation:** Thin wrapper around `search_documents` with `source_filter="gdrive"` hardcoded.

### 5. `send_sms` — Android SMS Gateway

Sends an SMS message via the Android SMS Gateway app running on the operator's phone.

| Property | Value |
|----------|-------|
| Source | Android SMS Gateway local server (REST API on phone's LAN) |
| Latency | ~500ms |
| Auth | Basic auth (credentials in `pass`) |
| Use cases | "Text my wife I'll be late", "Send Sarah a message saying..." |
| Safety | **Requires spoken confirmation before sending** |

**Parameters:**
- `recipient` (string, required): Contact name or phone number
- `message` (string, required): Message text

**Implementation:**
1. Resolve contact name to phone number via a contacts lookup (simple JSON map in config, not a full contacts API).
2. POST to `http://<phone_ip>:8080/messages` with basic auth from `pass show sms-gateway/credentials`.
3. **Confirmation flow:** Before executing, the handler returns a confirmation prompt to the LLM: "Send to [name] at [number]: '[message]' — should I send it?" The LLM speaks the confirmation. On user's "yes", a second tool call (`confirm_send_sms`) executes the actual send.

**Config additions:**
```python
sms_gateway_host: str = ""  # Phone LAN IP, e.g. "192.168.1.42:8080"
sms_contacts: dict[str, str] = {}  # {"Wife": "+1...", "Sarah": "+1..."}
```

### 6. `analyze_scene` — Camera + Gemini Flash vision

Captures images from available cameras and/or screen, sends to Gemini Flash for visual analysis.

| Property | Value |
|----------|-------|
| Source | BRIO webcam (operator), C920 webcam (hardware), cosmic-screenshot (screen) |
| Latency | ~2s (capture + vision model inference) |
| Auth | Gemini API via LiteLLM |
| Use cases | "Look at this", "What's on my screen?", "Can you see the mixer?", "How's the mic positioned?" |

**Parameters:**
- `cameras` (array of string, optional): Which sources to capture — `operator`, `hardware`, `screen` (default: all available)
- `question` (string, optional): Specific question about the scene (default: general description)

**Implementation:** Reuse existing `WebcamCapturer` and `ScreenCapturer` from hapax_voice modules. Capture frames, send to Gemini Flash vision model (`gemini-2.0-flash`) via LiteLLM with the question as prompt. Return the analysis text.

**Spontaneous vision triggers** (out-of-tool, daemon-level):
- The daemon's existing `WorkspaceMonitor` already runs periodic workspace analysis. When it detects a significant context shift (new person, equipment state change, activity mode change), it can inject updated `screen_context_block()` into the LLM's system prompt for the active session. This is not a tool call — it's a system message update between turns.

### 7. `get_system_status` — Health monitor

Returns current system health, infrastructure status, and VRAM usage.

| Property | Value |
|----------|-------|
| Source | Local health_monitor agent (deterministic, no LLM) |
| Latency | ~100ms |
| Auth | None (local) |
| Use cases | "How's the system?", "Is everything running?", "How much VRAM is free?" |

**Parameters:**
- `category` (string, optional): Filter to a specific check group — `docker`, `gpu`, `services`, `network`, `voice` (default: summary of all)

**Implementation:** Import and call `health_monitor.run_checks()` or a subset. Format results as a structured summary. Alternatively, read the most recent health check output from `~/.cache/hapax/health-monitor/latest.json` if it exists and is fresh (< 15 min old).

---

## Pipecat Integration

### Tool Registration Pattern

Tools are registered in `pipeline.py` using Pipecat's `FunctionSchema` + `ToolsSchema` system:

```python
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams

# Define tool schemas
search_documents_fn = FunctionSchema(
    name="search_documents",
    description="Search indexed documents, emails, calendar events, notes, and browsing history",
    properties={
        "query": {
            "type": "string",
            "description": "Natural language search query",
        },
        "source_filter": {
            "type": "string",
            "enum": ["gmail", "gcalendar", "gdrive", "obsidian", "chrome", "claude-code"],
            "description": "Optional: filter results to a specific source",
        },
        "max_results": {
            "type": "integer",
            "description": "Number of results to return (default 5)",
        },
    },
    required=["query"],
)

# ... define other tool schemas ...

tools = ToolsSchema(standard_tools=[
    search_documents_fn,
    get_calendar_today_fn,
    search_emails_fn,
    search_drive_fn,
    send_sms_fn,
    analyze_scene_fn,
    get_system_status_fn,
])

# Pass tools into the LLM context
context = OpenAILLMContext(
    messages=[{"role": "system", "content": prompt}],
    tools=tools,
)
```

### Handler Registration

Each tool gets an async handler registered on the LLM service:

```python
async def handle_search_documents(params: FunctionCallParams):
    query = params.arguments["query"]
    source = params.arguments.get("source_filter")
    max_results = params.arguments.get("max_results", 5)

    results = await qdrant_search(query, source_filter=source, limit=max_results)
    await params.result_callback(results)

llm.register_function("search_documents", handle_search_documents)
llm.register_function("get_calendar_today", handle_get_calendar_today)
# ... etc ...
```

### Guest Mode

When `guest_mode=True`, tools are **not registered**. The guest persona already explains it can't access system information. No tools = no data access = safe for non-operator conversations.

---

## New Module: `agents/hapax_voice/tools.py`

All tool schemas, handlers, and registration logic live in a single new module. Keeps `pipeline.py` clean.

### API Surface

```python
def get_tool_schemas(guest_mode: bool = False) -> ToolsSchema:
    """Return ToolsSchema for all voice tools. Empty if guest_mode."""

def register_tool_handlers(llm: OpenAILLMService, config: VoiceConfig) -> None:
    """Register all async tool handlers on the LLM service."""
```

### Dependencies

| Dependency | Source | Already in project? |
|------------|--------|---------------------|
| `qdrant-client` | Qdrant search | Yes |
| `google-api-python-client` | Calendar, Gmail API | Yes |
| `httpx` | SMS Gateway REST calls | Yes |
| `shared/google_auth.py` | OAuth token management | Yes |
| `shared/config.py` | Qdrant client, embed() | Yes |
| `agents/hapax_voice/webcam_capturer.py` | Camera capture | Yes |
| `agents/hapax_voice/screen_capturer.py` | Screen capture | Yes |

No new dependencies required.

---

## SMS Confirmation Flow

Sending messages is the only destructive/irreversible action. Two-step confirmation:

1. User: "Text my wife I'm running 20 minutes late"
2. LLM calls `send_sms(recipient="Wife", message="I'm running 20 minutes late")`
3. Handler does NOT send yet. Returns: `{"status": "pending_confirmation", "recipient": "Wife", "phone": "+1...", "message": "I'm running 20 minutes late"}`
4. LLM speaks: "I'll text your wife: 'I'm running 20 minutes late'. Should I send it?"
5. User: "Yes" / "Yeah" / "Send it"
6. LLM calls `confirm_send_sms(confirmation_id="...")`
7. Handler sends the SMS, returns: `{"status": "sent"}`
8. LLM speaks: "Sent."

This adds an 8th tool: `confirm_send_sms`. Only callable after a pending `send_sms`.

---

## Spontaneous Vision Injection

Not a tool — a daemon-level behavior. When the workspace monitor detects a context shift during an active session:

1. `WorkspaceMonitor` fires a `workspace_analysis_updated` event.
2. `VoiceDaemon._on_workspace_update()` checks if a pipeline session is active.
3. If active, updates the system message in the `OpenAILLMContext` with fresh `screen_context_block()` content.
4. The LLM sees the updated context on its next turn and can proactively reference what it sees.

**Heuristic triggers for spontaneous vision during conversation:**
- User mentions visual/spatial language ("look", "see", "this", "here", "over there")
- Significant ambient change detected by presence system (new face, operator left/returned)
- Timer-based: refresh workspace context every 60s during active session

---

## System Prompt Updates

The existing system prompt in `persona.py` needs tool-awareness additions:

```python
_SYSTEM_PROMPT = (
    "You are Hapax, a voice assistant for {name}. "
    "You are warm but concise — friendly without being chatty. "
    "You have full access to {name}'s system: briefings, calendar, meeting prep, "
    "notifications, and infrastructure status. "
    "You can search documents, emails, and notes. "
    "You can check the calendar and look up real-time events. "
    "You can send SMS messages (always confirm before sending). "
    "You can see through cameras and the screen when asked. "
    "Keep responses spoken-natural and brief. "
    "When reading data, summarize — don't dump raw output. "
    "If asked to go deeper, elaborate. "
    "You know {name} well — use first name, skip formalities."
)
```

---

## Config Additions

New fields in `VoiceConfig`:

```python
# SMS Gateway
sms_gateway_host: str = ""           # e.g. "192.168.1.42:8080"
sms_gateway_user: str = ""           # Basic auth username
sms_gateway_pass_key: str = "sms-gateway/password"  # pass store key
sms_contacts: dict[str, str] = {}    # {"Wife": "+1...", "Sarah": "+1..."}

# Tool behavior
tools_enabled: bool = True           # Master toggle
vision_spontaneous: bool = True      # Spontaneous vision injection
vision_refresh_interval: int = 60    # Seconds between spontaneous vision updates
```

---

## Location Capability Gap

Google Maps shared location has **no public API** for real-time lookups. No OAuth scope, no REST endpoint. Options considered:

1. ~~Google Maps API~~ — no shared-location read endpoint exists
2. ~~Google Latitude~~ — deprecated 2013
3. ~~People API~~ — contacts only, no live location

**Accepted workaround:** The voice assistant can:
- Check calendar for location clues ("she has yoga at 5pm")
- Ask the operator to text and ask (SMS round-trip)
- State honestly: "I can't check live location — Google doesn't provide an API for that"

This is documented as a known limitation, not a bug to fix.

---

## Out of Scope

- **Pydantic AI agent layer** — tools run as simple async functions, no agent orchestration needed yet.
- **Gemini Live backend** — no tool support; tools only work with the local Pipecat pipeline.
- **Multi-turn tool chains** — the LLM handles sequencing naturally via conversation context. No explicit chaining logic.
- **Contact sync** — SMS contacts are a static config map. Full Google Contacts integration is future work.
- **Incoming SMS handling** — Android SMS Gateway supports webhooks for incoming messages, but that's a separate feature (notification integration).
- **MPC/SP-404/hardware control** — MIDI control tools are a future phase, not part of this design.

---

## Testing Strategy

### Unit Tests (mocked external services)

- Each tool handler tested in isolation with mocked Qdrant/Google/SMS clients.
- Tool schema validation — all required fields present, types correct.
- Guest mode returns empty ToolsSchema.
- SMS confirmation flow: pending → confirm → sent.
- SMS confirmation flow: pending → deny → cancelled.

### Integration Tests (real Qdrant, mocked Google/SMS)

- `search_documents` returns relevant results from test collection.
- Tool registration on OpenAILLMService succeeds.
- Pipeline builds with tools without error.

### Manual Validation

- End-to-end voice test: say "hapax", ask "what's on my calendar today", verify spoken response.
- SMS test with actual Android SMS Gateway on phone.
- Vision test: "what do you see?" with cameras connected.
