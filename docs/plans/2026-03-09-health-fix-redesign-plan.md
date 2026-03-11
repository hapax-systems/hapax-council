# Health Monitor Fix System Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace hardcoded remediation strings with an LLM-evaluated capability-based fix system that proposes, validates, and executes structured fixes autonomously every 15 minutes.

**Architecture:** Capability modules (docker, systemd, ollama, filesystem) each define typed actions, live probes, and execution logic. A pydantic-ai evaluator agent selects actions per failing check. Safe actions auto-execute; destructive ones notify via ntfy and drop.

**Tech Stack:** Python 3.12+, pydantic-ai 1.63.0 (output_type, result.output), LiteLLM balanced model, Pydantic models throughout, unittest.mock for tests.

**Design doc:** `docs/plans/2026-03-09-health-fix-redesign-design.md`

---

### Task 1: Base Classes

**Files:**
- Create: `shared/fix_capabilities/__init__.py`
- Create: `shared/fix_capabilities/base.py`
- Test: `tests/test_fix_capabilities_base.py`

**Step 1: Write the failing tests**

```python
"""Tests for fix_capabilities base classes."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from shared.fix_capabilities.base import (
    Safety,
    Action,
    ProbeResult,
    FixProposal,
    ExecutionResult,
    Capability,
)


class TestSafety:
    def test_values(self):
        assert Safety.SAFE == "safe"
        assert Safety.DESTRUCTIVE == "destructive"

    def test_is_safe(self):
        assert Safety.SAFE != Safety.DESTRUCTIVE


class TestAction:
    def test_create_action(self):
        a = Action(name="stop_model", safety=Safety.SAFE, params={"model_name": "deepseek-r1:14b"})
        assert a.name == "stop_model"
        assert a.safety == Safety.SAFE
        assert a.params == {"model_name": "deepseek-r1:14b"}

    def test_action_defaults(self):
        a = Action(name="prune", safety=Safety.SAFE)
        assert a.params == {}


class TestProbeResult:
    def test_create_probe(self):
        p = ProbeResult(capability="ollama", raw={"models": []})
        assert p.capability == "ollama"
        assert p.raw == {"models": []}

    def test_summary(self):
        p = ProbeResult(capability="docker", raw={"containers": ["a", "b"]})
        assert "docker" in p.summary()


class TestFixProposal:
    def test_create_proposal(self):
        fp = FixProposal(
            capability="ollama",
            action_name="stop_model",
            params={"model_name": "deepseek-r1:14b"},
            rationale="Model is using 8GB VRAM and is idle",
            safety=Safety.SAFE,
        )
        assert fp.capability == "ollama"
        assert fp.action_name == "stop_model"
        assert fp.safety == Safety.SAFE

    def test_is_safe(self):
        fp = FixProposal(
            capability="docker", action_name="restart", params={},
            rationale="test", safety=Safety.SAFE,
        )
        assert fp.is_safe()

    def test_is_destructive(self):
        fp = FixProposal(
            capability="docker", action_name="prune", params={},
            rationale="test", safety=Safety.DESTRUCTIVE,
        )
        assert not fp.is_safe()


class TestExecutionResult:
    def test_success(self):
        er = ExecutionResult(success=True, message="Stopped model", output="OK")
        assert er.success
        assert er.message == "Stopped model"

    def test_failure(self):
        er = ExecutionResult(success=False, message="Timeout", output="")
        assert not er.success


class TestCapability:
    def test_cannot_instantiate_base(self):
        """Base Capability is abstract — requires subclass."""
        with pytest.raises(TypeError):
            Capability()

    def test_subclass_registration(self):
        """Concrete subclass must define required attributes."""
        class TestCap(Capability):
            name = "test"
            check_groups = {"test_group"}

            async def gather_context(self, check):
                return ProbeResult(capability="test", raw={})

            def available_actions(self):
                return [Action(name="do_thing", safety=Safety.SAFE)]

            def validate(self, proposal):
                return proposal.action_name == "do_thing"

            async def execute(self, proposal):
                return ExecutionResult(success=True, message="done", output="")

        cap = TestCap()
        assert cap.name == "test"
        assert "test_group" in cap.check_groups
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/user/projects/hapax-council && uv run pytest tests/test_fix_capabilities_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shared.fix_capabilities'`

**Step 3: Create the package init**

Create `shared/fix_capabilities/__init__.py`:

```python
"""Fix capabilities — structured fix evaluation and execution for health monitor."""
```

**Step 4: Write the base module**

Create `shared/fix_capabilities/base.py`:

```python
"""Base classes for the capability-based fix system.

Each capability module defines:
- Actions: typed operations with safety classification
- ProbeResult: live system state gathered when a check fails
- Capability: abstract base with gather_context, validate, execute
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Safety(str, Enum):
    SAFE = "safe"
    DESTRUCTIVE = "destructive"


class Action(BaseModel):
    """A typed operation a capability can perform."""
    name: str
    safety: Safety
    params: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class ProbeResult(BaseModel):
    """Live system state gathered by a capability's probe."""
    capability: str
    raw: dict[str, Any] = Field(default_factory=dict)

    def summary(self) -> str:
        """Human-readable summary for LLM context."""
        return f"[{self.capability}] {self.raw}"


class FixProposal(BaseModel):
    """LLM-proposed fix action."""
    capability: str
    action_name: str
    params: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    safety: Safety = Safety.SAFE

    def is_safe(self) -> bool:
        return self.safety == Safety.SAFE


class ExecutionResult(BaseModel):
    """Result of executing a fix action."""
    success: bool
    message: str
    output: str = ""


class Capability(ABC):
    """Abstract base for a fix capability module.

    Subclasses must define:
    - name: str — unique capability identifier
    - check_groups: set[str] — health check groups this capability handles
    - gather_context() — run live probe, return ProbeResult
    - available_actions() — list of Action types this capability supports
    - validate() — confirm a FixProposal is valid for this capability
    - execute() — run the proposed fix, return ExecutionResult
    """
    name: str
    check_groups: set[str]

    @abstractmethod
    async def gather_context(self, check: Any) -> ProbeResult:
        ...

    @abstractmethod
    def available_actions(self) -> list[Action]:
        ...

    @abstractmethod
    def validate(self, proposal: FixProposal) -> bool:
        ...

    @abstractmethod
    async def execute(self, proposal: FixProposal) -> ExecutionResult:
        ...
```

**Step 5: Run tests to verify they pass**

Run: `cd /home/user/projects/hapax-council && uv run pytest tests/test_fix_capabilities_base.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add shared/fix_capabilities/__init__.py shared/fix_capabilities/base.py tests/test_fix_capabilities_base.py
git commit -m "feat: add fix capability base classes and tests"
```

---

### Task 2: Capability Registry

**Files:**
- Modify: `shared/fix_capabilities/__init__.py`
- Test: `tests/test_fix_capabilities_registry.py`

**Step 1: Write the failing tests**

```python
"""Tests for fix capability registry."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from shared.fix_capabilities.base import (
    Action,
    Capability,
    ExecutionResult,
    FixProposal,
    ProbeResult,
    Safety,
)
from shared.fix_capabilities import (
    register_capability,
    get_capability_for_group,
    get_all_capabilities,
    _REGISTRY,
)


class _FakeCap(Capability):
    name = "fake"
    check_groups = {"fake_group", "other_group"}

    async def gather_context(self, check):
        return ProbeResult(capability="fake", raw={})

    def available_actions(self):
        return [Action(name="do_thing", safety=Safety.SAFE)]

    def validate(self, proposal):
        return True

    async def execute(self, proposal):
        return ExecutionResult(success=True, message="ok", output="")


class TestRegistry:
    def setup_method(self):
        _REGISTRY.clear()

    def test_register_capability(self):
        cap = _FakeCap()
        register_capability(cap)
        assert "fake" in _REGISTRY

    def test_get_capability_for_group(self):
        cap = _FakeCap()
        register_capability(cap)
        assert get_capability_for_group("fake_group") is cap
        assert get_capability_for_group("other_group") is cap

    def test_get_capability_for_unknown_group(self):
        assert get_capability_for_group("nonexistent") is None

    def test_get_all_capabilities(self):
        cap = _FakeCap()
        register_capability(cap)
        all_caps = get_all_capabilities()
        assert len(all_caps) == 1
        assert all_caps[0] is cap

    def test_duplicate_registration_overwrites(self):
        cap1 = _FakeCap()
        cap2 = _FakeCap()
        register_capability(cap1)
        register_capability(cap2)
        assert get_capability_for_group("fake_group") is cap2
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/user/projects/hapax-council && uv run pytest tests/test_fix_capabilities_registry.py -v`
Expected: FAIL — `ImportError: cannot import name 'register_capability'`

