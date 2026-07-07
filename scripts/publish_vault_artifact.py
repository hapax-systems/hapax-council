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
approved publication. No separate inbox-review step.

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


class PublicationGateError(ValueError):
    """Raised when a draft lacks explicit public-publication clearance."""


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
        log.error("YAML frontmatter in %s is invalid; refusing public publication", path)
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


def _configured_publication_surfaces(paths: Iterable[Path] = PUBLICATION_POLICY_PATHS) -> set[str]:
    surfaces: set[str] = set()
    for path in paths:
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise SurfaceAllowlistError(f"surface policy unreadable: {path}") from exc
        if not isinstance(loaded, Mapping):
            continue
        policy = loaded.get("publication_frontmatter_policy")
        if not isinstance(policy, Mapping):
            continue
        target_surfaces = policy.get("target_surfaces")
        if not isinstance(target_surfaces, list):
            continue
        surfaces.update(surface for surface in target_surfaces if isinstance(surface, str))
    if not surfaces:
        raise SurfaceAllowlistError("no target surface allowlist configured")
    return surfaces


def _assert_target_surfaces_allowed(surfaces: list[str]) -> None:
    allowed = _configured_publication_surfaces()
    disallowed = sorted(set(surfaces) - allowed)
    if disallowed:
        raise SurfaceAllowlistError(
            "target surfaces outside configured allowlist: " + ", ".join(disallowed)
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

    frontmatter, body = _parse_publication_markdown(args.path)
    if not body.strip():
        log.error("empty body in %s", args.path)
        return 2
    surfaces = _parse_surfaces(args.surfaces)
    try:
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
