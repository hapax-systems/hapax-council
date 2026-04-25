"""MonetizationRiskGate — zero-red-flag content invariant (task #165).

Gates candidate capabilities against YouTube monetization risk BEFORE the
affordance pipeline scores them. Sits adjacent to the consent gate in
``shared.affordance_pipeline.AffordancePipeline.select``.

Risk levels (matched on ``OperationalProperties.monetization_risk``):

- **high**: unconditionally blocked on every surface
- **medium**: blocked unless the active ``Programme`` opts the capability
  in via ``Programme.constraints.monetization_opt_ins``
- **low** / **none**: pass through the filter unchanged

The filter is pure (no side effects, no network, no state) in its
Ring-1-only mode. Optional Ring 2 integration (Phase 3) calls an
LLM classifier on the rendered payload and merges the verdict — Ring 2
can ESCALATE the risk but never DE-ESCALATE it (catalog is authoritative
on the floor; Ring 2 catches rendered-payload specifics the catalog
cannot foresee).

References:
    - docs/research/2026-04-19-demonetization-safety-design.md §1, §4
    - docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md §2, §3
"""

from __future__ import annotations

import logging
import os
import random
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol

from shared.affordance import MonetizationRisk
from shared.governance.demonet_metrics import METRICS as _METRICS

# Re-exports for Phase-1 call sites.
__all__ = [
    "MonetizationRisk",
    "MonetizationRiskGate",
    "RiskAssessment",
    "SurfaceKind",
    "reload_whitelist",
    "current_whitelist",
]

_log = logging.getLogger(__name__)

# D-27: Phase 6 egress audit wire — sampling per plan §Phase 6 lines 393-395.
# blocks + high-risk = SAMPLE_HIGH (default 100%); low/none allowed = SAMPLE_LOW
# (default 10%). Disable entirely with HAPAX_DEMONET_AUDIT=0 (incident response).
# Async queue is the proper async-write path (D-27b follow-on); current sync
# write hits a per-instance lock in the writer — acceptable for the recruitment
# path because the lock contention is bounded by sampling.
_AUDIT_ENABLED = os.environ.get("HAPAX_DEMONET_AUDIT", "1") != "0"
_SAMPLE_LOW = float(os.environ.get("HAPAX_EGRESS_AUDIT_SAMPLE_LOW", "0.1"))
_SAMPLE_HIGH = float(os.environ.get("HAPAX_EGRESS_AUDIT_SAMPLE_HIGH", "1.0"))

# D-17: In-process subscriber API so cross-cutting consumers (quiet_frame
# subscriber, future telemetry) can react to gate decisions without
# coupling the gate to those consumers. Each listener is called with
# (assessment, capability_name, programme_id) after the audit write.
# Listener exceptions are caught + logged; never propagate.
from collections.abc import Callable

_AssessListener = Callable[["RiskAssessment", str | None, str | None], None]
_assess_listeners: list[_AssessListener] = []


def register_assess_listener(listener: _AssessListener) -> None:
    """Register an in-process callback fired after every gate decision.

    Callback signature: ``(assessment, capability_name, programme_id)``.
    Called from inside ``_record_and_return()`` after the egress audit
    write. Listener exceptions are caught + logged; the gate's
    correctness cannot depend on listener side effects succeeding.

    Idempotent — re-registering the same callable is a no-op so a module
    that reloads (e.g. in tests) doesn't end up firing twice.
    """
    if listener not in _assess_listeners:
        _assess_listeners.append(listener)


# ── Phase 10: operator whitelist + flagged-payload sink ──────────────────
#
# The whitelist NARROWS Ring 2. It can override a Ring-2 escalation /
# rendered-payload block, but it CANNOT override a Ring-1 ``risk == "high"``
# catalog declaration — that short-circuit fires before any whitelist code.
# Tested in tests/monetization_review/test_whitelist.py::TestNeverBypassesRing1High.
#
# Module-level state because the gate's ``GATE`` singleton is stateless;
# stashing the whitelist on the instance would break the "pure filter"
# contract documented above and force every caller through the singleton.

from agents.monetization_review.flagged_store import FlaggedStore
from agents.monetization_review.whitelist import (
    DEFAULT_WHITELIST_PATH,
    Whitelist,
)

