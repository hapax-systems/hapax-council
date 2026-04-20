"""Pre-render classifier degradation — fail-closed policy (#203 / Phase 4).

Phase 4 of ``docs/superpowers/plans/2026-04-20-demonetization-safety-
plan.md``. Ships the fail-closed guard that activates when Phase 3's
Ring 2 pre-render classifier (``#202``) is unavailable — TabbyAPI down,
request timeout, parse failure, OOM.

**Fail-closed by design** — when the classifier can't render a
verdict, gate defaults to BLOCKING medium-risk capabilities
unconditionally on broadcast surfaces. Rationale: livestream going
silent for 30 s is a smaller governance failure than 30 s of
potentially-risky content bypassing the intended classifier tier.

Why it ships before Phase 3:

- The fail-closed path is CLASSIFIER-INDEPENDENT — it operates on
  ``ClassifierUnavailable`` exceptions + timeouts, not on classifier
  output. Pure protocol contract.
- When #202 lands, the concrete classifier implementation raises
  ``ClassifierUnavailable`` on its degraded paths and this module
  catches it.
- Shipping it first means Phase 3's degraded-path handling is
  pre-wired and has regression-tested semantics when the classifier
  implementation lands.

Operator override: ``HAPAX_CLASSIFIER_FAIL_OPEN=1`` environment flag
downgrades failure to fail-open (admits medium-risk). For debugging
only — the default is fail-closed per plan §4.

Reference:
    - docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md
      §4 Phase 4
    - shared/governance/monetization_safety.py — Phase 1 gate
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Protocol

from shared.governance.monetization_safety import RiskAssessment, SurfaceKind

log = logging.getLogger(__name__)

# Operator-debug env flag. Setting to "1" downgrades fail-closed to
# fail-open (governance-unsafe — use only for troubleshooting).
FAIL_OPEN_ENV: Final[str] = "HAPAX_CLASSIFIER_FAIL_OPEN"

# Timeout after which the classifier call is considered unavailable.
# Deliberately tight — broadcast cadence can't wait for a slow classifier.
DEFAULT_CLASSIFIER_TIMEOUT_S: Final[float] = 2.0


class ClassifierUnavailable(RuntimeError):
    """Raised by a classifier when it cannot render a verdict.

    Subclass for specific failure modes (TabbyAPI down, parse fail,
    timeout, OOM) so downstream audit can attribute correctly.
    """

    def __init__(self, reason: str, *, underlying: Exception | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.underlying = underlying


class ClassifierTimeout(ClassifierUnavailable):
    """Classifier did not return within ``DEFAULT_CLASSIFIER_TIMEOUT_S``."""


class ClassifierBackendDown(ClassifierUnavailable):
    """Classifier backend (TabbyAPI, LiteLLM gateway) returned an error."""


class ClassifierParseError(ClassifierUnavailable):
    """Classifier returned output the parser couldn't interpret."""


class DegradationMode(StrEnum):
    """How to handle classifier unavailability."""

    FAIL_CLOSED = "fail_closed"  # block medium-risk on unavailable (default)
    FAIL_OPEN = "fail_open"  # admit medium-risk (operator debug only)


class Classifier(Protocol):
    """Structural type for the Phase 3 Ring 2 classifier.

    The concrete implementation ships with task #202 and imports from
    ``shared.governance.ring2_classifier``. Tests inject stubs.
    """

    def classify(
        self,
        *,
        capability_name: str,
        rendered_payload: Any,
        surface: SurfaceKind,
    ) -> RiskAssessment: ...


@dataclass(frozen=True)
class DegradationDecision:
    """Outcome of a degraded-path call.

    ``used_fallback`` True iff the classifier raised and the fail-closed
    (or fail-open under env override) path fired. Egress audit consumes
    this to emit ``classifier_unavailable`` records.
    """

    assessment: RiskAssessment
    used_fallback: bool
    underlying_reason: str = ""


def _fail_open_env_enabled() -> bool:
    return os.environ.get(FAIL_OPEN_ENV, "") == "1"


