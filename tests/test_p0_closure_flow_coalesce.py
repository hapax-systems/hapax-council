"""Tests for P0 incident closure flow improvements.

Covers:
1. Dispatch refusal coalescing by time-window (not per-task)
2. Anti-recursion guard for dispatch refusals about P0 incident tasks
3. Batch-close stale blocked P0 incidents
"""

from __future__ import annotations

import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# ── Dispatch refusal coalescing tests ─────────────────────────────────────────


class TestDispatchRefusalCoalescing:
    """Dispatch refusals for different tasks within the same 6h window
    must produce the same fingerprint."""

    def test_same_window_same_fingerprint(self):
        from shared.p0_incident_intake import _fingerprint_for

        fp1 = _fingerprint_for(
            "sdlc_dispatch_refusal",
            "SDLC: dispatch refusal circuit breaker",
            "Task task-alpha-123 refused 3x on lane cx-crit.",
        )
        fp2 = _fingerprint_for(
            "sdlc_dispatch_refusal",
            "SDLC: dispatch refusal circuit breaker",
            "Task task-beta-456 refused 5x on lane cx-p0.",
        )
        assert fp1 == fp2, f"Different task refusals should coalesce: {fp1!r} vs {fp2!r}"

    def test_fingerprint_format(self):
        from shared.p0_incident_intake import _fingerprint_for

        fp = _fingerprint_for(
            "sdlc_dispatch_refusal",
            "SDLC: dispatch refusal circuit breaker",
            "Task some-task-id-here refused 3x on lane alpha.",
        )
        assert fp.startswith("sdlc_dispatch_refusal:batch-"), f"Unexpected format: {fp!r}"
        parts = fp.split("batch-")[1]
        assert parts.startswith("2"), f"Bucket should start with year: {parts!r}"
        assert "-q" in parts, f"Bucket should have quarter suffix: {parts!r}"

    def test_starvation_still_per_task(self):
        """sdlc_task_stalled should still use per-task fingerprinting."""
        from shared.p0_incident_intake import _fingerprint_for

        fp1 = _fingerprint_for(
            "sdlc_task_stalled",
            "SDLC: task stuck, blocked",
            "Task my-stuck-task-001 has been stalled for 2h.",
        )
        fp2 = _fingerprint_for(
            "sdlc_task_stalled",
            "SDLC: task stuck, blocked",
            "Task my-stuck-task-002 has been stalled for 3h.",
        )
        assert fp1 != fp2, "sdlc_task_stalled should still be per-task"

    def test_starvation_per_task(self):
        from shared.p0_incident_intake import _fingerprint_for

        fp = _fingerprint_for(
            "sdlc_dispatch_starvation",
            "SDLC: dispatch starvation detected",
            "offered=5 tasks, dispatched=0 for 60 minutes.",
        )
        assert fp.startswith("sdlc_dispatch_starvation:")
        assert "batch" not in fp


# ── Anti-recursion guard tests ────────────────────────────────────────────────


class TestDispatchRefusalAntiRecursion:
    """A dispatch refusal about a p0-incident task must not mint a new P0."""

    def test_refusal_about_p0_incident_is_nontechnical(self):
        from shared.p0_incident_intake import classify_notification

        result = classify_notification(
            "SDLC: dispatch refusal circuit breaker",
            (
                "Task p0-incident-systemd-service-failed-hapax-foo-abc12345 "
                "refused 3x on lane cx-crit.\n"
                "Reason: route policy refuse: runtime_actuation_receipt_absent"
            ),
            priority="urgent",
            tags=["skull"],
        )
        assert not result.technical, "Dispatch refusal about a P0 incident should be nontechnical"
        assert result.reason == "dispatch_refusal_incident_task_no_remint"

    def test_refusal_about_normal_task_is_still_technical(self):
        from shared.p0_incident_intake import classify_notification

        result = classify_notification(
            "SDLC: dispatch refusal circuit breaker",
            (
                "Task segprep-axis-b-ndcvb-scorer-b2-20260618 "
                "refused 3x on lane cx-crit.\n"
                "Reason: route policy refuse: capability mismatch"
            ),
            priority="urgent",
            tags=["skull"],
        )
        assert result.technical, "Dispatch refusal about a normal task should still be technical"
        assert result.reason == "matched"

    def test_stalled_p0_incident_still_blocked(self):
        """The existing sdlc_task_stalled guard should still work."""
        from shared.p0_incident_intake import classify_notification

        result = classify_notification(
            "SDLC: task stuck, blocked",
            "Task p0-incident-cc-hygiene-violation-orphan-pr-xyz has been stalled for 2h.",
            priority="urgent",
            tags=["skull"],
        )
        assert not result.technical
        assert result.reason == "stalled_incident_task_no_remint"


