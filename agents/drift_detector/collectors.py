"""Data collectors — Qdrant, Ollama, GPU, LiteLLM, disk, pass, profiles.

Infrastructure collectors (Docker, systemd, ports) are in collectors_infra.py.
"""

from __future__ import annotations

import asyncio
import json
import os
from urllib.request import Request, urlopen

# Re-export infra collectors for backward compatibility
from .collectors_infra import COMPOSE_FILE as COMPOSE_FILE  # noqa: F401
from .collectors_infra import collect_docker as collect_docker  # noqa: F401
from .collectors_infra import collect_listening_ports as collect_listening_ports  # noqa: F401
from .collectors_infra import collect_systemd as collect_systemd  # noqa: F401
from .config import LITELLM_BASE, OLLAMA_URL, PASSWORD_STORE_DIR, PROFILES_DIR
from .introspect import http_get, run_cmd
from .models import DiskInfo, GpuInfo, LiteLLMRoute, OllamaModel, QdrantCollection

PASSWORD_STORE = PASSWORD_STORE_DIR


async def collect_qdrant() -> list[QdrantCollection]:
    code, body = await http_get("http://localhost:6333/collections")
    if code != 200:
        return []

    try:
        data = json.loads(body)
        names = [c["name"] for c in data.get("result", {}).get("collections", [])]
    except (json.JSONDecodeError, KeyError):
        return []

    collections: list[QdrantCollection] = []
    for name in sorted(names):
        code2, body2 = await http_get(f"http://localhost:6333/collections/{name}")
        if code2 == 200:
            try:
                r = json.loads(body2).get("result", {})
                config = r.get("config", {}).get("params", {}).get("vectors", {})
                collections.append(
                    QdrantCollection(
                        name=name,
                        points_count=r.get("points_count", 0),
                        vectors_size=config.get("size", 768),
                        distance=config.get("distance", "Cosine"),
                    )
                )
            except (json.JSONDecodeError, KeyError):
                collections.append(QdrantCollection(name=name))

    return collections


async def collect_ollama() -> list[OllamaModel]:
    code, body = await http_get(f"{OLLAMA_URL}/api/tags")
    if code != 200:
        return []

    try:
        data = json.loads(body)
        return [
            OllamaModel(
                name=m.get("name", ""),
                size_bytes=m.get("size", 0),
                modified_at=m.get("modified_at", ""),
            )
            for m in data.get("models", [])
        ]
    except (json.JSONDecodeError, KeyError):
        return []


async def collect_gpu() -> GpuInfo | None:
    rc, out, _ = await run_cmd(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total,memory.used,memory.free,temperature.gpu",
            "--format=csv,noheader,nounits",
        ]
    )
    if rc != 0:
        return None

    parts = [p.strip() for p in out.split(",")]
    if len(parts) < 6:
        return None

    try:
        gpu = GpuInfo(
            name=parts[0],
            driver=parts[1],
            vram_total_mb=int(parts[2]),
            vram_used_mb=int(parts[3]),
            vram_free_mb=int(parts[4]),
            temperature_c=int(parts[5]),
        )
    except (ValueError, IndexError):
        return None

    code, body = await http_get(f"{OLLAMA_URL}/api/ps", timeout=2.0)
    if code == 200:
        try:
            models = json.loads(body).get("models", [])
            gpu.loaded_models = [m.get("name", "?") for m in models]
        except (json.JSONDecodeError, KeyError):
            pass

    return gpu


async def collect_litellm_routes() -> list[LiteLLMRoute]:
    api_key = os.environ.get("LITELLM_API_KEY", "")
    if not api_key:
        return []

    def _fetch() -> dict:
        req = Request(
            f"{LITELLM_BASE}/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        try:
            with urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            return {}

    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, _fetch)

    return [LiteLLMRoute(model_name=m.get("id", "")) for m in data.get("data", [])]


async def collect_disk() -> list[DiskInfo]:
    rc, out, _ = await run_cmd(["df", "-h", "--output=target,size,used,avail,pcent", "/home"])
    if rc != 0:
        return []

    disks: list[DiskInfo] = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 5:
            try:
                pct = int(parts[4].rstrip("%"))
            except ValueError:
                pct = 0
            disks.append(
                DiskInfo(
                    mount=parts[0],
                    size=parts[1],
                    used=parts[2],
                    available=parts[3],
                    use_percent=pct,
                )
            )
    return disks


def collect_pass_entries() -> list[str]:
    entries: list[str] = []
    if PASSWORD_STORE.is_dir():
        for gpg in sorted(PASSWORD_STORE.rglob("*.gpg")):
            entry = str(gpg.relative_to(PASSWORD_STORE)).removesuffix(".gpg")
            entries.append(entry)
    return entries


def collect_profile_files() -> list[str]:
    if not PROFILES_DIR.is_dir():
        return []
    return sorted(str(f.name) for f in PROFILES_DIR.iterdir() if f.is_file())