_CURRENT_WHITELIST: Whitelist = Whitelist.empty()
_FLAGGED_STORE: FlaggedStore | None = None


def reload_whitelist(path: Path | None = None) -> Whitelist:
    """Reload the operator whitelist from YAML. Returns the new whitelist.

    Called at module import (so daemon startups pick up the on-disk
    state automatically) and from a SIGHUP handler installed by
    ``agents.monetization_review.cli.install_inprocess_sighup_handler``.
    Idempotent — never raises; malformed YAML reverts to an empty
    whitelist with a warning log so a corrupted file cannot block traffic.
    """
    global _CURRENT_WHITELIST
    _CURRENT_WHITELIST = Whitelist.load(path)
    return _CURRENT_WHITELIST


def current_whitelist() -> Whitelist:
    """Return the active whitelist instance — used by tests + introspection."""
    return _CURRENT_WHITELIST


def _flagged_store() -> FlaggedStore:
    """Lazy-construct the partitioned flagged-payload store."""
    global _FLAGGED_STORE
    if _FLAGGED_STORE is None:
        _FLAGGED_STORE = FlaggedStore()
    return _FLAGGED_STORE


def _maybe_record_flagged(
    assessment: RiskAssessment,
    *,
    capability_name: str,
    rendered_payload: Any,
    programme_id: str | None,
) -> None:
    """Persist a block to the operator-review surface if a payload is present.

    Ring-1-only blocks (no ``rendered_payload`` ever passed to ``assess``)
    are skipped — the operator can't whitelist a payload they never see.
    Ring 1 high catalog blocks are intentionally elided here too because
    the whitelist cannot override them; surfacing them would imply they're
    actionable, which they aren't.
    """
    if assessment.allowed:
        return
    if rendered_payload is None:
        return
    if assessment.risk == "high" and "ring2" not in assessment.reason:
        return  # Ring 1 high — operator review surface elides
    try:
        _flagged_store().record_block(
            capability_name=capability_name,
            surface=assessment.surface.value if assessment.surface else None,
            rendered_payload=rendered_payload,
            risk=assessment.risk,
            reason=assessment.reason,
            programme_id=programme_id,
        )
    except Exception:  # noqa: BLE001 — flagged-store write must not break the gate
        _log.warning("flagged-store write failed", exc_info=True)


def _whitelist_overrides(
    *,
    capability_name: str,
    rendered_payload: Any,
) -> tuple[bool, str]:
    """True iff the active whitelist allows this capability + rendered text.

    Capability-name match wins over payload match (operator's broadest
    explicit decision). Payload match falls back to stringified value.
    """
    cap_match, cap_reason = _CURRENT_WHITELIST.matches_capability(capability_name)
    if cap_match:
        return True, cap_reason
    if rendered_payload is None:
        return False, ""
    return _CURRENT_WHITELIST.matches_payload(rendered_payload)


class SurfaceKind(StrEnum):
    """Where the rendered output would land if emitted.

    Phase 1 records the surface kind on each filter decision for later
    auditing; Phase 6 wires it into the egress JSONL. Phase 3 uses it to
    pick the classifier prompt.
    """

    TTS = "tts"
    CAPTIONS = "captions"
    CHRONICLE = "chronicle"
    OVERLAY = "overlay"
    WARD = "ward"
    NOTIFICATION = "notification"
    LOG = "log"


@dataclass(frozen=True)
class RiskAssessment:
    """Immutable result of a classification or catalog-lookup decision.

    Used by both the pre-flight capability filter (Ring 1) and the
    pre-render classifier (Ring 2, Phase 3) so both rings emit the same
    shape for downstream audit + quiet-frame logic.
    """

    allowed: bool
    risk: MonetizationRisk
    reason: str
    surface: SurfaceKind | None = None


class _CandidateLike(Protocol):
    """Structural type for AffordancePipeline SelectionCandidates.

    Accepts any object exposing ``capability_name`` and ``payload`` — keeps
    the gate independent of affordance_pipeline's import graph.
    """

    capability_name: str
    payload: dict[str, Any]


