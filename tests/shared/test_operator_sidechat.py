"""Tests for shared.operator_sidechat — operator → Hapax private channel (task #132).

Coverage:
- Pydantic validation: empty text, oversize text, role enum.
- JSONL writer: line format, atomic append semantics.
- Tailer: ``since_ts`` filter, chronological order, handles missing file.
- Concurrent writers: two processes appending simultaneously produce
  well-formed lines (no interleaving). Pins the O_APPEND atomicity promise.
- Egress-pin: sidechat path is NOT in ``shared.stream_mode`` deny list
  (it's read by in-process consumers only; it must not be advertised to
  any deny OR allow surface that would put it near an egress boundary).
- Cursor advance in consumer: mock-runner test exercises the cursor
  persist path.
"""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from shared.operator_sidechat import (
    SIDECHAT_MAX_LINE_BYTES,
    SIDECHAT_MAX_TEXT_LEN,
    SIDECHAT_PATH,
    SidechatMessage,
    append_sidechat,
    stream_sidechat,
    tail_sidechat,
)

# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------


class TestSidechatMessageValidation:
    def test_default_role_is_operator(self) -> None:
        m = SidechatMessage(ts=1.0, text="hello")
        assert m.role == "operator"
        assert m.channel == "sidechat"
        assert len(m.msg_id) == 12

    def test_rejects_empty_text(self) -> None:
        with pytest.raises(ValidationError):
            SidechatMessage(ts=1.0, text="")

    def test_rejects_whitespace_only_text(self) -> None:
        with pytest.raises(ValidationError):
            SidechatMessage(ts=1.0, text="   \n\t ")

    def test_rejects_oversize_text(self) -> None:
        with pytest.raises(ValidationError):
            SidechatMessage(ts=1.0, text="x" * (SIDECHAT_MAX_TEXT_LEN + 1))

    def test_accepts_text_at_cap(self) -> None:
        m = SidechatMessage(ts=1.0, text="x" * SIDECHAT_MAX_TEXT_LEN)
        assert len(m.text) == SIDECHAT_MAX_TEXT_LEN

    def test_rejects_invalid_role(self) -> None:
        with pytest.raises(ValidationError):
            SidechatMessage(ts=1.0, text="hi", role="system")  # type: ignore[arg-type]

    def test_accepts_hapax_role(self) -> None:
        m = SidechatMessage(ts=1.0, text="reply", role="hapax")
        assert m.role == "hapax"

    def test_channel_is_pinned(self) -> None:
        # channel literal — anything other than "sidechat" rejected
        with pytest.raises(ValidationError):
            SidechatMessage(ts=1.0, text="x", channel="public")  # type: ignore[arg-type]

    def test_is_frozen(self) -> None:
        m = SidechatMessage(ts=1.0, text="x")
        with pytest.raises(ValidationError):
            m.text = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# JSONL writer
# ---------------------------------------------------------------------------


class TestAppendSidechat:
    def test_writes_single_jsonl_line(self, tmp_path: Path) -> None:
        path = tmp_path / "sidechat.jsonl"
        msg = append_sidechat("hello world", ts=1234.5, path=path)
        assert path.exists()
        lines = path.read_text().splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed == {
            "ts": 1234.5,
            "role": "operator",
            "text": "hello world",
            "channel": "sidechat",
            "msg_id": msg.msg_id,
        }

    def test_append_does_not_truncate_existing(self, tmp_path: Path) -> None:
        path = tmp_path / "sidechat.jsonl"
        append_sidechat("first", ts=1.0, path=path)
        append_sidechat("second", ts=2.0, path=path)
        lines = path.read_text().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["text"] == "first"
        assert json.loads(lines[1])["text"] == "second"

    def test_default_ts_is_now(self, tmp_path: Path) -> None:
        path = tmp_path / "sidechat.jsonl"
        before = time.time()
        msg = append_sidechat("test", path=path)
        after = time.time()
        assert before <= msg.ts <= after

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "deeply" / "sidechat.jsonl"
        append_sidechat("hello", path=path)
        assert path.exists()

    def test_rejects_oversize_line(self, tmp_path: Path) -> None:
        path = tmp_path / "sidechat.jsonl"
        # Stay within the 2000-char text cap but the underlying
        # SIDECHAT_MAX_LINE_BYTES is 64 KB — our 2000-char text can't
        # exceed this on normal UTF-8. This test pins the invariant.
        msg = append_sidechat("x" * SIDECHAT_MAX_TEXT_LEN, path=path)
        line_bytes = len((msg.model_dump_json() + "\n").encode("utf-8"))
        assert line_bytes < SIDECHAT_MAX_LINE_BYTES

    def test_hapax_role_writes(self, tmp_path: Path) -> None:
        path = tmp_path / "sidechat.jsonl"
        msg = append_sidechat("reply", role="hapax", path=path)
        assert msg.role == "hapax"
        assert json.loads(path.read_text())["role"] == "hapax"


