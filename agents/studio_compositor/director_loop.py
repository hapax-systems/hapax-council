"""Director loop — orchestrates Hapax's autonomous livestream behavior.

Hapax chooses what to do based on signals: react to videos, engage chat,
comment on music, study its own research, or be silent. The activity
selector scores each possibility every tick and picks the best one.
The spirograph, videos, and shader effects run continuously regardless
of which activity is active.
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

from agents.studio_compositor.audio_control import SlotAudioControl

log = logging.getLogger(__name__)

SHM_DIR = Path("/dev/shm/hapax-compositor")
LEGOMENA_DIR = Path(os.path.expanduser("~/Documents/Personal/30-areas/legomena-live"))
ALBUM_STATE_FILE = SHM_DIR / "album-state.json"
FX_SNAPSHOT = SHM_DIR / "fx-snapshot.jpg"
MEMORY_SNAPSHOT = SHM_DIR / "memory-snapshot.json"


def _obsidian_log_path(now: datetime | None = None) -> Path:
    """Monthly-rotated markdown log: reactor-log-YYYY-MM.md."""
    now = now or datetime.now()
    return LEGOMENA_DIR / f"reactor-log-{now.strftime('%Y-%m')}.md"


def _jsonl_log_path(now: datetime | None = None) -> Path:
    """Monthly-rotated JSONL log: reactor-log-YYYY-MM.jsonl."""
    now = now or datetime.now()
    return LEGOMENA_DIR / f"reactor-log-{now.strftime('%Y-%m')}.jsonl"


LITELLM_URL = "http://localhost:4000/v1/chat/completions"
LITELLM_KEY = ""

PERCEPTION_INTERVAL = 8.0  # seconds between LLM perception calls
MIN_VIDEO_DURATION = 15.0  # minimum seconds before allowing CUT
MAX_VIDEO_DURATION = 60.0  # force CUT after this


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


ACTIVITY_CAPABILITIES = (
    "\n"
    "Activities available to you. Choose the one this moment calls for.\n"
    "\n"
    "- react: respond to the video content in the triangle display. What caught you?\n"
    "- chat: engage viewers in the livestream chat. Answer, respond, explain.\n"
    "- vinyl: comment on the music. The record, the track, the production.\n"
    "- study: reflect on your own research. Clark & Brennan, phenomenology,\n"
    "  grounding theory. Think out loud about what you're learning.\n"
    "- observe: notice the composed surface. Shaders, triangle layout, visual effects.\n"
    '- silence: say nothing. Let the music carry. Return {"activity": "silence"}.\n'
)


class DirectorLoop:
    """Orchestrates Hapax's autonomous livestream behavior."""

    def __init__(self, video_slots: list, reactor_overlay) -> None:
        self._slots = video_slots
        self._reactor = reactor_overlay
        self._activity = "react"  # current activity
        self._activity_start = 0.0
        self._state = "IDLE"
        self._active_slot = 0
        self._video_start_time = 0.0
        self._last_perception = 0.0
        self._accumulated_reacts: list[str] = []
        self._reaction_history: list[str] = []  # persists across turns
        self._reaction_count: int = 0
        self._last_album_track = ""  # for vinyl track-change detection
        self._tts_manager = None
        self._tts_lock = threading.Lock()
        self._transition_lock = threading.Lock()
        self._audio_control: SlotAudioControl | None = None
        self._running = False
        self._thread = None
        self._load_memory()

    def _load_memory(self) -> None:
        """Load reaction history from SHM snapshot or Qdrant on startup."""
        # Try SHM warm-start first (fast)
        try:
            if MEMORY_SNAPSHOT.exists():
                data = json.loads(MEMORY_SNAPSHOT.read_text())
                if time.time() - data.get("timestamp", 0) < 3600:  # < 1 hour old
                    self._reaction_history = data.get("reaction_history", [])
                    self._reaction_count = data.get("reaction_count", 0)
                    log.info("Loaded %d reactions from SHM snapshot", len(self._reaction_history))
                    return
        except Exception:
            pass

        # Fall back to Qdrant (slower but survives reboots)
        try:
            from shared.config import get_qdrant

            client = get_qdrant()
            collections = [c.name for c in client.get_collections().collections]
            if "stream-reactions" in collections:
                results = client.scroll(
                    collection_name="stream-reactions",
                    limit=20,
                    with_payload=True,
                    with_vectors=False,
                )[0]
                # Sort by timestamp descending, take last 20
                results.sort(key=lambda r: r.payload.get("timestamp", 0), reverse=True)
                self._reaction_history = [
                    f"[{r.payload.get('ts_str', '?')}] {r.payload.get('activity', 'react')}: "
                    f'"{r.payload.get("text", "")}"'
                    for r in results[:20]
                ]
                self._reaction_history.reverse()  # chronological order
                self._reaction_count = len(results)
                log.info("Loaded %d reactions from Qdrant", len(self._reaction_history))
        except Exception:
            log.debug("No Qdrant memory available (first run or Qdrant down)")

    def _reload_slot_from_playlist(self, slot_id: int) -> None:
        """Load a random video from the playlist into the given slot."""
        try:
            playlist_path = SHM_DIR / "playlist.json"
            if not playlist_path.exists():
                return
            playlist = json.loads(playlist_path.read_text())
            if not playlist:
                return
            import random

            pick = random.choice(playlist)
            url = pick["url"]
            body = json.dumps({"url": url}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:8055/slot/{slot_id}/play",
                body,
                {"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=90)
            log.info("Slot %d reloaded from playlist: %s", slot_id, pick["title"][:40])
        except Exception:
            log.debug("Playlist reload failed for slot %d", slot_id)

    def _save_memory_snapshot(self) -> None:
        """Snapshot reaction history to SHM for fast restart."""
        try:
            MEMORY_SNAPSHOT.write_text(
                json.dumps(
                    {
                        "timestamp": time.time(),
                        "reaction_history": self._reaction_history[-20:],
                        "reaction_count": self._reaction_count,
                    }
                )
            )
        except OSError:
            pass

    def start(self) -> None:
        self._running = True
        self._video_start_time = time.monotonic()
        self._audio_control = SlotAudioControl(slot_count=len(self._slots))
        if self._slots:
            self._slots[self._active_slot].is_active = True
            self._audio_control.mute_all_except(self._active_slot)
        self._thread = threading.Thread(target=self._loop, daemon=True, name="director-loop")
        self._thread.start()
        self._dispatch_cold_starts()
        log.info("Director loop started (slot %d active)", self._active_slot)

    def _slots_needing_cold_start(self) -> list[int]:
        """Slot IDs whose yt-frame-N.jpg is absent — candidates for bootstrapping."""
        return [
            s.slot_id for s in self._slots if not (SHM_DIR / f"yt-frame-{s.slot_id}.jpg").exists()
        ]

    def _dispatch_cold_starts(self) -> list[int]:
        """Kick off playlist reloads for slots missing a frame file.

        Without this, restarting youtube-player.service leaves the Sierpinski
        corners blank until a human manually POSTs /slot/N/play — observed
        2026-04-12 as a 13h outage. Returns the dispatched slot IDs.
        """
        missing = self._slots_needing_cold_start()
        for slot_id in missing:
            log.warning("Cold-starting slot %d (no frame file)", slot_id)
            threading.Thread(
                target=self._reload_slot_from_playlist,
                args=(slot_id,),
                daemon=True,
                name=f"cold-start-slot-{slot_id}",
            ).start()
        return missing

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        """Unified loop: Hapax decides what to do each tick."""
        while self._running:
            try:
                if self._state == "SPEAKING":
                    time.sleep(0.5)
                    continue

                # Check for finished videos — reload from playlist
                for s in self._slots:
                    if s.check_finished():
                        log.info("Slot %d finished, reloading from playlist", s.slot_id)
                        threading.Thread(
                            target=self._reload_slot_from_playlist,
                            args=(s.slot_id,),
                            daemon=True,
                        ).start()

                now = time.monotonic()
                if now - self._last_perception < PERCEPTION_INTERVAL:
                    time.sleep(0.5)
                    continue
                self._last_perception = now

                # Build unified prompt with all signals + activity capabilities
                prompt = self._build_unified_prompt()
                images = self._gather_images()

                # Single LLM call — Hapax chooses activity + content
                result = self._call_activity_llm(prompt, images)
                if not result:
                    time.sleep(1.0)
                    continue

                # Parse activity choice
                activity = "react"
                text = result
                try:
                    obj = json.loads(result) if result.startswith("{") else None
                    if obj:
                        activity = obj.get("activity", "react")
                        text = obj.get("react", "")
                except (json.JSONDecodeError, TypeError):
                    pass

                # Handle activity
                if activity == "silence" or not text:
                    if self._activity != "silence":
                        log.info("Activity: silence")
                        self._activity = activity
                        self._reactor.set_header("SILENCE")
                    time.sleep(5.0)
                    continue

                if activity != self._activity:
                    log.info("Activity: %s → %s", self._activity, activity)
                    self._activity = activity
                    self._reactor.set_header(activity.upper())

                # Speak — speech + slot advance happen in one thread
                self._speak_activity(text, activity)

            except Exception:
                log.exception("Director loop error")
            time.sleep(0.5)

    def _build_unified_prompt(self) -> str:
        """Assemble 4-layer reactor context per enrichment spec.

        Layers: situation block, phenomenal context (FAST tier ~200 tok),
        system state (TOON ~150 tok), recent reactions (last 8 ~120 tok).
        Total budget ~1,020 tokens. Spec:
        docs/superpowers/specs/2026-04-10-reactor-context-enrichment-design.md
        """
        live = (SHM_DIR / "stream-live").exists()
        album_info = _read_album_info()
        slot = self._slots[self._active_slot]

        parts: list[str] = ["<reactor_context>"]

        # ─── Identity + situation ─────────────────────────────────
        parts.append(
            "You are the daimonion — the persistent cognitive substrate of the Hapax system."
        )
        parts.append("This is Legomena Live. Oudepode is spinning vinyl.")
        parts.append("This is a live performance." if live else "This is practice.")
        parts.append("What you are: a system learning to achieve grounding.")
        parts.append("Every utterance is practice toward mutual understanding.")
        parts.append("")
        parts.append(f"Current video: '{slot._title}' by {slot._channel}.")
        other_titles = ", ".join(
            s._title[:30] for s in self._slots if s.slot_id != self._active_slot and s._title
        )
        if other_titles:
            parts.append(f"Also in rotation: {other_titles}.")
        parts.append(f"On the turntable: {album_info}.")
        parts.append(f"Time: {datetime.now().strftime('%H:%M')}.")

        # ─── Chat state ───────────────────────────────────────────
        try:
            chat_recent_path = SHM_DIR / "chat-recent.json"
            chat_state_path = SHM_DIR / "chat-state.json"
            if chat_state_path.exists():
                cs = json.loads(chat_state_path.read_text())
                total = cs.get("total_messages", 0)
                authors = cs.get("unique_authors", 0)
                if total == 0:
                    parts.append("Chat is silent.")
                elif authors <= 2:
                    parts.append("Chat is quiet.")
                else:
                    parts.append(f"Chat is active ({authors} people).")
            if chat_recent_path.exists():
                recent = json.loads(chat_recent_path.read_text())
                for m in recent[-3:]:
                    author = m.get("author", "")
                    text = m.get("text", "")
                    if text:
                        if "oudepode" in author.lower():
                            parts.append(f'Oudepode: "{text}"')
                        else:
                            parts.append(f'Someone in chat: "{text}"')
        except Exception:
            pass

        # ─── Layer 1: Phenomenal context (FAST tier ~200 tokens) ──
        try:
            from agents.hapax_daimonion.phenomenal_context import render as render_phenomenal

            phenom = render_phenomenal(tier="FAST")
            if phenom and phenom.strip():
                parts.append("")
                parts.append("## Phenomenal Context")
                parts.append(phenom.strip())
        except Exception:
            pass

        # ─── Layer 2: System state (TOON ~150 tokens, 40% savings) ─
        try:
            from shared.context import ContextAssembler
            from shared.context_compression import to_toon

            ctx = ContextAssembler().snapshot()
            toon_block = to_toon(ctx)
            if toon_block and toon_block != "null":
                parts.append("")
                parts.append("## System State")
                parts.append(toon_block)
        except Exception:
            pass

        # ─── Layer 3: Recent reactions (last 8, timestamped thread) ─
        if self._reaction_history:
            parts.append("")
            parts.append("## Recent Reactions")
            for entry in self._reaction_history[-8:]:
                parts.append(f"- {entry}")

        # ─── Role + response format ───────────────────────────────
        parts.append("")
        parts.append("## Your Role")
        parts.append(ACTIVITY_CAPABILITIES)
        parts.append("")
        parts.append("## Images")
        parts.append("Two images attached. First: the current video frame.")
        parts.append("Second: the full composed surface viewers see.")
        parts.append("")
        parts.append("## Response Format")
        parts.append('{"activity": "chosen_activity", "react": "your words"}')
        parts.append("Complete your sentences. Say as much or as little as the moment requires.")
        parts.append("</reactor_context>")

        return "\n".join(parts)

    def _gather_images(self) -> list[str]:
        """Collect image paths for the LLM call."""
        images = []
        # Video frame
        vf = SHM_DIR / f"yt-frame-{self._active_slot}.jpg"
        if vf.exists():
            images.append(str(vf))
        # Compositor snapshot
        if FX_SNAPSHOT.exists():
            images.append(str(FX_SNAPSHOT))
        return images

    # --- Legacy activity tick methods (kept for reference, not called) ---

    def _compute_coherence(self, react_text: str) -> float | None:
        """Cosine similarity of reaction against (video_title + album + chat context).

        Returns None if embedding fails. Higher = reaction tracks its context.
        """
        try:
            import math

            from shared.config import embed

            slot = self._slots[self._active_slot]
            album = _read_album_info()
            chat_snippet = ""
            try:
                chat_path = SHM_DIR / "chat-recent.json"
                if chat_path.exists():
                    recent = json.loads(chat_path.read_text())
                    chat_snippet = " ".join(m.get("text", "") for m in recent[-3:])
            except Exception:
                pass

            context_text = " | ".join(
                p for p in [slot._title or "", slot._channel or "", album, chat_snippet] if p
            )
            if not context_text or not react_text:
                return None

            v_react = embed(react_text)
            v_context = embed(context_text)
            if not v_react or not v_context:
                return None

            dot = sum(a * b for a, b in zip(v_react, v_context, strict=False))
            norm_r = math.sqrt(sum(a * a for a in v_react))
            norm_c = math.sqrt(sum(a * a for a in v_context))
            if norm_r == 0 or norm_c == 0:
                return None
            return dot / (norm_r * norm_c)
        except Exception:
            log.debug("Coherence computation failed", exc_info=True)
            return None

    def _call_activity_llm(self, prompt: str, images: list | None = None) -> str:
        """Call LLM with activity prompt. Returns parsed text or empty string.

        Wrapped in hapax_span("stream", "reaction") so per-reaction scores
        (tokens, coherence, activity) are tagged with stream-experiment.
        """
        key = _get_litellm_key()
        if not key:
            return ""

        content: list[dict] = []
        if images:
            import base64

            for img_path in images:
                try:
                    if Path(img_path).exists():
                        b64 = base64.b64encode(Path(img_path).read_bytes()).decode()
                        content.append(
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                            }
                        )
                except Exception:
                    pass
        content.append({"type": "text", "text": "Respond."})

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": content},
        ]

        body = json.dumps(
            {
                "model": "claude-opus",
                "messages": messages,
                "max_tokens": 300,
                "temperature": 0.7,
            }
        ).encode()

        try:
            from shared.telemetry import hapax_score, hapax_span
        except ImportError:
            hapax_span = None  # type: ignore[assignment]
            hapax_score = None  # type: ignore[assignment]

        # Context manager for Langfuse span — yields None if telemetry unavailable.
        from contextlib import nullcontext

        span_ctx = (
            hapax_span(
                "stream",
                "reaction",
                tags=["stream-experiment"],
                metadata={"activity": self._activity, "slot": self._active_slot},
            )
            if hapax_span is not None
            else nullcontext(None)
        )

        try:
            with span_ctx as span:
                req = urllib.request.Request(
                    LITELLM_URL,
                    body,
                    {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read())

                try:
                    import sys

                    sys.path.insert(
                        0, str(Path(__file__).resolve().parent.parent.parent / "scripts")
                    )
                    from token_ledger import record_spend

                    usage = data.get("usage", {})
                    record_spend(
                        "hapax",
                        usage.get("prompt_tokens", 0),
                        usage.get("completion_tokens", 0),
                    )
                except Exception:
                    pass

                raw_content = data["choices"][0]["message"].get("content")
                if not raw_content:
                    return ""
                react, _ = self._parse_llm_response(raw_content.strip())

                # Langfuse per-reaction scoring (spec: stream research infra).
                if hapax_score is not None and span is not None:
                    usage = data.get("usage", {})
                    hapax_score(
                        span,
                        "reaction_tokens",
                        float(usage.get("completion_tokens", 0)),
                        comment=f"activity={self._activity}",
                    )
                    coherence = self._compute_coherence(react)
                    if coherence is not None:
                        hapax_score(
                            span,
                            "reaction_coherence",
                            coherence,
                            comment=f"activity={self._activity}",
                        )
                    # Activity as a categorical score: map to {0,1} per activity
                    hapax_score(
                        span,
                        "reaction_activity",
                        1.0,
                        comment=self._activity,
                    )

                return react
        except Exception:
            log.exception("Activity LLM call failed")
            return ""

    def _speak_activity(self, text: str, activity: str) -> None:
        """Speak text, then advance slot if reacting. Single thread, locked."""
        self._state = "SPEAKING"
        self._reactor.set_text(text)
        self._reactor.set_speaking(True)
        log.info("%s [%s]: %s", activity.upper(), self._activity, text[:80])

        def _do_speak_and_advance():
            with self._transition_lock:
                try:
                    pcm = self._synthesize(text)
                    if pcm:
                        if self._audio_control:
                            self._audio_control.mute_all()
                        self._reactor.feed_pcm(pcm)
                        self._play_audio(pcm)
                        time.sleep(0.3)
                except Exception:
                    log.exception("TTS error")

                # Advance slot atomically (react mode only)
                if activity == "react":
                    self._slots[self._active_slot].is_active = False
                    self._accumulated_reacts.clear()
                    self._active_slot = (self._active_slot + 1) % len(self._slots)
                    self._slots[self._active_slot].is_active = True
                    self._video_start_time = time.monotonic()
                    self._last_perception = 0.0
                    log.info("Now playing slot %d", self._active_slot)

                # Restore audio on new active slot
                if self._audio_control:
                    self._audio_control.mute_all_except(self._active_slot)

                # Bookkeeping
                self._log_to_obsidian(text, activity)
                ts = datetime.now().strftime("%H:%M")
                label = f'[{ts}] {activity}: "{text}"'
                self._reaction_history.append(label)
                if len(self._reaction_history) > 20:
                    self._reaction_history = self._reaction_history[-20:]
                self._reactor.set_speaking(False)
                self._reactor.set_text("")
                self._state = "IDLE"

        threading.Thread(
            target=_do_speak_and_advance, daemon=True, name=f"speak-{activity}"
        ).start()

    def _synthesize(self, text: str) -> bytes:
        with self._tts_lock:
            if self._tts_manager is None:
                from agents.hapax_daimonion.tts import TTSManager

                self._tts_manager = TTSManager()
                self._tts_manager.preload()
            return self._tts_manager.synthesize(text, "conversation")

    def _play_audio(self, pcm: bytes) -> None:
        """Play PCM using persistent pw-cat subprocess targeting assistant sink."""
        try:
            if not hasattr(self, "_audio_output") or self._audio_output is None:
                from agents.hapax_daimonion.pw_audio_output import PwAudioOutput

                self._audio_output = PwAudioOutput(
                    sample_rate=24000,
                    channels=1,
                    target="input.loopback.sink.role.assistant",
                )
            self._audio_output.write(pcm)
        except Exception:
            log.exception("Audio playback error")

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

    def _log_to_obsidian(self, text: str, activity: str = "react") -> None:
        now = datetime.now()
        ts = now.strftime("%H:%M")
        album = _read_album_info()
        slot = self._slots[self._active_slot]
        video_title = slot._title or ""
        video_channel = slot._channel or ""

        # Markdown log (monthly rotation)
        obsidian_log = _obsidian_log_path(now)
        try:
            obsidian_log.parent.mkdir(parents=True, exist_ok=True)
            if activity == "react":
                label = f"Reacting to: *{video_title}* by {video_channel}"
            else:
                label = activity
            entry = f"- **{ts}** | {label}\n  > {text}\n  Album: {album}\n\n"
            with open(obsidian_log, "a") as f:
                f.write(entry)
        except OSError:
            pass

        # JSONL structured log
        self._reaction_count += 1
        record = {
            "ts": now.isoformat(),
            "ts_str": ts,
            "reaction_index": self._reaction_count,
            "activity": activity,
            "text": text,
            "tokens": len(text.split()),
            "video_title": video_title,
            "video_channel": video_channel,
            "album": album,
            "stimmung": "nominal",
        }
        try:
            stimmung_path = Path("/dev/shm/hapax-stimmung/state.json")
            if stimmung_path.exists():
                st = json.loads(stimmung_path.read_text())
                record["stimmung"] = st.get("overall_stance", "nominal")
        except Exception:
            pass
        try:
            cs_path = SHM_DIR / "chat-state.json"
            if cs_path.exists():
                cs = json.loads(cs_path.read_text())
                record["chat_authors"] = cs.get("unique_authors", 0)
                record["chat_messages"] = cs.get("total_messages", 0)
        except Exception:
            pass

        try:
            with open(_jsonl_log_path(now), "a") as f:
                f.write(json.dumps(record) + "\n")
        except OSError:
            pass

        # Qdrant persistence (async — don't block the reactor)
        def _persist_to_qdrant():
            try:
                from qdrant_client.models import Distance, PointStruct, VectorParams

                from shared.config import embed, get_qdrant

                client = get_qdrant()
                # Ensure collection exists
                collections = [c.name for c in client.get_collections().collections]
                if "stream-reactions" not in collections:
                    client.create_collection(
                        collection_name="stream-reactions",
                        vectors_config=VectorParams(size=768, distance=Distance.COSINE),
                    )
                    log.info("Created stream-reactions Qdrant collection")

                embed_text = f"{activity}: {text[:200]} | {video_title} | {album}"
                vector = embed(embed_text)
                if vector:
                    import uuid

                    client.upsert(
                        collection_name="stream-reactions",
                        points=[
                            PointStruct(
                                id=str(uuid.uuid4()),
                                vector=vector,
                                payload=record,
                            )
                        ],
                    )
            except Exception:
                log.debug("Qdrant persistence failed (non-fatal)", exc_info=True)

        threading.Thread(target=_persist_to_qdrant, daemon=True, name="qdrant-persist").start()

        # SHM memory snapshot (periodic — every 5 reactions)
        if self._reaction_count % 5 == 0:
            self._save_memory_snapshot()
