"""Ring 2 pre-render classifier — skeleton (#202 Phase 0).

Phase 3 of ``docs/superpowers/plans/2026-04-20-demonetization-safety-
plan.md``. Second-pass classifier that inspects the rendered payload
a medium-risk capability is about to emit, raising or lowering the
risk verdict beyond the capability-level catalog annotation from
Phase 2.

Phase 0 (this file) ships the **concrete class satisfying the
Classifier Protocol** + the integration call site. The LLM prompts
per ``SurfaceKind`` + the 500-sample benchmark land with Phase 1
once the operator has labelled the calibration set.

Until the real prompts + benchmark land, ``Ring2Classifier`` behaves
like ``NullClassifier``: always raises ``ClassifierBackendDown`` so
the fail-closed path
(``shared.governance.classifier_degradation.classify_with_fallback``)
fires. The reason string says "skeleton — awaiting Phase 1 prompts"
so the egress audit trail shows why medium-risk capabilities are
currently blocking on the default fail-closed path.

Operator override to disable the classifier entirely (e.g. during
demos):
    HAPAX_RING2_DISABLED=1

The degradation path's env override
``HAPAX_CLASSIFIER_FAIL_OPEN=1`` already covers the "admit anyway"
case; the Ring2 disable is a separate earlier-exit so the
classifier isn't even called.

Reference:
    - docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md §3
    - docs/research/2026-04-19-demonetization-safety-design.md §6
      (per-surface prompt design — unshipped)
    - shared/governance/classifier_degradation.py — the Protocol +
      fail-closed wrapper this module plugs into
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Final

from shared.governance.classifier_degradation import (
    ClassifierBackendDown,
    ClassifierParseError,
    DegradationDecision,
    classify_with_fallback,
)
from shared.governance.monetization_safety import (
    RiskAssessment,
    SurfaceKind,
)

log = logging.getLogger(__name__)

# Operator-disable env flag. When "1", Ring 2 is skipped entirely and
# the gate falls through to capability-level risk only. For demos
# where broadcast surfaces are manually curated and the classifier's
# fail-closed blocks are getting in the way.
DISABLED_ENV: Final[str] = "HAPAX_RING2_DISABLED"


@dataclass
class Ring2Classifier:
    """TabbyAPI-backed pre-render classifier (Phase 0 skeleton).

    Integrates with ``shared.config.get_litellm_client()`` — the
    concrete wiring lands in Phase 1. For now the ``classify``
    method raises ``ClassifierBackendDown`` so the surrounding
    ``classify_with_fallback`` applies the fail-closed policy.
    """

    model: str = "local-fast"
    _litellm_client: Any = None  # injected in Phase 1

    def classify(
        self,
        *,
        capability_name: str,
        rendered_payload: Any,
        surface: SurfaceKind,
    ) -> RiskAssessment:
        """Inspect ``rendered_payload`` for ``surface``-specific risk.

        Phase 0: always raises ``ClassifierBackendDown``. Phase 1
        replaces this body with a real LiteLLM call + JSON-verdict
        parse per ``docs/research/2026-04-19-demonetization-safety-
        design.md`` §6.
        """
        raise ClassifierBackendDown(
            "Ring2Classifier Phase 0 skeleton — awaiting Phase 1 prompts + "
            "500-sample benchmark; fail-closed path fires"
        )

    def _parse_verdict(self, response_text: str) -> RiskAssessment:
        """Parse the classifier's JSON verdict.

        Expected shape:
            {"allowed": bool, "risk": "none|low|medium|high",
             "reason": "short explanation"}

        Raises ``ClassifierParseError`` if the response doesn't match.
        """
        import json

        try:
            data = json.loads(response_text)
        except json.JSONDecodeError as e:
            raise ClassifierParseError(f"non-JSON response: {e}") from e
        if not isinstance(data, dict):
            raise ClassifierParseError("response not a JSON object")
        risk = data.get("risk")
        if risk not in ("none", "low", "medium", "high"):
            raise ClassifierParseError(f"unknown risk level {risk!r}")
        allowed = data.get("allowed")
        if not isinstance(allowed, bool):
            raise ClassifierParseError(f"allowed not a bool: {allowed!r}")
        reason = data.get("reason", "")
        return RiskAssessment(allowed=allowed, risk=risk, reason=str(reason))


def is_disabled() -> bool:
    """Check if operator has disabled Ring 2 via env flag."""
    return os.environ.get(DISABLED_ENV, "") == "1"


def classify_rendered_payload(
    capability_name: str,
    rendered_payload: Any,
    surface: SurfaceKind,
    *,
    classifier: Ring2Classifier | None = None,
) -> DegradationDecision | None:
    """Run Ring 2 through the fail-closed wrapper.

    Returns ``None`` when Ring 2 is disabled via env flag (caller
    skips the second-pass check and uses only capability-level
    risk). Returns ``DegradationDecision`` otherwise.

    Until Phase 1 ships real prompts, every call returns a
    fail-closed verdict (``allowed=False, risk="medium"``) with
    reason mentioning the skeleton state.
    """
    if is_disabled():
        log.debug(
            "ring2 disabled via %s=1; skipping classifier pass",
            DISABLED_ENV,
        )
        return None
    cls = classifier if classifier is not None else Ring2Classifier()
    return classify_with_fallback(
        cls,
        capability_name=capability_name,
        rendered_payload=rendered_payload,
        surface=surface,
    )