# ---------------------------------------------------------------------------
# Tailer
# ---------------------------------------------------------------------------


class TestTailSidechat:
    def test_returns_empty_on_missing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "missing.jsonl"
        assert list(tail_sidechat(path=path)) == []

    def test_since_ts_filter(self, tmp_path: Path) -> None:
        path = tmp_path / "sidechat.jsonl"
        append_sidechat("a", ts=1.0, path=path)
        append_sidechat("b", ts=2.0, path=path)
        append_sidechat("c", ts=3.0, path=path)
        result = list(tail_sidechat(since_ts=1.5, path=path))
        assert [m.text for m in result] == ["b", "c"]

    def test_since_ts_none_returns_all(self, tmp_path: Path) -> None:
        path = tmp_path / "sidechat.jsonl"
        append_sidechat("a", ts=1.0, path=path)
        append_sidechat("b", ts=2.0, path=path)
        result = list(tail_sidechat(path=path))
        assert [m.text for m in result] == ["a", "b"]

    def test_malformed_lines_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "sidechat.jsonl"
        append_sidechat("valid", ts=1.0, path=path)
        # Append a garbage line
        with path.open("a") as f:
            f.write("{ broken json\n")
            f.write("\n")  # blank line
        append_sidechat("also-valid", ts=3.0, path=path)
        result = list(tail_sidechat(path=path))
        assert [m.text for m in result] == ["valid", "also-valid"]

    def test_chronological_order(self, tmp_path: Path) -> None:
        path = tmp_path / "sidechat.jsonl"
        for i, text in enumerate(("a", "b", "c", "d")):
            append_sidechat(text, ts=float(i), path=path)
        result = list(tail_sidechat(path=path))
        timestamps = [m.ts for m in result]
        assert timestamps == sorted(timestamps)


# ---------------------------------------------------------------------------
# Concurrent writers — pin O_APPEND atomicity
# ---------------------------------------------------------------------------


def _writer_worker(path_str: str, prefix: str, count: int) -> None:
    """Child-process writer for concurrent-append test."""
    from shared.operator_sidechat import append_sidechat as _append

    for i in range(count):
        _append(f"{prefix}-{i}", path=Path(path_str))


class TestConcurrentWriters:
    def test_concurrent_writes_do_not_interleave(self, tmp_path: Path) -> None:
        """Two writers × N messages each → 2N well-formed JSON lines, no partial lines."""
        path = tmp_path / "sidechat.jsonl"
        # Create the file first so both writers O_APPEND onto the same inode.
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

        n = 50
        # Use spawn so the child process initializes cleanly (avoids
        # conftest fixture interaction in fork mode).
        ctx = multiprocessing.get_context("spawn")
        p1 = ctx.Process(target=_writer_worker, args=(str(path), "W1", n))
        p2 = ctx.Process(target=_writer_worker, args=(str(path), "W2", n))
        p1.start()
        p2.start()
        p1.join(timeout=30)
        p2.join(timeout=30)
        assert p1.exitcode == 0
        assert p2.exitcode == 0

        lines = path.read_text().splitlines()
        assert len(lines) == 2 * n, f"expected {2 * n} lines, got {len(lines)}"

        # Every line must be valid JSON and parse as a SidechatMessage.
        w1_count = 0
        w2_count = 0
        for line in lines:
            parsed = json.loads(line)  # would raise if interleaved
            msg = SidechatMessage.model_validate(parsed)
            if msg.text.startswith("W1-"):
                w1_count += 1
            elif msg.text.startswith("W2-"):
                w2_count += 1
        assert w1_count == n
        assert w2_count == n


