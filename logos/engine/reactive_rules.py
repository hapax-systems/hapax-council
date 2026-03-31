"""logos/engine/reactive_rules.py — Reactive engine rules (orchestrator).

Rules are organized by phase:
  Phase 0 (deterministic): rules_phase0.py
  Phase 1 (local GPU):     rules_phase1.py
  Phase 2 (cloud LLM):     rules_phase2.py

This file re-exports everything for backward compatibility.
"""

from __future__ import annotations

import logging

from logos.engine.rules import Rule

from .rules_phase0 import (
    BIOMETRIC_STATE_RULE,
    CARRIER_INTAKE_RULE,
    COLLECTOR_REFRESH_RULE,
    CONFIG_CHANGED_RULE,
    CONSENT_TRANSITION_RULE,
    PHONE_HEALTH_SUMMARY_RULE,
    PRESENCE_TRANSITION_RULE,
    SDLC_EVENT_RULE,
    _audio_archive_sidecar_filter,
    _audio_archive_sidecar_produce,
    _collector_refresh_filter,
    _collector_refresh_produce,
    _config_changed_filter,
    _config_changed_produce,
    _sdlc_event_filter,
    _sdlc_event_produce,
    get_carrier_registry,
    set_carrier_registry,
)
from .rules_phase1 import (
    AUDIO_ARCHIVE_SIDECAR_RULE,
    AUDIO_CLAP_INDEXED_RULE,
    RAG_SOURCE_RULE,
    _audio_clap_indexed_filter,
    _audio_clap_indexed_produce,
)
from .rules_phase2 import (
    CORRECTION_SYNTHESIS_RULE,
    KNOWLEDGE_MAINT_RULE,
    PATTERN_CONSOLIDATION_RULE,
    QuietWindowScheduler,
    get_knowledge_scheduler,
)

_log = logging.getLogger(__name__)


# ── Registration ────────────────────────────────────────────────────────────

ALL_RULES: list[Rule] = [
    COLLECTOR_REFRESH_RULE,
    CONFIG_CHANGED_RULE,
    SDLC_EVENT_RULE,
    RAG_SOURCE_RULE,
    AUDIO_ARCHIVE_SIDECAR_RULE,
    AUDIO_CLAP_INDEXED_RULE,
    CARRIER_INTAKE_RULE,
    KNOWLEDGE_MAINT_RULE,
    PATTERN_CONSOLIDATION_RULE,
    CORRECTION_SYNTHESIS_RULE,
    PRESENCE_TRANSITION_RULE,
    CONSENT_TRANSITION_RULE,
    BIOMETRIC_STATE_RULE,
    PHONE_HEALTH_SUMMARY_RULE,
]

# Backwards compat alias
INFRASTRUCTURE_RULES = ALL_RULES


def register_rules(registry) -> None:
    """Register all reactive rules on a RuleRegistry."""
    for rule in ALL_RULES:
        registry.register(rule)
    _log.info("Registered %d reactive rules", len(ALL_RULES))


# Backwards compat alias
register_infrastructure_rules = register_rules

# Re-export for backward compat (tests import these)
__all__ = [
    "ALL_RULES",
    "INFRASTRUCTURE_RULES",
    "QuietWindowScheduler",
    "_audio_archive_sidecar_filter",
    "_audio_archive_sidecar_produce",
    "_audio_clap_indexed_filter",
    "_audio_clap_indexed_produce",
    "_collector_refresh_filter",
    "_collector_refresh_produce",
    "_config_changed_filter",
    "_config_changed_produce",
    "_sdlc_event_filter",
    "_sdlc_event_produce",
    "get_carrier_registry",
    "get_knowledge_scheduler",
    "register_infrastructure_rules",
    "register_rules",
    "set_carrier_registry",
]
