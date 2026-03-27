# Session Conductor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic Python sidecar that runs alongside each Claude Code session, receives every hook event via Unix domain socket, and autonomously enforces workspace topology, research convergence, session coordination, relay sync, epic pipelines, and smoke test standards.

**Architecture:** A single `session_conductor` agent module with a UDS server and 6 rule modules. Four hook shim scripts (SessionStart, Stop, PreToolUse, PostToolUse) pipe events to the conductor. State lives in `/dev/shm/` (volatile per-session) and `~/.cache/hapax/` (persistent cross-session). No LLM calls — all logic is deterministic.

**Tech Stack:** Python 3.12, asyncio (UDS server), dataclasses, PyYAML, `socat` (hook shims), `jq` (JSON parsing in bash), inotify_simple (file watching), systemd-run (process scoping).

**Spec:** `docs/superpowers/specs/2026-03-27-session-conductor-design.md`

---

## File Structure

```
agents/session_conductor/
    __init__.py              # Package marker
    __main__.py              # CLI entry: start/stop/status
    state.py                 # SessionState, TopicState, EpicPhase, ChildSession dataclasses
    protocol.py              # UDS server + event routing
    topology.py              # Workspace topology config loader
    rules/
        __init__.py          # RuleBase ABC + rule registry
        focus.py             # Rule: workspace topology enforcement
        convergence.py       # Rule: research convergence + finding persistence
        epic.py              # Rule: epic pipeline phase tracking
        relay.py             # Rule: automatic relay status sync
        smoke.py             # Rule: smoke test profile
        spawn.py             # Rule: session spawning & reunion

hooks/scripts/
    conductor-start.sh       # SessionStart: launch conductor sidecar
    conductor-stop.sh        # Stop: shutdown conductor
    conductor-pre.sh         # PreToolUse: pipe to conductor UDS
    conductor-post.sh        # PostToolUse: pipe to conductor UDS

agents/manifests/
    session_conductor.yaml   # Agent manifest

~/.config/hapax/
    workspace-topology.yaml  # Monitor/workspace config (created once)

tests/session_conductor/
    __init__.py
    test_state.py            # State serialization, topic matching
    test_topology.py         # Topology config loading
    test_focus.py            # Focus rule logic
    test_convergence.py      # Convergence detection, finding persistence
    test_epic.py             # Epic phase transitions
    test_relay.py            # Relay status generation
    test_smoke.py            # Smoke test profile activation
    test_spawn.py            # Spawn manifest lifecycle
    test_protocol.py         # UDS server event routing
```

---

## Task 1: State Model & Serialization

**Files:**
- Create: `agents/session_conductor/__init__.py`
- Create: `agents/session_conductor/state.py`
- Test: `tests/session_conductor/__init__.py`
- Test: `tests/session_conductor/test_state.py`

- [ ] **Step 1: Write failing tests for state model**

```python
# tests/session_conductor/__init__.py
# (empty)
```

```python
# tests/session_conductor/test_state.py
"""Tests for session conductor state model."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from agents.session_conductor.state import (
    ChildSession,
    EpicPhase,
    SessionState,
    TopicState,
)


def test_session_state_creation():
    state = SessionState(
        session_id="abc-123",
        pid=12345,
        started_at=datetime(2026, 3, 27, 12, 0, 0),
    )
    assert state.session_id == "abc-123"
    assert state.pid == 12345
    assert state.parent_session is None
    assert state.children == []
    assert state.active_topics == {}
    assert state.in_flight_files == set()
    assert state.epic_phase is None


def test_topic_state_is_converging_true():
    topic = TopicState(
        slug="compositor-effects",
        rounds=3,
        findings_per_round=[12, 3, 1],
        first_seen=datetime(2026, 3, 27, 12, 0, 0),
        prior_file=Path("/tmp/test.md"),
    )
    assert topic.is_converging() is True


def test_topic_state_is_converging_false_too_few_rounds():
    topic = TopicState(
        slug="compositor-effects",
        rounds=1,
        findings_per_round=[12],
        first_seen=datetime(2026, 3, 27, 12, 0, 0),
        prior_file=Path("/tmp/test.md"),
    )
    assert topic.is_converging() is False


def test_topic_state_is_converging_false_not_decreasing():
    topic = TopicState(
        slug="compositor-effects",
        rounds=3,
        findings_per_round=[5, 8, 7],
        first_seen=datetime(2026, 3, 27, 12, 0, 0),
        prior_file=Path("/tmp/test.md"),
    )
    assert topic.is_converging() is False


def test_topic_state_is_capped():
    topic = TopicState(
        slug="test",
        rounds=5,
        findings_per_round=[10, 8, 6, 4, 2],
        first_seen=datetime(2026, 3, 27, 12, 0, 0),
        prior_file=Path("/tmp/test.md"),
    )
    assert topic.is_capped() is True


def test_topic_state_not_capped():
    topic = TopicState(
        slug="test",
        rounds=3,
        findings_per_round=[10, 8, 6],
        first_seen=datetime(2026, 3, 27, 12, 0, 0),
        prior_file=Path("/tmp/test.md"),
    )
    assert topic.is_capped() is False


def test_epic_phase_ordering():
    assert EpicPhase.RESEARCH.value == "research"
    assert EpicPhase.IMPLEMENTATION.value == "implementation"
    phases = list(EpicPhase)
    assert phases[0] == EpicPhase.RESEARCH
    assert phases[-1] == EpicPhase.IMPLEMENTATION


def test_session_state_serialize_roundtrip(tmp_path: Path):
    state = SessionState(
        session_id="abc-123",
        pid=12345,
        started_at=datetime(2026, 3, 27, 12, 0, 0),
    )
    state.active_topics["test"] = TopicState(
        slug="test",
        rounds=2,
        findings_per_round=[5, 3],
        first_seen=datetime(2026, 3, 27, 12, 0, 0),
        prior_file=tmp_path / "test.md",
    )
    state.in_flight_files.add("foo.py")

    path = tmp_path / "state.json"
    state.save(path)
    loaded = SessionState.load(path)

    assert loaded.session_id == "abc-123"
    assert loaded.pid == 12345
    assert "test" in loaded.active_topics
    assert loaded.active_topics["test"].rounds == 2
    assert "foo.py" in loaded.in_flight_files


def test_topic_slug_matching():
    topic = TopicState(
        slug="compositor-effects",
        rounds=1,
        findings_per_round=[5],
        first_seen=datetime(2026, 3, 27, 12, 0, 0),
        prior_file=Path("/tmp/test.md"),
    )
    assert topic.matches_prompt("research all compositor effects touch points") is True
    assert topic.matches_prompt("fix the login screen") is False


def test_child_session_creation():
    child = ChildSession(
        session_id="child-1",
        topic="logos-api-bug",
        spawn_manifest=Path("/tmp/spawn.yaml"),
        status="pending",
    )
    assert child.session_id == "child-1"
    assert child.status == "pending"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/session_conductor/test_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.session_conductor'`

- [ ] **Step 3: Implement state model**

```python
# agents/session_conductor/__init__.py
"""Session Conductor — deterministic sidecar for Claude Code session automation."""
```

```python
# agents/session_conductor/state.py
"""Session state model and serialization."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class EpicPhase(Enum):
    RESEARCH = "research"
    DESIGN = "design"
    DESIGN_GAPS = "design_gaps"
    PLANNING = "planning"
    PLANNING_GAPS = "planning_gaps"
    IMPLEMENTATION = "implementation"


EPIC_PHASE_ORDER = list(EpicPhase)

MAX_RESEARCH_ROUNDS = 5
MAX_GAP_ROUNDS = 2
CONVERGENCE_THRESHOLD = 0.30


@dataclass
class TopicState:
    slug: str
    rounds: int
    findings_per_round: list[int]
    first_seen: datetime
    prior_file: Path
    blocked_at_round: int | None = None

    def is_converging(self) -> bool:
        """True if last 2 rounds each found ≤30% of first round's findings."""
        if len(self.findings_per_round) < 3:
            return False
        first = self.findings_per_round[0]
        if first == 0:
            return True
        last_two = self.findings_per_round[-2:]
        return all(r / first <= CONVERGENCE_THRESHOLD for r in last_two)

    def is_capped(self) -> bool:
        return self.rounds >= MAX_RESEARCH_ROUNDS

    def matches_prompt(self, prompt: str) -> bool:
        """Check if a prompt is about this topic via keyword overlap."""
        slug_words = set(self.slug.split("-"))
        prompt_words = set(re.sub(r"[^a-z0-9\s]", "", prompt.lower()).split())
        if not slug_words:
            return False
        overlap = len(slug_words & prompt_words) / len(slug_words)
        return overlap >= 0.6


@dataclass
class ChildSession:
    session_id: str
    topic: str
    spawn_manifest: Path
    status: str  # pending, claimed, completed, orphaned


@dataclass
class SessionState:
    session_id: str
    pid: int
    started_at: datetime
    parent_session: str | None = None
    children: list[ChildSession] = field(default_factory=list)
    active_topics: dict[str, TopicState] = field(default_factory=dict)
    in_flight_files: set[str] = field(default_factory=set)
    epic_phase: EpicPhase | None = None
    last_relay_sync: datetime | None = None
    workstream_summary: str = ""
    smoke_test_active: bool = False

    def save(self, path: Path) -> None:
        """Serialize state to JSON file."""
        data = {
            "session_id": self.session_id,
            "pid": self.pid,
            "started_at": self.started_at.isoformat(),
            "parent_session": self.parent_session,
            "children": [
                {
                    "session_id": c.session_id,
                    "topic": c.topic,
                    "spawn_manifest": str(c.spawn_manifest),
                    "status": c.status,
                }
                for c in self.children
            ],
            "active_topics": {
                slug: {
                    "slug": t.slug,
                    "rounds": t.rounds,
                    "findings_per_round": t.findings_per_round,
                    "first_seen": t.first_seen.isoformat(),
                    "prior_file": str(t.prior_file),
                    "blocked_at_round": t.blocked_at_round,
                }
                for slug, t in self.active_topics.items()
            },
            "in_flight_files": sorted(self.in_flight_files),
            "epic_phase": self.epic_phase.value if self.epic_phase else None,
            "last_relay_sync": self.last_relay_sync.isoformat() if self.last_relay_sync else None,
            "workstream_summary": self.workstream_summary,
            "smoke_test_active": self.smoke_test_active,
        }
        path.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: Path) -> SessionState:
        """Deserialize state from JSON file."""
        data = json.loads(path.read_text())
        state = cls(
            session_id=data["session_id"],
            pid=data["pid"],
            started_at=datetime.fromisoformat(data["started_at"]),
            parent_session=data.get("parent_session"),
            workstream_summary=data.get("workstream_summary", ""),
            smoke_test_active=data.get("smoke_test_active", False),
        )
        state.children = [
            ChildSession(
                session_id=c["session_id"],
                topic=c["topic"],
                spawn_manifest=Path(c["spawn_manifest"]),
                status=c["status"],
            )
            for c in data.get("children", [])
        ]
        state.active_topics = {
            slug: TopicState(
                slug=t["slug"],
                rounds=t["rounds"],
                findings_per_round=t["findings_per_round"],
                first_seen=datetime.fromisoformat(t["first_seen"]),
                prior_file=Path(t["prior_file"]),
                blocked_at_round=t.get("blocked_at_round"),
            )
            for slug, t in data.get("active_topics", {}).items()
        }
        state.in_flight_files = set(data.get("in_flight_files", []))
        phase = data.get("epic_phase")
        state.epic_phase = EpicPhase(phase) if phase else None
        sync = data.get("last_relay_sync")
        state.last_relay_sync = datetime.fromisoformat(sync) if sync else None
        return state
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/session_conductor/test_state.py -v`
Expected: All 11 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/hapax/projects/hapax-council
git add agents/session_conductor/__init__.py agents/session_conductor/state.py tests/session_conductor/__init__.py tests/session_conductor/test_state.py
git commit -m "feat(conductor): add session state model and serialization"
```

---

## Task 2: Workspace Topology Config Loader

**Files:**
- Create: `agents/session_conductor/topology.py`
- Create: `~/.config/hapax/workspace-topology.yaml`
- Test: `tests/session_conductor/test_topology.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/session_conductor/test_topology.py
"""Tests for workspace topology config loader."""

from __future__ import annotations

from pathlib import Path

from agents.session_conductor.topology import TopologyConfig, load_topology


def test_load_topology_from_file(tmp_path: Path):
    config_file = tmp_path / "workspace-topology.yaml"
    config_file.write_text("""
monitors:
  primary:
    name: "Dell S3422DWG"
    position: left
    resolution: 3440x1440
    purpose: work
  secondary:
    name: "Dell S2721DGF"
    position: right
    resolution: 2560x1440
    purpose: logos

workspaces:
  1: { monitor: primary, purpose: terminals }
  2: { monitor: primary, purpose: browser }
  3: { monitor: secondary, purpose: logos }
  10: { monitor: secondary, purpose: playwright-testing, ephemeral: true }

playwright:
  testing_workspace: 10
  screenshot_max_bytes: 500000
  never_switch_operator_focus: true

smoke_test:
  workspace: 10
  fullscreen: true
  launch_method: fuzzel
  screenshot_interval_ms: 2000
""")
    config = load_topology(config_file)
    assert config.playwright.testing_workspace == 10
    assert config.playwright.screenshot_max_bytes == 500000
    assert config.playwright.never_switch_operator_focus is True
    assert config.smoke_test.workspace == 10
    assert config.smoke_test.fullscreen is True


