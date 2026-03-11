"""Base types for fix capabilities.

Defines the core abstractions that all capability modules implement:
Safety classification, actions, probe results, fix proposals, execution
results, and the Capability ABC.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Safety(str, Enum):
    """Safety classification for fix actions."""

    SAFE = "safe"
    DESTRUCTIVE = "destructive"


class Action(BaseModel):
    """A discrete fix action that a capability can perform."""

    name: str
    safety: Safety
    params: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class ProbeResult(BaseModel):
    """Result of gathering context about a failing check."""

    capability: str
    raw: dict[str, Any] = Field(default_factory=dict)

    def summary(self) -> str:
        """Human-readable summary of the probe result."""
        items = ", ".join(f"{k}={v}" for k, v in self.raw.items())
        return f"{self.capability}: {items}" if items else self.capability


class FixProposal(BaseModel):
    """A proposed fix action to remediate a failing check."""

    capability: str
    action_name: str
    params: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    safety: Safety = Safety.SAFE

    def is_safe(self) -> bool:
        """Return True if this proposal is classified as safe."""
        return self.safety == Safety.SAFE


class ExecutionResult(BaseModel):
    """Result of executing a fix proposal."""

    success: bool
    message: str
    output: str = ""


class Capability(ABC):
    """Abstract base for fix capability modules.

    Each capability maps to one or more health check groups and knows
    how to probe context, enumerate actions, validate proposals, and
    execute fixes.
    """

    name: str
    check_groups: set[str]

    @abstractmethod
    async def gather_context(self, check: Any) -> ProbeResult:
        """Probe the system to gather context about a failing check."""
        ...

    @abstractmethod
    def available_actions(self) -> list[Action]:
        """Return the list of actions this capability can perform."""
        ...

    @abstractmethod
    def validate(self, proposal: FixProposal) -> bool:
        """Validate that a proposal is acceptable for execution."""
        ...

    @abstractmethod
    async def execute(self, proposal: FixProposal) -> ExecutionResult:
        """Execute a validated fix proposal."""
        ...
