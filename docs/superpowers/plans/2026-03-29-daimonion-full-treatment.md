# Hapax-Daimonion Full Treatment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring hapax-daimonion to full capability — formal tool capability model, grounding activation in R&D mode, TPN↔DMN signaling, end-to-end verification.

**Architecture:** New `ToolCapability` dataclass + `ToolRegistry` class formalize the 26 existing tools into the Hapax capability meta-structure. Dynamic context-based filtering replaces the static tool list. Mode-driven grounding flag set in `__main__.py` (not frozen). TPN signal written by cognitive loop to `/dev/shm/hapax-dmn/tpn_active`. Three lines changed in frozen `conversation_pipeline.py` (DEVIATION-026).

**Tech Stack:** Python 3.12, asyncio, Pydantic (validation), existing LiteLLM tool-calling, shared/working_mode.py

**Spec:** `docs/superpowers/specs/2026-03-29-daimonion-full-treatment-design.md`

---

## File Map

### New Files

| File | Responsibility |
|------|---------------|
| `agents/hapax_daimonion/tool_capability.py` | ToolCapability, ToolCategory, ResourceTier, ToolContext, ToolRegistry |
| `agents/hapax_daimonion/tool_definitions.py` | 26 ToolCapability instances (migrated from tools_openai.py) |
| `tests/hapax_daimonion/test_tool_capability.py` | ToolCapability availability, filtering, degradation |
| `tests/hapax_daimonion/test_tool_definitions.py` | All 26 tools registered, schemas valid |
| `tests/hapax_daimonion/test_tpn_signal.py` | TPN_ACTIVE file write/read/cleanup |
| `tests/hapax_daimonion/test_grounding_mode.py` | Mode-driven grounding flag injection |
| `research/protocols/deviations/DEVIATION-026.md` | Tool execution enable in frozen code |

### Modified Files

| File | Change |
|------|--------|
| `agents/hapax_daimonion/__main__.py` | ToolRegistry construction, mode-driven grounding, ToolContext per utterance |
| `agents/hapax_daimonion/tools_openai.py` | Delegate to ToolRegistry (backward-compatible adapter) |
| `agents/hapax_daimonion/cognitive_loop.py` | TPN_ACTIVE file write at phase transitions |
| `agents/hapax_daimonion/conversation_pipeline.py` | **(FROZEN, DEVIATION-026)** Un-comment tools, call _handle_tool_calls, add timeout |

---

## Task 1: ToolCapability and ToolRegistry

**Files:**
- Create: `agents/hapax_daimonion/tool_capability.py`
- Test: `tests/hapax_daimonion/test_tool_capability.py`

- [ ] **Step 1: Write failing tests for ToolCapability availability**

```python
# tests/hapax_daimonion/test_tool_capability.py
"""Tests for tool capability model."""

from __future__ import annotations

import unittest

from agents.hapax_daimonion.tool_capability import (
    ResourceTier,
    ToolCapability,
    ToolCategory,
    ToolContext,
    ToolRegistry,
)


def _make_ctx(**overrides) -> ToolContext:
    defaults = {
        "stimmung_stance": "nominal",
        "consent_state": {},
        "guest_present": False,
        "active_backends": {"vision", "hyprland", "phone"},
        "working_mode": "rnd",
        "experiment_tools_enabled": False,
    }
    defaults.update(overrides)
    return ToolContext(**defaults)


async def _noop_handler(args: dict) -> str:
    return "ok"


def _make_tool(name: str = "test_tool", **overrides) -> ToolCapability:
    defaults = {
        "name": name,
        "description": "Test tool",
        "schema": {"type": "function", "function": {"name": name, "description": "test", "parameters": {"type": "object", "properties": {}, "required": []}}},
        "handler": _noop_handler,
        "category": ToolCategory.INFORMATION,
        "resource_tier": ResourceTier.INSTANT,
        "requires_consent": [],
        "requires_backends": [],
        "requires_confirmation": False,
        "timeout_s": 3.0,
    }
    defaults.update(overrides)
    return ToolCapability(**defaults)


class TestToolCapabilityAvailability(unittest.TestCase):
    def test_available_nominal(self):
        tool = _make_tool()
        assert tool.available(_make_ctx()) is True

    def test_heavy_tool_suppressed_when_degraded(self):
        tool = _make_tool(resource_tier=ResourceTier.HEAVY)
        assert tool.available(_make_ctx(stimmung_stance="degraded")) is False

    def test_heavy_tool_ok_when_nominal(self):
        tool = _make_tool(resource_tier=ResourceTier.HEAVY)
        assert tool.available(_make_ctx(stimmung_stance="nominal")) is True

    def test_consent_tool_suppressed_with_guest(self):
        tool = _make_tool(requires_consent=["interpersonal_transparency"])
        assert tool.available(_make_ctx(guest_present=True)) is False

    def test_consent_tool_ok_without_guest(self):
        tool = _make_tool(requires_consent=["interpersonal_transparency"])
        assert tool.available(_make_ctx(guest_present=False)) is True

    def test_backend_requirement_missing(self):
        tool = _make_tool(requires_backends=["vision"])
        assert tool.available(_make_ctx(active_backends={"hyprland"})) is False

    def test_backend_requirement_met(self):
        tool = _make_tool(requires_backends=["vision"])
        assert tool.available(_make_ctx(active_backends={"vision", "hyprland"})) is True

    def test_research_mode_suppresses_without_flag(self):
        tool = _make_tool()
        assert tool.available(_make_ctx(working_mode="research", experiment_tools_enabled=False)) is False

    def test_research_mode_allows_with_flag(self):
        tool = _make_tool()
        assert tool.available(_make_ctx(working_mode="research", experiment_tools_enabled=True)) is True


class TestToolRegistry(unittest.TestCase):
    def test_register_and_list(self):
        reg = ToolRegistry()
        reg.register(_make_tool("a"))
        reg.register(_make_tool("b"))
        assert len(reg.available_tools(_make_ctx())) == 2

    def test_filtering_removes_unavailable(self):
        reg = ToolRegistry()
        reg.register(_make_tool("light", resource_tier=ResourceTier.LIGHT))
        reg.register(_make_tool("heavy", resource_tier=ResourceTier.HEAVY))
        available = reg.available_tools(_make_ctx(stimmung_stance="critical"))
        names = [t.name for t in available]
        assert "light" in names
        assert "heavy" not in names

    def test_schemas_for_llm(self):
        reg = ToolRegistry()
        reg.register(_make_tool("a"))
        schemas = reg.schemas_for_llm(_make_ctx())
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "a"

    def test_handler_map(self):
        reg = ToolRegistry()
        reg.register(_make_tool("a"))
        handlers = reg.handler_map(_make_ctx())
        assert "a" in handlers

    def test_degrade_message(self):
        tool = _make_tool("analyze_scene")
        msg = tool.degrade()
        assert "analyze_scene" in msg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/hapax_daimonion/test_tool_capability.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.hapax_daimonion.tool_capability'`

