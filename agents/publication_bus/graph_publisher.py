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
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
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
from shared.governance.omg_referent import ENV_OPERATOR_LEGAL_NAME

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


def _bound_graph_creators(base: dict) -> list[dict[str, str]]:
    """Use the existing formal-name binding only at the admitted egress boundary.

    The graph caller has no separately authorized coauthor input. Refuse a
    conflicting override instead of inventing identity or silently replacing it.
    Never include the binding's value in diagnostics or local graph state.
    """
    raw_name = os.environ.get(ENV_OPERATOR_LEGAL_NAME, "")
    name = raw_name.strip()
    creators = [{"name": name}]
    if (
        not name
        or not raw_name.isprintable()
        or ("creators" in base and base["creators"] != creators)
    ):
        raise GraphPublisherError(
            "creator identity unavailable, invalid or conflicts with the declared binding. "
            "Next action: reconcile HAPAX_OPERATOR_NAME and graph creator metadata under "
            "the publication authority before retry; no remote attempt was started"
        )
    return creators


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
                prev_concept=prev_concept,
                deposit_metadata=deposit_metadata,
            )
            concept_doi = prev_concept
    except requests.RequestException as exc:
        graph_publisher_total.labels(
            outcome="mint-error" if is_first_version else "version-error"
        ).inc()
        raise GraphPublisherError("Zenodo transport failure") from exc
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
        block["creators"] = base["creators"]
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
    deposit_id = _remote_deposit_id(create_body)

    with _known_deposit(deposit_id):
        publish_resp = requests.post(
            f"{ZENODO_DEPOSIT_ENDPOINT}/{deposit_id}/actions/publish",
            headers=headers,
            timeout=ZENODO_REQUEST_TIMEOUT_S,
        )
        _raise_for_status(publish_resp, "deposit publish")
        publish_body = _safe_json(publish_resp)
        if _remote_deposit_id(publish_body) != deposit_id:
            raise GraphPublisherError("published deposit identity does not match created deposit")
        version_doi = _remote_doi(publish_body, "doi")
        concept_doi = _remote_doi(publish_body, "conceptdoi")
        return deposit_id, version_doi, concept_doi


