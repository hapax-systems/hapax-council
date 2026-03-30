"""All Pydantic models for drift_detector package."""

from __future__ import annotations

from pydantic import BaseModel, Field

# ── Infrastructure manifest models (from introspect.py) ────────────────────


class ContainerInfo(BaseModel):
    name: str
    service: str
    image: str
    state: str
    health: str
    ports: list[str] = Field(default_factory=list)


class SystemdUnit(BaseModel):
    name: str
    type: str  # service, timer
    active: str
    enabled: str
    description: str = ""


class QdrantCollection(BaseModel):
    name: str
    points_count: int = 0
    vectors_size: int = 768
    distance: str = "Cosine"


class OllamaModel(BaseModel):
    name: str
    size_bytes: int = 0
    modified_at: str = ""


class GpuInfo(BaseModel):
    name: str = ""
    driver: str = ""
    vram_total_mb: int = 0
    vram_used_mb: int = 0
    vram_free_mb: int = 0
    temperature_c: int = 0
    loaded_models: list[str] = Field(default_factory=list)


class LiteLLMRoute(BaseModel):
    model_name: str
    litellm_params_model: str = ""


class DiskInfo(BaseModel):
    mount: str
    size: str = ""
    used: str = ""
    available: str = ""
    use_percent: int = 0


class InfrastructureManifest(BaseModel):
    timestamp: str
    hostname: str
    os_info: str = ""
    docker_version: str = ""
    containers: list[ContainerInfo] = Field(default_factory=list)
    systemd_units: list[SystemdUnit] = Field(default_factory=list)
    systemd_timers: list[SystemdUnit] = Field(default_factory=list)
    qdrant_collections: list[QdrantCollection] = Field(default_factory=list)
    ollama_models: list[OllamaModel] = Field(default_factory=list)
    gpu: GpuInfo | None = None
    litellm_routes: list[LiteLLMRoute] = Field(default_factory=list)
    disk: list[DiskInfo] = Field(default_factory=list)
    listening_ports: list[str] = Field(default_factory=list)
    pass_entries: list[str] = Field(default_factory=list)
    compose_file: str = ""
    profile_files: list[str] = Field(default_factory=list)
    edge_nodes: list[dict] = Field(default_factory=list)


# ── Drift detection models ─────────────────────────────────────────────────


class DriftItem(BaseModel):
    """A single discrepancy between documentation and reality."""

    severity: str = Field(description="high, medium, or low")
    category: str = Field(
        description="Category: missing_service, extra_service, wrong_port, wrong_version, stale_reference, missing_doc, config_mismatch, goal-gap, axiom-violation, axiom-sufficiency-gap, stale_doc"
    )
    doc_file: str = Field(description="Which documentation file contains the drift")
    doc_claim: str = Field(description="What the documentation says")
    reality: str = Field(description="What the actual system state is")
    suggestion: str = Field(description="Suggested fix — either a doc edit or a system change")


class DriftReport(BaseModel):
    """Complete drift analysis."""

    drift_items: list[DriftItem] = Field(default_factory=list)
    docs_analyzed: list[str] = Field(default_factory=list)
    summary: str = Field(description="One-paragraph summary of overall drift state")


class DocFix(BaseModel):
    """A corrected section of a documentation file."""

    doc_file: str = Field(description="Which documentation file this fix applies to")
    section_title: str = Field(description="The section or table being corrected")
    original: str = Field(
        description="The original text that needs changing (exact match from the doc)"
    )
    corrected: str = Field(description="The corrected replacement text")
    explanation: str = Field(description="Brief explanation of what changed and why")


class FixReport(BaseModel):
    """Collection of documentation fixes."""

    fixes: list[DocFix] = Field(default_factory=list)
    summary: str = Field(description="One-line summary of all changes")


class ApplyResult(BaseModel):
    """Result of applying fixes to documentation files."""

    applied: int = 0
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