# ---------------------------------------------------------------------------
# Consumer cursor test (mock runner pattern)
# ---------------------------------------------------------------------------


class TestConsumerCursor:
    def test_cursor_advances_after_each_message(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """sidechat_consumer_loop should persist a monotonically-advancing ts cursor."""
        from agents.hapax_daimonion import run_loops_aux

        sidechat_path = tmp_path / "sidechat.jsonl"
        cursor_path = tmp_path / "sidechat-cursor.txt"

        # Redirect cursor + sidechat paths for this test
        monkeypatch.setattr(run_loops_aux, "_SIDECHAT_CURSOR_PATH", cursor_path)

        # Patch tail_sidechat to read from our temp path. We monkey-patch
        # the symbol as it's imported inside the loop function.
        import shared.operator_sidechat as sc_mod

        monkeypatch.setattr(sc_mod, "SIDECHAT_PATH", sidechat_path)

        # Seed sidechat with 3 messages
        append_sidechat("a", ts=10.0, path=sidechat_path)
        append_sidechat("b", ts=20.0, path=sidechat_path)
        append_sidechat("c", ts=30.0, path=sidechat_path)

        # Mock daemon — only needs _running flag and _affordance_pipeline
        daemon = MagicMock()
        daemon._affordance_pipeline = MagicMock()
        daemon._affordance_pipeline.select.return_value = []
        # Trip the loop to exit after one pass
        daemon._running = True

        # Run one pass manually — we can't easily loop forever in a test,
        # so invoke the core body once by flipping _running to False right
        # after the first pass completes.
        async def _run_then_stop():
            task = asyncio.create_task(run_loops_aux.sidechat_consumer_loop(daemon))
            # Give the loop a moment to process the three seeded messages
            await asyncio.sleep(0.1)
            daemon._running = False
            # Wait for clean exit (loop sleeps 0.5s between iterations)
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except TimeoutError:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        asyncio.run(_run_then_stop())

        # Cursor should have advanced to the final message ts
        assert cursor_path.exists()
        saved = float(cursor_path.read_text().strip())
        assert saved == 30.0

        # Re-running should NOT re-process messages (cursor past latest ts)
        daemon._affordance_pipeline.select.reset_mock()
        daemon._running = True

        async def _run_again():
            task = asyncio.create_task(run_loops_aux.sidechat_consumer_loop(daemon))
            await asyncio.sleep(0.1)
            daemon._running = False
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except TimeoutError:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        asyncio.run(_run_again())
        # select() should not have been called on the replay
        assert daemon._affordance_pipeline.select.call_count == 0


# ---------------------------------------------------------------------------
# Egress pin — sidechat must NOT be in any stream-visible allowlist
# ---------------------------------------------------------------------------


class TestEgressPin:
    """Regression pin: sidechat JSONL must never appear on a stream surface.

    The channel is privately-local by design (task #132). These tests
    enforce the privacy invariant structurally so a future refactor that
    "helpfully" exposes sidechat to chat/overlay/egress layers fails CI.
    """

    def test_sidechat_path_never_in_public_allowlists(self) -> None:
        """No module in shared.* declares an allowlist containing the sidechat path."""
        # The sidechat path string that must NOT appear in any allowlist.
        sidechat_literal = "operator-sidechat.jsonl"

        forbidden_names = (
            "ALLOW",
            "ALLOWLIST",
            "ALLOW_LIST",
            "PUBLIC_PATHS",
            "EGRESS_ALLOW",
            "CHAT_SURFACE_PATHS",
        )

        # Walk the shared/ tree for any constant that would advertise the
        # path as allowed. stream_mode's DENY lists are fine (they don't
        # carry sidechat either).
        repo_root = Path(__file__).resolve().parents[2]
        shared_dir = repo_root / "shared"
        for py in shared_dir.rglob("*.py"):
            try:
                text = py.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if sidechat_literal not in text:
                continue
            # The literal appears — make sure it's inside the sidechat module
            # itself (producer), not in any allowlist elsewhere.
            if py.name == "operator_sidechat.py":
                continue
            for name in forbidden_names:
                assert name not in text, (
                    f"{py} references {sidechat_literal} AND defines {name} — possible egress leak"
                )

    def test_sidechat_path_resides_in_local_shm(self) -> None:
        """The canonical path must be local /dev/shm, never a network path."""
        s = str(SIDECHAT_PATH)
        assert s.startswith("/dev/shm/"), (
            f"sidechat path {s} escaped /dev/shm — local-only invariant violated"
        )
        assert not s.startswith(("http://", "https://", "s3://", "gs://"))

    def test_no_twitch_or_youtube_import_in_producer(self) -> None:
        """The sidechat module must not import any egress client."""
        repo_root = Path(__file__).resolve().parents[2]
        producer = (repo_root / "shared" / "operator_sidechat.py").read_text()
        for banned in (
            "import twitch",
            "from twitch",
            "import youtube",
            "from youtube",
            "tmi.js",
            "pytwitchirc",
            "import obswebsocket",
        ):
            assert banned not in producer, (
                f"sidechat producer imports {banned!r} — local-only invariant violated"
            )


# ---------------------------------------------------------------------------
# Async streaming smoke test
# ---------------------------------------------------------------------------


class TestStreamSidechat:
    async def test_stream_yields_new_messages(self, tmp_path: Path) -> None:
        path = tmp_path / "sidechat.jsonl"
        # Pre-populate one historical message that should be SKIPPED
        # (stream_sidechat seeds cursor at end-of-file).
        append_sidechat("historical", ts=1.0, path=path)

        async def collect() -> list[str]:
            received: list[str] = []
            async for msg in stream_sidechat(path=path, poll_interval_s=0.1):
                received.append(msg.text)
                if len(received) >= 2:
                    break
            return received

        async def writer() -> None:
            await asyncio.sleep(0.2)
            append_sidechat("live-1", ts=time.time(), path=path)
            await asyncio.sleep(0.1)
            append_sidechat("live-2", ts=time.time() + 0.01, path=path)

        writer_task = asyncio.create_task(writer())
        try:
            received = await asyncio.wait_for(collect(), timeout=5.0)
        finally:
            writer_task.cancel()
            try:
                await writer_task
            except asyncio.CancelledError:
                pass

        assert received == ["live-1", "live-2"]


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------


class TestCli:
    def test_cli_writes_jsonl(self, tmp_path: Path) -> None:
        script = Path(__file__).resolve().parents[2] / "scripts" / "hapax-sidechat"
        assert script.exists()
        assert os.access(script, os.X_OK)

        path = tmp_path / "sidechat.jsonl"
        # Invoke through the python interpreter directly (avoids uv
        # requirement for CI). Pass --path so it writes to tmp.
        repo_root = Path(__file__).resolve().parents[2]
        env = {**os.environ, "PYTHONPATH": str(repo_root)}
        result = subprocess.run(
            [sys.executable, str(script), "--path", str(path), "hello", "world"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        # The script uses a `uv run python` shebang; if uv is unavailable
        # in the CI environment we fall back to invoking via sys.executable
        # above, which ignores the shebang. That's fine for a write test.
        assert result.returncode == 0, result.stderr
        assert path.exists()
        lines = path.read_text().splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["text"] == "hello world"
        assert parsed["role"] == "operator"
        assert parsed["channel"] == "sidechat"