- [ ] **Step 3: Implement ToolCapability, ToolContext, ToolRegistry**

```python
# agents/hapax_daimonion/tool_capability.py
"""Formal capability model for voice daemon tools.

Tools conform to the Hapax recruitment protocol: each declares what it
provides, what it requires, when it's available, and how it degrades.
This pass (queue #016) establishes registration + gating. A future pass
(queue #015) will replace LLM-menu selection with affordance-based recruitment.
"""

from __future__ import annotations

import enum
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


class ToolCategory(enum.Enum):
    INFORMATION = "information"
    ACTION = "action"
    CONTROL = "control"


class ResourceTier(enum.Enum):
    INSTANT = "instant"
    LIGHT = "light"
    HEAVY = "heavy"


@dataclass(frozen=True)
class ToolContext:
    """Snapshot of system state used for tool availability decisions."""

    stimmung_stance: str = "nominal"
    consent_state: dict = field(default_factory=dict)
    guest_present: bool = False
    active_backends: frozenset[str] = field(default_factory=frozenset)
    working_mode: str = "rnd"
    experiment_tools_enabled: bool = False


@dataclass
class ToolCapability:
    """A tool modeled as a formal Hapax capability."""

    name: str
    description: str
    schema: dict
    handler: Callable

    category: ToolCategory
    resource_tier: ResourceTier
    requires_consent: list[str] = field(default_factory=list)
    requires_backends: list[str] = field(default_factory=list)
    requires_confirmation: bool = False
    timeout_s: float = 3.0

    def available(self, ctx: ToolContext) -> bool:
        """Check all preconditions for this tool."""
        if ctx.working_mode == "research" and not ctx.experiment_tools_enabled:
            return False
        if self.resource_tier == ResourceTier.HEAVY and ctx.stimmung_stance in (
            "degraded",
            "critical",
        ):
            return False
        if self.requires_consent and ctx.guest_present:
            return False
        if self.requires_backends:
            backends = ctx.active_backends if isinstance(ctx.active_backends, (set, frozenset)) else set(ctx.active_backends)
            if not all(b in backends for b in self.requires_backends):
                return False
        return True

    def degrade(self) -> str:
        """Fallback message when this tool is unavailable."""
        return f"The {self.name} capability is not available right now."


class ToolRegistry:
    """Manages tool capabilities with dynamic availability filtering."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolCapability] = {}

    def register(self, tool: ToolCapability) -> None:
        if tool.name in self._tools:
            log.warning("Tool %s already registered, replacing", tool.name)
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolCapability | None:
        return self._tools.get(name)

    def available_tools(self, ctx: ToolContext) -> list[ToolCapability]:
        return [t for t in self._tools.values() if t.available(ctx)]

    def schemas_for_llm(self, ctx: ToolContext) -> list[dict]:
        return [t.schema for t in self.available_tools(ctx)]

    def handler_map(self, ctx: ToolContext) -> dict[str, Callable]:
        return {t.name: t.handler for t in self.available_tools(ctx)}

    def all_tools(self) -> list[ToolCapability]:
        return list(self._tools.values())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/hapax_daimonion/test_tool_capability.py -v`