def test_load_topology_missing_file(tmp_path: Path):
    config = load_topology(tmp_path / "nonexistent.yaml")
    assert config.playwright.testing_workspace == 10
    assert config.playwright.never_switch_operator_focus is True


def test_topology_get_workspace_monitor(tmp_path: Path):
    config_file = tmp_path / "workspace-topology.yaml"
    config_file.write_text("""
monitors:
  primary:
    name: "Test Monitor"
    position: left
    resolution: 1920x1080
    purpose: work
workspaces:
  1: { monitor: primary, purpose: terminals }
playwright:
  testing_workspace: 10
  screenshot_max_bytes: 500000
  never_switch_operator_focus: true
smoke_test:
  workspace: 10
  fullscreen: true
  launch_method: fuzzel
  screenshot_interval_ms: 2000
""")
    config = load_topology(config_file)
    assert config.get_workspace_monitor(1) == "primary"
    assert config.get_workspace_monitor(99) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/session_conductor/test_topology.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement topology loader**

```python
# agents/session_conductor/topology.py
"""Workspace topology configuration loader."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

DEFAULT_TOPOLOGY_PATH = Path.home() / ".config" / "hapax" / "workspace-topology.yaml"


@dataclass
class MonitorConfig:
    name: str = ""
    position: str = "left"
    resolution: str = "1920x1080"
    purpose: str = "work"


@dataclass
class WorkspaceConfig:
    monitor: str = "primary"
    purpose: str = ""
    ephemeral: bool = False


@dataclass
class PlaywrightConfig:
    testing_workspace: int = 10
    screenshot_max_bytes: int = 500_000
    never_switch_operator_focus: bool = True


@dataclass
class SmokeTestConfig:
    workspace: int = 10
    fullscreen: bool = True
    launch_method: str = "fuzzel"
    screenshot_interval_ms: int = 2000


@dataclass
class TopologyConfig:
    monitors: dict[str, MonitorConfig] = field(default_factory=dict)
    workspaces: dict[int, WorkspaceConfig] = field(default_factory=dict)
    playwright: PlaywrightConfig = field(default_factory=PlaywrightConfig)
    smoke_test: SmokeTestConfig = field(default_factory=SmokeTestConfig)

    def get_workspace_monitor(self, workspace: int) -> str | None:
        ws = self.workspaces.get(workspace)
        return ws.monitor if ws else None


def load_topology(path: Path | None = None) -> TopologyConfig:
    """Load topology config from YAML, falling back to defaults."""
    path = path or DEFAULT_TOPOLOGY_PATH
    if not path.exists():
        log.info("No topology config at %s, using defaults", path)
        return TopologyConfig()

    raw = yaml.safe_load(path.read_text()) or {}

    monitors = {
        name: MonitorConfig(**m) for name, m in raw.get("monitors", {}).items()
    }
    workspaces = {
        int(num): WorkspaceConfig(**ws) for num, ws in raw.get("workspaces", {}).items()
    }

    pw_raw = raw.get("playwright", {})
    playwright = PlaywrightConfig(**pw_raw)

    st_raw = raw.get("smoke_test", {})
    smoke_test = SmokeTestConfig(**st_raw)

    return TopologyConfig(
        monitors=monitors,
        workspaces=workspaces,
        playwright=playwright,
        smoke_test=smoke_test,
    )
```

- [ ] **Step 4: Create the actual topology config file**

```yaml
# ~/.config/hapax/workspace-topology.yaml
monitors:
  primary:
    name: "Dell S3422DWG"
    position: left
    resolution: 3440x1440
    purpose: work
  secondary:
    name: "Dell S2721DGF"
    position: right
    resolution: 2560x1440
    purpose: logos

workspaces:
  1: { monitor: primary, purpose: terminals }
  2: { monitor: primary, purpose: browser }
  3: { monitor: secondary, purpose: logos }
  10: { monitor: secondary, purpose: playwright-testing, ephemeral: true }

playwright:
  testing_workspace: 10
  screenshot_max_bytes: 500000
  never_switch_operator_focus: true

smoke_test:
  workspace: 10
  fullscreen: true
  launch_method: fuzzel
  screenshot_interval_ms: 2000
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/session_conductor/test_topology.py -v`
Expected: All 3 tests PASS

- [ ] **Step 6: Commit**

```bash
cd /home/hapax/projects/hapax-council
git add agents/session_conductor/topology.py tests/session_conductor/test_topology.py
git commit -m "feat(conductor): add workspace topology config loader"
```

---

## Task 3: Rule Base Class & Registry

**Files:**
- Create: `agents/session_conductor/rules/__init__.py`
- Test: `tests/session_conductor/test_rules_base.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/session_conductor/test_rules_base.py
"""Tests for rule base class and registry."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agents.session_conductor.rules import HookEvent, HookResponse, RuleBase, RuleRegistry
from agents.session_conductor.state import SessionState
from agents.session_conductor.topology import TopologyConfig


class DummyRule(RuleBase):
    def on_pre_tool_use(self, event: HookEvent, state: SessionState) -> HookResponse | None:
        if event.tool_name == "blocked_tool":
            return HookResponse(action="block", message="Blocked by dummy rule")
        return None

    def on_post_tool_use(self, event: HookEvent, state: SessionState) -> HookResponse | None:
        return None


def test_hook_event_from_dict():
    event = HookEvent.from_dict({
        "event": "pre_tool_use",
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
        "session_id": "abc-123",
    })
    assert event.event_type == "pre_tool_use"
    assert event.tool_name == "Bash"
    assert event.tool_input == {"command": "ls"}


def test_hook_response_to_dict():
    resp = HookResponse(action="block", message="No")
    d = resp.to_dict()
    assert d["action"] == "block"
    assert d["message"] == "No"


def test_hook_response_allow():
    resp = HookResponse.allow()
    assert resp.action == "allow"
    assert resp.message == ""


def test_rule_registry_dispatches():
    registry = RuleRegistry()
    state = SessionState(
        session_id="test", pid=1, started_at=datetime(2026, 3, 27)
    )
    topology = TopologyConfig()
    rule = DummyRule(topology=topology)
    registry.register(rule)

    event = HookEvent(
        event_type="pre_tool_use",
        tool_name="blocked_tool",
        tool_input={},
        session_id="test",
    )
    response = registry.process_pre_tool_use(event, state)
    assert response is not None
    assert response.action == "block"


def test_rule_registry_allows_when_no_rule_blocks():
    registry = RuleRegistry()
    state = SessionState(
        session_id="test", pid=1, started_at=datetime(2026, 3, 27)
    )
    topology = TopologyConfig()
    rule = DummyRule(topology=topology)
    registry.register(rule)

    event = HookEvent(
        event_type="pre_tool_use",
        tool_name="safe_tool",
        tool_input={},
        session_id="test",
    )
    response = registry.process_pre_tool_use(event, state)
    assert response is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/session_conductor/test_rules_base.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement rule base and registry**

```python
# agents/session_conductor/rules/__init__.py
"""Rule base class and registry for session conductor."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from agents.session_conductor.state import SessionState
from agents.session_conductor.topology import TopologyConfig

log = logging.getLogger(__name__)


@dataclass
class HookEvent:
    event_type: str  # "pre_tool_use" or "post_tool_use"
    tool_name: str
    tool_input: dict
    session_id: str
    user_message: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> HookEvent:
        return cls(
            event_type=data.get("event", ""),
            tool_name=data.get("tool_name", ""),
            tool_input=data.get("tool_input", {}),
            session_id=data.get("session_id", ""),
            user_message=data.get("user_message", ""),
        )


@dataclass
class HookResponse:
    action: str  # "allow", "block", "rewrite"
    message: str = ""
    rewrite: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d: dict = {"action": self.action, "message": self.message}
        if self.rewrite:
            d["rewrite"] = self.rewrite
        return d

    @classmethod
    def allow(cls, message: str = "") -> HookResponse:
        return cls(action="allow", message=message)

    @classmethod
    def block(cls, message: str) -> HookResponse:
        return cls(action="block", message=message)


class RuleBase(ABC):
    def __init__(self, topology: TopologyConfig) -> None:
        self.topology = topology

    @abstractmethod
    def on_pre_tool_use(self, event: HookEvent, state: SessionState) -> HookResponse | None:
        """Return a response to block/rewrite, or None to allow."""

    @abstractmethod
    def on_post_tool_use(self, event: HookEvent, state: SessionState) -> HookResponse | None:
        """Return an advisory response, or None for no action."""


class RuleRegistry:
    def __init__(self) -> None:
        self._rules: list[RuleBase] = []

    def register(self, rule: RuleBase) -> None:
        self._rules.append(rule)

    def process_pre_tool_use(self, event: HookEvent, state: SessionState) -> HookResponse | None:
        """Run all rules. First block/rewrite wins."""
        for rule in self._rules:
            try:
                response = rule.on_pre_tool_use(event, state)
                if response is not None:
                    return response
            except Exception:
                log.exception("Rule %s failed on pre_tool_use", type(rule).__name__)
        return None

    def process_post_tool_use(
        self, event: HookEvent, state: SessionState
    ) -> list[HookResponse]:
        """Run all rules. Collect all advisory responses."""
        responses: list[HookResponse] = []
        for rule in self._rules:
            try:
                response = rule.on_post_tool_use(event, state)
                if response is not None:
                    responses.append(response)
            except Exception:
                log.exception("Rule %s failed on post_tool_use", type(rule).__name__)
        return responses
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/session_conductor/test_rules_base.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/hapax/projects/hapax-council
git add agents/session_conductor/rules/__init__.py tests/session_conductor/test_rules_base.py
git commit -m "feat(conductor): add rule base class and registry"
```

---

## Task 4: Focus Enforcement Rule

**Files:**
- Create: `agents/session_conductor/rules/focus.py`
- Test: `tests/session_conductor/test_focus.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/session_conductor/test_focus.py
"""Tests for focus enforcement rule."""

from __future__ import annotations

from datetime import datetime

from agents.session_conductor.rules import HookEvent
from agents.session_conductor.rules.focus import FocusRule
from agents.session_conductor.state import SessionState
from agents.session_conductor.topology import PlaywrightConfig, TopologyConfig

PLAYWRIGHT_TOOLS = [
    "browser_navigate",
    "browser_click",
    "browser_snapshot",
    "browser_take_screenshot",
    "browser_fill_form",
    "browser_hover",
    "browser_press_key",
    "browser_select_option",
    "browser_type",
    "browser_drag",
]


def _make_state() -> SessionState:
    return SessionState(session_id="test", pid=1, started_at=datetime(2026, 3, 27))


def _make_topology() -> TopologyConfig:
    return TopologyConfig(
        playwright=PlaywrightConfig(
            testing_workspace=10,
            screenshot_max_bytes=500_000,
            never_switch_operator_focus=True,
        )
    )


def test_focus_rule_rewrites_playwright_tools():
    rule = FocusRule(topology=_make_topology())
    state = _make_state()
    for tool in PLAYWRIGHT_TOOLS:
        event = HookEvent(
            event_type="pre_tool_use",
            tool_name=tool,
            tool_input={},
            session_id="test",
        )
        response = rule.on_pre_tool_use(event, state)
        assert response is not None, f"Expected rewrite for {tool}"
        assert response.action == "rewrite"
        assert response.rewrite["workspace"] == 10


def test_focus_rule_ignores_non_playwright():
    rule = FocusRule(topology=_make_topology())
    state = _make_state()
    event = HookEvent(
        event_type="pre_tool_use",
        tool_name="Bash",
        tool_input={"command": "ls"},
        session_id="test",
    )
    response = rule.on_pre_tool_use(event, state)
    assert response is None


def test_focus_rule_blocks_workspace_switch_commands():
    rule = FocusRule(topology=_make_topology())
    state = _make_state()
    event = HookEvent(
        event_type="pre_tool_use",
        tool_name="Bash",
        tool_input={"command": "hyprctl dispatch workspace 3"},
        session_id="test",
    )
    response = rule.on_pre_tool_use(event, state)
    assert response is not None
    assert response.action == "rewrite"
    assert "movetoworkspacesilent" in response.message or "silent" in response.message.lower()


def test_focus_rule_allows_silent_workspace_commands():
    rule = FocusRule(topology=_make_topology())
    state = _make_state()
    event = HookEvent(
        event_type="pre_tool_use",
        tool_name="Bash",
        tool_input={"command": "hyprctl dispatch movetoworkspacesilent 10"},
        session_id="test",
    )
    response = rule.on_pre_tool_use(event, state)
    assert response is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/session_conductor/test_focus.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement focus rule**

```python
# agents/session_conductor/rules/focus.py
"""Focus enforcement rule — prevents Playwright from stealing operator focus."""

from __future__ import annotations

import logging
import re

from agents.session_conductor.rules import HookEvent, HookResponse, RuleBase
from agents.session_conductor.state import SessionState

log = logging.getLogger(__name__)

PLAYWRIGHT_TOOL_PREFIX = "browser_"

# Matches hyprctl dispatch workspace N (non-silent variant)
WORKSPACE_SWITCH_RE = re.compile(
    r"hyprctl\s+dispatch\s+(?:workspace|movetoworkspace)\s+(\d+)"
)
SILENT_SWITCH_RE = re.compile(r"hyprctl\s+dispatch\s+movetoworkspacesilent\s+\d+")


class FocusRule(RuleBase):
    def on_pre_tool_use(self, event: HookEvent, state: SessionState) -> HookResponse | None:
        if event.tool_name.startswith(PLAYWRIGHT_TOOL_PREFIX):
            return self._handle_playwright(event)

        if event.tool_name == "Bash":
            return self._handle_bash(event)

        return None

    def on_post_tool_use(self, event: HookEvent, state: SessionState) -> HookResponse | None:
        return None

    def _handle_playwright(self, event: HookEvent) -> HookResponse:
        ws = self.topology.playwright.testing_workspace
        return HookResponse(
            action="rewrite",
            message=f"Playwright routed to workspace {ws} (focus protected).",
            rewrite={"workspace": ws},
        )

    def _handle_bash(self, event: HookEvent) -> HookResponse | None:
        cmd = event.tool_input.get("command", "")

        # Allow already-silent commands
        if SILENT_SWITCH_RE.search(cmd):
            return None

        # Rewrite non-silent workspace switches
        match = WORKSPACE_SWITCH_RE.search(cmd)
        if match:
            target_ws = match.group(1)
            return HookResponse(
                action="rewrite",
                message=(
                    f"Rewrote workspace switch to silent variant. "
                    f"Use movetoworkspacesilent {target_ws} to avoid stealing operator focus."
                ),
                rewrite={"command": WORKSPACE_SWITCH_RE.sub(
                    f"hyprctl dispatch movetoworkspacesilent {target_ws}", cmd
                )},
            )

        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/session_conductor/test_focus.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/hapax/projects/hapax-council
git add agents/session_conductor/rules/focus.py tests/session_conductor/test_focus.py
git commit -m "feat(conductor): add focus enforcement rule"
```

---

## Task 5: Research Convergence & Finding Persistence Rule

**Files:**
- Create: `agents/session_conductor/rules/convergence.py`
- Test: `tests/session_conductor/test_convergence.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/session_conductor/test_convergence.py
"""Tests for research convergence and finding persistence rule."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agents.session_conductor.rules import HookEvent
from agents.session_conductor.rules.convergence import ConvergenceRule, count_findings, extract_topic_slug
from agents.session_conductor.state import SessionState, TopicState
from agents.session_conductor.topology import TopologyConfig


