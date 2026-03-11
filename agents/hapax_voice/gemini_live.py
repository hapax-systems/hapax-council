"""Gemini Live API client for speech-to-speech conversation."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class GeminiLiveConfig:
    """Configuration for Gemini Live session."""

    model: str = "gemini-2.5-flash-preview-native-audio"
    system_prompt: str = ""


class GeminiLiveSession:
    """WebSocket session with Gemini Live for speech-to-speech conversation.

    Manages a persistent connection to the Gemini Live API for
    bidirectional audio streaming. The session lifecycle is managed
    by the daemon — connect at session start, close at session end.
    """

    def __init__(self, model: str, system_prompt: str) -> None:
        self.model = model
        self.system_prompt = system_prompt
        self._session = None
        self._client = None
        self._receive_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._receive_task: asyncio.Task | None = None

    @property
    def is_connected(self) -> bool:
        """Whether the WebSocket session is active."""
        return self._session is not None

    async def connect(self) -> None:
        """Connect to Gemini Live API via WebSocket."""
        api_key = os.environ.get("GOOGLE_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            log.error("GOOGLE_API_KEY / GEMINI_API_KEY not set — cannot connect to Gemini Live")
            return

        try:
            from google import genai  # type: ignore[import-untyped]
            from google.genai import types  # type: ignore[import-untyped]

            self._client = genai.Client(api_key=api_key)

            config = types.LiveConnectConfig(
                response_modalities=["AUDIO"],
                system_instruction=self.system_prompt or None,
            )

            log.info("Connecting to Gemini Live (model=%s)", self.model)
            session = await self._client.aio.live.connect(
                model=self.model,
                config=config,
            ).__aenter__()
            self._session = session
            self._receive_task = asyncio.create_task(self._receive_loop())
            log.info("Gemini Live session connected")
        except ImportError:
            log.error(
                "google-genai not installed — cannot use Gemini Live. "
                "Install with: uv pip install google-genai"
            )
        except Exception:
            log.exception("Failed to connect to Gemini Live")
            self._session = None

    async def disconnect(self) -> None:
        """Close the WebSocket session."""
        if self._receive_task is not None:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                log.exception("Error closing Gemini Live session")
            finally:
                self._session = None
                log.info("Gemini Live session disconnected")

        # Drain the receive queue
        while not self._receive_queue.empty():
            try:
                self._receive_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def send_audio(self, audio_chunk: bytes) -> None:
        """Send an audio chunk to Gemini Live.

        Args:
            audio_chunk: Raw PCM audio bytes (16kHz, 16-bit, mono).
        """
        if not self.is_connected:
            log.warning("Cannot send audio — not connected")
            return

        try:
            from google.genai import types  # type: ignore[import-untyped]

            await self._session.send_realtime_input(
                media=types.Blob(data=audio_chunk, mime_type="audio/pcm;rate=16000")
            )
            log.debug("Sent %d bytes of audio", len(audio_chunk))
        except Exception:
            log.exception("Error sending audio to Gemini Live")

    async def receive_audio(self) -> bytes | None:
        """Receive audio response from Gemini Live.

        Returns:
            Audio bytes if available, None otherwise.
        """
        if not self.is_connected:
            return None

        try:
            return self._receive_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def _receive_loop(self) -> None:
        """Background task that reads from the session and enqueues audio."""
        try:
            async for msg in self._session.receive():
                if msg.server_content and msg.server_content.model_turn:
                    for part in msg.server_content.model_turn.parts:
                        if part.inline_data and part.inline_data.data:
                            await self._receive_queue.put(part.inline_data.data)
                # If the server signals turn complete, we can continue
                # listening for the next turn.
                if msg.server_content and msg.server_content.turn_complete:
                    log.debug("Gemini Live turn complete")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Gemini Live receive loop error")
