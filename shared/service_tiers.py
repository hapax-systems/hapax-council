"""Service tier classification for health check prioritization.

Tiers control alert severity, nudge priority, and overall status weighting.
T3 failures alone → DEGRADED (not FAILED) at the report level.
"""

from __future__ import annotations

from enum import IntEnum


class ServiceTier(IntEnum):
    """Service criticality tiers — lower number = more critical."""

    CRITICAL = 0  # Core infrastructure: data loss / total outage if down
    IMPORTANT = 1  # Key features: significant capability loss if down
    OBSERVABILITY = 2  # Monitoring/UI: reduced visibility if down
    OPTIONAL = 3  # Nice-to-have: no operational impact if down


# Map individual check names → tier.
# Checks not listed fall back to their group default (see GROUP_DEFAULTS).
TIER_MAP: dict[str, ServiceTier] = {
    # T0 — Critical
    "docker.qdrant": ServiceTier.CRITICAL,
    "docker.ollama": ServiceTier.CRITICAL,
    "docker.postgres": ServiceTier.CRITICAL,
    "docker.litellm": ServiceTier.CRITICAL,
    "endpoints.litellm": ServiceTier.CRITICAL,
    "endpoints.ollama": ServiceTier.CRITICAL,
    "gpu.available": ServiceTier.CRITICAL,
    "qdrant.health": ServiceTier.CRITICAL,
    # T1 — Important
    "docker.langfuse": ServiceTier.IMPORTANT,
    "docker.langfuse-worker": ServiceTier.IMPORTANT,
    "endpoints.langfuse": ServiceTier.IMPORTANT,
    # T2 — Observability
    "docker.open-webui": ServiceTier.OBSERVABILITY,
    "connectivity.ntfy": ServiceTier.OBSERVABILITY,
    "connectivity.n8n": ServiceTier.OBSERVABILITY,
    # T3 — Optional
    "connectivity.tailscale": ServiceTier.OPTIONAL,
    "connectivity.obsidian": ServiceTier.OPTIONAL,
    "connectivity.gdrive-sync": ServiceTier.OPTIONAL,
}

# Default tier for check groups (used when a specific check name isn't in TIER_MAP).
GROUP_DEFAULTS: dict[str, ServiceTier] = {
    "docker": ServiceTier.IMPORTANT,
    "gpu": ServiceTier.IMPORTANT,
    "systemd": ServiceTier.IMPORTANT,
    "qdrant": ServiceTier.CRITICAL,
    "profiles": ServiceTier.OBSERVABILITY,
    "endpoints": ServiceTier.IMPORTANT,
    "credentials": ServiceTier.IMPORTANT,
    "disk": ServiceTier.IMPORTANT,
    "models": ServiceTier.IMPORTANT,
    "auth": ServiceTier.IMPORTANT,
    "connectivity": ServiceTier.OPTIONAL,
    "latency": ServiceTier.IMPORTANT,
    "secrets": ServiceTier.IMPORTANT,
    "queues": ServiceTier.OBSERVABILITY,
    "budget": ServiceTier.OBSERVABILITY,
    "capacity": ServiceTier.IMPORTANT,
    "axioms": ServiceTier.OBSERVABILITY,
    "skills": ServiceTier.OBSERVABILITY,
}


def tier_for_check(check_name: str, group: str = "") -> ServiceTier:
    """Look up the tier for a check by name, falling back to group default."""
    if check_name in TIER_MAP:
        return TIER_MAP[check_name]
    # Infer group from check name if not provided (e.g. "docker.qdrant" → "docker")
    g = group or check_name.split(".")[0]
    return GROUP_DEFAULTS.get(g, ServiceTier.IMPORTANT)


# Nudge priority scores by tier
TIER_NUDGE_SCORES: dict[ServiceTier, int] = {
    ServiceTier.CRITICAL: 100,
    ServiceTier.IMPORTANT: 85,
    ServiceTier.OBSERVABILITY: 50,
    ServiceTier.OPTIONAL: 25,
}