**Step 3: Implement the registry**

Modify `shared/fix_capabilities/__init__.py`:

```python
"""Fix capabilities — structured fix evaluation and execution for health monitor.

Registry maps health check groups to capability modules. Use register_capability()
to register a capability, get_capability_for_group() to look up by check group.
"""
from __future__ import annotations

from shared.fix_capabilities.base import Capability

# group_name → Capability instance
_REGISTRY: dict[str, Capability] = {}


def register_capability(cap: Capability) -> None:
    """Register a capability, mapping all its check_groups."""
    for group in cap.check_groups:
        _REGISTRY[group] = cap


def get_capability_for_group(group: str) -> Capability | None:
    """Look up the capability that handles a given check group."""
    return _REGISTRY.get(group)


def get_all_capabilities() -> list[Capability]:
    """Return all unique registered capabilities."""
    seen: set[str] = set()
    result: list[Capability] = []
    for cap in _REGISTRY.values():
        if cap.name not in seen:
            seen.add(cap.name)
            result.append(cap)
    return result
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/user/projects/hapax-council && uv run pytest tests/test_fix_capabilities_registry.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add shared/fix_capabilities/__init__.py tests/test_fix_capabilities_registry.py
git commit -m "feat: add capability registry with group-based lookup"
```

---

### Task 3: Ollama Capability Module

**Files:**
- Create: `shared/fix_capabilities/ollama_cap.py`
- Test: `tests/test_fix_cap_ollama.py`

**Step 1: Write the failing tests**

```python
"""Tests for Ollama fix capability."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from agents.health_monitor import CheckResult, Status
from shared.fix_capabilities.base import (
    ExecutionResult,
    FixProposal,
    Safety,
)
from shared.fix_capabilities.ollama_cap import OllamaCapability


@pytest.fixture
def cap():
    return OllamaCapability()


@pytest.fixture
def vram_check():
    return CheckResult(
        name="gpu.vram", group="gpu", status=Status.FAILED,
        message="22000MiB / 24576MiB (90% used, 2576MiB free)",
        detail="Loaded Ollama models: deepseek-r1:14b, nomic-embed-text",
    )


class TestOllamaCapabilityMetadata:
    def test_name(self, cap):
        assert cap.name == "ollama"

    def test_check_groups(self, cap):
        assert "gpu" in cap.check_groups


class TestOllamaProbe:
    @pytest.mark.asyncio
    async def test_gather_context_success(self, cap, vram_check):
        mock_response = json.dumps({
            "models": [
                {"name": "deepseek-r1:14b", "size": 8_000_000_000, "details": {"parameter_size": "14B"}},
                {"name": "nomic-embed-text", "size": 500_000_000, "details": {"parameter_size": "137M"}},
            ]
        })
        with patch("shared.fix_capabilities.ollama_cap.http_get", new_callable=AsyncMock) as mock_http:
            mock_http.return_value = (200, mock_response)
            probe = await cap.gather_context(vram_check)

        assert probe.capability == "ollama"
        assert len(probe.raw["models"]) == 2
        assert probe.raw["models"][0]["name"] == "deepseek-r1:14b"

    @pytest.mark.asyncio
    async def test_gather_context_ollama_unreachable(self, cap, vram_check):
        with patch("shared.fix_capabilities.ollama_cap.http_get", new_callable=AsyncMock) as mock_http:
            mock_http.return_value = (0, "Connection refused")
            probe = await cap.gather_context(vram_check)

        assert probe.capability == "ollama"
        assert probe.raw["models"] == []
        assert "unreachable" in probe.raw.get("error", "").lower()


class TestOllamaActions:
    def test_available_actions(self, cap):
        actions = cap.available_actions()
        names = {a.name for a in actions}
        assert "stop_model" in names
        # stop_model should be SAFE
        stop = next(a for a in actions if a.name == "stop_model")
        assert stop.safety == Safety.SAFE

    def test_validate_stop_model(self, cap):
        proposal = FixProposal(
            capability="ollama", action_name="stop_model",
            params={"model_name": "deepseek-r1:14b"},
            rationale="test", safety=Safety.SAFE,
        )
        assert cap.validate(proposal)

    def test_validate_unknown_action(self, cap):
        proposal = FixProposal(
            capability="ollama", action_name="delete_everything",
            params={}, rationale="test", safety=Safety.SAFE,
        )
        assert not cap.validate(proposal)

    def test_validate_stop_model_missing_param(self, cap):
        proposal = FixProposal(
            capability="ollama", action_name="stop_model",
            params={}, rationale="test", safety=Safety.SAFE,
        )
        assert not cap.validate(proposal)


class TestOllamaExecute:
    @pytest.mark.asyncio
    async def test_execute_stop_model(self, cap):
        proposal = FixProposal(
            capability="ollama", action_name="stop_model",
            params={"model_name": "deepseek-r1:14b"},
            rationale="test", safety=Safety.SAFE,
        )
        with patch("shared.fix_capabilities.ollama_cap.run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, "success", "")
            result = await cap.execute(proposal)

        assert result.success
        mock_cmd.assert_called_once()
        cmd = mock_cmd.call_args[0][0]
        assert "ollama" in cmd
        assert "stop" in cmd
        assert "deepseek-r1:14b" in cmd

    @pytest.mark.asyncio
    async def test_execute_stop_model_failure(self, cap):
        proposal = FixProposal(
            capability="ollama", action_name="stop_model",
            params={"model_name": "deepseek-r1:14b"},
            rationale="test", safety=Safety.SAFE,
        )
        with patch("shared.fix_capabilities.ollama_cap.run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (1, "", "model not found")
            result = await cap.execute(proposal)

        assert not result.success
        assert "model not found" in result.message
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/user/projects/hapax-council && uv run pytest tests/test_fix_cap_ollama.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shared.fix_capabilities.ollama_cap'`

**Step 3: Implement the Ollama capability**

Create `shared/fix_capabilities/ollama_cap.py`:

```python
"""Ollama fix capability — manage loaded models and VRAM usage.

Handles gpu check group. Probes Ollama API for loaded models.
Actions: stop_model (safe).
"""
from __future__ import annotations

import json
import logging

from agents.health_monitor import CheckResult, run_cmd, http_get
from shared.fix_capabilities.base import (
    Action,
    Capability,
    ExecutionResult,
    FixProposal,
    ProbeResult,
    Safety,
)

log = logging.getLogger(__name__)

_ACTIONS = {
    "stop_model": Action(
        name="stop_model",
        safety=Safety.SAFE,
        description="Unload a model from Ollama to free VRAM",
    ),
}


class OllamaCapability(Capability):
    name = "ollama"
    check_groups = {"gpu"}

    async def gather_context(self, check: CheckResult) -> ProbeResult:
        """Query Ollama API for currently loaded models."""
        try:
            code, body = await http_get("http://localhost:11434/api/ps", timeout=3.0)
            if code == 200:
                data = json.loads(body)
                models = data.get("models", [])
                return ProbeResult(
                    capability="ollama",
                    raw={
                        "models": [
                            {
                                "name": m.get("name", "?"),
                                "size": m.get("size", 0),
                                "details": m.get("details", {}),
                            }
                            for m in models
                        ],
                    },
                )
        except Exception as e:
            log.warning("Ollama probe failed: %s", e)

        return ProbeResult(
            capability="ollama",
            raw={"models": [], "error": "Ollama unreachable"},
        )

    def available_actions(self) -> list[Action]:
        return list(_ACTIONS.values())

    def validate(self, proposal: FixProposal) -> bool:
        if proposal.action_name not in _ACTIONS:
            return False
        if proposal.action_name == "stop_model":
            return bool(proposal.params.get("model_name"))
        return True

    async def execute(self, proposal: FixProposal) -> ExecutionResult:
        if proposal.action_name == "stop_model":
            model = proposal.params["model_name"]
            rc, out, err = await run_cmd(
                ["docker", "exec", "ollama", "ollama", "stop", model],
                timeout=30.0,
            )
            if rc == 0:
                return ExecutionResult(
                    success=True,
                    message=f"Stopped model {model}",
                    output=out,
                )
            return ExecutionResult(
                success=False,
                message=err or out or f"Failed to stop {model} (rc={rc})",
                output=out,
            )

        return ExecutionResult(
            success=False,
            message=f"Unknown action: {proposal.action_name}",
            output="",
        )
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/user/projects/hapax-council && uv run pytest tests/test_fix_cap_ollama.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add shared/fix_capabilities/ollama_cap.py tests/test_fix_cap_ollama.py
git commit -m "feat: add Ollama fix capability with stop_model action"
```

