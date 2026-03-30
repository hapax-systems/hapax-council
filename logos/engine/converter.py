"""ChangeEvent → Impingement converter.

Translates filesystem events from the reactive engine's watcher into
Impingement objects for the CapabilityRegistry broadcast. Assigns
strength based on doc_type/path patterns and detects interrupt tokens
for safety-critical file changes.

Non-breaking: sits between watcher and rule evaluation. Does not
modify ChangeEvent or rule logic.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from logos.engine.models import ChangeEvent
from shared.impingement import Impingement, ImpingementType

_log = logging.getLogger(__name__)

# Strength mapping by doc_type / path pattern
_STRENGTH_MAP: dict[str, float] = {
    # High priority
    "axiom": 0.95,
    "consent": 0.90,
    "health": 0.85,
    "governance": 0.85,
    # Medium priority
    "profile": 0.70,
    "briefing": 0.65,
    "drift": 0.60,
    "sdlc": 0.60,
    # Lower priority
    "rag-source": 0.50,
    "knowledge": 0.50,
    "audio": 0.40,
    "config": 0.40,
}

# Interrupt tokens for critical path changes
_INTERRUPT_PATTERNS: dict[str, str] = {
    "axioms/registry.yaml": "axiom_config_changed",
    "axioms/implications/": "axiom_implication_changed",
    "axioms/contracts/": "consent_contract_changed",
    "health-history.jsonl": "health_status_changed",
    ".envrc": "secrets_changed",
}


def _compute_strength(event: ChangeEvent) -> float:
    """Compute impingement strength from event metadata."""
    # Check doc_type first
    if event.doc_type:
        for prefix, strength in _STRENGTH_MAP.items():
            if prefix in event.doc_type:
                return strength

    # Check path patterns
    path_str = str(event.path)
    for prefix, strength in _STRENGTH_MAP.items():
        if prefix in path_str:
            return strength

    # Default: moderate strength
    return 0.45


def _detect_interrupt(event: ChangeEvent) -> str | None:
    """Check if event matches an interrupt token pattern."""
    path_str = str(event.path)
    for pattern, token in _INTERRUPT_PATTERNS.items():
        if pattern in path_str:
            return token
    return None


def _read_stimmung_stance() -> str:
    """Read current stimmung stance for context enrichment."""
    try:
        path = Path("/dev/shm/hapax-stimmung/state.json")
        if path.exists():
            data = json.loads(path.read_text())
            return data.get("overall_stance", "unknown")
    except Exception:
        pass
    return "unknown"


def convert(event: ChangeEvent) -> Impingement:
    """Convert a ChangeEvent to an Impingement.

    The converted Impingement carries the event's metadata in its
    content dict, enabling RuleCapability wrappers to reconstruct
    the original ChangeEvent for backwards-compatible rule evaluation.
    """
    strength = _compute_strength(event)
    interrupt_token = _detect_interrupt(event)
    imp_type = (
        ImpingementType.PATTERN_MATCH if interrupt_token else ImpingementType.STATISTICAL_DEVIATION
    )

    imp = Impingement(
        timestamp=time.time(),
        source=f"engine.{event.subdirectory}",
        type=imp_type,
        strength=strength,
        content={
            "path": str(event.path),
            "event_type": event.event_type,
            "doc_type": event.doc_type or "",
            "subdirectory": event.subdirectory,
            "source_service": event.source_service or "",
        },
        context={
            "stimmung_stance": _read_stimmung_stance(),
        },
        interrupt_token=interrupt_token,
    )

    # Compute embedding for affordance retrieval (non-blocking, best-effort)
    try:
        from logos._config import embed_safe
        from shared.impingement import render_impingement_text

        text = render_impingement_text(imp)
        vec = embed_safe(text, prefix="search_query")
        if vec is not None:
            imp = imp.model_copy(update={"embedding": vec})
    except Exception:
        pass  # embedding is optional enrichment

    return imp
