"""Service latency checks (HTTP and TCP)."""

from __future__ import annotations

import asyncio
import time
from urllib.request import Request, urlopen

from .. import constants as _c
from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


async def _tcp_connect_ms(host: str, port: int, timeout: float = 3.0) -> float | None:
    """Measure TCP connect time in milliseconds. Returns None on failure."""
    import socket as _socket

    loop = asyncio.get_running_loop()

    def _connect() -> float | None:
        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            t0 = time.monotonic()
            sock.connect((host, port))
            return (time.monotonic() - t0) * 1000
        except (TimeoutError, OSError):
            return None
        finally:
            sock.close()

    return await loop.run_in_executor(None, _connect)


async def _http_latency_ms(url: str, timeout: float = 3.0) -> float | None:
    """Measure HTTP response time in milliseconds. Returns None on failure."""

    def _timed_fetch() -> float | None:
        req = Request(url)
        t0 = time.monotonic()
        try:
            with urlopen(req, timeout=timeout) as resp:
                resp.read()
                if 200 <= resp.status < 400:
                    return (time.monotonic() - t0) * 1000
        except Exception:
            pass
        return None

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _timed_fetch)


def _get_threshold(check_name: str, default: float) -> float:
    """Load threshold override if available, else return default."""
    try:
        from agents._threshold_tuner import get_threshold

        return get_threshold(check_name, default)
    except Exception:
        return default


@check_group("latency")
async def check_service_latency() -> list[CheckResult]:
    """Check HTTP response times for core services."""
    results: list[CheckResult] = []
    for name, (url, default_ms) in _c.LATENCY_THRESHOLDS.items():
        t = time.monotonic()
        threshold_ms = _get_threshold(name, default_ms)
        latency = await _http_latency_ms(url)
        if latency is None:
            results.append(
                CheckResult(
                    name=name,
                    group="latency",
                    status=Status.FAILED,
                    message="unreachable",
                    duration_ms=_u._timed(t),
                )
            )
        elif latency > threshold_ms:
            results.append(
                CheckResult(
                    name=name,
                    group="latency",
                    status=Status.DEGRADED,
                    message=f"{latency:.0f}ms (threshold: {threshold_ms:.0f}ms)",
                    duration_ms=_u._timed(t),
                )
            )
        else:
            results.append(
                CheckResult(
                    name=name,
                    group="latency",
                    status=Status.HEALTHY,
                    message=f"{latency:.0f}ms",
                    duration_ms=_u._timed(t),
                )
            )
    return results


@check_group("latency")
async def check_postgres_latency() -> list[CheckResult]:
    """Check PostgreSQL TCP connect time."""
    t = time.monotonic()
    latency = await _tcp_connect_ms("localhost", 5432)
    threshold = 50.0
    if latency is None:
        return [
            CheckResult(
                name="latency.postgres",
                group="latency",
                status=Status.FAILED,
                message="unreachable",
                duration_ms=_u._timed(t),
            )
        ]
    if latency > threshold:
        return [
            CheckResult(
                name="latency.postgres",
                group="latency",
                status=Status.DEGRADED,
                message=f"{latency:.0f}ms (threshold: {threshold:.0f}ms)",
                duration_ms=_u._timed(t),
            )
        ]
    return [
        CheckResult(
            name="latency.postgres",
            group="latency",
            status=Status.HEALTHY,
            message=f"{latency:.0f}ms",
            duration_ms=_u._timed(t),
        )
    ]