---

### Task 4: Docker Capability Module

**Files:**
- Create: `shared/fix_capabilities/docker_cap.py`
- Test: `tests/test_fix_cap_docker.py`

**Step 1: Write the failing tests**

```python
"""Tests for Docker fix capability."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from agents.health_monitor import CheckResult, Status
from shared.fix_capabilities.base import (
    ExecutionResult,
    FixProposal,
    Safety,
)
from shared.fix_capabilities.docker_cap import DockerCapability


@pytest.fixture
def cap():
    return DockerCapability()


@pytest.fixture
def container_check():
    return CheckResult(
        name="docker.containers", group="docker", status=Status.FAILED,
        message="Container qdrant is not running",
    )


class TestDockerCapabilityMetadata:
    def test_name(self, cap):
        assert cap.name == "docker"

    def test_check_groups(self, cap):
        assert "docker" in cap.check_groups


class TestDockerProbe:
    @pytest.mark.asyncio
    async def test_gather_context_success(self, cap, container_check):
        ps_output = "qdrant|exited|2h ago\nollama|running|3d\npostgres|running|3d"
        with patch("shared.fix_capabilities.docker_cap.run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, ps_output, "")
            probe = await cap.gather_context(container_check)

        assert probe.capability == "docker"
        assert len(probe.raw["containers"]) == 3

    @pytest.mark.asyncio
    async def test_gather_context_docker_unavailable(self, cap, container_check):
        with patch("shared.fix_capabilities.docker_cap.run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (1, "", "Cannot connect to Docker daemon")
            probe = await cap.gather_context(container_check)

        assert probe.raw["containers"] == []
        assert "error" in probe.raw


class TestDockerActions:
    def test_available_actions(self, cap):
        actions = cap.available_actions()
        names = {a.name for a in actions}
        assert "restart_container" in names
        assert "start_container" in names

    def test_validate_restart_container(self, cap):
        proposal = FixProposal(
            capability="docker", action_name="restart_container",
            params={"container_name": "qdrant"},
            rationale="test", safety=Safety.SAFE,
        )
        assert cap.validate(proposal)

    def test_validate_missing_container_name(self, cap):
        proposal = FixProposal(
            capability="docker", action_name="restart_container",
            params={}, rationale="test", safety=Safety.SAFE,
        )
        assert not cap.validate(proposal)

    def test_validate_unknown_action(self, cap):
        proposal = FixProposal(
            capability="docker", action_name="rm_all",
            params={}, rationale="test", safety=Safety.SAFE,
        )
        assert not cap.validate(proposal)


class TestDockerExecute:
    @pytest.mark.asyncio
    async def test_execute_restart(self, cap):
        proposal = FixProposal(
            capability="docker", action_name="restart_container",
            params={"container_name": "qdrant"},
            rationale="test", safety=Safety.SAFE,
        )
        with patch("shared.fix_capabilities.docker_cap.run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, "qdrant", "")
            result = await cap.execute(proposal)

        assert result.success
        cmd = mock_cmd.call_args[0][0]
        assert "restart" in cmd
        assert "qdrant" in cmd

    @pytest.mark.asyncio
    async def test_execute_start(self, cap):
        proposal = FixProposal(
            capability="docker", action_name="start_container",
            params={"container_name": "ollama"},
            rationale="test", safety=Safety.SAFE,
        )
        with patch("shared.fix_capabilities.docker_cap.run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, "ollama", "")
            result = await cap.execute(proposal)

        assert result.success
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/user/projects/hapax-council && uv run pytest tests/test_fix_cap_docker.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement the Docker capability**

Create `shared/fix_capabilities/docker_cap.py`:

```python
"""Docker fix capability — manage containers.

Handles docker check group. Probes container status via docker ps.
Actions: restart_container (safe), start_container (safe).
"""
from __future__ import annotations

import logging

from agents.health_monitor import CheckResult, run_cmd
from shared.fix_capabilities.base import (
    Action,
    Capability,
    ExecutionResult,
    FixProposal,
    ProbeResult,
    Safety,
)

log = logging.getLogger(__name__)

_ACTIONS = {
    "restart_container": Action(
        name="restart_container",
        safety=Safety.SAFE,
        description="Restart a Docker container",
    ),
    "start_container": Action(
        name="start_container",
        safety=Safety.SAFE,
        description="Start a stopped Docker container",
    ),
}


class DockerCapability(Capability):
    name = "docker"
    check_groups = {"docker"}

    async def gather_context(self, check: CheckResult) -> ProbeResult:
        """List all containers with status."""
        rc, out, err = await run_cmd(
            ["docker", "ps", "-a", "--format", "{{.Names}}|{{.Status}}|{{.RunningFor}}"],
            timeout=10.0,
        )
        if rc != 0:
            return ProbeResult(
                capability="docker",
                raw={"containers": [], "error": err or "Docker unavailable"},
            )

        containers = []
        for line in out.strip().splitlines():
            parts = line.split("|", 2)
            if len(parts) >= 2:
                containers.append({
                    "name": parts[0],
                    "status": parts[1],
                    "running_for": parts[2] if len(parts) > 2 else "",
                })

        return ProbeResult(capability="docker", raw={"containers": containers})

    def available_actions(self) -> list[Action]:
        return list(_ACTIONS.values())

    def validate(self, proposal: FixProposal) -> bool:
        if proposal.action_name not in _ACTIONS:
            return False
        return bool(proposal.params.get("container_name"))

    async def execute(self, proposal: FixProposal) -> ExecutionResult:
        container = proposal.params["container_name"]

        if proposal.action_name == "restart_container":
            cmd = ["docker", "restart", container]
        elif proposal.action_name == "start_container":
            cmd = ["docker", "start", container]
        else:
            return ExecutionResult(success=False, message=f"Unknown action: {proposal.action_name}", output="")

        rc, out, err = await run_cmd(cmd, timeout=30.0)
        if rc == 0:
            return ExecutionResult(success=True, message=f"{proposal.action_name}: {container}", output=out)
        return ExecutionResult(success=False, message=err or out or f"Failed (rc={rc})", output=out)
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/user/projects/hapax-council && uv run pytest tests/test_fix_cap_docker.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add shared/fix_capabilities/docker_cap.py tests/test_fix_cap_docker.py
git commit -m "feat: add Docker fix capability with restart/start actions"
```

---

### Task 5: Systemd Capability Module

**Files:**
- Create: `shared/fix_capabilities/systemd_cap.py`
- Test: `tests/test_fix_cap_systemd.py`

**Step 1: Write the failing tests**

```python
"""Tests for systemd fix capability."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.health_monitor import CheckResult, Status
from shared.fix_capabilities.base import (
    FixProposal,
    Safety,
)
from shared.fix_capabilities.systemd_cap import SystemdCapability


@pytest.fixture
def cap():
    return SystemdCapability()


@pytest.fixture
def timer_check():
    return CheckResult(
        name="systemd.health-monitor", group="systemd", status=Status.FAILED,
        message="Timer health-monitor.timer is not active",
    )


class TestSystemdCapabilityMetadata:
    def test_name(self, cap):
        assert cap.name == "systemd"

    def test_check_groups(self, cap):
        assert "systemd" in cap.check_groups


class TestSystemdProbe:
    @pytest.mark.asyncio
    async def test_gather_context(self, cap, timer_check):
        unit_output = "health-monitor.timer loaded inactive dead"
        with patch("shared.fix_capabilities.systemd_cap.run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, unit_output, "")
            probe = await cap.gather_context(timer_check)

        assert probe.capability == "systemd"
        assert "units" in probe.raw


class TestSystemdActions:
    def test_available_actions(self, cap):
        actions = cap.available_actions()
        names = {a.name for a in actions}
        assert "restart_unit" in names
        assert "reset_failed" in names

    def test_validate_restart_unit(self, cap):
        proposal = FixProposal(
            capability="systemd", action_name="restart_unit",
            params={"unit_name": "health-monitor.timer"},
            rationale="test", safety=Safety.SAFE,
        )
        assert cap.validate(proposal)

    def test_validate_missing_unit_name(self, cap):
        proposal = FixProposal(
            capability="systemd", action_name="restart_unit",
            params={}, rationale="test", safety=Safety.SAFE,
        )
        assert not cap.validate(proposal)


class TestSystemdExecute:
    @pytest.mark.asyncio
    async def test_execute_restart_unit(self, cap):
        proposal = FixProposal(
            capability="systemd", action_name="restart_unit",
            params={"unit_name": "health-monitor.timer"},
            rationale="test", safety=Safety.SAFE,
        )
        with patch("shared.fix_capabilities.systemd_cap.run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            result = await cap.execute(proposal)

        assert result.success
        cmd = mock_cmd.call_args[0][0]
        assert "restart" in cmd

    @pytest.mark.asyncio
    async def test_execute_reset_failed(self, cap):
        proposal = FixProposal(
            capability="systemd", action_name="reset_failed",
            params={"unit_name": "health-monitor.service"},
            rationale="test", safety=Safety.SAFE,
        )
        with patch("shared.fix_capabilities.systemd_cap.run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            result = await cap.execute(proposal)

        assert result.success
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/user/projects/hapax-council && uv run pytest tests/test_fix_cap_systemd.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement the systemd capability**

Create `shared/fix_capabilities/systemd_cap.py`:

```python
"""Systemd fix capability — manage user units and timers.

