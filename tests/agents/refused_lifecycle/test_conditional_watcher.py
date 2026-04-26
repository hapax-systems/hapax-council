"""Tests for ``agents.refused_lifecycle.conditional_watcher``.

Covers the dependency-event hook ``on_cc_task_closed`` and the
``probe_conditional`` delegation logic. The actual underlying probes
(structural HTTP / constitutional inotify) are unit-tested in their
respective files; this file covers the routing layer.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from agents.refused_lifecycle.conditional_watcher import (
    matches_dependency,
    probe_conditional,
)
from agents.refused_lifecycle.state import ProbeResult, RefusalTask


def _conditional_task(
    *,
    depends_on_slug: list[str] | None = None,
    url: str | None = None,
    conditional_path: str | None = None,
) -> RefusalTask:
    return RefusalTask(
        slug="hypothetical-conditional-task",
        path="/tmp/x.md",
        automation_status="REFUSED",
        refusal_reason="dependency-not-yet-shipped",
        evaluation_trigger=["conditional"],
        evaluation_probe={
            "url": url,
            "conditional_path": conditional_path,
            "depends_on_slug": depends_on_slug or ["pub-bus-orcid-auto-update"],
            "lift_keywords": [],
            "lift_polarity": "present",
            "last_etag": None,
            "last_lm": None,
            "last_fingerprint": None,
        },
    )


# ── matches_dependency ──────────────────────────────────────────────


class TestMatchesDependency:
    def test_string_match(self):
        task = _conditional_task(depends_on_slug=["pub-bus-orcid-auto-update"])
        assert matches_dependency(task, "pub-bus-orcid-auto-update") is True

    def test_list_match(self):
        task = _conditional_task(depends_on_slug=["pub-bus-orcid-auto-update", "another-dep"])
        assert matches_dependency(task, "another-dep") is True

    def test_no_match_returns_false(self):
        task = _conditional_task(depends_on_slug=["pub-bus-orcid-auto-update"])
        assert matches_dependency(task, "unrelated-task") is False

    def test_none_dependency_returns_false(self):
        # depends_on_slug explicitly None — must NOT match anything
        empty_task = RefusalTask(
            slug="x",
            path="/tmp/x",
            automation_status="REFUSED",
            refusal_reason="x",
            evaluation_trigger=["conditional"],
            evaluation_probe={"depends_on_slug": None},
        )
        assert matches_dependency(empty_task, "anything") is False

    def test_string_dep_normalised_to_match(self):
        # depends_on_slug may be a single string in legacy frontmatter
        task = _conditional_task()
        task.evaluation_probe["depends_on_slug"] = "single-slug"
        assert matches_dependency(task, "single-slug") is True


# ── probe_conditional delegation ─────────────────────────────────────


class TestProbeConditionalDelegation:
    @pytest.mark.asyncio
    async def test_delegates_to_structural_when_url_present(self):
        task = _conditional_task(url="https://example.com/policy")
        expected = ProbeResult(changed=True, evidence_url="https://x", snippet="lift")
        with patch(
            "agents.refused_lifecycle.conditional_watcher.structural_watcher.probe_url",
            new=AsyncMock(return_value=expected),
        ):
            result = await probe_conditional(task, just_closed="dep-x")
        assert result == expected

    @pytest.mark.asyncio
    async def test_delegates_to_constitutional_when_path_present(self, tmp_path: Path):
        target = tmp_path / "memory.md"
        target.write_text("content", encoding="utf-8")
        task = _conditional_task(conditional_path=str(target))
        expected = ProbeResult(changed=False)
        with patch(
            "agents.refused_lifecycle.conditional_watcher.constitutional_watcher.probe_constitutional",
            return_value=expected,
        ):
            result = await probe_conditional(task, just_closed="dep-x")
        assert result == expected

    @pytest.mark.asyncio
    async def test_no_underlying_probe_re_affirms_with_note(self):
        task = _conditional_task()
        # depends_on_slug set but no url + no conditional_path
        result = await probe_conditional(task, just_closed="pub-bus-orcid-auto-update")
        assert result.changed is False
        assert result.snippet is not None
        assert "pub-bus-orcid-auto-update" in result.snippet


# ── End-to-end on_cc_task_closed event hook ─────────────────────────


class TestOnCcTaskClosed:
    """The hook locates type-C tasks whose depends_on matches the closed
    slug, then routes through ``probe_conditional``. This integration is
    exercised by writing a small vault tree under tmp_path."""

    def _seed_conditional_task(
        self,
        active_dir: Path,
        slug: str,
        depends_on_slug: list[str] | str,
    ) -> Path:
        path = active_dir / f"{slug}.md"
        fm = {
            "type": "cc-task",
            "task_id": slug,
            "title": "x",
            "automation_status": "REFUSED",
            "refusal_reason": "y",
            "evaluation_trigger": ["conditional"],
            "evaluation_probe": {
                "url": None,
                "conditional_path": None,
                "depends_on_slug": depends_on_slug,
                "lift_keywords": [],
                "lift_polarity": "present",
                "last_etag": None,
                "last_lm": None,
                "last_fingerprint": None,
            },
        }
        path.write_text(f"---\n{yaml.safe_dump(fm)}---\n# body\n", encoding="utf-8")
        return path

    def test_on_close_finds_matching_type_c(self, tmp_path: Path):
        from agents.refused_lifecycle.conditional_watcher import (
            find_dependent_tasks,
        )

        active = tmp_path / "active"
        active.mkdir()
        self._seed_conditional_task(active, "a", ["pub-bus-orcid-auto-update"])
        b = self._seed_conditional_task(active, "b", ["unrelated"])
        self._seed_conditional_task(active, "c", ["pub-bus-orcid-auto-update"])

        matches = find_dependent_tasks(active, "pub-bus-orcid-auto-update")
        assert {t.slug for t in matches} == {"a", "c"}
        # Non-matching task untouched on disk
        assert b.exists()