# ── Batch close stale P0 tests ───────────────────────────────────────────────


def _load_batch_close(vault: Path):
    """Load the batch-close script as a module with patched vault paths."""
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "cc-batch-close-stale-p0"
    source = script_path.read_text(encoding="utf-8")
    mod = types.ModuleType("batch_close_test")
    mod.__file__ = str(script_path)
    exec(compile(source, str(script_path), "exec"), mod.__dict__)  # noqa: S102
    mod.VAULT = vault
    mod.ACTIVE = vault / "active"
    mod.CLOSED = vault / "closed"
    return mod


def _write_task(
    vault: Path, name: str, status: str, updated_at: str, pr: str = "null", branch: str = "null"
) -> Path:
    path = vault / "active" / f"{name}.md"
    content = (
        f"---\n"
        f"type: cc-task\n"
        f"task_id: {name}\n"
        f'title: "P0 incident: test"\n'
        f"status: {status}\n"
        f"priority: p0\n"
        f"pr: {pr}\n"
        f"branch: {branch}\n"
        f"created_at: 2026-06-12T00:00:00Z\n"
        f"updated_at: {updated_at}\n"
        f"---\n\n"
        f"# P0 incident: test\n\n"
        f"## Post-mortem\n\n"
        f"- Root cause:\n"
        f"- Remediation or refusal:\n"
        f"- Verification evidence:\n"
        f"- Recurrence prevention:\n"
        f"- Follow-up tasks:\n\n"
        f"## Session Log\n\n"
    )
    path.write_text(content)
    return path


class TestBatchCloseStaleP0:
    """Tests for the cc-batch-close-stale-p0 script."""

    @pytest.fixture()
    def vault(self, tmp_path):
        (tmp_path / "active").mkdir()
        (tmp_path / "closed").mkdir()
        return tmp_path

    def test_stale_blocked_withdrawn(self, vault):
        old = datetime.now(UTC) - timedelta(days=10)
        _write_task(vault, "p0-incident-test-stale", "blocked", old.strftime("%Y-%m-%dT%H:%M:%SZ"))
        mod = _load_batch_close(vault)
        assert mod.main(["--stale-days", "7"]) == 0
        assert (vault / "closed" / "p0-incident-test-stale.md").exists()
        assert not (vault / "active" / "p0-incident-test-stale.md").exists()
        text = (vault / "closed" / "p0-incident-test-stale.md").read_text()
        assert "status: withdrawn" in text

    def test_recent_blocked_skipped(self, vault):
        recent = datetime.now(UTC) - timedelta(days=2)
        _write_task(
            vault, "p0-incident-test-recent", "blocked", recent.strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        mod = _load_batch_close(vault)
        assert mod.main(["--stale-days", "7"]) == 0
        assert (vault / "active" / "p0-incident-test-recent.md").exists()

    def test_offered_not_touched(self, vault):
        old = datetime.now(UTC) - timedelta(days=20)
        _write_task(
            vault, "p0-incident-test-offered", "offered", old.strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        mod = _load_batch_close(vault)
        assert mod.main(["--stale-days", "7"]) == 0
        assert (vault / "active" / "p0-incident-test-offered.md").exists()

    def test_blocked_with_pr_skipped(self, vault):
        old = datetime.now(UTC) - timedelta(days=10)
        _write_task(
            vault, "p0-incident-test-pr", "blocked", old.strftime("%Y-%m-%dT%H:%M:%SZ"), pr="4200"
        )
        mod = _load_batch_close(vault)
        assert mod.main(["--stale-days", "7"]) == 0
        assert (vault / "active" / "p0-incident-test-pr.md").exists()

    def test_dry_run(self, vault):
        old = datetime.now(UTC) - timedelta(days=10)
        _write_task(vault, "p0-incident-test-dry", "blocked", old.strftime("%Y-%m-%dT%H:%M:%SZ"))
        mod = _load_batch_close(vault)
        assert mod.main(["--stale-days", "7", "--dry-run"]) == 0
        assert (vault / "active" / "p0-incident-test-dry.md").exists()
        assert not (vault / "closed" / "p0-incident-test-dry.md").exists()
