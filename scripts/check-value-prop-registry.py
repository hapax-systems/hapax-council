#!/usr/bin/env python3
"""Structural checker (v2) for the value-proposition registry seed.

Validates docs/repo-pres/value-prop-registry.yaml against the structural
contract, modeled on the registry mode of scripts/check-public-surface-claims.py.
Fail-closed: any error finding exits 1; malformed/missing input exits 2.

v1 checks:
  C1 enum/ref integrity  — unique value_proposition_id, int rank, maturity enum,
                           audience_ids resolve against the audiences block,
                           non-empty claim_ceiling, stale_behavior enum.
  C2 placement rule      — every audience with weight >= 78 is referenced by at
                           least one row with non-empty target_surfaces; every
                           present row with rank <= 16 has non-empty target_surfaces.
  C3 maturity-trigger    — planned rows carry a non-empty freshness_source trigger
                           predicate; present rows carry non-empty technical_items
                           (the grounding-refs field this registry carries).
  C6 evidence_visibility — vault-evidenced rows must not target public-copy
                           surfaces (surface ids containing readme/profile/weblog).
  C8 org-link lint       — no row text field may contain github.com/ryanklee.

v2 checks (registry-text linting only; rendered-surface linting still awaits
D4 marker convergence):
  C4  embargo lint       — the constraints embargo-terms machine list (fallback:
                           the seeded banned-absolutes lexicon) is scanned over row
                           claim-copy text (tangible_benefit, claim_ceiling,
                           maturity_note, notes, competitive_position,
                           comparative_claims text). A hit errors unless the row
                           carries the term in embargo_exceptions with a reason
                           (mention-not-use quoting of the ban itself).
  C5  required_pairings  — the constraints required-pairings map (absolute phrase
                           -> required disclosure substring): a row whose claim
                           copy uses the phrase must carry the paired disclosure
                           somewhere in the same row's text. Matching folds
                           hyphens/commas so 'no-false-green' still triggers.
  C7  comparative pins   — every comparative_claims entry carries a non-empty
                           evidence_level and an ISO scout_date; a pinned
                           comparator version/identifier (comparator /
                           comparator_pin / comparator_versions) is required
                           unless status=docs_internal (the registry's own
                           comparative-claim-hygiene escape); scout_date older
                           than the TTL (constraints comparative_claim_ttl_days,
                           default 45 days) errors unless docs_internal.
  C9  pinned counts      — standalone numerics (2+ digits; years, ISO dates,
                           dotted versions, and #NNNN refs excluded) inside
                           tangible_benefit / claim_ceiling require a
                           pinned_counts[<digits>] witness ref on the row.
  C10 PII screen         — rows referencing axioms/registry.yaml, 'frozen axiom',
                           or paths under 30-areas/ / Documents/Personal must
                           carry pii_screen_receipt (the adjacent
                           executive_function axiom text contains operator
                           medical details — constraint pii-screen).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VALUE_PROP_REGISTRY = REPO_ROOT / "docs/repo-pres/value-prop-registry.yaml"
VALUE_PROP_REGISTRY_RULE = "Hapax.ValuePropRegistry"
ALLOWED_MATURITIES = {"present", "planned"}
ALLOWED_STALE_BEHAVIORS = {
    "block_public_current",
    "revert_to_planned",
    "hold_docs_internal",
    "block_placement",
}
PLACEMENT_AUDIENCE_WEIGHT_FLOOR = 78
PLACEMENT_PRESENT_RANK_CEILING = 16
PUBLIC_COPY_SURFACE_MARKERS = ("readme", "profile", "weblog")
FORBIDDEN_ORG_LINK = "github.com/ryanklee"

# C4 fallback when the registry carries no machine list (constraints entry
# id=embargo-terms with a list-shaped terms, or a constraints.embargo_terms
# list). Seeded from banned-absolutes + the embargo lexicon.
DEFAULT_EMBARGO_TERMS = (
    "cannot lie",
    "structurally impossible",
    "structurally cannot",
    "proves what happens",
    "impossible to leak",
    "measured capability",
)
# Row claim-copy fields scanned by C4/C5 (comparative_claims text is added by
# _row_copy_strings). required_pairings prose and technical_items are row text
# (searched for C5 disclosures) but not claim copy (never trigger C4/C5).
ROW_COPY_TEXT_FIELDS = (
    "tangible_benefit",
    "claim_ceiling",
    "maturity_note",
    "notes",
    "competitive_position",
)
# C7: accepted field names for the pinned comparator version/identifier.
COMPARATOR_PIN_KEYS = ("comparator", "comparator_pin", "comparator_versions")
DEFAULT_COMPARATIVE_CLAIM_TTL_DAYS = 45
# C9: fields whose standalone numerics require a pinned_counts witness.
PINNED_COUNT_TEXT_FIELDS = ("tangible_benefit", "claim_ceiling")
# C10 trigger substrings (matched case-insensitively over all row strings).
PII_SCREEN_TRIGGERS = (
    "axioms/registry.yaml",
    "frozen axiom",
    "30-areas/",
    "documents/personal",
)

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATE_TOKEN_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_VERSION_TOKEN_RE = re.compile(r"\b[vV]?\d+(?:\.\d+)+\b")
_NUMERIC_CLAIM_RE = re.compile(r"\b\d{2,}\b")
_YEAR_TOKEN_RE = re.compile(r"^(?:19|20)\d{2}$")


class RequiredInputError(ValueError):
    """Required registry input is missing or malformed."""


@dataclass(frozen=True)
class Finding:
    file: str
    check: str
    message: str
    level: str = "error"

    def render(self) -> str:
        return f"{self.file}: {self.level}: {VALUE_PROP_REGISTRY_RULE}.{self.check}: {self.message}"


def load_value_prop_registry(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RequiredInputError(f"value-prop registry not found: {path}") from exc
    except OSError as exc:
        raise RequiredInputError(f"value-prop registry is not readable: {path}: {exc}") from exc

    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RequiredInputError(f"value-prop registry is not valid YAML: {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise RequiredInputError(f"value-prop registry must be a YAML object: {path}")
    return payload


def _row_label(row: Mapping[str, Any], index: int) -> str:
    row_id = row.get("value_proposition_id")
    if isinstance(row_id, str) and row_id.strip():
        return row_id
    return f"registry[{index}]"


def _audience_ids(row: Mapping[str, Any]) -> list[str]:
    raw = row.get("audience_ids")
    if isinstance(raw, Mapping):
        return [str(key) for key in raw]
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return []


def _nonempty_string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _iter_row_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        strings: list[str] = []
        for key, item in value.items():
            if isinstance(key, str):
                strings.append(key)
            strings.extend(_iter_row_strings(item))
        return strings
    if isinstance(value, list):
        strings = []
        for item in value:
            strings.extend(_iter_row_strings(item))
        return strings
    return []


def _normalize_copy_text(text: str) -> str:
    """Lowercase, fold hyphens/commas to spaces, collapse whitespace.

    Lets 'no-false-green' and 'No quorum, no merge' match their declared
    constraint phrases without a full tokenizer.
    """
    folded = re.sub(r"[-,]", " ", text.lower())
    return re.sub(r"\s+", " ", folded).strip()


def _constraint_entries(registry: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = registry.get("constraints")
    if isinstance(raw, list):
        return [entry for entry in raw if isinstance(entry, Mapping)]
    return []


def _embargo_terms(registry: Mapping[str, Any]) -> tuple[str, ...]:
    """Machine embargo-term list: constraints.embargo_terms (mapping shape) or a
    constraints entry id in {embargo-terms, banned-absolutes} carrying a
    list-shaped terms. The embargo-lexicon entry's mapping-shaped terms are
    lexicon ids with reasons, not scan phrases — never used here. Falls back to
    the seeded default so the check stays live on registries without the list."""
    candidates: list[Any] = []
    constraints = registry.get("constraints")
    if isinstance(constraints, Mapping):
        candidates.append(constraints.get("embargo_terms"))
    for entry in _constraint_entries(registry):
        if entry.get("id") in {"embargo-terms", "banned-absolutes"}:
            candidates.append(entry.get("terms"))
    terms: list[str] = []
    for raw in candidates:
        if isinstance(raw, list):
            terms.extend(item for item in raw if isinstance(item, str) and item.strip())
    return tuple(terms) if terms else DEFAULT_EMBARGO_TERMS


def _required_pairings(registry: Mapping[str, Any]) -> dict[str, str]:
    """Phrase -> required-disclosure map: constraints.required_pairings (mapping
    shape) or a constraints entry id=required-pairings carrying pairings."""
    raw: Any = None
    constraints = registry.get("constraints")
    if isinstance(constraints, Mapping):
        raw = constraints.get("required_pairings")
    else:
        for entry in _constraint_entries(registry):
            if entry.get("id") in {"required-pairings", "required_pairings"}:
                raw = entry.get("pairings")
                break
    if not isinstance(raw, Mapping):
        return {}
    return {
        str(phrase): str(disclosure)
        for phrase, disclosure in raw.items()
        if isinstance(phrase, str) and isinstance(disclosure, str) and disclosure.strip()
    }


def _comparative_claim_ttl_days(registry: Mapping[str, Any]) -> int:
    raw: Any = None
    constraints = registry.get("constraints")
    if isinstance(constraints, Mapping):
        raw = constraints.get("comparative_claim_ttl_days")
    else:
        for entry in _constraint_entries(registry):
            if "comparative_claim_ttl_days" in entry:
                raw = entry["comparative_claim_ttl_days"]
                break
    if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
        return raw
    return DEFAULT_COMPARATIVE_CLAIM_TTL_DAYS


def _row_copy_strings(row: Mapping[str, Any]) -> list[tuple[str, str]]:
    """(field label, text) pairs for the row's claim-copy fields (C4/C5 scan set)."""
    out: list[tuple[str, str]] = []
    for field in ROW_COPY_TEXT_FIELDS:
        value = row.get(field)
        if isinstance(value, str):
            out.append((field, value))
    claims = row.get("comparative_claims")
    if isinstance(claims, list):
        for index, claim in enumerate(claims):
            if isinstance(claim, str):
                out.append((f"comparative_claims[{index}]", claim))
            elif isinstance(claim, Mapping):
                for key in ("claim", "note"):
                    value = claim.get(key)
                    if isinstance(value, str):
                        out.append((f"comparative_claims[{index}].{key}", value))
    return out


