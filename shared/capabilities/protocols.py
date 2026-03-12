"""Capability Protocols: typed interfaces for disposable service abstractions.

Each Protocol defines a single capability domain. Adapters implement one
Protocol and are registered in the CapabilityRegistry. All Protocols share
a common shape: `name`, `available()`, `health()`.

9 Protocols defined together per the design; only EmbeddingCapability and
DesktopCapability have adapters in this batch. The rest are interface-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# ------------------------------------------------------------------
# Common result types
# ------------------------------------------------------------------


@dataclass(frozen=True)
class HealthStatus:
    """Health check result for a capability adapter."""

    healthy: bool
    message: str = ""
    latency_ms: float = 0.0


# ------------------------------------------------------------------
# 1. EmbeddingCapability
# ------------------------------------------------------------------


@dataclass(frozen=True)
class EmbeddingResult:
    """Result of an embedding operation."""

    vector: list[float]
    model: str
    dimensions: int


@runtime_checkable
class EmbeddingCapability(Protocol):
    @property
    def name(self) -> str: ...
    def available(self) -> bool: ...
    def health(self) -> HealthStatus: ...
    def embed(self, text: str) -> EmbeddingResult: ...


# ------------------------------------------------------------------
# 2. DesktopCapability
# ------------------------------------------------------------------


@dataclass(frozen=True)
class DesktopResult:
    """Snapshot of desktop state."""

    active_window_title: str = ""
    active_window_class: str = ""
    workspace_id: int = 0
    window_count: int = 0


@runtime_checkable
class DesktopCapability(Protocol):
    @property
    def name(self) -> str: ...
    def available(self) -> bool: ...
    def health(self) -> HealthStatus: ...
    def snapshot(self) -> DesktopResult: ...


# ------------------------------------------------------------------
# 3. CompletionCapability
# ------------------------------------------------------------------


@dataclass(frozen=True)
class CompletionResult:
    """Result of an LLM completion."""

    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


@runtime_checkable
class CompletionCapability(Protocol):
    @property
    def name(self) -> str: ...
    def available(self) -> bool: ...
    def health(self) -> HealthStatus: ...
    async def complete(self, prompt: str, *, model: str = "") -> CompletionResult: ...


# ------------------------------------------------------------------
# 4. VectorSearchCapability
# ------------------------------------------------------------------


@dataclass(frozen=True)
class SearchHit:
    """Single vector search result."""

    id: str
    score: float
    payload: dict


@runtime_checkable
class VectorSearchCapability(Protocol):
    @property
    def name(self) -> str: ...
    def available(self) -> bool: ...
    def health(self) -> HealthStatus: ...
    def search(self, collection: str, vector: list[float], *, limit: int = 5) -> list[SearchHit]: ...


# ------------------------------------------------------------------
# 5. NotificationCapability
# ------------------------------------------------------------------


@runtime_checkable
class NotificationCapability(Protocol):
    @property
    def name(self) -> str: ...
    def available(self) -> bool: ...
    def health(self) -> HealthStatus: ...
    def notify(self, title: str, message: str, *, priority: str = "default") -> bool: ...


# ------------------------------------------------------------------
# 6. AudioCapability
# ------------------------------------------------------------------


@dataclass(frozen=True)
class AudioState:
    """Current audio system state."""

    default_sink: str = ""
    default_source: str = ""
    sink_volume: float = 0.0
    source_muted: bool = False


@runtime_checkable
class AudioCapability(Protocol):
    @property
    def name(self) -> str: ...
    def available(self) -> bool: ...
    def health(self) -> HealthStatus: ...
    def state(self) -> AudioState: ...


# ------------------------------------------------------------------
# 7. TranscriptionCapability
# ------------------------------------------------------------------


@dataclass(frozen=True)
class TranscriptionResult:
    """Result of an audio transcription."""

    text: str
    language: str = ""
    confidence: float = 0.0


@runtime_checkable
class TranscriptionCapability(Protocol):
    @property
    def name(self) -> str: ...
    def available(self) -> bool: ...
    def health(self) -> HealthStatus: ...
    def transcribe(self, audio_path: str) -> TranscriptionResult: ...


# ------------------------------------------------------------------
# 8. TTSCapability
# ------------------------------------------------------------------


@runtime_checkable
class TTSCapability(Protocol):
    @property
    def name(self) -> str: ...
    def available(self) -> bool: ...
    def health(self) -> HealthStatus: ...
    def synthesize(self, text: str, *, voice: str = "") -> bytes: ...


# ------------------------------------------------------------------
# 9. StorageCapability
# ------------------------------------------------------------------


@runtime_checkable
class StorageCapability(Protocol):
    @property
    def name(self) -> str: ...
    def available(self) -> bool: ...
    def health(self) -> HealthStatus: ...
    def read(self, key: str) -> str | None: ...
    def write(self, key: str, value: str) -> None: ...
