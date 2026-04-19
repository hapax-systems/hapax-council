"""shared/audit_registry.py — Cross-agent audit point registry.

Enumerates every Gemini call-site in the council runtime as an ``AuditPoint``.
All entries default to ``enabled=False`` — this module is scaffolding. No
audit dispatches without explicit opt-in per call-site.

Governance doc: ``docs/governance/cross-agent-audit.md``.

Flipping an audit point live is a deliberate act — see §12 of the governance
doc for the activation procedure. Never toggle more than one at a time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Severity = Literal["low", "medium", "high", "critical"]
Auditor = Literal["claude-opus", "claude-sonnet"]


@dataclass(frozen=True)
class AuditPoint:
    """A single Gemini call-site eligible for Claude audit.

    Attributes:
        audit_id: Stable identifier (kebab-case). Used as label in Prometheus
            metrics and in audit-finding filenames.
        provider: Gemini model family. Informational; actual routing is
            resolved at the call-site.
        call_site: Repo-relative path plus line number of the invocation.
        purpose: One-line description of what the call does.
        auditor: Which Claude tier audits this point.
        severity_floor: Minimum severity attached to any finding. Individual
            findings can score higher; they cannot score lower.
        sampling_rate: Fraction of calls sampled for audit (0.0..1.0). Only
            consulted when ``enabled=True``.
        enabled: Master switch. ALL DEFAULT OFF — this is scaffolding.
        dimensions: Which of the six audit dimensions are examined. An empty
            tuple defaults to "all six" at audit time.
    """

    audit_id: str
    provider: str
    call_site: str
    purpose: str
    auditor: Auditor
    severity_floor: Severity
    sampling_rate: float = 1.0
    enabled: bool = False
    dimensions: tuple[str, ...] = field(default_factory=tuple)


# --- Registry seed ----------------------------------------------------------
#
# Seeded from ``docs/governance/cross-agent-audit.md`` §2. Any new Gemini
# call-site added to the runtime must register here in the same PR that adds
# the call-site; ``tests/shared/test_audit_registry.py`` enforces that the
# registry has at least the originally enumerated entries.

AUDIT_POINTS: list[AuditPoint] = [
    AuditPoint(
        audit_id="gemini-dmn-multimodal",
        provider="gemini-flash",
        call_site="agents/dmn/ollama.py:148",
        purpose="DMN evaluative tick — multimodal pulse seeing the rendered visual surface.",
        auditor="claude-sonnet",
        severity_floor="medium",
    ),
    AuditPoint(
        audit_id="gemini-vision-observer",
        provider="gemini-flash",
        call_site="agents/vision_observer/__main__.py:61",
        purpose="Vision observer — describes the rendered visual surface for introspection.",
        auditor="claude-sonnet",
        severity_floor="low",
    ),
    AuditPoint(
        audit_id="gemini-vision-tool",
        provider="gemini-2.0-flash",
        call_site="agents/hapax_daimonion/tools.py:846",
        purpose="On-demand visual analysis tool recruited by the daimonion.",
        auditor="claude-sonnet",
        severity_floor="medium",
    ),
    AuditPoint(
        audit_id="gemini-workspace-analyzer",
        provider="gemini-flash",
        call_site="agents/hapax_daimonion/workspace_analyzer.py:70",
        purpose="Multi-image workspace-state classification feeding intent routing.",
        auditor="claude-sonnet",
        severity_floor="medium",
    ),
    AuditPoint(
        audit_id="gemini-screen-analyzer",
        provider="gemini-flash",
        call_site="agents/hapax_daimonion/screen_analyzer.py:51",
        purpose="Screenshot-based activity classification (corporate-boundary adjacent).",
        auditor="claude-sonnet",
        severity_floor="high",
    ),
    AuditPoint(
        audit_id="gemini-workspace-monitor",
        provider="gemini-flash",
        call_site="agents/hapax_daimonion/workspace_monitor.py:53",
        purpose="Workspace monitor orchestration — local/cloud comparison gate.",
        auditor="claude-sonnet",
        severity_floor="medium",
    ),
    AuditPoint(
        audit_id="gemini-daimonion-conversation",
        provider="gemini-2.5-flash-preview-04-17",
        call_site="agents/hapax_daimonion/conversation_pipeline.py:267",
        purpose="Short atmospheric spontaneous speech (operator-audible).",
        auditor="claude-sonnet",
        severity_floor="high",
    ),
    AuditPoint(
        audit_id="gemini-live-session",
        provider="gemini-2.5-flash-preview-native-audio",
        call_site="agents/hapax_daimonion/gemini_live.py:17",
        purpose="Native-audio speech-to-speech session (operator-audible).",
        auditor="claude-opus",
        severity_floor="critical",
    ),
    AuditPoint(
        audit_id="gemini-director-loop",
        provider="gemini-flash",
        call_site="agents/studio_compositor/director_loop.py:442",
        purpose="Studio compositor grounded director (fallback Gemini tier only).",
        auditor="claude-sonnet",
        severity_floor="medium",
    ),
    AuditPoint(
        audit_id="gemini-session-events-ocr",
        provider="gemini-2.0-flash",
        call_site="agents/hapax_daimonion/session_events.py:194",
        purpose="Session-boundary high-res BRIO frame text extraction (OCR).",
        auditor="claude-sonnet",
        severity_floor="medium",
    ),
    AuditPoint(
        audit_id="gemini-daimonion-reasoning",
        provider="gemini-2.5-flash-preview-04-17",
        call_site="agents/hapax_daimonion/conversation_pipeline.py:259",
        purpose="Gemini daimonion reasoning pass in the conversation pipeline.",
        auditor="claude-sonnet",
        severity_floor="medium",
    ),
]


# --- Query helpers ----------------------------------------------------------


def get_by_id(audit_id: str) -> AuditPoint | None:
    """Return the ``AuditPoint`` matching ``audit_id``, or ``None``."""
    for point in AUDIT_POINTS:
        if point.audit_id == audit_id:
            return point
    return None


def active_points() -> list[AuditPoint]:
    """Return every audit point with ``enabled=True``.

    In scaffolding posture this always returns an empty list. Tests rely on
    this invariant — see ``test_audit_registry.py``.
    """
    return [p for p in AUDIT_POINTS if p.enabled]


def by_auditor(auditor: Auditor) -> list[AuditPoint]:
    """Return every audit point (enabled or not) routed to ``auditor``."""
    return [p for p in AUDIT_POINTS if p.auditor == auditor]


def by_severity_floor(floor: Severity) -> list[AuditPoint]:
    """Return every audit point with ``severity_floor`` matching ``floor``."""
    return [p for p in AUDIT_POINTS if p.severity_floor == floor]


__all__ = [
    "AUDIT_POINTS",
    "AuditPoint",
    "Auditor",
    "Severity",
    "active_points",
    "by_auditor",
    "by_severity_floor",
    "get_by_id",
]
