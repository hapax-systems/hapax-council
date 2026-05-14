"""Typed memory-pressure parsers and classifiers.

The helpers in this module are deliberately pure: callers inject text payloads
from procfs, sysfs, cgroupfs, or systemd show output and receive structured
signals. Host policy mutation belongs in later governed slices.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from shared.resource_model import (
    DEFAULT_SERVICE_PROFILES,
    DEFAULT_THRESHOLDS,
    ResourceState,
    ResourceThreshold,
    ResourceType,
    ServiceResourceProfile,
    YieldTier,
    classify_state,
)

BYTES_PER_KIB = 1024
BYTES_PER_GIB = 1024**3
DEFAULT_EXPECTED_SWAPPINESS = 5


class MemoryPressureClass(StrEnum):
    GLOBAL_RAM_PRESSURE = "global_ram_pressure"
    ZRAM_SATURATION = "zram_saturation"
    SYSCTL_DRIFT = "sysctl_drift"
    SERVICE_CGROUP_OOM = "service_cgroup_oom"
    CRITICAL_FLOOR_RISK = "critical_floor_risk"


class SwapDevice(BaseModel):
    filename: str
    device_type: str
    size_bytes: int
    used_bytes: int
    priority: int
    is_zram: bool = False


class ZramMmStat(BaseModel):
    orig_data_size: int
    compr_data_size: int
    mem_used_total: int
    mem_limit: int | None = None
    mem_used_max: int | None = None
    same_pages: int | None = None
    pages_compacted: int | None = None
    huge_pages: int | None = None
    huge_pages_since: int | None = None
    raw_values: list[int] = Field(default_factory=list)


class SystemdMemoryProperties(BaseModel):
    service_name: str
    memory_max_bytes: int | None = None
    memory_high_bytes: int | None = None
    oom_score_adjust: int | None = None


class MemoryPressureSignal(BaseModel):
    pressure_class: MemoryPressureClass
    state: ResourceState
    message: str
    resource_type: ResourceType = ResourceType.RAM
    current_value: float | None = None
    unit: str = ""
    threshold_signal: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


def parse_meminfo(text: str) -> dict[str, int]:
    """Parse /proc/meminfo text into byte values keyed by meminfo field."""

    values: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        if not rest:
            continue
        parts = rest.strip().split()
        if not parts:
            continue
        try:
            raw_value = int(parts[0])
        except ValueError:
            continue
        unit = parts[1].lower() if len(parts) > 1 else "b"
        values[key] = raw_value * BYTES_PER_KIB if unit == "kb" else raw_value
    return values


def parse_proc_swaps(text: str) -> list[SwapDevice]:
    """Parse /proc/swaps into typed swap devices."""

    devices: list[SwapDevice] = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 5:
            continue
        filename, device_type, size_kib, used_kib, priority = parts[:5]
        try:
            size_bytes = int(size_kib) * BYTES_PER_KIB
            used_bytes = int(used_kib) * BYTES_PER_KIB
            priority_int = int(priority)
        except ValueError:
            continue
        basename = Path(filename).name
        devices.append(
            SwapDevice(
                filename=filename,
                device_type=device_type,
                size_bytes=size_bytes,
                used_bytes=used_bytes,
                priority=priority_int,
                is_zram=basename.startswith("zram") or "/zram" in filename,
            )
        )
    return devices


def parse_zram_mm_stat(text: str) -> ZramMmStat:
    """Parse /sys/block/zram*/mm_stat payloads.

    Kernel versions may append fields, so the raw integer vector is preserved
    while the stable leading counters get named fields.
    """

    values = [int(token) for token in text.split()]
    if len(values) < 3:
        raise ValueError("zram mm_stat must contain at least three counters")
    padded = values + [None] * (9 - len(values))
    return ZramMmStat(
        orig_data_size=values[0],
        compr_data_size=values[1],
        mem_used_total=values[2],
        mem_limit=padded[3],
        mem_used_max=padded[4],
        same_pages=padded[5],
        pages_compacted=padded[6],
        huge_pages=padded[7],
        huge_pages_since=padded[8],
        raw_values=values,
    )


def parse_cgroup_memory_events(text: str) -> dict[str, int]:
    """Parse cgroup v2 memory.events contents."""

    events: dict[str, int] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            events[parts[0]] = int(parts[1])
        except ValueError:
            continue
    return events


def parse_systemd_memory_properties(
    text: str,
    *,
    service_name: str = "",
) -> SystemdMemoryProperties:
    """Parse selected `systemctl show` memory properties."""

    values: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if not sep:
            continue
        values[key] = value.strip()
    return SystemdMemoryProperties(
        service_name=service_name,
        memory_max_bytes=_parse_memory_bytes(values.get("MemoryMax")),
        memory_high_bytes=_parse_memory_bytes(values.get("MemoryHigh")),
        oom_score_adjust=_parse_int(values.get("OOMScoreAdjust")),
    )


def classify_global_ram_pressure(meminfo: Mapping[str, int]) -> MemoryPressureSignal:
    threshold = memory_threshold("mem_available_gb")
    mem_total = int(meminfo.get("MemTotal", 0))
    mem_available = int(meminfo.get("MemAvailable", 0))
    mem_available_gb = mem_available / BYTES_PER_GIB
    mem_available_pct = (mem_available / mem_total * 100.0) if mem_total else 0.0
    state = classify_state(mem_available_gb, threshold)
    return MemoryPressureSignal(
        pressure_class=MemoryPressureClass.GLOBAL_RAM_PRESSURE,
        state=state,
        current_value=round(mem_available_gb, 3),
        unit=threshold.unit,
        threshold_signal=threshold.signal,
        message=f"global RAM available {mem_available_gb:.1f} GiB ({mem_available_pct:.1f}%)",
        raw={
            "mem_total_bytes": mem_total,
            "mem_available_bytes": mem_available,
            "mem_available_gb": round(mem_available_gb, 3),
            "mem_available_pct": round(mem_available_pct, 3),
            "threshold": threshold.model_dump(mode="json"),
        },
    )


def classify_swap_zram_saturation(
    devices: Sequence[SwapDevice],
    *,
    zram_stats_by_device: Mapping[str, ZramMmStat] | None = None,
) -> MemoryPressureSignal:
    zram_devices = [device for device in devices if device.is_zram]
    scoped_devices = zram_devices or list(devices)
    scope = "zram" if zram_devices else "swap"
    threshold = memory_threshold("zram_used_pct" if zram_devices else "swap_used_pct")

    total_bytes = sum(device.size_bytes for device in scoped_devices)
    used_bytes = sum(device.used_bytes for device in scoped_devices)
    used_pct = (used_bytes / total_bytes * 100.0) if total_bytes else 0.0
    state = classify_state(used_pct, threshold)
    message = (
        f"{scope} used {used_pct:.1f}%"
        if total_bytes
        else "no active swap or zram devices reported"
    )
    zram_stats_by_device = zram_stats_by_device or {}
    return MemoryPressureSignal(
        pressure_class=MemoryPressureClass.ZRAM_SATURATION,
        state=state,
        current_value=round(used_pct, 3),
        unit=threshold.unit,
        threshold_signal=threshold.signal,
        message=message,
        raw={
            "scope": scope,
            "used_bytes": used_bytes,
            "total_bytes": total_bytes,
            "used_pct": round(used_pct, 3),
            "devices": [device.model_dump(mode="json") for device in scoped_devices],
            "zram_mm_stat": {
                name: stat.model_dump(mode="json") for name, stat in zram_stats_by_device.items()
            },
            "threshold": threshold.model_dump(mode="json"),
        },
    )


def classify_swappiness_drift(
    live_value: int,
    *,
    expected_value: int = DEFAULT_EXPECTED_SWAPPINESS,
) -> MemoryPressureSignal:
    drift = live_value - expected_value
    state = ResourceState.GREEN if drift == 0 else ResourceState.RED
    return MemoryPressureSignal(
        pressure_class=MemoryPressureClass.SYSCTL_DRIFT,
        state=state,
        current_value=float(live_value),
        unit="value",
        threshold_signal="vm.swappiness",
        message=f"vm.swappiness live {live_value}, expected {expected_value}",
        raw={"live_value": live_value, "expected_value": expected_value, "drift": drift},
    )


def classify_live_swappiness(
    reader: Callable[[], str | int],
    *,
    expected_value: int = DEFAULT_EXPECTED_SWAPPINESS,
) -> MemoryPressureSignal:
    """Classify live swappiness using an injected reader."""

    value = reader()
    return classify_swappiness_drift(int(str(value).strip()), expected_value=expected_value)


def classify_cgroup_memory_events(
    service_name: str,
    events: Mapping[str, int],
) -> MemoryPressureSignal:
    oom_kill = int(events.get("oom_kill", 0)) + int(events.get("oom_group_kill", 0))
    oom = int(events.get("oom", 0))
    max_events = int(events.get("max", 0))
    if oom_kill > 0:
        state = ResourceState.RED
        message = f"{service_name} cgroup recorded {oom_kill} OOM kill event(s)"
    elif oom > 0 or max_events > 0:
        state = ResourceState.YELLOW
        message = f"{service_name} cgroup recorded memory pressure events"
    else:
        state = ResourceState.GREEN
        message = f"{service_name} cgroup has no OOM events"
    return MemoryPressureSignal(
        pressure_class=MemoryPressureClass.SERVICE_CGROUP_OOM,
        state=state,
        threshold_signal="memory.events",
        message=message,
        raw={"service_name": service_name, "events": dict(events)},
    )


def classify_critical_floor_risk(
    service_name: str,
    properties: SystemdMemoryProperties,
    *,
    profile: ServiceResourceProfile | None = None,
) -> MemoryPressureSignal:
    profile = profile or DEFAULT_SERVICE_PROFILES.get(service_name)
    if profile is None:
        return MemoryPressureSignal(
            pressure_class=MemoryPressureClass.CRITICAL_FLOOR_RISK,
            state=ResourceState.YELLOW,
            threshold_signal="service_profile",
            message=f"{service_name} has no resource profile for critical floor evaluation",
            raw={"service_name": service_name, "properties": properties.model_dump(mode="json")},
        )

    expected_limit_bytes = _profile_ram_limit_bytes(profile)
    expected_oom_score = profile.oom_score_adj
    critical = profile.yield_tier == YieldTier.CRITICAL_PATH
    reasons: list[str] = []
    state = ResourceState.GREEN

    if critical and expected_limit_bytes is not None:
        if properties.memory_max_bytes is None:
            state = ResourceState.YELLOW
            reasons.append("missing_memory_max")
        elif properties.memory_max_bytes < expected_limit_bytes:
            state = ResourceState.RED
            reasons.append("memory_max_below_profile_limit")

    if critical and expected_oom_score is not None:
        if properties.oom_score_adjust is None:
            state = _worse_state(state, ResourceState.YELLOW)
            reasons.append("missing_oom_score_adjust")
        elif properties.oom_score_adjust > expected_oom_score:
            state = _worse_state(state, ResourceState.YELLOW)
            reasons.append("oom_score_less_protected_than_profile")

    message = (
        f"{service_name} critical memory floor risk: {', '.join(reasons)}"
        if reasons
        else f"{service_name} critical memory floor matches resource profile"
    )
    return MemoryPressureSignal(
        pressure_class=MemoryPressureClass.CRITICAL_FLOOR_RISK,
        state=state,
        threshold_signal="service_profile",
        message=message,
        raw={
            "service_name": service_name,
            "yield_tier": int(profile.yield_tier),
            "expected_memory_max_bytes": expected_limit_bytes,
            "expected_oom_score_adjust": expected_oom_score,
            "properties": properties.model_dump(mode="json"),
            "reasons": reasons,
        },
    )


def memory_threshold(signal: str) -> ResourceThreshold:
    for threshold in DEFAULT_THRESHOLDS:
        if threshold.resource_type == ResourceType.RAM and threshold.signal == signal:
            return threshold
    raise LookupError(f"No RAM threshold configured for {signal}")


def _parse_memory_bytes(value: str | None) -> int | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped or stripped in {"max", "infinity"}:
        return None
    if stripped == str(2**64 - 1):
        return None
    suffix = stripped[-1].upper()
    multiplier = 1
    number = stripped
    if suffix in {"K", "M", "G", "T"}:
        number = stripped[:-1]
        multiplier = {
            "K": 1024,
            "M": 1024**2,
            "G": 1024**3,
            "T": 1024**4,
        }[suffix]
    try:
        return int(float(number) * multiplier)
    except ValueError:
        return None


def _parse_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _profile_ram_limit_bytes(profile: ServiceResourceProfile) -> int | None:
    allocation = profile.allocations.get(ResourceType.RAM)
    if allocation is None or allocation.limit is None:
        return None
    if allocation.unit.lower() == "gb":
        return int(allocation.limit * BYTES_PER_GIB)
    if allocation.unit.lower() == "mib":
        return int(allocation.limit * 1024**2)
    return int(allocation.limit)


def _worse_state(left: ResourceState, right: ResourceState) -> ResourceState:
    order = {
        ResourceState.GREEN: 0,
        ResourceState.YELLOW: 1,
        ResourceState.RED: 2,
    }
    return left if order[left] >= order[right] else right