class _ProgrammeLike(Protocol):
    """Structural type for the Programme that opts-in medium capabilities.

    Phase 1 only reads ``monetization_opt_ins``. The concrete Programme
    model from ``shared.programme`` does not yet have this field (it
    lands in plan Phase 5 — intentionally so); for now the gate treats
    missing programmes and missing opt-ins identically.
    """

    @property
    def monetization_opt_ins(self) -> set[str]: ...


# Risk ordering used by the Ring 1 ↔ Ring 2 escalation merge. Ring 2 can
# raise the effective risk to the strictest of the two verdicts; it
# cannot drop below the catalog-declared floor.
_RISK_ORDER: dict[str, int] = {"none": 0, "low": 1, "medium": 2, "high": 3}


def _max_risk(a: str, b: str) -> str:
    """Return the stricter of two risk strings."""
    return a if _RISK_ORDER.get(a, 0) >= _RISK_ORDER.get(b, 0) else b


def _should_sample_audit(assessment: RiskAssessment) -> bool:
    """Sampling decision per plan §Phase 6.

    Always-write (sample=1.0): blocks (allowed=False), and any high-risk
    decision regardless of allowed. These are governance-critical and the
    audit must capture every one.

    Sampled (sample=SAMPLE_LOW, default 10%): low/none-risk allowed
    decisions. These are the high-volume mundane case from the recruitment
    hot path; sampling keeps the JSONL bounded without losing the ability
    to characterize traffic.

    Off entirely when ``HAPAX_DEMONET_AUDIT=0`` (incident response).
    """
    if not _AUDIT_ENABLED:
        return False
    if not assessment.allowed or assessment.risk == "high":
        return random.random() < _SAMPLE_HIGH
    return random.random() < _SAMPLE_LOW


def _record_and_return(
    assessment: RiskAssessment,
    *,
    capability_name: str | None = None,
    programme_id: str | None = None,
) -> RiskAssessment:
    """Tick the gate-decisions counter, append to the egress audit, return.

    Factored out of ``assess()`` so every return path increments the
    Prometheus counter and lands in the audit JSONL without sprawling
    inline calls. The counter is a no-op when prometheus_client isn't
    installed (see ``shared.governance.demonet_metrics``).

    Audit write (D-27, plan §Phase 6) is sampled per ``_should_sample_audit``
    and uses the module-level ``default_writer()`` singleton. Failures in
    the audit path are logged but never propagated — the gate's correctness
    cannot depend on disk I/O succeeding.
    """
    _METRICS.inc_gate_decision(
        risk=assessment.risk,
        allowed=assessment.allowed,
        surface=assessment.surface.value if assessment.surface else None,
    )
    if capability_name and _should_sample_audit(assessment):
        # Deferred import keeps the gate module's import graph independent
        # of the audit writer for callers (e.g. tests) that mock both.
        try:
            from shared.governance.monetization_egress_audit import default_writer

            default_writer().record(
                capability_name=capability_name,
                assessment=assessment,
                surface=assessment.surface,
                programme_id=programme_id,
            )
        except Exception:  # noqa: BLE001 — audit must never break the gate
            _log.warning("egress audit write failed", exc_info=True)
    # D-17: in-process listeners (quiet_frame subscriber, telemetry, etc.)
    # fire on EVERY decision (no sampling) so transition observers see the
    # full sequence. Each listener wrapped in try/except — listener faults
    # cannot break the gate.
    for listener in _assess_listeners:
        try:
            listener(assessment, capability_name, programme_id)
        except Exception:  # noqa: BLE001 — listener faults must not break gate
            _log.warning("assess listener %s raised; continuing", listener.__name__, exc_info=True)
    return assessment


