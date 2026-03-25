"""GPU and VRAM data collector for the logos.

Reads from profiles/infra-snapshot.json written by the host-side health
monitor, which has access to nvidia-smi and Ollama. The logos-api runs
inside Docker where GPU commands are unavailable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from shared.config import PROFILES_DIR

INFRA_SNAPSHOT = PROFILES_DIR / "infra-snapshot.json"


@dataclass
class VramSnapshot:
    name: str = ""
    total_mb: int = 0
    used_mb: int = 0
    free_mb: int = 0
    usage_pct: float = 0.0
    temperature_c: int = 0
    loaded_models: list[str] = field(default_factory=list)


async def collect_vram() -> VramSnapshot | None:
    """Read GPU state from infra snapshot."""
    try:
        snapshot = json.loads(INFRA_SNAPSHOT.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None

    gpu = snapshot.get("gpu")
    if not gpu:
        return None

    total = gpu.get("total_mb", 0)
    used = gpu.get("used_mb", 0)
    return VramSnapshot(
        name=gpu.get("name", "RTX 3090"),
        total_mb=total,
        used_mb=used,
        free_mb=gpu.get("free_mb", total - used),
        usage_pct=round((used / total) * 100, 1) if total > 0 else 0.0,
        temperature_c=gpu.get("temperature_c", 0),
        loaded_models=gpu.get("loaded_models", []),
    )
