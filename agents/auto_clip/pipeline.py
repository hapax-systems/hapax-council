"""Auto-clip pipeline orchestrator: detect, extract, render, gate, dispatch."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agents.auto_clip.clip_extractor import ExtractedClip, extract_clip
from agents.auto_clip.clip_renderer import RenderedClip, render_clip
from agents.auto_clip.platform_dispatch import (
    ClipMetadata,
    Platform,
    UploadResult,
    dispatch_clip,
)
from agents.auto_clip.provenance_gate import GateResult, check_clip
from agents.auto_clip.segment_detection import (
    LlmSegmentDetector,
    RollingContext,
    SegmentCandidate,
)

log = logging.getLogger(__name__)

try:
    from prometheus_client import Counter

    CLIPS_POSTED = Counter(
        "hapax_auto_clip_shorts_posted_total",
        "Total Shorts posted per channel per platform",
        ["channel", "platform"],
    )
    CLIPS_FAILED = Counter(
        "hapax_auto_clip_shorts_failed_total",
        "Total Shorts that failed at any pipeline stage",
        ["stage"],
    )
except ImportError:
    CLIPS_POSTED = None  # type: ignore[assignment]
    CLIPS_FAILED = None  # type: ignore[assignment]

PAUSE_FILE = Path.home() / "hapax-state" / "auto-clip" / "pause.md"
OUTPUT_DIR = Path.home() / "hapax-state" / "auto-clip" / "clips"
LEDGER_DIR = Path.home() / "hapax-state" / "auto-clip" / "ledger"
RESONANCE_THRESHOLD = 0.5


@dataclass
class ClipResult:
    clip_id: str
    candidate: SegmentCandidate
    extracted: ExtractedClip | None = None
    rendered: RenderedClip | None = None
    gate: GateResult | None = None
    uploads: list[UploadResult] = field(default_factory=list)
    stage_failed: str | None = None


def is_paused() -> bool:
    return PAUSE_FILE.is_file()


def _record_failure(stage: str) -> None:
    if CLIPS_FAILED is not None:
        CLIPS_FAILED.labels(stage=stage).inc()


def _record_success(channel: str, platform: str) -> None:
    if CLIPS_POSTED is not None:
        CLIPS_POSTED.labels(channel=channel, platform=platform).inc()


def _write_ledger_entry(result: ClipResult) -> None:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "clip_id": result.clip_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "candidate": result.candidate.model_dump(mode="json"),
        "stage_failed": result.stage_failed,
        "uploads": [
            {"platform": u.platform, "success": u.success, "url": u.url, "error": u.error}
            for u in result.uploads
        ],
    }
    path = LEDGER_DIR / f"{result.clip_id}.json"
    path.write_text(json.dumps(entry, indent=2), encoding="utf-8")


def process_candidate(
    candidate: SegmentCandidate,
    window_start: datetime,
    *,
    output_dir: Path | None = None,
    archive_path: Path | None = None,
    dry_run: bool = False,
    platforms: list[Platform] | None = None,
) -> ClipResult:
    out_dir = output_dir or OUTPUT_DIR
    clip_id = f"clip-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    result = ClipResult(clip_id=clip_id, candidate=candidate)

    extracted = extract_clip(
        window_start=window_start,
        start_offset=candidate.start_offset_seconds,
        end_offset=candidate.end_offset_seconds,
        output_dir=out_dir,
        clip_id=clip_id,
        archive_path=archive_path,
    )
    if extracted is None:
        result.stage_failed = "extract"
        _record_failure("extract")
        return result
    result.extracted = extracted

    primary_channel = candidate.decoder_channels[0]
    rendered = render_clip(
        raw_clip=extracted.path,
        output_dir=out_dir,
        clip_id=clip_id,
        hook_text=candidate.hook_text,
        decoder_channel=primary_channel,
        suggested_title=candidate.suggested_title,
    )
    if rendered is None:
        result.stage_failed = "render"
        _record_failure("render")
        return result
    result.rendered = rendered

    description = candidate.rationale
    gate = check_clip(
        clip_path=rendered.path,
        title=candidate.suggested_title,
        description=description,
        source_segments=extracted.source_segments,
    )
    result.gate = gate
    if not gate.passed:
        result.stage_failed = "provenance_gate"
        _record_failure("provenance_gate")
        return result

    if dry_run:
        log.info("Dry run: would dispatch %s", clip_id)
        return result

    metadata = ClipMetadata(
        title=candidate.suggested_title,
        description=description,
        decoder_channel=primary_channel.value,
        tags=["hapax", "ambient", primary_channel.value, "shorts", "autoclip"],
        clip_id=clip_id,
    )
    uploads = dispatch_clip(rendered.path, metadata, platforms=platforms)
    result.uploads = uploads

    for u in uploads:
        if u.success:
            _record_success(primary_channel.value, u.platform.value)
        else:
            _record_failure(f"upload_{u.platform.value}")

    return result


def run_pipeline(
    *,
    minutes: float = 10.0,
    model_alias: str = "balanced",
    dry_run: bool = False,
    archive_path: Path | None = None,
    output_dir: Path | None = None,
    platforms: list[Platform] | None = None,
    context: RollingContext | None = None,
) -> list[ClipResult]:
    if is_paused():
        log.info("Pipeline is paused via %s", PAUSE_FILE)
        return []

    now = datetime.now(UTC)
    if context is None:
        context = RollingContext(
            window_start=now - timedelta(minutes=minutes),
            window_end=now,
        )

    detector = LlmSegmentDetector(model_alias=model_alias)
    candidates = detector.detect(context)

    viable = [c for c in candidates if c.resonance >= RESONANCE_THRESHOLD]
    if not viable:
        log.info("No candidates above resonance threshold %.2f", RESONANCE_THRESHOLD)
        return []

    results: list[ClipResult] = []
    for candidate in viable:
        result = process_candidate(
            candidate,
            context.window_start,
            output_dir=output_dir,
            archive_path=archive_path,
            dry_run=dry_run,
            platforms=platforms,
        )
        _write_ledger_entry(result)
        results.append(result)

    return results