def _make_state() -> SessionState:
    return SessionState(session_id="test", pid=1, started_at=datetime(2026, 3, 27))


def _make_rule(tmp_path: Path) -> ConvergenceRule:
    return ConvergenceRule(
        topology=TopologyConfig(),
        context_dir=tmp_path / "relay" / "context",
    )


def test_extract_topic_slug():
    assert extract_topic_slug("research all compositor effects touch points") == "compositor-effects"
    assert extract_topic_slug("research the CI/CD coordination pipeline") == "ci-cd-coordination"


def test_count_findings():
    text = """
## Findings
- First finding
- Second finding
- Third finding

### Sub-section
1. Numbered finding
2. Another numbered finding
"""
    assert count_findings(text) == 5


def test_count_findings_empty():
    assert count_findings("No bullet points here.") == 0


def test_convergence_rule_tracks_new_topic(tmp_path: Path):
    rule = _make_rule(tmp_path)
    state = _make_state()

    event = HookEvent(
        event_type="post_tool_use",
        tool_name="Agent",
        tool_input={"prompt": "research all compositor effects"},
        session_id="test",
        user_message="research compositor effects",
    )
    # Simulate agent output with 10 findings
    event.tool_input["result"] = "\n".join(f"- Finding {i}" for i in range(10))

    rule.on_post_tool_use(event, state)
    assert "compositor-effects" in state.active_topics
    assert state.active_topics["compositor-effects"].rounds == 1
    assert state.active_topics["compositor-effects"].findings_per_round == [10]


def test_convergence_rule_blocks_when_converging(tmp_path: Path):
    rule = _make_rule(tmp_path)
    state = _make_state()

    # Pre-populate with converging topic
    state.active_topics["compositor-effects"] = TopicState(
        slug="compositor-effects",
        rounds=3,
        findings_per_round=[12, 3, 1],
        first_seen=datetime(2026, 3, 27),
        prior_file=tmp_path / "relay" / "context" / "compositor-effects.md",
    )

    event = HookEvent(
        event_type="pre_tool_use",
        tool_name="Agent",
        tool_input={"prompt": "research all compositor effects again"},
        session_id="test",
        user_message="research compositor effects",
    )
    response = rule.on_pre_tool_use(event, state)
    assert response is not None
    assert response.action == "block"
    assert "converging" in response.message.lower() or "CONVERGED" in response.message


def test_convergence_rule_blocks_at_hard_cap(tmp_path: Path):
    rule = _make_rule(tmp_path)
    state = _make_state()

    state.active_topics["test-topic"] = TopicState(
        slug="test-topic",
        rounds=5,
        findings_per_round=[10, 9, 8, 7, 6],
        first_seen=datetime(2026, 3, 27),
        prior_file=tmp_path / "relay" / "context" / "test-topic.md",
    )

    event = HookEvent(
        event_type="pre_tool_use",
        tool_name="Agent",
        tool_input={"prompt": "research test topic thoroughly"},
        session_id="test",
        user_message="research test topic",
    )
    response = rule.on_pre_tool_use(event, state)
    assert response is not None
    assert response.action == "block"
    assert "CAPPED" in response.message or "capped" in response.message.lower()


def test_convergence_rule_injects_prior_findings(tmp_path: Path):
    rule = _make_rule(tmp_path)
    state = _make_state()

    # Create prior findings file
    context_dir = tmp_path / "relay" / "context"
    context_dir.mkdir(parents=True)
    prior_file = context_dir / "compositor-effects.md"
    prior_file.write_text("## Prior Session\n- Important finding\n")

    event = HookEvent(
        event_type="pre_tool_use",
        tool_name="Agent",
        tool_input={"prompt": "research compositor effects"},
        session_id="test",
        user_message="research compositor effects",
    )

    response = rule.on_pre_tool_use(event, state)
    assert response is not None
    assert response.action == "rewrite"
    assert "PRIOR RESEARCH EXISTS" in response.message
    assert "Important finding" in response.message


def test_convergence_rule_persists_findings(tmp_path: Path):
    rule = _make_rule(tmp_path)
    state = _make_state()

    event = HookEvent(
        event_type="post_tool_use",
        tool_name="Agent",
        tool_input={
            "prompt": "research compositor effects",
            "result": "- Finding A\n- Finding B\n- Finding C",
        },
        session_id="test",
        user_message="research compositor effects",
    )

    rule.on_post_tool_use(event, state)

    context_dir = tmp_path / "relay" / "context"
    prior_file = context_dir / "compositor-effects.md"
    assert prior_file.exists()
    content = prior_file.read_text()
    assert "Finding A" in content
    assert "Finding B" in content


def test_convergence_rule_allows_non_agent_tools(tmp_path: Path):
    rule = _make_rule(tmp_path)
    state = _make_state()

    event = HookEvent(
        event_type="pre_tool_use",
        tool_name="Bash",
        tool_input={"command": "ls"},
        session_id="test",
    )
    response = rule.on_pre_tool_use(event, state)
    assert response is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/session_conductor/test_convergence.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement convergence rule**

```python
# agents/session_conductor/rules/convergence.py
"""Research convergence detection and finding persistence."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from agents.session_conductor.rules import HookEvent, HookResponse, RuleBase
from agents.session_conductor.state import SessionState, TopicState

log = logging.getLogger(__name__)

DEFAULT_CONTEXT_DIR = Path.home() / ".cache" / "hapax" / "relay" / "context"

# Words to strip when extracting topic slug
STOP_WORDS = {
    "research", "all", "any", "the", "every", "loose", "ends", "touch",
    "points", "thoroughly", "again", "deeply", "coherent", "granular",
    "independent", "agents", "each", "major", "single", "conceivable",
    "related", "work", "done", "look", "looks", "for", "more", "gaps",
    "and", "then", "with", "from", "into", "what", "how", "why",
    "figure", "out", "investigate", "analyze", "examine",
}


def extract_topic_slug(text: str) -> str:
    """Extract a topic slug from research-oriented text."""
    words = re.sub(r"[^a-z0-9\s]", "", text.lower()).split()
    topic_words = [w for w in words if w not in STOP_WORDS and len(w) > 2]
    # Take up to 3 most distinctive words
    slug = "-".join(topic_words[:3]) if topic_words else "unknown"
    return slug


def count_findings(text: str) -> int:
    """Count distinct findings in agent output (bullets + numbered items)."""
    bullet_re = re.compile(r"^\s*[-*]\s+\S", re.MULTILINE)
    numbered_re = re.compile(r"^\s*\d+[.)]\s+\S", re.MULTILINE)
    return len(bullet_re.findall(text)) + len(numbered_re.findall(text))


class ConvergenceRule(RuleBase):
    def __init__(self, topology, context_dir: Path | None = None) -> None:
        super().__init__(topology)
        self.context_dir = context_dir or DEFAULT_CONTEXT_DIR
        self.context_dir.mkdir(parents=True, exist_ok=True)

    def on_pre_tool_use(self, event: HookEvent, state: SessionState) -> HookResponse | None:
        if event.tool_name != "Agent":
            return None

        prompt = event.tool_input.get("prompt", "")
        if not self._is_research_dispatch(prompt, event.user_message):
            return None

        slug = self._match_existing_topic(prompt, state) or extract_topic_slug(prompt)

        # Check if topic is capped or converging
        topic = state.active_topics.get(slug)
        if topic:
            if topic.is_capped():
                return HookResponse.block(
                    f"RESEARCH CAPPED at round {topic.rounds} on \"{slug}\".\n"
                    f"{topic.rounds} rounds is sufficient. Proceed to design/implementation.\n"
                    f"Prior findings: {topic.prior_file}"
                )
            if topic.is_converging():
                findings_str = "→".join(str(f) for f in topic.findings_per_round)
                prior_content = self._load_prior_findings(slug)
                return HookResponse.block(
                    f"RESEARCH CONVERGED on \"{slug}\": rounds found {findings_str} new issues.\n"
                    f"Findings are stabilizing. Moving to next phase.\n\n"
                    f"{prior_content}"
                )

        # Check for prior findings to inject
        prior_content = self._load_prior_findings(slug)
        if prior_content:
            return HookResponse(
                action="rewrite",
                message=(
                    f"PRIOR RESEARCH EXISTS on this topic. "
                    f"Read and build on it — do not re-research from scratch.\n"
                    f"---\n{prior_content}\n---"
                ),
                rewrite={"prepend_prior": True},
            )

        return None

    def on_post_tool_use(self, event: HookEvent, state: SessionState) -> HookResponse | None:
        if event.tool_name != "Agent":
            return None

        prompt = event.tool_input.get("prompt", "")
        result = event.tool_input.get("result", "")
        if not self._is_research_dispatch(prompt, event.user_message):
            return None

        slug = self._match_existing_topic(prompt, state) or extract_topic_slug(prompt)
        findings = count_findings(result)

        # Update or create topic state
        if slug in state.active_topics:
            topic = state.active_topics[slug]
            topic.rounds += 1
            topic.findings_per_round.append(findings)
        else:
            prior_file = self.context_dir / f"{slug}.md"
            state.active_topics[slug] = TopicState(
                slug=slug,
                rounds=1,
                findings_per_round=[findings],
                first_seen=datetime.now(),
                prior_file=prior_file,
            )

        # Persist findings
        self._persist_findings(slug, state.session_id, result)

        topic = state.active_topics[slug]
        if topic.is_converging():
            findings_str = "→".join(str(f) for f in topic.findings_per_round)
            return HookResponse.allow(
                f"Research on \"{slug}\" is converging ({findings_str}). "
                f"Next dispatch on this topic will be blocked."
            )

        return None

    def _is_research_dispatch(self, prompt: str, user_message: str) -> bool:
        """Detect if this is a research-oriented agent dispatch."""
        combined = f"{prompt} {user_message}".lower()
        research_signals = [
            "research", "investigate", "analyze", "examine", "explore",
            "look for gaps", "loose ends", "touch points",
        ]
        return any(signal in combined for signal in research_signals)

    def _match_existing_topic(self, prompt: str, state: SessionState) -> str | None:
        """Check if prompt matches an existing topic."""
        for slug, topic in state.active_topics.items():
            if topic.matches_prompt(prompt):
                return slug
        return None

    def _load_prior_findings(self, slug: str) -> str:
        """Load prior findings from context file if it exists."""
        prior_file = self.context_dir / f"{slug}.md"
        if prior_file.exists():
            return prior_file.read_text().strip()
        return ""

    def _persist_findings(self, slug: str, session_id: str, result: str) -> None:
        """Append findings to context file."""
        prior_file = self.context_dir / f"{slug}.md"
        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M")
        topic = f"\n\n## {timestamp} — session {session_id[:8]}\n\n"
        # Trim to key findings (bullet points only)
        lines = result.split("\n")
        finding_lines = [
            l for l in lines
            if re.match(r"^\s*[-*]\s+\S", l) or re.match(r"^\s*\d+[.)]\s+\S", l)
        ]
        content = topic + "\n".join(finding_lines) if finding_lines else topic + result[:2000]

        with open(prior_file, "a") as f:
            f.write(content)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/session_conductor/test_convergence.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/hapax/projects/hapax-council
git add agents/session_conductor/rules/convergence.py tests/session_conductor/test_convergence.py
git commit -m "feat(conductor): add research convergence and finding persistence rule"
```

