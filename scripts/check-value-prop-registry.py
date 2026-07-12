#!/usr/bin/env python3
"""Structural checker (v1) for the value-proposition registry seed.

Validates docs/repo-pres/value-prop-registry.yaml against the v1 structural
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

Registered v2 follow-ups (from the design, not implemented here):
  C4  embargo lint (embargo-lexicon terms scanned on rendered copy),
  C5  required_pairings enforcement on placements,
  C7  comparative-claim pins (evidence_level + scout_date + comparator versions),
  C9  pinned counts (quoted numerics require a pinning test/receipt),
  C10 PII screen (registry-text quoting requires a PII-screen receipt).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from dataclasses import dataclass
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
    findings.extend(check_c6_evidence_visibility(rows, registry_path=registry_path))
    findings.extend(check_c8_org_link_lint(rows, registry_path=registry_path))
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
