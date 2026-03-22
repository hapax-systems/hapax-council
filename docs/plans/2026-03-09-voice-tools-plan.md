# Voice Tools Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 8 function-calling tools to the hapax-voice Pipecat pipeline so the voice assistant can search documents, check calendar, query emails, send SMS, analyze scenes, and report system status.

**Architecture:** Tools are registered as Pipecat `FunctionSchema` objects on the `OpenAILLMService`, with async handlers in a new `tools.py` module. The LLM decides when to call tools mid-conversation. SMS has a two-step confirmation flow. Guest mode disables all tools.

**Tech Stack:** Pipecat (FunctionSchema, ToolsSchema, FunctionCallParams), Qdrant (semantic search), Google API (Calendar, Gmail), httpx (SMS Gateway), existing webcam/screen capturers.

**Design doc:** `docs/plans/2026-03-09-voice-tools-design.md`

---

### Task 1: Config additions for tools

**Files:**
- Modify: `agents/hapax_voice/config.py` (add fields after line ~95)
- Test: `tests/hapax_voice/test_tools_config.py`

**Step 1: Write the failing test**

```python
# tests/hapax_voice/test_tools_config.py
"""Tests for voice tool config fields."""
from agents.hapax_voice.config import VoiceConfig


def test_tools_enabled_default():
    cfg = VoiceConfig()
    assert cfg.tools_enabled is True


def test_sms_gateway_defaults():
    cfg = VoiceConfig()
    assert cfg.sms_gateway_host == ""
    assert cfg.sms_contacts == {}
    assert cfg.sms_gateway_pass_key == "sms-gateway/password"


def test_sms_contacts_from_dict():
    cfg = VoiceConfig(sms_contacts={"Wife": "+15551234567"})
    assert cfg.sms_contacts["Wife"] == "+15551234567"


def test_vision_spontaneous_defaults():
    cfg = VoiceConfig()
    assert cfg.vision_spontaneous is True
    assert cfg.vision_refresh_interval == 60
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_tools_config.py -v`
Expected: FAIL — missing fields on VoiceConfig

**Step 3: Write minimal implementation**

Add to `agents/hapax_voice/config.py` inside the `VoiceConfig` class, after the observability fields:

```python
    # Tools
    tools_enabled: bool = True

    # SMS Gateway
    sms_gateway_host: str = ""
    sms_gateway_user: str = ""
    sms_gateway_pass_key: str = "sms-gateway/password"
    sms_contacts: dict[str, str] = {}

    # Vision tools
    vision_spontaneous: bool = True
    vision_refresh_interval: int = 60
```

**Step 4: Run test to verify it passes**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_tools_config.py -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add agents/hapax_voice/config.py tests/hapax_voice/test_tools_config.py
git commit -m "feat(voice): add tool config fields — SMS gateway, vision, tools toggle"
```

---

### Task 2: Tool schemas module — `search_documents` and `search_drive`

**Files:**
- Create: `agents/hapax_voice/tools.py`
- Test: `tests/hapax_voice/test_tool_schemas.py`

**Step 1: Write the failing test**

```python
# tests/hapax_voice/test_tool_schemas.py
"""Tests for voice tool schema definitions and registration."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_voice.tools import get_tool_schemas, TOOL_SCHEMAS


def test_tool_schemas_returns_tools_schema():
    tools = get_tool_schemas(guest_mode=False)
    # ToolsSchema has a standard_tools attribute
    assert tools is not None


def test_tool_schemas_guest_mode_empty():
    tools = get_tool_schemas(guest_mode=True)
    # Guest mode should return None (no tools)
    assert tools is None


def test_search_documents_schema_exists():
    names = [s.name for s in TOOL_SCHEMAS]
    assert "search_documents" in names


def test_search_drive_schema_exists():
    names = [s.name for s in TOOL_SCHEMAS]
    assert "search_drive" in names


def test_search_documents_has_required_query():
    schema = next(s for s in TOOL_SCHEMAS if s.name == "search_documents")
    assert "query" in schema.required


def test_all_schemas_have_description():
    for schema in TOOL_SCHEMAS:
        assert schema.description, f"{schema.name} missing description"
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_tool_schemas.py -v`
Expected: FAIL — cannot import `tools`

**Step 3: Write minimal implementation**

```python
# agents/hapax_voice/tools.py
"""Voice assistant tool schemas and handlers for Pipecat function calling.

Defines FunctionSchema objects for each tool and async handlers that execute
when the LLM calls them mid-conversation.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema

if TYPE_CHECKING:
    from pipecat.services.llm_service import FunctionCallParams
    from pipecat.services.openai.llm import OpenAILLMService

    from agents.hapax_voice.config import VoiceConfig

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool schema definitions
# ---------------------------------------------------------------------------

_search_documents = FunctionSchema(
    name="search_documents",
    description=(
        "Search indexed documents, emails, calendar events, notes, "
        "and browsing history via semantic search"
    ),
    properties={
        "query": {
            "type": "string",
            "description": "Natural language search query",
        },
        "source_filter": {
            "type": "string",
            "enum": [
                "gmail",
                "gcalendar",
                "gdrive",
                "obsidian",
                "chrome",
                "claude-code",
            ],
            "description": "Optional: filter results to a specific source",
        },
        "max_results": {
            "type": "integer",
            "description": "Number of results to return (default 5)",
        },
    },
    required=["query"],
)

_search_drive = FunctionSchema(
    name="search_drive",
    description="Search Google Drive documents and files",
    properties={
        "query": {
            "type": "string",
            "description": "Natural language search query",
        },
        "max_results": {
            "type": "integer",
            "description": "Number of results to return (default 5)",
        },
    },
    required=["query"],
)

TOOL_SCHEMAS: list[FunctionSchema] = [
    _search_documents,
    _search_drive,
]


def get_tool_schemas(guest_mode: bool = False) -> ToolsSchema | None:
    """Return ToolsSchema for all voice tools. None if guest_mode."""
    if guest_mode:
        return None
    return ToolsSchema(standard_tools=TOOL_SCHEMAS)
```

**Step 4: Run test to verify it passes**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_tool_schemas.py -v`
Expected: 6 PASSED

**Step 5: Commit**

```bash
git add agents/hapax_voice/tools.py tests/hapax_voice/test_tool_schemas.py
git commit -m "feat(voice): add tool schemas module with search_documents and search_drive"
```

---

### Task 3: Add remaining tool schemas (calendar, emails, SMS, vision, status)

**Files:**
- Modify: `agents/hapax_voice/tools.py`
- Modify: `tests/hapax_voice/test_tool_schemas.py`

**Step 1: Write the failing test**

Add to `tests/hapax_voice/test_tool_schemas.py`:

