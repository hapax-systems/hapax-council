"""Tests for agents.code_narration.producer (LRR Phase 9 hook 1)."""

from __future__ import annotations

import json
import time
from pathlib import Path

# ── active_window_is_editor ─────────────────────────────────────────────────


class TestActiveWindowIsEditor:
    def test_returns_true_for_neovide(self, monkeypatch):
        from agents.code_narration import producer

        monkeypatch.setattr(
            producer, "_run", lambda *a, **kw: '{"class": "neovide", "title": "foo.py"}'
        )
        assert producer.active_window_is_editor() is True

    def test_returns_true_for_vscode(self, monkeypatch):
        from agents.code_narration import producer

        monkeypatch.setattr(
            producer, "_run", lambda *a, **kw: '{"class": "Code", "title": "persona.py"}'
        )
        assert producer.active_window_is_editor() is True

    def test_returns_false_for_browser(self, monkeypatch):
        from agents.code_narration import producer

        monkeypatch.setattr(
            producer, "_run", lambda *a, **kw: '{"class": "firefox", "title": "docs"}'
        )
        assert producer.active_window_is_editor() is False

    def test_fails_closed_on_hyprctl_failure(self, monkeypatch):
        """If hyprctl isn't available, treat as not-editor (conservative)."""
        from agents.code_narration import producer

        monkeypatch.setattr(producer, "_run", lambda *a, **kw: None)
        assert producer.active_window_is_editor() is False

    def test_fails_closed_on_malformed_json(self, monkeypatch):
        from agents.code_narration import producer

        monkeypatch.setattr(producer, "_run", lambda *a, **kw: "not json")
        assert producer.active_window_is_editor() is False


# ── recent_project_changes ──────────────────────────────────────────────────


class TestRecentProjectChanges:
    def test_skips_project_without_git(self, monkeypatch, tmp_path):
        """A PROJECT_ROOTS entry without a .git dir is skipped silently."""
        from agents.code_narration import producer

        fake_project = tmp_path / "not-a-repo"
        fake_project.mkdir()
        monkeypatch.setattr(producer, "PROJECT_ROOTS", (fake_project,))
        assert producer.recent_project_changes() == []

    def test_includes_recently_modified_files(self, monkeypatch, tmp_path):
        from agents.code_narration import producer

        project = tmp_path / "myproject"
        (project / ".git").mkdir(parents=True)
        (project / "a.py").write_text("x")
        (project / "b.py").write_text("y")
        monkeypatch.setattr(producer, "PROJECT_ROOTS", (project,))
        monkeypatch.setattr(
            producer,
            "_run",
            lambda cmd, cwd=None, timeout=3.0: " M a.py\n M b.py" if cmd[0] == "git" else None,
        )

        result = producer.recent_project_changes()
        assert len(result) == 1
        root, files = result[0]
        assert root == project
        assert set(files) == {"a.py", "b.py"}

    def test_skips_files_older_than_window(self, monkeypatch, tmp_path):
        """Files with mtime older than _RECENT_FILE_WINDOW_S are excluded."""
        from agents.code_narration import producer

        project = tmp_path / "old-edits"
        (project / ".git").mkdir(parents=True)
        old_file = project / "ancient.py"
        old_file.write_text("y")
        # Backdate 10 minutes
        ten_min_ago = time.time() - 600
        import os

        os.utime(old_file, (ten_min_ago, ten_min_ago))

        monkeypatch.setattr(producer, "PROJECT_ROOTS", (project,))
        monkeypatch.setattr(
            producer,
            "_run",
            lambda cmd, cwd=None, timeout=3.0: " M ancient.py" if cmd[0] == "git" else None,
        )
        assert producer.recent_project_changes() == []

    def test_skips_deletions_and_untracked(self, monkeypatch, tmp_path):
        """Deleted + untracked files are noise, not ongoing work."""
        from agents.code_narration import producer

        project = tmp_path / "proj"
        (project / ".git").mkdir(parents=True)
        (project / "kept.py").write_text("k")
        monkeypatch.setattr(producer, "PROJECT_ROOTS", (project,))
        # Deleted file "gone.py", untracked "new.py", modified "kept.py"
        monkeypatch.setattr(
            producer,
            "_run",
            lambda cmd, cwd=None, timeout=3.0: (
                " D gone.py\n?? new.py\n M kept.py" if cmd[0] == "git" else None
            ),
        )
        result = producer.recent_project_changes()
        assert len(result) == 1
        _root, files = result[0]
        assert files == ["kept.py"]