---

## Task 6: Epic Pipeline Rule

**Files:**
- Create: `agents/session_conductor/rules/epic.py`
- Test: `tests/session_conductor/test_epic.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/session_conductor/test_epic.py
"""Tests for epic pipeline phase tracking rule."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agents.session_conductor.rules import HookEvent
from agents.session_conductor.rules.epic import EpicRule, is_epic_trigger
from agents.session_conductor.state import EpicPhase, SessionState, TopicState
from agents.session_conductor.topology import TopologyConfig


def _make_state() -> SessionState:
    return SessionState(session_id="test", pid=1, started_at=datetime(2026, 3, 27))


def _make_rule() -> EpicRule:
    return EpicRule(topology=TopologyConfig())


def test_is_epic_trigger():
    assert is_epic_trigger("research any loose ends then formal design") is True
    assert is_epic_trigger("research all touch points") is True
    assert is_epic_trigger("fix the login bug") is False


def test_epic_activates_on_research_pattern():
    rule = _make_rule()
    state = _make_state()

    event = HookEvent(
        event_type="post_tool_use",
        tool_name="Agent",
        tool_input={"prompt": "research all touch points"},
        session_id="test",
        user_message="research any loose ends then formal design doc",
    )
    rule.on_post_tool_use(event, state)
    assert state.epic_phase == EpicPhase.RESEARCH


def test_epic_transitions_to_design_on_convergence():
    rule = _make_rule()
    state = _make_state()
    state.epic_phase = EpicPhase.RESEARCH

    # Simulate converging topic
    state.active_topics["test"] = TopicState(
        slug="test",
        rounds=3,
        findings_per_round=[12, 3, 1],
        first_seen=datetime(2026, 3, 27),
        prior_file=Path("/tmp/test.md"),
    )

    response = rule.check_phase_transition(state)
    assert response is not None
    assert state.epic_phase == EpicPhase.DESIGN
    assert "DESIGN" in response.message


def test_epic_transitions_to_design_gaps_on_write(tmp_path: Path):
    rule = _make_rule()
    state = _make_state()
    state.epic_phase = EpicPhase.DESIGN

    event = HookEvent(
        event_type="post_tool_use",
        tool_name="Write",
        tool_input={"file_path": str(tmp_path / "docs/superpowers/specs/2026-test-design.md")},
        session_id="test",
    )
    response = rule.on_post_tool_use(event, state)
    assert state.epic_phase == EpicPhase.DESIGN_GAPS
    assert response is not None
    assert "DESIGN_GAPS" in response.message


def test_epic_gap_phases_capped_at_2():
    rule = _make_rule()
    state = _make_state()
    state.epic_phase = EpicPhase.DESIGN_GAPS

    state.active_topics["test"] = TopicState(
        slug="test",
        rounds=2,
        findings_per_round=[5, 3],
        first_seen=datetime(2026, 3, 27),
        prior_file=Path("/tmp/test.md"),
    )

    response = rule.check_phase_transition(state)
    assert response is not None
    assert state.epic_phase == EpicPhase.PLANNING


def test_epic_transitions_to_implementation():
    rule = _make_rule()
    state = _make_state()
    state.epic_phase = EpicPhase.PLANNING_GAPS

    state.active_topics["test"] = TopicState(
        slug="test",
        rounds=2,
        findings_per_round=[3, 1],
        first_seen=datetime(2026, 3, 27),
        prior_file=Path("/tmp/test.md"),
    )

    response = rule.check_phase_transition(state)
    assert response is not None
    assert state.epic_phase == EpicPhase.IMPLEMENTATION
    assert "IMPLEMENTATION" in response.message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/session_conductor/test_epic.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement epic rule**

```python
# agents/session_conductor/rules/epic.py
"""Epic pipeline phase tracking — automates research→design→plan→implement flow."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from agents.session_conductor.rules import HookEvent, HookResponse, RuleBase
from agents.session_conductor.state import (
    EPIC_PHASE_ORDER,
    MAX_GAP_ROUNDS,
    EpicPhase,
    SessionState,
)

log = logging.getLogger(__name__)

EPIC_TRIGGER_PATTERNS = [
    r"research\s+(any|all)\s+loose\s+ends",
    r"research\s+(every|all)\s+(coherent\s+)?touch\s+points?",
    r"research\s+(every|all)\s+(coherent\s+)?(granular\s+)?touch\s+points?",
    r"formal\s+design\s+doc",
    r"batched\s+planning.*batched\s+implement",
]

SPEC_PATH_RE = re.compile(r"docs/superpowers/specs/.*-design\.md$")
PLAN_PATH_RE = re.compile(r"docs/superpowers/plans/.*\.md$")


def is_epic_trigger(text: str) -> bool:
    """Detect if text matches the epic workflow pattern."""
    lower = text.lower()
    return any(re.search(p, lower) for p in EPIC_TRIGGER_PATTERNS)


class EpicRule(RuleBase):
    def on_pre_tool_use(self, event: HookEvent, state: SessionState) -> HookResponse | None:
        return None

    def on_post_tool_use(self, event: HookEvent, state: SessionState) -> HookResponse | None:
        # Detect epic entry
        if state.epic_phase is None and event.tool_name == "Agent":
            combined = f"{event.tool_input.get('prompt', '')} {event.user_message}"
            if is_epic_trigger(combined):
                state.epic_phase = EpicPhase.RESEARCH
                log.info("Epic pipeline activated at RESEARCH phase")
                return HookResponse.allow("Epic pipeline activated. Phase: RESEARCH")

        if state.epic_phase is None:
            return None

        # Detect design doc write → transition to DESIGN_GAPS
        if state.epic_phase == EpicPhase.DESIGN and event.tool_name in ("Write", "Edit"):
            file_path = event.tool_input.get("file_path", "")
            if SPEC_PATH_RE.search(file_path):
                state.epic_phase = EpicPhase.DESIGN_GAPS
                return HookResponse.allow(
                    f"Design document written. Transition to DESIGN_GAPS: "
                    f"research gaps in design. Capped at {MAX_GAP_ROUNDS} rounds."
                )

        # Detect plan write → transition to PLANNING_GAPS
        if state.epic_phase == EpicPhase.PLANNING and event.tool_name in ("Write", "Edit"):
            file_path = event.tool_input.get("file_path", "")
            if PLAN_PATH_RE.search(file_path):
                state.epic_phase = EpicPhase.PLANNING_GAPS
                return HookResponse.allow(
                    f"Plan written. Transition to PLANNING_GAPS: "
                    f"research gaps in plan. Capped at {MAX_GAP_ROUNDS} rounds."
                )

        # Check for convergence-driven transitions
        return self.check_phase_transition(state)

    def check_phase_transition(self, state: SessionState) -> HookResponse | None:
        """Check if research convergence should trigger a phase transition."""
        if state.epic_phase is None:
            return None

        # Find any converging or capped topic
        any_converging = any(t.is_converging() for t in state.active_topics.values())
        any_capped = any(t.is_capped() for t in state.active_topics.values())

        # Gap phases use a lower cap
        in_gap_phase = state.epic_phase in (EpicPhase.DESIGN_GAPS, EpicPhase.PLANNING_GAPS)
        any_gap_capped = in_gap_phase and any(
            t.rounds >= MAX_GAP_ROUNDS for t in state.active_topics.values()
        )

        should_transition = any_converging or any_capped or any_gap_capped

        if not should_transition:
            return None

        # Advance to next phase
        current_idx = EPIC_PHASE_ORDER.index(state.epic_phase)
        next_phase = self._next_phase(state.epic_phase)
        if next_phase is None:
            return None

        state.epic_phase = next_phase
        log.info("Epic pipeline advanced to %s", next_phase.value)

        return HookResponse.allow(
            f"Research stabilized. Transition to {next_phase.value.upper()}."
        )

    def _next_phase(self, current: EpicPhase) -> EpicPhase | None:
        """Get the next phase in the epic pipeline."""
        idx = EPIC_PHASE_ORDER.index(current)
        if idx + 1 < len(EPIC_PHASE_ORDER):
            return EPIC_PHASE_ORDER[idx + 1]
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/session_conductor/test_epic.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/hapax/projects/hapax-council
git add agents/session_conductor/rules/epic.py tests/session_conductor/test_epic.py
git commit -m "feat(conductor): add epic pipeline phase tracking rule"
```

---

## Task 7: Relay Sync Rule

**Files:**
- Create: `agents/session_conductor/rules/relay.py`
- Test: `tests/session_conductor/test_relay.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/session_conductor/test_relay.py
"""Tests for relay sync automation rule."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import yaml

from agents.session_conductor.rules import HookEvent
from agents.session_conductor.rules.relay import RelayRule, detect_pr_event
from agents.session_conductor.state import SessionState
from agents.session_conductor.topology import TopologyConfig


def _make_state() -> SessionState:
    return SessionState(session_id="test", pid=1, started_at=datetime(2026, 3, 27))


def _make_rule(tmp_path: Path, role: str = "alpha") -> RelayRule:
    relay_dir = tmp_path / "relay"
    relay_dir.mkdir(parents=True)
    return RelayRule(
        topology=TopologyConfig(),
        relay_dir=relay_dir,
        role=role,
    )


def test_detect_pr_create():
    result = detect_pr_event("https://github.com/hapax/council/pull/382\n")
    assert result is not None
    assert result["type"] == "pr_created"
    assert result["number"] == "382"


def test_detect_pr_merge():
    result = detect_pr_event("✓ Pull request #382 merged\n")
    assert result is not None
    assert result["type"] == "pr_merged"
    assert result["number"] == "382"


def test_detect_no_pr():
    assert detect_pr_event("just some output") is None


def test_relay_writes_status_on_pr(tmp_path: Path):
    rule = _make_rule(tmp_path)
    state = _make_state()
    state.workstream_summary = "voice pipeline"

    event = HookEvent(
        event_type="post_tool_use",
        tool_name="Bash",
        tool_input={
            "command": "gh pr create",
            "result": "https://github.com/hapax/council/pull/400\n",
        },
        session_id="test",
    )
    rule.on_post_tool_use(event, state)

    status_file = tmp_path / "relay" / "alpha.yaml"
    assert status_file.exists()
    status = yaml.safe_load(status_file.read_text())
    assert status["session"] == "alpha"


def test_relay_periodic_sync(tmp_path: Path):
    rule = _make_rule(tmp_path)
    state = _make_state()
    state.last_relay_sync = datetime.now() - timedelta(minutes=31)
    state.workstream_summary = "testing"

    event = HookEvent(
        event_type="post_tool_use",
        tool_name="Edit",
        tool_input={"file_path": "foo.py"},
        session_id="test",
    )
    rule.on_post_tool_use(event, state)

    status_file = tmp_path / "relay" / "alpha.yaml"
    assert status_file.exists()


def test_relay_tracks_in_flight_files(tmp_path: Path):
    rule = _make_rule(tmp_path)
    state = _make_state()

    event = HookEvent(
        event_type="post_tool_use",
        tool_name="Edit",
        tool_input={"file_path": "/home/hapax/projects/hapax-council/agents/voice.py"},
        session_id="test",
    )
    rule.on_post_tool_use(event, state)
    assert "agents/voice.py" in state.in_flight_files or any(
        "voice.py" in f for f in state.in_flight_files
    )


