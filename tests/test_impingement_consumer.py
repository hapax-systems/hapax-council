"""tests/test_impingement_consumer.py — ImpingementConsumer unit tests."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

from shared.impingement import Impingement, ImpingementType
from shared.impingement_consumer import ImpingementConsumer
from shared.jsonl_cursor import write_jsonl_cursor


def _make_imp(source: str = "dmn.test", strength: float = 0.5) -> Impingement:
    return Impingement(
        timestamp=time.time(),
        source=source,
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=strength,
        content={"metric": "test"},
    )


def _write_jsonl(path: Path, imps: list[Impingement]) -> None:
    with path.open("a", encoding="utf-8") as f:
        for imp in imps:
            f.write(imp.model_dump_json() + "\n")


class TestImpingementConsumer:
    def test_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "imp.jsonl"
        path.write_text("", encoding="utf-8")
        consumer = ImpingementConsumer(path)
        assert consumer.read_new() == []
        assert consumer.cursor == 0

    def test_missing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "nonexistent.jsonl"
        consumer = ImpingementConsumer(path)
        assert consumer.read_new() == []

    def test_reads_new_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "imp.jsonl"
        imp1 = _make_imp("source.a")
        imp2 = _make_imp("source.b")
        _write_jsonl(path, [imp1, imp2])
        consumer = ImpingementConsumer(path)
        result = consumer.read_new()
        assert len(result) == 2
        assert result[0].source == "source.a"
        assert result[1].source == "source.b"
        assert consumer.cursor == 2

    def test_cursor_advances(self, tmp_path: Path) -> None:
        path = tmp_path / "imp.jsonl"
        _write_jsonl(path, [_make_imp("first")])
        consumer = ImpingementConsumer(path)
        first = consumer.read_new()
        assert len(first) == 1
        _write_jsonl(path, [_make_imp("second"), _make_imp("third")])
        second = consumer.read_new()
        assert len(second) == 2
        assert second[0].source == "second"
        assert consumer.cursor == 3

    def test_no_new_lines_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "imp.jsonl"
        _write_jsonl(path, [_make_imp()])
        consumer = ImpingementConsumer(path)
        consumer.read_new()
        assert consumer.read_new() == []

    def test_malformed_lines_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "imp.jsonl"
        imp = _make_imp("valid")
        with path.open("w", encoding="utf-8") as f:
            f.write("not json at all\n")
            f.write(imp.model_dump_json() + "\n")
            f.write("{bad json\n")
        consumer = ImpingementConsumer(path)
        result = consumer.read_new()
        assert len(result) == 1
        assert result[0].source == "valid"
        assert consumer.cursor == 3

    def test_blank_lines_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "imp.jsonl"
        imp = _make_imp()
        with path.open("w", encoding="utf-8") as f:
            f.write("\n")
            f.write(imp.model_dump_json() + "\n")
            f.write("\n")
        consumer = ImpingementConsumer(path)
        result = consumer.read_new()
        assert len(result) == 1

    def test_oserror_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "imp.jsonl"
        _write_jsonl(path, [_make_imp()])
        consumer = ImpingementConsumer(path)
        with patch.object(Path, "read_text", side_effect=OSError("disk")):
            assert consumer.read_new() == []
        assert consumer.cursor == 0

    def test_start_at_end_skips_backlog(self, tmp_path: Path) -> None:
        """F6: start_at_end=True skips any accumulated lines on construction."""
        path = tmp_path / "imp.jsonl"
        _write_jsonl(path, [_make_imp("backlog.a"), _make_imp("backlog.b"), _make_imp("backlog.c")])
        consumer = ImpingementConsumer(path, start_at_end=True)
        # Cursor should already be positioned at the end.
        assert consumer.cursor == 3
        # First read yields no impingements — all pre-existing lines skipped.
        assert consumer.read_new() == []

    def test_start_at_end_yields_new_lines_after_init(self, tmp_path: Path) -> None:
        """F6: start_at_end=True does not block future lines."""
        path = tmp_path / "imp.jsonl"
        _write_jsonl(path, [_make_imp("old")])
        consumer = ImpingementConsumer(path, start_at_end=True)
        assert consumer.read_new() == []
        # Append a new line after construction.
        _write_jsonl(path, [_make_imp("fresh")])
        result = consumer.read_new()
        assert len(result) == 1
        assert result[0].source == "fresh"

    def test_start_at_end_on_missing_file(self, tmp_path: Path) -> None:
        """F6: start_at_end=True handles missing file without raising."""
        path = tmp_path / "not-yet.jsonl"
        consumer = ImpingementConsumer(path, start_at_end=True)
        assert consumer.cursor == 0
        # File appears after construction.
        _write_jsonl(path, [_make_imp("first")])
        result = consumer.read_new()
        assert len(result) == 1
        assert result[0].source == "first"

    def test_start_at_end_default_is_false(self, tmp_path: Path) -> None:
        """F6: backward compat — default behavior reads from beginning."""
        path = tmp_path / "imp.jsonl"
        _write_jsonl(path, [_make_imp("backlog")])
        consumer = ImpingementConsumer(path)  # no start_at_end kwarg
        assert consumer.cursor == 0
        result = consumer.read_new()
        assert len(result) == 1
        assert result[0].source == "backlog"


class TestCursorPersistence:
    """Cursor persistence across restarts (F6 part 2).

    Composes on top of ``start_at_end``: ``cursor_path`` combines
    startup-skip semantics with crash-resume. First-ever startup (cursor
    file missing) seeks to end; subsequent starts resume from the saved
    cursor. Each advance is atomically persisted. Correct for daemons
    where missing an impingement would be a correctness bug
    (daimonion voice state, fortress governance).
    """

    def test_first_startup_seeks_to_end_and_skips_backlog(self, tmp_path: Path) -> None:
        path = tmp_path / "imp.jsonl"
        cursor_path = tmp_path / "cursor.txt"
        _write_jsonl(path, [_make_imp("pre-backlog-1"), _make_imp("pre-backlog-2")])

        consumer = ImpingementConsumer(path, cursor_path=cursor_path)

        assert consumer.cursor == 2
        assert consumer.read_new() == []
        assert cursor_path.exists()
        assert cursor_path.read_text() == "2"

    def test_second_startup_resumes_from_persisted_cursor(self, tmp_path: Path) -> None:
        path = tmp_path / "imp.jsonl"
        cursor_path = tmp_path / "cursor.txt"
        _write_jsonl(path, [_make_imp("old-1"), _make_imp("old-2")])

        c1 = ImpingementConsumer(path, cursor_path=cursor_path)
        assert c1.cursor == 2

        _write_jsonl(path, [_make_imp("new-1"), _make_imp("new-2")])

        c2 = ImpingementConsumer(path, cursor_path=cursor_path)
        assert c2.cursor == 2
        result = c2.read_new()
        assert len(result) == 2
        assert result[0].source == "new-1"
        assert result[1].source == "new-2"
        assert cursor_path.read_text() == "4"

    def test_cursor_persisted_after_read_new_advance(self, tmp_path: Path) -> None:
        path = tmp_path / "imp.jsonl"
        cursor_path = tmp_path / "cursor.txt"
        path.write_text("", encoding="utf-8")

        consumer = ImpingementConsumer(path, cursor_path=cursor_path)
        assert consumer.cursor == 0
        assert cursor_path.read_text() == "0"

        _write_jsonl(path, [_make_imp("one"), _make_imp("two")])
        consumer.read_new()
        assert cursor_path.read_text() == "2"

        _write_jsonl(path, [_make_imp("three")])
        consumer.read_new()
        assert cursor_path.read_text() == "3"

    def test_corrupt_cursor_file_falls_back_to_end_of_file(self, tmp_path: Path) -> None:
        path = tmp_path / "imp.jsonl"
        cursor_path = tmp_path / "cursor.txt"
        _write_jsonl(path, [_make_imp("a"), _make_imp("b"), _make_imp("c")])
        cursor_path.write_text("not-a-number", encoding="utf-8")

        consumer = ImpingementConsumer(path, cursor_path=cursor_path)

        assert consumer.cursor == 3
        assert consumer.read_new() == []
        assert cursor_path.read_text() == "3"

    def test_negative_cursor_in_file_falls_back_to_end_of_file(self, tmp_path: Path) -> None:
        path = tmp_path / "imp.jsonl"
        cursor_path = tmp_path / "cursor.txt"
        _write_jsonl(path, [_make_imp("a"), _make_imp("b")])
        cursor_path.write_text("-5", encoding="utf-8")

        consumer = ImpingementConsumer(path, cursor_path=cursor_path)

        assert consumer.cursor == 2

    def test_file_shrinkage_resets_cursor_and_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "imp.jsonl"
        cursor_path = tmp_path / "cursor.txt"
        _write_jsonl(path, [_make_imp("a"), _make_imp("b"), _make_imp("c")])

        consumer = ImpingementConsumer(path, cursor_path=cursor_path)
        assert consumer.cursor == 3

        path.write_text("", encoding="utf-8")
        _write_jsonl(path, [_make_imp("post-rotation")])

        result = consumer.read_new()
        assert result == []
        assert consumer.cursor == 1
        assert cursor_path.read_text() == "1"

        _write_jsonl(path, [_make_imp("after-reset")])
        result = consumer.read_new()
        assert len(result) == 1
        assert result[0].source == "after-reset"

    def test_rename_rotation_resets_cursor_and_reads_future_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "imp.jsonl"
        cursor_path = tmp_path / "cursor.txt"
        _write_jsonl(path, [_make_imp("a"), _make_imp("b"), _make_imp("c")])

        consumer = ImpingementConsumer(path, cursor_path=cursor_path)
        assert consumer.cursor == 3

        rotated = tmp_path / "imp.rotated.jsonl"
        path.replace(rotated)
        path.write_text("", encoding="utf-8")
        _write_jsonl(path, [_make_imp("post-rotation")])

        result = consumer.read_new()
        assert len(result) == 1
        assert result[0].source == "post-rotation"
        assert consumer.cursor == 1
        assert cursor_path.read_text() == "1"

        _write_jsonl(path, [_make_imp("after-reset")])
        result = consumer.read_new()

        assert len(result) == 1
        assert result[0].source == "after-reset"

    def test_inode_rotation_at_same_line_count_reads_replacement_file(self, tmp_path: Path) -> None:
        path = tmp_path / "imp.jsonl"
        cursor_path = tmp_path / "cursor.txt"
        _write_jsonl(path, [_make_imp("old-a"), _make_imp("old-b")])

        consumer = ImpingementConsumer(path, cursor_path=cursor_path)
        assert consumer.cursor == 2

        rotated = tmp_path / "imp.rotated.jsonl"
        path.replace(rotated)
        _write_jsonl(path, [_make_imp("new-a"), _make_imp("new-b")])

        result = consumer.read_new()

        assert [imp.source for imp in result] == ["new-a", "new-b"]
        assert consumer.cursor == 2

    def test_legacy_cursor_without_identity_reads_same_line_count_replacement(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "imp.jsonl"
        cursor_path = tmp_path / "cursor.txt"
        _write_jsonl(path, [_make_imp("new-a"), _make_imp("new-b")])
        cursor_path.write_text("2", encoding="utf-8")

        consumer = ImpingementConsumer(path, cursor_path=cursor_path)
        result = consumer.read_new()

        assert [imp.source for imp in result] == ["new-a", "new-b"]
        assert consumer.cursor == 2
        assert cursor_path.with_name("cursor.txt.state.json").exists()

    def test_cursor_parent_directory_created_on_demand(self, tmp_path: Path) -> None:
        path = tmp_path / "imp.jsonl"
        cursor_path = tmp_path / "nested" / "deeper" / "cursor.txt"
        _write_jsonl(path, [_make_imp()])

        consumer = ImpingementConsumer(path, cursor_path=cursor_path)

        assert cursor_path.exists()
        assert cursor_path.parent.is_dir()
        assert consumer.cursor == 1

    def test_cursor_path_takes_precedence_over_start_at_end(self, tmp_path: Path) -> None:
        path = tmp_path / "imp.jsonl"
        cursor_path = tmp_path / "cursor.txt"
        _write_jsonl(path, [_make_imp("first"), _make_imp("second")])
        write_jsonl_cursor(cursor_path, 1, source_path=path)

        consumer = ImpingementConsumer(
            path,
            start_at_end=True,
            cursor_path=cursor_path,
        )

        assert consumer.cursor == 1
        result = consumer.read_new()
        assert len(result) == 1
        assert result[0].source == "second"

    def test_cursor_write_failure_does_not_crash_read_new(self, tmp_path: Path) -> None:
        path = tmp_path / "imp.jsonl"
        cursor_path = tmp_path / "cursor.txt"
        path.write_text("", encoding="utf-8")
        consumer = ImpingementConsumer(path, cursor_path=cursor_path)

        _write_jsonl(path, [_make_imp("one")])

        with patch.object(Path, "replace", side_effect=OSError("readonly fs")):
            result = consumer.read_new()

        assert len(result) == 1
        assert consumer.cursor == 1

    def test_missing_impingement_file_bootstrap(self, tmp_path: Path) -> None:
        path = tmp_path / "imp.jsonl"
        cursor_path = tmp_path / "cursor.txt"

        consumer = ImpingementConsumer(path, cursor_path=cursor_path)

        assert consumer.cursor == 0
        assert cursor_path.read_text() == "0"
        assert consumer.read_new() == []

        _write_jsonl(path, [_make_imp("first-write")])
        result = consumer.read_new()
        assert len(result) == 1
        assert result[0].source == "first-write"
