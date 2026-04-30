"""Faithful smoke path for live-caption production wiring."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from agents.live_captions.daimonion_bridge import DaimonionCaptionBridge
from agents.live_captions.reader import CaptionReader
from agents.live_captions.routing import RoutedCaptionWriter, RoutingPolicy
from agents.live_captions.writer import CaptionWriter


@dataclass(frozen=True)
class CaptionSmokeResult:
    """Result from the routed writer -> reader smoke flow."""

    ok: bool
    emitted: bool
    observed_events: int
    observed_text: str | None
    audio_start_ts: float
    audio_duration_s: float
    av_offset_s: float
    observed_ts: float | None
    captions_path: str


def run_caption_smoke(
    captions_path: Path,
    *,
    text: str = "ytb-009 caption smoke",
    audio_duration_s: float = 1.2,
    av_offset_s: float = 0.18,
    now_s: float | None = None,
) -> CaptionSmokeResult:
    """Emit one caption through the production bridge shape and read it back.

    The reader is constructed before emit so an existing JSONL backlog is
    ignored, matching the long-lived consumer that tails live captions in
    production. ``observe_av_offset`` is called with a synthetic but
    bounded offset sample to prove timestamp alignment works in the same
    smoke.
    """
    captions_path.parent.mkdir(parents=True, exist_ok=True)
    reader = CaptionReader(captions_path=captions_path)
    bridge = DaimonionCaptionBridge(
        routed_writer=RoutedCaptionWriter(
            policy=RoutingPolicy(),
            writer=CaptionWriter(captions_path=captions_path),
        )
    )

    duration_s = max(0.0, audio_duration_s)
    audio_start_ts = (time.time() if now_s is None else now_s) - duration_s
    reader.observe_av_offset(audio_ts=audio_start_ts, video_ts=audio_start_ts + av_offset_s)

    emitted = bridge.emit_transcription(
        audio_start_ts=audio_start_ts,
        audio_duration_s=duration_s,
        text=text,
    )
    events = list(reader.read_pending())
    observed = events[-1] if events else None
    observed_ts = observed.ts if observed is not None else None
    ok = (
        emitted
        and observed is not None
        and observed.text == text.strip()
        and abs(reader.av_offset_s - av_offset_s) < 1e-6
    )

    return CaptionSmokeResult(
        ok=ok,
        emitted=emitted,
        observed_events=len(events),
        observed_text=observed.text if observed is not None else None,
        audio_start_ts=audio_start_ts,
        audio_duration_s=duration_s,
        av_offset_s=reader.av_offset_s,
        observed_ts=observed_ts,
        captions_path=str(captions_path),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captions-path", type=Path)
    parser.add_argument("--text", default="ytb-009 caption smoke")
    parser.add_argument("--audio-duration-s", type=float, default=1.2)
    parser.add_argument("--av-offset-s", type=float, default=0.18)
    args = parser.parse_args(argv)

    captions_path = args.captions_path
    if captions_path is None:
        captions_path = Path(tempfile.mkdtemp(prefix="hapax-caption-smoke-")) / "live.jsonl"

    result = run_caption_smoke(
        captions_path,
        text=args.text,
        audio_duration_s=args.audio_duration_s,
        av_offset_s=args.av_offset_s,
    )
    print(json.dumps(asdict(result), sort_keys=True))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["CaptionSmokeResult", "main", "run_caption_smoke"]
