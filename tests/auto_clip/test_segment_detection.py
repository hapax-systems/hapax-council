"""Tests for the LLM-assisted segment-detection layer.

The pydantic-ai :class:`Agent` is replaced with a fake whose
``run_sync`` returns deterministic candidates so we never reach a real
LLM. All file-system inputs use ``tmp_path``.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from agents.auto_clip import __main__ as cli
from agents.auto_clip.segment_detection import (
    DecoderChannel,
    LlmSegmentDetector,
    RollingContext,
    SegmentCandidate,
    chat_snapshots_to_dicts,
    read_recent_impingements,
)

# ──────────────────────────────────────────────────────────────────────
# SegmentCandidate validation
# ──────────────────────────────────────────────────────────────────────


def _valid_candidate_kwargs(**overrides) -> dict:
    base = {
        "start_offset_seconds": 30.0,
        "end_offset_seconds": 75.0,
        "resonance": 0.8,
        "decoder_channels": [DecoderChannel.VISUAL, DecoderChannel.LINGUISTIC],
        "rationale": "Reverie shader transition while chronicle voice lands a quotable line.",
        "hook_text": "watch this glyph shimmer",
        "suggested_title": "Reverie + chronicle: 12s of shimmer",
    }
    base.update(overrides)
    return base


def test_valid_segment_candidate_round_trips():
    candidate = SegmentCandidate(**_valid_candidate_kwargs())
    assert candidate.start_offset_seconds == 30.0
    assert candidate.end_offset_seconds == 75.0
    assert DecoderChannel.VISUAL in candidate.decoder_channels


def test_resonance_must_be_in_unit_interval():
    with pytest.raises(ValidationError):
        SegmentCandidate(**_valid_candidate_kwargs(resonance=1.5))
    with pytest.raises(ValidationError):
        SegmentCandidate(**_valid_candidate_kwargs(resonance=-0.1))


def test_end_must_exceed_start():
    with pytest.raises(ValidationError):
        SegmentCandidate(**_valid_candidate_kwargs(start_offset_seconds=60, end_offset_seconds=30))
    # equal start/end is also rejected
    with pytest.raises(ValidationError):
        SegmentCandidate(**_valid_candidate_kwargs(start_offset_seconds=60, end_offset_seconds=60))


def test_decoder_channels_dedupe_preserves_order():
    candidate = SegmentCandidate(
        **_valid_candidate_kwargs(
            decoder_channels=[
                DecoderChannel.VISUAL,
                DecoderChannel.LINGUISTIC,
                DecoderChannel.VISUAL,
                DecoderChannel.SONIC,
            ]
        )
    )
    assert candidate.decoder_channels == [
        DecoderChannel.VISUAL,
        DecoderChannel.LINGUISTIC,
        DecoderChannel.SONIC,
    ]


def test_decoder_channels_must_be_nonempty():
    with pytest.raises(ValidationError):
        SegmentCandidate(**_valid_candidate_kwargs(decoder_channels=[]))


# ──────────────────────────────────────────────────────────────────────
# RollingContext
# ──────────────────────────────────────────────────────────────────────


def test_rolling_context_window_seconds():
    start = datetime(2026, 5, 5, 0, 0, 0, tzinfo=UTC)
    end = start + timedelta(minutes=10)
    ctx = RollingContext(window_start=start, window_end=end)
    assert ctx.window_seconds == 600.0
    assert ctx.transcript_text == ""
    assert ctx.impingements == []
    assert ctx.chat_messages == []


# ──────────────────────────────────────────────────────────────────────
# LlmSegmentDetector — fake-agent injection
# ──────────────────────────────────────────────────────────────────────


def _make_candidates(*resonances: float) -> list[SegmentCandidate]:
    return [
        SegmentCandidate(
            **_valid_candidate_kwargs(
                start_offset_seconds=10.0 * i,
                end_offset_seconds=10.0 * i + 30.0,
                resonance=r,
                suggested_title=f"clip {i}",
            )
        )
        for i, r in enumerate(resonances)
    ]


class _FakeAgent:
    def __init__(self, candidates: list[SegmentCandidate]) -> None:
        self.candidates = candidates
        self.last_prompt: str | None = None

    def run_sync(self, user_prompt: str) -> object:
        self.last_prompt = user_prompt
        return SimpleNamespace(output=list(self.candidates))


def _ctx(now: datetime | None = None) -> RollingContext:
    if now is None:
        now = datetime.now(UTC)
    return RollingContext(window_start=now - timedelta(minutes=10), window_end=now)


def test_detect_returns_candidates_sorted_by_resonance_desc():
    fake = _FakeAgent(_make_candidates(0.4, 0.9, 0.6))
    detector = LlmSegmentDetector(agent=fake)
    out = detector.detect(_ctx())
    assert [c.resonance for c in out] == [0.9, 0.6, 0.4]


def test_detect_clamps_to_max_five_candidates():
    fake = _FakeAgent(_make_candidates(0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.65))
    detector = LlmSegmentDetector(agent=fake)
    out = detector.detect(_ctx())
    assert len(out) == LlmSegmentDetector.MAX_CANDIDATES == 5
    assert [c.resonance for c in out] == [0.95, 0.9, 0.85, 0.8, 0.75]


def test_detect_passes_under_min_through_unchanged_for_caller_inspection():
    # Two-candidate output is below MIN; we don't synthesize fillers,
    # the caller (downstream pipeline) detects the degraded window.
    fake = _FakeAgent(_make_candidates(0.7, 0.5))
    detector = LlmSegmentDetector(agent=fake)
    out = detector.detect(_ctx())
    assert len(out) == 2


def test_detect_renders_window_and_signal_counts_into_prompt():
    fake = _FakeAgent(_make_candidates(0.7, 0.6, 0.5))
    detector = LlmSegmentDetector(agent=fake)
    now = datetime(2026, 5, 5, 12, 0, 0, tzinfo=UTC)
    ctx = RollingContext(
        window_start=now - timedelta(minutes=10),
        window_end=now,
        transcript_text="narrator: a glyph passes through the lattice.",
        impingements=[
            {"kind": "visual.shader_transition", "narrative": "lattice contracts"},
            {"kind": "chat.density_spike", "narrative": "viewers reacting"},
        ],
        chat_messages=[
            {"text": "this is hypnotic", "sentiment": 0.6},
            {"text": "what is this stream", "sentiment": 0.0},
        ],
    )
    detector.detect(ctx)
    assert fake.last_prompt is not None
    assert "WINDOW: 600 seconds" in fake.last_prompt
    assert "TRANSCRIPT:" in fake.last_prompt
    assert "narrator:" in fake.last_prompt
    assert "IMPINGEMENTS (2)" in fake.last_prompt
    assert "lattice contracts" in fake.last_prompt
    assert "CHAT (2)" in fake.last_prompt
    assert "this is hypnotic" in fake.last_prompt


def test_detect_handles_empty_window_gracefully():
    fake = _FakeAgent(_make_candidates(0.5, 0.4, 0.3))
    detector = LlmSegmentDetector(agent=fake)
    detector.detect(_ctx())
    assert fake.last_prompt is not None
    assert "(no transcript captured for this window)" in fake.last_prompt
    assert "(no impingements in this window)" in fake.last_prompt
    assert "(no chat messages in this window)" in fake.last_prompt


# ──────────────────────────────────────────────────────────────────────
# read_recent_impingements
# ──────────────────────────────────────────────────────────────────────


def test_read_recent_impingements_filters_by_window(tmp_path: Path):
    now = datetime(2026, 5, 5, 12, 0, 0, tzinfo=UTC)
    fresh_ts = (now - timedelta(minutes=2)).isoformat()
    stale_ts = (now - timedelta(minutes=30)).isoformat()
    path = tmp_path / "impingements.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"timestamp": fresh_ts, "kind": "fresh"}),
                json.dumps({"timestamp": stale_ts, "kind": "stale"}),
                json.dumps({"kind": "no-timestamp"}),  # kept (no ts → can't filter)
                "not-json",  # skipped
                "",  # skipped
            ]
        ),
        encoding="utf-8",
    )
    out = read_recent_impingements(path=path, window=timedelta(minutes=10), now=now)
    kinds = [e["kind"] for e in out]
    assert "fresh" in kinds
    assert "no-timestamp" in kinds
    assert "stale" not in kinds


def test_read_recent_impingements_missing_file_returns_empty(tmp_path: Path):
    out = read_recent_impingements(
        path=tmp_path / "nonexistent.jsonl",
        window=timedelta(minutes=10),
    )
    assert out == []


# ──────────────────────────────────────────────────────────────────────
# chat_snapshots_to_dicts
# ──────────────────────────────────────────────────────────────────────


def test_chat_snapshots_to_dicts_passes_dicts_through():
    raw = [{"text": "hi", "sentiment": 0.4, "length": 2, "posted_at_unix": 100.0}]
    assert chat_snapshots_to_dicts(raw) == raw


def test_chat_snapshots_to_dicts_extracts_attrs():
    snap = SimpleNamespace(text="hello", sentiment=0.2, length=5, posted_at_unix=42.0)
    out = chat_snapshots_to_dicts([snap])
    assert out == [{"text": "hello", "sentiment": 0.2, "length": 5, "posted_at_unix": 42.0}]


# ──────────────────────────────────────────────────────────────────────
# CLI dry-run smoke
# ──────────────────────────────────────────────────────────────────────


def test_cli_dry_run_emits_json_payload(tmp_path: Path):
    impingements_path = tmp_path / "imp.jsonl"
    impingements_path.write_text("", encoding="utf-8")  # empty but parseable

    fake = _FakeAgent(_make_candidates(0.8, 0.7, 0.6))
    buf = io.StringIO()
    with patch.object(cli, "LlmSegmentDetector", return_value=_DetectorWrapper(fake)):
        with redirect_stdout(buf):
            rc = cli.main(
                [
                    "--dry-run",
                    "--minutes",
                    "10",
                    "--impingements",
                    str(impingements_path),
                ]
            )
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["candidate_count"] == 3
    assert payload["window_seconds"] == 600.0
    assert len(payload["candidates"]) == 3
    assert payload["candidates"][0]["resonance"] == 0.8


def test_cli_requires_dry_run_flag():
    # argparse exits with code 2 on missing required arg
    with pytest.raises(SystemExit) as exc_info:
        cli.main([])
    assert exc_info.value.code == 2


class _DetectorWrapper:
    """Adapter so the CLI's LlmSegmentDetector(model_alias=...) call works.

    Real :class:`LlmSegmentDetector.__init__` accepts ``model_alias`` and
    constructs an Agent. Tests bypass that and inject a fake agent.
    """

    def __init__(self, fake_agent: _FakeAgent) -> None:
        self._inner = LlmSegmentDetector(agent=fake_agent)

    def __call__(self, *args, **kwargs) -> LlmSegmentDetector:
        # When CLI does LlmSegmentDetector(model_alias=...), we ignore
        # the kwargs and return the pre-built fake-agent detector.
        return self._inner

    def detect(self, ctx: RollingContext) -> list[SegmentCandidate]:
        return self._inner.detect(ctx)
