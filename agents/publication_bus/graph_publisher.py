"""Self-citation graph DOI minter — Phase 2 wired path.

Phase 1 lives in ``agents/publication_bus/self_citation_graph_doi.py``
(scaffold + scan + material-change detector + dry-run report). This
module owns the actual minting:

- :func:`mint_or_version` performs the Zenodo deposit + publish flow
  on first run (concept-DOI mint) and the Zenodo new-version flow on
  subsequent material changes.
- :func:`persist_graph_state` writes ``concept-doi.txt``,
  ``last-fingerprint.txt``, ``last-deposit-id.txt`` and appends to
  ``version-doi-history.jsonl``.
- :class:`GraphPublisher` is the V5 :class:`Publisher` subclass that
  wraps these helpers with the three load-bearing invariants
  (allowlist, legal-name guard, Counter). ``requires_legal_name=True``
  because Zenodo's creators array uses the formal legal name.

Spec: ``docs/superpowers/specs/2026-04-25-publication-bus-v5-design.md``
+ drop-5 fresh-pattern §3 #1 (DataCite GraphQL self-citation graph).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import ClassVar

from prometheus_client import Counter

from agents.publication_bus.publisher_kit import (
    Publisher,
    PublisherPayload,
    PublisherResult,
)
from agents.publication_bus.publisher_kit.allowlist import (
    AllowlistGate,
    load_allowlist,
)

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

log = logging.getLogger(__name__)


graph_publisher_total = Counter(
    "hapax_publication_bus_graph_publisher_total",
    "Citation-graph DOI mint + version outcomes per result.",
    ["outcome"],
)
"""Outcomes:

- ``mint-ok`` — first-version concept-DOI minted successfully.
- ``version-ok`` — new version-DOI minted successfully.
- ``mint-error`` — first-version mint failed (transport/API/missing-deps).
- ``version-error`` — new-version mint failed.

