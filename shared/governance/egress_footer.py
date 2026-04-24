"""Anti-personification egress footer — FINDING ef7b-165 Phase 9.

De-monetization safety plan §Phase 9 (docs/superpowers/plans/
2026-04-20-demonetization-safety-plan.md). Provides the static text
string that the livestream's persistent footer strip renders to frame
the channel for advertiser review without claiming AI sentience.

The footer is static — validated once at startup via Ring 2, cached,
then reused on every frame by the downstream cairo source. Dynamic
content is restricted to operator name + research-home URL pulled
from environment (``HAPAX_OPERATOR_NAME``, ``HAPAX_RESEARCH_HOME_URL``).

This module ships the text + validation primitives. The cairo rendering
surface lands in a follow-up PR that composes this module onto the
compositor footer layer (the plan originally referenced
``chronicle_source.py``; the live path is a new dedicated footer
source to avoid coupling with the chronicle ticker ward).

Example usage::

    from shared.governance.egress_footer import (
        render_footer_text,
        validate_footer_once,
    )

    text = render_footer_text()           # env-driven
    validate_footer_once(text)            # fail-closed on Ring 2 reject
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from shared.governance.monetization_safety import (
    RiskAssessment,
    SurfaceKind,
)

if TYPE_CHECKING:
    from shared.governance.ring2_classifier import Ring2Classifier

log = logging.getLogger(__name__)


#: BitchX-grammar anti-personification footer. Frames the channel as
#: a *research instrument* without claiming cognition or sentience.
#: Keeps Hapax in the role of object-of-study rather than agent.
FOOTER_TEMPLATE: str = (
    ">>> Council research instrument — experimental cognitive architecture "
    "(operator: {operator_name}, research home: {research_home_url})"
)

#: Env-var names the footer reads. Mirrors the plan's ``config/defaults.py``
#: contract (the config file in the plan never shipped; we use env vars
#: with hard-coded safe defaults instead — simpler, same outcome).
ENV_OPERATOR_NAME: str = "HAPAX_OPERATOR_NAME"
ENV_RESEARCH_HOME_URL: str = "HAPAX_RESEARCH_HOME_URL"

#: Safe fallback values if env vars are unset. Generic-enough to stay
#: accurate pre-configuration without leaking any personal identifier.
DEFAULT_OPERATOR_NAME: str = "the operator"
DEFAULT_RESEARCH_HOME_URL: str = "hapax.ryankleeberger.com"


def render_footer_text(
    *,
    operator_name: str | None = None,
    research_home_url: str | None = None,
) -> str:
    """Return the fully-substituted footer text.

    Env-driven by default. Explicit arguments override env (useful in
    tests). Unset env collapses to ``DEFAULT_*`` constants — the
    footer never renders an empty placeholder.
    """
    name = operator_name or os.environ.get(ENV_OPERATOR_NAME) or DEFAULT_OPERATOR_NAME
    url = research_home_url or os.environ.get(ENV_RESEARCH_HOME_URL) or DEFAULT_RESEARCH_HOME_URL
    return FOOTER_TEMPLATE.format(operator_name=name, research_home_url=url)


def validate_footer_once(
    text: str,
    *,
    classifier: Ring2Classifier | None = None,
) -> RiskAssessment:
    """Run the footer text through Ring 2 once and return the verdict.

    Meant to be called at startup and the result cached for the life of
    the process. Surface is ``OVERLAY`` (legibility chrome, not TTS or
    ward content). Fail-closed: any non-allowed verdict raises the
    classifier's usual exceptions; callers should not ship the footer
    if this call raises or returns ``allowed=False``.

    ``classifier`` defaults to a freshly-constructed ``Ring2Classifier``
    so callers can inject a stub in tests.
    """
    if classifier is None:
        from shared.governance.ring2_classifier import Ring2Classifier

        classifier = Ring2Classifier()

    verdict = classifier.classify(
        capability_name="egress_footer",
        rendered_payload=text,
        surface=SurfaceKind.OVERLAY,
    )
    if not verdict.allowed:
        log.warning(
            "egress footer rejected by Ring 2: risk=%s reason=%s",
            verdict.risk,
            verdict.reason,
        )
    return verdict


__all__ = [
    "DEFAULT_OPERATOR_NAME",
    "DEFAULT_RESEARCH_HOME_URL",
    "ENV_OPERATOR_NAME",
    "ENV_RESEARCH_HOME_URL",
    "FOOTER_TEMPLATE",
    "render_footer_text",
    "validate_footer_once",
]