def classify_with_fallback(
    classifier: Classifier,
    *,
    capability_name: str,
    rendered_payload: Any,
    surface: SurfaceKind,
    mode: DegradationMode | None = None,
    timeout_s: float = DEFAULT_CLASSIFIER_TIMEOUT_S,
    audit_writer: Any = None,
) -> DegradationDecision:
    """Invoke ``classifier.classify`` with fail-closed (default) degradation.

    Flow:
    1. Call ``classifier.classify(...)``. Return its RiskAssessment on
       success, wrapped in ``DegradationDecision(used_fallback=False)``.
    2. On ``ClassifierUnavailable`` (any subclass), apply the
       degradation mode:
       - FAIL_CLOSED (default) → emit a synthetic RiskAssessment with
         ``allowed=False``, ``risk="medium"``,
         ``reason="classifier unavailable ({underlying}); fail-closed"``.
       - FAIL_OPEN → emit ``allowed=True, risk="medium",
         reason="...; fail-open (operator debug)"``.
    3. ``mode=None`` (default) consults env: ``FAIL_OPEN_ENV=="1"``
       means FAIL_OPEN, otherwise FAIL_CLOSED.

    **Timeout enforcement is POST-HOC and best-effort** (D-24 §8.6).
    The classifier contract ``classify()`` has no built-in deadline —
    we check ``elapsed > timeout_s`` *after* the call returns and
    synthesize a ``ClassifierTimeout`` raise. This means a genuinely-
    hung classifier (e.g. a TabbyAPI request that never completes)
    will block this call indefinitely; only an overly-slow-but-
    completing classifier triggers the synthetic timeout. Hard
    deadline enforcement (via ``signal.alarm`` or async cancellation)
    is out of scope here — the per-classifier implementation is
    responsible for its own hard timeouts. The ``timeout_s`` argument
    is forwarded to the classifier contract for callers that surface
    it on the Classifier Protocol (not required).

    ``audit_writer`` (D-23) is an optional ``MonetizationEgressAudit``-
    like object; when provided, every decision (success or fallback)
    is recorded to the egress trail so the JSONL captures classifier
    runtime verdicts alongside catalog-level Ring 1 decisions. Errors
    in the writer are swallowed — the classifier is load-bearing,
    audit is best-effort observability.
    """
    decision: DegradationDecision
    try:
        start = time.monotonic()
        assessment = classifier.classify(
            capability_name=capability_name,
            rendered_payload=rendered_payload,
            surface=surface,
        )
        elapsed = time.monotonic() - start
        if elapsed > timeout_s:
            # Classifier didn't raise but exceeded budget — treat as
            # unavailable even though output exists. Broadcast cadence
            # can't tolerate slow classifiers any more than silent ones.
            raise ClassifierTimeout(
                f"classifier.classify took {elapsed:.2f} s > {timeout_s:.2f} s budget"
            )
        decision = DegradationDecision(assessment=assessment, used_fallback=False)
        _write_audit(audit_writer, capability_name, assessment, surface, used_fallback=False)
        return decision
    except ClassifierUnavailable as exc:
        effective_mode = mode
        if effective_mode is None:
            effective_mode = (
                DegradationMode.FAIL_OPEN
                if _fail_open_env_enabled()
                else DegradationMode.FAIL_CLOSED
            )
        decision = _degrade(
            capability_name=capability_name,
            surface=surface,
            underlying=exc,
            mode=effective_mode,
        )
        _write_audit(
            audit_writer,
            capability_name,
            decision.assessment,
            surface,
            used_fallback=True,
        )
        return decision


def _write_audit(
    writer: Any,
    capability_name: str,
    assessment: RiskAssessment,
    surface: SurfaceKind,
    *,
    used_fallback: bool,
) -> None:
    """Best-effort audit write + Prometheus tick (D-23); never raises."""
    # Prometheus tick first (always runs, cheap).
    try:
        from shared.governance.demonet_metrics import METRICS as _M

        _M.inc_classifier_call(assessment.risk, used_fallback)
    except Exception:  # noqa: BLE001
        log.debug("classifier_calls counter tick failed", exc_info=True)
    # Audit write (optional writer; swallow on failure).
    if writer is None:
        return
    try:
        writer.record(
            capability_name,
            assessment,
            surface=surface,
            extra={"source": "ring2_classifier", "used_fallback": used_fallback},
        )
    except Exception:  # noqa: BLE001 — audit must never crash the classifier path
        log.debug("audit_writer.record raised; suppressing", exc_info=True)


def _degrade(
    *,
    capability_name: str,
    surface: SurfaceKind,
    underlying: ClassifierUnavailable,
    mode: DegradationMode,
) -> DegradationDecision:
    """Build the degradation RiskAssessment."""
    if mode == DegradationMode.FAIL_OPEN:
        reason = (
            f"{capability_name}: classifier unavailable ({underlying.reason}); "
            "fail-open (operator debug override)"
        )
        log.warning(
            "classifier fail-open: admitting %s on %s despite classifier failure: %s",
            capability_name,
            surface.value,
            underlying.reason,
        )
        return DegradationDecision(
            assessment=RiskAssessment(
                allowed=True,
                risk="medium",
                reason=reason,
                surface=surface,
            ),
            used_fallback=True,
            underlying_reason=underlying.reason,
        )
    # FAIL_CLOSED path.
    reason = (
        f"{capability_name}: classifier unavailable ({underlying.reason}); "
        "fail-closed — medium-risk blocked"
    )
    log.info(
        "classifier fail-closed: blocking %s on %s (%s)",
        capability_name,
        surface.value,
        underlying.reason,
    )
    return DegradationDecision(
        assessment=RiskAssessment(
            allowed=False,
            risk="medium",
            reason=reason,
            surface=surface,
        ),
        used_fallback=True,
        underlying_reason=underlying.reason,
    )