The ``no-token`` case is recorded by the caller
(``self_citation_graph_doi``) before reaching this module."""


GRAPH_PUBLISHER_SURFACE: str = "datacite-graphql-mirror"
"""Stable surface identifier; mirrored in
:data:`agents.publication_bus.surface_registry.SURFACE_REGISTRY`."""

GRAPH_DEPOSIT_TYPE: str = "constellation-graph"
"""Hapax-internal deposit-type tag carried in the deposit description
+ keywords. Surfaces in DataCite as a discoverable graph artefact."""

ZENODO_DEPOSIT_ENDPOINT: str = "https://zenodo.org/api/deposit/depositions"
"""Zenodo REST API depositions endpoint."""

ZENODO_REQUEST_TIMEOUT_S: float = 60.0
"""Graph deposits are small JSON; 60s is generous."""

DEFAULT_GRAPH_PUBLISHER_ALLOWLIST: AllowlistGate = load_allowlist(
    GRAPH_PUBLISHER_SURFACE,
    permitted=[GRAPH_PUBLISHER_SURFACE],
)
"""Single-target allowlist — the surface only ever publishes to its own slug."""


class GraphPublisherError(RuntimeError):
    """Transport / API failure during a Zenodo mint or new-version flow."""


def mint_or_version(
    *,
    zenodo_token: str,
    graph_dir: Path,
    snapshot_path: Path,
    fingerprint: str,
    metadata: dict,
) -> tuple[str, str, int]:
    """Mint a new concept-DOI on first run, or a new version-DOI on subsequent material changes.

    Returns ``(concept_doi, version_doi, deposit_id)``. The caller
    persists state via :func:`persist_graph_state`.

    Raises :class:`GraphPublisherError` for any non-2xx response or
    transport failure. Caller catches and reports as a publisher
    error result.
    """
    if requests is None:
        graph_publisher_total.labels(outcome="mint-error").inc()
        raise GraphPublisherError("requests library not available")

    concept_doi_path = graph_dir / "concept-doi.txt"
    last_deposit_id_path = graph_dir / "last-deposit-id.txt"
    is_first_version = not (concept_doi_path.is_file() and last_deposit_id_path.is_file())

    deposit_metadata = _build_deposit_metadata(
        snapshot_path=snapshot_path, fingerprint=fingerprint, base=metadata
    )
    headers = {
        "Authorization": f"Bearer {zenodo_token}",
        "Content-Type": "application/json",
    }

    try:
        if is_first_version:
            deposit_id, version_doi, concept_doi = _create_first_version(
                headers=headers, deposit_metadata=deposit_metadata
            )
        else:
            prev_concept = concept_doi_path.read_text(encoding="utf-8").strip()
            prev_id_text = last_deposit_id_path.read_text(encoding="utf-8").strip()
            try:
                prev_id = int(prev_id_text)
            except ValueError as exc:
                # Counter increment happens in the outer GraphPublisherError catch;
                # this raises into that handler rather than double-counting.
                raise GraphPublisherError(f"corrupt last-deposit-id.txt: {prev_id_text!r}") from exc
            deposit_id, version_doi = _create_new_version(
                headers=headers,
                prev_id=prev_id,
                deposit_metadata=deposit_metadata,
            )
            concept_doi = prev_concept
    except requests.RequestException as exc:
        graph_publisher_total.labels(
            outcome="mint-error" if is_first_version else "version-error"
        ).inc()
        raise GraphPublisherError(f"Zenodo transport failure: {exc}") from exc
    except GraphPublisherError:
        graph_publisher_total.labels(
            outcome="mint-error" if is_first_version else "version-error"
        ).inc()
        raise

    graph_publisher_total.labels(outcome="mint-ok" if is_first_version else "version-ok").inc()
    return concept_doi, version_doi, deposit_id


def _build_deposit_metadata(
    *,
    snapshot_path: Path,
    fingerprint: str,
    base: dict,
) -> dict:
    """Compose the Zenodo deposit metadata block from caller-provided base."""
    title = base.get("title") or "Hapax constellation graph (DataCite GraphQL)"
    description = base.get("description") or (
        "Self-citation graph derived from a parameterised DataCite GraphQL "
        "query against Hapax's authored works. Each version-DOI captures "
        "the graph topology at a specific snapshot; the concept-DOI is "
        "stable across versions. Refusal-as-data + infrastructure-as-argument."
    )
    keywords = list(
        base.get(
            "keywords",
            [
                GRAPH_DEPOSIT_TYPE,
                "self-citation",
                "datacite-graphql",
                "refusal-as-data",
                "infrastructure-as-argument",
            ],
        )
    )
    block = {
        "title": title,
        "upload_type": "publication",
        "publication_type": "other",
        "description": description,
        "keywords": keywords,
        "notes": (f"snapshot={snapshot_path.name} topology_fingerprint={fingerprint}"),
    }
    if "related_identifiers" in base:
        block["related_identifiers"] = base["related_identifiers"]
    if "creators" in base:
        creators = []
        for c in base["creators"]:
            if isinstance(c, dict) and "name" in c:
                creators.append(c)
            else:
                creators.append({"name": str(c)})
        block["creators"] = creators
    else:
        block["creators"] = [{"name": "Hapax System"}]
    return block


def _create_first_version(
    *,
    headers: dict,
    deposit_metadata: dict,
) -> tuple[int, str, str]:
    """POST /depositions then POST /actions/publish; returns (id, version_doi, concept_doi)."""
    create_resp = requests.post(
        ZENODO_DEPOSIT_ENDPOINT,
        json={"metadata": deposit_metadata},
        headers=headers,
        timeout=ZENODO_REQUEST_TIMEOUT_S,
    )
    _raise_for_status(create_resp, "deposit create")
    create_body = _safe_json(create_resp)
    deposit_id = int(create_body.get("id"))

    publish_resp = requests.post(
        f"{ZENODO_DEPOSIT_ENDPOINT}/{deposit_id}/actions/publish",
        headers=headers,
        timeout=ZENODO_REQUEST_TIMEOUT_S,
    )
    _raise_for_status(publish_resp, "deposit publish")
    publish_body = _safe_json(publish_resp)
    version_doi = str(publish_body.get("doi") or create_body.get("doi") or "")
    concept_doi = str(publish_body.get("conceptdoi") or version_doi)
    return deposit_id, version_doi, concept_doi


def _create_new_version(
    *,
    headers: dict,
    prev_id: int,
    deposit_metadata: dict,
) -> tuple[int, str]:
    """POST /actions/newversion → PUT metadata → POST /actions/publish; returns (id, version_doi)."""
    newver_resp = requests.post(
        f"{ZENODO_DEPOSIT_ENDPOINT}/{prev_id}/actions/newversion",
        headers=headers,
        timeout=ZENODO_REQUEST_TIMEOUT_S,
    )
    _raise_for_status(newver_resp, "newversion")
    newver_body = _safe_json(newver_resp)
    new_id = int(newver_body.get("id") or 0)
    if not new_id:
        raise GraphPublisherError("newversion response missing id")

    put_resp = requests.put(
        f"{ZENODO_DEPOSIT_ENDPOINT}/{new_id}",
        json={"metadata": deposit_metadata},
        headers=headers,
        timeout=ZENODO_REQUEST_TIMEOUT_S,
    )
    _raise_for_status(put_resp, "metadata update")

    publish_resp = requests.post(
        f"{ZENODO_DEPOSIT_ENDPOINT}/{new_id}/actions/publish",
        headers=headers,
        timeout=ZENODO_REQUEST_TIMEOUT_S,
    )
    _raise_for_status(publish_resp, "new-version publish")
    publish_body = _safe_json(publish_resp)
    version_doi = str(publish_body.get("doi") or newver_body.get("doi") or "")
    return new_id, version_doi


def _raise_for_status(response, op: str) -> None:
    """Raise GraphPublisherError on transport failure or non-2xx."""
    try:
        status = response.status_code
    except Exception as exc:
        raise GraphPublisherError(f"{op}: malformed response: {exc}") from exc
    if not (200 <= status < 300):
        body = getattr(response, "text", "")[:160]
        raise GraphPublisherError(f"{op}: HTTP {status}: {body}")


def _safe_json(response) -> dict:
    try:
        body = response.json()
    except (ValueError, AttributeError) as exc:
        raise GraphPublisherError(f"unparseable JSON response: {exc}") from exc
    if not isinstance(body, dict):
        raise GraphPublisherError(f"unexpected JSON shape: {type(body).__name__}")
    return body


def persist_graph_state(
    *,
    graph_dir: Path,
    concept_doi: str,
    version_doi: str,
    fingerprint: str,
    deposit_id: int,
) -> None:
    """Persist the freshly-minted DOI state.

    Writes ``concept-doi.txt`` (idempotent — first version sets it,
    subsequent calls overwrite with the same value), overwrites
    ``last-fingerprint.txt`` and ``last-deposit-id.txt``, and appends
    a JSONL entry to ``version-doi-history.jsonl``.
    """
    graph_dir.mkdir(parents=True, exist_ok=True)
    (graph_dir / "concept-doi.txt").write_text(concept_doi + "\n", encoding="utf-8")
    (graph_dir / "last-fingerprint.txt").write_text(fingerprint + "\n", encoding="utf-8")
    (graph_dir / "last-deposit-id.txt").write_text(str(deposit_id) + "\n", encoding="utf-8")

    history_entry = {
        "concept_doi": concept_doi,
        "version_doi": version_doi,
        "fingerprint": fingerprint,
        "deposit_id": deposit_id,
    }
    history_path = graph_dir / "version-doi-history.jsonl"
    with history_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(history_entry) + "\n")


class GraphPublisher(Publisher):
    """V5 publication-bus subclass for the constellation-graph deposit.

    ``payload.metadata`` MUST contain ``snapshot_path`` and
    ``fingerprint``; may include ``deposit_metadata`` (Zenodo metadata
    block override) for tests. Dispatches to :func:`mint_or_version`
    (which selects first-version vs new-version based on graph_dir
    state) and returns a :class:`PublisherResult` carrying the minted
    DOIs in ``detail``.

    ``requires_legal_name=True``: Zenodo creators array uses the formal
    legal name; the legal-name guard is skipped on this surface.
    """

    surface_name: ClassVar[str] = GRAPH_PUBLISHER_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_GRAPH_PUBLISHER_ALLOWLIST
    requires_legal_name: ClassVar[bool] = True

    def __init__(self, *, zenodo_token: str, graph_dir: Path) -> None:
        self.zenodo_token = zenodo_token
        self.graph_dir = graph_dir

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        if not self.zenodo_token:
            return PublisherResult(
                refused=True,
                detail=(
                    "missing Zenodo credentials "
                    "(operator-action queue: configure HAPAX_ZENODO_TOKEN)"
                ),
            )
        snapshot_path_raw = payload.metadata.get("snapshot_path")
        fingerprint = payload.metadata.get("fingerprint")
        if not snapshot_path_raw or not fingerprint:
            return PublisherResult(
                error=True,
                detail="payload missing snapshot_path or fingerprint",
            )
        deposit_metadata = dict(payload.metadata.get("deposit_metadata", {}) or {})

        try:
            concept_doi, version_doi, _deposit_id = mint_or_version(
                zenodo_token=self.zenodo_token,
                graph_dir=self.graph_dir,
                snapshot_path=Path(str(snapshot_path_raw)),
                fingerprint=str(fingerprint),
                metadata=deposit_metadata,
            )
        except GraphPublisherError as exc:
            return PublisherResult(error=True, detail=f"{exc}")

        return PublisherResult(
            ok=True,
            detail=f"version-DOI {version_doi} (concept {concept_doi})",
        )


__all__ = [
    "DEFAULT_GRAPH_PUBLISHER_ALLOWLIST",
    "GRAPH_DEPOSIT_TYPE",
    "GRAPH_PUBLISHER_SURFACE",
    "GraphPublisher",
    "GraphPublisherError",
    "ZENODO_DEPOSIT_ENDPOINT",
    "ZENODO_REQUEST_TIMEOUT_S",
    "mint_or_version",
    "persist_graph_state",
]
