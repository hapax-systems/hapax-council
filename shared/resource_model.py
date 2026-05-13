"""Resource topology model for infrastructure capacity management."""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ResourceType(StrEnum):
    CPU = "cpu"
    RAM = "ram"
    GPU_VRAM = "gpu_vram"
    DISK_IO = "disk_io"
    DISK_SPACE = "disk_space"


class YieldTier(IntEnum):
    AGENT_SESSION = 1
    BACKGROUND_BATCH = 2
    DISCRETIONARY_GPU = 3
    ANALYTICS = 4
    INFRASTRUCTURE = 5
    CRITICAL_PATH = 6


class ResourceState(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class Enforcement(StrEnum):
    HARD = "hard"
    SOFT = "soft"
    HYBRID = "hybrid"


class ResourceThreshold(BaseModel):
    resource_type: ResourceType
    signal: str
    unit: str
    green_above: float
    yellow_above: float
    red_below: float | None = None
    direction: Literal["higher_is_better", "lower_is_better"] = "higher_is_better"


class ResourceAllocation(BaseModel):
    resource_type: ResourceType
    steady_state: float
    peak: float | None = None
    limit: float | None = None
    unit: str
    enforcement: Enforcement = Enforcement.SOFT
    notes: str = ""


class ContentionGroup(BaseModel):
    name: str
    resource_type: ResourceType
    total_capacity: float
    unit: str
    members: list[str]
    headroom_min: float
    notes: str = ""

    @model_validator(mode="after")
    def _validate_non_empty(self) -> ContentionGroup:
        if self.total_capacity <= 0:
            raise ValueError("total_capacity must be positive")
        if not self.members:
            raise ValueError("members must not be empty")
        return self


class ServiceResourceProfile(BaseModel):
    service_name: str
    yield_tier: YieldTier
    allocations: dict[ResourceType, ResourceAllocation]
    contention_groups: list[str]
    oom_score_adj: int | None = None
    labels: dict[str, str] = Field(default_factory=dict)


class ResourcePressure(BaseModel):
    resource_type: ResourceType
    state: ResourceState
    current_value: float
    threshold: ResourceThreshold
    measured_at: datetime
    contention_group: str | None = None


class ResourceConstraint(BaseModel):
    constraint_id: str
    resource_type: ResourceType
    signal: str
    green_threshold: float
    yellow_threshold: float
    red_threshold: float
    enforcement: Enforcement
    source: str
    created_at: datetime
    active: bool = True
    reason: str = ""
    expires_at: datetime | None = None


def classify_state(
    value: float,
    threshold: ResourceThreshold,
) -> ResourceState:
    if threshold.direction == "higher_is_better":
        if value > threshold.green_above:
            return ResourceState.GREEN
        if value > threshold.yellow_above:
            return ResourceState.YELLOW
        return ResourceState.RED
    if value < threshold.green_above:
        return ResourceState.GREEN
    if value < threshold.yellow_above:
        return ResourceState.YELLOW
    return ResourceState.RED


# ---------------------------------------------------------------------------
# Data constants from infrastructure resource model research (2026-05-09)
# ---------------------------------------------------------------------------

DEFAULT_THRESHOLDS: list[ResourceThreshold] = [
    ResourceThreshold(
        resource_type=ResourceType.RAM,
        signal="mem_available_gb",
        unit="GB",
        green_above=30.0,
        yellow_above=15.0,
        direction="higher_is_better",
    ),
    ResourceThreshold(
        resource_type=ResourceType.RAM,
        signal="swap_used_gb",
        unit="GB",
        green_above=4.0,
        yellow_above=16.0,
        direction="lower_is_better",
    ),
    ResourceThreshold(
        resource_type=ResourceType.RAM,
        signal="swap_used_pct",
        unit="%",
        green_above=70.0,
        yellow_above=85.0,
        direction="lower_is_better",
    ),
    ResourceThreshold(
        resource_type=ResourceType.RAM,
        signal="zram_used_pct",
        unit="%",
        green_above=70.0,
        yellow_above=85.0,
        direction="lower_is_better",
    ),
    ResourceThreshold(
        resource_type=ResourceType.GPU_VRAM,
        signal="vram_free_gb",
        unit="GB",
        green_above=2.0,
        yellow_above=1.0,
        direction="higher_is_better",
    ),
    ResourceThreshold(
        resource_type=ResourceType.GPU_VRAM,
        signal="gpu_util_pct",
        unit="%",
        green_above=90.0,
        yellow_above=95.0,
        direction="lower_is_better",
    ),
    ResourceThreshold(
        resource_type=ResourceType.GPU_VRAM,
        signal="gpu_temp_c",
        unit="C",
        green_above=80.0,
        yellow_above=90.0,
        direction="lower_is_better",
    ),
    ResourceThreshold(
        resource_type=ResourceType.CPU,
        signal="load_avg_5m",
        unit="load",
        green_above=10.0,
        yellow_above=14.0,
        direction="lower_is_better",
    ),
    ResourceThreshold(
        resource_type=ResourceType.DISK_SPACE,
        signal="disk_usage_pct",
        unit="%",
        green_above=80.0,
        yellow_above=90.0,
        direction="lower_is_better",
    ),
    ResourceThreshold(
        resource_type=ResourceType.DISK_IO,
        signal="nvme_queue_depth",
        unit="depth",
        green_above=64.0,
        yellow_above=128.0,
        direction="lower_is_better",
    ),
]

DEFAULT_CONTENTION_GROUPS: dict[str, ContentionGroup] = {
    "CG-GPU0": ContentionGroup(
        name="CG-GPU0",
        resource_type=ResourceType.GPU_VRAM,
        total_capacity=24576.0,
        unit="MiB",
        members=["tabbyapi", "hapax-daimonion", "studio-compositor", "obs"],
        headroom_min=2048.0,
        notes="RTX 3090 VRAM",
    ),
    "CG-GPU1": ContentionGroup(
        name="CG-GPU1",
        resource_type=ResourceType.GPU_VRAM,
        total_capacity=16311.0,
        unit="MiB",
        members=["tabbyapi", "studio-person-detector", "ollama", "hapax-imagination"],
        headroom_min=2048.0,
        notes="RTX 5060 Ti VRAM",
    ),
    "CG-AUDIO": ContentionGroup(
        name="CG-AUDIO",
        resource_type=ResourceType.CPU,
        total_capacity=4.0,
        unit="cores",
        members=["pipewire", "wireplumber", "pipewire-pulse"],
        headroom_min=0.0,
        notes="Dedicated cores 6,7,14,15",
    ),
    "CG-CPU-GENERAL": ContentionGroup(
        name="CG-CPU-GENERAL",
        resource_type=ResourceType.CPU,
        total_capacity=12.0,
        unit="cores",
        members=[
            "agent-sessions",
            "clickhouse",
            "grafana",
            "hapax-backup-local",
            "hapax-daimonion",
            "hapax-dmn",
            "hapax-imagination",
            "langfuse",
            "langfuse-worker",
            "litellm",
            "logos-api",
            "minio",
            "n8n",
            "ntfy",
            "obs",
            "ollama",
            "open-webui",
            "postgres",
            "prometheus",
            "qdrant",
            "rag-ingest",
            "redis",
            "reverie",
            "studio-compositor",
            "studio-fx-output",
            "studio-person-detector",
            "tabbyapi",
            "visual-layer-aggregator",
        ],
        headroom_min=2.0,
        notes="General CPU cores 0-5, 8-13",
    ),
    "CG-RAM": ContentionGroup(
        name="CG-RAM",
        resource_type=ResourceType.RAM,
        total_capacity=128.0,
        unit="GB",
        members=[
            "agent-sessions",
            "clickhouse",
            "grafana",
            "hapax-backup-local",
            "hapax-daimonion",
            "hapax-dmn",
            "hapax-imagination",
            "langfuse",
            "langfuse-worker",
            "litellm",
            "logos-api",
            "minio",
            "n8n",
            "ntfy",
            "obs",
            "ollama",
            "open-webui",
            "pipewire",
            "pipewire-pulse",
            "postgres",
            "prometheus",
            "qdrant",
            "rag-ingest",
            "redis",
            "reverie",
            "studio-compositor",
            "studio-fx-output",
            "studio-person-detector",
            "tabbyapi",
            "visual-layer-aggregator",
            "wireplumber",
        ],
        headroom_min=30.0,
    ),
    "CG-DISK-IO": ContentionGroup(
        name="CG-DISK-IO",
        resource_type=ResourceType.DISK_IO,
        total_capacity=1.0,
        unit="drive",
        members=[
            "agent-sessions",
            "clickhouse",
            "hapax-backup-local",
            "rag-ingest",
            "studio-compositor",
        ],
        headroom_min=0.0,
        notes="Single NVMe, all workloads share",
    ),
}

# ---------------------------------------------------------------------------
# Service resource profiles — one per service from research §1.3, §1.4, §2
# ---------------------------------------------------------------------------

DEFAULT_SERVICE_PROFILES: dict[str, ServiceResourceProfile] = {
    # === Critical Path (Y6) — never throttle, never drain ===
    "tabbyapi": ServiceResourceProfile(
        service_name="tabbyapi",
        yield_tier=YieldTier.CRITICAL_PATH,
        allocations={
            ResourceType.GPU_VRAM: ResourceAllocation(
                resource_type=ResourceType.GPU_VRAM,
                steady_state=24730.0,
                unit="MiB",
                notes="GPU 0: 13600 + GPU 1: 11130",
            ),
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=5.65,
                peak=20.5,
                unit="GB",
            ),
        },
        contention_groups=["CG-GPU0", "CG-GPU1", "CG-CPU-GENERAL", "CG-RAM"],
        labels={"kind": "systemd"},
    ),
    "hapax-daimonion": ServiceResourceProfile(
        service_name="hapax-daimonion",
        yield_tier=YieldTier.CRITICAL_PATH,
        allocations={
            ResourceType.GPU_VRAM: ResourceAllocation(
                resource_type=ResourceType.GPU_VRAM,
                steady_state=3526.0,
                unit="MiB",
            ),
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=4.3,
                peak=7.33,
                limit=12.0,
                unit="GB",
                enforcement=Enforcement.HARD,
            ),
        },
        contention_groups=["CG-GPU0", "CG-CPU-GENERAL", "CG-RAM"],
        oom_score_adj=-500,
        labels={"kind": "systemd"},
    ),
    "studio-compositor": ServiceResourceProfile(
        service_name="studio-compositor",
        yield_tier=YieldTier.CRITICAL_PATH,
        allocations={
            ResourceType.GPU_VRAM: ResourceAllocation(
                resource_type=ResourceType.GPU_VRAM,
                steady_state=1493.0,
                unit="MiB",
            ),
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=2.97,
                peak=3.02,
                limit=6.0,
                unit="GB",
                enforcement=Enforcement.HARD,
            ),
            ResourceType.DISK_IO: ResourceAllocation(
                resource_type=ResourceType.DISK_IO,
                steady_state=400.0,
                unit="weight",
                enforcement=Enforcement.HARD,
            ),
        },
        contention_groups=["CG-GPU0", "CG-CPU-GENERAL", "CG-RAM", "CG-DISK-IO"],
        labels={"kind": "systemd"},
    ),
    "obs": ServiceResourceProfile(
        service_name="obs",
        yield_tier=YieldTier.CRITICAL_PATH,
        allocations={
            ResourceType.GPU_VRAM: ResourceAllocation(
                resource_type=ResourceType.GPU_VRAM,
                steady_state=518.0,
                unit="MiB",
            ),
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=0.85,
                unit="GB",
            ),
        },
        contention_groups=["CG-GPU0", "CG-CPU-GENERAL", "CG-RAM"],
        labels={"kind": "user-session"},
    ),
    "logos-api": ServiceResourceProfile(
        service_name="logos-api",
        yield_tier=YieldTier.CRITICAL_PATH,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=0.84,
                peak=1.03,
                limit=1.0,
                unit="GB",
                enforcement=Enforcement.HARD,
            ),
        },
        contention_groups=["CG-CPU-GENERAL", "CG-RAM"],
        labels={"kind": "systemd"},
    ),
    "hapax-dmn": ServiceResourceProfile(
        service_name="hapax-dmn",
        yield_tier=YieldTier.CRITICAL_PATH,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=0.17,
                unit="GB",
            ),
        },
        contention_groups=["CG-CPU-GENERAL", "CG-RAM"],
        labels={"kind": "systemd"},
    ),
    "pipewire": ServiceResourceProfile(
        service_name="pipewire",
        yield_tier=YieldTier.CRITICAL_PATH,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=0.05,
                unit="GB",
            ),
        },
        contention_groups=["CG-AUDIO", "CG-RAM"],
        labels={"kind": "audio"},
    ),
    "wireplumber": ServiceResourceProfile(
        service_name="wireplumber",
        yield_tier=YieldTier.CRITICAL_PATH,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=0.03,
                unit="GB",
            ),
        },
        contention_groups=["CG-AUDIO", "CG-RAM"],
        labels={"kind": "audio"},
    ),
    "pipewire-pulse": ServiceResourceProfile(
        service_name="pipewire-pulse",
        yield_tier=YieldTier.CRITICAL_PATH,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=0.02,
                unit="GB",
            ),
        },
        contention_groups=["CG-AUDIO", "CG-RAM"],
        labels={"kind": "audio"},
    ),
    # === Infrastructure (Y5) — degrade only, never drain ===
    "litellm": ServiceResourceProfile(
        service_name="litellm",
        yield_tier=YieldTier.INFRASTRUCTURE,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=1.523,
                limit=2.0,
                unit="GB",
                enforcement=Enforcement.HARD,
            ),
            ResourceType.CPU: ResourceAllocation(
                resource_type=ResourceType.CPU,
                steady_state=1.0,
                limit=1.0,
                unit="cores",
                enforcement=Enforcement.HARD,
            ),
        },
        contention_groups=["CG-CPU-GENERAL", "CG-RAM"],
        labels={"kind": "docker"},
    ),
    "postgres": ServiceResourceProfile(
        service_name="postgres",
        yield_tier=YieldTier.INFRASTRUCTURE,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=0.273,
                limit=6.0,
                unit="GB",
                enforcement=Enforcement.HARD,
            ),
            ResourceType.CPU: ResourceAllocation(
                resource_type=ResourceType.CPU,
                steady_state=1.0,
                limit=1.0,
                unit="cores",
                enforcement=Enforcement.HARD,
            ),
        },
        contention_groups=["CG-CPU-GENERAL", "CG-RAM"],
        labels={"kind": "docker"},
    ),
    "redis": ServiceResourceProfile(
        service_name="redis",
        yield_tier=YieldTier.INFRASTRUCTURE,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=0.754,
                limit=2.0,
                unit="GB",
                enforcement=Enforcement.HARD,
            ),
            ResourceType.CPU: ResourceAllocation(
                resource_type=ResourceType.CPU,
                steady_state=1.0,
                limit=1.0,
                unit="cores",
                enforcement=Enforcement.HARD,
            ),
        },
        contention_groups=["CG-CPU-GENERAL", "CG-RAM"],
        labels={"kind": "docker"},
    ),
    "qdrant": ServiceResourceProfile(
        service_name="qdrant",
        yield_tier=YieldTier.INFRASTRUCTURE,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=0.332,
                limit=6.0,
                unit="GB",
                enforcement=Enforcement.HARD,
            ),
            ResourceType.CPU: ResourceAllocation(
                resource_type=ResourceType.CPU,
                steady_state=4.0,
                limit=4.0,
                unit="cores",
                enforcement=Enforcement.HARD,
            ),
        },
        contention_groups=["CG-CPU-GENERAL", "CG-RAM"],
        labels={"kind": "docker"},
    ),
    "minio": ServiceResourceProfile(
        service_name="minio",
        yield_tier=YieldTier.INFRASTRUCTURE,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=2.965,
                limit=4.0,
                unit="GB",
                enforcement=Enforcement.HARD,
            ),
            ResourceType.CPU: ResourceAllocation(
                resource_type=ResourceType.CPU,
                steady_state=1.0,
                limit=1.0,
                unit="cores",
                enforcement=Enforcement.HARD,
            ),
        },
        contention_groups=["CG-CPU-GENERAL", "CG-RAM"],
        labels={"kind": "docker"},
    ),
    "n8n": ServiceResourceProfile(
        service_name="n8n",
        yield_tier=YieldTier.INFRASTRUCTURE,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=0.273,
                limit=1.0,
                unit="GB",
                enforcement=Enforcement.HARD,
            ),
            ResourceType.CPU: ResourceAllocation(
                resource_type=ResourceType.CPU,
                steady_state=0.5,
                limit=0.5,
                unit="cores",
                enforcement=Enforcement.HARD,
            ),
        },
        contention_groups=["CG-CPU-GENERAL", "CG-RAM"],
        labels={"kind": "docker"},
    ),
    "ntfy": ServiceResourceProfile(
        service_name="ntfy",
        yield_tier=YieldTier.INFRASTRUCTURE,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=0.019,
                limit=0.256,
                unit="GB",
                enforcement=Enforcement.HARD,
            ),
            ResourceType.CPU: ResourceAllocation(
                resource_type=ResourceType.CPU,
                steady_state=0.25,
                limit=0.25,
                unit="cores",
                enforcement=Enforcement.HARD,
            ),
        },
        contention_groups=["CG-CPU-GENERAL", "CG-RAM"],
        labels={"kind": "docker"},
    ),
    "open-webui": ServiceResourceProfile(
        service_name="open-webui",
        yield_tier=YieldTier.INFRASTRUCTURE,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=0.681,
                limit=2.0,
                unit="GB",
                enforcement=Enforcement.HARD,
            ),
            ResourceType.CPU: ResourceAllocation(
                resource_type=ResourceType.CPU,
                steady_state=0.5,
                limit=0.5,
                unit="cores",
                enforcement=Enforcement.HARD,
            ),
        },
        contention_groups=["CG-CPU-GENERAL", "CG-RAM"],
        labels={"kind": "docker"},
    ),
    "visual-layer-aggregator": ServiceResourceProfile(
        service_name="visual-layer-aggregator",
        yield_tier=YieldTier.INFRASTRUCTURE,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=0.78,
                unit="GB",
            ),
        },
        contention_groups=["CG-CPU-GENERAL", "CG-RAM"],
        labels={"kind": "systemd"},
    ),
    "reverie": ServiceResourceProfile(
        service_name="reverie",
        yield_tier=YieldTier.INFRASTRUCTURE,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=0.28,
                unit="GB",
            ),
        },
        contention_groups=["CG-CPU-GENERAL", "CG-RAM"],
        labels={"kind": "systemd"},
    ),
    # === Analytics (Y4) — reduce sampling, stop non-essential ===
    "langfuse": ServiceResourceProfile(
        service_name="langfuse",
        yield_tier=YieldTier.ANALYTICS,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=0.835,
                limit=2.0,
                unit="GB",
                enforcement=Enforcement.HARD,
            ),
            ResourceType.CPU: ResourceAllocation(
                resource_type=ResourceType.CPU,
                steady_state=2.0,
                limit=2.0,
                unit="cores",
                enforcement=Enforcement.HARD,
            ),
        },
        contention_groups=["CG-CPU-GENERAL", "CG-RAM"],
        labels={"kind": "docker"},
    ),
    "langfuse-worker": ServiceResourceProfile(
        service_name="langfuse-worker",
        yield_tier=YieldTier.ANALYTICS,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=0.607,
                limit=2.0,
                unit="GB",
                enforcement=Enforcement.HARD,
            ),
            ResourceType.CPU: ResourceAllocation(
                resource_type=ResourceType.CPU,
                steady_state=2.0,
                limit=2.0,
                unit="cores",
                enforcement=Enforcement.HARD,
            ),
        },
        contention_groups=["CG-CPU-GENERAL", "CG-RAM"],
        labels={"kind": "docker"},
    ),
    "clickhouse": ServiceResourceProfile(
        service_name="clickhouse",
        yield_tier=YieldTier.ANALYTICS,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=2.811,
                limit=4.0,
                unit="GB",
                enforcement=Enforcement.HARD,
            ),
            ResourceType.CPU: ResourceAllocation(
                resource_type=ResourceType.CPU,
                steady_state=2.0,
                limit=2.0,
                unit="cores",
                enforcement=Enforcement.HARD,
            ),
        },
        contention_groups=["CG-CPU-GENERAL", "CG-RAM", "CG-DISK-IO"],
        labels={"kind": "docker"},
    ),
    "grafana": ServiceResourceProfile(
        service_name="grafana",
        yield_tier=YieldTier.ANALYTICS,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=0.135,
                limit=0.768,
                unit="GB",
                enforcement=Enforcement.HARD,
            ),
            ResourceType.CPU: ResourceAllocation(
                resource_type=ResourceType.CPU,
                steady_state=0.25,
                limit=0.25,
                unit="cores",
                enforcement=Enforcement.HARD,
            ),
        },
        contention_groups=["CG-CPU-GENERAL", "CG-RAM"],
        labels={"kind": "docker"},
    ),
    "prometheus": ServiceResourceProfile(
        service_name="prometheus",
        yield_tier=YieldTier.ANALYTICS,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=0.124,
                limit=1.0,
                unit="GB",
                enforcement=Enforcement.HARD,
            ),
            ResourceType.CPU: ResourceAllocation(
                resource_type=ResourceType.CPU,
                steady_state=0.5,
                limit=0.5,
                unit="cores",
                enforcement=Enforcement.HARD,
            ),
        },
        contention_groups=["CG-CPU-GENERAL", "CG-RAM"],
        labels={"kind": "docker"},
    ),
    # === Discretionary GPU (Y3) — pause, unload models ===
    "studio-person-detector": ServiceResourceProfile(
        service_name="studio-person-detector",
        yield_tier=YieldTier.DISCRETIONARY_GPU,
        allocations={
            ResourceType.GPU_VRAM: ResourceAllocation(
                resource_type=ResourceType.GPU_VRAM,
                steady_state=286.0,
                unit="MiB",
            ),
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=1.63,
                unit="GB",
            ),
        },
        contention_groups=["CG-GPU1", "CG-CPU-GENERAL", "CG-RAM"],
        labels={"kind": "user-session"},
    ),
    "hapax-imagination": ServiceResourceProfile(
        service_name="hapax-imagination",
        yield_tier=YieldTier.DISCRETIONARY_GPU,
        allocations={
            ResourceType.GPU_VRAM: ResourceAllocation(
                resource_type=ResourceType.GPU_VRAM,
                steady_state=94.0,
                unit="MiB",
            ),
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=0.09,
                peak=0.11,
                limit=4.0,
                unit="GB",
                enforcement=Enforcement.HARD,
            ),
        },
        contention_groups=["CG-GPU1", "CG-CPU-GENERAL", "CG-RAM"],
        labels={"kind": "systemd"},
    ),
    "ollama": ServiceResourceProfile(
        service_name="ollama",
        yield_tier=YieldTier.DISCRETIONARY_GPU,
        allocations={
            ResourceType.GPU_VRAM: ResourceAllocation(
                resource_type=ResourceType.GPU_VRAM,
                steady_state=276.0,
                unit="MiB",
                notes="GPU 1 isolation leak",
            ),
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=0.5,
                unit="GB",
            ),
        },
        contention_groups=["CG-GPU1", "CG-CPU-GENERAL", "CG-RAM"],
        labels={"kind": "systemd"},
    ),
    # === Background Batch (Y2) — pause/stop via systemctl ===
    "rag-ingest": ServiceResourceProfile(
        service_name="rag-ingest",
        yield_tier=YieldTier.BACKGROUND_BATCH,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=0.09,
                peak=0.11,
                limit=4.0,
                unit="GB",
                enforcement=Enforcement.HARD,
            ),
            ResourceType.CPU: ResourceAllocation(
                resource_type=ResourceType.CPU,
                steady_state=0.8,
                limit=0.8,
                unit="cores",
                enforcement=Enforcement.HARD,
            ),
            ResourceType.DISK_IO: ResourceAllocation(
                resource_type=ResourceType.DISK_IO,
                steady_state=50.0,
                unit="weight",
                enforcement=Enforcement.HARD,
            ),
        },
        contention_groups=["CG-CPU-GENERAL", "CG-RAM", "CG-DISK-IO"],
        labels={"kind": "systemd"},
    ),
    "hapax-backup-local": ServiceResourceProfile(
        service_name="hapax-backup-local",
        yield_tier=YieldTier.BACKGROUND_BATCH,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=0.1,
                limit=2.0,
                unit="GB",
                enforcement=Enforcement.HARD,
            ),
            ResourceType.CPU: ResourceAllocation(
                resource_type=ResourceType.CPU,
                steady_state=0.5,
                limit=0.5,
                unit="cores",
                enforcement=Enforcement.HARD,
            ),
        },
        contention_groups=["CG-CPU-GENERAL", "CG-RAM", "CG-DISK-IO"],
        labels={"kind": "systemd"},
    ),
    "studio-fx-output": ServiceResourceProfile(
        service_name="studio-fx-output",
        yield_tier=YieldTier.BACKGROUND_BATCH,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=0.1,
                limit=0.5,
                unit="GB",
                enforcement=Enforcement.HARD,
            ),
            ResourceType.DISK_IO: ResourceAllocation(
                resource_type=ResourceType.DISK_IO,
                steady_state=50.0,
                unit="weight",
                enforcement=Enforcement.HARD,
            ),
        },
        contention_groups=["CG-CPU-GENERAL", "CG-RAM"],
        labels={"kind": "systemd"},
    ),
    # === Agent Session (Y1) — drain first ===
    "agent-sessions": ServiceResourceProfile(
        service_name="agent-sessions",
        yield_tier=YieldTier.AGENT_SESSION,
        allocations={
            ResourceType.RAM: ResourceAllocation(
                resource_type=ResourceType.RAM,
                steady_state=6.0,
                unit="GB",
            ),
        },
        contention_groups=["CG-CPU-GENERAL", "CG-RAM", "CG-DISK-IO"],
        labels={"kind": "aggregate"},
    ),
}