# ── build_narrative ─────────────────────────────────────────────────────────


class TestBuildNarrative:
    def test_single_file(self):
        from agents.code_narration import producer

        narrative = producer.build_narrative(Path("/home/h/projects/hapax-council"), ["x.py"])
        assert "hapax-council" in narrative
        assert "x.py" in narrative

    def test_multiple_files_truncates(self):
        from agents.code_narration import producer

        narrative = producer.build_narrative(Path("/r"), ["a", "b", "c", "d", "e", "f"])
        # First 3 named, rest summarized as count
        assert "a" in narrative and "b" in narrative and "c" in narrative
        assert "3 other files" in narrative


# ── run_once (end-to-end with mocks) ────────────────────────────────────────


class TestRunOnce:
    def test_no_editor_no_emit(self, monkeypatch, tmp_path):
        from agents.code_narration import producer

        monkeypatch.setattr(producer, "_THROTTLE_STATE_FILE", tmp_path / "state.json")
        monkeypatch.setattr(producer, "IMPINGEMENTS_FILE", tmp_path / "impingements.jsonl")
        monkeypatch.setattr(producer, "active_window_is_editor", lambda: False)
        assert producer.run_once() == 0

    def test_no_changes_no_emit(self, monkeypatch, tmp_path):
        from agents.code_narration import producer

        monkeypatch.setattr(producer, "_THROTTLE_STATE_FILE", tmp_path / "state.json")
        monkeypatch.setattr(producer, "IMPINGEMENTS_FILE", tmp_path / "impingements.jsonl")
        monkeypatch.setattr(producer, "active_window_is_editor", lambda: True)
        monkeypatch.setattr(producer, "recent_project_changes", lambda: [])
        assert producer.run_once() == 0

    def test_editor_plus_changes_emits_and_throttles(self, monkeypatch, tmp_path):
        from agents.code_narration import producer

        state_file = tmp_path / "state.json"
        imp_file = tmp_path / "impingements.jsonl"
        monkeypatch.setattr(producer, "_THROTTLE_STATE_FILE", state_file)
        # Patch into the module used by _emit_impingement
        import shared.sensor_protocol

        monkeypatch.setattr(shared.sensor_protocol, "IMPINGEMENTS_FILE", imp_file)
        monkeypatch.setattr(producer, "IMPINGEMENTS_FILE", imp_file)
        monkeypatch.setattr(producer, "active_window_is_editor", lambda: True)

        fake_project = tmp_path / "proj"
        fake_project.mkdir()
        monkeypatch.setattr(
            producer,
            "recent_project_changes",
            lambda: [(fake_project, ["a.py", "b.py"])],
        )

        # First call should emit
        assert producer.run_once() == 1
        assert imp_file.exists()
        first_lines = imp_file.read_text().splitlines()
        assert len(first_lines) == 1
        payload = json.loads(first_lines[0])
        assert payload["source"] == "code_narration"
        assert payload["strength"] == 0.25
        assert payload["content"]["project"] == fake_project.name
        assert "a.py" in payload["content"]["files"]
        assert "a.py" in payload["content"]["narrative"]

        # Second call immediately after — throttled, no new emit
        assert producer.run_once() == 0
        assert len(imp_file.read_text().splitlines()) == 1

    def test_throttle_expires_after_cooldown(self, monkeypatch, tmp_path):
        from agents.code_narration import producer

        state_file = tmp_path / "state.json"
        imp_file = tmp_path / "impingements.jsonl"
        monkeypatch.setattr(producer, "_THROTTLE_STATE_FILE", state_file)
        import shared.sensor_protocol

        monkeypatch.setattr(shared.sensor_protocol, "IMPINGEMENTS_FILE", imp_file)
        monkeypatch.setattr(producer, "IMPINGEMENTS_FILE", imp_file)
        monkeypatch.setattr(producer, "active_window_is_editor", lambda: True)

        fake_project = tmp_path / "proj"
        fake_project.mkdir()
        monkeypatch.setattr(
            producer,
            "recent_project_changes",
            lambda: [(fake_project, ["a.py"])],
        )

        # Prime throttle state with a timestamp that's OLDER than cooldown
        old_ts = time.time() - producer._THROTTLE_PROJECT_S - 30
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps({str(fake_project): old_ts}))

        # Should emit because cooldown expired
        assert producer.run_once() == 1