class MonetizationRiskGate:
    """Pure filter — blocks high-risk always, gates medium-risk on programme.

    No I/O, no caching, no logging in the hot path. A separate audit hook
    (Phase 6) will subscribe to the filter's return value without touching
    the filter itself.

    Ring 2 pre-render classification (Phase 3) is opt-in — callers that
    have a rendered payload and want a second-pass verdict pass
    ``ring2_classifier`` + ``surface`` + ``rendered_payload`` to
    ``assess()``. Call sites without those stay on Ring 1 (catalog-only)
    behavior — zero cost, zero behavior change.
    """

    def assess(
        self,
        candidate: _CandidateLike,
        programme: _ProgrammeLike | None = None,
        *,
        ring2_classifier: Any = None,
        surface: SurfaceKind | None = None,
        rendered_payload: Any = None,
    ) -> RiskAssessment:
        """Return a RiskAssessment without mutating state.

        Called from the pipeline's filter step and also available as a
        standalone helper for ad-hoc audits (plan Phases 6, 10).

        Ring 2 integration (optional): when ``ring2_classifier`` and
        ``surface`` are both provided and the surface is a broadcast
        surface, the classifier is invoked on the rendered payload and
        its verdict is merged with the catalog's ring-1 annotation via
        ``max_risk`` (stricter wins). Classifier failures go through
        ``classify_with_fallback`` which applies the fail-closed policy.
        """
        ring1_risk: MonetizationRisk = candidate.payload.get("monetization_risk", "none")
        ring1_reason = candidate.payload.get("risk_reason") or ""
        name = candidate.capability_name
        # D-27: extract programme_id once for audit propagation. Programme
        # primitive carries `programme_id` per `shared/programme.py`; getattr
        # keeps the gate's structural-typing contract.
        programme_id = getattr(programme, "programme_id", None) if programme else None

        # Short-circuit: ring-1 high is authoritative — no Ring 2 call,
        # no Programme opt-in path. Saves the GPU round-trip on the
        # capabilities catalog already declares unsafe.
        if ring1_risk == "high":
            return _record_and_return(
                RiskAssessment(
                    allowed=False,
                    risk=ring1_risk,
                    reason=f"{name}: high-risk capability blocked unconditionally ({ring1_reason})".strip(
                        " ()"
                    ),
                    surface=surface,
                ),
                capability_name=name,
                programme_id=programme_id,
            )

        # Ring 2 pass — only when caller opted in + surface is broadcast.
        effective_risk: str = ring1_risk
        ring2_reason = ""
        ring2_used = False
        if ring2_classifier is not None and surface is not None:
            # Deferred imports keep this module dependency-light for
            # callers that never use Ring 2.
            from shared.governance.classifier_degradation import classify_with_fallback
            from shared.governance.ring2_prompts import is_broadcast_surface

            if is_broadcast_surface(surface):
                decision = classify_with_fallback(
                    ring2_classifier,
                    capability_name=name,
                    rendered_payload=rendered_payload,
                    surface=surface,
                )
                ring2_used = True
                ring2_reason = decision.assessment.reason
                # Ring 2 can escalate the risk but never de-escalate —
                # catalog is the floor.
                effective_risk = _max_risk(ring1_risk, decision.assessment.risk)
                # If the fail-closed wrapper fired and blocked, surface
                # that immediately; don't continue through opt-in logic.
                if not decision.assessment.allowed and decision.used_fallback:
                    assessment = RiskAssessment(
                        allowed=False,
                        risk=effective_risk,  # type: ignore[arg-type]
                        reason=f"{name}: ring2 degraded → {ring2_reason}",
                        surface=surface,
                    )
                    _maybe_record_flagged(
                        assessment,
                        capability_name=name,
                        rendered_payload=rendered_payload,
                        programme_id=programme_id,
                    )
                    return _record_and_return(
                        assessment,
                        capability_name=name,
                        programme_id=programme_id,
                    )

        # Phase 10: whitelist override — applies ONLY when Ring 2
        # was used and either escalated risk or kept the payload at a
        # blockable tier. Ring 1 high already short-circuited above and
        # never reaches this code, so the "NEVER bypasses Ring 1 high"
        # invariant holds structurally — see TestNeverBypassesRing1High.
        if ring2_used and effective_risk in ("high", "medium"):
            allowed_by_whitelist, override_reason = _whitelist_overrides(
                capability_name=name,
                rendered_payload=rendered_payload,
            )
            if allowed_by_whitelist:
                _log.info(
                    "monetization: ring2 verdict overridden by whitelist (%s): %s",
                    name,
                    override_reason,
                )
                return _record_and_return(
                    RiskAssessment(
                        allowed=True,
                        risk=ring1_risk,
                        reason=(
                            f"{name}: ring2 verdict {effective_risk!r} overridden by "
                            f"whitelist — {override_reason}"
                        ),
                        surface=surface,
                    ),
                    capability_name=name,
                    programme_id=programme_id,
                )

        # Effective-risk-high path: Ring 2 escalated to high.
        if effective_risk == "high":
            assessment = RiskAssessment(
                allowed=False,
                risk=effective_risk,  # type: ignore[arg-type]
                reason=f"{name}: ring2 escalated to high ({ring2_reason})",
                surface=surface,
            )
            _maybe_record_flagged(
                assessment,
                capability_name=name,
                rendered_payload=rendered_payload,
                programme_id=programme_id,
            )
            return _record_and_return(
                assessment,
                capability_name=name,
                programme_id=programme_id,
            )
        if effective_risk == "medium":
            opted_in = False
            if programme is not None:
                opt_ins = getattr(programme, "monetization_opt_ins", None)
                if opt_ins is not None and name in opt_ins:
                    opted_in = True
            if not opted_in:
                detail = (
                    f" (ring2: {ring2_reason})"
                    if ring2_used and ring2_reason and effective_risk != ring1_risk
                    else ""
                )
                assessment = RiskAssessment(
                    allowed=False,
                    risk=effective_risk,  # type: ignore[arg-type]
                    reason=f"{name}: medium-risk capability requires programme opt-in{detail}",
                    surface=surface,
                )
                _maybe_record_flagged(
                    assessment,
                    capability_name=name,
                    rendered_payload=rendered_payload,
                    programme_id=programme_id,
                )
                return _record_and_return(
                    assessment,
                    capability_name=name,
                    programme_id=programme_id,
                )
            return _record_and_return(
                RiskAssessment(
                    allowed=True,
                    risk=effective_risk,  # type: ignore[arg-type]
                    reason=f"{name}: medium-risk capability opted in by active programme",
                    surface=surface,
                ),
                capability_name=name,
                programme_id=programme_id,
            )
        return _record_and_return(
            RiskAssessment(
                allowed=True,
                risk=effective_risk,  # type: ignore[arg-type]
                reason=f"{name}: {effective_risk}-risk capability — passed",
                surface=surface,
            ),
            capability_name=name,
            programme_id=programme_id,
        )

    def candidate_filter(
        self,
        candidates: list[_CandidateLike],
        programme: _ProgrammeLike | None = None,
    ) -> list[_CandidateLike]:
        """Return only the candidates that pass the monetization gate.

        Batch helper — Ring 2 is deliberately not wired here because
        the rendered payload differs per candidate. Call ``assess()``
        directly with Ring 2 kwargs when classification is needed.
        """
        return [c for c in candidates if self.assess(c, programme).allowed]


