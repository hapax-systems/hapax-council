"""preset.bias heartbeat fallback — chain-mutation backstop.

Background tick that keeps ``recent-recruitment.json`` populated with a
``preset.bias`` family entry when LLM-driven recruitment stalls.

Provenance — `/tmp/effect-cam-orchestration-audit-2026-05-02.md` §4 F1
+ §5 U1 + §7 QW2 (R2):

    director emits compositional_impingement(preset.bias) → 100% flagged
    UNGROUNDED → recent-recruitment.json never gets a preset.bias entry
    → preset_recruitment_consumer.process_preset_recruitment() never
    fires → /dev/shm/hapax-compositor/graph-mutation.json never written
    → 0/24 family-mapped presets and 0/5 transition primitives
    exercised in the live window.

This agent is a STRICT FALLBACK — it never replaces LLM-driven
recruitment. The 30-second tick checks the freshness of the
``preset.bias`` entry; if a fresh (≤60s) entry exists, the heartbeat
no-ops. Only when the entry is stale (>60s) or missing does the
heartbeat write a uniform-sampled family entry, marked
``source: "heartbeat-fallback"`` so observability can distinguish LLM
vs heartbeat origins.

Family list comes from
:func:`agents.studio_compositor.preset_family_selector.family_names` —
the canonical disk inventory — never a hardcoded list. When the
operator edits ``FAMILY_PRESETS`` the heartbeat tracks the change on
the next tick.

When to disable: once the LLM recruitment grounding rate is restored
to >>0% (per §4 F4), this agent becomes redundant. Detect by counting
``preset.bias`` entries with ``source: "llm-recruitment"`` (or absent
``source`` field, which is the legacy LLM path) over a 24h window —
when the LLM rate exceeds 1/min, stop the unit and review.
"""

from __future__ import annotations

from agents.preset_bias_heartbeat.heartbeat import (
    DEFAULT_FRESHNESS_S,
    DEFAULT_TICK_S,
    HEARTBEAT_SOURCE,
    RECRUITMENT_FILE,
    pick_family,
    read_recruitment,
    run_forever,
    tick_once,
    write_heartbeat_entry,
)

__all__ = [
    "DEFAULT_FRESHNESS_S",
    "DEFAULT_TICK_S",
    "HEARTBEAT_SOURCE",
    "RECRUITMENT_FILE",
    "pick_family",
    "read_recruitment",
    "run_forever",
    "tick_once",
    "write_heartbeat_entry",
]
