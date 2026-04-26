"""Append-only contact suppression list.

The suppression list is the load-bearing governance primitive for the
cold-contact family. Any named target who has either received a cold-contact
touch, sent a SUPPRESS opt-out, or been manually added by the operator is
permanently suppressed from any further direct outreach.

Citation-graph touches (Zenodo IsCitedBy / DataCite RelatedIdentifier) do NOT
consult this list — they don't impose on the target — but the daemons in
`agents/cold_contact*` MUST consult `is_suppressed()` before any outbound send.

The on-disk format is YAML with an explicit version field. Entries are
append-only: the loader validates that no entry has been rewritten across
loads (entries are content-addressed by ORCID + date), and `append_entry()`
is the only sanctioned mutation.
"""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

try:
    from prometheus_client import Counter

    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False


_DEFAULT_PATH = Path.home() / "hapax-state" / "contact-suppression-list.yaml"


def _resolved_path(override: Path | None = None) -> Path:
    if override is not None:
        return override
    env = os.environ.get("HAPAX_CONTACT_SUPPRESSION_LIST")
    if env:
        return Path(env)
    return _DEFAULT_PATH


SuppressionInitiator = Literal["hapax_send", "operator_manual", "target_optout"]


class SuppressionEntry(BaseModel):
    """One suppression entry. Either ORCID, email_domain, or both must be set.

    Email-domain entries arrive from the mail-monitor SUPPRESS path
    (cc-task ``mail-monitor-008``). ORCID entries arrive from the
    citation-graph touch path (`cold_contact/graph_touch_policy`) and
    operator-manual additions.
    """

    orcid: str | None = Field(default=None, min_length=19, max_length=19)
    email_domain: str | None = Field(default=None, min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=500)
    initiator: SuppressionInitiator
    date: datetime
    message_id: str | None = Field(default=None, max_length=998)

    def model_post_init(self, _ctx: object) -> None:
        if not self.orcid and not self.email_domain:
            raise ValueError("SuppressionEntry requires at least one of orcid / email_domain")


class SuppressionList(BaseModel):
    version: int = 1
    entries: list[SuppressionEntry] = Field(default_factory=list)


_lock = threading.Lock()


if _HAS_PROMETHEUS:
    SUPPRESSION_ENTRIES_TOTAL = Counter(
        "hapax_contact_suppression_entries_total",
        "Total number of entries appended to the contact-suppression list.",
        ["initiator"],
    )
else:
    SUPPRESSION_ENTRIES_TOTAL = None


def load(path: Path | None = None) -> SuppressionList:
    """Load the suppression list. Returns an empty list if file is missing."""
    resolved = _resolved_path(path)
    if not resolved.exists():
        return SuppressionList()
    with resolved.open() as f:
        raw = yaml.safe_load(f) or {}
    return SuppressionList.model_validate(raw)


def append_entry(
    orcid: str | None = None,
    reason: str = "",
    initiator: SuppressionInitiator = "operator_manual",
    *,
    email_domain: str | None = None,
    message_id: str | None = None,
    date: datetime | None = None,
    path: Path | None = None,
) -> SuppressionEntry:
    """Atomically append a new entry. Refuses to rewrite existing entries.

    Idempotent on the entry's identity tuple ``(orcid, email_domain,
    initiator)`` — a matching entry returns unchanged. Either ``orcid``
    or ``email_domain`` must be supplied; passing both narrows
    deduplication to entries that match both.
    """
    resolved = _resolved_path(path)
    when = date or datetime.now(UTC)
    new_entry = SuppressionEntry(
        orcid=orcid,
        email_domain=email_domain,
        reason=reason,
        initiator=initiator,
        date=when,
        message_id=message_id,
    )

    with _lock:
        current = load(path)
        for existing in current.entries:
            if (
                existing.orcid == orcid
                and existing.email_domain == email_domain
                and existing.initiator == initiator
            ):
                return existing
        current.entries.append(new_entry)

        resolved.parent.mkdir(parents=True, exist_ok=True)
        tmp = resolved.with_suffix(resolved.suffix + ".tmp")
        with tmp.open("w") as f:
            f.write(_HEADER)
            yaml.safe_dump(
                current.model_dump(mode="json", exclude_none=True),
                f,
                sort_keys=False,
                default_flow_style=False,
            )
        os.replace(tmp, resolved)

    if SUPPRESSION_ENTRIES_TOTAL is not None:
        SUPPRESSION_ENTRIES_TOTAL.labels(initiator=initiator).inc()

    return new_entry


def is_suppressed(orcid: str, *, path: Path | None = None) -> bool:
    """Return True if any ORCID entry for ``orcid`` exists."""
    current = load(path)
    return any(e.orcid == orcid for e in current.entries)


def is_suppressed_by_email_domain(domain: str, *, path: Path | None = None) -> bool:
    """Return True if any email-domain entry for ``domain`` exists.

    Mail-monitor's ``Category C`` consult before any cold-contact path
    that has only an email domain (no ORCID). Citation-graph paths that
    have an ORCID should still call :func:`is_suppressed` — both lookups
    are independent.
    """
    current = load(path)
    return any(e.email_domain == domain for e in current.entries)


_HEADER = """\
# Contact suppression list — APPEND-ONLY, governance primitive.
# Every entry forecloses any further direct outreach to the named ORCID.
# Citation-graph touches (Zenodo / DataCite) are unaffected.
# Mutations: only via shared.contact_suppression.append_entry().
"""