# Phase 1 ships a module-level singleton — the gate is stateless, so a
# single instance costs nothing and prevents accidental drift if callers
# were to construct multiple gates with divergent futures.
GATE = MonetizationRiskGate()


def candidate_filter(
    candidates: list[_CandidateLike],
    programme: _ProgrammeLike | None = None,
) -> list[_CandidateLike]:
    """Module-level convenience for the shared singleton."""
    return GATE.candidate_filter(candidates, programme)


def assess(
    candidate: _CandidateLike,
    programme: _ProgrammeLike | None = None,
) -> RiskAssessment:
    """Module-level convenience for the shared singleton."""
    return GATE.assess(candidate, programme)


# Deliberately unused import — kept only so ``Literal`` remains available
# for Phase 3 RiskAssessment refinements when the classifier lands.
_ = Literal


# Phase 10: load the operator whitelist at module import so daemon
# startups pick up the on-disk state without an explicit bootstrap call.
# Tests that need a known-empty starting point call ``reload_whitelist``
# with a tmp_path. Wrapped in try/except because module import must
# never fail on a corrupted whitelist; the loader already returns an
# empty whitelist on parse failure so this is belt-and-braces.
try:
    reload_whitelist(DEFAULT_WHITELIST_PATH)
except Exception:  # noqa: BLE001 — module import must not fail
    _log.warning("monetization-whitelist: bootstrap load failed", exc_info=True)