```python
EXPECTED_TOOL_NAMES = [
    "search_documents",
    "search_drive",
    "get_calendar_today",
    "search_emails",
    "send_sms",
    "confirm_send_sms",
    "analyze_scene",
    "get_system_status",
]


def test_all_expected_tools_present():
    names = [s.name for s in TOOL_SCHEMAS]
    for expected in EXPECTED_TOOL_NAMES:
        assert expected in names, f"Missing tool schema: {expected}"


def test_total_tool_count():
    assert len(TOOL_SCHEMAS) == 8


def test_send_sms_requires_recipient_and_message():
    schema = next(s for s in TOOL_SCHEMAS if s.name == "send_sms")
    assert "recipient" in schema.required
    assert "message" in schema.required


def test_confirm_send_sms_requires_confirmation_id():
    schema = next(s for s in TOOL_SCHEMAS if s.name == "confirm_send_sms")
    assert "confirmation_id" in schema.required
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_tool_schemas.py::test_all_expected_tools_present -v`
Expected: FAIL — missing schemas

**Step 3: Write minimal implementation**

Add to `agents/hapax_voice/tools.py` before the `TOOL_SCHEMAS` list:

```python
_get_calendar_today = FunctionSchema(
    name="get_calendar_today",
    description="Get today's and upcoming calendar events in real time",
    properties={
        "days_ahead": {
            "type": "integer",
            "description": "How many days to look ahead (default 2, max 7)",
        },
    },
    required=[],
)

_search_emails = FunctionSchema(
    name="search_emails",
    description="Search recent emails by sender, subject, or content",
    properties={
        "query": {
            "type": "string",
            "description": "Search query (natural language or Gmail search syntax)",
        },
        "max_results": {
            "type": "integer",
            "description": "Number of results (default 5)",
        },
        "recent_only": {
            "type": "boolean",
            "description": "If true, fetch directly from Gmail for freshest results",
        },
    },
    required=["query"],
)

_send_sms = FunctionSchema(
    name="send_sms",
    description=(
        "Prepare an SMS message for sending. Returns a confirmation prompt — "
        "the message is NOT sent until confirm_send_sms is called"
    ),
    properties={
        "recipient": {
            "type": "string",
            "description": "Contact name (e.g. 'Wife') or phone number",
        },
        "message": {
            "type": "string",
            "description": "The text message to send",
        },
    },
    required=["recipient", "message"],
)

_confirm_send_sms = FunctionSchema(
    name="confirm_send_sms",
    description="Confirm and send a previously prepared SMS message",
    properties={
        "confirmation_id": {
            "type": "string",
            "description": "The confirmation ID from the send_sms response",
        },
    },
    required=["confirmation_id"],
)

_analyze_scene = FunctionSchema(
    name="analyze_scene",
    description=(
        "Capture images from cameras and/or screen and analyze what is visible"
    ),
    properties={
        "cameras": {
            "type": "array",
            "items": {"type": "string", "enum": ["operator", "hardware", "screen"]},
            "description": "Which sources to capture (default: all available)",
        },
        "question": {
            "type": "string",
            "description": "Specific question about the scene (default: general description)",
        },
    },
    required=[],
)

_get_system_status = FunctionSchema(
    name="get_system_status",
    description="Check system health, infrastructure status, and GPU VRAM usage",
    properties={
        "category": {
            "type": "string",
            "enum": ["docker", "gpu", "services", "network", "voice"],
            "description": "Filter to a specific check group (default: summary of all)",
        },
    },
    required=[],
)
```

Update `TOOL_SCHEMAS`:

```python
TOOL_SCHEMAS: list[FunctionSchema] = [
    _search_documents,
    _search_drive,
    _get_calendar_today,
    _search_emails,
    _send_sms,
    _confirm_send_sms,
    _analyze_scene,
    _get_system_status,
]
```