Handles systemd check group. Probes unit status via systemctl --user.
Actions: restart_unit (safe), reset_failed (safe).
"""
from __future__ import annotations

import logging

from agents.health_monitor import CheckResult, run_cmd
from shared.fix_capabilities.base import (
    Action,
    Capability,
    ExecutionResult,
    FixProposal,
    ProbeResult,
    Safety,
)

log = logging.getLogger(__name__)

_ACTIONS = {
    "restart_unit": Action(
        name="restart_unit",
        safety=Safety.SAFE,
        description="Restart a systemd user unit",
    ),
    "reset_failed": Action(
        name="reset_failed",
        safety=Safety.SAFE,
        description="Reset failed state for a systemd user unit",
    ),
}


class SystemdCapability(Capability):
    name = "systemd"
    check_groups = {"systemd"}

    async def gather_context(self, check: CheckResult) -> ProbeResult:
        """List user unit status for relevant units."""
        rc, out, err = await run_cmd(
            ["systemctl", "--user", "list-units", "--type=timer,service",
             "--all", "--no-pager", "--plain", "--no-legend"],
            timeout=10.0,
        )
        if rc != 0:
            return ProbeResult(
                capability="systemd",
                raw={"units": [], "error": err or "systemctl unavailable"},
            )

        units = []
        for line in out.strip().splitlines():
            parts = line.split(None, 4)
            if len(parts) >= 3:
                units.append({
                    "unit": parts[0],
                    "load": parts[1] if len(parts) > 1 else "",
                    "active": parts[2] if len(parts) > 2 else "",
                    "sub": parts[3] if len(parts) > 3 else "",
                })

        return ProbeResult(capability="systemd", raw={"units": units})

    def available_actions(self) -> list[Action]:
        return list(_ACTIONS.values())

    def validate(self, proposal: FixProposal) -> bool:
        if proposal.action_name not in _ACTIONS:
            return False
        return bool(proposal.params.get("unit_name"))

    async def execute(self, proposal: FixProposal) -> ExecutionResult:
        unit = proposal.params["unit_name"]

        if proposal.action_name == "restart_unit":
            cmd = ["systemctl", "--user", "restart", unit]
        elif proposal.action_name == "reset_failed":
            cmd = ["systemctl", "--user", "reset-failed", unit]
        else:
            return ExecutionResult(success=False, message=f"Unknown action: {proposal.action_name}", output="")

        rc, out, err = await run_cmd(cmd, timeout=15.0)
        if rc == 0:
            return ExecutionResult(success=True, message=f"{proposal.action_name}: {unit}", output=out)
        return ExecutionResult(success=False, message=err or out or f"Failed (rc={rc})", output=out)
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/user/projects/hapax-council && uv run pytest tests/test_fix_cap_systemd.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add shared/fix_capabilities/systemd_cap.py tests/test_fix_cap_systemd.py
git commit -m "feat: add systemd fix capability with restart/reset-failed actions"
```

---

### Task 6: Filesystem Capability Module

**Files:**
- Create: `shared/fix_capabilities/filesystem_cap.py`
- Test: `tests/test_fix_cap_filesystem.py`

**Step 1: Write the failing tests**

```python
"""Tests for filesystem fix capability."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.health_monitor import CheckResult, Status
from shared.fix_capabilities.base import (
    FixProposal,
    Safety,
)
from shared.fix_capabilities.filesystem_cap import FilesystemCapability


@pytest.fixture
def cap():
    return FilesystemCapability()


@pytest.fixture
def disk_check():
    return CheckResult(
        name="disk.space", group="disk", status=Status.DEGRADED,
        message="Disk usage at 92%",
    )


class TestFilesystemCapabilityMetadata:
    def test_name(self, cap):
        assert cap.name == "filesystem"

    def test_check_groups(self, cap):
        assert "disk" in cap.check_groups


