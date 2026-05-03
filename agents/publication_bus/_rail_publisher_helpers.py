"""Shared helpers for the 10 monetization-rail V5 publishers.

Per cc-task ``jr-monetization-rails-cross-cutting-helpers-extract``.
Extracts the cross-cutting boilerplate that was duplicated across
the 10 rail publishers shipped over PRs #2280 through #2316:

- :func:`default_output_dir` — every publisher computed
  ``Path(HAPAX_HOME or HOME) / "hapax-state" / "publications" / <slug>``
  identically; factored to a single call.
- :func:`safe_filename_for_event` — every publisher built
  ``event-{kind}-{sha16}.md`` with the same dotted-kind
  sanitization (`replace(".", "_")` since several rails emit dotted
  event kinds like ``membership.cancelled``).
- :func:`write_manifest_entry` — the disk-write side of every
  publisher's ``_emit()`` was identical: ``mkdir(parents=True,
  exist_ok=True)``, ``write_text(payload.text, encoding="utf-8")``,
  return :class:`PublisherResult` with the path, swallow
  :class:`OSError` to ``error=True``.
- :func:`auto_link_cancellation_to_refusal_log` — five publishers
  (Sponsors / Liberapay / Stripe / Patreon / BMaC) carried
  near-identical implementations of the cancellation auto-link to
  ``agents.refusal_brief`` under axiom
  :data:`CANCELLATION_REFUSAL_AXIOM`. Now a single helper that
  takes the per-rail axiom/surface/reason as parameters.

The helpers are receive-only by construction — they do not import
any HTTP client (``requests`` / ``httpx`` / ``urllib.request``),
do not declare any send/initiate/payout method, and are tested by
the same source-pin tests the publisher modules carry.

cc-task: ``jr-monetization-rails-cross-cutting-helpers-extract``
(scope: 10 publishers refactored; ~30% LOC reduction; pure refactor
— no behavior change). Sibling: ``2026-05-03-monetization-rails-
tier-1-wired-complete.md`` §4.1.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from agents.publication_bus.publisher_kit import (
    PublisherPayload,
    PublisherResult,
)

CANCELLATION_REFUSAL_AXIOM: str = "full_auto_or_nothing"
"""Canonical axiom under which cancellation events route into the
refusal-as-data log. All 5 cancellation-aware rails (Sponsors,
Liberapay, Stripe Payment Link, Patreon, BMaC) emit under this
axiom; the per-rail surface string disambiguates which rail's
cancellation fired."""


def default_output_dir(rail_slug: str) -> Path:
    """Resolve the manifest output directory for a rail, honoring HAPAX_HOME.

    Layout:
        ``<HAPAX_HOME or ~>/hapax-state/publications/<rail_slug>``

    Used by every rail publisher's no-output-dir-passed default
    branch. The rail slug is the stable per-rail identifier
    (``github-sponsors``, ``liberapay``, ``mercury``, etc.); per
    convention this matches the ``surface_slug`` registered in
    :data:`agents.publication_bus.surface_registry.SURFACE_REGISTRY`.
    """
    home_env = os.environ.get("HAPAX_HOME")
    base = Path(home_env) if home_env else Path.home()
    return base / "hapax-state" / "publications" / rail_slug


def safe_filename_for_event(event_kind_value: str, sha: str) -> str:
    """Build the canonical event-manifest filename.

    Returns ``event-{safe_kind}-{safe_sha}.md`` where:

    - ``safe_kind`` is ``event_kind_value`` with ``.`` replaced by
      ``_`` (filesystem-safe; needed for dotted-kind rails like
      BMaC ``membership.cancelled`` or Modern Treasury
      ``incoming_payment_detail.created``).
    - ``safe_sha`` is the first 16 chars of ``sha`` (or
      ``"unknown"`` if empty / falsy).

    Pure function; no I/O.
    """
    safe_kind = event_kind_value.replace(".", "_")
    safe_sha = sha[:16] if sha else "unknown"
    return f"event-{safe_kind}-{safe_sha}.md"


def write_manifest_entry(
    output_dir: Path,
    payload: PublisherPayload,
    *,
    log: logging.Logger,
) -> PublisherResult:
    """Write the aggregate manifest entry to disk.

    The disk-write side of every rail publisher's ``_emit()``.
    Reads ``payload.metadata["raw_payload_sha256"]`` for the SHA
    suffix. Creates the parent directory with ``parents=True``,
    ``exist_ok=True``. Swallows :class:`OSError` to a typed
    :class:`PublisherResult` with ``error=True`` and a detail
    string; the publisher boundary's responsibility is to surface
    the result, not to blow up.

    Caller is responsible for any post-write side-effects (e.g.,
    cancellation auto-link via
    :func:`auto_link_cancellation_to_refusal_log`).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    sha = str(payload.metadata.get("raw_payload_sha256", ""))
    path = output_dir / safe_filename_for_event(payload.target, sha)
    try:
        path.write_text(payload.text, encoding="utf-8")
    except OSError as exc:
        log.warning("rail manifest write failed: %s", exc)
        return PublisherResult(error=True, detail=f"write failed: {exc}")
    return PublisherResult(ok=True, detail=str(path))


def auto_link_cancellation_to_refusal_log(
    payload: PublisherPayload,
    *,
    axiom: str,
    surface: str,
    reason: str,
    log: logging.Logger,
) -> None:
    """Append a :class:`RefusalEvent` to the canonical refusal log.

    Five rail publishers (Sponsors / Liberapay / Stripe Payment
    Link / Patreon / BMaC) call this from their ``_emit()`` when
    their respective cancellation event-kind fires; the existing
    ``refusal_annex_renderer`` aggregates these into per-rail
    annex slugs.

    Best-effort: append failures swallow at the publisher boundary
    so observability hiccups never break the publish path. The
    ``HAPAX_REFUSALS_LOG_PATH`` env var override is consulted at
    call time so the test harness can redirect the log to a temp
    dir without monkey-patching the writer module.

    The 160-char cap on ``reason`` matches the
    :class:`agents.refusal_brief.RefusalEvent` schema constraint.
    """
    try:
        from pathlib import Path as _Path

        from agents.refusal_brief import RefusalEvent, append

        override_path = os.environ.get("HAPAX_REFUSALS_LOG_PATH")
        event = RefusalEvent(
            timestamp=datetime.now(UTC),
            axiom=axiom,
            surface=surface,
            reason=reason[:160],
        )
        if override_path:
            append(event, log_path=_Path(override_path))
        else:
            append(event)
    except Exception:
        log.debug("refusal_brief auto-link failed", exc_info=True)


__all__ = [
    "CANCELLATION_REFUSAL_AXIOM",
    "auto_link_cancellation_to_refusal_log",
    "default_output_dir",
    "safe_filename_for_event",
    "write_manifest_entry",
]