def _create_new_version(
    *,
    headers: dict,
    prev_id: int,
    prev_concept: str,
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
    # Zenodo returns the original resource here, not the new draft. Only the
    # declared deposition link identifies the version we may update/publish.
    # https://developers.zenodo.org/#new-version
    if _remote_deposit_id(newver_body) != prev_id:
        raise GraphPublisherError("newversion response does not match previous deposit")
    links = newver_body.get("links")
    draft_url = links.get("latest_draft") if isinstance(links, dict) else None
    prefix = ZENODO_DEPOSIT_ENDPOINT + "/"
    if not isinstance(draft_url, str) or not draft_url.startswith(prefix):
        raise GraphPublisherError("newversion response missing or invalid latest_draft link")
    draft_id = draft_url[len(prefix) :]
    if not draft_id.isascii() or not draft_id.isdecimal() or int(draft_id) <= 0:
        raise GraphPublisherError("newversion latest_draft has invalid deposit identity")
    new_id = int(draft_id)
    if new_id == prev_id:
        raise GraphPublisherError("newversion response reused previous deposit identity")

    with _known_deposit(new_id):
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
        if _remote_deposit_id(publish_body) != new_id:
            raise GraphPublisherError("published deposit identity does not match new version")
        version_doi = _remote_doi(publish_body, "doi")
        if _remote_doi(publish_body, "conceptdoi") != prev_concept:
            raise GraphPublisherError("published concept DOI does not match previous concept")
        return new_id, version_doi


@contextmanager
def _known_deposit(deposit_id: int) -> Iterator[None]:
    """Retain the validated reconciliation identity without response/token contents."""
    try:
        yield
    except GraphPublisherError as exc:
        raise GraphPublisherError(f"{exc}; deposit_id={deposit_id}") from exc
    except requests.RequestException as exc:
        raise GraphPublisherError(f"Zenodo transport failure; deposit_id={deposit_id}") from exc


def _remote_deposit_id(body: dict) -> int:
    deposit_id = body.get("id")
    if type(deposit_id) is not int or deposit_id <= 0:
        raise GraphPublisherError("remote response missing or invalid deposit identity")
    return deposit_id


def _remote_doi(body: dict, field: str) -> str:
    doi = body.get(field)
    # Bare DOI name, not a resolver URL. Preserve its spelling; do not trim
    # malformed remote values into valid identities. This syntax check is not
    # evidence that the DOI resolves or identifies the intended public version.
    if (
        not isinstance(doi, str)
        or not doi.isprintable()
        or re.fullmatch(r"10\.[0-9]+(?:\.[0-9]+)*/\S+", doi) is None
    ):
        raise GraphPublisherError(f"remote response missing or invalid {field}")
    return doi


def _raise_for_status(response, op: str) -> None:
    """Raise GraphPublisherError on transport failure or non-2xx."""
    try:
        status = response.status_code
    except Exception as exc:
        raise GraphPublisherError(f"{op}: malformed response") from exc
    if not (200 <= status < 300):
        raise GraphPublisherError(f"{op}: HTTP {status}")


def _safe_json(response) -> dict:
    try:
        body = response.json()
    except (ValueError, AttributeError) as exc:
        raise GraphPublisherError("unparseable JSON response") from exc
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

    Append the remote identity before updating the three checkpoint files,
    with the fingerprint last. Flush each file and its directory before the
    publisher can clear its attempt fence. On any failure the fence remains,
    including failure before the first history write.
    """
    graph_dir.mkdir(parents=True, exist_ok=True)
    history_entry = {
        "concept_doi": concept_doi,
        "version_doi": version_doi,
        "fingerprint": fingerprint,
        "deposit_id": deposit_id,
    }
    history_path = graph_dir / "version-doi-history.jsonl"
    with history_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(history_entry) + "\n")
        f.flush()
        os.fsync(f.fileno())
    for name, value in (
        ("concept-doi.txt", concept_doi),
        ("last-deposit-id.txt", str(deposit_id)),
        ("last-fingerprint.txt", fingerprint),
    ):
        with (graph_dir / name).open("w", encoding="utf-8") as f:
            f.write(value + "\n")
            f.flush()
            os.fsync(f.fileno())
    _sync_directory(graph_dir)


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _begin_attempt(graph_dir: Path, fingerprint: str) -> None:
    """Exclusively fence this graph before reading state or sending a request.

    Presence alone blocks; empty/torn records are also unresolved attempts.
    Never expire or automatically recover one: the remote outcome is unknown.
    Create the intended directory chain on first use. Sync every ancestor
    before remote I/O, including on retries after failed provisioning; merely
    observing an existing directory does not establish its durability.
    """
    graph_dir.mkdir(parents=True, exist_ok=True)
    with (graph_dir / "mint-attempt.json").open("x", encoding="utf-8") as f:
        json.dump({"fingerprint": fingerprint}, f)
        f.flush()
        os.fsync(f.fileno())
    _sync_directory(graph_dir)
    for parent in graph_dir.parents:
        _sync_directory(parent)


def _finish_attempt(graph_dir: Path) -> None:
    """Only called after durable persistence or a validated no-change result."""
    (graph_dir / "mint-attempt.json").unlink()
    _sync_directory(graph_dir)


def _persisted_fingerprint(graph_dir: Path) -> str | None:
    """Read a consistent existing checkpoint; absence alone permits first mint.

    Keep the existing four-file state contract. Incomplete, unreadable or
    inconsistent state requires reconciliation, never a first-mint fallback
    or a successful no-change result based on the fingerprint file alone.
    """
    paths = [
        graph_dir / name
        for name in (
            "concept-doi.txt",
            "last-deposit-id.txt",
            "last-fingerprint.txt",
            "version-doi-history.jsonl",
        )
    ]
    try:
        if not any(path.exists() for path in paths):
            return None
        concept = paths[0].read_text(encoding="utf-8").removesuffix("\n")
        deposit, fingerprint = [path.read_text(encoding="utf-8").strip() for path in paths[1:3]]
        last = json.loads(paths[3].read_text(encoding="utf-8").splitlines()[-1])
        if (
            not concept
            or not fingerprint
            or int(deposit) <= 0
            or not isinstance(last, dict)
            or last.get("concept_doi") != concept
            or last.get("deposit_id") != int(deposit)
            or last.get("fingerprint") != fingerprint
            or not isinstance(last.get("version_doi"), str)
            or not last["version_doi"]
        ):
            raise ValueError("checkpoint does not match latest history entry")
        _remote_doi({"conceptdoi": concept}, "conceptdoi")
        _remote_doi(last, "version_doi")
    except (GraphPublisherError, OSError, ValueError, IndexError) as exc:
        raise GraphPublisherError(
            "graph state incomplete or inconsistent; reconcile remote DOI and local state before retry"
        ) from exc
    return fingerprint


class GraphPublisher(Publisher):
    """V5 publication-bus subclass for the constellation-graph deposit.

    ``payload.metadata`` MUST contain ``snapshot_path`` and
    ``fingerprint``; may include ``deposit_metadata`` (Zenodo metadata
    block override). Exclusively fences the attempt, checks the existing
    checkpoint, skips unchanged graphs, then mints and persists within admission.
    A surviving fence requires remote reconciliation before another invocation;
    clearing it is a separate recovery act, never a retry/timeout policy.
    The result's ``detail`` carries
    the remote DOIs and deposit ID, including when persistence fails after
    emission. No automatic retry is performed on an ambiguous outcome.

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
            deposit_metadata["creators"] = _bound_graph_creators(deposit_metadata)
        except GraphPublisherError as exc:
            return PublisherResult(refused=True, detail=str(exc))
        recovery = (
            f"reconcile remote DOI and local state before retry; inspect "
            f"{self.graph_dir / 'mint-attempt.json'}, verify the remote outcome and repair "
            "the checkpoint before clearing the attempt fence"
        )

        try:
            _begin_attempt(self.graph_dir, str(fingerprint))
            previous_fingerprint = _persisted_fingerprint(self.graph_dir)
            if previous_fingerprint == str(fingerprint):
                _finish_attempt(self.graph_dir)
                return PublisherResult(
                    ok=True, detail="(no material change since last deposit; skipping mint)"
                )
            concept_doi, version_doi, deposit_id = mint_or_version(
                zenodo_token=self.zenodo_token,
                graph_dir=self.graph_dir,
                snapshot_path=Path(str(snapshot_path_raw)),
                fingerprint=str(fingerprint),
                metadata=deposit_metadata,
            )
        except (GraphPublisherError, OSError) as exc:
            return PublisherResult(error=True, detail=f"graph publication held: {exc}; {recovery}")

        remote_identity = (
            f"concept-DOI={concept_doi} version-DOI={version_doi} (deposit_id={deposit_id})"
        )
        try:
            persist_graph_state(
                graph_dir=self.graph_dir,
                concept_doi=concept_doi,
                version_doi=version_doi,
                fingerprint=str(fingerprint),
                deposit_id=deposit_id,
            )
            _finish_attempt(self.graph_dir)
        except OSError:
            log.exception("graph publisher: state persistence failed after %s", remote_identity)
            return PublisherResult(
                error=True,
                detail=(
                    f"state persistence failed after remote mint: {remote_identity}; {recovery}"
                ),
            )

        return PublisherResult(
            ok=True,
            detail=f"minted {remote_identity}",
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
