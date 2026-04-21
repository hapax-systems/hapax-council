"""GPU and VRAM health checks."""

from __future__ import annotations

import json
import time

from .. import constants as _c
from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


async def _nvidia_smi(query: str) -> tuple[int, str, str]:
    """Try nvidia-smi, fall back to /usr/bin/nvidia-smi."""
    rc, out, err = await _u.run_cmd(
        ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"]
    )
    if rc == 127:
        rc, out, err = await _u.run_cmd(
            ["/usr/bin/nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"]
        )
    return rc, out, err


@check_group("gpu")
async def check_gpu_available() -> list[CheckResult]:
    t = time.monotonic()
    rc, out, err = await _nvidia_smi("driver_version,name")
    if rc == 0 and out:
        parts = [p.strip() for p in out.split(",")]
        driver = parts[0] if parts else "?"
        gpu_name = parts[1] if len(parts) > 1 else "?"
        return [
            CheckResult(
                name="gpu.available",
                group="gpu",
                status=Status.HEALTHY,
                message=f"{gpu_name} (driver {driver})",
                duration_ms=_u._timed(t),
            )
        ]
    return [
        CheckResult(
            name="gpu.available",
            group="gpu",
            status=Status.FAILED,
            message="GPU not detected",
            detail=err or out,
            remediation="nvidia-smi",
            duration_ms=_u._timed(t),
        )
    ]


@check_group("gpu")
async def check_gpu_vram() -> list[CheckResult]:
    t = time.monotonic()
    rc, out, err = await _nvidia_smi("memory.used,memory.total,memory.free")
    if rc != 0:
        return [
            CheckResult(
                name="gpu.vram",
                group="gpu",
                status=Status.FAILED,
                message="Cannot query VRAM",
                detail=err,
                duration_ms=_u._timed(t),
            )
        ]

    # nvidia-smi returns one CSV row per GPU. The pre-multi-GPU parser
    # split the whole blob on `,`, which on a 2-GPU box yields 6 fields
    # (last+first of adjacent rows fused, e.g. "18669\n627") and
    # int() chokes. Parse line-by-line and pick the worst-case GPU
    # (highest used%) — that's the bottleneck signal the operator cares
    # about for VRAM headroom.
    rows: list[tuple[int, int, int]] = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            rows.append((int(parts[0]), int(parts[1]), int(parts[2])))
        except ValueError:
            continue
    if not rows:
        return [
            CheckResult(
                name="gpu.vram",
                group="gpu",
                status=Status.DEGRADED,
                message=f"Cannot parse VRAM values: {out}",
                duration_ms=_u._timed(t),
            )
        ]

    # Pick the GPU with the highest used% (the bottleneck). Reporting
    # one number keeps the existing dashboard / health-rollup shape.
    used, total, free = max(rows, key=lambda r: (r[0] / r[1]) if r[1] > 0 else 0)
    pct = (used / total * 100) if total > 0 else 0
    if pct < 90:
        status = Status.HEALTHY
    elif pct < 95:
        status = Status.DEGRADED
    else:
        status = Status.FAILED

    msg = f"{used}MiB / {total}MiB ({pct:.0f}% used, {free}MiB free)"

    detail = None
    try:
        code, body = await _u.http_get(f"{_c.OLLAMA_URL}/api/ps", timeout=2.0)
        if code == 200:
            data = json.loads(body)
            models = data.get("models", [])
            if models:
                model_names = [m.get("name", "?") for m in models]
                detail = f"Loaded Ollama models: {', '.join(model_names)}"
            else:
                detail = "No Ollama models currently loaded"
    except Exception:
        pass

    return [
        CheckResult(
            name="gpu.vram",
            group="gpu",
            status=status,
            message=msg,
            detail=detail,
            remediation="docker exec ollama ollama stop <model>"
            if status != Status.HEALTHY
            else None,
            duration_ms=_u._timed(t),
        )
    ]


@check_group("gpu")
async def check_gpu_temperature() -> list[CheckResult]:
    t = time.monotonic()
    rc, out, err = await _nvidia_smi("temperature.gpu")
    if rc != 0:
        return [
            CheckResult(
                name="gpu.temperature",
                group="gpu",
                status=Status.FAILED,
                message="Cannot query temperature",
                detail=err,
                duration_ms=_u._timed(t),
            )
        ]
    # nvidia-smi returns one row per GPU. Take the max temp across
    # GPUs (hottest is the bottleneck for thermal throttling).
    temps: list[int] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            temps.append(int(line))
        except ValueError:
            continue
    if not temps:
        return [
            CheckResult(
                name="gpu.temperature",
                group="gpu",
                status=Status.DEGRADED,
                message=f"Cannot parse temperature: {out}",
                duration_ms=_u._timed(t),
            )
        ]
    temp = max(temps)

    if temp < 80:
        status = Status.HEALTHY
    elif temp < 90:
        status = Status.DEGRADED
    else:
        status = Status.FAILED

    return [
        CheckResult(
            name="gpu.temperature",
            group="gpu",
            status=status,
            message=f"{temp}\u00b0C",
            duration_ms=_u._timed(t),
        )
    ]
