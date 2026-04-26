"""V5 publication-bus wire-or-delete registry — tracks per-publisher reachability.

Each V5 ``Publisher`` subclass under ``agents/publication_bus/`` is one of:

- **WIRED** — instantiated by a daemon (publish_orchestrator, weblog
  composer, sc-attestation runner, etc.) on the prod path. Confirmed via
  ``grep`` for prod callers excluding tests.
- **CRED_BLOCKED** — substrate complete and tested; awaiting operator
  credential bootstrap (e.g., ``pass insert <slug>``). When creds arrive,
  the wire decision flips to WIRED via a follow-up adapter PR.
- **DELETE** — substrate cannot be reached because the upstream surface
  was retired or replaced. Slated for removal in a follow-up cleanup PR.

The registry replaces the absence-bug R-5 ``wire-or-delete-decision``
ambiguity: each publisher now has an explicit decision recorded alongside
its module. Audit tooling can verify that any new publisher under
``agents/publication_bus/*_publisher.py`` is catalogued here.

R-5 source: ``~/.cache/hapax/relay/research/2026-04-26-absence-bugs-synthesis-for-beta.md``
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

WireStatus = Literal["WIRED", "CRED_BLOCKED", "DELETE"]


@dataclass(frozen=True)
class WireEntry:
    """One per-publisher reachability entry."""

    module: str
    surface_slug: str
    status: WireStatus
    pass_key_required: str | None = None
    rationale: str = ""


PUBLISHER_WIRE_REGISTRY: dict[str, WireEntry] = {
    "agents.publication_bus.bluesky_publisher": WireEntry(
        module="agents.publication_bus.bluesky_publisher",
        surface_slug="bluesky-atproto-multi-identity",
        status="CRED_BLOCKED",
        pass_key_required="bluesky/operator-app-password, bluesky/operator-did",
        rationale=(
            "AT Protocol XRPC publisher; multi-identity (operator + oudepode). "
            "Substrate complete + tested. Awaiting operator app-password "
            "bootstrap. When creds arrive, add a `bluesky-atproto` entry to "
            "publish_orchestrator._DISPATCH_MAP via adapter."
        ),
    ),
    "agents.publication_bus.bridgy_publisher": WireEntry(
        module="agents.publication_bus.bridgy_publisher",
        surface_slug="bridgy-webmention-publish",
        status="CRED_BLOCKED",
        pass_key_required=None,  # No creds; needs hapax-assets repo
        rationale=(
            "POSSE webmention via brid.gy/publish/webmention. No API key "
            "needed, but depends on the operator's omg.lol weblog being "
            "live as the source URL. Wire when assets/weblog are bootstrapped."
        ),
    ),
    "agents.publication_bus.internet_archive_publisher": WireEntry(
        module="agents.publication_bus.internet_archive_publisher",
        surface_slug="internet-archive-ias3",
        status="CRED_BLOCKED",
        pass_key_required="ia/access-key, ia/secret-key",
        rationale=(
            "Internet Archive S3 PUT; bare-requests. Substrate complete + "
            "tested. Wire when operator inserts IA credentials."
        ),
    ),
    "agents.publication_bus.omg_weblog_publisher": WireEntry(
        module="agents.publication_bus.omg_weblog_publisher",
        surface_slug="omg-lol-weblog-bearer-fanout",
        status="WIRED",
        pass_key_required="omg-lol/api-key",
        rationale=(
            "Wired via agents/omg_weblog_publisher (legacy adapter) into "
            "publish_orchestrator._DISPATCH_MAP entries `omg-weblog` and "
            "`oudepode-omg-weblog`. Also referenced by sc_attestation_publisher "
            "and omg_rss_fanout helper."
        ),
    ),
    "agents.publication_bus.osf_prereg_publisher": WireEntry(
        module="agents.publication_bus.osf_prereg_publisher",
        surface_slug="osf-prereg",
        status="CRED_BLOCKED",
        pass_key_required="osf/api-token",
        rationale=(
            "OSF preregistration JSON:API publisher; distinct from the legacy "
            "agents/osf_preprint_publisher. Substrate complete + tested. "
            "Wire when operator inserts OSF token (separate from any "
            "preprint flow)."
        ),
    ),
    "agents.publication_bus.philarchive_publisher": WireEntry(
        module="agents.publication_bus.philarchive_publisher",
        surface_slug="philarchive-deposit",
        status="CRED_BLOCKED",
        pass_key_required="philarchive/session-cookie, philarchive/author-id",
        rationale=(
            "PhilArchive form-POST via session cookie; CONDITIONAL_ENGAGE per "
            "drop-5 §2 (one-time Playwright login produces the cookie). "
            "Substrate complete + tested. Wire when operator runs the cookie-"
            "extraction step."
        ),
    ),
    "agents.publication_bus.refusal_brief_publisher": WireEntry(
        module="agents.publication_bus.refusal_brief_publisher",
        surface_slug="zenodo-refusal-deposit",
        status="WIRED",
        pass_key_required=None,
        rationale=(
            "Wired via agents/refusal_brief_zenodo_adapter into "
            "publish_orchestrator._DISPATCH_MAP entry "
            "`zenodo-refusal-deposit`. Token from env HAPAX_ZENODO_TOKEN "
            "(hapax-secrets.service from pass `zenodo/api-token`). "
            "RelatedIdentifier graph composition (IsRequiredBy + "
            "IsObsoletedBy) ships with the publisher."
        ),
    ),
    "agents.attribution.crossref_depositor": WireEntry(
        module="agents.attribution.crossref_depositor",
        surface_slug="crossref-doi-deposit",
        status="CRED_BLOCKED",
        pass_key_required="crossref/depositor-credentials",
        rationale=(
            "Crossref DOI depositor (sibling to Zenodo). Substrate complete + "
            "tested. Wire on Crossref membership creds (operator-action gated)."
        ),
    ),
}


def status_summary() -> dict[WireStatus, int]:
    """Tally publishers by status."""
    counts: dict[WireStatus, int] = {"WIRED": 0, "CRED_BLOCKED": 0, "DELETE": 0}
    for entry in PUBLISHER_WIRE_REGISTRY.values():
        counts[entry.status] += 1
    return counts


def cred_blocked_pass_keys() -> list[str]:
    """Return the operator-action queue: pass keys needed to unblock wiring."""
    keys: list[str] = []
    for entry in PUBLISHER_WIRE_REGISTRY.values():
        if entry.status == "CRED_BLOCKED" and entry.pass_key_required:
            for k in entry.pass_key_required.split(","):
                keys.append(k.strip())
    return sorted(set(keys))


__all__ = [
    "PUBLISHER_WIRE_REGISTRY",
    "WireEntry",
    "WireStatus",
    "cred_blocked_pass_keys",
    "status_summary",
]
