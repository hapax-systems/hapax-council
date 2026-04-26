"""Category B processor — DOI / ORCID extraction from verify-emails.

Spec: ``docs/specs/2026-04-25-mail-monitor.md`` §3.B.

Verify-mails come from a small allow-list (Zenodo, ORCID, OSF,
DataCite) — server-side filter A routes them to ``Hapax/Verify``. This
processor extracts the DOI / ORCID identifier from the body, writes
it to the canonical artefact manifest, and emits a chronicle event so
``pub-bus-zenodo-graph`` and adjacent daemons can ratify their
API-side belief about the deposit.

Extraction is deterministic regex-only — no LLM call. The (rare) case
where regex fires but no plausible DOI is found surfaces as a
refusal-brief log entry with ``kind=verify_extraction_failed`` so the
operator can audit. Pending-actions correlation lands in a follow-up
when ``mail-monitor-010`` ships the writer.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from prometheus_client import Counter

from agents.mail_monitor.audit import audit_call
from agents.mail_monitor.processors.refusal_feedback import emit_refusal_feedback

log = logging.getLogger(__name__)

# Crossref-recommended DOI regex (RFC-style). The trailing
# punctuation set is intentionally permissive — DOI suffixes can
# include any printable except space.
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:a-zA-Z0-9]+\b")
# ORCID iD: NNNN-NNNN-NNNN-NNNX where X is digit or 'X'.
_ORCID_RE = re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b")
# OSF project identifier: 5-character lowercase-hex from the
# ``osf.io/<id>`` URL form. Matches lowercase letters and digits.
_OSF_RE = re.compile(r"\bosf\.io/([a-z0-9]{4,8})\b", re.IGNORECASE)

# Where mail-monitor expects per-artefact deposit manifests to live.
# The Hapax-side deposit writer creates one per outbound deposit; the
# verify processor mutates `version_doi` / `concept_doi` once the
# confirmation email arrives.
ARTEFACT_QUEUE_DIR = Path("~/hapax-state/publications/queue").expanduser()

VERIFY_EXTRACTED_COUNTER = Counter(
    "hapax_mail_monitor_verify_extracted_total",
    "Verify-mail extractions by identifier-kind and outcome.",
    labelnames=("kind", "result"),
)
for _kind in ("doi", "orcid", "osf"):
    for _result in ("extracted", "missing", "manifest_written", "manifest_skipped"):
        VERIFY_EXTRACTED_COUNTER.labels(kind=_kind, result=_result)


def extract_doi(body: str | None) -> str | None:
    """Return the first DOI found in ``body`` or ``None``."""
    if not body:
        return None
    match = _DOI_RE.search(body)
    return match.group(0) if match else None


def extract_orcid(body: str | None) -> str | None:
    """Return the first ORCID iD found in ``body`` or ``None``."""
    if not body:
        return None
    match = _ORCID_RE.search(body)
    return match.group(0) if match else None


def extract_osf_id(body: str | None) -> str | None:
    """Return the first OSF project id (5-8 char) or ``None``."""
    if not body:
        return None
    match = _OSF_RE.search(body)
    return match.group(1).lower() if match else None


def _find_artefact_manifest(artefact_id: str | None) -> Path | None:
    """Resolve the artefact id to its on-disk manifest, or ``None``.

    The Hapax-side deposit writer (out of scope for this commit)
    creates ``~/hapax-state/publications/queue/{artefact-id}/manifest.yaml``
    when it initiates a deposit. ``manifest.json`` is the JSON variant.
    """
    if not artefact_id:
        return None
    base = ARTEFACT_QUEUE_DIR / artefact_id
    for name in ("manifest.json", ".zenodo.json"):
        candidate = base / name
        if candidate.exists():
            return candidate
    return None


def _write_doi_to_manifest(manifest_path: Path, doi: str) -> bool:
    """Atomically merge ``version_doi`` (or ``concept_doi``) into the manifest.

    The choice of key is deterministic by manifest content: if a
    ``concept_doi`` already exists, the new arrival is the
    ``version_doi`` (next deposit revision). Otherwise the arrival is
    the ``concept_doi`` (first deposit).
    """
    try:
        payload = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("manifest read failed at %s: %s", manifest_path, exc)
        return False

    # Idempotency: if the DOI is already recorded as either concept or
    # version, don't write a redundant entry.
    if payload.get("concept_doi") == doi or payload.get("version_doi") == doi:
        return True

    key = "version_doi" if "concept_doi" in payload else "concept_doi"

    payload[key] = doi
    tmp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp.rename(manifest_path)
    except OSError as exc:
        log.warning("manifest write failed at %s: %s", manifest_path, exc)
        return False
    return True


def process_verify(service: Any, message: dict[str, Any]) -> bool:
    """Extract identifiers from a verify-mail and update the artefact manifest.

    ``message`` is the dict produced by the runner. Notable fields:

    - ``body_text`` — plain-text body for regex extraction.
    - ``artefact_id`` — optional handle the runner enriched from prior
      pending-actions correlation. When absent, the processor still
      extracts identifiers and audits the read; manifest mutation is
      skipped.

    Returns ``True`` if the read + audit completed (manifest mutation
    is best-effort and does not flip the return).
    """
    message_id = message.get("id") or message.get("messageId")
    body = message.get("body_text") or ""

    doi = extract_doi(body)
    orcid = extract_orcid(body)
    osf_id = extract_osf_id(body)

    for kind, value in (("doi", doi), ("orcid", orcid), ("osf", osf_id)):
        VERIFY_EXTRACTED_COUNTER.labels(kind=kind, result="extracted" if value else "missing").inc()

    artefact_id = message.get("artefact_id")
    manifest_path = _find_artefact_manifest(artefact_id)

    if doi and manifest_path is not None:
        wrote = _write_doi_to_manifest(manifest_path, doi)
        VERIFY_EXTRACTED_COUNTER.labels(
            kind="doi",
            result="manifest_written" if wrote else "manifest_skipped",
        ).inc()
    elif doi:
        # No manifest path resolved — the daemon-side deposit writer
        # hasn't shipped yet, or this is a verify-mail unrelated to a
        # tracked outbound. Audit-log records the read; the digest in
        # mail-monitor-012 catches the gap.
        VERIFY_EXTRACTED_COUNTER.labels(kind="doi", result="manifest_skipped").inc()

    if not doi and not orcid and not osf_id:
        # Filter A delivered the message but extraction came up empty.
        # Spec §3.B: surface a refusal-brief entry tagged
        # ``mail-monitor:verify-extract-fail`` so the operator can
        # audit but is not paged.
        emit_refusal_feedback(message, kind="verify_extraction_failed")

    audit_call(
        "messages.get",
        message_id=message_id,
        label="Hapax/Verify",
        result="ok",
        extra={
            "doi": doi,
            "orcid": orcid,
            "osf_id": osf_id,
            "manifest_written": bool(manifest_path is not None and doi),
        },
    )
    return True