**Step 4: Run test to verify it passes**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_tool_schemas.py -v`
Expected: 10 PASSED

**Step 5: Commit**

```bash
git add agents/hapax_voice/tools.py tests/hapax_voice/test_tool_schemas.py
git commit -m "feat(voice): add all 8 tool schemas — calendar, email, SMS, vision, status"
```

---

### Task 4: Implement `search_documents` handler

**Files:**
- Modify: `agents/hapax_voice/tools.py`
- Test: `tests/hapax_voice/test_tool_handlers.py`

**Step 1: Write the failing test**

```python
# tests/hapax_voice/test_tool_handlers.py
"""Tests for voice tool handler implementations."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_qdrant():
    """Mock Qdrant client with query_points returning fake results."""
    client = MagicMock()
    point = MagicMock()
    point.payload = {"filename": "test.md", "text": "Sample document text", "source_service": "obsidian"}
    point.score = 0.85
    response = MagicMock()
    response.points = [point]
    client.query_points.return_value = response
    return client


@pytest.fixture
def mock_embed():
    """Mock embed function returning a fake 768-dim vector."""
    return MagicMock(return_value=[0.1] * 768)


@pytest.fixture
def mock_fn_params():
    """Create a mock FunctionCallParams with result_callback."""
    params = MagicMock()
    params.result_callback = AsyncMock()
    return params


class TestSearchDocumentsHandler:
    @pytest.mark.asyncio
    async def test_basic_search(self, mock_fn_params, mock_qdrant, mock_embed):
        from agents.hapax_voice.tools import handle_search_documents

        mock_fn_params.arguments = {"query": "meeting notes"}

        with patch("agents.hapax_voice.tools.get_qdrant", return_value=mock_qdrant), \
             patch("agents.hapax_voice.tools.embed", mock_embed):
            await handle_search_documents(mock_fn_params)

        mock_embed.assert_called_once_with("meeting notes", prefix="search_query")
        mock_qdrant.query_points.assert_called_once()
        mock_fn_params.result_callback.assert_awaited_once()
        result = mock_fn_params.result_callback.call_args[0][0]
        assert "test.md" in result
        assert "Sample document text" in result

    @pytest.mark.asyncio
    async def test_source_filter(self, mock_fn_params, mock_qdrant, mock_embed):
        from agents.hapax_voice.tools import handle_search_documents

        mock_fn_params.arguments = {"query": "budget", "source_filter": "gdrive"}

        with patch("agents.hapax_voice.tools.get_qdrant", return_value=mock_qdrant), \
             patch("agents.hapax_voice.tools.embed", mock_embed):
            await handle_search_documents(mock_fn_params)

        call_kwargs = mock_qdrant.query_points.call_args
        # Should have a filter applied
        assert call_kwargs is not None

    @pytest.mark.asyncio
    async def test_no_results(self, mock_fn_params, mock_embed):
        from agents.hapax_voice.tools import handle_search_documents

        mock_fn_params.arguments = {"query": "nonexistent"}
        empty_client = MagicMock()
        empty_response = MagicMock()
        empty_response.points = []
        empty_client.query_points.return_value = empty_response

        with patch("agents.hapax_voice.tools.get_qdrant", return_value=empty_client), \
             patch("agents.hapax_voice.tools.embed", mock_embed):
            await handle_search_documents(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "no relevant" in result.lower() or "no results" in result.lower()

    @pytest.mark.asyncio
    async def test_error_handling(self, mock_fn_params):
        from agents.hapax_voice.tools import handle_search_documents

        mock_fn_params.arguments = {"query": "test"}

        with patch("agents.hapax_voice.tools.get_qdrant", side_effect=RuntimeError("connection failed")):
            await handle_search_documents(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "failed" in result.lower() or "error" in result.lower()
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_tool_handlers.py::TestSearchDocumentsHandler -v`
Expected: FAIL — `handle_search_documents` not found

**Step 3: Write minimal implementation**

Add to `agents/hapax_voice/tools.py`:

```python
from qdrant_client.models import FieldCondition, Filter, MatchValue

from shared.config import embed, get_qdrant

_DOCUMENTS_COLLECTION = "documents"
_DEFAULT_MAX_RESULTS = 5
_SCORE_THRESHOLD = 0.3


async def handle_search_documents(params: FunctionCallParams) -> None:
    """Search Qdrant documents collection with semantic similarity."""
    query = params.arguments["query"]
    source = params.arguments.get("source_filter")
    max_results = params.arguments.get("max_results", _DEFAULT_MAX_RESULTS)

    try:
        vector = embed(query, prefix="search_query")
        client = get_qdrant()

        query_filter = None
        if source:
            query_filter = Filter(
                must=[FieldCondition(key="source_service", match=MatchValue(value=source))]
            )

        results = client.query_points(
            _DOCUMENTS_COLLECTION,
            query=vector,
            query_filter=query_filter,
            limit=max_results,
            score_threshold=_SCORE_THRESHOLD,
        )

        if not results.points:
            await params.result_callback("No relevant documents found.")
            return

        chunks = []
        for p in results.points:
            filename = p.payload.get("filename", "unknown")
            text = p.payload.get("text", "")
            source_svc = p.payload.get("source_service", "")
            chunks.append(f"[{filename} ({source_svc}), relevance={p.score:.2f}]\n{text}")

        await params.result_callback("\n\n---\n\n".join(chunks))

    except Exception as exc:
        log.exception("search_documents failed")
        await params.result_callback(f"Search failed: {exc}")
```

**Step 4: Run test to verify it passes**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_tool_handlers.py::TestSearchDocumentsHandler -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add agents/hapax_voice/tools.py tests/hapax_voice/test_tool_handlers.py
git commit -m "feat(voice): implement search_documents tool handler with Qdrant search"
```

---

### Task 5: Implement `get_calendar_today` handler

**Files:**
- Modify: `agents/hapax_voice/tools.py`
- Modify: `tests/hapax_voice/test_tool_handlers.py`

**Step 1: Write the failing test**

Add to `tests/hapax_voice/test_tool_handlers.py`:

```python
from datetime import datetime, timezone


class TestGetCalendarTodayHandler:
    @pytest.mark.asyncio
    async def test_returns_events(self, mock_fn_params):
        from agents.hapax_voice.tools import handle_get_calendar_today

        mock_fn_params.arguments = {}

        mock_service = MagicMock()
        mock_events = MagicMock()
        mock_service.events.return_value = mock_events
        mock_list = MagicMock()
        mock_events.list.return_value = mock_list
        mock_list.execute.return_value = {
            "items": [
                {
                    "summary": "Team standup",
                    "start": {"dateTime": "2026-03-09T09:00:00-05:00"},
                    "end": {"dateTime": "2026-03-09T09:30:00-05:00"},
                    "attendees": [{"email": "alice@example.com"}],
                },
                {
                    "summary": "Lunch",
                    "start": {"date": "2026-03-09"},
                    "end": {"date": "2026-03-09"},
                },
            ]
        }

        with patch("agents.hapax_voice.tools.build_service", return_value=mock_service):
            await handle_get_calendar_today(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "Team standup" in result
        assert "Lunch" in result

    @pytest.mark.asyncio
    async def test_no_events(self, mock_fn_params):
        from agents.hapax_voice.tools import handle_get_calendar_today

        mock_fn_params.arguments = {}

        mock_service = MagicMock()
        mock_events = MagicMock()
        mock_service.events.return_value = mock_events
        mock_list = MagicMock()
        mock_events.list.return_value = mock_list
        mock_list.execute.return_value = {"items": []}

        with patch("agents.hapax_voice.tools.build_service", return_value=mock_service):
            await handle_get_calendar_today(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "no events" in result.lower() or "clear" in result.lower()

    @pytest.mark.asyncio
    async def test_api_error(self, mock_fn_params):
        from agents.hapax_voice.tools import handle_get_calendar_today

        mock_fn_params.arguments = {}

        with patch("agents.hapax_voice.tools.build_service", side_effect=Exception("auth failed")):
            await handle_get_calendar_today(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "failed" in result.lower()
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_tool_handlers.py::TestGetCalendarTodayHandler -v`
Expected: FAIL — `handle_get_calendar_today` not found

**Step 3: Write minimal implementation**

Add to `agents/hapax_voice/tools.py`:

```python
from datetime import datetime, timedelta, timezone

from shared.google_auth import build_service

_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


async def handle_get_calendar_today(params: FunctionCallParams) -> None:
    """Fetch upcoming calendar events from Google Calendar API."""
    days_ahead = min(params.arguments.get("days_ahead", 2), 7)

    try:
        service = build_service("calendar", "v3", [_CALENDAR_SCOPE])
        now = datetime.now(timezone.utc)
        time_max = now + timedelta(days=days_ahead)

        result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=20,
            )
            .execute()
        )

        events = result.get("items", [])
        if not events:
            await params.result_callback("Your calendar is clear — no upcoming events.")
            return

        lines = []
        for event in events:
            summary = event.get("summary", "(no title)")
            start = event["start"].get("dateTime", event["start"].get("date", ""))
            location = event.get("location", "")
            attendees = event.get("attendees", [])
            attendee_names = ", ".join(
                a.get("displayName", a.get("email", "")) for a in attendees[:5]
            )

            line = f"- {start}: {summary}"
            if location:
                line += f" @ {location}"
            if attendee_names:
                line += f" (with {attendee_names})"
            lines.append(line)

        await params.result_callback("\n".join(lines))

    except Exception as exc:
        log.exception("get_calendar_today failed")
        await params.result_callback(f"Calendar lookup failed: {exc}")
```

**Step 4: Run test to verify it passes**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_tool_handlers.py::TestGetCalendarTodayHandler -v`
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add agents/hapax_voice/tools.py tests/hapax_voice/test_tool_handlers.py
git commit -m "feat(voice): implement get_calendar_today handler with Google Calendar API"
```

---

### Task 6: Implement `search_emails` handler

**Files:**
- Modify: `agents/hapax_voice/tools.py`
- Modify: `tests/hapax_voice/test_tool_handlers.py`

**Step 1: Write the failing test**

Add to `tests/hapax_voice/test_tool_handlers.py`:

```python
class TestSearchEmailsHandler:
    @pytest.mark.asyncio
    async def test_qdrant_search_default(self, mock_fn_params, mock_qdrant, mock_embed):
        from agents.hapax_voice.tools import handle_search_emails

        mock_fn_params.arguments = {"query": "invoice from Sarah"}

        with patch("agents.hapax_voice.tools.get_qdrant", return_value=mock_qdrant), \
             patch("agents.hapax_voice.tools.embed", mock_embed):
            await handle_search_emails(mock_fn_params)

        # Default mode should use Qdrant
        mock_qdrant.query_points.assert_called_once()
        mock_fn_params.result_callback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recent_only_uses_gmail_api(self, mock_fn_params):
        from agents.hapax_voice.tools import handle_search_emails

        mock_fn_params.arguments = {"query": "from:sarah", "recent_only": True}

        mock_service = MagicMock()
        mock_users = MagicMock()
        mock_service.users.return_value = mock_users
        mock_messages = MagicMock()
        mock_users.messages.return_value = mock_messages
        mock_list = MagicMock()
        mock_messages.list.return_value = mock_list
        mock_list.execute.return_value = {
            "messages": [{"id": "msg1", "threadId": "t1"}]
        }
        mock_get = MagicMock()
        mock_messages.get.return_value = mock_get
        mock_get.execute.return_value = {
            "id": "msg1",
            "snippet": "Hi, here is the invoice...",
            "payload": {
                "headers": [
                    {"name": "From", "value": "sarah@example.com"},
                    {"name": "Subject", "value": "Invoice Q1"},
                    {"name": "Date", "value": "Mon, 9 Mar 2026 10:00:00 -0500"},
                ],
            },
        }

        with patch("agents.hapax_voice.tools.build_service", return_value=mock_service):
            await handle_search_emails(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "Invoice Q1" in result or "sarah" in result.lower()

    @pytest.mark.asyncio
    async def test_no_results(self, mock_fn_params, mock_embed):
        from agents.hapax_voice.tools import handle_search_emails

        mock_fn_params.arguments = {"query": "nonexistent"}
        empty_client = MagicMock()
        empty_response = MagicMock()
        empty_response.points = []
        empty_client.query_points.return_value = empty_response

        with patch("agents.hapax_voice.tools.get_qdrant", return_value=empty_client), \
             patch("agents.hapax_voice.tools.embed", mock_embed):
            await handle_search_emails(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "no" in result.lower()
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_tool_handlers.py::TestSearchEmailsHandler -v`
Expected: FAIL — `handle_search_emails` not found

**Step 3: Write minimal implementation**

Add to `agents/hapax_voice/tools.py`:

```python
_GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


async def handle_search_emails(params: FunctionCallParams) -> None:
    """Search emails via Qdrant or Gmail API."""
    query = params.arguments["query"]
    max_results = params.arguments.get("max_results", _DEFAULT_MAX_RESULTS)
    recent_only = params.arguments.get("recent_only", False)

    try:
        if recent_only:
            await _search_emails_gmail(params, query, max_results)
        else:
            await _search_emails_qdrant(params, query, max_results)
    except Exception as exc:
        log.exception("search_emails failed")
        await params.result_callback(f"Email search failed: {exc}")


async def _search_emails_qdrant(
    params: FunctionCallParams, query: str, max_results: int
) -> None:
    """Search emails via Qdrant semantic search."""
    vector = embed(query, prefix="search_query")
    client = get_qdrant()
    query_filter = Filter(
        must=[FieldCondition(key="source_service", match=MatchValue(value="gmail"))]
    )
    results = client.query_points(
        _DOCUMENTS_COLLECTION,
        query=vector,
        query_filter=query_filter,
        limit=max_results,
        score_threshold=_SCORE_THRESHOLD,
    )
    if not results.points:
        await params.result_callback("No matching emails found.")
        return

    chunks = []
    for p in results.points:
        filename = p.payload.get("filename", "")
        text = p.payload.get("text", "")
        chunks.append(f"[{filename}, relevance={p.score:.2f}]\n{text}")
    await params.result_callback("\n\n---\n\n".join(chunks))


async def _search_emails_gmail(
    params: FunctionCallParams, query: str, max_results: int
) -> None:
    """Search emails directly via Gmail API for freshest results."""
    service = build_service("gmail", "v1", [_GMAIL_SCOPE])
    result = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )
    messages = result.get("messages", [])
    if not messages:
        await params.result_callback("No matching emails found.")
        return

    lines = []
    for msg_ref in messages[:max_results]:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_ref["id"], format="metadata",
                 metadataHeaders=["From", "Subject", "Date"])
            .execute()
        )
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        snippet = msg.get("snippet", "")
        lines.append(
            f"- From: {headers.get('From', '?')} | "
            f"Subject: {headers.get('Subject', '?')} | "
            f"Date: {headers.get('Date', '?')}\n  {snippet}"
        )
    await params.result_callback("\n".join(lines))
```

**Step 4: Run test to verify it passes**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_tool_handlers.py::TestSearchEmailsHandler -v`
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add agents/hapax_voice/tools.py tests/hapax_voice/test_tool_handlers.py
git commit -m "feat(voice): implement search_emails handler with Qdrant + Gmail API fallback"
```

---

### Task 7: Implement `send_sms` and `confirm_send_sms` handlers

**Files:**
- Modify: `agents/hapax_voice/tools.py`
- Modify: `tests/hapax_voice/test_tool_handlers.py`
- Dependency note: `httpx` is dev-only in pyproject.toml — add to main deps

**Step 1: Write the failing test**

Add to `tests/hapax_voice/test_tool_handlers.py`:

```python
class TestSendSmsHandler:
    @pytest.mark.asyncio
    async def test_prepare_sms_returns_confirmation(self, mock_fn_params):
        from agents.hapax_voice.tools import handle_send_sms, _pending_sms

        _pending_sms.clear()
        mock_fn_params.arguments = {"recipient": "Wife", "message": "Running late"}

        mock_cfg = MagicMock()
        mock_cfg.sms_contacts = {"Wife": "+15551234567"}

        with patch("agents.hapax_voice.tools._voice_config", mock_cfg):
            await handle_send_sms(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "pending_confirmation" in str(result)
        assert "+15551234567" in str(result)
        assert len(_pending_sms) == 1

    @pytest.mark.asyncio
    async def test_unknown_recipient(self, mock_fn_params):
        from agents.hapax_voice.tools import handle_send_sms

        mock_fn_params.arguments = {"recipient": "Unknown Person", "message": "Hello"}

        mock_cfg = MagicMock()
        mock_cfg.sms_contacts = {"Wife": "+15551234567"}

        with patch("agents.hapax_voice.tools._voice_config", mock_cfg):
            await handle_send_sms(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "not found" in str(result).lower() or "unknown" in str(result).lower()


class TestConfirmSendSmsHandler:
    @pytest.mark.asyncio
    async def test_confirm_sends_sms(self, mock_fn_params):
        from agents.hapax_voice.tools import handle_confirm_send_sms, _pending_sms

        _pending_sms.clear()
        _pending_sms["test-123"] = {
            "phone": "+15551234567",
            "message": "Running late",
            "recipient": "Wife",
        }
        mock_fn_params.arguments = {"confirmation_id": "test-123"}

        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.json.return_value = {"state": "Pending"}

        with patch("agents.hapax_voice.tools.httpx") as mock_httpx:
            mock_httpx.post.return_value = mock_response
            mock_cfg = MagicMock()
            mock_cfg.sms_gateway_host = "192.168.1.42:8080"
            mock_cfg.sms_gateway_user = "user"
            mock_cfg.sms_gateway_pass_key = "sms/pass"
            with patch("agents.hapax_voice.tools._voice_config", mock_cfg), \
                 patch("agents.hapax_voice.tools._get_sms_password", return_value="secret"):
                await handle_confirm_send_sms(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "sent" in str(result).lower()
        assert "test-123" not in _pending_sms

    @pytest.mark.asyncio
    async def test_invalid_confirmation_id(self, mock_fn_params):
        from agents.hapax_voice.tools import handle_confirm_send_sms, _pending_sms

        _pending_sms.clear()
        mock_fn_params.arguments = {"confirmation_id": "nonexistent"}

        await handle_confirm_send_sms(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "not found" in str(result).lower() or "expired" in str(result).lower()
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_tool_handlers.py::TestSendSmsHandler -v`
Expected: FAIL — `handle_send_sms` not found

**Step 3: Add httpx to main dependencies**

In `pyproject.toml`, add `"httpx>=0.28.0"` to the main `dependencies` list (not just dev).

**Step 4: Write minimal implementation**

Add to `agents/hapax_voice/tools.py`:

```python
import subprocess
import uuid

import httpx

# Module-level state for SMS confirmation flow
_pending_sms: dict[str, dict] = {}
_voice_config: VoiceConfig | None = None


def _get_sms_password(pass_key: str) -> str:
    """Retrieve SMS gateway password from pass store."""
    result = subprocess.run(
        ["pass", "show", pass_key],
        capture_output=True, text=True, timeout=5,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pass show {pass_key} failed: {result.stderr}")
    return result.stdout.strip()


async def handle_send_sms(params: FunctionCallParams) -> None:
    """Prepare an SMS for sending — returns confirmation, does NOT send yet."""
    recipient = params.arguments["recipient"]
    message = params.arguments["message"]

    cfg = _voice_config
    if cfg is None:
        await params.result_callback({"status": "error", "detail": "SMS not configured"})
        return

    # Resolve contact name to phone number
    phone = cfg.sms_contacts.get(recipient)
    if phone is None:
        # Try case-insensitive lookup
        for name, number in cfg.sms_contacts.items():
            if name.lower() == recipient.lower():
                phone = number
                break

    if phone is None:
        # Check if recipient is already a phone number
        if recipient.startswith("+"):
            phone = recipient
        else:
            await params.result_callback({
                "status": "error",
                "detail": f"Contact '{recipient}' not found. Known contacts: {', '.join(cfg.sms_contacts.keys())}",
            })
            return

    confirmation_id = str(uuid.uuid4())[:8]
    _pending_sms[confirmation_id] = {
        "phone": phone,
        "message": message,
        "recipient": recipient,
    }

    await params.result_callback({
        "status": "pending_confirmation",
        "confirmation_id": confirmation_id,
        "recipient": recipient,
        "phone": phone,
        "message": message,
    })


async def handle_confirm_send_sms(params: FunctionCallParams) -> None:
    """Confirm and send a previously prepared SMS."""
    confirmation_id = params.arguments["confirmation_id"]

    pending = _pending_sms.pop(confirmation_id, None)
    if pending is None:
        await params.result_callback({
            "status": "error",
            "detail": "Confirmation not found or expired.",
        })
        return

    cfg = _voice_config
    if cfg is None or not cfg.sms_gateway_host:
        await params.result_callback({"status": "error", "detail": "SMS gateway not configured"})
        return

    try:
        password = _get_sms_password(cfg.sms_gateway_pass_key)
        url = f"http://{cfg.sms_gateway_host}/messages"
        response = httpx.post(
            url,
            json={
                "phoneNumbers": [pending["phone"]],
                "textMessage": {"text": pending["message"]},
            },
            auth=(cfg.sms_gateway_user, password),
            timeout=10.0,
        )

        if response.status_code in (200, 201, 202):
            await params.result_callback({
                "status": "sent",
                "recipient": pending["recipient"],
                "phone": pending["phone"],
            })
        else:
            await params.result_callback({
                "status": "error",
                "detail": f"SMS gateway returned {response.status_code}: {response.text}",
            })

    except Exception as exc:
        log.exception("SMS send failed")
        await params.result_callback({"status": "error", "detail": f"SMS send failed: {exc}"})
```

**Step 5: Run test to verify it passes**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_tool_handlers.py::TestSendSmsHandler tests/hapax_voice/test_tool_handlers.py::TestConfirmSendSmsHandler -v`
Expected: 4 PASSED

**Step 6: Commit**

```bash
git add agents/hapax_voice/tools.py tests/hapax_voice/test_tool_handlers.py pyproject.toml
git commit -m "feat(voice): implement SMS send/confirm handlers with Android SMS Gateway"
```

---

### Task 8: Implement `analyze_scene` handler

**Files:**
- Modify: `agents/hapax_voice/tools.py`
- Modify: `tests/hapax_voice/test_tool_handlers.py`

**Step 1: Write the failing test**

Add to `tests/hapax_voice/test_tool_handlers.py`:

```python
class TestAnalyzeSceneHandler:
    @pytest.mark.asyncio
    async def test_captures_and_analyzes(self, mock_fn_params):
        from agents.hapax_voice.tools import handle_analyze_scene

        mock_fn_params.arguments = {"question": "What equipment is visible?"}

        mock_webcam = MagicMock()
        mock_webcam.has_camera.return_value = True
        mock_webcam.capture.return_value = "base64_image_data"
        mock_webcam.reset_cooldown = MagicMock()

        mock_screen = MagicMock()
        mock_screen.capture.return_value = "base64_screen_data"
        mock_screen.reset_cooldown = MagicMock()

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "I can see a mixer and two SP-404s"

        with patch("agents.hapax_voice.tools._webcam_capturer", mock_webcam), \
             patch("agents.hapax_voice.tools._screen_capturer", mock_screen), \
             patch("agents.hapax_voice.tools._vision_analyze", return_value="I can see a mixer and two SP-404s"):
            await handle_analyze_scene(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "mixer" in result.lower() or "SP-404" in result

    @pytest.mark.asyncio
    async def test_no_cameras_available(self, mock_fn_params):
        from agents.hapax_voice.tools import handle_analyze_scene

        mock_fn_params.arguments = {}

        mock_webcam = MagicMock()
        mock_webcam.has_camera.return_value = False
        mock_webcam.capture.return_value = None

        mock_screen = MagicMock()
        mock_screen.capture.return_value = None

        with patch("agents.hapax_voice.tools._webcam_capturer", mock_webcam), \
             patch("agents.hapax_voice.tools._screen_capturer", mock_screen):
            await handle_analyze_scene(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "no images" in result.lower() or "couldn't capture" in result.lower()
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_tool_handlers.py::TestAnalyzeSceneHandler -v`
Expected: FAIL — `handle_analyze_scene` not found

**Step 3: Write minimal implementation**

Add to `agents/hapax_voice/tools.py`:

```python
import os

from openai import OpenAI

# Module-level references set during registration
_webcam_capturer = None
_screen_capturer = None


def _vision_analyze(images: list[str], question: str) -> str:
    """Send base64 images to Gemini Flash for visual analysis via LiteLLM."""
    base_url = os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:4000")
    api_key = os.environ.get("LITELLM_API_KEY", "not-set")
    client = OpenAI(base_url=base_url, api_key=api_key)

    content = []
    for img in images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{img}"},
        })
    content.append({"type": "text", "text": question or "Describe what you see in detail."})

    response = client.chat.completions.create(
        model="gemini-2.0-flash",
        messages=[{"role": "user", "content": content}],
        max_tokens=500,
    )
    return response.choices[0].message.content


async def handle_analyze_scene(params: FunctionCallParams) -> None:
    """Capture images from cameras/screen and analyze with vision model."""
    cameras = params.arguments.get("cameras", ["operator", "hardware", "screen"])
    question = params.arguments.get("question", "Describe what you see.")

    try:
        images = []

        if _webcam_capturer is not None:
            for role in cameras:
                if role in ("operator", "hardware"):
                    _webcam_capturer.reset_cooldown(role)
                    frame = _webcam_capturer.capture(role)
                    if frame:
                        images.append(frame)

        if "screen" in cameras and _screen_capturer is not None:
            _screen_capturer.reset_cooldown()
            screen = _screen_capturer.capture()
            if screen:
                images.append(screen)

        if not images:
            await params.result_callback("Couldn't capture any images — no cameras or screen available.")
            return

        analysis = _vision_analyze(images, question)
        await params.result_callback(analysis)

    except Exception as exc:
        log.exception("analyze_scene failed")
        await params.result_callback(f"Scene analysis failed: {exc}")
```

**Step 4: Run test to verify it passes**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_tool_handlers.py::TestAnalyzeSceneHandler -v`
Expected: 2 PASSED

**Step 5: Commit**

```bash
git add agents/hapax_voice/tools.py tests/hapax_voice/test_tool_handlers.py
git commit -m "feat(voice): implement analyze_scene handler with camera capture + Gemini Flash"
```

---

### Task 9: Implement `get_system_status` handler

**Files:**
- Modify: `agents/hapax_voice/tools.py`
- Modify: `tests/hapax_voice/test_tool_handlers.py`

**Step 1: Write the failing test**

Add to `tests/hapax_voice/test_tool_handlers.py`:

```python
class TestGetSystemStatusHandler:
    @pytest.mark.asyncio
    async def test_returns_status_summary(self, mock_fn_params):
        from agents.hapax_voice.tools import handle_get_system_status

        mock_fn_params.arguments = {}

        mock_results = [
            MagicMock(name="docker.daemon", group="docker", status=MagicMock(value="healthy"),
                      message="Docker 27.0", detail=None),
            MagicMock(name="gpu.vram", group="gpu", status=MagicMock(value="healthy"),
                      message="10GB/24GB used", detail=None),
        ]

        with patch("agents.hapax_voice.tools._run_health_checks", return_value=mock_results):
            await handle_get_system_status(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "docker" in result.lower() or "healthy" in result.lower()

    @pytest.mark.asyncio
    async def test_category_filter(self, mock_fn_params):
        from agents.hapax_voice.tools import handle_get_system_status

        mock_fn_params.arguments = {"category": "gpu"}

        mock_results = [
            MagicMock(name="gpu.vram", group="gpu", status=MagicMock(value="healthy"),
                      message="10GB/24GB", detail=None),
        ]

        with patch("agents.hapax_voice.tools._run_health_checks", return_value=mock_results):
            await handle_get_system_status(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        mock_fn_params.result_callback.assert_awaited_once()
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_tool_handlers.py::TestGetSystemStatusHandler -v`
Expected: FAIL — `handle_get_system_status` not found

**Step 3: Write minimal implementation**

Add to `agents/hapax_voice/tools.py`:

```python
import asyncio
import json
from pathlib import Path

_HEALTH_CACHE_PATH = Path.home() / ".cache" / "hapax" / "health-monitor" / "latest.json"
_HEALTH_CACHE_MAX_AGE_S = 900  # 15 minutes


async def _run_health_checks(category: str | None = None) -> list:
    """Run health checks, using cache if fresh enough."""
    # Try cache first
    if _HEALTH_CACHE_PATH.exists():
        import time
        age = time.time() - _HEALTH_CACHE_PATH.stat().st_mtime
        if age < _HEALTH_CACHE_MAX_AGE_S:
            try:
                data = json.loads(_HEALTH_CACHE_PATH.read_text())
                results = data if isinstance(data, list) else data.get("results", [])
                if category:
                    results = [r for r in results if r.get("group") == category]
                return results
            except Exception:
                pass

    # Fall back to running checks directly
    try:
        from agents.health_monitor import CHECK_REGISTRY
        all_results = []
        groups = [category] if category and category in CHECK_REGISTRY else CHECK_REGISTRY.keys()
        for group in groups:
            for check_fn in CHECK_REGISTRY.get(group, []):
                results = await check_fn()
                all_results.extend(results)
        return all_results
    except Exception as exc:
        log.warning("Health check execution failed: %s", exc)
        return []


async def handle_get_system_status(params: FunctionCallParams) -> None:
    """Report current system health and infrastructure status."""
    category = params.arguments.get("category")

    try:
        results = await _run_health_checks(category)

        if not results:
            await params.result_callback("No health check results available.")
            return

        lines = []
        for r in results:
            if isinstance(r, dict):
                name = r.get("name", "?")
                status = r.get("status", "?")
                message = r.get("message", "")
            else:
                name = getattr(r, "name", "?")
                status = getattr(r, "status", "?")
                if hasattr(status, "value"):
                    status = status.value
                message = getattr(r, "message", "")
            lines.append(f"- {name}: {status} — {message}")

        await params.result_callback("\n".join(lines))

    except Exception as exc:
        log.exception("get_system_status failed")
        await params.result_callback(f"Status check failed: {exc}")
```

**Step 4: Run test to verify it passes**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_tool_handlers.py::TestGetSystemStatusHandler -v`
Expected: 2 PASSED

**Step 5: Commit**

```bash
git add agents/hapax_voice/tools.py tests/hapax_voice/test_tool_handlers.py
git commit -m "feat(voice): implement get_system_status handler with health check cache"
```

---

### Task 10: Tool registration function and pipeline integration

**Files:**
- Modify: `agents/hapax_voice/tools.py` (add `register_tool_handlers`)
- Modify: `agents/hapax_voice/pipeline.py` (wire tools into pipeline)
- Test: `tests/hapax_voice/test_tool_registration.py`

**Step 1: Write the failing test**

```python
# tests/hapax_voice/test_tool_registration.py
"""Tests for tool registration on the Pipecat LLM service."""
from unittest.mock import MagicMock, patch

import pytest

from agents.hapax_voice.config import VoiceConfig


def test_register_tool_handlers_calls_register_function():
    from agents.hapax_voice.tools import register_tool_handlers

    mock_llm = MagicMock()
    cfg = VoiceConfig(tools_enabled=True)

    register_tool_handlers(mock_llm, cfg)

    # Should register all 8 handlers
    assert mock_llm.register_function.call_count == 8

    registered_names = [call.args[0] for call in mock_llm.register_function.call_args_list]
    assert "search_documents" in registered_names
    assert "get_calendar_today" in registered_names
    assert "search_emails" in registered_names
    assert "search_drive" in registered_names
    assert "send_sms" in registered_names
    assert "confirm_send_sms" in registered_names
    assert "analyze_scene" in registered_names
    assert "get_system_status" in registered_names


def test_register_skipped_when_tools_disabled():
    from agents.hapax_voice.tools import register_tool_handlers

    mock_llm = MagicMock()
    cfg = VoiceConfig(tools_enabled=False)

    register_tool_handlers(mock_llm, cfg)

    mock_llm.register_function.assert_not_called()


def test_build_pipeline_task_accepts_tools():
    """Verify pipeline.build_pipeline_task signature accepts tools parameter."""
    from agents.hapax_voice.pipeline import build_pipeline_task
    import inspect

    sig = inspect.signature(build_pipeline_task)
    assert "config" in sig.parameters or "tools" in sig.parameters
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_tool_registration.py -v`
Expected: FAIL — `register_tool_handlers` not found

**Step 3: Write minimal implementation**

Add to `agents/hapax_voice/tools.py`:

```python
def register_tool_handlers(
    llm: OpenAILLMService,
    config: VoiceConfig,
    webcam_capturer=None,
    screen_capturer=None,
) -> None:
    """Register all async tool handlers on the LLM service.

    Args:
        llm: The Pipecat OpenAI LLM service instance.
        config: Voice daemon config with SMS gateway settings etc.
        webcam_capturer: Optional WebcamCapturer instance for vision tools.
        screen_capturer: Optional ScreenCapturer instance for vision tools.
    """
    if not config.tools_enabled:
        log.info("Tools disabled by config")
        return

    global _voice_config, _webcam_capturer, _screen_capturer
    _voice_config = config
    _webcam_capturer = webcam_capturer
    _screen_capturer = screen_capturer

    llm.register_function("search_documents", handle_search_documents)
    llm.register_function("get_calendar_today", handle_get_calendar_today)
    llm.register_function("search_emails", handle_search_emails)
    llm.register_function("search_drive", handle_search_drive)
    llm.register_function("send_sms", handle_send_sms)
    llm.register_function("confirm_send_sms", handle_confirm_send_sms)
    llm.register_function("analyze_scene", handle_analyze_scene)
    llm.register_function("get_system_status", handle_get_system_status)

    log.info("Registered %d voice tools", 8)


async def handle_search_drive(params: FunctionCallParams) -> None:
    """Search Google Drive documents — thin wrapper around search_documents."""
    # Inject source_filter=gdrive and delegate
    params.arguments["source_filter"] = "gdrive"
    await handle_search_documents(params)
```

**Step 4: Modify `pipeline.py` to accept and wire tools**

Update `build_pipeline_task` in `agents/hapax_voice/pipeline.py`:

```python
def build_pipeline_task(
    *,
    stt_model: str = "large-v3",
    llm_model: str = "claude-sonnet",
    kokoro_voice: str = "af_heart",
    guest_mode: bool = False,
    config: VoiceConfig | None = None,
    webcam_capturer=None,
    screen_capturer=None,
) -> tuple[PipelineTask, LocalAudioTransport]:
```

Add after `llm = _build_llm(...)`:

```python
    # Register tools
    from agents.hapax_voice.tools import get_tool_schemas, register_tool_handlers
    tools = get_tool_schemas(guest_mode=guest_mode)
    if config is not None:
        register_tool_handlers(llm, config, webcam_capturer, screen_capturer)
```

Update `_build_context` call:

```python
    context = OpenAILLMContext(
        messages=[{"role": "system", "content": prompt}],
        tools=tools,
    )
```

Add import at top of `pipeline.py`:

```python
from agents.hapax_voice.config import VoiceConfig
```

**Step 5: Run test to verify it passes**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_tool_registration.py -v`
Expected: 3 PASSED

**Step 6: Commit**

```bash
git add agents/hapax_voice/tools.py agents/hapax_voice/pipeline.py tests/hapax_voice/test_tool_registration.py
git commit -m "feat(voice): wire tool registration into pipeline — 8 handlers + schema injection"
```

---

### Task 11: Update system prompt for tool awareness

**Files:**
- Modify: `agents/hapax_voice/persona.py`
- Test: `tests/hapax_voice/test_persona.py` (if exists, add test; otherwise create)

**Step 1: Write the failing test**

```python
# tests/hapax_voice/test_tool_persona.py
"""Tests for tool-aware system prompt."""
from agents.hapax_voice.persona import system_prompt


def test_operator_prompt_mentions_tools():
    prompt = system_prompt(guest_mode=False)
    assert "search" in prompt.lower() or "documents" in prompt.lower()
    assert "calendar" in prompt.lower()
    assert "sms" in prompt.lower() or "message" in prompt.lower()
    assert "camera" in prompt.lower() or "see" in prompt.lower()


def test_guest_prompt_does_not_mention_tools():
    prompt = system_prompt(guest_mode=True)
    assert "search" not in prompt.lower() or "cannot" in prompt.lower()
    assert "sms" not in prompt.lower()
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_tool_persona.py -v`
Expected: FAIL — prompt doesn't mention tools yet

**Step 3: Write minimal implementation**

Edit `agents/hapax_voice/persona.py`, replace `_SYSTEM_PROMPT`:

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

**Step 4: Run test to verify it passes**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_tool_persona.py -v`
Expected: 2 PASSED

**Step 5: Commit**

```bash
git add agents/hapax_voice/persona.py tests/hapax_voice/test_tool_persona.py
git commit -m "feat(voice): update system prompt with tool capabilities"
```

---

### Task 12: Wire daemon to pass config and capturers to pipeline

**Files:**
- Modify: `agents/hapax_voice/__main__.py` (~line 212-246, `_start_local_pipeline`)

**Step 1: Write the failing test**

```python
# tests/hapax_voice/test_daemon_tool_wiring.py
"""Test that VoiceDaemon passes config and capturers to pipeline."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_start_local_pipeline_passes_config():
    """Verify _start_local_pipeline passes config, webcam, screen to build_pipeline_task."""
    with patch("agents.hapax_voice.__main__.build_pipeline_task") as mock_build:
        mock_task = MagicMock()
        mock_transport = MagicMock()
        mock_build.return_value = (mock_task, mock_transport)

        # Import after patching
        from agents.hapax_voice.__main__ import VoiceDaemon
        from agents.hapax_voice.config import VoiceConfig

        cfg = VoiceConfig()
        daemon = VoiceDaemon.__new__(VoiceDaemon)
        daemon.cfg = cfg
        daemon.session = MagicMock()
        daemon.session.is_guest_mode = False
        daemon._pipecat_task = None
        daemon._pipecat_transport = None
        daemon._pipeline_task = None

        # Set up webcam and screen capturers
        daemon.workspace_monitor = MagicMock()
        daemon.workspace_monitor.webcam_capturer = MagicMock()
        daemon.workspace_monitor.screen_capturer = MagicMock()

        with patch("agents.hapax_voice.__main__.PipelineRunner") as mock_runner_cls:
            mock_runner = AsyncMock()
            mock_runner_cls.return_value = mock_runner
            await daemon._start_local_pipeline()

        # Verify config was passed
        call_kwargs = mock_build.call_args
        assert call_kwargs.kwargs.get("config") is not None
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_daemon_tool_wiring.py -v`
Expected: FAIL — `config` kwarg not passed

**Step 3: Write minimal implementation**

In `agents/hapax_voice/__main__.py`, update `_start_local_pipeline()` to pass config and capturers:

Find the `build_pipeline_task(` call (~line 220) and update to:

```python
        task, transport = build_pipeline_task(
            stt_model=self.cfg.local_stt_model,
            llm_model=self.cfg.llm_model,
            kokoro_voice=self.cfg.kokoro_voice,
            guest_mode=guest_mode,
            config=self.cfg,
            webcam_capturer=getattr(self.workspace_monitor, "webcam_capturer", None),
            screen_capturer=getattr(self.workspace_monitor, "screen_capturer", None),
        )
```

**Step 4: Run test to verify it passes**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_daemon_tool_wiring.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add agents/hapax_voice/__main__.py tests/hapax_voice/test_daemon_tool_wiring.py
git commit -m "feat(voice): pass config and capturers from daemon to pipeline for tool access"
```

---

### Task 13: Run full test suite and fix any issues

**Files:**
- All files from Tasks 1-12

**Step 1: Run all new tests**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_tools_config.py tests/hapax_voice/test_tool_schemas.py tests/hapax_voice/test_tool_handlers.py tests/hapax_voice/test_tool_registration.py tests/hapax_voice/test_tool_persona.py tests/hapax_voice/test_daemon_tool_wiring.py -v`
Expected: All PASSED

**Step 2: Run existing hapax_voice tests to verify no regressions**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/ -v --ignore=tests/hapax_voice/test_hardware.py -x`
Expected: All PASSED, no regressions

**Step 3: Fix any failures**

If any existing tests break due to `build_pipeline_task` signature change, update them to pass `config=None` (the new default).

**Step 4: Commit any fixes**

```bash
git add -u
git commit -m "fix(voice): resolve test regressions from tool pipeline wiring"
```

---

### Task 14: Android SMS Gateway phone setup (manual)

This task is manual — no code changes.

**Step 1: Install Android SMS Gateway app**

- Download from F-Droid or Google Play: "SMS Gateway"
- Package: `com.capcom6.smsgateway`

**Step 2: Configure local server mode**

- Open the app → Settings → Enable Local Server
- Note the phone's LAN IP and port (default 8080)
- Set a username and password

**Step 3: Store credentials in pass**

```bash
pass insert sms-gateway/password
# Enter the password you set in the app
```

**Step 4: Update voice config YAML**

Edit `~/.config/hapax-voice/config.yaml`:

```yaml
sms_gateway_host: "192.168.1.XX:8080"  # Replace with phone IP
sms_gateway_user: "hapax"
sms_contacts:
  Wife: "+1XXXXXXXXXX"
```

**Step 5: Test SMS connectivity**

```bash
curl -X POST -u hapax:$(pass show sms-gateway/password) \
  -H "Content-Type: application/json" \
  -d '{"phoneNumbers": ["+1XXXXXXXXXX"], "textMessage": {"text": "Test from Hapax"}}' \
  http://192.168.1.XX:8080/messages
```

---

### Task 15: Manual end-to-end voice test

**Step 1: Start the voice daemon**

```bash
cd ~/projects/ai-agents && uv run python -m agents.hapax_voice --config ~/.config/hapax-voice/config.yaml
```

**Step 2: Test document search**

Say "Hapax" → wait for acknowledgment → "What notes do I have about studio layout?"
Expected: Hapax searches Qdrant and speaks a summary of matching documents.

**Step 3: Test calendar**

Say "Hapax" → "What's on my calendar today?"
Expected: Hapax calls Google Calendar API and reads back events.

**Step 4: Test email search**

Say "Hapax" → "Any recent emails about the project?"
Expected: Hapax searches Qdrant for Gmail-sourced documents and summarizes.

**Step 5: Test vision**

Say "Hapax" → "What do you see?"
Expected: Hapax captures camera frames, sends to Gemini Flash, describes the scene.

**Step 6: Test SMS (if gateway configured)**

Say "Hapax" → "Text my wife I'll be home in 20 minutes"
Expected: Hapax says "I'll text your wife: 'I'll be home in 20 minutes'. Should I send it?"
Say "Yes" → Expected: "Sent."

**Step 7: Test system status**

Say "Hapax" → "How's the system doing?"
Expected: Hapax reads health check results aloud.
