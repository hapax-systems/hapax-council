"""Service dependency graph for dependency-aware remediation.

Models which services depend on which, enabling topological sort of
remediation commands (fix upstream before downstream).
"""

from __future__ import annotations

from collections import deque

# service → list of services it depends on
SERVICE_DEPENDENCIES: dict[str, list[str]] = {
    "litellm": ["postgres", "ollama"],
    "langfuse": ["postgres", "clickhouse", "redis", "minio"],
    "langfuse-worker": ["langfuse", "postgres", "clickhouse", "redis"],
    "open-webui": ["litellm", "ollama"],
    "n8n": ["postgres"],
    "qdrant": [],
    "ollama": [],
    "postgres": [],
    "clickhouse": [],
    "redis": [],
    "minio": [],
    "ntfy": [],
}


def get_dependents(service: str) -> list[str]:
    """Return services that depend on the given service (direct dependents)."""
    return [svc for svc, deps in SERVICE_DEPENDENCIES.items() if service in deps]


def get_dependencies(service: str) -> list[str]:
    """Return services that the given service depends on (direct dependencies)."""
    return SERVICE_DEPENDENCIES.get(service, [])


def remediation_order(services: list[str]) -> list[str]:
    """Topological sort: returns services ordered so dependencies come first.

    If a service isn't in the dependency graph, it's placed at the end.
    """
    # Build subgraph of requested services
    known = set(SERVICE_DEPENDENCIES.keys())
    in_graph = [s for s in services if s in known]
    unknown = [s for s in services if s not in known]

    # Kahn's algorithm
    in_degree: dict[str, int] = {s: 0 for s in in_graph}
    adj: dict[str, list[str]] = {s: [] for s in in_graph}

    for s in in_graph:
        for dep in SERVICE_DEPENDENCIES.get(s, []):
            if dep in in_degree:
                in_degree[s] += 1
                adj[dep].append(s)

    queue: deque[str] = deque(s for s in in_graph if in_degree[s] == 0)
    result: list[str] = []

    while queue:
        node = queue.popleft()
        result.append(node)
        for dependent in adj[node]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    # If there are cycles, append remaining
    remaining = [s for s in in_graph if s not in result]
    return result + remaining + unknown


def impact_analysis(service: str) -> dict[str, list[str]]:
    """Analyze the impact of a service going down.

    Returns {"direct": [...], "transitive": [...]}.
    """
    direct = get_dependents(service)

    # BFS for transitive dependents
    visited = set(direct)
    queue = deque(direct)
    transitive: list[str] = []

    while queue:
        svc = queue.popleft()
        for dep in get_dependents(svc):
            if dep not in visited:
                visited.add(dep)
                transitive.append(dep)
                queue.append(dep)

    return {"direct": direct, "transitive": transitive}
