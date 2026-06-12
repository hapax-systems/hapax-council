"""Tests for bounded JSONL retention helpers."""

from __future__ import annotations

from pathlib import Path

from shared.jsonl_retention import append_bounded_jsonl_line, rewrite_bounded_jsonl_lines


def test_append_bounded_jsonl_line_keeps_newest_rows(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"

    for idx in range(3):
        append_bounded_jsonl_line(path, f'{{"idx":{idx}}}', max_lines=2)

    assert path.read_text(encoding="utf-8").splitlines() == ['{"idx":1}', '{"idx":2}']


def test_rewrite_bounded_jsonl_lines_replaces_with_cap(tmp_path: Path) -> None:
    path = tmp_path / "state.jsonl"
    path.write_text('{"old":true}\n', encoding="utf-8")

    rewrite_bounded_jsonl_lines(
        path,
        (f'{{"idx":{idx}}}' for idx in range(3)),
        max_lines=2,
    )

    assert path.read_text(encoding="utf-8").splitlines() == ['{"idx":1}', '{"idx":2}']
