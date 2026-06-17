"""Immediate host memory pressure checks."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from shared.memory_pressure import (
    MemoryPressureSignal,
    classify_global_ram_pressure,
    classify_memory_psi_pressure,
    classify_swap_zram_saturation,
    classify_swappiness_drift,
    parse_meminfo,
    parse_memory_psi,
    parse_proc_swaps,
)
from shared.resource_model import ResourceState

from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group

_MEMINFO_PATH = Path("/proc/meminfo")
_MEMORY_PSI_PATH = Path("/proc/pressure/memory")
_SWAPS_PATH = Path("/proc/swaps")
_SWAPPINESS_PATH = Path("/proc/sys/vm/swappiness")


@check_group("memory")
async def check_memory_pressure() -> list[CheckResult]:
    """Classify current RAM, zram/swap, and swappiness drift signals."""

    t = time.monotonic()
    meminfo_text = _read_text(_MEMINFO_PATH)
    if meminfo_text is None:
        return [
            CheckResult(
                name="memory.global_ram_pressure",
                group="memory",
                status=Status.DEGRADED,
                message="Cannot read /proc/meminfo",
                duration_ms=_u._timed(t),
            )
        ]

    signals = [classify_global_ram_pressure(parse_meminfo(meminfo_text))]

    memory_psi_text = _read_text(_MEMORY_PSI_PATH)
    if memory_psi_text is not None:
        signals.append(classify_memory_psi_pressure(parse_memory_psi(memory_psi_text)))

    swaps_text = _read_text(_SWAPS_PATH) or ""
    swap_devices = parse_proc_swaps(swaps_text)
    signals.append(classify_swap_zram_saturation(swap_devices))
    zram_active = any(device.is_zram for device in swap_devices)

    swappiness_text = _read_text(_SWAPPINESS_PATH)
    if swappiness_text is None:
        results = [_check_result(signal, started_at=t) for signal in signals]
        results.append(
            CheckResult(
                name="memory.sysctl_drift",
                group="memory",
                status=Status.DEGRADED,
                message="Cannot read /proc/sys/vm/swappiness",
                duration_ms=_u._timed(t),
            )
        )
        return results

    try:
        live_swappiness = int(swappiness_text.strip())
        expected_env = os.environ.get("HAPAX_EXPECTED_SWAPPINESS")
        if expected_env is not None:
            # explicit operator override wins (exact match)
            signals.append(
                classify_swappiness_drift(live_swappiness, expected_value=int(expected_env))
            )
        else:
            # box-class default: a zram swap box correctly runs a high vm.swappiness
            # (CachyOS sets 150), so only hold to the flat low default when off zram.
            signals.append(classify_swappiness_drift(live_swappiness, zram_active=zram_active))
    except ValueError:
        results = [_check_result(signal, started_at=t) for signal in signals]
        results.append(
            CheckResult(
                name="memory.sysctl_drift",
                group="memory",
                status=Status.DEGRADED,
                message=f"Cannot parse vm.swappiness: {swappiness_text.strip()}",
                duration_ms=_u._timed(t),
            )
        )
        return results

    return [_check_result(signal, started_at=t) for signal in signals]


def _check_result(signal: MemoryPressureSignal, *, started_at: float) -> CheckResult:
    return CheckResult(
        name=f"memory.{signal.pressure_class.value}",
        group="memory",
        status=_status_from_resource_state(signal.state),
        message=signal.message,
        detail=json.dumps(signal.raw, sort_keys=True),
        remediation=_remediation(signal) if signal.state != ResourceState.GREEN else None,
        duration_ms=_u._timed(started_at),
    )


def _status_from_resource_state(state: ResourceState) -> Status:
    if state == ResourceState.GREEN:
        return Status.HEALTHY
    if state == ResourceState.YELLOW:
        return Status.DEGRADED
    return Status.FAILED


def _remediation(signal: MemoryPressureSignal) -> str | None:
    if signal.pressure_class.value == "global_ram_pressure":
        return "Pause discretionary sessions and inspect top RSS consumers before repair."
    if signal.pressure_class.value == "memory_psi_pressure":
        return "Inspect memory stall sources before admission or restart gates proceed."
    if signal.pressure_class.value == "zram_saturation":
        return (
            "Treat swap/zram saturation as telemetry unless RAM availability or PSI shows pressure."
        )
    if signal.pressure_class.value == "sysctl_drift":
        return "Reconcile live vm.swappiness with source-controlled Hapax policy."
    return None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None