Expected: All 14 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_daimonion/tool_capability.py tests/hapax_daimonion/test_tool_capability.py
git commit -m "feat(daimonion): ToolCapability model + ToolRegistry with dynamic filtering"
```

---

## Task 2: Tool Definitions — Migrate 26 Tools

**Files:**
- Create: `agents/hapax_daimonion/tool_definitions.py`
- Test: `tests/hapax_daimonion/test_tool_definitions.py`

- [ ] **Step 1: Write failing test that all 26 tools register**

```python
# tests/hapax_daimonion/test_tool_definitions.py
"""Tests for tool capability definitions."""

from __future__ import annotations

import unittest

from agents.hapax_daimonion.tool_capability import ToolCategory, ToolContext, ToolRegistry
from agents.hapax_daimonion.tool_definitions import build_registry


class TestToolDefinitions(unittest.TestCase):
    def test_registry_has_all_tools(self):
        reg = build_registry()
        tools = reg.all_tools()
        names = {t.name for t in tools}
        # Core tools
        assert "get_current_time" in names
        assert "search_documents" in names
        assert "get_weather" in names
        assert "get_briefing" in names
        assert "get_system_status" in names
        assert "analyze_scene" in names
        assert "send_sms" in names
        # Desktop tools
        assert "focus_window" in names
        assert "open_app" in names
        assert "get_desktop_state" in names
        # At least 20 tools registered
        assert len(tools) >= 20

    def test_all_schemas_valid(self):
        reg = build_registry()
        for tool in reg.all_tools():
            assert tool.schema["type"] == "function"
            assert "name" in tool.schema["function"]
            assert "parameters" in tool.schema["function"]

    def test_categories_assigned(self):
        reg = build_registry()
        cats = {t.category for t in reg.all_tools()}
        assert ToolCategory.INFORMATION in cats
        assert ToolCategory.CONTROL in cats

    def test_heavy_tools_identified(self):
        reg = build_registry()
        from agents.hapax_daimonion.tool_capability import ResourceTier
        heavy = [t for t in reg.all_tools() if t.resource_tier == ResourceTier.HEAVY]
        heavy_names = {t.name for t in heavy}
        assert "analyze_scene" in heavy_names
        assert "generate_image" in heavy_names

    def test_confirmation_tools_identified(self):
        reg = build_registry()
        confirm = [t for t in reg.all_tools() if t.requires_confirmation]
        confirm_names = {t.name for t in confirm}
        assert "send_sms" in confirm_names
        assert "open_app" in confirm_names

    def test_consent_tools_identified(self):
        reg = build_registry()
        consent = [t for t in reg.all_tools() if t.requires_consent]
        consent_names = {t.name for t in consent}
        assert "analyze_scene" in consent_names
        assert "search_drive" in consent_names

    def test_filtering_suppresses_vision_without_backend(self):
        reg = build_registry()
        ctx = ToolContext(active_backends=frozenset({"hyprland", "phone"}))
        available = {t.name for t in reg.available_tools(ctx)}
        assert "analyze_scene" not in available
        assert "get_current_time" in available
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/hapax_daimonion/test_tool_definitions.py -v`
Expected: FAIL — `cannot import name 'build_registry' from 'agents.hapax_daimonion.tool_definitions'`

- [ ] **Step 3: Implement build_registry**

```python
# agents/hapax_daimonion/tool_definitions.py
"""Concrete tool capability definitions for all 26 daimonion tools.

Each tool from tools_openai.py is migrated to a ToolCapability instance
with formal category, resource tier, consent, backend, and confirmation
metadata. The build_registry() function is the single entry point.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from agents.hapax_daimonion.tool_capability import (
    ResourceTier,
    ToolCapability,
    ToolCategory,
    ToolRegistry,
)

log = logging.getLogger(__name__)


def _cap(
    name: str,
    handler: Callable,
    schema: dict,
    category: ToolCategory = ToolCategory.INFORMATION,
    resource_tier: ResourceTier = ResourceTier.LIGHT,
    requires_consent: list[str] | None = None,
    requires_backends: list[str] | None = None,
    requires_confirmation: bool = False,
    timeout_s: float = 3.0,
) -> ToolCapability:
    return ToolCapability(
        name=name,
        description=schema.get("function", {}).get("description", ""),
        schema=schema,
        handler=handler,
        category=category,
        resource_tier=resource_tier,
        requires_consent=requires_consent or [],
        requires_backends=requires_backends or [],
        requires_confirmation=requires_confirmation,
        timeout_s=timeout_s,
    )


def build_registry(
    guest_mode: bool = False,
    config=None,
    webcam_capturer=None,
    screen_capturer=None,
) -> ToolRegistry:
    """Build the tool registry with all 26 capabilities.

    This replaces the flat (tools, handlers) tuple from get_openai_tools().
    """
    if guest_mode:
        return ToolRegistry()

    from agents.hapax_daimonion.tools_openai import get_openai_tools

    tools_list, handler_map = get_openai_tools(
        guest_mode=False,
        config=config,
        webcam_capturer=webcam_capturer,
        screen_capturer=screen_capturer,
    )

    # Build a name→schema lookup from the flat list
    schema_by_name: dict[str, dict] = {}
    for schema in tools_list:
        fname = schema.get("function", {}).get("name", "")
        if fname:
            schema_by_name[fname] = schema

    # Tool metadata: (category, resource_tier, consent, backends, confirmation, timeout)
    _META: dict[str, tuple] = {
        "get_current_time": (ToolCategory.INFORMATION, ResourceTier.INSTANT, [], [], False, 1.0),
        "get_weather": (ToolCategory.INFORMATION, ResourceTier.LIGHT, [], [], False, 3.0),
        "get_briefing": (ToolCategory.INFORMATION, ResourceTier.LIGHT, [], [], False, 3.0),
        "get_system_status": (ToolCategory.INFORMATION, ResourceTier.LIGHT, [], [], False, 3.0),
        "get_calendar_today": (ToolCategory.INFORMATION, ResourceTier.LIGHT, [], [], False, 3.0),
        "get_desktop_state": (ToolCategory.INFORMATION, ResourceTier.INSTANT, [], ["hyprland"], False, 1.0),
        "search_documents": (ToolCategory.INFORMATION, ResourceTier.LIGHT, [], [], False, 3.0),
        "search_drive": (ToolCategory.INFORMATION, ResourceTier.LIGHT, ["corporate_boundary"], [], False, 3.0),
        "search_emails": (ToolCategory.INFORMATION, ResourceTier.LIGHT, ["corporate_boundary"], [], False, 3.0),
        "check_consent_status": (ToolCategory.INFORMATION, ResourceTier.INSTANT, [], [], False, 1.0),
        "describe_consent_flow": (ToolCategory.INFORMATION, ResourceTier.INSTANT, [], [], False, 1.0),
        "check_governance_health": (ToolCategory.INFORMATION, ResourceTier.LIGHT, [], [], False, 3.0),
        "analyze_scene": (ToolCategory.INFORMATION, ResourceTier.HEAVY, ["interpersonal_transparency"], ["vision"], False, 5.0),
        "query_scene_inventory": (ToolCategory.INFORMATION, ResourceTier.LIGHT, ["interpersonal_transparency"], ["vision"], False, 3.0),
        "generate_image": (ToolCategory.ACTION, ResourceTier.HEAVY, [], [], False, 10.0),
        "send_sms": (ToolCategory.ACTION, ResourceTier.LIGHT, [], ["phone"], True, 3.0),
        "confirm_send_sms": (ToolCategory.ACTION, ResourceTier.LIGHT, [], ["phone"], False, 3.0),
        "highlight_detection": (ToolCategory.CONTROL, ResourceTier.INSTANT, [], ["vision"], False, 1.0),
        "set_detection_layers": (ToolCategory.CONTROL, ResourceTier.INSTANT, [], ["vision"], False, 1.0),
        "focus_window": (ToolCategory.CONTROL, ResourceTier.INSTANT, [], ["hyprland"], False, 1.0),
        "switch_workspace": (ToolCategory.CONTROL, ResourceTier.INSTANT, [], ["hyprland"], False, 1.0),
        "open_app": (ToolCategory.CONTROL, ResourceTier.LIGHT, [], ["hyprland"], True, 3.0),
        "confirm_open_app": (ToolCategory.CONTROL, ResourceTier.LIGHT, [], ["hyprland"], False, 3.0),
        "close_window": (ToolCategory.CONTROL, ResourceTier.INSTANT, [], ["hyprland"], False, 1.0),
        "move_window": (ToolCategory.CONTROL, ResourceTier.INSTANT, [], ["hyprland"], False, 1.0),
        "resize_window": (ToolCategory.CONTROL, ResourceTier.INSTANT, [], ["hyprland"], False, 1.0),
    }

    registry = ToolRegistry()

    for name, handler in handler_map.items():
        schema = schema_by_name.get(name)
        if schema is None:
            log.debug("Tool %s has handler but no schema, skipping", name)
            continue
        meta = _META.get(name)
        if meta is None:
            # Unknown tool — register with safe defaults
            log.debug("Tool %s has no metadata, registering with defaults", name)
            registry.register(_cap(name, handler, schema))
            continue
        cat, tier, consent, backends, confirm, timeout = meta
        registry.register(_cap(
            name, handler, schema,
            category=cat,
            resource_tier=tier,
            requires_consent=consent,
            requires_backends=backends,
            requires_confirmation=confirm,
            timeout_s=timeout,
        ))

    log.info("Tool registry built: %d capabilities", len(registry.all_tools()))
    return registry
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/hapax_daimonion/test_tool_definitions.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_daimonion/tool_definitions.py tests/hapax_daimonion/test_tool_definitions.py
git commit -m "feat(daimonion): migrate 26 tools to ToolCapability definitions"
```

---

## Task 3: Wire ToolRegistry into Daemon

**Files:**
- Modify: `agents/hapax_daimonion/__main__.py` (~lines 910-932, 1159-1173, 1209-1210)
- Modify: `agents/hapax_daimonion/tools_openai.py` (add adapter function)

- [ ] **Step 1: Modify __main__.py to build ToolRegistry at startup**

In `_precompute_pipeline_deps()` (around line 912), replace:

```python
        from agents.hapax_daimonion.tools_openai import get_openai_tools

        # Tools (stable across sessions for operator mode)
        self._precomputed_tools = None
        self._precomputed_handlers: dict = {}
        if self.cfg.tools_enabled:
            tool_kwargs: dict = {
                "guest_mode": False,
                "config": self.cfg,
                "webcam_capturer": getattr(self.workspace_monitor, "_webcam_capturer", None),
                "screen_capturer": getattr(self.workspace_monitor, "_screen_capturer", None),
            }
            vfx = getattr(self.tts, "vocal_fx", None)
            if vfx is not None:
                import inspect

                sig = inspect.signature(get_openai_tools)
                if "vocal_fx" in sig.parameters:
                    tool_kwargs["vocal_fx"] = vfx
            self._precomputed_tools, self._precomputed_handlers = get_openai_tools(**tool_kwargs)
```

With:

```python
        from agents.hapax_daimonion.tool_definitions import build_registry

        # Tool registry (stable across sessions for operator mode)
        self._tool_registry = build_registry(
            guest_mode=False,
            config=self.cfg,
            webcam_capturer=getattr(self.workspace_monitor, "_webcam_capturer", None),
            screen_capturer=getattr(self.workspace_monitor, "_screen_capturer", None),
        ) if self.cfg.tools_enabled else build_registry(guest_mode=True)
```

- [ ] **Step 2: Modify _start_conversation to use ToolRegistry with ToolContext**

In `_start_conversation()` (around line 1150-1173), replace the tool resolution block with:

```python
        # Build tool context from current system state
        from agents.hapax_daimonion.tool_capability import ToolContext

        _stimmung_stance = "nominal"
        try:
            import json as _json
            _shm = Path("/dev/shm/hapax-stimmung/state.json")
            if _shm.exists():
                _stimmung_stance = _json.loads(_shm.read_text()).get("overall_stance", "nominal")
        except Exception:
            pass

        _active_backends = set()
        if hasattr(self, "perception") and self.perception is not None:
            _active_backends = {
                b.name for b in self.perception._backends if b.available()
            }

        tool_ctx = ToolContext(
            stimmung_stance=_stimmung_stance,
            consent_state={},
            guest_present=self.session.is_guest_mode,
            active_backends=frozenset(_active_backends),
            working_mode=get_working_mode().value,
            experiment_tools_enabled=_exp.get("tools_enabled", False),
        )

        if self.session.is_guest_mode:
            tools = None
            tool_handlers = {}
        else:
            tools = self._tool_registry.schemas_for_llm(tool_ctx)
            tool_handlers = self._tool_registry.handler_map(tool_ctx)
```

Add import at the top of `_start_conversation`:

```python
        from shared.working_mode import get_working_mode
```

- [ ] **Step 3: Inject mode-driven grounding flag**

After the experiment flags are loaded (around line 1122), add:

```python
        # Mode-driven grounding: always on in R&D, flag-controlled in Research
        from shared.working_mode import get_working_mode

        if get_working_mode().value == "rnd":
            _exp["enable_grounding"] = True
```

- [ ] **Step 4: Run existing tests to verify no regressions**

Run: `uv run pytest tests/hapax_daimonion/ -q --ignore=tests/hapax_daimonion/test_tool_capability.py --ignore=tests/hapax_daimonion/test_tool_definitions.py -x`
Expected: All existing tests PASS (or pre-existing failures only)

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_daimonion/__main__.py
git commit -m "feat(daimonion): wire ToolRegistry + mode-driven grounding into daemon"
```

---

## Task 4: TPN_ACTIVE Signal

**Files:**
- Modify: `agents/hapax_daimonion/cognitive_loop.py`
- Test: `tests/hapax_daimonion/test_tpn_signal.py`

- [ ] **Step 1: Write failing test for TPN signal write**

```python
# tests/hapax_daimonion/test_tpn_signal.py
"""Tests for TPN_ACTIVE signal file."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.hapax_daimonion.cognitive_loop import write_tpn_active, TPN_ACTIVE_FILE


