#!/usr/bin/env python3
"""Assert that hapax-spine remains a strict, declared extraction of hapax-council/shared.

WHY. `reins` — the frontdoor, and the artifact an outside reviewer would actually run — consumes
`hapax-spine`. The estate itself consumes `hapax-council/shared`. Fifteen modules exist in both
under the same names, and nothing checks their relationship. Measured 2026-08-10:

    108 public symbols exist in council and not in spine
      0 public symbols exist in spine and not in council

That zero is the finding. Spine has NOT forked — a fork drifts both ways. It is a narrower
extraction that has fallen behind in five modules, and what it lacks is almost entirely this
estate's private specifics (`AGY_REVIEW_ROUTE_ID`, `CLAUDE_ACCOUNT_LIVE_QUOTA_BLOCKER`, the
`CANON_TRANSITION_*` family), which is the Ring-0 boundary holding rather than failing.

So the invariant is NOT equality — the modules must differ, by design. It is two things:

  1. `spine-only` stays EMPTY. A public symbol spine exports that council lacks is either dead
     code in the published package or an estate-private name that leaked outward. Both are
     defects, and today the count is zero, which is a clean line to hold.
  2. The council-only set is DECLARED. `NOT_EXTRACTED` below is the pinned gap. A new symbol
     appearing there without being listed means something was added to council and silently not
     extracted — which is exactly the difference between "deliberately kept private" and
     "extracted once and then forgotten", a distinction nothing currently makes.

Bodies are deliberately not compared. `coord_projection` is 8,888 lines in council against 527
in spine; requiring byte parity would be requiring the extraction not to be an extraction.

AST-only — nothing is imported from either tree, so this is safe to run anywhere.

Exit codes:
    0  the check RAN and passed
    1  finding (spine-only non-empty, or an undeclared council-only symbol)
    2  INDETERMINATE — the spine tree was not found, so nothing was checked.
       Deliberately not 0: an unevaluated check that reports success is the failure mode this
       estate keeps rediscovering.
"""

from __future__ import annotations

import argparse
import ast
import os
import sys
from pathlib import Path

OK = 0
FINDING = 1
INDETERMINATE = 2

DEFAULT_COUNCIL = Path(__file__).resolve().parents[1] / "shared"
DEFAULT_SPINE = (
    Path(os.environ.get("HAPAX_SPINE_ROOT", str(Path.home() / "projects/hapax-spine")))
    / "src/hapax/spine"
)

