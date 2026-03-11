"""Session classification across development dimensions."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TagResult:
    """Result of a classification."""
    dimension: str
    value: str
    confidence: float


def classify_work_type(commit_messages: list[str]) -> TagResult:
    """Classify session work type from correlated commit messages."""
    if not commit_messages:
        return TagResult(dimension="work_type", value="unknown", confidence=0.0)

    counts = {"feature": 0, "bugfix": 0, "refactor": 0, "docs": 0, "test": 0, "chore": 0}
    for msg in commit_messages:
        lower = msg.lower().strip()
        if lower.startswith("feat"):
            counts["feature"] += 1
        elif lower.startswith("fix"):
            counts["bugfix"] += 1
        elif lower.startswith("refactor"):
            counts["refactor"] += 1
        elif lower.startswith("doc"):
            counts["docs"] += 1
        elif lower.startswith("test"):
            counts["test"] += 1
        elif lower.startswith("chore"):
            counts["chore"] += 1

    total = sum(counts.values())
    if total == 0:
        return TagResult(dimension="work_type", value="unknown", confidence=0.3)

    winner = max(counts, key=counts.get)
    confidence = counts[winner] / total
    return TagResult(dimension="work_type", value=winner, confidence=confidence)


def classify_interaction_mode(
    user_msg_lengths: list[int],
    parallel: bool = False,
) -> TagResult:
    """Classify interaction mode from user message lengths."""
    if not user_msg_lengths:
        return TagResult(dimension="interaction_mode", value="unknown", confidence=0.0)

    avg_length = sum(user_msg_lengths) / len(user_msg_lengths)
    short_ratio = sum(1 for l in user_msg_lengths if l < 20) / len(user_msg_lengths)

    if parallel:
        base = "parallel-"
    else:
        base = ""

    if short_ratio > 0.7:
        return TagResult(
            dimension="interaction_mode",
            value=f"{base}high-steering",
            confidence=min(short_ratio, 0.95),
        )
    elif avg_length > 100:
        return TagResult(
            dimension="interaction_mode",
            value=f"{base}autonomous",
            confidence=min(avg_length / 200, 0.95),
        )
    else:
        return TagResult(
            dimension="interaction_mode",
            value=f"{base}mixed",
            confidence=0.6,
        )


def classify_env_topology(file_paths: list[str]) -> TagResult:
    """Classify environment topology from file paths touched."""
    if not file_paths:
        return TagResult(dimension="env_topology", value="unknown", confidence=0.0)

    docker_files = sum(1 for p in file_paths if "docker" in p.lower() or "Dockerfile" in p)
    systemd_files = sum(1 for p in file_paths if "systemd/" in p)
    top_dirs = {p.split("/")[0] for p in file_paths if "/" in p}

    if docker_files > 0:
        return TagResult(dimension="env_topology", value="containerized", confidence=0.8)
    if systemd_files > 0:
        return TagResult(dimension="env_topology", value="host-side", confidence=0.7)
    return TagResult(dimension="env_topology", value="single-repo", confidence=0.6)


def classify_session_scale(file_paths: list[str]) -> TagResult:
    """Classify session scale from file paths."""
    if not file_paths:
        return TagResult(dimension="session_scale", value="unknown", confidence=0.0)

    if len(file_paths) == 1:
        return TagResult(dimension="session_scale", value="single-file", confidence=0.95)

    modules = set()
    for p in file_paths:
        parts = p.split("/")
        if len(parts) >= 2:
            modules.add(parts[0])
        else:
            modules.add(p)

    if len(modules) >= 3:
        return TagResult(dimension="session_scale", value="cross-module", confidence=0.8)
    elif len(modules) == 2:
        return TagResult(dimension="session_scale", value="multi-module", confidence=0.7)
    else:
        return TagResult(dimension="session_scale", value="single-module", confidence=0.7)