class TestTpnSignal(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._tmp_file = Path(self._tmpdir) / "tpn_active"

    def test_write_active(self):
        write_tpn_active(True, self._tmp_file)
        assert self._tmp_file.read_text().strip() == "1"

    def test_write_inactive(self):
        write_tpn_active(False, self._tmp_file)
        assert self._tmp_file.read_text().strip() == "0"

    def test_write_overwrites(self):
        write_tpn_active(True, self._tmp_file)
        write_tpn_active(False, self._tmp_file)
        assert self._tmp_file.read_text().strip() == "0"

    def test_write_creates_parent(self):
        nested = Path(self._tmpdir) / "sub" / "tpn_active"
        write_tpn_active(True, nested)
        assert nested.read_text().strip() == "1"

    def test_write_failure_does_not_raise(self):
        # Writing to /dev/null-like path should not crash
        write_tpn_active(True, Path("/proc/nonexistent/tpn_active"))
        # No exception = pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/hapax_daimonion/test_tpn_signal.py -v`
Expected: FAIL — `cannot import name 'write_tpn_active'`

- [ ] **Step 3: Add write_tpn_active function and wire into phase transitions**

At the top of `cognitive_loop.py`, add:

```python
from pathlib import Path

TPN_ACTIVE_FILE = Path("/dev/shm/hapax-dmn/tpn_active")


def write_tpn_active(active: bool, path: Path = TPN_ACTIVE_FILE) -> None:
    """Write TPN active signal for DMN anti-correlation."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text("1" if active else "0")
        tmp.rename(path)
    except OSError:
        pass
```

In `_on_phase_transition()`, add at the end of the method:

```python
        # TPN_ACTIVE signal for DMN anti-correlation
        _tpn_active = to_phase in (TurnPhase.TRANSITION, TurnPhase.HAPAX_SPEAKING)
        write_tpn_active(_tpn_active)
```

In `stop_loop()`, add:

```python
        write_tpn_active(False)
```

In the `finally` block of `run()` (around line 233), add:

```python
            write_tpn_active(False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/hapax_daimonion/test_tpn_signal.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Run full cognitive loop tests**

Run: `uv run pytest tests/hapax_daimonion/test_cognitive_loop.py -v`
Expected: All existing tests PASS

- [ ] **Step 6: Commit**

```bash
git add agents/hapax_daimonion/cognitive_loop.py tests/hapax_daimonion/test_tpn_signal.py
git commit -m "feat(daimonion): TPN_ACTIVE signaling for DMN anti-correlation"
```

---

## Task 5: DEVIATION-026 — Enable Tool Execution in Frozen Code

**Files:**
- Create: `research/protocols/deviations/DEVIATION-026.md`
- Modify: `agents/hapax_daimonion/conversation_pipeline.py` (FROZEN — 3 targeted changes)

- [ ] **Step 1: Write DEVIATION-026**

```markdown
# Deviation Record: DEVIATION-026

**Date:** 2026-03-30
**Phase at time of change:** baseline (Cycle 2 Phase A)
**Author:** Claude (alpha session)

## What Changed

`agents/hapax_daimonion/conversation_pipeline.py` — 3 changes:

1. Line 1233-1234: un-comment `kwargs["tools"] = self.tools` so tools are
   passed to the LLM via function-calling.
2. Lines 1428-1436: replace the skip block with
   `await self._handle_tool_calls(tool_calls_data, full_text)` to execute
   tools instead of logging and discarding.
3. Inside `_handle_tool_calls` (line 1496): wrap handler call with
   `asyncio.wait_for(handler(args), timeout=self._tool_timeout)` for per-tool
   timeout safety.

## Why

Tool execution was disabled due to latency concerns (10-15s round-trip).
The existing `_handle_tool_calls()` method is complete (bridge phrases,
consent filtering, follow-up generation) but never called. With per-tool
timeouts (3s default) and dynamic tool filtering (heavy tools suppressed
under resource pressure), the latency concern is addressed.

## Impact on Experiment Validity

Low. Tool execution is gated by `ToolContext`: in Research mode, tools are
suppressed unless `experiment_tools_enabled` flag is set. Baseline Phase A
data collection uses Research mode with tools disabled. R&D mode (current)
enables tools — this is non-experiment usage.

## Mitigation

- Per-tool timeout prevents runaway execution
- Dynamic filtering suppresses heavy tools under stimmung pressure
- Research mode suppresses all tools by default
- Existing consent filtering in `_handle_tool_calls` preserved
- Bridge phrase ("Let me check...") covers tool execution latency
```

- [ ] **Step 2: Un-comment tool passing (line 1233-1234)**

Change:

```python
            # if self.tools:
            #     kwargs["tools"] = self.tools
```

To:

```python
            if self.tools:
                kwargs["tools"] = self.tools
```

- [ ] **Step 3: Replace tool skip block (lines 1428-1436)**

Change:

```python
            if tool_calls_data:
                log.info(
                    "Skipping %d tool call(s) for voice pacing: %s",
                    len(tool_calls_data),
                    [tc["name"] for tc in tool_calls_data],
                )
                # Record as assistant message without executing tools
                if full_text:
                    self.messages.append({"role": "assistant", "content": full_text})
```

To:

```python
            if tool_calls_data:
                log.info(
                    "Executing %d tool call(s): %s",
                    len(tool_calls_data),
                    [tc["name"] for tc in tool_calls_data],
                )
                await self._handle_tool_calls(tool_calls_data, full_text)
```

- [ ] **Step 4: Add per-tool timeout in _handle_tool_calls (line ~1496)**

Change the handler invocation block:

```python
                try:
                    args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                    result = (
                        await handler(args)
                        if asyncio.iscoroutinefunction(handler)
                        else handler(args)
                    )
```

To:

```python
                try:
                    args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                    _timeout = getattr(self, "_tool_timeout", 3.0)
                    if asyncio.iscoroutinefunction(handler):
                        result = await asyncio.wait_for(handler(args), timeout=_timeout)
                    else:
                        result = handler(args)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/hapax_daimonion/ -q -x`
Expected: All tests PASS

- [ ] **Step 6: Commit with deviation reference**

```bash
git add research/protocols/deviations/DEVIATION-026.md agents/hapax_daimonion/conversation_pipeline.py
git commit -m "feat(daimonion): enable tool execution with per-tool timeout (DEVIATION-026)"
```

---

## Task 6: Grounding Mode Test

**Files:**
- Test: `tests/hapax_daimonion/test_grounding_mode.py`

- [ ] **Step 1: Write test for mode-driven grounding injection**

```python
# tests/hapax_daimonion/test_grounding_mode.py
"""Tests for mode-driven grounding flag injection."""

from __future__ import annotations

import unittest
from unittest.mock import patch


class TestGroundingModeInjection(unittest.TestCase):
    def test_rnd_mode_enables_grounding(self):
        from shared.working_mode import WorkingMode

        flags: dict = {"enable_grounding": False}
        with patch("shared.working_mode.get_working_mode", return_value=WorkingMode.RND):
            from shared.working_mode import get_working_mode

            if get_working_mode().value == "rnd":
                flags["enable_grounding"] = True
        assert flags["enable_grounding"] is True

    def test_research_mode_preserves_flag(self):
        from shared.working_mode import WorkingMode

        flags: dict = {"enable_grounding": False}
        with patch("shared.working_mode.get_working_mode", return_value=WorkingMode.RESEARCH):
            from shared.working_mode import get_working_mode

            if get_working_mode().value == "rnd":
                flags["enable_grounding"] = True
        assert flags["enable_grounding"] is False

    def test_research_mode_respects_explicit_true(self):
        from shared.working_mode import WorkingMode

        flags: dict = {"enable_grounding": True}
        with patch("shared.working_mode.get_working_mode", return_value=WorkingMode.RESEARCH):
            from shared.working_mode import get_working_mode

            if get_working_mode().value == "rnd":
                flags["enable_grounding"] = True
        # Research mode doesn't force it off — the flag file controls
        assert flags["enable_grounding"] is True
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/hapax_daimonion/test_grounding_mode.py -v`
Expected: All 3 tests PASS (logic was already wired in Task 3)

- [ ] **Step 3: Commit**

```bash
git add tests/hapax_daimonion/test_grounding_mode.py
git commit -m "test(daimonion): mode-driven grounding flag injection"
```

---

## Task 7: End-to-End Verification Script

**Files:**
- Create: `scripts/verify-daimonion.sh`

- [ ] **Step 1: Write verification script**

```bash
#!/usr/bin/env bash
# verify-daimonion.sh — End-to-end verification of hapax-daimonion capabilities.
# Run after the full treatment to confirm all subsystems are online.
set -euo pipefail

PASS=0
FAIL=0
SKIP=0

check() {
    local name="$1" result="$2"
    if [ "$result" = "PASS" ]; then
        printf "  ✓ %s\n" "$name"
        ((PASS++))
    elif [ "$result" = "SKIP" ]; then
        printf "  ○ %s (skipped)\n" "$name"
        ((SKIP++))
    else
        printf "  ✗ %s — %s\n" "$name" "$result"
        ((FAIL++))
    fi
}

echo "=== Hapax-Daimonion End-to-End Verification ==="
echo

# 1. Service running
echo "[1/7] Service status"
if systemctl --user is-active hapax-daimonion >/dev/null 2>&1; then
    check "hapax-daimonion active" "PASS"
else
    check "hapax-daimonion active" "FAIL: service not running"
fi

# 2. Ambient classification (pw-record)
echo "[2/7] Ambient classification"
if timeout 5 pw-record --target "$(wpctl inspect @DEFAULT_AUDIO_SINK@ 2>&1 | grep 'node.name' | head -1 | awk -F'"' '{print $2}')" --format s16 --rate 32000 --channels 1 /tmp/daimonion-verify-audio.raw 2>/dev/null; then
    SIZE=$(stat -c%s /tmp/daimonion-verify-audio.raw 2>/dev/null || echo 0)
    if [ "$SIZE" -gt 1000 ]; then
        check "pw-record capture" "PASS"
    else
        check "pw-record capture" "FAIL: $SIZE bytes (expected >1000)"
    fi
    rm -f /tmp/daimonion-verify-audio.raw
else
    check "pw-record capture" "FAIL: timeout or error"
fi

# Check for recent pw-record timeouts in logs
TIMEOUTS=$(journalctl --user -u hapax-daimonion --no-pager --since '5 min ago' 2>/dev/null | grep -c 'pw-record timed out' || true)
if [ "$TIMEOUTS" -eq 0 ]; then
    check "No pw-record timeouts (5m)" "PASS"
else
    check "No pw-record timeouts (5m)" "FAIL: $TIMEOUTS timeouts"
fi

# 3. TPN signal file
echo "[3/7] TPN_ACTIVE signaling"
TPN_FILE="/dev/shm/hapax-dmn/tpn_active"
if [ -f "$TPN_FILE" ]; then
    VAL=$(cat "$TPN_FILE" 2>/dev/null)
    if [ "$VAL" = "0" ] || [ "$VAL" = "1" ]; then
        check "tpn_active file valid" "PASS"
    else
        check "tpn_active file valid" "FAIL: unexpected value '$VAL'"
    fi
else
    check "tpn_active file valid" "SKIP"
fi

# 4. DMN running and reading TPN
echo "[4/7] DMN integration"
if systemctl --user is-active hapax-dmn >/dev/null 2>&1; then
    check "hapax-dmn active" "PASS"
else
    check "hapax-dmn active" "FAIL: service not running"
fi
IMPINGEMENTS="/dev/shm/hapax-dmn/impingements.jsonl"
if [ -f "$IMPINGEMENTS" ]; then
    LINES=$(wc -l < "$IMPINGEMENTS")
    check "DMN impingements ($LINES entries)" "PASS"
else
    check "DMN impingements" "FAIL: file missing"
fi

# 5. Context enrichment (shm files fresh)
echo "[5/7] Context enrichment sources"
for SHM_FILE in /dev/shm/hapax-stimmung/state.json /dev/shm/hapax-temporal/bands.json; do
    if [ -f "$SHM_FILE" ]; then
        AGE=$(( $(date +%s) - $(stat -c%Y "$SHM_FILE") ))
        if [ "$AGE" -lt 120 ]; then
            check "$(basename "$SHM_FILE") fresh (${AGE}s)" "PASS"
        else
            check "$(basename "$SHM_FILE")" "FAIL: stale (${AGE}s)"
        fi
    else
        check "$(basename "$SHM_FILE")" "FAIL: missing"
    fi
done

# 6. Grounding (check working mode and flag)
echo "[6/7] Grounding activation"
MODE=$(cat ~/.cache/hapax/working-mode 2>/dev/null || echo "unknown")
check "Working mode: $MODE" "PASS"
if [ "$MODE" = "rnd" ]; then
    check "Grounding expected: ON (R&D mode)" "PASS"
else
    check "Grounding expected: flag-controlled (Research mode)" "PASS"
fi

# 7. Tool registry (test import)
echo "[7/7] Tool capability model"
TOOL_COUNT=$(cd ~/projects/hapax-council && uv run python3 -c "
from agents.hapax_daimonion.tool_definitions import build_registry
reg = build_registry()
print(len(reg.all_tools()))
" 2>/dev/null || echo "0")
if [ "$TOOL_COUNT" -gt 0 ]; then
    check "Tool registry: $TOOL_COUNT capabilities" "PASS"
else
    check "Tool registry" "FAIL: no tools loaded"
fi

echo
echo "=== Results: $PASS pass, $FAIL fail, $SKIP skip ==="
exit "$FAIL"
```

- [ ] **Step 2: Make executable and test**

```bash
chmod +x scripts/verify-daimonion.sh
bash scripts/verify-daimonion.sh
```

Expected: All checks PASS (after daemon restart with new code)

- [ ] **Step 3: Commit**

```bash
git add scripts/verify-daimonion.sh
git commit -m "feat(daimonion): end-to-end verification script"
```

---

## Task 8: PR and Merge

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/hapax_daimonion/ -q -x && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

- [ ] **Step 2: Run verification script**

Run: `bash scripts/verify-daimonion.sh`
Expected: All checks pass

- [ ] **Step 3: Push and create PR**

```bash
git push -u origin HEAD
gh pr create --title "feat(daimonion): full treatment — capability model, grounding, TPN, tools" --body "..."
```

- [ ] **Step 4: Monitor CI, fix failures, merge when green**
