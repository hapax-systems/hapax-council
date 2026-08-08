from __future__ import annotations

from pathlib import Path

from shared.jsonl_tail import read_tail_lines

# Generous ceiling for the "cost tracks the request, not the file" assertion: a
# few backward chunks, nowhere near the multi-megabyte ledger under test.
MAX_EXPECTED_SCAN_BYTES = 128 * 1024


def _write(path: Path, lines: list[str], *, trailing_newline: bool = True) -> None:
    text = "\n".join(lines)
    if trailing_newline:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def test_returns_whole_file_when_smaller_than_the_window(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    _write(ledger, ["a", "b", "c"])

    assert read_tail_lines(ledger, max_lines=100) == ["a", "b", "c"]


def test_returns_newest_lines_oldest_first(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    _write(ledger, [f"row-{i}" for i in range(1000)])

    assert read_tail_lines(ledger, max_lines=3) == ["row-997", "row-998", "row-999"]


def test_drops_the_partial_line_at_the_window_edge(tmp_path: Path) -> None:
    """A tiny chunk size forces several backward reads, so the boundary is exercised."""
    ledger = tmp_path / "ledger.jsonl"
    _write(ledger, [f"row-{i:04d}" for i in range(500)])

    tail = read_tail_lines(ledger, max_lines=5, chunk_bytes=8)

    assert tail == [f"row-{i:04d}" for i in range(495, 500)]
    assert all(line.startswith("row-") for line in tail)


def test_handles_missing_trailing_newline(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    _write(ledger, ["a", "b", "c"], trailing_newline=False)

    assert read_tail_lines(ledger, max_lines=2, chunk_bytes=1) == ["b", "c"]


def test_empty_file_and_nonpositive_limit(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("", encoding="utf-8")

    assert read_tail_lines(ledger, max_lines=10) == []
    assert read_tail_lines(ledger, max_lines=0) == []


def test_max_bytes_caps_the_scan(tmp_path: Path) -> None:
    """A single unterminated giant row must not be slurped whole."""
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("x" * 1_000_000, encoding="utf-8")

    # No newline anywhere, so every scanned byte is one partial line, which is
    # dropped — the point is that the read stops rather than loading 1 MB.
    assert read_tail_lines(ledger, max_lines=10, max_bytes=4096, chunk_bytes=1024) == []


def test_reads_far_less_than_the_file(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    _write(ledger, [f"row-{i:06d}" for i in range(200_000)])
    size = ledger.stat().st_size

    read_bytes = 0
    real_open = Path.open

    def counting_open(self: Path, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        handle = real_open(self, *args, **kwargs)  # type: ignore[arg-type]
        real_read = handle.read

        def counting_read(*read_args: object, **read_kwargs: object):  # type: ignore[no-untyped-def]
            nonlocal read_bytes
            data = real_read(*read_args, **read_kwargs)  # type: ignore[arg-type]
            read_bytes += len(data)
            return data

        handle.read = counting_read  # type: ignore[method-assign]
        return handle

    Path.open = counting_open  # type: ignore[method-assign]
    try:
        tail = read_tail_lines(ledger, max_lines=5)
    finally:
        Path.open = real_open  # type: ignore[method-assign]

    assert tail == [f"row-{i:06d}" for i in range(199_995, 200_000)]
    assert size > 1_000_000
    assert read_bytes <= MAX_EXPECTED_SCAN_BYTES, (
        f"read {read_bytes} bytes from a {size}-byte ledger"
    )
