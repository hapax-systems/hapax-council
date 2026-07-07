#!/usr/bin/env python3
"""Drop a vault markdown file into the publish-bus inbox as a PreprintArtifact.

Operator-facing CLI for the FULL_AUTO publish path. Reads a markdown file
with YAML frontmatter from the Obsidian vault, constructs a
``PreprintArtifact`` from it, enforces ``Publication-Allowed`` frontmatter,
marks allowed artifacts ``APPROVED``, and writes the JSON to
``$HAPAX_STATE/publish/inbox/{slug}.json``. The publish_orchestrator service
picks it up on the next 30s tick and fans out to every surface listed in
``surfaces_targeted`` via ``SURFACE_REGISTRY``.

## Frontmatter contract

The vault file's YAML frontmatter MUST include:

  title: str           # used as PreprintArtifact.title
  slug:  str           # used as filename + omg.lol entry slug
  type:  str           # informational only
  Publication-Allowed: true  # explicit Claim Verification Council clearance
  publication_gate_receipts:
    source_artifact_public_safe: receipt-ref
    source_refs_present: receipt-ref
    rights_privacy_redaction_pass: receipt-ref
    target_surface_allowlist_pass: receipt-ref
    claim_review_current: receipt-ref
    no_direct_public_egress: receipt-ref

Optional:

  surfaces_targeted: list[str]  # else default to [zenodo-doi, omg-weblog]
  attribution_block: str        # else inferred from operator + co-authors
  abstract:          str        # else first ~500 chars of body
  author_model:      str        # reviewer author-model hint
  doi:               str        # for cross-citation

## Approval semantics

This script marks the artifact ``APPROVED`` directly only when frontmatter
explicitly allows publication. The vault is the operator's editing surface;
once an allowed vault file lands at this script, the operator has implicitly
approved publication. No separate inbox-review step. There is no bypass in
this CLI for public egress: invalid YAML, missing clearance, malformed
clearance, unreadable policy, or out-of-allowlist target surfaces must stop
before an inbox artifact is written. Break-glass correction or takedown is a
surface-specific operator action outside this approval path and must leave its
own incident/authority receipt before any replacement artifact is published.

## Usage

  uv run python scripts/publish_vault_artifact.py \\
      ~/Documents/Personal/30-areas/hapax/refusal-brief.md \\
      --surfaces zenodo-doi,omg-weblog

  uv run python scripts/publish_vault_artifact.py \\
      ~/Documents/Personal/30-areas/hapax/refusal-brief.md \\
      --dry-run            # print the artifact JSON, don't write to inbox
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

import yaml

from agents.publication_bus.surface_registry import dispatch_registry
from shared.co_author_model import CoAuthor
from shared.co_author_model import get as get_co_author
from shared.frontmatter import parse_frontmatter_with_diagnostics
from shared.preprint_artifact import ApprovalState, PreprintArtifact

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SURFACES = ["zenodo-doi", "omg-weblog"]
PUBLICATION_POLICY_PATHS = (
    REPO_ROOT / "config" / "omg-lol.yaml",
    REPO_ROOT / "config" / "omg-lol-fanout.yaml",
)
PUBLICATION_ALLOWED_TRUE_VALUES = frozenset({"true", "yes", "1", "allowed", "approved"})
PUBLICATION_ALLOWED_FALSE_VALUES = frozenset({"false", "no", "0", "blocked", "withheld"})
PUBLICATION_GATE_RECEIPT_KEYS = (
    "publication_gate_receipts",
    "Publication-Gate-Receipts",
    "publication-gate-receipts",
)
FANOUT_SURFACE_IDS = frozenset({"omg-lol-weblog-bearer-fanout"})
PUBLICATION_BASELINE_REQUIRED_GATES = (
    "source_artifact_public_safe",
    "source_refs_present",
    "rights_privacy_redaction_pass",
    "target_surface_allowlist_pass",
    "claim_review_current",
    "no_direct_public_egress",
)
PUBLICATION_FANOUT_REQUIRED_GATES = (
    *PUBLICATION_BASELINE_REQUIRED_GATES,
    "fanout_loop_prevention_present",
)


class PublicationGateError(ValueError):
    """Raised when a draft lacks explicit public-publication clearance."""


class PublicationFrontmatterError(PublicationGateError):
    """Raised when publication frontmatter is structurally unsafe."""


class SurfaceAllowlistError(PublicationGateError):
    """Raised when a draft targets a surface outside configured public policy."""


def _default_state_root() -> Path:
    env = os.environ.get("HAPAX_STATE")
    if env:
        return Path(env)
    return Path.home() / "hapax-state"


def _resolve_co_authors(frontmatter: dict) -> list[CoAuthor]:
    """Resolve frontmatter ``co_authors`` to canonical ``CoAuthor`` objects.

    Recognized entry shapes (each must round-trip cleanly to a registered
    ``CoAuthor`` — partial matches default to ALL_CO_AUTHORS to avoid
    silent author dropping):

      - ``"hapax"`` / ``"claude-code"`` / ``"oudepode"`` — alias keys
      - ``"Hapax (entity, primary)"`` — first-token-stem normalized to
        kebab-case, looked up via ``shared.co_author_model.get()``
      - ``{"alias": "..."}`` — dict with explicit alias

    If the frontmatter list is absent OR any entry fails to resolve,
    return ``[]`` so the ``PreprintArtifact`` constructor populates with
    ``ALL_CO_AUTHORS``. This avoids silently shipping with fewer authors
    than the operator intended.
    """
    raw = frontmatter.get("co_authors")
    if not raw:
        return []  # PreprintArtifact default → ALL_CO_AUTHORS

    resolved: list[CoAuthor] = []
    for entry in raw:
        co = _resolve_one_co_author(entry)
        if co is None:
            log.warning(
                "co_author %r could not be resolved; falling back to default ALL_CO_AUTHORS",
                entry,
            )
            return []
        resolved.append(co)
    return resolved


def _resolve_one_co_author(entry) -> CoAuthor | None:  # type: ignore[no-untyped-def]
    """Resolve a single frontmatter entry to a ``CoAuthor`` or ``None``.

    Splits on first ``(`` to lift the name out of "Name (role, ...)"
    prose; normalizes to kebab-case-lowercase before hitting
    ``co_author_model.get``.
    """
    if isinstance(entry, dict):
        alias = entry.get("alias") or entry.get("key")
        if not alias:
            return None
        try:
            return get_co_author(str(alias))
        except KeyError:
            return None

    if not isinstance(entry, str):
        return None

    stripped = entry.strip()
    name_part = stripped.split("(", 1)[0].strip()
    key = name_part.lower().replace(" ", "-")
    try:
        return get_co_author(key)
    except KeyError:
        return None


def _parse_publication_markdown(path: Path) -> tuple[dict, str]:
    result = parse_frontmatter_with_diagnostics(path)
    if result.ok:
        return result.frontmatter or {}, result.body

    if result.error_kind == "yaml_error":
        raise PublicationFrontmatterError(f"YAML frontmatter is invalid: {path}")
    return {}, result.body


def _publication_allowed(frontmatter: dict) -> bool:
    value = _frontmatter_value(
        frontmatter,
        "Publication-Allowed",
        "publication_allowed",
        "publication-allowed",
    )
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in PUBLICATION_ALLOWED_TRUE_VALUES:
            return True
        if normalized in PUBLICATION_ALLOWED_FALSE_VALUES:
            return False
    return False


def _configured_publication_surfaces(paths: Iterable[Path] | None = None) -> set[str]:
    surfaces: set[str] = set()
    paths = PUBLICATION_POLICY_PATHS if paths is None else paths
    for policy in _configured_publication_policies(paths):
        target_surfaces = policy.get("target_surfaces")
        if not isinstance(target_surfaces, list) or not target_surfaces:
            raise SurfaceAllowlistError(
                "surface policy target_surfaces must be a non-empty list; "
                "next action: repair config/omg-lol*.yaml before publishing"
            )
        non_string = [surface for surface in target_surfaces if not isinstance(surface, str)]
        if non_string:
            raise SurfaceAllowlistError(
                "surface policy target_surfaces must be strings; "
                "next action: repair config/omg-lol*.yaml before publishing"
            )
        surfaces.update(surface for surface in target_surfaces if isinstance(surface, str))
    if not surfaces:
        raise SurfaceAllowlistError(
            "no target surface allowlist configured; next action: repair "
            "config/omg-lol*.yaml before publishing"
        )
    return surfaces


def _configured_publication_policies(
    paths: Iterable[Path] | None = None,
) -> list[Mapping[str, object]]:
    policies: list[Mapping[str, object]] = []
    paths = PUBLICATION_POLICY_PATHS if paths is None else paths
    for path in paths:
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise SurfaceAllowlistError(
                f"surface policy unreadable: {path}; next action: repair readable "
                "YAML policy before publishing"
            ) from exc
        if not isinstance(loaded, Mapping):
            raise SurfaceAllowlistError(
                f"surface policy must be a mapping: {path}; next action: restore "
                "the publication_frontmatter_policy mapping"
            )
        policy = loaded.get("publication_frontmatter_policy")
        if not isinstance(policy, Mapping):
            raise SurfaceAllowlistError(
                f"surface policy missing publication_frontmatter_policy: {path}; "
                "next action: restore required public-egress policy fields"
            )
        policies.append(policy)
    return policies


def _assert_target_surfaces_allowed(surfaces: list[str]) -> None:
    if not surfaces:
        raise SurfaceAllowlistError(
            "target surfaces must be a non-empty list; next action: pass at least one "
            "publication-bus dispatchable surface"
        )
    allowed = _configured_publication_surfaces()
    disallowed = sorted(set(surfaces) - allowed)
    if disallowed:
        raise SurfaceAllowlistError(
            "target surfaces outside configured allowlist: "
            + ", ".join(disallowed)
            + "; next action: remove those targets from frontmatter or add them to the "
            "reviewed publication_frontmatter_policy.target_surfaces allowlist"
        )
    dispatchable = set(dispatch_registry())
    unwired = sorted(set(surfaces) - dispatchable)
    if unwired:
        raise SurfaceAllowlistError(
            "target surfaces are not dispatchable by publish_orchestrator: "
            + ", ".join(unwired)
            + "; next action: target a dispatchable surface or wire a dispatch_entry first"
        )


def _required_publication_gate_receipts(surfaces: list[str]) -> set[str]:
    selected = set(surfaces)
    required: set[str] = set()
    for policy in _configured_publication_policies():
        target_surfaces = policy.get("target_surfaces")
        if not isinstance(target_surfaces, list):
            continue
        policy_targets = {surface for surface in target_surfaces if isinstance(surface, str)}
        if not selected.intersection(policy_targets):
            continue
        if policy.get("status") == "guarded_public_fanout" and not selected.intersection(
            FANOUT_SURFACE_IDS
        ):
            continue
        required.update(_policy_required_gate_ids(policy))
    if not required:
        raise PublicationGateError(
            "no publication gate policy covers target surfaces; next action: add the "
            "surface policy before publishing"
        )
    return required


def _policy_required_gate_ids(policy: Mapping[str, object]) -> set[str]:
    baseline = (
        PUBLICATION_FANOUT_REQUIRED_GATES
        if policy.get("status") == "guarded_public_fanout"
        else PUBLICATION_BASELINE_REQUIRED_GATES
    )
    gates = policy.get("required_gates")
    if not isinstance(gates, list) or not gates:
        raise PublicationGateError(
            "publication policy has no required_gates; next action: repair "
            "config/omg-lol*.yaml before publishing"
        )

    normalized: set[str] = set()
    malformed = False
    for gate in gates:
        if not isinstance(gate, str) or not gate.strip():
            malformed = True
            continue
        normalized.add(gate.strip())
    if malformed:
        raise PublicationGateError(
            "publication policy required_gates contains blank or non-string gate ids; "
            "next action: repair config/omg-lol*.yaml before publishing"
        )

    missing = sorted(set(baseline) - normalized)
    if missing:
        raise PublicationGateError(
            "publication policy required_gates missing baseline gate ids: "
            + ", ".join(missing)
            + "; next action: restore the baseline publication gate list before publishing"
        )
    return set(baseline) | normalized


def _publication_gate_receipts(frontmatter: dict) -> dict[str, object]:
    raw = _frontmatter_value(frontmatter, *PUBLICATION_GATE_RECEIPT_KEYS)
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise PublicationGateError(
            "publication_gate_receipts must be a mapping of gate id to receipt refs"
        )
    return {str(key): value for key, value in raw.items()}


def _receipt_value_present(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, str, Mapping)):
        return any(_receipt_value_present(item) for item in value)
    return False


def _assert_publication_gate_receipts(frontmatter: dict, surfaces: list[str]) -> None:
    required = _required_publication_gate_receipts(surfaces)
    receipts = _publication_gate_receipts(frontmatter)
    missing = sorted(gate for gate in required if not _receipt_value_present(receipts.get(gate)))
    if missing:
        raise PublicationGateError(
            "publication_gate_receipts missing required receipt refs: "
            + ", ".join(missing)
            + "; next action: hold the draft until publication-bus gate receipts are recorded"
        )


def _build_artifact(
    *,
    body_md: str,
    frontmatter: dict,
    surfaces: list[str],
    approver: str,
    source_path: Path | None = None,
) -> PreprintArtifact:
    if not _publication_allowed(frontmatter):
        raise PublicationGateError("Publication-Allowed must be explicitly true")
    _assert_target_surfaces_allowed(surfaces)
    _assert_publication_gate_receipts(frontmatter, surfaces)

    title = _optional_string(_frontmatter_value(frontmatter, "title"))
    title = title or _extract_first_heading(body_md) or "Untitled"
    slug = _optional_string(_frontmatter_value(frontmatter, "slug")) or _slugify(title)
    abstract = _optional_string(_frontmatter_value(frontmatter, "abstract")) or _summarize(
        body_md, max_chars=500
    )
    attribution = _optional_string(_frontmatter_value(frontmatter, "attribution_block")) or ""
    doi = _optional_string(_frontmatter_value(frontmatter, "doi"))
    author_model = _optional_string(
        _frontmatter_value(frontmatter, "author_model", "draft_author_model", "llm_model")
    )
    publication_gate_context = _optional_mapping(
        _frontmatter_value(frontmatter, "publication_gate_context")
    )
    publication_gate_receipts = _publication_gate_receipts(frontmatter)
    if publication_gate_receipts:
        publication_gate_context = dict(publication_gate_context or {})
        publication_gate_context["publication_gate_receipts"] = publication_gate_receipts
    publication_gate_override = _optional_mapping(
        _frontmatter_value(frontmatter, "publication_gate_override")
    )

    co_authors = _resolve_co_authors(frontmatter)
    kwargs: dict = {
        "slug": slug,
        "title": title,
        "abstract": abstract,
        "body_md": body_md,
        "attribution_block": attribution,
        "surfaces_targeted": surfaces,
        "doi": doi,
    }
    if co_authors:
        kwargs["co_authors"] = co_authors
    if source_path is not None:
        kwargs["source_path"] = str(source_path)
    if author_model:
        kwargs["author_model"] = author_model
    if publication_gate_context is not None:
        kwargs["publication_gate_context"] = publication_gate_context
    if publication_gate_override is not None:
        kwargs["publication_gate_override"] = publication_gate_override

    artifact = PreprintArtifact(**kwargs)
    artifact.mark_approved(by_referent=approver)
    return artifact


def _extract_first_heading(body: str) -> str | None:
    """Pull the first ``# H1`` heading from the body, if present."""
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _summarize(body: str, *, max_chars: int) -> str:
    """First non-blank, non-heading paragraph, truncated."""
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    for para in paragraphs:
        if not para.startswith("#") and not para.startswith("---"):
            return para[:max_chars]
    return ""


def _slugify(title: str) -> str:
    """Cheap kebab-case slugifier; PreprintArtifact validates length."""
    out: list[str] = []
    for ch in title.lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "-", "_"):
            out.append("-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:120] or "untitled"


def _parse_surfaces(raw: str | None) -> list[str]:
    if not raw:
        return DEFAULT_SURFACES
    return [s.strip() for s in raw.split(",") if s.strip()]


def _frontmatter_value(frontmatter: dict, *keys: str) -> object | None:
    for key in keys:
        if key in frontmatter:
            return frontmatter[key]

    lowered = {str(raw_key).lower(): value for raw_key, value in frontmatter.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value is not None:
            return value
    return None


def _optional_string(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _optional_mapping(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    return None


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("HAPAX_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        prog="scripts.publish_vault_artifact",
        description="Drop a vault markdown file into publish-bus inbox.",
    )
    parser.add_argument("path", type=Path, help="Vault markdown file with YAML frontmatter")
    parser.add_argument(
        "--surfaces",
        default=None,
        help=(f"Comma-separated SURFACE_REGISTRY slugs (default: {','.join(DEFAULT_SURFACES)})"),
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        default=_default_state_root(),
        help="Override $HAPAX_STATE for testing",
    )
    parser.add_argument(
        "--approver",
        default="Oudepode",
        help="Operator referent to record on mark_approved (default: Oudepode)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print artifact JSON to stdout without writing to inbox",
    )
    args = parser.parse_args(argv)

    if not args.path.exists():
        log.error("vault file not found: %s", args.path)
        return 2

    try:
        frontmatter, body = _parse_publication_markdown(args.path)
    except PublicationGateError as exc:
        log.error(
            "publication not allowed for %s: %s; next action: fix YAML frontmatter "
            "and clear Publication-Allowed through Claim Verification Council review",
            args.path,
            exc,
        )
        return 1
    if not body.strip():
        log.error("empty body in %s", args.path)
        return 2
    surfaces = _parse_surfaces(args.surfaces)
    try:
        _assert_target_surfaces_allowed(surfaces)
        artifact = _build_artifact(
            body_md=body,
            frontmatter=frontmatter,
            surfaces=surfaces,
            approver=args.approver,
            source_path=args.path.expanduser().resolve(),
        )
    except PublicationGateError as exc:
        log.error(
            "publication not allowed for %s: %s; next action: rewrite and clear "
            "Publication-Allowed plus target surfaces through Claim Verification "
            "Council review",
            args.path,
            exc,
        )
        return 1

    payload = artifact.model_dump_json(indent=2)

    if args.dry_run:
        sys.stdout.write(payload + "\n")
        log.info(
            "DRY RUN — would write to %s",
            artifact.inbox_path(state_root=args.state_root),
        )
        return 0

    inbox_path = artifact.inbox_path(state_root=args.state_root)
    inbox_path.parent.mkdir(parents=True, exist_ok=True)
    inbox_path.write_text(payload)
    log.info(
        "dropped %s → %s (surfaces=%s, approval=%s)",
        artifact.slug,
        inbox_path,
        ",".join(surfaces),
        ApprovalState.APPROVED.value,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
