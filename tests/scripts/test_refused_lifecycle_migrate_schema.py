"""Tests for ``scripts/refused_lifecycle_migrate_schema.py``.

Migration adds the seven new schema fields to every cc-task with
``automation_status: REFUSED``. Idempotent — re-running on already-migrated
files is a no-op. Body preserved verbatim.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
_SCRIPT_PATH = _SCRIPTS_DIR / "refused_lifecycle_migrate_schema.py"


@pytest.fixture(scope="module")
def migrate_module():
    spec = importlib.util.spec_from_file_location("refused_lifecycle_migrate_schema", _SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["refused_lifecycle_migrate_schema"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_NOW = datetime(2026, 4, 26, 22, 0, tzinfo=UTC)


def _write_task(
    path: Path,
    *,
    automation_status: str = "REFUSED",
    refusal_reason: str = "single_user axiom",
    body: str = "# refusal\n\nbody.\n",
    extra: dict | None = None,
) -> None:
    fm = {
        "type": "cc-task",
        "task_id": path.stem,
        "title": f"refusal: {path.stem}",
        "status": "claimed",
        "created_at": "2026-04-25T18:30:00Z",
        "automation_status": automation_status,
        "refusal_reason": refusal_reason,
        "tags": ["refusal-as-data"],
    }
    if extra:
        fm.update(extra)
    path.write_text(f"---\n{yaml.safe_dump(fm)}---\n{body}", encoding="utf-8")


def _read_fm(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    rest = text[4:]
    end = rest.find("\n---\n")
    return yaml.safe_load(rest[:end]) or {}


# ── Migration adds seven new fields ─────────────────────────────────


class TestMigrationAddsFields:
    def test_all_seven_fields_added(self, tmp_path: Path, migrate_module):
        f = tmp_path / "leverage-twitter.md"
        _write_task(f)
        migrate_module.migrate(tmp_path, _NOW)
        fm = _read_fm(f)
        assert "last_evaluated_at" in fm
        assert "next_evaluation_at" in fm
        assert fm["evaluation_trigger"] == ["constitutional"]
        assert isinstance(fm["evaluation_probe"], dict)
        assert "url" in fm["evaluation_probe"]
        assert "lift_keywords" in fm["evaluation_probe"]
        assert isinstance(fm["refusal_history"], list)
        assert fm["superseded_by"] is None
        assert fm["acceptance_evidence"] is None
        assert fm["removed_reason"] is None

    def test_history_carries_original_refusal_reason(self, tmp_path: Path, migrate_module):
        f = tmp_path / "x.md"
        _write_task(f, refusal_reason="full-automation-or-nothing axiom")
        migrate_module.migrate(tmp_path, _NOW)
        fm = _read_fm(f)
        assert len(fm["refusal_history"]) == 1
        entry = fm["refusal_history"][0]
        assert entry["transition"] == "created"
        assert entry["reason"] == "full-automation-or-nothing axiom"

    def test_original_refusal_reason_preserved_verbatim(self, tmp_path: Path, migrate_module):
        f = tmp_path / "x.md"
        _write_task(f, refusal_reason="exact policy text")
        migrate_module.migrate(tmp_path, _NOW)
        fm = _read_fm(f)
        # `refusal_reason` field must still be present and unchanged
        assert fm["refusal_reason"] == "exact policy text"

    def test_next_evaluation_is_30_days_default(self, tmp_path: Path, migrate_module):
        f = tmp_path / "x.md"
        _write_task(f)
        migrate_module.migrate(tmp_path, _NOW)
        fm = _read_fm(f)
        next_eval = datetime.fromisoformat(fm["next_evaluation_at"])
        assert next_eval - _NOW == timedelta(days=30)


# ── Idempotency ──────────────────────────────────────────────────────


class TestIdempotency:
    def test_re_run_is_noop(self, tmp_path: Path, migrate_module):
        f = tmp_path / "x.md"
        _write_task(f)
        first = migrate_module.migrate(tmp_path, _NOW)
        assert len(first) == 1
        text_after_first = f.read_text(encoding="utf-8")

        # Re-run — should skip already-migrated files
        second = migrate_module.migrate(tmp_path, _NOW + timedelta(hours=1))
        assert len(second) == 0
        assert f.read_text(encoding="utf-8") == text_after_first


# ── Body preservation ───────────────────────────────────────────────


class TestBodyPreservation:
    def test_body_unchanged(self, tmp_path: Path, migrate_module):
        f = tmp_path / "x.md"
        unique_body = "# Title\n\n```python\ncode block\n```\n\n- list\n- items\n"
        _write_task(f, body=unique_body)
        migrate_module.migrate(tmp_path, _NOW)
        text = f.read_text(encoding="utf-8")
        body_part = text.split("---\n", 2)[2]
        assert body_part == unique_body


# ── Status filtering ───────────────────────────────────────────────


class TestStatusFiltering:
    def test_skips_offered_tasks(self, tmp_path: Path, migrate_module):
        f = tmp_path / "x.md"
        _write_task(f, automation_status="OFFERED")
        migrated = migrate_module.migrate(tmp_path, _NOW)
        assert migrated == []
        fm = _read_fm(f)
        assert "refusal_history" not in fm

    def test_skips_full_auto_tasks(self, tmp_path: Path, migrate_module):
        f = tmp_path / "x.md"
        _write_task(f, automation_status="FULL_AUTO")
        migrated = migrate_module.migrate(tmp_path, _NOW)
        assert migrated == []

    def test_skips_files_without_automation_status(self, tmp_path: Path, migrate_module):
        f = tmp_path / "x.md"
        # No automation_status in frontmatter
        f.write_text(
            "---\ntype: cc-task\ntitle: legacy\n---\n# body\n",
            encoding="utf-8",
        )
        migrated = migrate_module.migrate(tmp_path, _NOW)
        assert migrated == []


# ── Malformed frontmatter ────────────────────────────────────────────


class TestMalformedFrontmatter:
    def test_skips_files_without_frontmatter(self, tmp_path: Path, migrate_module):
        f = tmp_path / "x.md"
        f.write_text("# just markdown\n\nno frontmatter\n", encoding="utf-8")
        migrated = migrate_module.migrate(tmp_path, _NOW)
        assert migrated == []
        # File untouched
        assert f.read_text(encoding="utf-8") == "# just markdown\n\nno frontmatter\n"


# ── Dry-run ──────────────────────────────────────────────────────────


class TestDryRun:
    def test_dry_run_does_not_write(self, tmp_path: Path, migrate_module):
        f = tmp_path / "x.md"
        _write_task(f)
        before = f.read_text(encoding="utf-8")
        migrated = migrate_module.migrate(tmp_path, _NOW, dry_run=True)
        assert len(migrated) == 1  # planned migration reported
        assert f.read_text(encoding="utf-8") == before  # but not committed


# ── Multiple files ───────────────────────────────────────────────────


class TestMultipleFiles:
    def test_migrates_all_refused(self, tmp_path: Path, migrate_module):
        for slug in ("a", "b", "c"):
            _write_task(tmp_path / f"{slug}.md")
        _write_task(tmp_path / "skip.md", automation_status="OFFERED")
        migrated = migrate_module.migrate(tmp_path, _NOW)
        assert len(migrated) == 3
        assert {p.stem for p in migrated} == {"a", "b", "c"}