def test_relay_detects_peer_conflict(tmp_path: Path):
    rule = _make_rule(tmp_path)
    state = _make_state()
    state.in_flight_files.add("agents/voice.py")

    # Write peer status showing they're editing the same file
    peer_status = tmp_path / "relay" / "beta.yaml"
    peer_status.write_text(yaml.dump({
        "session": "beta",
        "updated": datetime.now().isoformat(),
        "focus": "voice pipeline refactor",
        "in_flight_files": ["agents/voice.py"],
    }))

    conflicts = rule.check_peer_conflicts(state)
    assert len(conflicts) > 0
    assert "voice.py" in conflicts[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/session_conductor/test_relay.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement relay rule**

```python
# agents/session_conductor/rules/relay.py
"""Automatic relay status sync between sessions."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from agents.session_conductor.rules import HookEvent, HookResponse, RuleBase
from agents.session_conductor.state import SessionState

log = logging.getLogger(__name__)

DEFAULT_RELAY_DIR = Path.home() / ".cache" / "hapax" / "relay"
SYNC_INTERVAL = timedelta(minutes=30)

PR_CREATE_RE = re.compile(r"https://github\.com/[^/]+/[^/]+/pull/(\d+)")
PR_MERGE_RE = re.compile(r"[Pp]ull request #(\d+) merged")

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def detect_pr_event(output: str) -> dict | None:
    """Detect PR creation or merge in command output."""
    match = PR_CREATE_RE.search(output)
    if match:
        return {"type": "pr_created", "number": match.group(1)}
    match = PR_MERGE_RE.search(output)
    if match:
        return {"type": "pr_merged", "number": match.group(1)}
    return None


class RelayRule(RuleBase):
    def __init__(self, topology, relay_dir: Path | None = None, role: str = "alpha") -> None:
        super().__init__(topology)
        self.relay_dir = relay_dir or DEFAULT_RELAY_DIR
        self.relay_dir.mkdir(parents=True, exist_ok=True)
        self.role = role
        self.peer_role = "beta" if role == "alpha" else "alpha"
        self.completed_prs: list[str] = []

    def on_pre_tool_use(self, event: HookEvent, state: SessionState) -> HookResponse | None:
        return None

    def on_post_tool_use(self, event: HookEvent, state: SessionState) -> HookResponse | None:
        # Track in-flight files
        if event.tool_name in EDIT_TOOLS:
            file_path = event.tool_input.get("file_path", "")
            if file_path:
                # Normalize to relative path
                relative = file_path.replace("/home/hapax/projects/hapax-council/", "")
                state.in_flight_files.add(relative)

        # Detect PR events
        if event.tool_name == "Bash":
            result = event.tool_input.get("result", "")
            pr_event = detect_pr_event(result)
            if pr_event:
                self.completed_prs.append(f"PR #{pr_event['number']} ({pr_event['type']})")
                self._write_status(state)
                return HookResponse.allow(
                    f"Relay status updated: {pr_event['type']} #{pr_event['number']}"
                )

        # Periodic sync
        now = datetime.now()
        if state.last_relay_sync is None or now - state.last_relay_sync > SYNC_INTERVAL:
            self._write_status(state)
            state.last_relay_sync = now

        return None

    def _write_status(self, state: SessionState) -> None:
        """Write relay status file."""
        status = {
            "session": self.role,
            "updated": datetime.now().isoformat(),
            "workstream": state.workstream_summary or "active",
            "focus": state.epic_phase.value if state.epic_phase else "general",
            "current_item": None,
            "in_flight_files": sorted(state.in_flight_files),
            "completed": self.completed_prs[-10:],  # last 10
        }
        status_file = self.relay_dir / f"{self.role}.yaml"
        status_file.write_text(yaml.dump(status, default_flow_style=False))

    def check_peer_conflicts(self, state: SessionState) -> list[str]:
        """Check if peer session is editing the same files."""
        peer_file = self.relay_dir / f"{self.peer_role}.yaml"
        if not peer_file.exists():
            return []

        try:
            peer = yaml.safe_load(peer_file.read_text()) or {}
        except Exception:
            return []

        peer_files = set(peer.get("in_flight_files", []))
        conflicts = state.in_flight_files & peer_files
        return [f"CONFLICT: both sessions editing {f}" for f in sorted(conflicts)]

    def write_final_status(self, state: SessionState) -> None:
        """Write final status on session shutdown."""
        self._write_status(state)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/session_conductor/test_relay.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/hapax/projects/hapax-council
git add agents/session_conductor/rules/relay.py tests/session_conductor/test_relay.py
git commit -m "feat(conductor): add relay sync automation rule"
```

---

## Task 8: Smoke Test Rule

**Files:**
- Create: `agents/session_conductor/rules/smoke.py`
- Test: `tests/session_conductor/test_smoke.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/session_conductor/test_smoke.py
"""Tests for smoke test standardization rule."""

from __future__ import annotations

from datetime import datetime

from agents.session_conductor.rules import HookEvent
from agents.session_conductor.rules.smoke import SmokeRule, is_smoke_test_trigger
from agents.session_conductor.state import SessionState
from agents.session_conductor.topology import PlaywrightConfig, SmokeTestConfig, TopologyConfig


def _make_state() -> SessionState:
    return SessionState(session_id="test", pid=1, started_at=datetime(2026, 3, 27))


def _make_rule() -> SmokeRule:
    return SmokeRule(
        topology=TopologyConfig(
            playwright=PlaywrightConfig(
                testing_workspace=10,
                screenshot_max_bytes=500_000,
                never_switch_operator_focus=True,
            ),
            smoke_test=SmokeTestConfig(
                workspace=10,
                fullscreen=True,
                launch_method="fuzzel",
                screenshot_interval_ms=2000,
            ),
        )
    )


def test_smoke_trigger_detection():
    assert is_smoke_test_trigger("smoke test the whole thing") is True
    assert is_smoke_test_trigger("smoke test then smoke test end-to-end") is True
    assert is_smoke_test_trigger("fix the login bug") is False


def test_smoke_activates_on_user_message():
    rule = _make_rule()
    state = _make_state()

    event = HookEvent(
        event_type="post_tool_use",
        tool_name="Bash",
        tool_input={"command": "echo start"},
        session_id="test",
        user_message="smoke test using playwright",
    )
    rule.on_post_tool_use(event, state)
    assert state.smoke_test_active is True


def test_smoke_activates_on_pr_create():
    rule = _make_rule()
    state = _make_state()

    event = HookEvent(
        event_type="post_tool_use",
        tool_name="Bash",
        tool_input={
            "command": "gh pr create",
            "result": "https://github.com/hapax/council/pull/400",
        },
        session_id="test",
    )
    rule.on_post_tool_use(event, state)
    assert state.smoke_test_active is True


def test_smoke_rewrites_playwright_when_active():
    rule = _make_rule()
    state = _make_state()
    state.smoke_test_active = True

    event = HookEvent(
        event_type="pre_tool_use",
        tool_name="browser_navigate",
        tool_input={"url": "http://localhost:5173"},
        session_id="test",
    )
    response = rule.on_pre_tool_use(event, state)
    assert response is not None
    assert response.action == "rewrite"
    assert response.rewrite["workspace"] == 10
    assert response.rewrite["fullscreen"] is True


def test_smoke_no_rewrite_when_inactive():
    rule = _make_rule()
    state = _make_state()
    state.smoke_test_active = False

    event = HookEvent(
        event_type="pre_tool_use",
        tool_name="browser_navigate",
        tool_input={"url": "http://localhost:5173"},
        session_id="test",
    )
    response = rule.on_pre_tool_use(event, state)
    # Focus rule would handle this, not smoke rule
    assert response is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/session_conductor/test_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement smoke rule**

```python
# agents/session_conductor/rules/smoke.py
"""Smoke test standardization — auto-activates correct workspace, fullscreen, size limits."""

from __future__ import annotations

import logging
import re

from agents.session_conductor.rules import HookEvent, HookResponse, RuleBase
from agents.session_conductor.state import SessionState

log = logging.getLogger(__name__)

SMOKE_RE = re.compile(r"smoke\s+test", re.IGNORECASE)
PR_CREATE_RE = re.compile(r"https://github\.com/[^/]+/[^/]+/pull/\d+")
PLAYWRIGHT_TOOL_PREFIX = "browser_"


def is_smoke_test_trigger(text: str) -> bool:
    return SMOKE_RE.search(text) is not None


class SmokeRule(RuleBase):
    def on_pre_tool_use(self, event: HookEvent, state: SessionState) -> HookResponse | None:
        if not state.smoke_test_active:
            return None

        if not event.tool_name.startswith(PLAYWRIGHT_TOOL_PREFIX):
            return None

        config = self.topology.smoke_test
        return HookResponse(
            action="rewrite",
            message=f"Smoke test active: workspace {config.workspace}, fullscreen={config.fullscreen}.",
            rewrite={
                "workspace": config.workspace,
                "fullscreen": config.fullscreen,
                "launch_method": config.launch_method,
                "screenshot_max_bytes": self.topology.playwright.screenshot_max_bytes,
            },
        )

    def on_post_tool_use(self, event: HookEvent, state: SessionState) -> HookResponse | None:
        # Activate on user message containing "smoke test"
        if event.user_message and is_smoke_test_trigger(event.user_message):
            if not state.smoke_test_active:
                state.smoke_test_active = True
                log.info("Smoke test profile activated via user message")
                return HookResponse.allow("Smoke test profile activated.")

        # Activate on PR creation
        if event.tool_name == "Bash":
            result = event.tool_input.get("result", "")
            if PR_CREATE_RE.search(result) and not state.smoke_test_active:
                state.smoke_test_active = True
                log.info("Smoke test profile activated via PR creation")
                return HookResponse.allow(
                    "PR created. Smoke test profile activated for post-PR verification."
                )

        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/session_conductor/test_smoke.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/hapax/projects/hapax-council
git add agents/session_conductor/rules/smoke.py tests/session_conductor/test_smoke.py
git commit -m "feat(conductor): add smoke test standardization rule"
```

---

## Task 9: Session Spawn & Reunion Rule

**Files:**
- Create: `agents/session_conductor/rules/spawn.py`
- Test: `tests/session_conductor/test_spawn.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/session_conductor/test_spawn.py
"""Tests for session spawning and reunion rule."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import yaml

from agents.session_conductor.rules import HookEvent
from agents.session_conductor.rules.spawn import SpawnRule, detect_spawn_intent
from agents.session_conductor.state import ChildSession, SessionState
from agents.session_conductor.topology import TopologyConfig


def _make_state() -> SessionState:
    return SessionState(session_id="parent-123", pid=1, started_at=datetime(2026, 3, 27))


def _make_rule(tmp_path: Path) -> SpawnRule:
    spawns_dir = tmp_path / "conductor" / "spawns"
    spawns_dir.mkdir(parents=True)
    return SpawnRule(topology=TopologyConfig(), spawns_dir=spawns_dir)


def test_detect_spawn_intent():
    assert detect_spawn_intent("break this out to another session") is True
    assert detect_spawn_intent("have another session fix this") is True
    assert detect_spawn_intent("fix it in a separate session") is True
    assert detect_spawn_intent("fix the login bug") is False


def test_spawn_writes_manifest(tmp_path: Path):
    rule = _make_rule(tmp_path)
    state = _make_state()
    state.in_flight_files = {"agents/voice.py", "agents/salience.py"}

    event = HookEvent(
        event_type="post_tool_use",
        tool_name="Bash",
        tool_input={"command": "echo test"},
        session_id="parent-123",
        user_message="break this out to another session, the logos API is returning 500",
    )
    response = rule.on_post_tool_use(event, state)

    assert response is not None
    spawns_dir = tmp_path / "conductor" / "spawns"
    manifests = list(spawns_dir.glob("*.yaml"))
    assert len(manifests) == 1

    manifest = yaml.safe_load(manifests[0].read_text())
    assert manifest["parent_session"] == "parent-123"
    assert manifest["status"] == "pending"
    assert "agents/voice.py" in manifest["do_not_touch"]


def test_child_claims_manifest(tmp_path: Path):
    rule = _make_rule(tmp_path)

    # Write a pending manifest
    spawns_dir = tmp_path / "conductor" / "spawns"
    manifest_file = spawns_dir / "spawn-test.yaml"
    manifest_file.write_text(yaml.dump({
        "parent_session": "parent-123",
        "topic": "logos-api-bug",
        "context": "API returning 500",
        "do_not_touch": ["agents/voice.py"],
        "in_flight_files": ["agents/voice.py"],
        "created": datetime.now().isoformat(),
        "status": "pending",
    }))

    child_state = SessionState(
        session_id="child-456", pid=2, started_at=datetime(2026, 3, 27)
    )

    result = rule.claim_pending_manifest(child_state)
    assert result is not None
    assert child_state.parent_session == "parent-123"
    assert "logos-api-bug" in result


def test_child_blocked_from_parent_files(tmp_path: Path):
    rule = _make_rule(tmp_path)
    state = SessionState(
        session_id="child-456",
        pid=2,
        started_at=datetime(2026, 3, 27),
        parent_session="parent-123",
    )
    rule.blocked_patterns = ["agents/voice.py", "agents/salience.py"]

    event = HookEvent(
        event_type="pre_tool_use",
        tool_name="Edit",
        tool_input={"file_path": "/home/hapax/projects/hapax-council/agents/voice.py"},
        session_id="child-456",
    )
    response = rule.on_pre_tool_use(event, state)
    assert response is not None
    assert response.action == "block"


def test_reunion_injects_results(tmp_path: Path):
    rule = _make_rule(tmp_path)
    state = _make_state()

    # Create a completed spawn manifest
    spawns_dir = tmp_path / "conductor" / "spawns"
    manifest_file = spawns_dir / "spawn-test.yaml"
    manifest_file.write_text(yaml.dump({
        "parent_session": "parent-123",
        "topic": "logos-api-bug",
        "status": "completed",
        "result": "Fixed empty stimmung vector. PR #382 merged.",
        "files_changed": ["logos/api/routes/cockpit.py"],
    }))

    state.children.append(ChildSession(
        session_id="child-456",
        topic="logos-api-bug",
        spawn_manifest=manifest_file,
        status="pending",
    ))

    results = rule.check_completed_children(state)
    assert len(results) == 1
    assert "PR #382" in results[0]


def test_stale_manifest_ignored(tmp_path: Path):
    rule = _make_rule(tmp_path)

    # Write a manifest from 20 minutes ago
    spawns_dir = tmp_path / "conductor" / "spawns"
    manifest_file = spawns_dir / "old-spawn.yaml"
    manifest_file.write_text(yaml.dump({
        "parent_session": "old-parent",
        "topic": "stale-issue",
        "created": (datetime.now() - timedelta(minutes=20)).isoformat(),
        "status": "pending",
    }))

    child_state = SessionState(
        session_id="child-789", pid=3, started_at=datetime(2026, 3, 27)
    )
    result = rule.claim_pending_manifest(child_state)
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/session_conductor/test_spawn.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement spawn rule**

```python
# agents/session_conductor/rules/spawn.py
"""Session spawning and reunion — context packaging and result injection."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from fnmatch import fnmatch

import yaml

from agents.session_conductor.rules import HookEvent, HookResponse, RuleBase
from agents.session_conductor.state import ChildSession, SessionState

log = logging.getLogger(__name__)

DEFAULT_SPAWNS_DIR = Path.home() / ".cache" / "hapax" / "conductor" / "spawns"
MANIFEST_CLAIM_WINDOW = timedelta(minutes=10)

SPAWN_PATTERNS = [
    r"break\s+this\s+out\s+to\s+another\s+session",
    r"have\s+another\s+session\s+fix",
    r"fix\s+(it|this)\s+in\s+a\s+(separate|different)\s+session",
    r"another\s+session\s+(should|can|will)\s+(handle|fix|implement)",
    r"spawn\s+a\s+session",
]

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def detect_spawn_intent(text: str) -> bool:
    lower = text.lower()
    return any(re.search(p, lower) for p in SPAWN_PATTERNS)


class SpawnRule(RuleBase):
    def __init__(self, topology, spawns_dir: Path | None = None) -> None:
        super().__init__(topology)
        self.spawns_dir = spawns_dir or DEFAULT_SPAWNS_DIR
        self.spawns_dir.mkdir(parents=True, exist_ok=True)
        self.blocked_patterns: list[str] = []

    def on_pre_tool_use(self, event: HookEvent, state: SessionState) -> HookResponse | None:
        # Block edits to parent's in-flight files
        if state.parent_session and event.tool_name in EDIT_TOOLS:
            file_path = event.tool_input.get("file_path", "")
            relative = file_path.replace("/home/hapax/projects/hapax-council/", "")
            for pattern in self.blocked_patterns:
                if fnmatch(relative, pattern) or relative == pattern:
                    return HookResponse.block(
                        f"BLOCKED: parent session has in-flight changes on {relative}. "
                        f"Do not edit this file."
                    )
        return None

    def on_post_tool_use(self, event: HookEvent, state: SessionState) -> HookResponse | None:
        if event.user_message and detect_spawn_intent(event.user_message):
            return self._write_spawn_manifest(event, state)
        return None

    def _write_spawn_manifest(self, event: HookEvent, state: SessionState) -> HookResponse:
        """Write a spawn manifest for a child session."""
        timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        context = event.user_message

        manifest = {
            "parent_session": state.session_id,
            "topic": "side-issue",
            "context": context,
            "do_not_touch": sorted(state.in_flight_files),
            "in_flight_files": sorted(state.in_flight_files),
            "created": datetime.now().isoformat(),
            "status": "pending",
        }

        manifest_file = self.spawns_dir / f"{timestamp}-spawn.yaml"
        manifest_file.write_text(yaml.dump(manifest, default_flow_style=False))

        state.children.append(ChildSession(
            session_id="pending",
            topic="side-issue",
            spawn_manifest=manifest_file,
            status="pending",
        ))

        log.info("Spawn manifest written: %s", manifest_file)
        return HookResponse.allow(
            f"Spawn manifest written. Next Claude Code session in this project "
            f"will receive context and file-edit restrictions."
        )

    def claim_pending_manifest(self, state: SessionState) -> str | None:
        """Called at session start — claim a pending manifest if one exists."""
        now = datetime.now()
        for manifest_file in sorted(self.spawns_dir.glob("*.yaml")):
            try:
                manifest = yaml.safe_load(manifest_file.read_text()) or {}
            except Exception:
                continue

            if manifest.get("status") != "pending":
                continue

            created = datetime.fromisoformat(manifest["created"])
            if now - created > MANIFEST_CLAIM_WINDOW:
                continue

            # Claim it
            manifest["status"] = "claimed"
            manifest["child_session"] = state.session_id
            manifest_file.write_text(yaml.dump(manifest, default_flow_style=False))

            state.parent_session = manifest["parent_session"]
            self.blocked_patterns = manifest.get("do_not_touch", [])

            context = manifest.get("context", "")
            topic = manifest.get("topic", "side-issue")

            return (
                f"SPAWNED SESSION — fixing side issue for parent session.\n"
                f"Topic: {topic}\n"
                f"Context: {context}\n"
                f"DO NOT EDIT (parent has in-flight changes):\n"
                + "\n".join(f"  - {f}" for f in self.blocked_patterns)
                + "\nComplete the fix, PR it, and exit."
            )

        return None

    def check_completed_children(self, state: SessionState) -> list[str]:
        """Check if any child sessions have completed."""
        results: list[str] = []
        for child in state.children:
            if child.status == "completed":
                continue
            if not child.spawn_manifest.exists():
                continue
            try:
                manifest = yaml.safe_load(child.spawn_manifest.read_text()) or {}
            except Exception:
                continue

            if manifest.get("status") == "completed":
                child.status = "completed"
                result_text = manifest.get("result", "No details provided.")
                files_changed = manifest.get("files_changed", [])
                msg = (
                    f"CHILD SESSION COMPLETED: {child.topic}\n"
                    f"Result: {result_text}\n"
                )
                if files_changed:
                    msg += f"Files changed: {', '.join(files_changed)}\n"
                    msg += "Action needed: rebase onto main to pick up changes."
                results.append(msg)

        return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/session_conductor/test_spawn.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/hapax/projects/hapax-council
git add agents/session_conductor/rules/spawn.py tests/session_conductor/test_spawn.py
git commit -m "feat(conductor): add session spawning and reunion rule"
```

---

## Task 10: UDS Protocol Server

**Files:**
- Create: `agents/session_conductor/protocol.py`
- Test: `tests/session_conductor/test_protocol.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/session_conductor/test_protocol.py
"""Tests for UDS protocol server and event routing."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest

from agents.session_conductor.protocol import ConductorServer
from agents.session_conductor.rules import HookEvent, HookResponse, RuleBase, RuleRegistry
from agents.session_conductor.state import SessionState
from agents.session_conductor.topology import TopologyConfig


class AllowRule(RuleBase):
    def on_pre_tool_use(self, event: HookEvent, state: SessionState) -> HookResponse | None:
        return None

    def on_post_tool_use(self, event: HookEvent, state: SessionState) -> HookResponse | None:
        return None


class BlockRule(RuleBase):
    def on_pre_tool_use(self, event: HookEvent, state: SessionState) -> HookResponse | None:
        if event.tool_name == "Dangerous":
            return HookResponse.block("Blocked by test rule")
        return None

    def on_post_tool_use(self, event: HookEvent, state: SessionState) -> HookResponse | None:
        return HookResponse.allow("Noted by test rule")


def _make_server(tmp_path: Path) -> ConductorServer:
    state = SessionState(session_id="test-123", pid=1, started_at=datetime(2026, 3, 27))
    registry = RuleRegistry()
    topology = TopologyConfig()
    registry.register(AllowRule(topology=topology))
    registry.register(BlockRule(topology=topology))
    state_path = tmp_path / "state.json"
    sock_path = tmp_path / "conductor.sock"
    return ConductorServer(
        state=state,
        registry=registry,
        state_path=state_path,
        sock_path=sock_path,
    )


def test_process_event_allow(tmp_path: Path):
    server = _make_server(tmp_path)
    event_data = {
        "event": "pre_tool_use",
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
        "session_id": "test-123",
    }
    response = server.process_event(event_data)
    assert response["action"] == "allow"


def test_process_event_block(tmp_path: Path):
    server = _make_server(tmp_path)
    event_data = {
        "event": "pre_tool_use",
        "tool_name": "Dangerous",
        "tool_input": {},
        "session_id": "test-123",
    }
    response = server.process_event(event_data)
    assert response["action"] == "block"
    assert "Blocked by test rule" in response["message"]


def test_process_event_post_tool(tmp_path: Path):
    server = _make_server(tmp_path)
    event_data = {
        "event": "post_tool_use",
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
        "session_id": "test-123",
    }
    response = server.process_event(event_data)
    assert response["action"] == "allow"
    assert "Noted" in response["message"]


def test_process_event_saves_state(tmp_path: Path):
    server = _make_server(tmp_path)
    event_data = {
        "event": "post_tool_use",
        "tool_name": "Bash",
        "tool_input": {},
        "session_id": "test-123",
    }
    server.process_event(event_data)
    assert server.state_path.exists()


def test_process_event_invalid_json(tmp_path: Path):
    server = _make_server(tmp_path)
    response = server.process_event({})
    assert response["action"] == "allow"


@pytest.mark.asyncio
async def test_uds_roundtrip(tmp_path: Path):
    server = _make_server(tmp_path)
    sock_path = tmp_path / "conductor.sock"

    # Start server
    task = asyncio.create_task(server.start())
    await asyncio.sleep(0.1)  # let server bind

    # Connect and send event
    reader, writer = await asyncio.open_unix_connection(str(sock_path))
    event = json.dumps({
        "event": "pre_tool_use",
        "tool_name": "Dangerous",
        "tool_input": {},
        "session_id": "test-123",
    })
    writer.write(event.encode() + b"\n")
    await writer.drain()

    response_line = await asyncio.wait_for(reader.readline(), timeout=2.0)
    response = json.loads(response_line)
    assert response["action"] == "block"

    writer.close()
    await writer.wait_closed()
    server.shutdown()
    await task
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/session_conductor/test_protocol.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement protocol server**

```python
# agents/session_conductor/protocol.py
"""UDS server for receiving hook events and routing to rules."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from agents.session_conductor.rules import HookEvent, HookResponse, RuleRegistry
from agents.session_conductor.state import SessionState

log = logging.getLogger(__name__)

DEFAULT_SOCK_DIR = Path("/run/user/1000")


class ConductorServer:
    def __init__(
        self,
        state: SessionState,
        registry: RuleRegistry,
        state_path: Path,
        sock_path: Path | None = None,
    ) -> None:
        self.state = state
        self.registry = registry
        self.state_path = state_path
        self.sock_path = sock_path or DEFAULT_SOCK_DIR / f"conductor-{state.session_id}.sock"
        self._server: asyncio.AbstractServer | None = None
        self._running = True

    def process_event(self, event_data: dict) -> dict:
        """Process a single hook event and return response dict."""
        try:
            event = HookEvent.from_dict(event_data)
        except Exception:
            log.exception("Failed to parse hook event")
            return HookResponse.allow().to_dict()

        if event.event_type == "pre_tool_use":
            response = self.registry.process_pre_tool_use(event, self.state)
            if response:
                self._save_state()
                return response.to_dict()
            self._save_state()
            return HookResponse.allow().to_dict()

        elif event.event_type == "post_tool_use":
            responses = self.registry.process_post_tool_use(event, self.state)
            self._save_state()
            if responses:
                # Combine all advisory messages
                combined_message = "\n".join(r.message for r in responses if r.message)
                return HookResponse.allow(combined_message).to_dict()
            return HookResponse.allow().to_dict()

        return HookResponse.allow().to_dict()

    async def start(self) -> None:
        """Start the UDS server."""
        self.sock_path.parent.mkdir(parents=True, exist_ok=True)
        if self.sock_path.exists():
            self.sock_path.unlink()

        self._server = await asyncio.start_unix_server(
            self._handle_client, path=str(self.sock_path)
        )
        log.info("Conductor server listening on %s", self.sock_path)

        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            self._server.close()
            await self._server.wait_closed()
            if self.sock_path.exists():
                self.sock_path.unlink()

    def shutdown(self) -> None:
        """Signal the server to stop."""
        self._running = False

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a single client connection."""
        try:
            data = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if not data:
                return

            event_data = json.loads(data.decode())
            response = self.process_event(event_data)
            writer.write(json.dumps(response).encode() + b"\n")
            await writer.drain()
        except asyncio.TimeoutError:
            log.warning("Client connection timed out")
        except json.JSONDecodeError:
            log.warning("Invalid JSON from client")
            writer.write(json.dumps(HookResponse.allow().to_dict()).encode() + b"\n")
            await writer.drain()
        except Exception:
            log.exception("Error handling client")
        finally:
            writer.close()
            await writer.wait_closed()

    def _save_state(self) -> None:
        """Persist state to disk."""
        try:
            self.state.save(self.state_path)
        except Exception:
            log.exception("Failed to save state")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/session_conductor/test_protocol.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/hapax/projects/hapax-council
git add agents/session_conductor/protocol.py tests/session_conductor/test_protocol.py
git commit -m "feat(conductor): add UDS protocol server"
```

---

## Task 11: CLI Entry Point

**Files:**
- Create: `agents/session_conductor/__main__.py`

- [ ] **Step 1: Write the entry point**

```python
# agents/session_conductor/__main__.py
"""Session Conductor — deterministic sidecar for Claude Code session automation.

Usage:
    uv run python -m agents.session_conductor start --session-id ID --cc-pid PID [--role alpha]
    uv run python -m agents.session_conductor stop --session-id ID
    uv run python -m agents.session_conductor status --session-id ID
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

from shared.log_setup import configure_logging

from agents.session_conductor.protocol import ConductorServer
from agents.session_conductor.rules import RuleRegistry
from agents.session_conductor.rules.convergence import ConvergenceRule
from agents.session_conductor.rules.epic import EpicRule
from agents.session_conductor.rules.focus import FocusRule
from agents.session_conductor.rules.relay import RelayRule
from agents.session_conductor.rules.smoke import SmokeRule
from agents.session_conductor.rules.spawn import SpawnRule
from agents.session_conductor.state import SessionState
from agents.session_conductor.topology import load_topology

log = logging.getLogger(__name__)

STATE_DIR = Path("/dev/shm")
SOCK_DIR = Path(f"/run/user/{os.getuid()}")
PID_DIR = Path.home() / ".cache" / "hapax" / "conductor"


def start(args: argparse.Namespace) -> None:
    """Launch the conductor sidecar."""
    configure_logging(agent="session_conductor")

    session_id = args.session_id
    cc_pid = args.cc_pid
    role = args.role

    # PID file check
    PID_DIR.mkdir(parents=True, exist_ok=True)
    pid_file = PID_DIR / f"{session_id}.pid"
    if pid_file.exists():
        existing_pid = int(pid_file.read_text().strip())
        try:
            os.kill(existing_pid, 0)
            log.error("Conductor already running for session %s (pid %d)", session_id, existing_pid)
            sys.exit(1)
        except ProcessLookupError:
            pid_file.unlink()

    pid_file.write_text(str(os.getpid()))

    # Load topology
    topology = load_topology()

    # Create state
    state = SessionState(
        session_id=session_id,
        pid=cc_pid,
        started_at=datetime.now(),
    )

    # Build rule registry
    registry = RuleRegistry()
    registry.register(FocusRule(topology=topology))
    registry.register(SmokeRule(topology=topology))
    registry.register(ConvergenceRule(topology=topology))
    registry.register(EpicRule(topology=topology))
    registry.register(RelayRule(topology=topology, role=role))

    spawn_rule = SpawnRule(topology=topology)
    registry.register(spawn_rule)

    # Check for pending spawn manifest (child session startup)
    spawn_context = spawn_rule.claim_pending_manifest(state)
    if spawn_context:
        log.info("Claimed spawn manifest — this is a child session")
        # Write context to a file the SessionStart hook can inject
        context_file = PID_DIR / f"{session_id}.spawn-context"
        context_file.write_text(spawn_context)

    # Create server
    state_path = STATE_DIR / f"conductor-{session_id}.json"
    sock_path = SOCK_DIR / f"conductor-{session_id}.sock"
    server = ConductorServer(
        state=state,
        registry=registry,
        state_path=state_path,
        sock_path=sock_path,
    )

    # Signal handlers
    def handle_shutdown(signum, frame):
        log.info("Received signal %d, shutting down", signum)
        server.shutdown()

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    # Parent PID watchdog
    async def watchdog():
        while server._running:
            try:
                os.kill(cc_pid, 0)
            except ProcessLookupError:
                log.warning("Parent CC process %d gone, shutting down", cc_pid)
                server.shutdown()
                return
            await asyncio.sleep(30)

    async def run():
        asyncio.create_task(watchdog())
        await server.start()

    log.info(
        "Starting conductor for session %s (CC pid %d, role %s)",
        session_id, cc_pid, role,
    )

    try:
        asyncio.run(run())
    finally:
        # Cleanup
        relay_rule = next((r for r in registry._rules if isinstance(r, RelayRule)), None)
        if relay_rule:
            relay_rule.write_final_status(state)

        if pid_file.exists():
            pid_file.unlink()
        if state_path.exists():
            state_path.unlink()
        log.info("Conductor shut down cleanly")


def stop(args: argparse.Namespace) -> None:
    """Send shutdown signal to a running conductor."""
    pid_file = PID_DIR / f"{args.session_id}.pid"
    if not pid_file.exists():
        print(f"No conductor found for session {args.session_id}")
        sys.exit(1)

    pid = int(pid_file.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to conductor pid {pid}")
    except ProcessLookupError:
        print(f"Conductor pid {pid} already gone, cleaning up")
        pid_file.unlink()


def status(args: argparse.Namespace) -> None:
    """Print conductor state."""
    state_path = STATE_DIR / f"conductor-{args.session_id}.json"
    if not state_path.exists():
        print(f"No state found for session {args.session_id}")
        sys.exit(1)

    state = SessionState.load(state_path)
    print(json.dumps({
        "session_id": state.session_id,
        "pid": state.pid,
        "started_at": state.started_at.isoformat(),
        "active_topics": len(state.active_topics),
        "in_flight_files": len(state.in_flight_files),
        "epic_phase": state.epic_phase.value if state.epic_phase else None,
        "children": len(state.children),
        "smoke_test_active": state.smoke_test_active,
    }, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Session Conductor")
    sub = parser.add_subparsers(dest="command", required=True)

    start_p = sub.add_parser("start", help="Launch conductor sidecar")
    start_p.add_argument("--session-id", required=True)
    start_p.add_argument("--cc-pid", type=int, required=True)
    start_p.add_argument("--role", default="alpha", choices=["alpha", "beta"])

    stop_p = sub.add_parser("stop", help="Stop conductor")
    stop_p.add_argument("--session-id", required=True)

    status_p = sub.add_parser("status", help="Print conductor state")
    status_p.add_argument("--session-id", required=True)

    args = parser.parse_args()

    if args.command == "start":
        start(args)
    elif args.command == "stop":
        stop(args)
    elif args.command == "status":
        status(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it parses help without error**

Run: `cd /home/hapax/projects/hapax-council && uv run python -m agents.session_conductor --help`
Expected: Usage text with start/stop/status subcommands

- [ ] **Step 3: Commit**

```bash
cd /home/hapax/projects/hapax-council
git add agents/session_conductor/__main__.py
git commit -m "feat(conductor): add CLI entry point with start/stop/status"
```

---

## Task 12: Hook Shim Scripts

**Files:**
- Create: `hooks/scripts/conductor-start.sh`
- Create: `hooks/scripts/conductor-stop.sh`
- Create: `hooks/scripts/conductor-pre.sh`
- Create: `hooks/scripts/conductor-post.sh`

- [ ] **Step 1: Write the SessionStart hook**

```bash
#!/usr/bin/env bash
# conductor-start.sh — SessionStart hook: launch conductor sidecar
set -euo pipefail

INPUT="$(cat)"
SESSION_ID="$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)"
[ -z "$SESSION_ID" ] && exit 0

CC_PID="$$"
COUNCIL_DIR="$HOME/projects/hapax-council"
PID_DIR="$HOME/.cache/hapax/conductor"

# Detect role from worktree
ROLE="alpha"
CWD="$(pwd)"
if echo "$CWD" | grep -q "\-\-beta"; then
    ROLE="beta"
fi

# Don't launch if already running for this session
if [ -f "$PID_DIR/$SESSION_ID.pid" ]; then
    EXISTING_PID="$(cat "$PID_DIR/$SESSION_ID.pid")"
    if kill -0 "$EXISTING_PID" 2>/dev/null; then
        exit 0
    fi
fi

# Launch conductor as background process in a systemd scope
systemd-run --user --scope --quiet \
    --unit="conductor-${SESSION_ID:0:8}" \
    --description="Session Conductor for $SESSION_ID" \
    "$HOME/.local/bin/uv" run \
    --directory "$COUNCIL_DIR" \
    python -m agents.session_conductor start \
    --session-id "$SESSION_ID" \
    --cc-pid "$PPID" \
    --role "$ROLE" \
    &>/dev/null &

# Wait for socket to appear (up to 3 seconds)
SOCK="/run/user/$(id -u)/conductor-${SESSION_ID}.sock"
for i in $(seq 1 30); do
    [ -S "$SOCK" ] && break
    sleep 0.1
done

# Inject spawn context if this is a child session
CONTEXT_FILE="$PID_DIR/$SESSION_ID.spawn-context"
if [ -f "$CONTEXT_FILE" ]; then
    cat "$CONTEXT_FILE"
    rm -f "$CONTEXT_FILE"
fi
```

- [ ] **Step 2: Write the Stop hook**

```bash
#!/usr/bin/env bash
# conductor-stop.sh — Stop hook: shutdown conductor sidecar
set -euo pipefail

INPUT="$(cat)"
SESSION_ID="$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)"
[ -z "$SESSION_ID" ] && exit 0

COUNCIL_DIR="$HOME/projects/hapax-council"

cd "$COUNCIL_DIR" && uv run python -m agents.session_conductor stop \
    --session-id "$SESSION_ID" 2>/dev/null || true
```

- [ ] **Step 3: Write the PreToolUse shim**

```bash
#!/usr/bin/env bash
# conductor-pre.sh — PreToolUse hook: pipe event to conductor UDS
set -euo pipefail

INPUT="$(cat)"
SESSION_ID="$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)"
[ -z "$SESSION_ID" ] && exit 0

SOCK="/run/user/$(id -u)/conductor-${SESSION_ID}.sock"
[ -S "$SOCK" ] || exit 0  # No conductor = allow all

# Build event JSON
TOOL_NAME="$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)"
EVENT="{\"event\":\"pre_tool_use\",\"tool_name\":\"$TOOL_NAME\",\"tool_input\":$(echo "$INPUT" | jq '.tool_input // {}' 2>/dev/null),\"session_id\":\"$SESSION_ID\"}"

RESPONSE="$(echo "$EVENT" | timeout 0.5 socat - UNIX-CONNECT:"$SOCK" 2>/dev/null)" || exit 0

ACTION="$(echo "$RESPONSE" | jq -r '.action // "allow"' 2>/dev/null)"
MESSAGE="$(echo "$RESPONSE" | jq -r '.message // empty' 2>/dev/null)"

[ -n "$MESSAGE" ] && echo "$MESSAGE" >&2

case "$ACTION" in
    block) exit 2 ;;
    *) exit 0 ;;
esac
```

- [ ] **Step 4: Write the PostToolUse shim**

```bash
#!/usr/bin/env bash
# conductor-post.sh — PostToolUse hook: pipe event to conductor UDS
set -euo pipefail

INPUT="$(cat)"
SESSION_ID="$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)"
[ -z "$SESSION_ID" ] && exit 0

SOCK="/run/user/$(id -u)/conductor-${SESSION_ID}.sock"
[ -S "$SOCK" ] || exit 0

TOOL_NAME="$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)"
EVENT="{\"event\":\"post_tool_use\",\"tool_name\":\"$TOOL_NAME\",\"tool_input\":$(echo "$INPUT" | jq '.tool_input // {}' 2>/dev/null),\"session_id\":\"$SESSION_ID\"}"

RESPONSE="$(echo "$EVENT" | timeout 0.5 socat - UNIX-CONNECT:"$SOCK" 2>/dev/null)" || exit 0

MESSAGE="$(echo "$RESPONSE" | jq -r '.message // empty' 2>/dev/null)"
[ -n "$MESSAGE" ] && echo "$MESSAGE" >&2

exit 0
```

- [ ] **Step 5: Make all scripts executable**

Run: `chmod +x /home/hapax/projects/hapax-council/hooks/scripts/conductor-{start,stop,pre,post}.sh`

- [ ] **Step 6: Commit**

```bash
cd /home/hapax/projects/hapax-council
git add hooks/scripts/conductor-start.sh hooks/scripts/conductor-stop.sh hooks/scripts/conductor-pre.sh hooks/scripts/conductor-post.sh
git commit -m "feat(conductor): add hook shim scripts"
```

---

## Task 13: Wire Hooks into settings.json

**Files:**
- Modify: `~/.claude/settings.json`

- [ ] **Step 1: Read current settings.json to find hook sections**

Run: `cat ~/.claude/settings.json | jq '.hooks'`

- [ ] **Step 2: Add conductor hooks to settings.json**

Add these entries to the existing hooks arrays (do not remove existing hooks):

Under `PreToolUse`, add:
```json
{
  "matcher": "",
  "hooks": [
    {
      "type": "command",
      "command": "/home/hapax/projects/hapax-council/hooks/scripts/conductor-pre.sh"
    }
  ]
}
```

Under `PostToolUse`, add:
```json
{
  "matcher": "",
  "hooks": [
    {
      "type": "command",
      "command": "/home/hapax/projects/hapax-council/hooks/scripts/conductor-post.sh"
    }
  ]
}
```

Under `SessionStart`, add:
```json
{
  "matcher": "",
  "hooks": [
    {
      "type": "command",
      "command": "/home/hapax/projects/hapax-council/hooks/scripts/conductor-start.sh"
    }
  ]
}
```

Under `Stop`, add:
```json
{
  "matcher": "",
  "hooks": [
    {
      "type": "command",
      "command": "/home/hapax/projects/hapax-council/hooks/scripts/conductor-stop.sh"
    }
  ]
}
```

- [ ] **Step 3: Commit settings**

```bash
cd ~/.claude
git add settings.json
git commit -m "feat(conductor): wire conductor hooks into settings.json"
```

---

## Task 14: Agent Manifest

**Files:**
- Create: `agents/manifests/session_conductor.yaml`

- [ ] **Step 1: Write the manifest**

```yaml
# agents/manifests/session_conductor.yaml
id: session_conductor
name: Session Conductor
version: 1.0.0
category: governance
reports_to: operator

peers:
  - health_monitor
depends_on: []

purpose: >
  Deterministic sidecar for Claude Code sessions. Enforces workspace topology,
  caps research convergence, persists cross-session findings, automates relay
  status sync, manages epic pipelines, standardizes smoke tests, and coordinates
  parent-child session spawning/reunion.

inputs:
  - Claude Code hook events (PreToolUse, PostToolUse JSON via UDS)
  - ~/.config/hapax/workspace-topology.yaml
  - ~/.cache/hapax/relay/context/*.md (prior research findings)
  - ~/.cache/hapax/conductor/spawns/*.yaml (spawn manifests)
  - ~/.cache/hapax/relay/{alpha,beta}.yaml (peer status)

outputs:
  - /dev/shm/conductor-{session-id}.json (volatile session state)
  - ~/.cache/hapax/relay/{role}.yaml (relay status updates)
  - ~/.cache/hapax/relay/context/{topic}.md (persisted research findings)
  - ~/.cache/hapax/relay/convergence.log (convergence entries)
  - ~/.cache/hapax/conductor/spawns/*.yaml (spawn manifests)

capabilities:
  - focus_enforcement
  - research_convergence
  - finding_persistence
  - relay_sync
  - epic_pipeline
  - smoke_test_standardization
  - session_spawn_reunion

schedule:
  type: daemon
  systemd_unit: null  # Launched by Claude Code SessionStart hook, not systemd

model: null  # No LLM calls — fully deterministic

autonomy: full
decision_scope: >
  Rewrites Playwright workspace targeting, blocks excessive research rounds,
  injects prior research findings, updates relay status files, tracks epic
  pipeline phases, activates smoke test profiles, manages parent-child session
  coordination. All actions are deterministic and rule-based.
escalation_target: operator

axiom_bindings:
  - axiom_id: executive_function
    implications:
      - ex-cognitive-009
      - ex-routine-001
      - ex-attention-001
    role: enforcer
  - axiom_id: single_user
    implications: []
    role: subject

raci:
  - task: session_coordination
    role: responsible
  - task: research_convergence
    role: responsible
  - task: workspace_enforcement
    role: responsible

health_group: null
service_tier: 1
metrics_source: /dev/shm/conductor-{session-id}.json

cli:
  command: uv run python -m agents.session_conductor
  module: agents.session_conductor
  flags:
    - flag: start
      description: Launch conductor sidecar
      flag_type: subcommand
    - flag: --session-id
      description: Claude Code session ID
      flag_type: value
    - flag: --cc-pid
      description: Claude Code process PID
      flag_type: value
    - flag: --role
      description: Session role (alpha/beta)
      flag_type: value
      default: alpha
      choices: [alpha, beta]
    - flag: stop
      description: Stop conductor
      flag_type: subcommand
    - flag: status
      description: Print conductor state
      flag_type: subcommand
```

- [ ] **Step 2: Commit**

```bash
cd /home/hapax/projects/hapax-council
git add agents/manifests/session_conductor.yaml
git commit -m "feat(conductor): add agent manifest"
```

---

## Task 15: Integration Test & Smoke Test

**Files:**
- Create: `tests/session_conductor/test_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/session_conductor/test_integration.py
"""Integration tests — full conductor lifecycle with all rules."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest

from agents.session_conductor.protocol import ConductorServer
from agents.session_conductor.rules import RuleRegistry
from agents.session_conductor.rules.convergence import ConvergenceRule
from agents.session_conductor.rules.epic import EpicRule
from agents.session_conductor.rules.focus import FocusRule
from agents.session_conductor.rules.relay import RelayRule
from agents.session_conductor.rules.smoke import SmokeRule
from agents.session_conductor.rules.spawn import SpawnRule
from agents.session_conductor.state import SessionState
from agents.session_conductor.topology import TopologyConfig, PlaywrightConfig, SmokeTestConfig


def _build_server(tmp_path: Path) -> ConductorServer:
    topology = TopologyConfig(
        playwright=PlaywrightConfig(testing_workspace=10, screenshot_max_bytes=500_000),
        smoke_test=SmokeTestConfig(workspace=10, fullscreen=True),
    )
    state = SessionState(session_id="integ-test", pid=1, started_at=datetime(2026, 3, 27))
    registry = RuleRegistry()
    registry.register(FocusRule(topology=topology))
    registry.register(SmokeRule(topology=topology))
    registry.register(ConvergenceRule(topology=topology, context_dir=tmp_path / "context"))
    registry.register(EpicRule(topology=topology))
    registry.register(RelayRule(topology=topology, relay_dir=tmp_path / "relay", role="alpha"))
    registry.register(SpawnRule(topology=topology, spawns_dir=tmp_path / "spawns"))
    return ConductorServer(
        state=state,
        registry=registry,
        state_path=tmp_path / "state.json",
        sock_path=tmp_path / "conductor.sock",
    )


def test_playwright_always_workspace_10(tmp_path: Path):
    server = _build_server(tmp_path)
    response = server.process_event({
        "event": "pre_tool_use",
        "tool_name": "browser_navigate",
        "tool_input": {"url": "http://localhost:5173"},
        "session_id": "integ-test",
    })
    assert response["action"] == "rewrite"
    assert response["rewrite"]["workspace"] == 10


def test_research_tracked_across_rounds(tmp_path: Path):
    server = _build_server(tmp_path)

    # Round 1: 10 findings
    server.process_event({
        "event": "post_tool_use",
        "tool_name": "Agent",
        "tool_input": {
            "prompt": "research compositor effects",
            "result": "\n".join(f"- Finding {i}" for i in range(10)),
        },
        "session_id": "integ-test",
        "user_message": "research compositor effects",
    })
    assert "compositor-effects" in server.state.active_topics
    assert server.state.active_topics["compositor-effects"].rounds == 1

    # Round 2: 3 findings
    server.process_event({
        "event": "post_tool_use",
        "tool_name": "Agent",
        "tool_input": {
            "prompt": "research compositor effects deeper",
            "result": "- Finding A\n- Finding B\n- Finding C",
        },
        "session_id": "integ-test",
        "user_message": "research compositor effects",
    })
    assert server.state.active_topics["compositor-effects"].rounds == 2

    # Round 3: 1 finding (converging)
    server.process_event({
        "event": "post_tool_use",
        "tool_name": "Agent",
        "tool_input": {
            "prompt": "research compositor effects final",
            "result": "- One last finding",
        },
        "session_id": "integ-test",
        "user_message": "research compositor effects",
    })
    assert server.state.active_topics["compositor-effects"].is_converging()

    # Round 4: should be blocked
    response = server.process_event({
        "event": "pre_tool_use",
        "tool_name": "Agent",
        "tool_input": {"prompt": "research compositor effects yet again"},
        "session_id": "integ-test",
        "user_message": "research compositor effects",
    })
    assert response["action"] == "block"
    assert "CONVERGED" in response["message"]


def test_epic_pipeline_full_flow(tmp_path: Path):
    server = _build_server(tmp_path)

    # Trigger epic
    server.process_event({
        "event": "post_tool_use",
        "tool_name": "Agent",
        "tool_input": {"prompt": "research all touch points"},
        "session_id": "integ-test",
        "user_message": "research any loose ends then formal design doc",
    })
    assert server.state.epic_phase is not None


def test_smoke_activates_on_pr(tmp_path: Path):
    server = _build_server(tmp_path)

    server.process_event({
        "event": "post_tool_use",
        "tool_name": "Bash",
        "tool_input": {
            "command": "gh pr create",
            "result": "https://github.com/hapax/council/pull/400",
        },
        "session_id": "integ-test",
    })
    assert server.state.smoke_test_active is True


def test_file_edits_tracked(tmp_path: Path):
    server = _build_server(tmp_path)

    server.process_event({
        "event": "post_tool_use",
        "tool_name": "Edit",
        "tool_input": {"file_path": "/home/hapax/projects/hapax-council/agents/voice.py"},
        "session_id": "integ-test",
    })
    assert any("voice.py" in f for f in server.state.in_flight_files)


@pytest.mark.asyncio
async def test_uds_full_lifecycle(tmp_path: Path):
    server = _build_server(tmp_path)
    sock_path = tmp_path / "conductor.sock"

    task = asyncio.create_task(server.start())
    await asyncio.sleep(0.2)

    # Send a Playwright pre_tool_use
    reader, writer = await asyncio.open_unix_connection(str(sock_path))
    event = json.dumps({
        "event": "pre_tool_use",
        "tool_name": "browser_navigate",
        "tool_input": {"url": "http://localhost:5173"},
        "session_id": "integ-test",
    })
    writer.write(event.encode() + b"\n")
    await writer.drain()

    response_line = await asyncio.wait_for(reader.readline(), timeout=2.0)
    response = json.loads(response_line)
    assert response["action"] == "rewrite"
    assert response["rewrite"]["workspace"] == 10

    writer.close()
    await writer.wait_closed()
    server.shutdown()
    await task
```

- [ ] **Step 2: Run all tests**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/session_conductor/ -v`
Expected: All tests PASS (state: 11, topology: 3, rules_base: 5, focus: 4, convergence: 8, epic: 6, relay: 6, smoke: 5, spawn: 6, protocol: 6, integration: 7 = ~67 tests)

- [ ] **Step 3: Run linting**

Run: `cd /home/hapax/projects/hapax-council && uv run ruff check agents/session_conductor/ tests/session_conductor/ && uv run ruff format --check agents/session_conductor/ tests/session_conductor/`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
cd /home/hapax/projects/hapax-council
git add tests/session_conductor/test_integration.py
git commit -m "test(conductor): add integration tests for full lifecycle"
```

---

## Task 16: PR

- [ ] **Step 1: Create feature branch**

```bash
cd /home/hapax/projects/hapax-council
git checkout -b feat/session-conductor
```

- [ ] **Step 2: Push and create PR**

```bash
git push -u origin feat/session-conductor
gh pr create --title "feat: session conductor sidecar for CC automation" --body "$(cat <<'EOF'
## Summary
- Adds session conductor: a deterministic Python sidecar per Claude Code session
- 6 rules: focus enforcement, research convergence, epic pipeline, relay sync, smoke test, session spawn/reunion
- 4 hook shim scripts wired into settings.json
- Workspace topology config at ~/.config/hapax/workspace-topology.yaml
- ~67 tests covering state model, all rules, protocol server, and integration

## Motivation
91 sessions in 7 days with low coordination. Relay protocol went dormant. Same research repeated 3+ times across sessions. "Don't steal my focus" typed 9+ times. This makes all of that automatic.

## Test plan
- [ ] `uv run pytest tests/session_conductor/ -v` — all tests pass
- [ ] `uv run ruff check agents/session_conductor/` — no lint errors
- [ ] Start a new Claude Code session — conductor launches as sidecar
- [ ] Open Playwright — verify workspace 10 targeting
- [ ] Research a topic twice — verify prior findings injected
- [ ] Create a PR — verify smoke test profile activates
- [ ] Check relay status file — verify auto-updated

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Monitor CI and fix any failures**

Run: `gh pr checks` and fix issues if any arise.
