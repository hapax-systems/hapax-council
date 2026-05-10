"""Tests for scheduler readiness unblock reconciliation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from shared.content_programme_scheduler_policy import load_policy
from shared.scheduler_readiness_reconciler import (
    GROUNDING_RUNNER_TASK_ID,
    PRIVATE_DRY_RUN_TASK_ID,
    PROGRAMME_RUN_FIXTURE_PACK_TASK_ID,
    PROGRAMME_WCS_RUNNER_READINESS_TESTS_TASK_ID,
    PROGRAMME_WCS_SNAPSHOT_TASK_ID,
    SCHEDULER_RECONCILE_TASK_ID,
    build_scheduler_readiness_reconcile,
    inspect_public_mode_gates,
    load_cc_task_records,
    render_handoff_markdown,
)


def _write_task(
    root: Path,
    collection: str,
    task_id: str,
    *,
    status: str,
    depends_on: tuple[str, ...] = (),
    blocked_reason: str | None = None,
    pr: int | None = None,
) -> None:
    directory = root / collection
    directory.mkdir(parents=True, exist_ok=True)
    frontmatter: dict[str, Any] = {
        "type": "cc-task",
        "task_id": task_id,
        "title": task_id.replace("-", " ").title(),
        "status": status,
        "blocked_reason": blocked_reason,
        "depends_on": list(depends_on),
        "blocks": [],
        "pr": pr,
    }
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n\n# Task\n"
    (directory / f"{task_id}.md").write_text(text, encoding="utf-8")


def _closed(root: Path, task_id: str, *, pr: int | None = None) -> None:
    _write_task(root, "closed", task_id, status="done", pr=pr)


def _fixture_vault(root: Path) -> None:
    for task_id, pr in {
        "content-programme-scheduler-policy": 3024,
        "content-programme-feedback-ledger": 1812,
        "content-programme-run-store-event-surface": 1802,
        "content-programme-run-envelope-schema-fixtures": 1837,
        "format-to-public-event-adapter": 1810,
        "format-wcs-requirement-matrix": 1875,
        "opportunity-to-run-wcs-gate": 2193,
        "programme-outcome-to-feedback-live-wire": 1849,
        "wcs-witness-probe-runtime": 1828,
        "runner-public-mode-refusal-harness": 3027,
        "rights-safe-media-reference-gate": 2162,
        "monetization-readiness-ledger": 1932,
        "programme-to-scrim-profile-policy": 1836,
        "scrim-wcs-claim-posture-gate": 1848,
        "director-scrim-gesture-adapter": 1860,
        "scrim-translucency-and-no-visualizer-health-fixtures": 1857,
        "director-read-model-programme-format-actions": 2199,
        "autonomous-content-programming-format-registry": 1787,
        "tier-ranking-bracket-engine": 1807,
        "programme-boundary-wcs-evidence-adapter": 1881,
        "content-programme-outcome-nesting": 1886,
        "world-surface-no-false-grounding-fixtures": 2273,
    }.items():
        _closed(root, task_id, pr=pr)

    _write_task(
        root,
        "active",
        SCHEDULER_RECONCILE_TASK_ID,
        status="claimed",
        depends_on=(
            "content-programme-scheduler-policy",
            "content-programme-feedback-ledger",
            "content-programme-run-store-event-surface",
            "format-to-public-event-adapter",
        ),
        blocked_reason="waits for content-programme-scheduler-policy",
    )
    _write_task(
        root,
        "active",
        PRIVATE_DRY_RUN_TASK_ID,
        status="blocked",
        depends_on=(
            SCHEDULER_RECONCILE_TASK_ID,
            "opportunity-to-run-wcs-gate",
            "content-programme-run-envelope-schema-fixtures",
            "format-wcs-requirement-matrix",
            PROGRAMME_WCS_SNAPSHOT_TASK_ID,
            "programme-outcome-to-feedback-live-wire",
            PROGRAMME_RUN_FIXTURE_PACK_TASK_ID,
            "runner-public-mode-refusal-harness",
            "wcs-witness-probe-runtime",
        ),
        blocked_reason=(
            "waits for scheduler-readiness-unblock-reconcile, opportunity-to-run-wcs-gate, "
            "format-wcs-requirement-matrix, programme-wcs-snapshot-smoke, "
            "programme-run-fixture-pack-live-smoke, and runner-public-mode-refusal-harness"
        ),
    )
    _write_task(
        root,
        "active",
        GROUNDING_RUNNER_TASK_ID,
        status="offered",
        depends_on=(
            "content-programme-scheduler-policy",
            "rights-safe-media-reference-gate",
            "monetization-readiness-ledger",
            "programme-to-scrim-profile-policy",
            "scrim-wcs-claim-posture-gate",
            "director-scrim-gesture-adapter",
            "scrim-translucency-and-no-visualizer-health-fixtures",
            "runner-public-mode-refusal-harness",
        ),
        blocked_reason=(
            "waits for scheduler policy, rights-safe media gate, monetization readiness, "
            "scrim WCS/profile/gesture/health packets, and dry-run/public-mode refusal harnesses"
        ),
    )
    _write_task(
        root,
        "active",
        PROGRAMME_WCS_SNAPSHOT_TASK_ID,
        status="blocked",
        depends_on=(
            "wcs-director-snapshot-api",
            "wcs-health-degraded-blocker-bus",
            "content-programme-run-store-event-surface",
            "content-programme-run-envelope-schema-fixtures",
            "director-read-model-programme-format-actions",
        ),
        blocked_reason="waits for WCS director snapshot API, health blocker bus, and programme run envelope",
    )
    _write_task(root, "active", "wcs-director-snapshot-api", status="blocked")
    _write_task(root, "active", "wcs-health-degraded-blocker-bus", status="blocked")
    _write_task(
        root,
        "active",
        PROGRAMME_RUN_FIXTURE_PACK_TASK_ID,
        status="blocked",
        depends_on=(
            PROGRAMME_WCS_SNAPSHOT_TASK_ID,
            "content-programme-run-store-event-surface",
            "autonomous-content-programming-format-registry",
            "tier-ranking-bracket-engine",
        ),
        blocked_reason="waits for programme WCS snapshot smoke",
    )
    _write_task(
        root,
        "active",
        PROGRAMME_WCS_RUNNER_READINESS_TESTS_TASK_ID,
        status="blocked",
        depends_on=(
            "content-programme-run-envelope-schema-fixtures",
            "format-wcs-requirement-matrix",
            "opportunity-to-run-wcs-gate",
            "programme-boundary-wcs-evidence-adapter",
            "content-programme-outcome-nesting",
            "world-surface-no-false-grounding-fixtures",
        ),
        blocked_reason=(
            "Waiting on run envelope, format matrix, opportunity gate, boundary evidence, "
            "nested outcomes, and no-false-grounding fixtures."
        ),
    )


def test_reconciler_identifies_ready_stale_and_remaining_private_dry_run_deps(
    tmp_path: Path,
) -> None:
    _fixture_vault(tmp_path)

    report = build_scheduler_readiness_reconcile(
        load_cc_task_records(tmp_path),
        assume_done_task_ids=(SCHEDULER_RECONCILE_TASK_ID,),
    )

    private = next(target for target in report.targets if target.task_id == PRIVATE_DRY_RUN_TASK_ID)
    runner = next(target for target in report.targets if target.task_id == GROUNDING_RUNNER_TASK_ID)
    snapshot = next(
        target for target in report.targets if target.task_id == PROGRAMME_WCS_SNAPSHOT_TASK_ID
    )
    runner_readiness = next(
        target
        for target in report.targets
        if target.task_id == PROGRAMME_WCS_RUNNER_READINESS_TESTS_TASK_ID
    )

    assert private.open_dependencies == (
        PROGRAMME_WCS_SNAPSHOT_TASK_ID,
        PROGRAMME_RUN_FIXTURE_PACK_TASK_ID,
    )
    assert report.minimum_remaining_private_dry_run_dependencies == private.open_dependencies
    assert SCHEDULER_RECONCILE_TASK_ID in private.stale_dependency_blockers
    assert runner.readiness == "stale_note"
    assert "content-programme-scheduler-policy" in runner.stale_dependency_blockers
    assert runner.recommended_blocked_reason is None
    assert snapshot.open_dependencies == (
        "wcs-director-snapshot-api",
        "wcs-health-degraded-blocker-bus",
    )
    assert "content-programme-run-envelope-schema-fixtures" in snapshot.stale_dependency_blockers
    assert runner_readiness.readiness == "stale_note"
    assert runner_readiness.open_dependencies == ()


def test_public_mode_gate_summary_preserves_live_archive_and_monetized_boundaries() -> None:
    summary = inspect_public_mode_gates(load_policy())

    assert summary.preserved is True
    assert summary.missing_hard_gates == ()
    assert summary.public_live_route_present is True
    assert summary.public_archive_route_present is True
    assert summary.monetized_route_present is True
    assert summary.manual_calendar_allowed is False
    assert summary.request_queue_allowed is False
    assert summary.supporter_controlled_show_allowed is False
    assert summary.community_moderation_allowed is False


def test_closed_evidence_clause_is_not_counted_as_stale_blocker(tmp_path: Path) -> None:
    _fixture_vault(tmp_path)
    _write_task(
        tmp_path,
        "active",
        PRIVATE_DRY_RUN_TASK_ID,
        status="blocked",
        depends_on=(
            SCHEDULER_RECONCILE_TASK_ID,
            "opportunity-to-run-wcs-gate",
            "content-programme-run-envelope-schema-fixtures",
            "format-wcs-requirement-matrix",
            PROGRAMME_WCS_SNAPSHOT_TASK_ID,
            "programme-outcome-to-feedback-live-wire",
            PROGRAMME_RUN_FIXTURE_PACK_TASK_ID,
            "runner-public-mode-refusal-harness",
            "wcs-witness-probe-runtime",
        ),
        blocked_reason=(
            "waits for programme-wcs-snapshot-smoke and programme-run-fixture-pack-live-smoke; "
            "scheduler policy, opportunity gate, run envelope, format WCS matrix, outcome "
            "feedback, WCS witness runtime, and public-mode refusal harness are closed"
        ),
    )

    report = build_scheduler_readiness_reconcile(
        load_cc_task_records(tmp_path),
        assume_done_task_ids=(SCHEDULER_RECONCILE_TASK_ID,),
    )

    private = next(target for target in report.targets if target.task_id == PRIVATE_DRY_RUN_TASK_ID)
    assert private.open_dependencies == (
        PROGRAMME_WCS_SNAPSHOT_TASK_ID,
        PROGRAMME_RUN_FIXTURE_PACK_TASK_ID,
    )
    assert private.stale_dependency_blockers == ()


def test_handoff_note_names_ready_blocked_stale_and_operator_boundary(
    tmp_path: Path,
) -> None:
    _fixture_vault(tmp_path)
    report = build_scheduler_readiness_reconcile(
        load_cc_task_records(tmp_path),
        assume_done_task_ids=(SCHEDULER_RECONCILE_TASK_ID,),
    )

    note = render_handoff_markdown(report)

    assert "## Ready" in note
    assert "## Blocked" in note
    assert "## Stale Blockers" in note
    assert "programme-wcs-snapshot-smoke" in note
    assert "programme-run-fixture-pack-live-smoke" in note
    assert "No manual calendar, request queue" in note
    assert "Public-live and monetized routes remain gated" in note
