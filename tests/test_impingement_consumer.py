"""tests/test_impingement_consumer.py — ImpingementConsumer unit tests."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

from shared.impingement import Impingement, ImpingementType
from shared.impingement_consumer import ImpingementConsumer


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
