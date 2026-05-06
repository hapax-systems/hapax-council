"""CBIP Ring-2 pre-render gate — last check before enhanced platter output ships.

Spec §5 of `docs/superpowers/specs/2026-04-21-cbip-phase-1-design.md`.

Three independent gates, fail-CLOSED to Phase 0 (deterministic tint) on
any failure:

1. **Content-ID matchability** — the fingerprint of the associated
   source asset must be present in a copyright-clear set. If absent, the
   source may match a Content-ID claim and the enhanced output should not be
   amplified — substitute Phase 0.
2. **Copyright freshness** — source metadata must have been re-checked
   within the last 90 days. Stale metadata is risk; substitute Phase 0
   and re-check via the copyright-status surface.
3. **Demonetization risk** — Ring 2 classifier on the rendered output;
   risk ≥ medium blocks (numeric: ≥ 0.4 on the 0..1 scale).

The three checks are injectable callables so this module stays pure
logic + boundary code. Delta wires the real Content-ID lookup +
copyright-status API + Ring2Classifier in Phase 1.7 follow-up; until
then ``Ring2PreRenderGate`` accepts simple stubs that the test suite
exercises end-to-end.

Wired between enhancement-family render and final compositor blit:
when ``GateResult.substitute_phase_0`` is True the renderer falls back
to deterministic-tint output.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

log = logging.getLogger(__name__)

# ── Thresholds (spec §5) ────────────────────────────────────────────────

DEMONET_RISK_BLOCK_THRESHOLD = 0.4  # numeric risk; ≥ this blocks
COPYRIGHT_FRESHNESS_MAX_AGE_S = 90 * 24 * 60 * 60  # 90 days

# Risk labels treated as block. "high" is unconditional; "medium" is the
# conservative bar (matches "≤0.4 numeric").
_RISK_LABELS_BLOCK: frozenset[str] = frozenset({"medium", "high"})


class GateName(StrEnum):
    CONTENT_ID = "content_id_matchability"
    COPYRIGHT_FRESHNESS = "copyright_freshness"
    DEMONET_RISK = "demonetization_risk"


@dataclass(frozen=True)
class GateOutcome:
    """One gate's pass/fail + a one-line reason."""

    name: GateName
    passed: bool
    reason: str = ""


@dataclass(frozen=True)
class GateResult:
    """Aggregate result over all three gates.

    Fail-CLOSED: ``substitute_phase_0`` is True iff any gate failed
    OR a gate raised. Renderer reads this single bool.
    """

    outcomes: tuple[GateOutcome, ...]
    substitute_phase_0: bool

    @property
    def passed(self) -> bool:
        return all(o.passed for o in self.outcomes)

    @property
    def failures(self) -> tuple[GateOutcome, ...]:
        return tuple(o for o in self.outcomes if not o.passed)


# ── Injectable callables (Protocol contracts) ──────────────────────────


class ContentIdLookup(Protocol):
    """Returns True if the track's audio fingerprint is in the clear set."""

    def __call__(self, track_id: str) -> bool: ...


class CopyrightFreshnessClock(Protocol):
    """Returns the unix timestamp of the last copyright re-check."""

    def __call__(self, album_id: str) -> float | None: ...


class DemonetRiskScorer(Protocol):
    """Returns either a numeric risk in [0, 1] OR a risk label string.

    Numeric: ≥ DEMONET_RISK_BLOCK_THRESHOLD blocks.
    Label: "medium" or "high" blocks.
    """

    def __call__(self, rendered: Any) -> float | str: ...


# ── The gate ────────────────────────────────────────────────────────────