def _embargo_exception_terms(row: Mapping[str, Any]) -> set[str]:
    """Normalized terms the row excepts via embargo_exceptions WITH a reason.

    Accepts a list of {term, reason} mappings (the registry shape) or a
    {term: reason} mapping. A missing/empty reason grants no exception.
    """
    raw = row.get("embargo_exceptions")
    out: set[str] = set()
    if isinstance(raw, Mapping):
        for term, reason in raw.items():
            if isinstance(term, str) and isinstance(reason, str) and reason.strip():
                out.add(_normalize_copy_text(term))
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            term = item.get("term")
            reason = item.get("reason")
            if isinstance(term, str) and isinstance(reason, str) and reason.strip():
                out.add(_normalize_copy_text(term))
    return out


def check_c4_embargo_lint(
    rows: list[Mapping[str, Any]],
    registry: Mapping[str, Any],
    *,
    registry_path: Path,
) -> list[Finding]:
    findings: list[Finding] = []
    terms = _embargo_terms(registry)
    for index, row in enumerate(rows):
        label = _row_label(row, index)
        excepted = _embargo_exception_terms(row)
        for field, text in _row_copy_strings(row):
            normalized = _normalize_copy_text(text)
            for term in terms:
                normalized_term = _normalize_copy_text(term)
                if not normalized_term or normalized_term not in normalized:
                    continue
                if normalized_term in excepted:
                    continue
                findings.append(
                    Finding(
                        file=str(registry_path),
                        check="C4",
                        message=(
                            f"{label}.{field} contains embargoed term {term!r}. "
                            "Next action: reword to ceiling-honest phrasing, or carry "
                            "the term in the row's embargo_exceptions with a reason "
                            "(mention-not-use quoting of the ban itself)."
                        ),
                    )
                )
    return findings


