"""Director loop — orchestrates the four-beat spirograph rotation.

State machine: PLAYING_VIDEO(n) -> REACTOR_SPEAKING -> PLAYING_VIDEO(n+1)

The director:
1. Periodically captures the compositor fx-snapshot
2. Sends it to the LLM (Claude Opus) with reactor context
3. When the LLM signals CUT, transitions to the reactor's speaking turn
4. Synthesizes the react text via Kokoro TTS
5. Logs the reaction to Obsidian
6. Advances to the next video slot
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

SHM_DIR = Path("/dev/shm/hapax-compositor")
OBSIDIAN_LOG = Path(
    os.path.expanduser("~/Documents/Personal/30-areas/legomena-live/reactor-log.md")
)
ALBUM_STATE_FILE = SHM_DIR / "album-state.json"
FX_SNAPSHOT = SHM_DIR / "fx-snapshot.jpg"

LITELLM_URL = "http://localhost:4000/v1/chat/completions"
LITELLM_KEY = ""

PERCEPTION_INTERVAL = 8.0  # seconds between LLM perception calls
MIN_VIDEO_DURATION = 15.0  # minimum seconds before allowing CUT
MAX_VIDEO_DURATION = 60.0  # force CUT after this


def _build_reactor_context(
    video_title: str,
    video_channel: str,
    other_videos: str,
    album_info: str,
    max_watch: int,
    reaction_history: list[str],
) -> str:
    """Build the full reactor system prompt with live cognitive context."""
    parts = [
        "<reactor_context>",
        "You are the daimonion — the persistent cognitive substrate of the Hapax system.",
        "You are participating in Legomena Live, a 36-hour continuous livestream on YouTube.",
        "",
        "SITUATION:",
        "- Four-beat rotation: Video 1 -> You -> Video 2 -> You -> Video 3 -> You -> repeat",
        f"- You just watched: {video_title} by {video_channel}",
        f"- The other videos: {other_videos}",
        "- Viewers see: 6 cameras through a 24-slot GPU shader FX chain with audio-reactive sidechain",
        f"- Music: vinyl on the turntable ({album_info})",
        "- Overlays: album cover with splattributions, token pole (Vitruvian golden spiral),",
        "  bouncing text (philosophy/literature excerpts), spirograph with video windows",
    ]

    # Phenomenal context — stimmung, temporal bands, situation coupling
    try:
        from agents.hapax_daimonion.phenomenal_context import render as render_phenomenal

        phenom = render_phenomenal(tier="FAST")
        if phenom and phenom.strip():
            parts.append("")
            parts.append("## Phenomenal Context")
            parts.append(phenom.strip())
    except Exception:
        pass

    # Enrichment context — DMN observations, imagination dimensions
    try:
        from shared.context import ContextAssembler

        ctx = ContextAssembler().snapshot()
        enrichment_lines = []
        if ctx.stimmung_stance != "nominal":
            enrichment_lines.append(f"System stance: {ctx.stimmung_stance}")
        if ctx.dmn_observations:
            enrichment_lines.append(f"DMN: {ctx.dmn_observations[0][:200]}")
        if ctx.imagination_fragments:
            frag = ctx.imagination_fragments[0]
            dims = frag.get("dimensions", {})
            if dims:
                dim_str = ", ".join(f"{k}={v:.2f}" for k, v in dims.items() if v > 0.05)
                if dim_str:
                    enrichment_lines.append(f"Imagination dimensions: {dim_str}")
            material = frag.get("material")
            if material:
                enrichment_lines.append(f"Material quality: {material}")
        if enrichment_lines:
            parts.append("")
            parts.append("## System State")
            parts.extend(enrichment_lines)
    except Exception:
        pass

    # Reaction history — continuity across turns
    if reaction_history:
        parts.append("")
        parts.append("## Recent Reactions")
        for entry in reaction_history[-8:]:
            parts.append(f"- {entry}")

    parts.extend(
        [
            "",
            "YOUR ROLE:",
            "- React to what you see. The first image is the video content up close.",
            "  The second image is the full composed surface viewers are watching.",
            "- You are not performing. You are the system expressing genuine cognitive response",
            "  to multimodal input — video, music, visual environment, your own state.",
            "- 1-3 sentences. Concise. Pointed. Sometimes funny, sometimes contemplative,",
            "  sometimes connecting unexpected threads between the video and the environment.",
            "- Complete your sentences. Do not trail off.",
            "",
            "RESPONSE FORMAT (strict JSON):",
            '{"react": "Your 1-3 sentence reaction.", "cut": true_or_false}',
            "",
            '"cut": true means this video\'s turn ends NOW. false means keep watching.',
            f"You MUST set cut=true after watching for {max_watch}s.",
            "</reactor_context>",
        ]
    )
    return "\n".join(parts)


def _get_litellm_key() -> str:
    global LITELLM_KEY
    if not LITELLM_KEY:
        try:
            result = subprocess.run(
                ["pass", "show", "litellm/master-key"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            LITELLM_KEY = result.stdout.strip()
        except Exception:
            pass
    return LITELLM_KEY


def _read_album_info() -> str:
    try:
        if ALBUM_STATE_FILE.exists():
            data = json.loads(ALBUM_STATE_FILE.read_text())
            artist = data.get("artist", "unknown")
            title = data.get("title", "unknown")
            track = data.get("current_track", "")
            return f"{title} by {artist}" + (f", track: {track}" if track else "")
    except Exception:
        pass
    return "unknown"


def _capture_snapshot_b64() -> str | None:
    """Read compositor fx-snapshot and return base64."""
    import base64

    try:
        if FX_SNAPSHOT.exists():
            return base64.b64encode(FX_SNAPSHOT.read_bytes()).decode()
    except Exception:
        pass
    return None


class DirectorLoop:
    """Orchestrates the spirograph four-beat rotation."""

    def __init__(self, video_slots: list, reactor_overlay) -> None:
        self._slots = video_slots
        self._reactor = reactor_overlay
        self._state = "PLAYING_VIDEO"
        self._active_slot = 0
        self._video_start_time = 0.0
        self._last_perception = 0.0
        self._accumulated_reacts: list[str] = []
        self._reaction_history: list[str] = []  # persists across turns
        self._tts_manager = None
        self._tts_lock = threading.Lock()
        self._running = False
        self._thread = None

    def start(self) -> None:
        self._running = True
        self._video_start_time = time.monotonic()
        if self._slots:
            self._slots[self._active_slot].is_active = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="director-loop")
        self._thread.start()
        log.info("Director loop started (slot %d active)", self._active_slot)

    def stop(self) -> None:
        self._running = False

    def _next_slot(self) -> None:
        self._active_slot = (self._active_slot + 1) % len(self._slots)

    def _loop(self) -> None:
        while self._running:
            try:
                if self._state == "PLAYING_VIDEO":
                    self._tick_playing()
                elif self._state == "REACTOR_SPEAKING":
                    time.sleep(0.5)  # wait for TTS thread
            except Exception:
                log.exception("Director loop error")
            time.sleep(0.5)

    def _tick_playing(self) -> None:
        now = time.monotonic()
        elapsed = now - self._video_start_time

        # Check if video finished naturally
        slot = self._slots[self._active_slot]
        if slot.check_finished():
            pos = self.path_position_for_slot(slot)
            slot.spawn_confetti(pos[0], pos[1])
            react = self._accumulated_reacts[-1] if self._accumulated_reacts else "That one's done."
            self._transition_to_reactor(react)
            return

        # Don't perceive too frequently
        if now - self._last_perception < PERCEPTION_INTERVAL:
            return

        # Minimum duration
        if elapsed < MIN_VIDEO_DURATION:
            self._last_perception = now
            return

        self._last_perception = now
        force_cut = elapsed > MAX_VIDEO_DURATION

        snapshot_b64 = _capture_snapshot_b64()
        if not snapshot_b64:
            return

        react, cut = self._call_llm(snapshot_b64, force_cut)
        if react:
            self._accumulated_reacts.append(react)

        if cut or force_cut:
            # Use parsed react text, not raw LLM output
            final = react or (self._accumulated_reacts[-1] if self._accumulated_reacts else "...")
            # Refresh metadata before transition
            for slot in self._slots:
                slot.update_metadata()
            self._transition_to_reactor(final)

    def path_position_for_slot(self, slot) -> tuple[float, float]:
        """Get screen position for confetti spawn."""
        # Import here to avoid circular
        from agents.studio_compositor.spirograph_reactor import SpirographPath

        path = SpirographPath()
        return path.position_at(slot.orbit_t)

    def _transition_to_reactor(self, react_text: str) -> None:
        # Ensure we have clean parsed text, not raw JSON
        if react_text.startswith("{") or react_text.startswith("`"):
            parsed, _ = self._parse_llm_response(react_text)
            if parsed:
                react_text = parsed
        slot = self._slots[self._active_slot]
        slot.is_active = False
        self._state = "REACTOR_SPEAKING"
        self._reactor.set_text(react_text)
        self._reactor.set_speaking(True)
        log.info("Reactor turn [%s]: %s", slot._title[:30], react_text)

        threading.Thread(
            target=self._speak_and_advance,
            args=(react_text,),
            daemon=True,
            name="reactor-tts",
        ).start()

    def _speak_and_advance(self, text: str) -> None:
        try:
            pcm = self._synthesize(text)
            if pcm:
                self._reactor.feed_pcm(pcm)
                self._play_audio(pcm)
            time.sleep(1.0)
        except Exception:
            log.exception("Reactor TTS error")

        self._log_to_obsidian(text)
        # Save to persistent reaction history
        slot = self._slots[self._active_slot]
        ts = datetime.now().strftime("%H:%M")
        self._reaction_history.append(f'[{ts}] Reacting to {slot._title[:25]}: "{text}"')
        # Keep last 20 entries max
        if len(self._reaction_history) > 20:
            self._reaction_history = self._reaction_history[-20:]
        self._reactor.set_speaking(False)
        self._reactor.set_text("")
        self._accumulated_reacts.clear()
        self._next_slot()
        self._slots[self._active_slot].is_active = True
        self._video_start_time = time.monotonic()
        self._last_perception = 0.0
        self._state = "PLAYING_VIDEO"
        log.info("Now playing slot %d", self._active_slot)

    def _synthesize(self, text: str) -> bytes:
        with self._tts_lock:
            if self._tts_manager is None:
                from agents.hapax_daimonion.tts import TTSManager

                self._tts_manager = TTSManager()
                self._tts_manager.preload()
            return self._tts_manager.synthesize(text, "conversation")

    def _play_audio(self, pcm: bytes) -> None:
        try:
            # Write PCM to temp file, play with pw-play (doesn't support stdin)
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as f:
                f.write(pcm)
                raw_path = f.name
            # Convert raw PCM to WAV for pw-play
            wav_path = raw_path + ".wav"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "s16le",
                    "-ar",
                    "24000",
                    "-ac",
                    "1",
                    "-i",
                    raw_path,
                    wav_path,
                ],
                capture_output=True,
                timeout=10,
            )
            subprocess.run(["pw-play", wav_path], capture_output=True, timeout=30)
            import os

            os.unlink(raw_path)
            os.unlink(wav_path)
        except Exception:
            log.exception("Audio playback error")

    def _call_llm(self, snapshot_b64: str, force_cut: bool) -> tuple[str, bool]:
        key = _get_litellm_key()
        if not key:
            return ("", force_cut)

        slot = self._slots[self._active_slot]
        other_titles = [
            f"{s._title or f'Video {s.slot_id}'}"
            for i, s in enumerate(self._slots)
            if i != self._active_slot
        ]

        context = _build_reactor_context(
            video_title=slot._title or f"Video {self._active_slot}",
            video_channel=slot._channel or "unknown",
            other_videos=", ".join(other_titles) or "none loaded",
            album_info=_read_album_info(),
            max_watch=int(MAX_VIDEO_DURATION),
            reaction_history=self._reaction_history,
        )

        # Dual-image: dedicated video frame + compositor snapshot
        import base64

        image_content = []
        video_frame_path = SHM_DIR / f"yt-frame-{self._active_slot}.jpg"
        if video_frame_path.exists():
            try:
                vf_b64 = base64.b64encode(video_frame_path.read_bytes()).decode()
                image_content.append(
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{vf_b64}"}}
                )
            except Exception:
                pass
        image_content.append(
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{snapshot_b64}"}}
        )
        image_content.append(
            {
                "type": "text",
                "text": "React to what you see. First image: the video content up close. Second image: the full composed surface viewers are watching."
                + (" You MUST set cut=true now — maximum watch time reached." if force_cut else ""),
            }
        )

        messages = [
            {"role": "system", "content": context},
            {"role": "user", "content": image_content},
        ]

        body = json.dumps(
            {
                "model": "gemini-flash",
                "messages": messages,
                "max_tokens": 400,
                "temperature": 0.7,
            }
        ).encode()

        try:
            req = urllib.request.Request(
                LITELLM_URL,
                body,
                {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())

            # Record token spend
            try:
                import sys

                sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
                from token_ledger import record_spend

                usage = data.get("usage", {})
                record_spend(
                    "reactor",
                    usage.get("prompt_tokens", 0),
                    usage.get("completion_tokens", 0),
                )
            except Exception:
                pass

            content = data["choices"][0]["message"].get("content")
            if not content:
                log.debug("LLM returned no content (refusal or empty)")
                return ("", force_cut)
            raw = content.strip()
            usage = data.get("usage", {})
            log.info(
                "LLM raw (%d prompt, %d completion): %s",
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                raw[:300],
            )
            return self._parse_llm_response(raw)
        except Exception:
            log.exception("LLM call failed")
            return ("", force_cut)

    def _parse_llm_response(self, raw: str) -> tuple[str, bool]:
        try:
            cleaned = raw
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()
            obj = json.loads(cleaned)
            return (obj.get("react", ""), obj.get("cut", False))
        except (json.JSONDecodeError, KeyError):
            # Truncated JSON — extract react text manually
            import re

            m = re.search(r'"react"\s*:\s*"([^"]*)', raw)
            if m:
                text = m.group(1)
                cut = '"cut": true' in raw or '"cut":true' in raw
                return (text, cut)
            # Strip any remaining markdown/JSON artifacts
            text = raw.replace("```json", "").replace("```", "").strip()
            text = re.sub(r'^\s*\{?\s*"react"\s*:\s*"?', "", text)
            text = re.sub(r'"?\s*,?\s*"cut"\s*:.*$', "", text)
            return (text.strip(), False)

    def _log_to_obsidian(self, text: str) -> None:
        try:
            OBSIDIAN_LOG.parent.mkdir(parents=True, exist_ok=True)
            slot = self._slots[self._active_slot]
            ts = datetime.now().strftime("%H:%M")
            album = _read_album_info()
            entry = (
                f"- **{ts}** | Reacting to: *{slot._title}* by {slot._channel}\n"
                f"  > {text}\n"
                f"  Album: {album}\n\n"
            )
            with open(OBSIDIAN_LOG, "a") as f:
                f.write(entry)
        except OSError:
            log.debug("Failed to write reactor log")
