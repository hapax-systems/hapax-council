"""Legal-name-leak guard for V5 publication-bus publishers.

Per the operator-referent policy
(``shared.operator_referent.OperatorReferentPicker``): the operator's
formal-context legal name appears only in formal-required fields
(CITATION.cff ``authors:``, git author metadata, Zenodo ``creators``
array, ORCID record). Any other emitted text payload is scanned for
the legal-name pattern and the publish-event is refused on match.

The guard wraps the existing
``shared.governance.omg_referent.safe_render`` infrastructure
(established in PR #1373 AUDIT-05) at the V5 publication-bus
boundary. The infrastructure side has been stable for weeks; this
module is a thin V5-namespace bridge.
"""

from __future__ import annotations

from shared.governance.omg_referent import OperatorNameLeak as _OmgOperatorNameLeak
from shared.governance.omg_referent import safe_render as _omg_safe_render

# Re-export OperatorNameLeak under the V5 publication-bus name. The
# V5 caller imports ``LegalNameLeak`` from
# ``agents.publication_bus.publisher_kit.legal_name_guard``; the
# alias preserves the v4 behavior under a v5 name.
LegalNameLeak = _OmgOperatorNameLeak


def assert_no_leak(
    text: str,
    *,
    segment_id: str | None = None,
    legal_name_pattern: str | None = None,
) -> None:
    """Scan ``text`` for the operator's legal-name pattern; raise on match.

    Wraps ``shared.governance.omg_referent.safe_render``. The wrapper
    raises :class:`LegalNameLeak` when the legal-name pattern matches
    the rendered text; otherwise returns silently. The
    :class:`Publisher.publish()` superclass method catches this
    exception and converts to a refused result.

    ``segment_id`` is the sticky seed for the referent picker (a
    per-artifact id, e.g., the artifact's slug). When ``None``, the
    picker uses the stochastic mode — suitable for one-off scans
    that don't need per-call consistency.

    ``legal_name_pattern`` is the plain string (case-insensitive)
    to scan for; falls back to ``HAPAX_OPERATOR_NAME`` env var when
    omitted.

    Subclass code should not need to call this directly; the
    superclass handles the guard before invoking ``_emit()``. This
    function is exposed for tests and for explicit one-off use.
    """
    _omg_safe_render(
        text,
        segment_id=segment_id,
        legal_name_pattern=legal_name_pattern,
    )


__all__ = [
    "LegalNameLeak",
    "assert_no_leak",
]
