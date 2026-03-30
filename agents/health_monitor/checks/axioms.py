"""Axiom infrastructure checks (registry, hooks, settings, EF compliance).

Split into axiom_registry and axiom_ef for the constitutional vs EF checks.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from .. import constants as _c
from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


@check_group("axioms")
async def check_axiom_registry() -> list[CheckResult]:
    """Check axiom enforcement infrastructure is operational."""
    results = []
    t = time.monotonic()

    try:
        from agents._axiom_registry import AXIOMS_PATH, load_axioms

        registry_file = AXIOMS_PATH / "registry.yaml"
        if registry_file.exists():
            axioms = load_axioms()
            if axioms:
                results.append(
                    CheckResult(
                        name="axiom.registry",
                        group="axioms",
                        status=Status.HEALTHY,
                        message=f"Registry loaded: {len(axioms)} active axiom(s)",
                        duration_ms=_u._timed(t),
                    )
                )
            else:
                results.append(
                    CheckResult(
                        name="axiom.registry",
                        group="axioms",
                        status=Status.DEGRADED,
                        message="Registry exists but no active axioms found",
                        duration_ms=_u._timed(t),
                    )
                )
        else:
            results.append(
                CheckResult(
                    name="axiom.registry",
                    group="axioms",
                    status=Status.DEGRADED,
                    message="Axiom registry not found",
                    detail=str(registry_file),
                    duration_ms=_u._timed(t),
                )
            )
    except Exception as e:
        results.append(
            CheckResult(
                name="axiom.registry",
                group="axioms",
                status=Status.FAILED,
                message="Cannot check axiom registry",
                detail=str(e),
                duration_ms=_u._timed(t),
            )
        )

    # Check precedent collection exists in Qdrant
    t2 = time.monotonic()
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(_c.QDRANT_URL)
        collections = [c.name for c in client.get_collections().collections]
        if "axiom-precedents" in collections:
            info = client.get_collection("axiom-precedents")
            count = info.points_count
            results.append(
                CheckResult(
                    name="axiom.precedents",
                    group="axioms",
                    status=Status.HEALTHY,
                    message=f"Precedent collection: {count} point(s)",
                    duration_ms=_u._timed(t2),
                )
            )
        else:
            results.append(
                CheckResult(
                    name="axiom.precedents",
                    group="axioms",
                    status=Status.DEGRADED,
                    message="axiom-precedents collection not found in Qdrant",
                    remediation="cd ~/projects/hapax-council && uv run python -c 'from agents._axiom_precedents import PrecedentStore; PrecedentStore().ensure_collection()'",
                    duration_ms=_u._timed(t2),
                )
            )
    except Exception as e:
        results.append(
            CheckResult(
                name="axiom.precedents",
                group="axioms",
                status=Status.FAILED,
                message="Cannot check precedent collection",
                detail=str(e),
                duration_ms=_u._timed(t2),
            )
        )

    # Check implications exist for active axioms
    t3 = time.monotonic()
    try:
        from agents._axiom_registry import load_axioms as _load_axioms
        from agents._axiom_registry import load_implications

        active = _load_axioms()
        if active:
            missing = [a.id for a in active if not load_implications(a.id)]
            if not missing:
                results.append(
                    CheckResult(
                        name="axiom.implications",
                        group="axioms",
                        status=Status.HEALTHY,
                        message="All active axioms have implication files",
                        duration_ms=_u._timed(t3),
                    )
                )
            else:
                results.append(
                    CheckResult(
                        name="axiom.implications",
                        group="axioms",
                        status=Status.DEGRADED,
                        message=f"Missing implications for: {', '.join(missing)}",
                        remediation=f"cd ~/projects/hapax-council && uv run python -m shared.axiom_derivation --axiom {missing[0]}",
                        duration_ms=_u._timed(t3),
                    )
                )
    except Exception as e:
        results.append(
            CheckResult(
                name="axiom.implications",
                group="axioms",
                status=Status.FAILED,
                message="Cannot check axiom implications",
                detail=str(e),
                duration_ms=_u._timed(t3),
            )
        )

    # Check supremacy
    t4 = time.monotonic()
    try:
        from agents._axiom_registry import validate_supremacy

        tensions = validate_supremacy()
        if not tensions:
            results.append(
                CheckResult(
                    name="axiom.supremacy",
                    group="axioms",
                    status=Status.HEALTHY,
                    message="No domain T0 tensions (or no domain axioms)",
                    duration_ms=_u._timed(t4),
                )
            )
        else:
            ids = ", ".join(t.domain_impl_id for t in tensions)
            results.append(
                CheckResult(
                    name="axiom.supremacy",
                    group="axioms",
                    status=Status.DEGRADED,
                    message=f"{len(tensions)} domain T0 block(s) need operator review: {ids}",
                    remediation="Run: /axiom-review to create precedents acknowledging these",
                    duration_ms=_u._timed(t4),
                )
            )
    except Exception as e:
        results.append(
            CheckResult(
                name="axiom.supremacy",
                group="axioms",
                status=Status.FAILED,
                message="Cannot check axiom supremacy",
                detail=str(e),
                duration_ms=_u._timed(t4),
            )
        )

    return results


@check_group("axioms")
async def check_axiom_hooks_active() -> list[CheckResult]:
    """Check that axiom enforcement hooks are firing."""
    results = []
    t = time.monotonic()

    audit_dir = _c.AXIOM_AUDIT_DIR
    if not audit_dir.exists():
        results.append(
            CheckResult(
                name="axiom.hooks_active",
                group="axioms",
                status=Status.DEGRADED,
                message="Audit directory missing \u2014 hooks may never have fired",
                remediation="Check axiom hooks in ~/.claude/settings.json (PreToolUse/PostToolUse)",
                duration_ms=_u._timed(t),
            )
        )
        return results

    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)
    today_file = audit_dir / f"{today.isoformat()}.jsonl"
    yesterday_file = audit_dir / f"{yesterday.isoformat()}.jsonl"

    if today_file.exists():
        lines = sum(1 for _ in today_file.open())
        results.append(
            CheckResult(
                name="axiom.hooks_active",
                group="axioms",
                status=Status.HEALTHY,
                message=f"Audit trail active: {lines} entries today",
                duration_ms=_u._timed(t),
            )
        )
    elif yesterday_file.exists():
        results.append(
            CheckResult(
                name="axiom.hooks_active",
                group="axioms",
                status=Status.HEALTHY,
                message="Audit trail active (last entry yesterday)",
                duration_ms=_u._timed(t),
            )
        )
    else:
        any_files = list(audit_dir.glob("*.jsonl"))
        if any_files:
            newest = max(any_files, key=lambda p: p.stat().st_mtime)
            results.append(
                CheckResult(
                    name="axiom.hooks_active",
                    group="axioms",
                    status=Status.DEGRADED,
                    message=f"Audit trail stale \u2014 newest: {newest.name}",
                    remediation="Verify hooks in ~/.claude/settings.json are configured",
                    duration_ms=_u._timed(t),
                )
            )
        else:
            results.append(
                CheckResult(
                    name="axiom.hooks_active",
                    group="axioms",
                    status=Status.DEGRADED,
                    message="No audit trail entries found",
                    remediation="Check axiom hooks in ~/.claude/settings.json and restart Claude Code",
                    duration_ms=_u._timed(t),
                )
            )

    return results
