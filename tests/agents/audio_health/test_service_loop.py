"""Tests for shared audio-health daemon loop helpers."""

from __future__ import annotations

import pytest

from agents.audio_health.service_loop import interruptible_sleep


def test_interruptible_sleep_chunks_long_waits() -> None:
    chunks: list[float] = []

    interruptible_sleep(
        1.2,
        lambda: False,
        sleep_fn=chunks.append,
        max_chunk_s=0.5,
    )

    assert chunks == pytest.approx([0.5, 0.5, 0.2])


def test_interruptible_sleep_stops_after_shutdown_predicate_flips() -> None:
    chunks: list[float] = []
    shutdown = {"stop": False}

    def sleep_fn(seconds: float) -> None:
        chunks.append(seconds)
        shutdown["stop"] = True

    interruptible_sleep(
        300.0,
        lambda: shutdown["stop"],
        sleep_fn=sleep_fn,
        max_chunk_s=0.5,
    )

    assert chunks == [0.5]


def test_interruptible_sleep_does_not_sleep_when_already_shutdown() -> None:
    chunks: list[float] = []

    interruptible_sleep(60.0, lambda: True, sleep_fn=chunks.append)

    assert chunks == []
