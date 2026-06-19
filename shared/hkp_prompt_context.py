"""HKP local prompt-context adapter.

Assembles support-only prompt context from HKP cache bundles for a LOCAL
consumer. Per the accepted contract
(``hkp-local-prompt-context-contract-2026-06-19``) this adapter is
``local_prompt_context`` (``allow_with_ceiling``):

- it emits ONLY the narrow allow-listed fields and NEVER ``body`` /
  ``private_source_path`` / ``secret`` (or any concept the policy forbids);
- every snippet carries the mandatory non-authority banner;
- it preserves the authority ceiling (``may_authorize: false``), the
  cannot-prove posture, freshness, and the cited source ref;
- it runs the section-7 redaction scan over the assembled text and refuses to
  emit if any residual private path / secret / token survives.

It assembles TEXT only; it does not call a model, write source/vault/dashboard/
Qdrant state, dispatch, close, release, mutate runtime, export publicly, or spend
provider budget. The local-only delivery boundary (resolved ``api_base`` is a
local TabbyAPI / Ollama route, and the response is not persisted to a
retrievable/observability sink) is the CALLER's obligation, stated in the
contract; this module supplies safe context plus the warning the caller must keep.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.frontmatter import parse_frontmatter_with_diagnostics  # noqa: E402
from shared.hkp_bundle_schema import HkpConceptFrontmatter  # noqa: E402

# Reuse the research viewer's redaction regexes so there is ONE redaction
# source of truth across HKP read consumers.
from shared.hkp_research_viewer import (  # noqa: E402
    ABSOLUTE_PATH_RE,
    AWS_ACCESS_KEY_RE,
    BEARER_TOKEN_RE,
    JWT_TOKEN_RE,
    PRIVATE_KEY_HEADER_RE,
    SECRET_ASSIGNMENT_RE,
)

CONSUMER_NAME = "local_prompt_context"

NON_AUTHORITY_BANNER = (
    "HKP projection is not authority — derived support context; "
    "verify against the cited source before acting."
)

# The allow_with_ceiling field set (contract section 2). Never raw body/path/secret.
ALLOWED_FIELDS = frozenset(
    {
        "title",
        "description",
        "source_refs",
        "authority",
        "freshness",
        "posture",
        "projection_provenance",
    }
)
FORBIDDEN_FIELDS = frozenset({"body", "private_source_path", "secret"})

_REDACTIONS = (
    (ABSOLUTE_PATH_RE, "[private-path-redacted]"),
    (SECRET_ASSIGNMENT_RE, "[secret-redacted]"),
    (BEARER_TOKEN_RE, "[secret-redacted]"),
    (AWS_ACCESS_KEY_RE, "[secret-redacted]"),
    (JWT_TOKEN_RE, "[secret-redacted]"),
    (PRIVATE_KEY_HEADER_RE, "[secret-redacted]"),
)

# Re-run after redaction to assert zero residual (a leak escaping redaction is a
# fail-closed condition, not a silent pass).
_RESIDUAL_RES = (ABSOLUTE_PATH_RE, BEARER_TOKEN_RE, AWS_ACCESS_KEY_RE, JWT_TOKEN_RE)


class PromptContextError(ValueError):
    """Fail-closed error: the adapter refuses to emit unsafe context."""


@dataclass
class PromptContextResult:
    text: str
    snippets: list[dict[str, Any]] = field(default_factory=list)
    concept_count: int = 0


def _redact(value: Any) -> str:
    text = str(value)
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def _assert_clean(text: str) -> str:
    for pattern in _RESIDUAL_RES:
        if pattern.search(text):
            raise PromptContextError(
                "redaction left a residual private path/secret; "
                "next-action: fix the redaction set or drop the field"
            )
    return text


def _consumer_row(policy: dict[str, Any]) -> dict[str, Any] | None:
    for row in policy.get("consumers") or []:
        if isinstance(row, dict) and row.get("consumer") == CONSUMER_NAME:
            return row
    return None


def _effective_allowed_fields(policy: dict[str, Any] | None) -> frozenset[str]:
    """Intersect the bundle's local_prompt_context allow-list with the ceiling.

    Fail-closed: anything the policy forbids, or any field outside the ceiling,
    is dropped. A missing/deny row yields the static ceiling (still never
    body/path/secret).
    """
    allowed = set(ALLOWED_FIELDS)
    if policy is not None:
        row = _consumer_row(policy)
        if row is not None:
            if str(row.get("default")) == "deny":
                return frozenset()
            policy_allowed = {str(f) for f in (row.get("allowed_fields") or [])}
            if policy_allowed:
                allowed &= policy_allowed
            allowed -= {str(f) for f in (row.get("forbidden_fields") or [])}
    return frozenset(allowed - FORBIDDEN_FIELDS)


def _primary_source(concept: HkpConceptFrontmatter) -> dict[str, str]:
    if not concept.source_refs:
        return {"uri": "(none)", "freshness_state": "unknown"}
    ref = concept.source_refs[0]
    return {
        "uri": _redact(getattr(ref, "uri", "") or "(none)"),
        "freshness_state": str(getattr(ref, "freshness_state", "unknown")),
    }


def _snippet_for_concept(concept: HkpConceptFrontmatter, allowed: frozenset[str]) -> dict[str, Any]:
    src = _primary_source(concept)
    snippet: dict[str, Any] = {
        "concept_uid": concept.concept_uid,
        "non_authority": NON_AUTHORITY_BANNER,
    }
    if "title" in allowed:
        snippet["title"] = _redact(concept.title)
    if "description" in allowed:
        snippet["description"] = _redact(concept.description)
    if "authority" in allowed:
        # cannot-prove / authority ceiling are preserved verbatim, never upgraded.
        snippet["authority"] = {
            "level": concept.authority.level,
            "may_authorize": bool(concept.authority.may_authorize),
            "ceiling": concept.authority.ceiling,
        }
    if "freshness" in allowed:
        snippet["freshness"] = concept.freshness.state
    if "posture" in allowed:
        snippet["privacy_class"] = concept.posture.privacy_class
        snippet["egress_state"] = concept.posture.egress_state
    if "source_refs" in allowed:
        snippet["source"] = src
    return snippet


def _render_text(snippets: list[dict[str, Any]]) -> str:
    lines = [f"[{NON_AUTHORITY_BANNER}]", ""]
    for s in snippets:
        lines.append(f"- {s.get('title', s['concept_uid'])}")
        if s.get("description"):
            lines.append(f"  {s['description']}")
        auth = s.get("authority")
        if auth:
            lines.append(
                f"  authority: {auth['level']} (may_authorize: {auth['may_authorize']}), "
                f"ceiling: {auth['ceiling']}"
            )
        if "freshness" in s:
            lines.append(f"  freshness: {s['freshness']}")
        if s.get("source"):
            lines.append(f"  source: {s['source']['uri']} ({s['source']['freshness_state']})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _read_concepts(bundle: Path) -> list[HkpConceptFrontmatter]:
    concepts_dir = bundle / "concepts"
    concepts: list[HkpConceptFrontmatter] = []
    for path in sorted(concepts_dir.glob("*.md")):
        if path.is_symlink():
            raise PromptContextError(f"refusing symlinked concept: {path}")
        parsed = parse_frontmatter_with_diagnostics(path)
        if not parsed.ok or parsed.frontmatter is None:
            raise PromptContextError(
                f"cannot parse concept frontmatter: {path}; next-action: validate the bundle"
            )
        concepts.append(HkpConceptFrontmatter.model_validate(parsed.frontmatter))
    return concepts


def build_prompt_context(bundle: Path) -> PromptContextResult:
    """Assemble support-only prompt context from one HKP cache bundle."""
    import yaml  # local import; pyyaml is a council dependency

    policy_path = bundle / "_hkp" / "consumer_policy.yaml"
    policy: dict[str, Any] | None = None
    if policy_path.is_file() and not policy_path.is_symlink():
        policy = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    allowed = _effective_allowed_fields(policy)
    if not allowed:
        raise PromptContextError(
            f"bundle denies {CONSUMER_NAME}; next-action: no prompt context emitted"
        )

    snippets = [_snippet_for_concept(c, allowed) for c in _read_concepts(bundle)]
    text = _assert_clean(_render_text(snippets))
    # Defence in depth: no forbidden field key may appear anywhere in the output.
    serialized = json.dumps(snippets)
    for forbidden in FORBIDDEN_FIELDS:
        if f'"{forbidden}"' in serialized:
            raise PromptContextError(f"forbidden field '{forbidden}' present in context")
    return PromptContextResult(text=text, snippets=snippets, concept_count=len(snippets))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assemble local support-only HKP prompt context from a cache bundle."
    )
    parser.add_argument("bundle", help="path to an HKP shadow bundle directory")
    parser.add_argument("--json", action="store_true", help="emit JSON snippets")
    args = parser.parse_args(argv)
    try:
        result = build_prompt_context(Path(args.bundle))
    except PromptContextError as exc:
        print(f"hapax-hkp-prompt-context: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(
            json.dumps(
                {"concept_count": result.concept_count, "snippets": result.snippets},
                indent=2,
            )
        )
    else:
        print(result.text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