def check_c5_required_pairings(
    rows: list[Mapping[str, Any]],
    registry: Mapping[str, Any],
    *,
    registry_path: Path,
) -> list[Finding]:
    findings: list[Finding] = []
    pairings = _required_pairings(registry)
    if not pairings:
        return findings
    for index, row in enumerate(rows):
        label = _row_label(row, index)
        copy_text = " | ".join(_normalize_copy_text(text) for _, text in _row_copy_strings(row))
        row_text = " | ".join(_normalize_copy_text(text) for text in _iter_row_strings(row))
        for phrase, disclosure in sorted(pairings.items()):
            if _normalize_copy_text(phrase) not in copy_text:
                continue
            if _normalize_copy_text(disclosure) in row_text:
                continue
            findings.append(
                Finding(
                    file=str(registry_path),
                    check="C5",
                    message=(
                        f"{label} uses absolute phrase {phrase!r} without its required "
                        f"pairing {disclosure!r} in the same row. Next action: add the "
                        "paired disclosure (e.g. a required_pairings entry) or drop the "
                        "absolute phrase from the row copy."
                    ),
                )
            )
    return findings


def _parse_scout_date(raw: Any) -> date | None:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str) and _ISO_DATE_RE.match(raw.strip()):
        try:
            return date.fromisoformat(raw.strip())
        except ValueError:
            return None
    return None