class TestFilesystemProbe:
    @pytest.mark.asyncio
    async def test_gather_context(self, cap, disk_check):
        df_output = "/dev/sda1 500G 460G 40G 92% /"
        with patch("shared.fix_capabilities.filesystem_cap.run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, df_output, "")
            probe = await cap.gather_context(disk_check)

        assert probe.capability == "filesystem"
        assert "disk" in probe.raw


class TestFilesystemActions:
    def test_available_actions(self, cap):
        actions = cap.available_actions()
        names = {a.name for a in actions}
        assert "prune_docker" in names
        assert "clear_cache_dir" in names

    def test_validate_prune_docker(self, cap):
        proposal = FixProposal(
            capability="filesystem", action_name="prune_docker",
            params={}, rationale="test", safety=Safety.DESTRUCTIVE,
        )
        assert cap.validate(proposal)

    def test_validate_clear_cache_dir(self, cap):
        proposal = FixProposal(
            capability="filesystem", action_name="clear_cache_dir",
            params={"dir_path": "/tmp/cache"},
            rationale="test", safety=Safety.DESTRUCTIVE,
        )
        assert cap.validate(proposal)

    def test_validate_clear_cache_missing_path(self, cap):
        proposal = FixProposal(
            capability="filesystem", action_name="clear_cache_dir",
            params={}, rationale="test", safety=Safety.DESTRUCTIVE,
        )
        assert not cap.validate(proposal)


class TestFilesystemExecute:
    @pytest.mark.asyncio
    async def test_execute_prune_docker(self, cap):
        proposal = FixProposal(
            capability="filesystem", action_name="prune_docker",
            params={}, rationale="test", safety=Safety.DESTRUCTIVE,
        )
        with patch("shared.fix_capabilities.filesystem_cap.run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, "Deleted 2.3GB", "")
            result = await cap.execute(proposal)

        assert result.success
        cmd = mock_cmd.call_args[0][0]
        assert "docker" in cmd
        assert "prune" in cmd
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/user/projects/hapax-council && uv run pytest tests/test_fix_cap_filesystem.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement the filesystem capability**

Create `shared/fix_capabilities/filesystem_cap.py`:

```python
"""Filesystem fix capability — manage disk space.

Handles disk check group. Probes disk usage via df.
Actions: prune_docker (destructive), clear_cache_dir (destructive).
"""
from __future__ import annotations

import logging

from agents.health_monitor import CheckResult, run_cmd
from shared.fix_capabilities.base import (
    Action,
    Capability,
    ExecutionResult,
    FixProposal,
    ProbeResult,
    Safety,
)

log = logging.getLogger(__name__)

# Allowlisted cache directories that are safe to clear
_SAFE_CACHE_DIRS = frozenset({
    "/tmp/cache",
    "/home/user/.cache/uv",
    "/home/user/.cache/pip",
})

_ACTIONS = {
    "prune_docker": Action(
        name="prune_docker",
        safety=Safety.DESTRUCTIVE,
        description="Remove unused Docker images, containers, and build cache",
    ),
    "clear_cache_dir": Action(
        name="clear_cache_dir",
        safety=Safety.DESTRUCTIVE,
        description="Clear contents of an allowlisted cache directory",
    ),
}


class FilesystemCapability(Capability):
    name = "filesystem"
    check_groups = {"disk"}

    async def gather_context(self, check: CheckResult) -> ProbeResult:
        """Get disk usage information."""
        rc, out, err = await run_cmd(
            ["df", "-h", "--output=source,size,used,avail,pcent,target", "/"],
            timeout=5.0,
        )
        if rc != 0:
            return ProbeResult(
                capability="filesystem",
                raw={"disk": [], "error": err or "df unavailable"},
            )

        return ProbeResult(capability="filesystem", raw={"disk": out})

    def available_actions(self) -> list[Action]:
        return list(_ACTIONS.values())

    def validate(self, proposal: FixProposal) -> bool:
        if proposal.action_name not in _ACTIONS:
            return False
        if proposal.action_name == "clear_cache_dir":
            dir_path = proposal.params.get("dir_path", "")
            return bool(dir_path) and dir_path in _SAFE_CACHE_DIRS
        return True

    async def execute(self, proposal: FixProposal) -> ExecutionResult:
        if proposal.action_name == "prune_docker":
            rc, out, err = await run_cmd(
                ["docker", "system", "prune", "-f", "--volumes"],
                timeout=60.0,
            )
            if rc == 0:
                return ExecutionResult(success=True, message="Docker pruned", output=out)
            return ExecutionResult(success=False, message=err or out, output=out)

        if proposal.action_name == "clear_cache_dir":
            dir_path = proposal.params["dir_path"]
            if dir_path not in _SAFE_CACHE_DIRS:
                return ExecutionResult(success=False, message=f"Not in allowlist: {dir_path}", output="")
            rc, out, err = await run_cmd(
                ["find", dir_path, "-mindepth", "1", "-delete"],
                timeout=30.0,
            )
            if rc == 0:
                return ExecutionResult(success=True, message=f"Cleared {dir_path}", output=out)
            return ExecutionResult(success=False, message=err or out, output=out)

        return ExecutionResult(success=False, message=f"Unknown action: {proposal.action_name}", output="")
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/user/projects/hapax-council && uv run pytest tests/test_fix_cap_filesystem.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add shared/fix_capabilities/filesystem_cap.py tests/test_fix_cap_filesystem.py
git commit -m "feat: add filesystem fix capability with prune/cache-clear actions"
```

---

### Task 7: LLM Evaluator Agent

**Files:**
- Create: `shared/fix_capabilities/evaluator.py`
- Test: `tests/test_fix_evaluator.py`

**Step 1: Write the failing tests**

```python
"""Tests for LLM fix evaluator agent."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.health_monitor import CheckResult, Status
from shared.fix_capabilities.base import (
    Action,
    ExecutionResult,
    FixProposal,
    ProbeResult,
    Safety,
)
from shared.fix_capabilities.evaluator import evaluate_check


@pytest.fixture
def failing_check():
    return CheckResult(
        name="gpu.vram", group="gpu", status=Status.FAILED,
        message="22000MiB / 24576MiB (90% used)",
        detail="Loaded Ollama models: deepseek-r1:14b",
        remediation="docker exec ollama ollama stop <model>",
    )


@pytest.fixture
def probe_result():
    return ProbeResult(
        capability="ollama",
        raw={"models": [{"name": "deepseek-r1:14b", "size": 8_000_000_000}]},
    )


@pytest.fixture
def actions():
    return [
        Action(name="stop_model", safety=Safety.SAFE, description="Stop an Ollama model"),
    ]


class TestEvaluateCheck:
    @pytest.mark.asyncio
    async def test_returns_fix_proposal(self, failing_check, probe_result, actions):
        mock_proposal = FixProposal(
            capability="ollama",
            action_name="stop_model",
            params={"model_name": "deepseek-r1:14b"},
            rationale="Model is idle and using 8GB VRAM",
            safety=Safety.SAFE,
        )
        mock_result = MagicMock()
        mock_result.output = mock_proposal

        with patch("shared.fix_capabilities.evaluator._evaluator_agent") as mock_agent:
            mock_agent.run = AsyncMock(return_value=mock_result)
            proposal = await evaluate_check(failing_check, probe_result, actions)

        assert proposal is not None
        assert proposal.action_name == "stop_model"
        assert proposal.params["model_name"] == "deepseek-r1:14b"

    @pytest.mark.asyncio
    async def test_returns_none_on_llm_error(self, failing_check, probe_result, actions):
        with patch("shared.fix_capabilities.evaluator._evaluator_agent") as mock_agent:
            mock_agent.run = AsyncMock(side_effect=Exception("API error"))
            proposal = await evaluate_check(failing_check, probe_result, actions)

        assert proposal is None

    @pytest.mark.asyncio
    async def test_returns_none_for_healthy_check(self, probe_result, actions):
        healthy_check = CheckResult(
            name="gpu.vram", group="gpu", status=Status.HEALTHY,
            message="All good",
        )
        proposal = await evaluate_check(healthy_check, probe_result, actions)
        assert proposal is None

    @pytest.mark.asyncio
    async def test_prompt_includes_check_context(self, failing_check, probe_result, actions):
        mock_result = MagicMock()
        mock_result.output = FixProposal(
            capability="ollama", action_name="stop_model",
            params={"model_name": "test"}, rationale="test", safety=Safety.SAFE,
        )

        with patch("shared.fix_capabilities.evaluator._evaluator_agent") as mock_agent:
            mock_agent.run = AsyncMock(return_value=mock_result)
            await evaluate_check(failing_check, probe_result, actions)

        # Verify the prompt sent to the LLM contains the check info
        call_args = mock_agent.run.call_args
        prompt = call_args[0][0]
        assert "gpu.vram" in prompt
        assert "22000MiB" in prompt
        assert "deepseek-r1:14b" in prompt
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/user/projects/hapax-council && uv run pytest tests/test_fix_evaluator.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement the evaluator**

Create `shared/fix_capabilities/evaluator.py`:

```python
"""LLM evaluator agent for health check fix proposals.

Uses pydantic-ai with the balanced model (claude-sonnet via LiteLLM).
Receives a failing CheckResult + probe context + available actions,
returns a FixProposal or None.
"""
from __future__ import annotations

import logging
from typing import Optional

from pydantic_ai import Agent

from agents.health_monitor import CheckResult, Status
from shared.config import get_model
from shared.fix_capabilities.base import (
    Action,
    FixProposal,
    ProbeResult,
    Safety,
)

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a system health fix evaluator for a single-user LLM workstation.
You receive a failing health check result, live system probe data, and a list
of available fix actions. Your job is to propose the single best fix action.

Rules:
- Pick exactly one action from the available actions list.
- Fill in the action parameters based on the probe data and check context.
- Set safety to match the action's defined safety level.
- Write a brief rationale explaining why this fix is appropriate.
- If no available action can address the problem, respond with action_name "no_action".
- Never invent actions not in the available list.
"""

_evaluator_agent = Agent(
    model=get_model("balanced"),
    output_type=FixProposal,
    system_prompt=_SYSTEM_PROMPT,
)


def _build_prompt(
    check: CheckResult,
    probe: ProbeResult,
    actions: list[Action],
) -> str:
    """Build the evaluation prompt from check context."""
    action_descriptions = "\n".join(
        f"  - {a.name} (safety: {a.safety.value}): {a.description} | params schema: {a.params}"
        for a in actions
    )

    parts = [
        f"FAILING CHECK: {check.name}",
        f"Group: {check.group}",
        f"Status: {check.status.value}",
        f"Message: {check.message}",
    ]
    if check.detail:
        parts.append(f"Detail: {check.detail}")
    if check.remediation:
        parts.append(f"Remediation hint: {check.remediation}")

    parts.append(f"\nLIVE PROBE ({probe.capability}):\n{probe.summary()}")
    parts.append(f"\nAVAILABLE ACTIONS:\n{action_descriptions}")
    parts.append(f"\nCapability: {probe.capability}")

    return "\n".join(parts)


async def evaluate_check(
    check: CheckResult,
    probe: ProbeResult,
    actions: list[Action],
) -> Optional[FixProposal]:
    """Ask the LLM to propose a fix for a failing check.

    Returns None if the check is healthy, no actions available, or LLM errors.
    """
    if check.status == Status.HEALTHY:
        return None

    if not actions:
        return None

    prompt = _build_prompt(check, probe, actions)

    try:
        result = await _evaluator_agent.run(prompt)
        proposal = result.output
        if proposal.action_name == "no_action":
            log.info("Evaluator: no action for %s", check.name)
            return None
        return proposal
    except Exception as e:
        log.warning("Fix evaluator failed for %s: %s", check.name, e)
        return None
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/user/projects/hapax-council && uv run pytest tests/test_fix_evaluator.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add shared/fix_capabilities/evaluator.py tests/test_fix_evaluator.py
git commit -m "feat: add LLM evaluator agent for fix proposals"
```

---

### Task 8: Fix Pipeline

**Files:**
- Create: `shared/fix_capabilities/pipeline.py`
- Test: `tests/test_fix_pipeline.py`

This is the orchestrator that wires check failures → capability lookup → probe → evaluate → validate → execute/notify.

**Step 1: Write the failing tests**

```python
"""Tests for fix pipeline orchestration."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.health_monitor import CheckResult, GroupResult, HealthReport, Status
from shared.fix_capabilities.base import (
    Action,
    Capability,
    ExecutionResult,
    FixProposal,
    ProbeResult,
    Safety,
)
from shared.fix_capabilities.pipeline import (
    run_fix_pipeline,
    PipelineResult,
    FixOutcome,
)


def _make_report(*checks: CheckResult) -> HealthReport:
    """Build a minimal HealthReport from check results."""
    groups: dict[str, list[CheckResult]] = {}
    for c in checks:
        groups.setdefault(c.group, []).append(c)

    group_results = []
    for gname, gchecks in groups.items():
        statuses = [c.status for c in gchecks]
        from agents.health_monitor import worst_status
        group_results.append(GroupResult(
            group=gname,
            status=worst_status(*statuses),
            checks=gchecks,
        ))

    return HealthReport(
        timestamp="2026-03-09T12:00:00Z",
        hostname="test",
        overall_status=worst_status(*(c.status for c in checks)),
        groups=group_results,
        total_checks=len(checks),
    )


class _MockCap(Capability):
    name = "mock"
    check_groups = {"gpu"}

    async def gather_context(self, check):
        return ProbeResult(capability="mock", raw={"test": True})

    def available_actions(self):
        return [Action(name="fix_it", safety=Safety.SAFE, description="Fix it")]

    def validate(self, proposal):
        return proposal.action_name == "fix_it"

    async def execute(self, proposal):
        return ExecutionResult(success=True, message="Fixed", output="ok")


class TestFixPipeline:
    @pytest.mark.asyncio
    async def test_no_failures_returns_empty(self):
        report = _make_report(
            CheckResult(name="gpu.vram", group="gpu", status=Status.HEALTHY, message="ok"),
        )
        result = await run_fix_pipeline(report, mode="apply")
        assert result.total == 0
        assert result.outcomes == []

    @pytest.mark.asyncio
    async def test_no_capability_skips_check(self):
        report = _make_report(
            CheckResult(name="unknown.check", group="unknown", status=Status.FAILED, message="bad"),
        )
        with patch("shared.fix_capabilities.pipeline.get_capability_for_group", return_value=None):
            result = await run_fix_pipeline(report, mode="apply")
        assert result.total == 0

    @pytest.mark.asyncio
    async def test_safe_proposal_executes(self):
        check = CheckResult(name="gpu.vram", group="gpu", status=Status.FAILED, message="90% used")
        report = _make_report(check)
        mock_cap = _MockCap()
        proposal = FixProposal(
            capability="mock", action_name="fix_it", params={},
            rationale="test", safety=Safety.SAFE,
        )

        with patch("shared.fix_capabilities.pipeline.get_capability_for_group", return_value=mock_cap), \
             patch("shared.fix_capabilities.pipeline.evaluate_check", new_callable=AsyncMock, return_value=proposal):
            result = await run_fix_pipeline(report, mode="apply")

        assert result.total == 1
        assert result.outcomes[0].executed
        assert result.outcomes[0].execution_result.success

    @pytest.mark.asyncio
    async def test_destructive_proposal_notifies_not_executes(self):
        check = CheckResult(name="disk.space", group="disk", status=Status.FAILED, message="95% used")
        report = _make_report(check)
        mock_cap = _MockCap()
        proposal = FixProposal(
            capability="mock", action_name="fix_it", params={},
            rationale="test", safety=Safety.DESTRUCTIVE,
        )

        with patch("shared.fix_capabilities.pipeline.get_capability_for_group", return_value=mock_cap), \
             patch("shared.fix_capabilities.pipeline.evaluate_check", new_callable=AsyncMock, return_value=proposal), \
             patch("shared.fix_capabilities.pipeline.send_notification") as mock_notify:
            result = await run_fix_pipeline(report, mode="apply")

        assert result.total == 1
        assert not result.outcomes[0].executed
        assert result.outcomes[0].notified
        mock_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_dry_run_does_not_execute(self):
        check = CheckResult(name="gpu.vram", group="gpu", status=Status.FAILED, message="90% used")
        report = _make_report(check)
        mock_cap = _MockCap()
        proposal = FixProposal(
            capability="mock", action_name="fix_it", params={},
            rationale="test", safety=Safety.SAFE,
        )

        with patch("shared.fix_capabilities.pipeline.get_capability_for_group", return_value=mock_cap), \
             patch("shared.fix_capabilities.pipeline.evaluate_check", new_callable=AsyncMock, return_value=proposal):
            result = await run_fix_pipeline(report, mode="dry_run")

        assert result.total == 1
        assert not result.outcomes[0].executed

    @pytest.mark.asyncio
    async def test_validation_failure_skips(self):
        check = CheckResult(name="gpu.vram", group="gpu", status=Status.FAILED, message="90% used")
        report = _make_report(check)
        mock_cap = _MockCap()
        # Proposal with wrong action name — will fail validate
        proposal = FixProposal(
            capability="mock", action_name="wrong_action", params={},
            rationale="test", safety=Safety.SAFE,
        )

        with patch("shared.fix_capabilities.pipeline.get_capability_for_group", return_value=mock_cap), \
             patch("shared.fix_capabilities.pipeline.evaluate_check", new_callable=AsyncMock, return_value=proposal):
            result = await run_fix_pipeline(report, mode="apply")

        assert result.total == 1
        assert not result.outcomes[0].executed
        assert result.outcomes[0].rejected_reason is not None

    @pytest.mark.asyncio
    async def test_evaluator_returns_none_skips(self):
        check = CheckResult(name="gpu.vram", group="gpu", status=Status.FAILED, message="90% used")
        report = _make_report(check)
        mock_cap = _MockCap()

        with patch("shared.fix_capabilities.pipeline.get_capability_for_group", return_value=mock_cap), \
             patch("shared.fix_capabilities.pipeline.evaluate_check", new_callable=AsyncMock, return_value=None):
            result = await run_fix_pipeline(report, mode="apply")

        assert result.total == 0
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/user/projects/hapax-council && uv run pytest tests/test_fix_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement the pipeline**

Create `shared/fix_capabilities/pipeline.py`:

```python
"""Fix pipeline — orchestrates check → probe → evaluate → validate → execute.

Modes:
- apply: auto-execute safe proposals, notify for destructive
- dry_run: evaluate only, no execution
- interactive: prompt before each execution (used by CLI --fix)
"""
from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from agents.health_monitor import CheckResult, HealthReport, Status
from shared.fix_capabilities import get_capability_for_group
from shared.fix_capabilities.base import (
    ExecutionResult,
    FixProposal,
)
from shared.fix_capabilities.evaluator import evaluate_check
from shared.notify import send_notification

log = logging.getLogger(__name__)


class FixOutcome(BaseModel):
    """Result of processing a single failing check through the pipeline."""
    check_name: str
    proposal: Optional[FixProposal] = None
    executed: bool = False
    notified: bool = False
    execution_result: Optional[ExecutionResult] = None
    rejected_reason: Optional[str] = None


class PipelineResult(BaseModel):
    """Aggregate result of the fix pipeline run."""
    total: int = 0
    outcomes: list[FixOutcome] = Field(default_factory=list)

    @property
    def executed_count(self) -> int:
        return sum(1 for o in self.outcomes if o.executed)

    @property
    def notified_count(self) -> int:
        return sum(1 for o in self.outcomes if o.notified)


async def run_fix_pipeline(
    report: HealthReport,
    *,
    mode: str = "apply",
) -> PipelineResult:
    """Run the fix pipeline for all failing checks in a health report.

    Args:
        report: Health check report with failing checks
        mode: "apply" (auto-execute safe, notify destructive),
              "dry_run" (evaluate only), or
              "interactive" (prompt per proposal)

    Returns:
        PipelineResult with outcomes for each processed check
    """
    result = PipelineResult()

    # Collect all failing checks
    failing = [
        c for gr in report.groups for c in gr.checks
        if c.status != Status.HEALTHY
    ]

    if not failing:
        return result

    for check in failing:
        cap = get_capability_for_group(check.group)
        if cap is None:
            log.debug("No capability for group %s, skipping %s", check.group, check.name)
            continue

        # Probe
        try:
            probe = await cap.gather_context(check)
        except Exception as e:
            log.warning("Probe failed for %s: %s", check.name, e)
            continue

        # Evaluate
        actions = cap.available_actions()
        proposal = await evaluate_check(check, probe, actions)
        if proposal is None:
            continue

        outcome = FixOutcome(check_name=check.name, proposal=proposal)
        result.total += 1

        # Validate
        if not cap.validate(proposal):
            outcome.rejected_reason = f"Validation failed: {proposal.action_name} with {proposal.params}"
            log.warning("Proposal rejected for %s: %s", check.name, outcome.rejected_reason)
            result.outcomes.append(outcome)
            continue

        # Execute based on mode
        if mode == "dry_run":
            result.outcomes.append(outcome)
            continue

        if proposal.is_safe():
            try:
                exec_result = await cap.execute(proposal)
                outcome.executed = True
                outcome.execution_result = exec_result
                if exec_result.success:
                    log.info("Fix applied for %s: %s", check.name, exec_result.message)
                else:
                    log.warning("Fix failed for %s: %s", check.name, exec_result.message)
            except Exception as e:
                outcome.executed = True
                outcome.execution_result = ExecutionResult(
                    success=False, message=str(e), output="",
                )
                log.warning("Fix execution error for %s: %s", check.name, e)
        else:
            # Destructive — notify and drop
            msg = (
                f"Check: {check.name}\n"
                f"Status: {check.status.value}\n"
                f"Proposed: {proposal.action_name}({proposal.params})\n"
                f"Rationale: {proposal.rationale}"
            )
            try:
                send_notification(
                    "Fix Proposal (destructive)",
                    msg,
                    priority="high",
                    tags=["warning"],
                )
                outcome.notified = True
            except Exception as e:
                log.warning("Failed to notify for %s: %s", check.name, e)

        result.outcomes.append(outcome)

    return result
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/user/projects/hapax-council && uv run pytest tests/test_fix_pipeline.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add shared/fix_capabilities/pipeline.py tests/test_fix_pipeline.py
git commit -m "feat: add fix pipeline orchestrator with apply/dry-run modes"
```

---

### Task 9: Register Capabilities on Import

**Files:**
- Modify: `shared/fix_capabilities/__init__.py`
- Test: `tests/test_fix_capabilities_registration.py`

**Step 1: Write the failing test**

```python
"""Tests for auto-registration of built-in capabilities."""
from __future__ import annotations

from shared.fix_capabilities import get_capability_for_group, load_builtin_capabilities


class TestBuiltinRegistration:
    def test_load_registers_ollama(self):
        load_builtin_capabilities()
        cap = get_capability_for_group("gpu")
        assert cap is not None
        assert cap.name == "ollama"

    def test_load_registers_docker(self):
        load_builtin_capabilities()
        cap = get_capability_for_group("docker")
        assert cap is not None
        assert cap.name == "docker"

    def test_load_registers_systemd(self):
        load_builtin_capabilities()
        cap = get_capability_for_group("systemd")
        assert cap is not None
        assert cap.name == "systemd"

    def test_load_registers_filesystem(self):
        load_builtin_capabilities()
        cap = get_capability_for_group("disk")
        assert cap is not None
        assert cap.name == "filesystem"

    def test_load_is_idempotent(self):
        load_builtin_capabilities()
        load_builtin_capabilities()
        cap = get_capability_for_group("gpu")
        assert cap is not None
```

**Step 2: Run test to verify it fails**

Run: `cd /home/user/projects/hapax-council && uv run pytest tests/test_fix_capabilities_registration.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_builtin_capabilities'`

**Step 3: Add load_builtin_capabilities to __init__**

Add to `shared/fix_capabilities/__init__.py`:

```python
def load_builtin_capabilities() -> None:
    """Register all built-in capability modules."""
    from shared.fix_capabilities.ollama_cap import OllamaCapability
    from shared.fix_capabilities.docker_cap import DockerCapability
    from shared.fix_capabilities.systemd_cap import SystemdCapability
    from shared.fix_capabilities.filesystem_cap import FilesystemCapability

    register_capability(OllamaCapability())
    register_capability(DockerCapability())
    register_capability(SystemdCapability())
    register_capability(FilesystemCapability())
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/user/projects/hapax-council && uv run pytest tests/test_fix_capabilities_registration.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add shared/fix_capabilities/__init__.py tests/test_fix_capabilities_registration.py
git commit -m "feat: add auto-registration of built-in capabilities"
```

---

### Task 10: Wire Pipeline into Health Monitor

**Files:**
- Modify: `agents/health_monitor.py` (lines 2171-2230 and 2306-2338)
- Test: `tests/test_health_monitor_pipeline.py`

**Step 1: Write the failing tests**

```python
"""Tests for health monitor pipeline integration."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from agents.health_monitor import CheckResult, GroupResult, HealthReport, Status


class TestRunFixesNewPipeline:
    """Test that --fix now uses the capability pipeline."""

    @pytest.mark.asyncio
    async def test_fix_calls_pipeline(self):
        from agents.health_monitor import run_fixes_v2
        report = HealthReport(
            timestamp="2026-03-09T12:00:00Z",
            hostname="test",
            overall_status=Status.FAILED,
            groups=[GroupResult(
                group="gpu", status=Status.FAILED,
                checks=[CheckResult(
                    name="gpu.vram", group="gpu", status=Status.FAILED,
                    message="90% used",
                )],
            )],
        )
        mock_result = MagicMock()
        mock_result.total = 1
        mock_result.executed_count = 1
        mock_result.outcomes = []

        with patch("agents.health_monitor.run_fix_pipeline", new_callable=AsyncMock, return_value=mock_result) as mock_pipe:
            count = await run_fixes_v2(report, mode="apply")

        mock_pipe.assert_called_once_with(report, mode="apply")
        assert count == 1

    @pytest.mark.asyncio
    async def test_fix_interactive_mode(self):
        from agents.health_monitor import run_fixes_v2
        report = HealthReport(
            timestamp="2026-03-09T12:00:00Z",
            hostname="test",
            overall_status=Status.HEALTHY,
            groups=[],
        )
        mock_result = MagicMock()
        mock_result.total = 0
        mock_result.executed_count = 0
        mock_result.outcomes = []

        with patch("agents.health_monitor.run_fix_pipeline", new_callable=AsyncMock, return_value=mock_result):
            count = await run_fixes_v2(report, mode="interactive")

        assert count == 0
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/user/projects/hapax-council && uv run pytest tests/test_health_monitor_pipeline.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_fixes_v2'`

**Step 3: Add `run_fixes_v2` and `--apply`/`--dry-run` flags**

Modify `agents/health_monitor.py`. Add import near the top (after existing imports):

```python
from shared.fix_capabilities import load_builtin_capabilities
from shared.fix_capabilities.pipeline import run_fix_pipeline, PipelineResult
```

Add `run_fixes_v2` function after the existing `run_fixes` function (keep `run_fixes` for backwards compat):

```python
async def run_fixes_v2(report: HealthReport, mode: str = "apply") -> int:
    """Run LLM-evaluated fix pipeline.

    Modes: apply (auto-execute safe), dry_run (evaluate only), interactive (prompt each).
    Returns count of proposals processed.
    """
    load_builtin_capabilities()
    result = await run_fix_pipeline(report, mode=mode)

    if result.total == 0:
        print("No fix proposals generated.")
        return 0

    for outcome in result.outcomes:
        if outcome.executed and outcome.execution_result:
            icon = "OK" if outcome.execution_result.success else "FAIL"
            print(f"  [{icon}] {outcome.check_name}: {outcome.execution_result.message}")
            if outcome.proposal:
                print(f"         Rationale: {outcome.proposal.rationale}")
        elif outcome.notified:
            print(f"  [HELD] {outcome.check_name}: destructive — notification sent")
            if outcome.proposal:
                print(f"         Proposed: {outcome.proposal.action_name}({outcome.proposal.params})")
        elif outcome.rejected_reason:
            print(f"  [SKIP] {outcome.check_name}: {outcome.rejected_reason}")
        elif mode == "dry_run" and outcome.proposal:
            print(f"  [DRY ] {outcome.check_name}: would run {outcome.proposal.action_name}({outcome.proposal.params})")
            print(f"         Rationale: {outcome.proposal.rationale}")

    return result.total
```

Add CLI flags in the `main()` function, after the existing `--yes` argument:

```python
    parser.add_argument(
        "--apply", action="store_true",
        help="Auto-apply safe fixes (for watchdog timer use)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Evaluate fixes but don't execute (shows what would happen)",
    )
```

Modify the fix handling in `main()` to use the new pipeline when `--apply` or `--dry-run` is given. After `report = await run_checks(groups=check_groups)` and the existing fix block, add:

```python
    if args.apply or args.dry_run:
        mode = "dry_run" if args.dry_run else "apply"
        await run_fixes_v2(report, mode=mode)
    elif args.fix:
        # Legacy interactive fix path
        await run_fixes(report, yes=args.yes)
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/user/projects/hapax-council && uv run pytest tests/test_health_monitor_pipeline.py -v`
Expected: All PASS

**Step 5: Run existing health monitor tests to verify no regressions**

Run: `cd /home/user/projects/hapax-council && uv run pytest tests/test_health_monitor.py -v`
Expected: All PASS (existing tests unaffected)

**Step 6: Commit**

```bash
git add agents/health_monitor.py tests/test_health_monitor_pipeline.py
git commit -m "feat: wire LLM fix pipeline into health monitor with --apply and --dry-run flags"
```

---

### Task 11: Simplify Health Watchdog

**Files:**
- Modify: `systemd/watchdogs/health-watchdog`

**Step 1: Simplify the watchdog script**

Replace the auto-fix section (lines 28-83 of the current script) with a simpler pipeline call. The new watchdog drops the bash-level 3-attempt backoff and `fix-attempts.json` tracking — the Python pipeline handles everything.

Replace the fix section with:

```bash
# If there are failures, run LLM-evaluated fix pipeline
REPORT2=""
if [[ "$STATUS" != "healthy" ]]; then
    $UV run python -m agents.health_monitor --apply 2>/dev/null || true

    # Re-check after fix
    REPORT2=$($UV run python -m agents.health_monitor --json 2>/dev/null) || true
    if [[ -n "$REPORT2" ]]; then
        STATUS2=$(echo "$REPORT2" | python3 -c "import sys,json; print(json.load(sys.stdin)['overall_status'])")

        if [[ "$STATUS2" == "healthy" ]]; then
            echo "$REPORT" | $UV run python -c "
import sys, json, os
from shared.notify import send_notification, nudges_uri
r = json.load(sys.stdin)
send_notification('Auto-Fixed', f\"{r['summary']} -> All healthy\nLLM-evaluated fix applied\", tags=['white_check_mark'], click_url=nudges_uri())
" 2>/dev/null || true
        fi
        STATUS="\$STATUS2"
    fi
fi
```

Remove the `FIX_STATE_DIR`, `FIX_STATE_FILE`, and `fix-attempts.json` logic entirely. Remove the healthy-case reset of fix counters.

**Step 2: Verify watchdog syntax**

Run: `bash -n systemd/watchdogs/health-watchdog`
Expected: No syntax errors

**Step 3: Commit**

```bash
git add systemd/watchdogs/health-watchdog
git commit -m "refactor: simplify health-watchdog to use LLM fix pipeline"
```

---

### Task 12: Final Integration Test

**Files:**
- Test: `tests/test_fix_integration.py`

**Step 1: Write end-to-end integration test**

```python
"""End-to-end integration test for the fix system."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.health_monitor import CheckResult, GroupResult, HealthReport, Status, worst_status
from shared.fix_capabilities import _REGISTRY, load_builtin_capabilities, get_capability_for_group
from shared.fix_capabilities.base import (
    ExecutionResult,
    FixProposal,
    ProbeResult,
    Safety,
)
from shared.fix_capabilities.pipeline import run_fix_pipeline


class TestEndToEnd:
    def setup_method(self):
        _REGISTRY.clear()
        load_builtin_capabilities()

    @pytest.mark.asyncio
    async def test_full_pipeline_gpu_fix(self):
        """Simulates: GPU check fails → Ollama probe → LLM proposes stop_model → executes."""
        check = CheckResult(
            name="gpu.vram", group="gpu", status=Status.FAILED,
            message="22000MiB / 24576MiB (90% used)",
            detail="Loaded Ollama models: deepseek-r1:14b",
        )
        report = HealthReport(
            timestamp="2026-03-09T12:00:00Z",
            hostname="test",
            overall_status=Status.FAILED,
            groups=[GroupResult(group="gpu", status=Status.FAILED, checks=[check])],
            total_checks=1,
            failed_count=1,
        )

        probe = ProbeResult(
            capability="ollama",
            raw={"models": [{"name": "deepseek-r1:14b", "size": 8_000_000_000}]},
        )
        proposal = FixProposal(
            capability="ollama",
            action_name="stop_model",
            params={"model_name": "deepseek-r1:14b"},
            rationale="Model using 8GB VRAM, stopping to free memory",
            safety=Safety.SAFE,
        )

        cap = get_capability_for_group("gpu")

        with patch.object(cap, "gather_context", new_callable=AsyncMock, return_value=probe), \
             patch("shared.fix_capabilities.pipeline.evaluate_check", new_callable=AsyncMock, return_value=proposal), \
             patch.object(cap, "execute", new_callable=AsyncMock, return_value=ExecutionResult(success=True, message="Stopped deepseek-r1:14b", output="ok")):
            result = await run_fix_pipeline(report, mode="apply")

        assert result.total == 1
        assert result.executed_count == 1
        assert result.outcomes[0].executed
        assert result.outcomes[0].execution_result.success

    @pytest.mark.asyncio
    async def test_full_pipeline_destructive_notifies(self):
        """Simulates: disk check fails → filesystem probe → LLM proposes prune → notifies."""
        check = CheckResult(
            name="disk.space", group="disk", status=Status.FAILED,
            message="95% used",
        )
        report = HealthReport(
            timestamp="2026-03-09T12:00:00Z",
            hostname="test",
            overall_status=Status.FAILED,
            groups=[GroupResult(group="disk", status=Status.FAILED, checks=[check])],
            total_checks=1,
            failed_count=1,
        )

        probe = ProbeResult(capability="filesystem", raw={"disk": "95% used"})
        proposal = FixProposal(
            capability="filesystem",
            action_name="prune_docker",
            params={},
            rationale="Disk nearly full, prune Docker to free space",
            safety=Safety.DESTRUCTIVE,
        )

        cap = get_capability_for_group("disk")

        with patch.object(cap, "gather_context", new_callable=AsyncMock, return_value=probe), \
             patch("shared.fix_capabilities.pipeline.evaluate_check", new_callable=AsyncMock, return_value=proposal), \
             patch("shared.fix_capabilities.pipeline.send_notification") as mock_notify:
            result = await run_fix_pipeline(report, mode="apply")

        assert result.total == 1
        assert result.notified_count == 1
        assert not result.outcomes[0].executed
        mock_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_capabilities_registered(self):
        """Verify all expected capabilities are registered."""
        assert get_capability_for_group("gpu") is not None
        assert get_capability_for_group("docker") is not None
        assert get_capability_for_group("systemd") is not None
        assert get_capability_for_group("disk") is not None
```

**Step 2: Run tests to verify they pass**

Run: `cd /home/user/projects/hapax-council && uv run pytest tests/test_fix_integration.py -v`
Expected: All PASS

**Step 3: Run the full test suite**

Run: `cd /home/user/projects/hapax-council && uv run pytest tests/test_fix_capabilities_base.py tests/test_fix_capabilities_registry.py tests/test_fix_cap_ollama.py tests/test_fix_cap_docker.py tests/test_fix_cap_systemd.py tests/test_fix_cap_filesystem.py tests/test_fix_evaluator.py tests/test_fix_pipeline.py tests/test_fix_capabilities_registration.py tests/test_health_monitor_pipeline.py tests/test_fix_integration.py tests/test_health_monitor.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add tests/test_fix_integration.py
git commit -m "test: add end-to-end integration tests for fix pipeline"
```

---

## Summary

| Task | Description | New Files | Test Count |
|------|-------------|-----------|------------|
| 1 | Base classes | `shared/fix_capabilities/base.py` | ~11 |
| 2 | Capability registry | `shared/fix_capabilities/__init__.py` | ~5 |
| 3 | Ollama capability | `shared/fix_capabilities/ollama_cap.py` | ~9 |
| 4 | Docker capability | `shared/fix_capabilities/docker_cap.py` | ~8 |
| 5 | Systemd capability | `shared/fix_capabilities/systemd_cap.py` | ~7 |
| 6 | Filesystem capability | `shared/fix_capabilities/filesystem_cap.py` | ~7 |
| 7 | LLM evaluator agent | `shared/fix_capabilities/evaluator.py` | ~4 |
| 8 | Fix pipeline | `shared/fix_capabilities/pipeline.py` | ~7 |
| 9 | Auto-registration | (modify __init__) | ~5 |
| 10 | Wire into health monitor | (modify health_monitor.py) | ~2 |
| 11 | Simplify watchdog | (modify health-watchdog) | 0 |
| 12 | Integration tests | `tests/test_fix_integration.py` | ~3 |
| **Total** | | **8 new modules** | **~68 tests** |
