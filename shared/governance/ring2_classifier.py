"""Ring 2 pre-render classifier — Phase 1 (#202).

Phase 3 of ``docs/superpowers/plans/2026-04-20-demonetization-safety-
plan.md``. Second-pass classifier that inspects the rendered payload
a medium-risk capability is about to emit, raising or lowering the
risk verdict beyond the capability-level catalog annotation from
Phase 2.

Phase 1 ships the real LLM-backed ``classify()`` body. The classifier
routes to the ``local-fast`` LiteLLM alias (TabbyAPI-served Qwen3.5-9B
EXL3 on :5000) with a tight 2-second timeout and a strict JSON output
contract (see ``ring2_prompts.Ring2Verdict``).

Surface routing:

- **Broadcast surfaces** (TTS, CAPTIONS, OVERLAY, WARD) — call the
  LLM with the surface-specific system prompt from ``ring2_prompts``.
- **Internal surfaces** (CHRONICLE, NOTIFICATION, LOG) — default-pass
  with ``risk="none"`` and NO LLM call. Saves GPU + round-trip on
  operator-only payloads.

Failure modes raise ``ClassifierUnavailable`` subclasses so the
surrounding ``classify_with_fallback`` from
``shared.governance.classifier_degradation`` can apply the fail-closed
policy.

Operator overrides:
    - ``HAPAX_RING2_DISABLED=1`` — skip the classifier pass entirely.
    - ``HAPAX_CLASSIFIER_FAIL_OPEN=1`` — admit medium-risk on failure.

Reference:
    - docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md §3
    - docs/research/2026-04-19-demonetization-safety-design.md §6
    - shared/governance/ring2_prompts.py — per-surface prompts +
      Ring2Verdict pydantic model
    - shared/governance/classifier_degradation.py — the Protocol +
      fail-closed wrapper this module plugs into
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Final

from shared.governance.classifier_degradation import (
    ClassifierBackendDown,
    ClassifierParseError,
    ClassifierTimeout,
    DegradationDecision,
    classify_with_fallback,
)
from shared.governance.monetization_safety import (
    RiskAssessment,
    SurfaceKind,
)
from shared.governance.ring2_prompts import (
    SURFACE_IS_BROADCAST,
    Ring2Verdict,
    format_user_prompt,
    prompt_for_surface,
)

log = logging.getLogger(__name__)

# Operator-disable env flag. When "1", Ring 2 is skipped entirely and
# the gate falls through to capability-level risk only. For demos
# where broadcast surfaces are manually curated and the classifier's
# fail-closed blocks are getting in the way.
DISABLED_ENV: Final[str] = "HAPAX_RING2_DISABLED"

# Default classifier model — routes through LiteLLM to TabbyAPI. Keep
# this as an alias string so stimmung-aware downgrades / local-fast
# swaps land transparently without classifier-specific changes.
DEFAULT_CLASSIFIER_MODEL: Final[str] = "local-fast"

# Default timeout — broadcast cadence can't wait. 2 s is the shared
# ClassifierUnavailable budget.
DEFAULT_TIMEOUT_S: Final[float] = 2.0


@dataclass
class Ring2Classifier:
    """TabbyAPI-backed pre-render classifier (Phase 1 real impl).

    The classifier holds a lazy reference to a pydantic-ai Agent so
    tests can instantiate the class without actually constructing
    the LLM provider. On first ``classify()``, the agent is built
    once per (surface, model) pair and cached.

    Fields:
        model: LiteLLM alias — ``local-fast`` by default. Override
            for benchmarks or operator-requested escalation.
        timeout_s: Per-call timeout. Enforced by
            ``classifier_degradation.classify_with_fallback`` at the
            Protocol layer; also forwarded to the LiteLLM client.
    """

    model: str = DEFAULT_CLASSIFIER_MODEL
    timeout_s: float = DEFAULT_TIMEOUT_S
    _agents_by_surface: dict[SurfaceKind, Any] = field(default_factory=dict)

    def classify(
        self,
        *,
        capability_name: str,
        rendered_payload: Any,
        surface: SurfaceKind,
    ) -> RiskAssessment:
        """Inspect ``rendered_payload`` for ``surface``-specific risk.

        Broadcast surfaces route to the per-surface LLM agent.
        Internal surfaces default-pass without an LLM call.
        """
        # Internal surfaces — no LLM, default-pass.
        if surface not in SURFACE_IS_BROADCAST:
            return RiskAssessment(
                allowed=True,
                risk="none",
                reason=f"{capability_name}: internal surface {surface.value}; Ring 2 skipped",
                surface=surface,
            )

        agent = self._agent_for(surface)
        user_prompt = format_user_prompt(capability_name, rendered_payload)
        try:
            result = agent.run_sync(user_prompt)
        except TimeoutError as e:
            raise ClassifierTimeout(
                f"classifier timed out after {self.timeout_s:.1f}s", underlying=e
            ) from e
        except Exception as e:
            # Network / provider / import failures all collapse to
            # "backend down" so the fail-closed path fires.
            raise ClassifierBackendDown(
                f"classifier backend failed: {type(e).__name__}: {e}", underlying=e
            ) from e

        verdict = self._coerce_verdict(result)
        if verdict.risk not in ("none", "low", "medium", "high"):
            raise ClassifierParseError(f"unknown risk level {verdict.risk!r}")

        # High-risk always blocks regardless of the LLM's ``allowed``
        # field. Defends against a confused verdict where the LLM
        # writes risk=high but allowed=true (rare but possible).
        allowed = verdict.allowed and verdict.risk != "high"
        return RiskAssessment(
            allowed=allowed,
            risk=verdict.risk,  # type: ignore[arg-type]
            reason=f"{capability_name}: {verdict.reason}",
            surface=surface,
        )

    # --- internals --------------------------------------------------

    def _agent_for(self, surface: SurfaceKind) -> Any:
        """Build-or-return the cached pydantic-ai Agent for ``surface``.

        Lazy so the classifier class is instantiable without importing
        pydantic-ai (tests can monkeypatch _agents_by_surface with a
        stub that has .run_sync).
        """
        if surface not in self._agents_by_surface:
            # Imports deferred so tests + CI without LLM stack don't
            # pay import cost just to exercise _coerce_verdict / the
            # internal-surface pass-through.
            from pydantic_ai import Agent

            from shared.config import get_model

            system_prompt = prompt_for_surface(surface)
            self._agents_by_surface[surface] = Agent(
                get_model(self.model),
                output_type=Ring2Verdict,
                system_prompt=system_prompt,
            )
        return self._agents_by_surface[surface]

    @staticmethod
    def _coerce_verdict(result: Any) -> Ring2Verdict:
        """Pull a ``Ring2Verdict`` out of whatever the agent returned.

        Pydantic-ai's ``.run_sync()`` returns a RunResult whose
        ``.output`` is the structured model. Tests may inject stubs
        that return the Ring2Verdict directly, a dict, or a raw JSON
        string — handle all three so the classifier is easy to stub.
        """
        # Pydantic-ai RunResult.
        if hasattr(result, "output"):
            out = result.output
            if isinstance(out, Ring2Verdict):
                return out
            if isinstance(out, dict):
                return Ring2Verdict.model_validate(out)
            if isinstance(out, str):
                return _verdict_from_str(out)
        # Direct Verdict.
        if isinstance(result, Ring2Verdict):
            return result
        # Dict.
        if isinstance(result, dict):
            return Ring2Verdict.model_validate(result)
        # Raw JSON string.
        if isinstance(result, str):
            return _verdict_from_str(result)
        raise ClassifierParseError(f"unexpected classifier result type: {type(result).__name__}")

    def _parse_verdict(self, response_text: str) -> RiskAssessment:
        """Parse a JSON verdict string into a ``RiskAssessment``.

        Kept on the class for backward compatibility with Phase 0
        tests and for ad-hoc benchmark scripts that pass raw LLM
        output text. Raises ``ClassifierParseError`` on any parse
        failure.
        """
        verdict = _verdict_from_str(response_text)
        return RiskAssessment(
            allowed=verdict.allowed and verdict.risk != "high",
            risk=verdict.risk,  # type: ignore[arg-type]
            reason=verdict.reason,
        )


def _verdict_from_str(text: str) -> Ring2Verdict:
    """Turn a JSON-formatted verdict string into ``Ring2Verdict``.

    Tolerates triple-backtick-fenced responses (``local-fast`` models
    sometimes wrap their JSON in markdown despite instructions).
    """
    stripped = text.strip()
    # Strip ```json ... ``` and ``` ... ``` fences if present.
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        # Drop the opening fence + (optional) language tag.
        if len(lines) > 1:
            lines = lines[1:]
        # Drop trailing fence.
        while lines and lines[-1].strip() == "```":
            lines.pop()
        stripped = "\n".join(lines).strip()
    try:
        data = json.loads(stripped)
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
    reason = str(data.get("reason", ""))
    return Ring2Verdict(allowed=allowed, risk=risk, reason=reason)


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
    risk). Returns ``DegradationDecision`` otherwise, whose
    ``assessment`` field is the RiskAssessment to enforce.
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