def check_c7_comparative_claim_pins(
    rows: list[Mapping[str, Any]],
    registry: Mapping[str, Any],
    *,
    registry_path: Path,
    today: date | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    ttl_days = _comparative_claim_ttl_days(registry)
    today = today or datetime.now(UTC).date()
    for index, row in enumerate(rows):
        label = _row_label(row, index)
        claims = row.get("comparative_claims")
        if not isinstance(claims, list):
            continue
        for claim_index, claim in enumerate(claims):
            claim_label = f"{label}.comparative_claims[{claim_index}]"
            if not isinstance(claim, Mapping):
                findings.append(
                    Finding(
                        file=str(registry_path),
                        check="C7",
                        message=(
                            f"{claim_label} must be a mapping carrying evidence_level, "
                            "scout_date, and a pinned comparator. Next action: restructure "
                            "the entry."
                        ),
                    )
                )
                continue
            docs_internal = claim.get("status") == "docs_internal"
            evidence_level = claim.get("evidence_level")
            if not isinstance(evidence_level, str) or not evidence_level.strip():
                findings.append(
                    Finding(
                        file=str(registry_path),
                        check="C7",
                        message=(
                            f"{claim_label} is missing evidence_level. Next action: tag the "
                            "claim's evidence level (SV/DC/RM/DS discipline)."
                        ),
                    )
                )
            scout = _parse_scout_date(claim.get("scout_date"))
            if scout is None:
                findings.append(
                    Finding(
                        file=str(registry_path),
                        check="C7",
                        message=(
                            f"{claim_label} is missing an ISO scout_date (YYYY-MM-DD). "
                            "Next action: record when the comparator field was scouted."
                        ),
                    )
                )
            has_pin = any(
                isinstance(claim.get(key), str) and str(claim.get(key)).strip()
                for key in COMPARATOR_PIN_KEYS
            )
            if not has_pin and not docs_internal:
                findings.append(
                    Finding(
                        file=str(registry_path),
                        check="C7",
                        message=(
                            f"{claim_label} carries no pinned comparator version/identifier "
                            f"({'/'.join(COMPARATOR_PIN_KEYS)}). Next action: pin the "
                            "comparator scouted, or mark the claim status: docs_internal "
                            "(constraint comparative-claim-hygiene)."
                        ),
                    )
                )
            if scout is not None and not docs_internal:
                age_days = (today - scout).days
                if age_days > ttl_days:
                    findings.append(
                        Finding(
                            file=str(registry_path),
                            check="C7",
                            message=(
                                f"{claim_label} scout_date {scout.isoformat()} is {age_days} "
                                f"days old (TTL {ttl_days}d). Next action: refresh the "
                                "comparator scout or mark the claim status: docs_internal."
                            ),
                        )
                    )
    return findings


def _standalone_numerics(text: str) -> list[str]:
    """Standalone 2+ digit tokens after excluding ISO dates, dotted versions,
    #NNNN issue/PR refs, 19xx/20xx years, and letter-hyphen identifier suffixes
    (Gate-13, sec-12 — digits that LEAD a compound, like 111-element, still
    count). Returned in order, de-duplicated."""
    scrubbed = _ISO_DATE_TOKEN_RE.sub(" ", text)
    scrubbed = _VERSION_TOKEN_RE.sub(" ", scrubbed)
    out: list[str] = []
    for match in _NUMERIC_CLAIM_RE.finditer(scrubbed):
        token = match.group(0)
        start = match.start()
        if _YEAR_TOKEN_RE.match(token):
            continue
        if start > 0 and scrubbed[start - 1] == "#":
            continue
        if start > 1 and scrubbed[start - 1] == "-" and scrubbed[start - 2].isalpha():
            continue
        if token not in out:
            out.append(token)
    return out


def check_c9_pinned_counts(rows: list[Mapping[str, Any]], *, registry_path: Path) -> list[Finding]:
    findings: list[Finding] = []
    for index, row in enumerate(rows):
        label = _row_label(row, index)
        raw_pins = row.get("pinned_counts")
        pins: dict[str, str] = {}
        if isinstance(raw_pins, Mapping):
            for numeric, witness in raw_pins.items():
                if isinstance(witness, str) and witness.strip():
                    pins[str(numeric)] = witness
        for field in PINNED_COUNT_TEXT_FIELDS:
            value = row.get(field)
            if not isinstance(value, str):
                continue
            for numeric in _standalone_numerics(value):
                if numeric in pins:
                    continue
                findings.append(
                    Finding(
                        file=str(registry_path),
                        check="C9",
                        message=(
                            f"{label}.{field} quotes numeric {numeric!r} without a "
                            f"pinned_counts witness. Next action: add pinned_counts"
                            f"[{numeric!r}] = <witness ref> backed by a real artifact or "
                            "test, or remove the numeric from the text."
                        ),
                    )
                )
    return findings


def check_c10_pii_screen(rows: list[Mapping[str, Any]], *, registry_path: Path) -> list[Finding]:
    findings: list[Finding] = []
    for index, row in enumerate(rows):
        receipt = row.get("pii_screen_receipt")
        if isinstance(receipt, str) and receipt.strip():
            continue
        hits: set[str] = set()
        for text in _iter_row_strings(row):
            lowered = text.lower()
            hits.update(trigger for trigger in PII_SCREEN_TRIGGERS if trigger in lowered)
        if not hits:
            continue
        label = _row_label(row, index)
        findings.append(
            Finding(
                file=str(registry_path),
                check="C10",
                message=(
                    f"{label} references {sorted(hits)} but carries no pii_screen_receipt. "
                    "Next action: run the PII screen and record pii_screen_receipt: <ref> "
                    "— the adjacent executive_function axiom text contains operator "
                    "medical details (constraint pii-screen)."
                ),
            )
        )
    return findings


def check_audiences_block(
    registry: Mapping[str, Any], *, registry_path: Path
) -> tuple[dict[str, int], list[Finding]]:
    findings: list[Finding] = []
    audiences = registry.get("audiences")
    if not isinstance(audiences, Mapping) or not audiences:
        findings.append(
            Finding(
                file=str(registry_path),
                check="C1",
                message=(
                    "top-level audiences block must be a non-empty mapping. "
                    "Next action: restore the audiences block (audience id -> {weight, ...})."
                ),
            )
        )
        return {}, findings

    weights: dict[str, int] = {}
    for audience_id, spec in audiences.items():
        weight = spec.get("weight") if isinstance(spec, Mapping) else None
        if not isinstance(weight, int) or isinstance(weight, bool):
            findings.append(
                Finding(
                    file=str(registry_path),
                    check="C1",
                    message=(
                        f"audiences.{audience_id}.weight must be an integer. "
                        "Next action: set an integer weight so C2 placement "
                        "coverage can be computed."
                    ),
                )
            )
            continue
        weights[str(audience_id)] = weight
    return weights, findings


def check_c1_enum_ref_integrity(
    rows: list[Mapping[str, Any]],
    audience_weights: Mapping[str, int],
    *,
    registry_path: Path,
) -> list[Finding]:
    findings: list[Finding] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(rows):
        label = _row_label(row, index)

        row_id = row.get("value_proposition_id")
        if not isinstance(row_id, str) or not row_id.strip():
            findings.append(
                Finding(
                    file=str(registry_path),
                    check="C1",
                    message=(
                        f"{label}.value_proposition_id is required and must be a non-empty "
                        "string. Next action: assign a unique id to the row."
                    ),
                )
            )
        elif row_id in seen_ids:
            findings.append(
                Finding(
                    file=str(registry_path),
                    check="C1",
                    message=(
                        f"duplicate value_proposition_id {row_id!r}. "
                        "Next action: merge or rename one of the duplicate rows."
                    ),
                )
            )
        else:
            seen_ids.add(row_id)

        rank = row.get("rank")
        if not isinstance(rank, int) or isinstance(rank, bool):
            findings.append(
                Finding(
                    file=str(registry_path),
                    check="C1",
                    message=(
                        f"{label}.rank must be an integer. Next action: set the row's integer rank."
                    ),
                )
            )

        maturity = row.get("implementation_maturity")
        if maturity not in ALLOWED_MATURITIES:
            findings.append(
                Finding(
                    file=str(registry_path),
                    check="C1",
                    message=(
                        f"{label}.implementation_maturity must be one of "
                        f"{sorted(ALLOWED_MATURITIES)}, got {maturity!r}. "
                        "Next action: set binary maturity; carry mixed states in "
                        "maturity_note."
                    ),
                )
            )

        row_audiences = _audience_ids(row)
        if not row_audiences:
            findings.append(
                Finding(
                    file=str(registry_path),
                    check="C1",
                    message=(
                        f"{label}.audience_ids must reference at least one audience. "
                        "Next action: join the row to the audiences block."
                    ),
                )
            )
        for audience_id in row_audiences:
            if audience_id not in audience_weights:
                findings.append(
                    Finding(
                        file=str(registry_path),
                        check="C1",
                        message=(
                            f"{label}.audience_ids references unknown audience "
                            f"{audience_id!r}. Next action: add the audience to the "
                            "top-level audiences block or fix the reference."
                        ),
                    )
                )

        claim_ceiling = row.get("claim_ceiling")
        if not isinstance(claim_ceiling, str) or not claim_ceiling.strip():
            findings.append(
                Finding(
                    file=str(registry_path),
                    check="C1",
                    message=(
                        f"{label}.claim_ceiling text is required and must be non-empty. "
                        "Next action: state the row's claim ceiling explicitly."
                    ),
                )
            )

        stale_behavior = row.get("stale_behavior")
        if stale_behavior is not None and stale_behavior not in ALLOWED_STALE_BEHAVIORS:
            findings.append(
                Finding(
                    file=str(registry_path),
                    check="C1",
                    message=(
                        f"{label}.stale_behavior must be one of "
                        f"{sorted(ALLOWED_STALE_BEHAVIORS)}, got {stale_behavior!r}. "
                        "Next action: pick a registered stale behavior or omit the field "
                        "to inherit the registry default."
                    ),
                )
            )
    return findings


def check_c2_placement_rule(
    rows: list[Mapping[str, Any]],
    audience_weights: Mapping[str, int],
    *,
    registry_path: Path,
) -> list[Finding]:
    findings: list[Finding] = []
    placed_audiences: set[str] = set()
    for row in rows:
        if _nonempty_string_list(row.get("target_surfaces")):
            placed_audiences.update(_audience_ids(row))

    for audience_id, weight in sorted(audience_weights.items()):
        if weight >= PLACEMENT_AUDIENCE_WEIGHT_FLOOR and audience_id not in placed_audiences:
            findings.append(
                Finding(
                    file=str(registry_path),
                    check="C2",
                    message=(
                        f"audience {audience_id!r} (weight {weight} >= "
                        f"{PLACEMENT_AUDIENCE_WEIGHT_FLOOR}) is not referenced by any row "
                        "with non-empty target_surfaces. Next action: give a row serving "
                        "this audience a target surface, or lower the audience weight with "
                        "a note."
                    ),
                )
            )

    for index, row in enumerate(rows):
        label = _row_label(row, index)
        rank = row.get("rank")
        if (
            row.get("implementation_maturity") == "present"
            and isinstance(rank, int)
            and not isinstance(rank, bool)
            and rank <= PLACEMENT_PRESENT_RANK_CEILING
            and not _nonempty_string_list(row.get("target_surfaces"))
        ):
            findings.append(
                Finding(
                    file=str(registry_path),
                    check="C2",
                    message=(
                        f"{label} is maturity=present at rank {rank} <= "
                        f"{PLACEMENT_PRESENT_RANK_CEILING} but has no target_surfaces. "
                        "Next action: place the row on at least one surface or demote its "
                        "rank."
                    ),
                )
            )
    return findings


def check_c3_maturity_trigger(
    rows: list[Mapping[str, Any]], *, registry_path: Path
) -> list[Finding]:
    findings: list[Finding] = []
    for index, row in enumerate(rows):
        label = _row_label(row, index)
        maturity = row.get("implementation_maturity")
        if maturity == "planned":
            freshness_source = row.get("freshness_source")
            if not isinstance(freshness_source, str) or not freshness_source.strip():
                findings.append(
                    Finding(
                        file=str(registry_path),
                        check="C3",
                        message=(
                            f"{label} is planned but has no freshness_source trigger "
                            "predicate. Next action: register the machine-checkable "
                            "planned->present trigger in freshness_source."
                        ),
                    )
                )
        elif maturity == "present" and not _nonempty_string_list(row.get("technical_items")):
            findings.append(
                Finding(
                    file=str(registry_path),
                    check="C3",
                    message=(
                        f"{label} is present but has no technical_items grounding refs. "
                        "Next action: list the shipped artifacts grounding the row or "
                        "flip it to planned."
                    ),
                )
            )
    return findings


def check_c6_evidence_visibility(
    rows: list[Mapping[str, Any]], *, registry_path: Path
) -> list[Finding]:
    findings: list[Finding] = []
    for index, row in enumerate(rows):
        if row.get("evidence_visibility") != "vault":
            continue
        label = _row_label(row, index)
        surfaces = row.get("target_surfaces")
        if not isinstance(surfaces, list):
            continue
        for surface in surfaces:
            if not isinstance(surface, str):
                continue
            lowered = surface.lower()
            if any(marker in lowered for marker in PUBLIC_COPY_SURFACE_MARKERS):
                findings.append(
                    Finding(
                        file=str(registry_path),
                        check="C6",
                        message=(
                            f"{label} has evidence_visibility=vault but targets public-copy "
                            f"surface {surface!r}. Next action: remove the placement (defer "
                            "it in maturity_note) until a public projection of the vault "
                            "evidence exists."
                        ),
                    )
                )
    return findings


def check_c8_org_link_lint(rows: list[Mapping[str, Any]], *, registry_path: Path) -> list[Finding]:
    findings: list[Finding] = []
    for index, row in enumerate(rows):
        label = _row_label(row, index)
        for text in _iter_row_strings(row):
            if FORBIDDEN_ORG_LINK in text:
                findings.append(
                    Finding(
                        file=str(registry_path),
                        check="C8",
                        message=(
                            f"{label} contains forbidden org link {FORBIDDEN_ORG_LINK!r} "
                            f"in {text!r}. Next action: replace with the hapax-systems org "
                            "path (ryanklee paths never seed copy)."
                        ),
                    )
                )
    return findings


def value_prop_registry_findings(
    registry: Mapping[str, Any], *, registry_path: Path
) -> list[Finding]:
    audience_weights, findings = check_audiences_block(registry, registry_path=registry_path)

    raw_rows = registry.get("registry")
    if not isinstance(raw_rows, list) or not raw_rows:
        findings.append(
            Finding(
                file=str(registry_path),
                check="C1",
                message=(
                    "value-prop registry must declare at least one row under registry:. "
                    "Next action: seed the registry rows."
                ),
            )
        )
        return findings

    rows: list[Mapping[str, Any]] = []
    for index, row in enumerate(raw_rows):
        if isinstance(row, Mapping):
            rows.append(row)
        else:
            findings.append(
                Finding(
                    file=str(registry_path),
                    check="C1",
                    message=(
                        f"registry[{index}] must be a mapping. "
                        "Next action: fix the row's YAML structure."
                    ),
                )
            )

    findings.extend(
        check_c1_enum_ref_integrity(rows, audience_weights, registry_path=registry_path)
    )
    findings.extend(check_c2_placement_rule(rows, audience_weights, registry_path=registry_path))
    findings.extend(check_c3_maturity_trigger(rows, registry_path=registry_path))
    findings.extend(check_c4_embargo_lint(rows, registry, registry_path=registry_path))
    findings.extend(check_c5_required_pairings(rows, registry, registry_path=registry_path))
    findings.extend(check_c6_evidence_visibility(rows, registry_path=registry_path))
    findings.extend(check_c7_comparative_claim_pins(rows, registry, registry_path=registry_path))
    findings.extend(check_c8_org_link_lint(rows, registry_path=registry_path))
    findings.extend(check_c9_pinned_counts(rows, registry_path=registry_path))
    findings.extend(check_c10_pii_screen(rows, registry_path=registry_path))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_VALUE_PROP_REGISTRY,
        help="value-prop registry to validate",
    )
    args = parser.parse_args(argv)

    try:
        registry = load_value_prop_registry(args.registry)
    except RequiredInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    findings = value_prop_registry_findings(registry, registry_path=args.registry)
    for finding in findings:
        print(finding.render())

    if findings:
        return 1
    print(f"value-prop registry OK: {args.registry}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