#: Public symbols present in council and deliberately NOT extracted into spine, as of
#: 2026-08-10. A literal, not a computation: a baseline that regenerates itself pins nothing.
#: Adding an entry here is a visible diff and an explicit decision that a symbol stays private.
NOT_EXTRACTED: dict[str, tuple[str, ...]] = {
    "coord_projection.py": (
        "CANON_TRANSITION_ABORTED",
        "CANON_TRANSITION_APPLIED",
        "CANON_TRANSITION_PREPARED",
        "CapturedFile",
        "FileObservation",
        "FileProjection",
        "FsSnapshotSeal",
        "FsStamp",
        "LIFECYCLE_DEFINITION_BINDING_SCHEMA",
        "LIFECYCLE_DEFINITION_COMPILER_REF",
        "LIFECYCLE_DERIVATION_MODE",
        "LIFECYCLE_INSPECTION_SCHEMA",
        "LifecycleDefinitionBinding",
        "LifecycleInspectionEnvelope",
        "LifecycleMaterializationPlan",
        "LifecyclePhaseAppendProjection",
        "LifecycleReceiptFrontierEntry",
        "LifecycleRecoveryResult",
        "LifecycleTransactionInspection",
        "LifecycleTransitionError",
        "LifecycleTransitionIntent",
        "LifecycleTransitionReceipt",
        "MATERIALIZATION_PLAN_SCHEMA",
        "PHASE_APPEND_PROJECTION_SCHEMA",
        "PinnedDirectory",
        "ReadOnlyFsSnapshot",
        "ReadOnlySnapshotError",
        "SUPPORTED_LIFECYCLE_DEFINITION_COMPILER_REFS",
        "TRANSITION_TRANSACTION_SCHEMA",
        "TRANSITION_TRANSACTION_SCHEMA_V1",
        "TRANSITION_TRANSACTION_SCHEMA_V2",
        "capture_coord_replay_snapshot",
        "execute_lifecycle_transition",
        "inspect_lifecycle_transactions",
        "lifecycle_transition_id",
        "lifecycle_transition_intent_ref",
        "recover_lifecycle_transactions",
    ),
    "dispatcher_policy.py": (
        "CAPABILITY_SURFACE_DELTA_PATH_ENV",
        "GLOBAL_SURFACE_DELTA_ROUTE_KEY",
    ),
    "platform_capability_registry.py": (
        "AGY_REVIEW_ROUTE_ID",
        "AGY_ROUTE_SPECIFIC_QUOTA_BLOCKER",
        "CLAUDE_ACCOUNT_LIVE_QUOTA_BLOCKER",
        "CLAUDE_HEADLESS_ROUTE_ID",
        "CLAUDE_REVIEW_ADMISSION_BLOCKER",
        "CLAUDE_REVIEW_ROUTE_ID",
        "CLAUDE_REVIEW_ROUTE_SPECIFIC_QUOTA_BLOCKER",
        "CapabilityShapeClass",
        "CapabilityShapeDescriptor",
        "CapabilityShapeFreshnessState",
        "CapabilityShapeState",
        "CapabilitySurfaceDeltaAction",
        "CapabilitySurfaceDisposition",
        "GLMCP_REVIEW_ADMISSION_BLOCKER",
        "GLMCP_REVIEW_ROUTE_ID",
        "OmittedShapeFreshnessCheck",
        "OmittedShapeFreshnessReport",
        "REPO_ROOT",
        "ROUTE_SPECIFIC_QUOTA_ADMISSION_BLOCKERS",
        "SCORES_INHERITED_ACROSS_MODEL_BOUNDARY",
        "check_omitted_shape_freshness",
        "disposition_for_capability_surface_delta",
        "is_registered_evidence_only_surface",
        "load_platform_capability_registry_for_dispatch",
        "normalize_capability_surface_identity",
    ),
    "quota_spend_ledger.py": (
        "AGY_ADMISSION_EVIDENCE_REF_RE",
        "AGY_ADMISSION_MODEL",
        "AGY_ADMISSION_RECEIPT_LABEL_RE",
        "AGY_ADMISSION_SECRETISH_RE",
        "AGY_ADMISSION_SUPPORTED_TOOL",
        "AGY_ADMISSION_WITNESS_REF_RE",
        "CLAUDE_ADMISSION_ACCOUNT_LIVE_QUOTA_SUFFIX",
        "CLAUDE_ADMISSION_BILLINGISH_RE",
        "CLAUDE_ADMISSION_COMPOSITE_REF_RE",
        "CLAUDE_ADMISSION_EVIDENCE_REF_RE",
        "CLAUDE_ADMISSION_IGNORED_REASON_RE",
        "CLAUDE_ADMISSION_IGNORED_UNSAFE_DETAIL_RE",
        "CLAUDE_ADMISSION_LANE_PRESENCE_RE",
        "CLAUDE_ADMISSION_OBSERVATIONS",
        "CLAUDE_ADMISSION_OBSERVATION_PATTERN",
        "CLAUDE_ADMISSION_RECEIPT_LABEL_RE",
        "CLAUDE_ADMISSION_SECRETISH_RE",
        "CLAUDE_ADMISSION_WITNESS_ALLOWLIST_RE",
        "CLAUDE_ADMISSION_WITNESS_PATTERN",
        "CLAUDE_ADMISSION_WITNESS_REF_RE",
        "CLAUDE_RECEIPT_BOUNDED_SUBSCRIPTION_ROUTES",
        "GLMCP_ADMISSION_CODING_PLAN_ENDPOINT",
        "GLMCP_ADMISSION_PAYG_ENDPOINT",
        "GLMCP_PAYG_BUDGET_PROFILE",
        "GLMCP_PAYG_BUDGET_PROVIDER",
        "GLMCP_PAYG_BUDGET_QUALITY_FLOOR",
        "GLMCP_PAYG_BUDGET_ROUTE_ID",
        "GLMCP_PAYG_BUDGET_TASK_CLASS",
        "GLMCP_PAYG_ESTIMATED_COST_USD",
        "GLMCP_PAYG_PRIMARY_ERROR_CLASSES",
        "GLMCP_PAYG_PRIMARY_ERROR_CLASS_REF_RE",
        "GLMCP_PAYG_QUOTA_WALL_REF_RE",
        "REPO_ROOT",
        "has_successful_task_scoped_glmcp_payg_review_spend",
        "successful_task_scoped_glmcp_payg_review_spend_receipts",
    ),
    "sdlc_router.py": (
        "DEFAULT_JUDGE_HEALTH_THRESHOLDS",
        "DEFAULT_JUDGE_SHADOW_LOG",
        "JudgeHealthMeasure",
        "JudgeHealthThresholds",
        "JudgePromotionDecision",
        "authoritative_flip_allowed",
        "judge_promotion_gate",
        "load_judge_shadow_pairs",
        "measure_judge_health",
    ),
}