@dataclass
class Ring2PreRenderGate:
    """Three-gate pre-render evaluator with fail-CLOSED semantics.

    Construct with the three injectable callables; call ``.evaluate()``
    per render. The callables can be replaced in tests with simple
    lambdas; production wiring binds them to:

    * Content-ID lookup → copyright-clear set query
      (delta wires in Phase 1.7 follow-up)
    * Copyright freshness clock → source metadata store mtime
    * Demonet risk scorer → ``shared.governance.ring2_classifier``

    Any callable that raises is treated as a gate failure (fail-CLOSED).
    """

    content_id_lookup: ContentIdLookup
    copyright_freshness_clock: CopyrightFreshnessClock
    demonet_risk_scorer: DemonetRiskScorer
    now_fn: Any = field(default=time.time)

    def evaluate(
        self,
        rendered: Any,
        *,
        track_id: str,
        album_id: str,
    ) -> GateResult:
        outcomes: list[GateOutcome] = []

        # 1. Content-ID matchability
        try:
            in_clear_set = bool(self.content_id_lookup(track_id))
            outcomes.append(
                GateOutcome(
                    name=GateName.CONTENT_ID,
                    passed=in_clear_set,
                    reason=(
                        "track in copyright-clear set"
                        if in_clear_set
                        else "track absent from copyright-clear set"
                    ),
                )
            )
        except Exception as e:
            log.warning("content_id_lookup raised — failing closed", exc_info=True)
            outcomes.append(
                GateOutcome(
                    name=GateName.CONTENT_ID,
                    passed=False,
                    reason=f"lookup raised {type(e).__name__}: {e}",
                )
            )

        # 2. Copyright freshness
        try:
            last_check = self.copyright_freshness_clock(album_id)
            if last_check is None:
                outcomes.append(
                    GateOutcome(
                        name=GateName.COPYRIGHT_FRESHNESS,
                        passed=False,
                        reason="no copyright check on record",
                    )
                )
            else:
                age_s = self.now_fn() - last_check
                fresh = age_s < COPYRIGHT_FRESHNESS_MAX_AGE_S
                outcomes.append(
                    GateOutcome(
                        name=GateName.COPYRIGHT_FRESHNESS,
                        passed=fresh,
                        reason=(
                            f"last check {age_s / 86400.0:.1f}d ago "
                            f"({'fresh' if fresh else 'stale'}; max=90d)"
                        ),
                    )
                )
        except Exception as e:
            log.warning("copyright_freshness_clock raised — failing closed", exc_info=True)
            outcomes.append(
                GateOutcome(
                    name=GateName.COPYRIGHT_FRESHNESS,
                    passed=False,
                    reason=f"clock raised {type(e).__name__}: {e}",
                )
            )

        # 3. Demonetization risk
        try:
            risk = self.demonet_risk_scorer(rendered)
            blocked, reason = _interpret_demonet_risk(risk)
            outcomes.append(
                GateOutcome(
                    name=GateName.DEMONET_RISK,
                    passed=not blocked,
                    reason=reason,
                )
            )
        except Exception as e:
            log.warning("demonet_risk_scorer raised — failing closed", exc_info=True)
            outcomes.append(
                GateOutcome(
                    name=GateName.DEMONET_RISK,
                    passed=False,
                    reason=f"scorer raised {type(e).__name__}: {e}",
                )
            )

        substitute = not all(o.passed for o in outcomes)
        return GateResult(outcomes=tuple(outcomes), substitute_phase_0=substitute)


def _interpret_demonet_risk(risk: float | str) -> tuple[bool, str]:
    """Translate a numeric or label risk into (blocked, reason).

    Returns (True, reason) if risk should block render; (False, reason)
    if safe.
    """
    if isinstance(risk, str):
        normalized = risk.strip().lower()
        blocked = normalized in _RISK_LABELS_BLOCK
        return (blocked, f"risk={normalized!r} ({'blocked' if blocked else 'allowed'})")
    try:
        score = float(risk)
    except (TypeError, ValueError):
        # Non-numeric, non-string risk → fail closed
        return (True, f"risk type {type(risk).__name__} unrecognized — failing closed")
    if score < 0.0 or score > 1.0:
        return (True, f"risk={score} out of [0, 1] — failing closed")
    blocked = score >= DEMONET_RISK_BLOCK_THRESHOLD
    return (blocked, f"risk={score:.3f} ({'blocked' if blocked else 'allowed'})")


__all__ = [
    "COPYRIGHT_FRESHNESS_MAX_AGE_S",
    "DEMONET_RISK_BLOCK_THRESHOLD",
    "ContentIdLookup",
    "CopyrightFreshnessClock",
    "DemonetRiskScorer",
    "GateName",
    "GateOutcome",
    "GateResult",
    "Ring2PreRenderGate",
]
