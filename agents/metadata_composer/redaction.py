"""Walk MonetizationRiskGate to redact capability names in composer prose.

Capability names that the gate assesses at MEDIUM or HIGH risk get
replaced with a generic label before the prose leaves the module.
Anything LOW or absent passes through. The walk is best-effort: if the
gate is unreachable for any reason, redaction returns the input
unchanged (callers compose with the trust they would have without us).
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

# Pattern: any backticked or single-quoted identifier-shaped token. We
# only consider tokens that look like Python-style attribute names so we
# don't false-positive on regular prose.
_CAPABILITY_TOKEN = re.compile(r"`([a-z][a-z0-9_]+(?:\.[a-z0-9_]+)*)`")

_GENERIC_LABEL = "a creative-expression capability"


def redact_capabilities(prose: str, programme: Any) -> str:
    """Replace any backticked capability identifier in ``prose`` whose risk
    assessment is MEDIUM or HIGH with a generic label.

    The composer marks capability names with backticks in the seed prose;
    this is the only signal we look for. Any backticked token that does
    not parse as a capability identifier is left untouched.
    """
    if not prose or "`" not in prose:
        return prose

    try:
        from shared.governance.monetization_safety import (  # noqa: PLC0415
            assess as _assess,
        )
    except Exception as exc:
        log.debug("monetization gate unreachable: %s", exc)
        return prose

    def _replace(match: re.Match) -> str:
        name = match.group(1)
        try:
            assessment = _assess(_Candidate(capability_name=name), programme)
        except Exception as exc:
            log.debug("monetization assess failed for %s: %s", name, exc)
            return match.group(0)
        risk = _risk_value(assessment)
        if risk in {"medium", "high"}:
            return _GENERIC_LABEL
        return match.group(0)

    return _CAPABILITY_TOKEN.sub(_replace, prose)


# ── helpers ────────────────────────────────────────────────────────────────


class _Candidate:
    """Minimal duck-typed candidate for ``MonetizationRiskGate.assess``.

    The gate's protocol expects ``capability_name`` and ``payload``
    attributes; we satisfy both with the smallest surface that lets the
    risk read at the catalog (ring 1) level — no rendered payload, no
    ring-2 classifier handoff.
    """

    def __init__(self, capability_name: str) -> None:
        self.capability_name = capability_name
        self.payload: dict = {}


def _risk_value(assessment: Any) -> str:
    """Pull a normalised risk string out of a RiskAssessment shape."""
    risk = getattr(assessment, "risk", None) or getattr(assessment, "level", None)
    if risk is None:
        return "none"
    if hasattr(risk, "value"):
        risk = risk.value
    return str(risk).lower()