def public_symbols(path: Path) -> set[str]:
    """Module-level public names: functions, classes, and UPPER_CASE constants."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return set()
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            if not node.name.startswith("_"):
                names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    if not target.id.startswith("_"):
                        names.add(target.id)
    return names


def check(council: Path, spine: Path) -> tuple[int, list[str]]:
    lines: list[str] = []
    shared = sorted({p.name for p in council.glob("*.py")} & {p.name for p in spine.glob("*.py")})
    if not shared:
        return INDETERMINATE, ["no modules exist in both trees; nothing was compared"]

    leaked: dict[str, list[str]] = {}
    undeclared: dict[str, list[str]] = {}
    for module in shared:
        c = public_symbols(council / module)
        s = public_symbols(spine / module)
        if extra := sorted(s - c):
            leaked[module] = extra
        if new := sorted((c - s) - set(NOT_EXTRACTED.get(module, ()))):
            undeclared[module] = new

    lines.append(f"check-spine-extraction-parity: {len(shared)} shared module(s)")

    if leaked:
        lines.append("  SPINE-ONLY SYMBOLS — spine exports names council does not have:")
        for module, names in leaked.items():
            lines.append(f"    {module}: {', '.join(names)}")
        lines.append(
            "    Each is either dead code in the published package or an estate-private name "
            "that leaked outward. Next: remove it from spine, or add it to council if the "
            "extraction is now leading."
        )

    if undeclared:
        lines.append("  UNDECLARED GAP — council gained public symbols spine lacks:")
        for module, names in undeclared.items():
            lines.append(f"    {module}: {', '.join(names)}")
        lines.append(
            "    Next: extract them into hapax-spine, or add them to NOT_EXTRACTED in this file "
            "to record that they stay private. Silence is the third option and it is the wrong one."
        )

    if leaked or undeclared:
        return FINDING, lines

    declared = sum(len(v) for v in NOT_EXTRACTED.values())
    lines.append(f"  spine-only: 0 | council-only: {declared}, all declared")
    return OK, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--council", type=Path, default=DEFAULT_COUNCIL)
    parser.add_argument("--spine", type=Path, default=DEFAULT_SPINE)
    args = parser.parse_args(argv)

    if not args.council.is_dir():
        print(
            f"check-spine-extraction-parity: INDETERMINATE — council shared/ not found at "
            f"{args.council}. Nothing was checked.",
            file=sys.stderr,
        )
        return INDETERMINATE
    if not args.spine.is_dir():
        print(
            f"check-spine-extraction-parity: INDETERMINATE — hapax-spine not found at "
            f"{args.spine}. Nothing was checked; this is NOT a pass. Next: clone hapax-spine, "
            f"or set HAPAX_SPINE_ROOT.",
            file=sys.stderr,
        )
        return INDETERMINATE

    code, lines = check(args.council, args.spine)
    stream = sys.stderr if code else sys.stdout
    for line in lines:
        print(line, file=stream)
    return code


if __name__ == "__main__":
    sys.exit(main())
