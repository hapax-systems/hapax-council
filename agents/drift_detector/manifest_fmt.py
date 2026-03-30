"""Human-readable formatting for the infrastructure manifest."""

from __future__ import annotations

import time

from .models import InfrastructureManifest


def format_summary(m: InfrastructureManifest) -> str:
    """Human-readable summary of the manifest."""
    lines = [
        f"Infrastructure Manifest -- {m.hostname} -- {m.timestamp[:19]}",
        f"OS: {m.os_info}  Docker: {m.docker_version}",
        "",
    ]

    if m.gpu:
        lines.append(f"GPU: {m.gpu.name} (driver {m.gpu.driver})")
        lines.append(
            f"  VRAM: {m.gpu.vram_used_mb}/{m.gpu.vram_total_mb} MiB ({m.gpu.temperature_c} C)"
        )
        if m.gpu.loaded_models:
            lines.append(f"  Loaded: {', '.join(m.gpu.loaded_models)}")
        lines.append("")

    lines.append(f"Docker Containers ({len(m.containers)}):")
    for c in m.containers:
        health = f" ({c.health})" if c.health else ""
        ports_str = f"  [{', '.join(c.ports)}]" if c.ports else ""
        lines.append(f"  {c.service:20s} {c.state}{health}{ports_str}")
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

    lines.append("Disk:")
    for d in m.disk:
        lines.append(f"  {d.mount:15s} {d.used}/{d.size} ({d.use_percent}%)")
    lines.append("")

    lines.append(f"Pass Entries ({len(m.pass_entries)}): {', '.join(m.pass_entries)}")
    lines.append(f"Profile Files: {', '.join(m.profile_files)}")
    lines.append(f"Listening Ports: {', '.join(m.listening_ports)}")

    if m.edge_nodes:
        lines.append("")
        lines.append(f"Edge Nodes ({len(m.edge_nodes)}):")
        for node in m.edge_nodes:
            hostname = node.hostname or "unknown"
            role = node.role or "?"
            cpu_temp: float | str = node.cpu_temp_c if node.cpu_temp_c is not None else "?"
            mem_avail: float | str = (
                node.mem_available_mb if node.mem_available_mb is not None else "?"
            )
            age = time.time() - node.last_seen_epoch
            status = "online" if age < 300 else f"stale ({age / 60:.0f}m)"
            lines.append(
                f"  {hostname:15s} ({role:10s}) {status}, CPU {cpu_temp} C, {mem_avail}MB free"
            )

    return "\n".join(lines)
