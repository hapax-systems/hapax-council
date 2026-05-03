"""Sierpinski content loader — publishes local visual-pool frames.

Replaces the legacy ContentTextureManager/slots.json path. Selects
broadcast-safe local frame assets from ``~/hapax-pool/visual/`` by
aesthetic tag and content-risk ceiling, then injects them into the wgpu
content source protocol via ``content_injector``.

The Sierpinski triangle shader (``sierpinski_content.wgsl``) handles
the triangle-region masking and compositing on the GPU side. This
loader is the data pipeline.

Active slot opacity is higher (0.9) than inactive slots (0.3). Slot
ordering via ``z_order`` so the active slot sorts highest and the
shader binds it first.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from agents.visual_pool.repository import (
    DEFAULT_MAX_CONTENT_RISK,
    DEFAULT_SIERPINSKI_TAGS,
    LocalVisualPoolSelector,
    VisualPoolAsset,
)
from shared.affordance import ContentRisk
from shared.content_source_provenance_egress import (
    EgressManifestGate,
    build_broadcast_manifest,
    read_music_provenance_asset,
    write_broadcast_manifest,
)

log = logging.getLogger(__name__)

# Number of visual slots the loader manages. One slot matches the current
# live Sierpinski surface. Re-expanding later is a one-number change plus
# shader/director policy alignment.
VIDEO_SLOT_COUNT: int = 1


class VisualPoolSlotStub:
    """Minimal stub matching the fields DirectorLoop reads from video slots."""

    externally_managed_frames = True

    def __init__(self, slot_id: int, selector: LocalVisualPoolSelector) -> None:
        self.slot_id = slot_id
        self._selector = selector
        self._asset: VisualPoolAsset | None = None
        self._title = ""
        self._channel = ""
        self.is_active = False

    @property
    def current_frame_path(self) -> Path | None:
        asset = self.current_asset()
        return asset.path if asset is not None else None

    def current_asset(self) -> VisualPoolAsset | None:
        asset = self._selector.select(self.slot_id)
        if asset is not None:
            self._asset = asset
            self._title = asset.metadata.title or asset.path.stem
            self._channel = asset.metadata.source
        return self._asset

    def check_finished(self) -> bool:
        """Local pool frames are static frame sources; nothing auto-reloads."""
        return False

    def update_metadata(self) -> None:
        """Refresh title/source from the selected local pool sidecar."""
        self.current_asset()


class SierpinskiLoader:
    """Publishes local visual-pool frames to the wgpu content source protocol.

    Each slot becomes a named source at
    ``/dev/shm/hapax-imagination/sources/visual-pool-slot-{N}/``. Sources are
    refreshed every 0.4s. Active slot gets higher opacity and z_order so the
    shader binds it prominently.
    """

    def __init__(
        self,
        *,
        pool_root: Path | str | None = None,
        aesthetic_tags: list[str] | tuple[str, ...] = DEFAULT_SIERPINSKI_TAGS,
        max_content_risk: ContentRisk = DEFAULT_MAX_CONTENT_RISK,
    ) -> None:
        self._running = False
        self._thread: threading.Thread | None = None
        self._active_slot = 0
        self._selector = LocalVisualPoolSelector(
            root=pool_root,
            aesthetic_tags=aesthetic_tags,
            max_content_risk=max_content_risk,
        )
        self._egress_gate = EgressManifestGate(producer_id="studio_compositor.sierpinski_loader")
        self.video_slots = [VisualPoolSlotStub(i, self._selector) for i in range(VIDEO_SLOT_COUNT)]

    def start(self) -> None:
        """Start the frame polling thread and deferred director initialization."""
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="sierpinski-loader"
        )
        self._thread.start()
        # Start director loop after a delay (youtube-player needs time to start ffmpeg)
        threading.Thread(
            target=self._start_director, daemon=True, name="sierpinski-director-init"
        ).start()
        log.info("SierpinskiLoader started")

    def _start_director(self) -> None:
        """Deferred director loop startup — waits briefly for local frames."""
        # Wait for at least one local visual-pool frame to validate.
        for _ in range(30):
            if any(slot.current_frame_path is not None for slot in self.video_slots):
                break
            time.sleep(1)
        try:
            for slot in self.video_slots:
                slot.update_metadata()

            from agents.studio_compositor.director_loop import DirectorLoop
            from agents.studio_compositor.programme_context import (
                default_provider as programme_provider,
            )

            self._director = DirectorLoop(
                video_slots=self.video_slots,
                reactor_overlay=self,
                programme_provider=programme_provider,
            )
            self._director.start()
            log.info("DirectorLoop started via SierpinskiLoader")
        except Exception:
            log.exception("DirectorLoop startup failed")

        # Phase 5c: twitch (4s deterministic) + structural (150s LLM) directors
        # run alongside narrative. Enable via env flags so operator can disable
        # if either introduces an issue during rehearsal. Defaults ON for
        # post-epic behavior.
        if os.environ.get("HAPAX_TWITCH_DIRECTOR_ENABLED", "1").lower() not in {
            "0",
            "false",
            "off",
            "no",
        }:
            try:
                from agents.studio_compositor.twitch_director import TwitchDirector

                self._twitch_director = TwitchDirector()
                self._twitch_director.start()
                log.info("TwitchDirector started (4s cadence)")
            except Exception:
                log.exception("TwitchDirector startup failed")
        if os.environ.get("HAPAX_STRUCTURAL_DIRECTOR_ENABLED", "1").lower() not in {
            "0",
            "false",
            "off",
            "no",
        }:
            try:
                from agents.studio_compositor.programme_context import (
                    default_provider as programme_provider,
                )
                from agents.studio_compositor.structural_director import StructuralDirector

                self._structural_director = StructuralDirector(
                    programme_provider=programme_provider,
                )
                self._structural_director.start()
                log.info("StructuralDirector started (150s cadence)")
            except Exception:
                log.exception("StructuralDirector startup failed")

    def stop(self) -> None:
        self._running = False

    def set_active_slot(self, slot_id: int) -> None:
        """Called by director loop when active slot changes."""
        self._active_slot = slot_id

    # --- ReactorOverlay compatibility (director loop calls these) ---

    def set_header(self, header: str) -> None:
        pass

    def set_text(self, text: str) -> None:
        pass

    def set_speaking(self, speaking: bool) -> None:
        pass

    def feed_pcm(self, pcm_bytes: bytes) -> None:
        pass

    def _poll_loop(self) -> None:
        """Poll local visual-pool selections and publish them as content sources."""
        from agents.reverie.content_injector import inject_jpeg, remove_source

        while self._running:
            try:
                self._publish_sources(inject_jpeg, remove_source)
            except Exception:
                log.debug("Source publish failed", exc_info=True)
            time.sleep(0.4)

    def _publish_sources(self, inject_jpeg, remove_source) -> None:
        """Publish each local visual-pool slot as a source via content_injector.

        Active slot gets opacity 0.9 and z_order 5 (highest among local slots).
        Inactive slots get opacity 0.3 and z_order 2-4.
        Slots without a valid local pool asset get their source removed.
        """
        slot_assets = []
        visual_manifest_assets = []
        for slot in self.video_slots:
            slot_id = slot.slot_id
            asset = slot.current_asset()
            source_id = f"visual-pool-slot-{slot_id}"
            if asset is None or not asset.path.exists():
                slot_assets.append((slot, source_id, None))
                continue
            slot_assets.append((slot, source_id, asset))
            visual_manifest_assets.append(asset.to_broadcast_manifest_asset(source_id=source_id))

        audio_asset = read_music_provenance_asset()
        manifest = build_broadcast_manifest(
            audio_assets=(audio_asset,) if audio_asset is not None else (),
            visual_assets=visual_manifest_assets,
        )
        write_broadcast_manifest(manifest, self._egress_gate.manifest_path)
        decision = self._egress_gate.tick(manifest)
        kill_active = bool(decision and decision.kill_switch_fired)

        for slot, source_id, asset in slot_assets:
            if asset is None:
                remove_source(source_id)
                continue
            if kill_active:
                remove_source(source_id)
                log.warning(
                    "egress manifest gate active; removing visual pool source %s",
                    source_id,
                )
                continue
            slot_id = slot.slot_id
            is_active = slot_id == self._active_slot
            opacity = 0.9 if is_active else 0.3
            z_order = 5 if is_active else (2 + slot_id)
            inject_jpeg(
                source_id=source_id,
                jpeg_path=asset.path,
                opacity=opacity,
                z_order=z_order,
                blend_mode="over",
                tags=[
                    "local-visual-pool",
                    "sierpinski",
                    asset.metadata.content_risk,
                    *asset.metadata.aesthetic_tags,
                ],
            )
