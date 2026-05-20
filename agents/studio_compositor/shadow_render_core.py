"""Clock-owned render core running in private shadow mode.

Implements step 2 of the livestream render architecture shadow plan:
a 30fps clock that produces frame manifests without blocking on any
source. Disabled by default (HAPAX_RENDER_CORE_SHADOW=0).

Spec: docs/superpowers/specs/2026-05-10-livestream-render-architecture-shadow-plan.md
Contract: config/livestream-render-architecture-shadow-plan.yaml
"""

from __future__ import annotations

import json
import logging
import os
import signal as _signal
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

log = logging.getLogger(__name__)

SHADOW_OUTPUT_DIR = Path("/dev/shm/hapax-compositor/render-shadow")
TARGET_FPS = 30
FRAME_BUDGET_US = 1_000_000 // TARGET_FPS
STALE_THRESHOLD_S = 2.0


class SourceHealth(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    OFFLINE = "offline"


class SourceClass(StrEnum):
    CAMERA = "camera"
    WARD = "ward"
    SHADER = "shader"
    SLATE = "slate"


@dataclass(frozen=True)
class SourceContribution:
    source_id: str
    source_class: SourceClass
    health: SourceHealth
    width: int
    height: int
    colorspace: str = "rgba"
    last_update_ns: int = 0


@dataclass
class FrameManifest:
    sequence: int
    timestamp_ns: int
    render_cost_us: int
    sources: list[SourceContribution] = field(default_factory=list)
    degraded_sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "sequence": self.sequence,
            "timestamp_ns": self.timestamp_ns,
            "render_cost_us": self.render_cost_us,
            "source_count": len(self.sources),
            "degraded_count": len(self.degraded_sources),
            "degraded_sources": self.degraded_sources,
            "sources": [
                {
                    "source_id": s.source_id,
                    "source_class": s.source_class.value,
                    "health": s.health.value,
                    "width": s.width,
                    "height": s.height,
                    "colorspace": s.colorspace,
                }
                for s in self.sources
            ],
        }


class ShadowRenderCore:
    """30fps clock-owned render core for private shadow mode.

    The clock runs unconditionally — no source, ward, shader, or egress
    adapter may block the frame cadence. Missing or stale sources degrade
    within STALE_THRESHOLD_S to offline status.
    """

    def __init__(
        self,
        *,
        output_dir: Path | None = None,
        target_fps: int = TARGET_FPS,
    ) -> None:
        self._output_dir = output_dir or SHADOW_OUTPUT_DIR
        self._target_fps = max(1, target_fps)
        self._frame_interval = 1.0 / self._target_fps
        self._sequence = 0
        self._stop = threading.Event()
        self._sources: dict[str, SourceContribution] = {}
        self._lock = threading.Lock()

    @property
    def sequence(self) -> int:
        return self._sequence

    @property
    def is_running(self) -> bool:
        return not self._stop.is_set()

    def register_source(self, contribution: SourceContribution) -> None:
        with self._lock:
            self._sources[contribution.source_id] = contribution

    def update_source(self, source_id: str, *, timestamp_ns: int) -> None:
        with self._lock:
            if source_id in self._sources:
                old = self._sources[source_id]
                self._sources[source_id] = SourceContribution(
                    source_id=old.source_id,
                    source_class=old.source_class,
                    health=SourceHealth.FRESH,
                    width=old.width,
                    height=old.height,
                    colorspace=old.colorspace,
                    last_update_ns=timestamp_ns,
                )

    def run(self) -> None:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        log.info(
            "shadow render core started: %dfps, output=%s",
            self._target_fps,
            self._output_dir,
        )

        while not self._stop.is_set():
            frame_start = time.monotonic_ns()
            manifest = self._produce_frame(frame_start)
            self._write_manifest(manifest)
            frame_end = time.monotonic_ns()

            render_us = (frame_end - frame_start) // 1000
            sleep_s = self._frame_interval - (render_us / 1_000_000)
            if sleep_s > 0:
                self._stop.wait(sleep_s)

        log.info("shadow render core stopped at sequence %d", self._sequence)

    def stop(self) -> None:
        self._stop.set()

    def _produce_frame(self, now_ns: int) -> FrameManifest:
        self._sequence += 1
        start_us = time.monotonic_ns() // 1000

        with self._lock:
            sources = list(self._sources.values())

        evaluated: list[SourceContribution] = []
        degraded: list[str] = []

        for src in sources:
            if src.last_update_ns == 0:
                health = SourceHealth.OFFLINE
            elif (now_ns - src.last_update_ns) > int(STALE_THRESHOLD_S * 1e9):
                health = SourceHealth.STALE
            else:
                health = src.health

            if health != SourceHealth.FRESH:
                degraded.append(src.source_id)
                evaluated.append(
                    SourceContribution(
                        source_id=src.source_id,
                        source_class=src.source_class,
                        health=health,
                        width=src.width,
                        height=src.height,
                        colorspace=src.colorspace,
                        last_update_ns=src.last_update_ns,
                    )
                )
            else:
                evaluated.append(src)

        end_us = time.monotonic_ns() // 1000
        return FrameManifest(
            sequence=self._sequence,
            timestamp_ns=now_ns,
            render_cost_us=end_us - start_us,
            sources=evaluated,
            degraded_sources=degraded,
        )

    def _write_manifest(self, manifest: FrameManifest) -> None:
        manifest_path = self._output_dir / "manifest.json"
        try:
            manifest_path.write_text(json.dumps(manifest.to_dict()))
        except OSError:
            log.debug("failed to write shadow manifest", exc_info=True)


def shadow_enabled() -> bool:
    return os.environ.get("HAPAX_RENDER_CORE_SHADOW", "0") == "1"


def run_shadow_render_core() -> None:
    if not shadow_enabled():
        log.info("shadow render core disabled (HAPAX_RENDER_CORE_SHADOW != 1)")
        return

    core = ShadowRenderCore()
    for sig in (_signal.SIGTERM, _signal.SIGINT):
        try:
            _signal.signal(sig, lambda *_: core.stop())
        except ValueError:
            pass

    core.run()


__all__ = [
    "FrameManifest",
    "ShadowRenderCore",
    "SourceClass",
    "SourceContribution",
    "SourceHealth",
    "run_shadow_render_core",
    "shadow_enabled",
]
