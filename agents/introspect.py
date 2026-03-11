"""introspect.py — Live infrastructure manifest generator.

Queries the actual system state and produces a structured JSON snapshot of
everything that's running: Docker containers, systemd units, Qdrant collections,
Ollama models, LiteLLM routes, ports, volumes, timers, GPU state.

Zero LLM calls. Pure deterministic inspection. The output is the "source of truth"
for drift detection against documentation.

Usage:
    uv run python -m agents.introspect              # Human-readable summary
    uv run python -m agents.introspect --json        # Full JSON manifest
    uv run python -m agents.introspect --save        # Save to profiles/manifest.json
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from agents.health_monitor import run_cmd, http_get


# ── Schemas ──────────────────────────────────────────────────────────────────

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


# ── Collectors ───────────────────────────────────────────────────────────────

from shared.config import PROFILES_DIR, LLM_STACK_DIR, PASSWORD_STORE_DIR
COMPOSE_FILE = LLM_STACK_DIR / "docker-compose.yml"
PASSWORD_STORE = PASSWORD_STORE_DIR


async def collect_docker() -> tuple[str, list[ContainerInfo]]:
    rc, ver, _ = await run_cmd(["docker", "info", "--format", "{{.ServerVersion}}"])
    version = ver.strip() if rc == 0 else ""

    rc, out, _ = await run_cmd([
        "docker", "compose", "-f", str(COMPOSE_FILE), "ps", "--format", "json",
    ])
    containers = []
    if rc == 0 and out:
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                c = json.loads(line)
                ports = []
                for p in c.get("Publishers", []):
                    if p.get("PublishedPort"):
                        ports.append(f"{p.get('URL', '')}:{p['PublishedPort']}->{p['TargetPort']}/{p.get('Protocol', 'tcp')}")
                containers.append(ContainerInfo(
                    name=c.get("Name", ""),
                    service=c.get("Service", ""),
                    image=c.get("Image", ""),
                    state=c.get("State", ""),
                    health=c.get("Health", ""),
                    ports=ports,
                ))
            except (json.JSONDecodeError, KeyError):
                continue

    return version, containers


async def collect_systemd() -> tuple[list[SystemdUnit], list[SystemdUnit]]:
    services = []
    timers = []

    # List user services
    rc, out, _ = await run_cmd([
        "systemctl", "--user", "list-units", "--type=service",
        "--no-pager", "--no-legend", "--plain",
    ])
    if rc == 0 and out:
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 4:
                name = parts[0]
                active = parts[2]  # active/inactive
                # Get enabled status
                rc2, en, _ = await run_cmd(["systemctl", "--user", "is-enabled", name])
                # Get description
                rc3, desc, _ = await run_cmd([
                    "systemctl", "--user", "show", name, "--property=Description", "--value",
                ])
                services.append(SystemdUnit(
                    name=name, type="service",
                    active=active, enabled=en.strip() if rc2 == 0 else "unknown",
                    description=desc.strip() if rc3 == 0 else "",
                ))

    # List user timers
    rc, out, _ = await run_cmd([
        "systemctl", "--user", "list-units", "--type=timer",
        "--no-pager", "--no-legend", "--plain",
    ])
    if rc == 0 and out:
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 4:
                name = parts[0]
                active = parts[2]
                rc2, en, _ = await run_cmd(["systemctl", "--user", "is-enabled", name])
                rc3, desc, _ = await run_cmd([
                    "systemctl", "--user", "show", name, "--property=Description", "--value",
                ])
                timers.append(SystemdUnit(
                    name=name, type="timer",
                    active=active, enabled=en.strip() if rc2 == 0 else "unknown",
                    description=desc.strip() if rc3 == 0 else "",
                ))

    return services, timers


async def collect_qdrant() -> list[QdrantCollection]:
    code, body = await http_get("http://localhost:6333/collections")
    if code != 200:
        return []

    try:
        data = json.loads(body)
        names = [c["name"] for c in data.get("result", {}).get("collections", [])]
    except (json.JSONDecodeError, KeyError):
        return []

    collections = []
    for name in sorted(names):
        code2, body2 = await http_get(f"http://localhost:6333/collections/{name}")
        if code2 == 200:
            try:
                r = json.loads(body2).get("result", {})
                config = r.get("config", {}).get("params", {}).get("vectors", {})
                collections.append(QdrantCollection(
                    name=name,
                    points_count=r.get("points_count", 0),
                    vectors_size=config.get("size", 768),
                    distance=config.get("distance", "Cosine"),
                ))
            except (json.JSONDecodeError, KeyError):
                collections.append(QdrantCollection(name=name))

    return collections


async def collect_ollama() -> list[OllamaModel]:
    code, body = await http_get("http://localhost:11434/api/tags")
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
    rc, out, _ = await run_cmd([
        "nvidia-smi",
        "--query-gpu=name,driver_version,memory.total,memory.used,memory.free,temperature.gpu",
        "--format=csv,noheader,nounits",
    ])
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

    # Get loaded models
    code, body = await http_get("http://localhost:11434/api/ps", timeout=2.0)
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

    from urllib.request import Request, urlopen
    from urllib.error import URLError

    def _fetch():
        req = Request(
            "http://localhost:4000/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        try:
            with urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            return {}

    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, _fetch)

    return [
        LiteLLMRoute(model_name=m.get("id", ""))
        for m in data.get("data", [])
    ]


async def collect_disk() -> list[DiskInfo]:
    rc, out, _ = await run_cmd(["df", "-h", "--output=target,size,used,avail,pcent", "/home"])
    if rc != 0:
        return []

    disks = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 5:
            try:
                pct = int(parts[4].rstrip("%"))
            except ValueError:
                pct = 0
            disks.append(DiskInfo(
                mount=parts[0], size=parts[1], used=parts[2],
                available=parts[3], use_percent=pct,
            ))
    return disks


def collect_pass_entries() -> list[str]:
    entries = []
    if PASSWORD_STORE.is_dir():
        for gpg in sorted(PASSWORD_STORE.rglob("*.gpg")):
            entry = str(gpg.relative_to(PASSWORD_STORE)).removesuffix(".gpg")
            entries.append(entry)
    return entries


def collect_profile_files() -> list[str]:
    if not PROFILES_DIR.is_dir():
        return []
    return sorted(str(f.name) for f in PROFILES_DIR.iterdir() if f.is_file())


async def collect_listening_ports() -> list[str]:
    """Get ports bound to 127.0.0.1 by our stack."""
    rc, out, _ = await run_cmd(["ss", "-tlnp"])
    if rc != 0:
        return []

    ports = []
    for line in out.splitlines()[1:]:
        if "127.0.0.1" in line:
            parts = line.split()
            if len(parts) >= 4:
                addr = parts[3]
                ports.append(addr)
    return sorted(set(ports))


# ── Main collector ───────────────────────────────────────────────────────────

async def generate_manifest() -> InfrastructureManifest:
    """Collect all infrastructure state into a single manifest."""
    # Run collectors in parallel
    (docker_version, containers), (services, timers_list), collections, models, gpu, routes, disks, ports = (
        await asyncio.gather(
            collect_docker(),
            collect_systemd(),
            collect_qdrant(),
            collect_ollama(),
            collect_gpu(),
            collect_litellm_routes(),
            collect_disk(),
            collect_listening_ports(),
        )
    )

    # OS info
    rc, os_info, _ = await run_cmd(["uname", "-sr"])

    return InfrastructureManifest(
        timestamp=datetime.now(timezone.utc).isoformat(),
        hostname=socket.gethostname(),
        os_info=os_info.strip() if rc == 0 else "",
        docker_version=docker_version,
        containers=containers,
        systemd_units=services,
        systemd_timers=timers_list,
        qdrant_collections=collections,
        ollama_models=models,
        gpu=gpu,
        litellm_routes=routes,
        disk=disks,
        listening_ports=ports,
        pass_entries=collect_pass_entries(),
        compose_file=str(COMPOSE_FILE) if COMPOSE_FILE.is_file() else "",
        profile_files=collect_profile_files(),
    )


def format_summary(m: InfrastructureManifest) -> str:
    """Human-readable summary of the manifest."""
    lines = [
        f"Infrastructure Manifest — {m.hostname} — {m.timestamp[:19]}",
        f"OS: {m.os_info}  Docker: {m.docker_version}",
        "",
    ]

    if m.gpu:
        lines.append(f"GPU: {m.gpu.name} (driver {m.gpu.driver})")
        lines.append(f"  VRAM: {m.gpu.vram_used_mb}/{m.gpu.vram_total_mb} MiB ({m.gpu.temperature_c}°C)")
        if m.gpu.loaded_models:
            lines.append(f"  Loaded: {', '.join(m.gpu.loaded_models)}")
        lines.append("")

    lines.append(f"Docker Containers ({len(m.containers)}):")
    for c in m.containers:
        health = f" ({c.health})" if c.health else ""
        ports = f"  [{', '.join(c.ports)}]" if c.ports else ""
        lines.append(f"  {c.service:20s} {c.state}{health}{ports}")
    lines.append("")

    lines.append(f"Systemd Services ({len(m.systemd_units)}):")
    for u in m.systemd_units:
        lines.append(f"  {u.name:35s} {u.active:10s} ({u.enabled})")
    lines.append("")

    lines.append(f"Systemd Timers ({len(m.systemd_timers)}):")
    for u in m.systemd_timers:
        lines.append(f"  {u.name:35s} {u.active:10s} ({u.enabled})")
    lines.append("")

    lines.append(f"Qdrant Collections ({len(m.qdrant_collections)}):")
    for c in m.qdrant_collections:
        lines.append(f"  {c.name:25s} {c.points_count:6d} points  ({c.vectors_size}d {c.distance})")
    lines.append("")

    lines.append(f"Ollama Models ({len(m.ollama_models)}):")
    for om in m.ollama_models:
        size_mb = om.size_bytes // (1024 * 1024)
        lines.append(f"  {om.name:45s} {size_mb:6d} MB")
    lines.append("")

    lines.append(f"LiteLLM Routes ({len(m.litellm_routes)}):")
    for r in m.litellm_routes:
        lines.append(f"  {r.model_name}")
    lines.append("")

    lines.append(f"Disk:")
    for d in m.disk:
        lines.append(f"  {d.mount:15s} {d.used}/{d.size} ({d.use_percent}%)")
    lines.append("")

    lines.append(f"Pass Entries ({len(m.pass_entries)}): {', '.join(m.pass_entries)}")
    lines.append(f"Profile Files: {', '.join(m.profile_files)}")
    lines.append(f"Listening Ports: {', '.join(m.listening_ports)}")

    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="Infrastructure manifest generator — live system state snapshot",
        prog="python -m agents.introspect",
    )
    parser.add_argument("--json", action="store_true", help="Full JSON manifest")
    parser.add_argument("--save", action="store_true", help="Save to profiles/manifest.json")
    args = parser.parse_args()

    manifest = await generate_manifest()

    if args.json:
        print(manifest.model_dump_json(indent=2))
    elif args.save:
        out_path = PROFILES_DIR / "manifest.json"
        out_path.write_text(manifest.model_dump_json(indent=2))
        print(f"Saved to {out_path}")
    else:
        print(format_summary(manifest))


if __name__ == "__main__":
    asyncio.run(main())
