"""Tests for ``agents.refused_lifecycle.runner``.

Atomic frontmatter rewrite + body preservation + iteration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml

from agents.refused_lifecycle.runner import (
    apply_transition,
    iter_refused_tasks,
    parse_frontmatter,
    transitions_total,
)
from agents.refused_lifecycle.state import (
    TransitionEvent,
)

_NOW = datetime(2026, 4, 26, 21, 30, tzinfo=UTC)


def _write_task_file(
    path: Path,
    *,
    slug: str = "leverage-twitter",
    automation_status: str = "REFUSED",
    body: str = "# Refusal: leverage twitter\n\nDescription.\n",
    extra: dict | None = None,
) -> None:
    fm = {
        "type": "cc-task",
        "task_id": slug,
        "title": f"refusal: {slug}",
        "automation_status": automation_status,
        "refusal_reason": "single_user axiom",
        "evaluation_trigger": ["constitutional"],
        "evaluation_probe": {"depends_on_slug": None},
    }
    if extra:
        fm.update(extra)
    path.write_text(f"---\n{yaml.safe_dump(fm)}---\n{body}", encoding="utf-8")


# ── parse_frontmatter ────────────────────────────────────────────────


class TestParseFrontmatter:
    def test_parses_basic_refused_task(self, tmp_path: Path):
        f = tmp_path / "leverage-twitter.md"
        _write_task_file(f)
        task = parse_frontmatter(f)
        assert task.slug == "leverage-twitter"
        assert task.automation_status == "REFUSED"
        assert task.evaluation_trigger == ["constitutional"]

    def test_slug_derives_from_filename(self, tmp_path: Path):
        f = tmp_path / "custom-slug.md"
        _write_task_file(f, slug="leverage-twitter")
        task = parse_frontmatter(f)
        assert task.slug == "custom-slug"


# ── iter_refused_tasks ───────────────────────────────────────────────


class TestIterRefusedTasks:
    def test_yields_only_refused_status(self, tmp_path: Path):
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        c = tmp_path / "c.md"
        _write_task_file(a, slug="a", automation_status="REFUSED")
        _write_task_file(b, slug="b", automation_status="OFFERED")
        _write_task_file(c, slug="c", automation_status="REMOVED")
        results = list(iter_refused_tasks(tmp_path))
        assert {t.slug for t in results} == {"a"}

    def test_skips_files_without_automation_status(self, tmp_path: Path):
        # Regression pin: parse_frontmatter must NOT default missing status
        # to "REFUSED", or every legacy cc-task gets mass-mutated on tick.
        f = tmp_path / "legacy.md"
        f.write_text(
            "---\ntype: cc-task\ntask_id: legacy\ntitle: legacy\n---\n# body\n",
            encoding="utf-8",
        )
        results = list(iter_refused_tasks(tmp_path))
        assert results == []

    def test_walks_both_active_and_closed_subdirs(self, tmp_path: Path):
        # Regression pin for the P0 vault-scope-fix: when scan_root has an
        # `active/` subdir, walk both `active/` and `closed/`. Most refusal
        # cc-tasks live in closed/ once their refusal-briefs ship, but the
        # constitutional refusal persists indefinitely.
        active = tmp_path / "active"
        closed = tmp_path / "closed"
        active.mkdir()
        closed.mkdir()
        _write_task_file(active / "refused-active.md", slug="refused-active")
        _write_task_file(closed / "refused-closed.md", slug="refused-closed")
        results = list(iter_refused_tasks(tmp_path))
        assert {t.slug for t in results} == {"refused-active", "refused-closed"}

    def test_active_dir_passed_directly_promotes_to_vault_base(self, tmp_path: Path):
        # Production shape: the env-var default points at .../active. We
        # auto-promote to the parent so closed/ is scanned too.
        active = tmp_path / "active"
        closed = tmp_path / "closed"
        active.mkdir()
        closed.mkdir()
        _write_task_file(active / "a.md", slug="a")
        _write_task_file(closed / "c.md", slug="c")
        results = list(iter_refused_tasks(active))
        assert {t.slug for t in results} == {"a", "c"}


# ── apply_transition: re-affirm ─────────────────────────────────────


class TestApplyTransitionReAffirm:
    def test_status_remains_refused_history_appended(self, tmp_path: Path):
        f = tmp_path / "leverage-twitter.md"
        _write_task_file(f)
        task = parse_frontmatter(f)
        event = TransitionEvent(
            timestamp=_NOW,
            cc_task_slug=task.slug,
            from_state="REFUSED",
            to_state="REFUSED",
            transition="re-affirmed",
            trigger=["constitutional"],
            reason="probe-content-unchanged",
        )
        apply_transition(f, task, event, _NOW)

        text = f.read_text(encoding="utf-8")
        assert "automation_status: REFUSED" in text
        assert "# Refusal: leverage twitter" in text  # body preserved verbatim
        # Reload and verify history appended
        task2 = parse_frontmatter(f)
        assert len(task2.refusal_history) == 1
        assert task2.refusal_history[0].transition == "re-affirmed"
        assert task2.last_evaluated_at is not None

    def test_body_preserved_verbatim(self, tmp_path: Path):
        f = tmp_path / "x.md"
        unique_body = "# Title\n\nA paragraph with `code` and **bold**.\n\n- item 1\n- item 2\n"
        _write_task_file(f, body=unique_body)
        task = parse_frontmatter(f)
        event = TransitionEvent(
            timestamp=_NOW,
            cc_task_slug=task.slug,
            from_state="REFUSED",
            to_state="REFUSED",
            transition="re-affirmed",
            trigger=["constitutional"],
            reason="x",
        )
        apply_transition(f, task, event, _NOW)
        text = f.read_text(encoding="utf-8")
        # Body after closing --- must be exactly unique_body
        body_part = text.split("---\n", 2)[2]
        assert body_part == unique_body


# ── apply_transition: accept ─────────────────────────────────────────


class TestApplyTransitionAccept:
    def test_status_flipped_to_offered(self, tmp_path: Path):
        f = tmp_path / "x.md"
        _write_task_file(f)
        task = parse_frontmatter(f)
        event = TransitionEvent(
            timestamp=_NOW,
            cc_task_slug=task.slug,
            from_state="REFUSED",
            to_state="ACCEPTED",
            transition="accepted",
            trigger=["constitutional"],
            evidence_url="https://example.com/lifted",
            reason="lift-keyword present",
        )
        apply_transition(f, task, event, _NOW)
        task2 = parse_frontmatter(f)
        assert task2.automation_status == "OFFERED"
        assert task2.acceptance_evidence is not None
        assert task2.acceptance_evidence["evidence_url"] == "https://example.com/lifted"


# ── apply_transition: removal ────────────────────────────────────────


class TestApplyTransitionRoundTripsProbe:
    """P0-2 regression: apply_transition must persist evaluation_probe so
    watcher mutations (etag / last_lm / last_fingerprint) survive the YAML
    rewrite. Without round-trip the next probe burns a full GET every cycle.
    """

    def test_evaluation_probe_round_trips(self, tmp_path: Path):
        f = tmp_path / "x.md"
        _write_task_file(f)
        task = parse_frontmatter(f)
        # Watcher mutated the in-memory probe state (simulating
        # _persist_probe_state having run with new etag/fingerprint)
        task.evaluation_probe = {
            "url": "https://example.com",
            "last_etag": '"new-etag"',
            "last_fingerprint": "abc" * 21 + "x",
            "lift_keywords": ["upload"],
        }
        event = TransitionEvent(
            timestamp=_NOW,
            cc_task_slug=task.slug,
            from_state="REFUSED",
            to_state="REFUSED",
            transition="re-affirmed",
            trigger=["structural"],
            reason="probe-content-unchanged",
        )
        apply_transition(f, task, event, _NOW)
        task2 = parse_frontmatter(f)
        assert task2.evaluation_probe["last_etag"] == '"new-etag"'
        assert task2.evaluation_probe["last_fingerprint"] == "abc" * 21 + "x"


class TestApplyTransitionRemoval:
    def test_status_flipped_to_removed(self, tmp_path: Path):
        f = tmp_path / "x.md"
        _write_task_file(f)
        task = parse_frontmatter(f)
        event = TransitionEvent(
            timestamp=_NOW,
            cc_task_slug=task.slug,
            from_state="REFUSED",
            to_state="REMOVED",
            transition="removed",
            trigger=["constitutional"],
            reason="axiom retired",
        )
        apply_transition(f, task, event, _NOW)
        text = f.read_text(encoding="utf-8")
        assert "automation_status: REMOVED" in text


# ── Atomicity ────────────────────────────────────────────────────────


class TestAtomicWrite:
    def test_no_tmp_file_remains(self, tmp_path: Path):
        f = tmp_path / "x.md"
        _write_task_file(f)
        task = parse_frontmatter(f)
        event = TransitionEvent(
            timestamp=_NOW,
            cc_task_slug=task.slug,
            from_state="REFUSED",
            to_state="REFUSED",
            transition="re-affirmed",
            trigger=["constitutional"],
            reason="x",
        )
        apply_transition(f, task, event, _NOW)
        # Only the original file should remain — no .md.tmp.* leftover
        files = list(tmp_path.iterdir())
        assert files == [f]


# ── Prometheus counter ───────────────────────────────────────────────


class TestPrometheusCounter:
    def test_apply_transition_increments_counter(self, tmp_path: Path):
        f = tmp_path / "metric-test.md"
        _write_task_file(f, slug="metric-test")
        task = parse_frontmatter(f)
        event = TransitionEvent(
            timestamp=_NOW,
            cc_task_slug=task.slug,
            from_state="REFUSED",
            to_state="REFUSED",
            transition="re-affirmed",
            trigger=["constitutional"],
            reason="x",
        )
        before = transitions_total.labels(
            from_state="REFUSED", to_state="REFUSED", slug="metric-test"
        )._value.get()
        apply_transition(f, task, event, _NOW)
        after = transitions_total.labels(
            from_state="REFUSED", to_state="REFUSED", slug="metric-test"
        )._value.get()
        assert after == before + 1
