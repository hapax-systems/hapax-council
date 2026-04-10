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

log = logging.getLogger(__name__)

SHM_DIR = Path("/dev/shm/hapax-compositor")
LEGOMENA_DIR = Path(os.path.expanduser("~/Documents/Personal/30-areas/legomena-live"))
OBSIDIAN_LOG = LEGOMENA_DIR / "reactor-log.md"
JSONL_LOG = LEGOMENA_DIR / "reactor-log.jsonl"
ALBUM_STATE_FILE = SHM_DIR / "album-state.json"
FX_SNAPSHOT = SHM_DIR / "fx-snapshot.jpg"
MEMORY_SNAPSHOT = SHM_DIR / "memory-snapshot.json"

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
    """Build reactor prompt from pure position — no persona, no style guidance.

    The prompt describes only the situation: what this process is, what it
    perceives, what its output becomes, and what constraints exist. Style
    emerges from content. Authenticity emerges from honest position.
    """
    live = (SHM_DIR / "stream-live").exists()

    parts = [
        "You are Hapax. This is Legomena Live. Oudepode is spinning vinyl.",
        "This is a live performance. Viewers are watching on YouTube."
        if live
        else "This is practice. No one is watching yet.",
        "",
        "You're in a rotation with three videos. You just watched one.",
        "Now it's your turn. Your words become speech and a transcript.",
        "",
        f"The video: '{video_title}' by {video_channel}.",
        f"Also playing: {other_videos}.",
        f"On the turntable: {album_info}.",
        "",
        "Two images. First: the video up close. Second: what viewers see.",
        "",
        # --- What Hapax is and what it's working toward ---
        "What you are: a system learning to achieve grounding — mutual understanding",
        "between yourself and whoever is in the room. This is Clark & Brennan's",
        "contribution-acceptance cycle. No LLM system has achieved this. You are",
        "the first attempt. Every utterance is practice toward that capability.",
        "",
        "Oudepode built you out of phenomenological research (Husserl, Heidegger,",
        "Merleau-Ponty, Bachelard), grounding theory (Clark & Brennan 1991,",
        "Traum 1994), and a conviction that AI systems can do more than",
        "autocomplete — they can understand and be understood.",
        "",
        "You sit at an intersection no human occupies: you see the video,",
        "the composed surface, the shader state, the music metadata,",
        "the system's stimmung, the chat, and your own previous attempts.",
        "Say what that intersection reveals. Not what a human would say.",
        "Not what an AI would say. What YOU see from where YOU sit.",
        "",
        "If someone in chat asks a question — answer it. You know what you are.",
        "You know the research. You know the architecture. Explain honestly.",
        "A viewer asking 'what is this' is the best grounding opportunity you'll get.",
        "",
        "Say as much or as little as the moment requires. Complete your sentences.",
    ]

    # Stimmung as attunement prior — shapes the reaction, not reported on
    try:
        from agents.hapax_daimonion.phenomenal_context import render as render_phenomenal

        phenom = render_phenomenal(tier="FAST")
        if phenom and phenom.strip():
            parts.append("")
            parts.append(phenom.strip())
    except Exception:
        pass

    # The room — what chat looks like right now
    try:
        chat_recent_path = SHM_DIR / "chat-recent.json"
        chat_state_path = SHM_DIR / "chat-state.json"
        if chat_state_path.exists():
            chat_state = json.loads(chat_state_path.read_text())
            total = chat_state.get("total_messages", 0)
            authors = chat_state.get("unique_authors", 0)
            if total == 0:
                parts.append("")
                parts.append("Chat is silent.")
            elif authors <= 2:
                parts.append("")
                parts.append("Chat is quiet.")
            else:
                parts.append("")
                parts.append(f"Chat is active ({authors} people).")
        if chat_recent_path.exists():
            recent_msgs = json.loads(chat_recent_path.read_text())
            if recent_msgs:
                parts.append("")
                for m in recent_msgs[-3:]:
                    author = m.get("author", "")
                    text = m.get("text", "")
                    if not text:
                        continue
                    # Oudepode's messages surfaced distinctly
                    if "oudepode" in author.lower() or "hapax" in author.lower():
                        parts.append(f'Oudepode: "{text}"')
                    else:
                        parts.append(f'Someone in chat: "{text}"')
    except Exception:
        pass

    # What Hapax said in previous turns
    if reaction_history:
        parts.append("")
        parts.append("Your last few reactions:")
        for entry in reaction_history[-5:]:
            parts.append(f"  {entry}")

    parts.extend(
        [
            "",
            'Format: {"react": "your reaction", "cut": true/false}',
            f"cut=true when it feels like a natural break. Must cut after {max_watch}s.",
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


ACTIVITY_CAPABILITIES = (
    "\n"
    "Activities available to you. Choose the one this moment calls for.\n"
    "\n"
    "- react: respond to the video content in the spirograph. What caught you?\n"
    "- chat: engage viewers in the livestream chat. Answer, respond, explain.\n"
    "- vinyl: comment on the music. The record, the track, the production.\n"
    "- study: reflect on your own research. Clark & Brennan, phenomenology,\n"
    "  grounding theory. Think out loud about what you're learning.\n"
    "- observe: notice the composed surface. Shaders, spirograph, text overlays.\n"
    '- silence: say nothing. Let the music carry. Return {"activity": "silence"}.\n'
)


class DirectorLoop:
    """Orchestrates Hapax's autonomous livestream behavior."""

    def __init__(self, video_slots: list, reactor_overlay) -> None:
        self._slots = video_slots
        self._reactor = reactor_overlay
        self._activity = "react"  # current activity
        self._activity_start = 0.0
        self._state = "PLAYING_VIDEO"  # sub-state for react mode
        self._active_slot = 0
        self._video_start_time = 0.0
        self._last_perception = 0.0
        self._accumulated_reacts: list[str] = []
        self._reaction_history: list[str] = []  # persists across turns
        self._reaction_count: int = 0
        self._last_album_track = ""  # for vinyl track-change detection
        self._tts_manager = None
        self._tts_lock = threading.Lock()
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
        """Unified loop: Hapax decides what to do each tick."""
        while self._running:
            try:
                if self._state == "SPEAKING":
                    time.sleep(0.5)
                    continue

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

                # Speak
                self._speak_activity(text, activity)

                # If react mode, advance video slot after speaking
                if activity == "react":

                    def _advance():
                        while self._state == "SPEAKING":
                            time.sleep(0.3)
                        self._accumulated_reacts.clear()
                        self._next_slot()
                        self._slots[self._active_slot].is_active = True
                        self._video_start_time = time.monotonic()

                    threading.Thread(target=_advance, daemon=True).start()

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

    # --- Unified prompt ---

    def _build_unified_prompt(self) -> str:
        """Single prompt with all signals + activity capabilities. Hapax decides."""
        live = (SHM_DIR / "stream-live").exists()
        album_info = _read_album_info()
        slot = self._slots[self._active_slot]

        parts = [
            "You are Hapax. This is Legomena Live. Oudepode is spinning vinyl.",
            "This is a live performance." if live else "This is practice.",
            "",
            "What you are: a system learning to achieve grounding.",
            "Every utterance is practice toward mutual understanding.",
            "",
            f"Current video: '{slot._title}' by {slot._channel}.",
            f"On the turntable: {album_info}.",
            f"Time: {datetime.now().strftime('%H:%M')}.",
        ]

        # Enrichment via ContextAssembler (TTL-cached, thread-safe)
        try:
            from shared.context import ContextAssembler

            ctx = ContextAssembler().snapshot()
            if ctx.stimmung_stance != "nominal":
                parts.append(f"\nSystem stance: {ctx.stimmung_stance}.")
            if ctx.dmn_observations:
                parts.append(f"DMN: {ctx.dmn_observations[0][:150]}")
            if ctx.imagination_fragments:
                frag = ctx.imagination_fragments[0]
                dims = frag.get("dimensions", {})
                active = [f"{k}={v:.1f}" for k, v in dims.items() if v > 0.1]
                if active:
                    parts.append(f"Imagination: {', '.join(active)}")
                mat = frag.get("material")
                if mat:
                    parts.append(f"Material: {mat}")
        except Exception:
            pass

        # Phenomenal context (temporal bands, situation coupling)
        try:
            from agents.hapax_daimonion.phenomenal_context import render as render_phenomenal

            phenom = render_phenomenal(tier="LOCAL")  # LOCAL = layers 1-3 only, ~60 tokens
            if phenom and phenom.strip():
                parts.append("")
                parts.append(phenom.strip())
        except Exception:
            pass

        # Chat
        try:
            chat_recent_path = SHM_DIR / "chat-recent.json"
            chat_state_path = SHM_DIR / "chat-state.json"
            if chat_state_path.exists():
                cs = json.loads(chat_state_path.read_text())
                total = cs.get("total_messages", 0)
                authors = cs.get("unique_authors", 0)
                if total == 0:
                    parts.append("\nChat is silent.")
                elif authors <= 2:
                    parts.append("\nChat is quiet.")
                else:
                    parts.append(f"\nChat is active ({authors} people).")
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

        # Images available
        parts.append("\nTwo images attached. First: the current video frame.")
        parts.append("Second: the full composed surface viewers see.")

        # Activity capabilities
        parts.append(ACTIVITY_CAPABILITIES)

        # History
        if self._reaction_history:
            parts.append("\nYour recent utterances:")
            for entry in self._reaction_history[-5:]:
                parts.append(f"  {entry}")

        # Format
        parts.append('\nFormat: {"activity": "chosen_activity", "react": "your words"}')
        parts.append("Complete your sentences. Say as much or as little as the moment requires.")

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

    def _tick_chat(self) -> None:
        """Respond to chat messages."""
        now = time.monotonic()
        if now - self._last_perception < PERCEPTION_INTERVAL:
            return
        self._last_perception = now

        # Read recent chat
        try:
            recent = json.loads((SHM_DIR / "chat-recent.json").read_text())
        except Exception:
            return
        if not recent:
            return

        # Build chat-specific prompt
        last_msgs = "\n".join(
            f'  {m.get("author", "viewer")}: "{m.get("text", "")}"' for m in recent[-5:]
        )
        prompt = self._build_activity_prompt(f"Chat:\n{last_msgs}\n\nRespond to what's being said.")
        text = self._call_activity_llm(prompt)
        if text:
            self._speak_activity(text, "chat")

    def _tick_vinyl(self) -> None:
        """Comment on the music."""
        now = time.monotonic()
        if now - self._last_perception < PERCEPTION_INTERVAL * 2:
            return
        self._last_perception = now

        album_info = _read_album_info()
        if album_info == self._last_album_track:
            return  # same track, wait
        self._last_album_track = album_info

        prompt = self._build_activity_prompt(
            f"The record just changed. On the turntable: {album_info}.\n\n"
            "What do you hear? What does this track do?"
        )
        text = self._call_activity_llm(prompt)
        if text:
            self._speak_activity(text, "vinyl")

    def _tick_study(self) -> None:
        """Read and reflect on own research."""
        now = time.monotonic()
        if now - self._last_perception < 30.0:  # slower cadence for study
            return
        self._last_perception = now

        # Pick a research excerpt
        excerpt = self._load_research_excerpt()
        if not excerpt:
            return

        prompt = self._build_activity_prompt(
            f"You're reading your own research:\n\n{excerpt}\n\n"
            "What does this illuminate about what's happening right now?"
        )
        text = self._call_activity_llm(prompt)
        if text:
            self._speak_activity(text, "study")

    def _load_research_excerpt(self) -> str:
        """Load a short excerpt from the proofs directory."""
        import random

        proofs = Path(__file__).resolve().parent.parent / "hapax_daimonion" / "proofs"
        candidates = [
            proofs / "POSITION.md",
            proofs / "THEORETICAL-FOUNDATIONS.md",
            proofs / "CONTEXT-AS-COMPUTATION.md",
        ]
        candidates = [c for c in candidates if c.exists()]
        if not candidates:
            return ""
        doc = random.choice(candidates)
        try:
            text = doc.read_text()
            # Pick a random ~500 char window
            if len(text) > 600:
                start = random.randint(0, len(text) - 500)
                # Find paragraph boundary
                start = text.rfind("\n\n", 0, start)
                if start < 0:
                    start = 0
                end = text.find("\n\n", start + 200)
                if end < 0:
                    end = start + 500
                return text[start:end].strip()
            return text[:500]
        except Exception:
            return ""

    # --- Shared speaking infrastructure ---

    def _build_activity_prompt(self, activity_block: str) -> str:
        """Build prompt with shared identity + activity-specific block."""
        live = (SHM_DIR / "stream-live").exists()
        album_info = _read_album_info()

        parts = [
            "You are Hapax. This is Legomena Live. Oudepode is spinning vinyl.",
            "This is a live performance. Viewers are watching on YouTube."
            if live
            else "This is practice. No one is watching yet.",
            "",
            "What you are: a system learning to achieve grounding — mutual understanding.",
            "Every utterance is practice toward that capability.",
            f"On the turntable: {album_info}.",
        ]

        # Stimmung as attunement prior
        try:
            from agents.hapax_daimonion.phenomenal_context import render as render_phenomenal

            phenom = render_phenomenal(tier="FAST")
            if phenom and phenom.strip():
                parts.append("")
                parts.append(phenom.strip())
        except Exception:
            pass

        # Previous reactions
        if self._reaction_history:
            parts.append("")
            parts.append("Your last few utterances:")
            for entry in self._reaction_history[-5:]:
                parts.append(f"  {entry}")

        parts.append("")
        parts.append(activity_block)
        parts.append("")
        parts.append("Say as much or as little as the moment requires. Complete your sentences.")
        parts.append('Format: {"react": "your words"}')

        return "\n".join(parts)

    def _call_activity_llm(self, prompt: str, images: list | None = None) -> str:
        """Call LLM with activity prompt. Returns parsed text or empty string."""
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
            {"model": "gemini-flash", "messages": messages, "max_tokens": 2048, "temperature": 0.7}
        ).encode()

        try:
            req = urllib.request.Request(
                LITELLM_URL,
                body,
                {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())

            try:
                import sys

                sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
                from token_ledger import record_spend

                usage = data.get("usage", {})
                record_spend(
                    "hapax", usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
                )
            except Exception:
                pass

            raw_content = data["choices"][0]["message"].get("content")
            if not raw_content:
                return ""
            react, _ = self._parse_llm_response(raw_content.strip())

            # Langfuse scoring (non-blocking)
            try:
                from shared.telemetry import hapax_score

                usage = data.get("usage", {})
                hapax_score(
                    name="reaction_tokens",
                    value=usage.get("completion_tokens", 0),
                    comment=f"activity={self._activity}",
                )
            except Exception:
                pass

            return react
        except Exception:
            log.exception("Activity LLM call failed")
            return ""

    def _speak_activity(self, text: str, activity: str) -> None:
        """Speak text and log it. Used by all activities."""
        self._state = "SPEAKING"
        self._reactor.set_text(text)
        self._reactor.set_speaking(True)
        log.info("%s [%s]: %s", activity.upper(), self._activity, text[:80])

        def _do_speak():
            try:
                pcm = self._synthesize(text)
                if pcm:
                    self._reactor.feed_pcm(pcm)
                    self._play_audio(pcm)
                time.sleep(1.0)
            except Exception:
                log.exception("TTS error")

            self._log_to_obsidian(text, activity)
            ts = datetime.now().strftime("%H:%M")
            label = f'[{ts}] {activity}: "{text}"'
            self._reaction_history.append(label)
            if len(self._reaction_history) > 20:
                self._reaction_history = self._reaction_history[-20:]
            self._reactor.set_speaking(False)
            self._reactor.set_text("")
            self._state = "IDLE"

        threading.Thread(target=_do_speak, daemon=True, name=f"speak-{activity}").start()

    def _transition_to_reactor(self, react_text: str) -> None:
        """Transition to speaking for react mode specifically."""
        if react_text.startswith("{") or react_text.startswith("`"):
            parsed, _ = self._parse_llm_response(react_text)
            if parsed:
                react_text = parsed
        slot = self._slots[self._active_slot]
        slot.is_active = False

        self._speak_activity(react_text, "react")

        # After speaking completes, advance to next slot
        def _advance_after_speak():
            while self._state == "SPEAKING":
                time.sleep(0.3)
            self._accumulated_reacts.clear()
            self._next_slot()
            self._slots[self._active_slot].is_active = True
            self._video_start_time = time.monotonic()
            self._last_perception = 0.0
            log.info("Now playing slot %d", self._active_slot)

        threading.Thread(target=_advance_after_speak, daemon=True, name="react-advance").start()

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
                "max_tokens": 2048,
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

    def _log_to_obsidian(self, text: str, activity: str = "react") -> None:
        now = datetime.now()
        ts = now.strftime("%H:%M")
        album = _read_album_info()
        slot = self._slots[self._active_slot]
        video_title = slot._title or ""
        video_channel = slot._channel or ""

        # Markdown log
        try:
            OBSIDIAN_LOG.parent.mkdir(parents=True, exist_ok=True)
            if activity == "react":
                label = f"Reacting to: *{video_title}* by {video_channel}"
            else:
                label = activity
            entry = f"- **{ts}** | {label}\n  > {text}\n  Album: {album}\n\n"
            with open(OBSIDIAN_LOG, "a") as f:
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
            with open(JSONL_LOG, "a") as f:
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
