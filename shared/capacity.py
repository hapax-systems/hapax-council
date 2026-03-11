"""Capacity monitoring and exhaustion forecasting.

Collects disk, VRAM, Qdrant points, and Docker volume usage. With enough
historical data points (min 5), performs linear regression to forecast
when resources will be exhausted.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from shared.config import PROFILES_DIR

CAPACITY_HISTORY = PROFILES_DIR / "capacity-history.jsonl"


@dataclass
class CapacitySnapshot:
    timestamp: str = ""
    disk_used_gb: float = 0.0
    disk_total_gb: float = 0.0
    disk_pct: float = 0.0
    vram_used_mb: float = 0.0
    vram_total_mb: float = 0.0
    qdrant_points: int = 0
    docker_disk_gb: float = 0.0

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "disk_used_gb": self.disk_used_gb,
            "disk_total_gb": self.disk_total_gb,
            "disk_pct": self.disk_pct,
            "vram_used_mb": self.vram_used_mb,
            "vram_total_mb": self.vram_total_mb,
            "qdrant_points": self.qdrant_points,
            "docker_disk_gb": self.docker_disk_gb,
        }

    @classmethod
    def from_dict(cls, d: dict) -> CapacitySnapshot:
        return cls(
            timestamp=d.get("timestamp", ""),
            disk_used_gb=d.get("disk_used_gb", 0.0),
            disk_total_gb=d.get("disk_total_gb", 0.0),
            disk_pct=d.get("disk_pct", 0.0),
            vram_used_mb=d.get("vram_used_mb", 0.0),
            vram_total_mb=d.get("vram_total_mb", 0.0),
            qdrant_points=d.get("qdrant_points", 0),
            docker_disk_gb=d.get("docker_disk_gb", 0.0),
        )


@dataclass
class ExhaustionForecast:
    resource: str
    current_value: float
    max_value: float
    days_to_exhaustion: float | None = None  # None = not enough data or stable
    trend: str = "stable"  # "growing", "stable", "shrinking"

    def is_warning(self, threshold_days: float = 7.0) -> bool:
        return self.days_to_exhaustion is not None and self.days_to_exhaustion < threshold_days


def collect_capacity() -> CapacitySnapshot:
    """Collect current capacity metrics from the system."""
    now = datetime.now(UTC).isoformat()

    # Disk usage (home partition)
    from shared.config import HAPAX_HOME

    usage = shutil.disk_usage(str(HAPAX_HOME))
    disk_used = usage.used / (1024**3)
    disk_total = usage.total / (1024**3)
    disk_pct = (usage.used / usage.total) * 100 if usage.total else 0.0

    # VRAM (nvidia-smi, best-effort)
    vram_used = 0.0
    vram_total = 0.0
    try:
        import subprocess

        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(",")
            if len(parts) >= 2:
                vram_used = float(parts[0].strip())
                vram_total = float(parts[1].strip())
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass

    # Qdrant points (best-effort)
    qdrant_points = 0
    try:
        import json as _json
        from urllib.request import urlopen

        resp = urlopen("http://localhost:6333/collections", timeout=3)
        data = _json.loads(resp.read())
        for coll in data.get("result", {}).get("collections", []):
            name = coll.get("name", "")
            try:
                resp2 = urlopen(f"http://localhost:6333/collections/{name}", timeout=3)
                cdata = _json.loads(resp2.read())
                qdrant_points += cdata.get("result", {}).get("points_count", 0)
            except Exception:
                pass
    except Exception:
        pass

    # Docker disk (best-effort via docker system df)
    docker_disk = 0.0
    try:
        import subprocess

        result = subprocess.run(
            ["docker", "system", "df", "--format", "{{.Size}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                line = line.strip().upper()
                multiplier = 1.0
                if "GB" in line:
                    multiplier = 1.0
                elif "MB" in line:
                    multiplier = 0.001
                elif "KB" in line:
                    multiplier = 0.000001
                try:
                    num = float(
                        line.replace("GB", "")
                        .replace("MB", "")
                        .replace("KB", "")
                        .replace("B", "")
                        .strip()
                    )
                    docker_disk += num * multiplier
                except ValueError:
                    pass
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return CapacitySnapshot(
        timestamp=now,
        disk_used_gb=round(disk_used, 2),
        disk_total_gb=round(disk_total, 2),
        disk_pct=round(disk_pct, 1),
        vram_used_mb=round(vram_used, 0),
        vram_total_mb=round(vram_total, 0),
        qdrant_points=qdrant_points,
        docker_disk_gb=round(docker_disk, 2),
    )


def append_capacity_snapshot(
    snapshot: CapacitySnapshot | None = None,
    path: Path | None = None,
) -> None:
    """Append a capacity snapshot to the history file."""
    path = path or CAPACITY_HISTORY
    if snapshot is None:
        snapshot = collect_capacity()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(snapshot.to_dict()) + "\n")


def _linear_regression(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Simple least-squares linear regression. Returns (slope, intercept)."""
    n = len(xs)
    if n < 2:
        return (0.0, ys[0] if ys else 0.0)
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys, strict=False))
    sum_x2 = sum(x * x for x in xs)
    denom = n * sum_x2 - sum_x * sum_x
    if abs(denom) < 1e-10:
        return (0.0, sum_y / n)
    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    return (slope, intercept)


def forecast_exhaustion(
    path: Path | None = None,
    min_points: int = 5,
) -> list[ExhaustionForecast]:
    """Forecast resource exhaustion from capacity history.

    Returns forecasts for disk, VRAM, and Qdrant. Requires at least `min_points`
    data points for a meaningful forecast.
    """
    path = path or CAPACITY_HISTORY
    if not path.exists():
        return []

    entries = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if len(entries) < min_points:
        return []

    # Convert timestamps to days-from-first
    base_ts = None
    days: list[float] = []
    for e in entries:
        try:
            dt = datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00"))
            if base_ts is None:
                base_ts = dt
            days.append((dt - base_ts).total_seconds() / 86400)
        except (ValueError, KeyError):
            days.append(0.0)

    forecasts = []

    # Disk
    disk_vals = [e.get("disk_used_gb", 0.0) for e in entries]
    disk_total = entries[-1].get("disk_total_gb", 0.0)
    if disk_total > 0:
        slope, intercept = _linear_regression(days, disk_vals)
        current = disk_vals[-1]
        remaining = disk_total - current
        days_left = remaining / slope if slope > 0.01 else None
        forecasts.append(
            ExhaustionForecast(
                resource="disk",
                current_value=current,
                max_value=disk_total,
                days_to_exhaustion=round(days_left, 1) if days_left else None,
                trend="growing" if slope > 0.01 else "shrinking" if slope < -0.01 else "stable",
            )
        )

    # Qdrant points (no hard max, but track growth rate)
    qdrant_vals = [float(e.get("qdrant_points", 0)) for e in entries]
    slope_q, _ = _linear_regression(days, qdrant_vals)
    forecasts.append(
        ExhaustionForecast(
            resource="qdrant_points",
            current_value=qdrant_vals[-1],
            max_value=0,  # no fixed max
            days_to_exhaustion=None,
            trend="growing" if slope_q > 1 else "stable",
        )
    )

    return forecasts
