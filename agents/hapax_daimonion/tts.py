"""Tiered TTS abstraction — backend selected via ``HAPAX_TTS_BACKEND``.

Backend selection is versioned code: ``HAPAX_TTS_BACKEND`` (``chatterbox`` |
``kokoro``, read at :class:`TTSManager` construction) picks the primary
engine; the systemd drop-in that sets it lives at
``systemd/units/hapax-daimonion.service.d/tts-backend.conf``. Invalid or
unset values resolve to ``chatterbox``, which itself falls back to Kokoro
when the model cannot load or a synthesis call fails. The engine that
actually produced the most recent PCM is exposed as
:attr:`TTSManager.last_synthesis_backend` for the voice-output witness.

Every TTS call passes through :func:`shared.speech_safety.censor` before
synthesis — this is the canonical fail-closed slur gate. The voice is
raw material for S-4 self-modulation; voice identity lives in the S-4's
transformation, not in the TTS model's output.

Chatterbox (classic ``ChatterboxTTS``, 350M, GPU): voice cloned from
non-human reference audio (processed Kokoro output with shifted formants).
Paralinguistic tags ([whisper], [breath], [gasp]) used as timbral
variation points for S-4 granular processing, not as emotions. The Turbo
class swap rides the torch>=2.9+cu128 keystone (Phase 1 of
CASE-VOICE-FOUNDATION-20260610); until then sm_120 cards have no kernels
and Chatterbox fails to load.

Kokoro 82M (CPU): selectable primary or automatic fallback.

``HAPAX_TTS_TRANSPORT`` selects where synthesis runs. ``local`` keeps the
model in-process; ``server`` makes :class:`TTSManager` a synchronous client
for the podium-local TTS engine UDS. The daimonion service uses ``server`` so
daemon restarts do not reload TTS models; the engine service uses ``local``.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import time
from pathlib import Path
from typing import Any

import numpy as np

from shared.speech_lexicon import apply_lexicon as _speech_lexicon_apply
from shared.speech_safety import censor as _speech_safety_censor

log = logging.getLogger(__name__)

_TIER_MAP: dict[str, str] = {
    "conversation": "chatterbox",
    "notification": "chatterbox",
    "briefing": "chatterbox",
    "proactive": "chatterbox",
}

TTS_SAMPLE_RATE = 24000

TTS_BACKEND_ENV = "HAPAX_TTS_BACKEND"
VALID_TTS_BACKENDS: tuple[str, ...] = ("chatterbox", "kokoro")
_DEFAULT_TTS_BACKEND = "chatterbox"

TTS_TRANSPORT_ENV = "HAPAX_TTS_TRANSPORT"
VALID_TTS_TRANSPORTS: tuple[str, ...] = ("local", "server")
_DEFAULT_TTS_TRANSPORT = "local"
TTS_SERVER_SOCKET_ENV = "HAPAX_TTS_SERVER_SOCKET"
TTS_REQUEST_DEADLINE_ENV = "HAPAX_TTS_REQUEST_DEADLINE_S"
TTS_STREAM_PROTOCOL = "hapax.tts.pcm-stream.v1"
_DEFAULT_TTS_REQUEST_DEADLINE_S = 30.0
_TTS_CLIENT_TIMEOUT_OVERHEAD_S = 2.0

_VOICE_SAMPLE_PATH = Path(__file__).resolve().parent.parent.parent / "profiles" / "voice-sample.wav"
_CHATTERBOX_DEVICE = os.environ.get("HAPAX_CHATTERBOX_DEVICE", "cuda:0")
_CHATTERBOX_EXAGGERATION = 0.50
_CHATTERBOX_CFG_WEIGHT = 0.3
_INTERVIEW_EXAGGERATION = 0.20
_INTERVIEW_CFG_WEIGHT = 0.50


# Expressiveness gained from arc open (0.0) to arc peak (1.0). Small + bounded
# so delivery stays natural — this is a continuous controller of prosody, not a
# per-beat preset table.
_ARC_EXAGGERATION_GAIN = 0.15


class _SocketBuffer:
    """Small buffered reader for line headers plus exact PCM frame bodies."""

    def __init__(self, sock: socket.socket, initial: bytes = b"") -> None:
        self._sock = sock
        self._buf = bytearray(initial)

    def read_line(self, *, max_bytes: int = 64 * 1024) -> bytes:
        while True:
            idx = self._buf.find(b"\n")
            if idx >= 0:
                line = bytes(self._buf[:idx])
                del self._buf[: idx + 1]
                return line
            if len(self._buf) > max_bytes:
                raise RuntimeError("tts server line exceeded 64 KiB")
            chunk = self._sock.recv(4096)
            if not chunk:
                raise EOFError("tts server closed before line")
            self._buf.extend(chunk)

    def read_exact(self, size: int) -> bytes:
        out = bytearray()
        while len(out) < size:
            if self._buf:
                take = min(size - len(out), len(self._buf))
                out.extend(self._buf[:take])
                del self._buf[:take]
                continue
            chunk = self._sock.recv(min(65536, size - len(out)))
            if not chunk:
                raise EOFError("tts server closed mid-frame")
            out.extend(chunk)
        return bytes(out)


def select_tier(use_case: str) -> str:
    return _TIER_MAP.get(use_case, "chatterbox")


def default_tts_server_socket_path() -> Path:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return Path(runtime_dir) / "hapax-tts-local.sock"


def resolve_backend_from_env() -> str:
    """Resolve the primary TTS backend from ``HAPAX_TTS_BACKEND``.

    Unset/empty resolves to the default; an invalid value warns with the
    valid choices and resolves to the default rather than dying silently.
    """
    raw = os.environ.get(TTS_BACKEND_ENV, "").strip().lower()
    if not raw:
        return _DEFAULT_TTS_BACKEND
    if raw in VALID_TTS_BACKENDS:
        return raw
    log.warning(
        "%s=%r is not a valid TTS backend (valid: %s) — using %r",
        TTS_BACKEND_ENV,
        raw,
        ", ".join(VALID_TTS_BACKENDS),
        _DEFAULT_TTS_BACKEND,
    )
    return _DEFAULT_TTS_BACKEND


def _resolve_transport_value(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    if not value:
        return _DEFAULT_TTS_TRANSPORT
    if value in VALID_TTS_TRANSPORTS:
        return value
    log.warning(
        "%s=%r is not a valid TTS transport (valid: %s) — using %r",
        TTS_TRANSPORT_ENV,
        value,
        ", ".join(VALID_TTS_TRANSPORTS),
        _DEFAULT_TTS_TRANSPORT,
    )
    return _DEFAULT_TTS_TRANSPORT


def resolve_transport_from_env() -> str:
    """Resolve the TTS transport from ``HAPAX_TTS_TRANSPORT``."""

    return _resolve_transport_value(os.environ.get(TTS_TRANSPORT_ENV))


def resolve_server_socket_path() -> Path:
    raw = os.environ.get(TTS_SERVER_SOCKET_ENV, "").strip()
    if not raw:
        return default_tts_server_socket_path()
    return Path(raw).expanduser()


def resolve_request_deadline_s() -> float:
    raw = os.environ.get(TTS_REQUEST_DEADLINE_ENV, "").strip()
    if not raw:
        return _DEFAULT_TTS_REQUEST_DEADLINE_S
    try:
        value = float(raw)
    except ValueError:
        log.warning(
            "%s=%r is not numeric — using %.1fs",
            TTS_REQUEST_DEADLINE_ENV,
            raw,
            _DEFAULT_TTS_REQUEST_DEADLINE_S,
        )
        return _DEFAULT_TTS_REQUEST_DEADLINE_S
    if value <= 0:
        log.warning(
            "%s=%r must be positive — using %.1fs",
            TTS_REQUEST_DEADLINE_ENV,
            raw,
            _DEFAULT_TTS_REQUEST_DEADLINE_S,
        )
        return _DEFAULT_TTS_REQUEST_DEADLINE_S
    return value


def priority_class_for_use_case(use_case: str) -> str:
    """Map public TTS use cases onto the engine server's priority classes."""

    normalized = (use_case or "").strip().lower()
    if normalized in {"conversation", "notification", "session", "session_timeout"}:
        return "interactive"
    if normalized in {"bridge", "tool-running", "presynth", "signal"}:
        return "bridge"
    return "hosting"


def _arc_prosody(
    arc_position: float | None,
    *,
    base_exag: float,
    base_cfg: float,
) -> tuple[float, float]:
    """Modulate (exaggeration, cfg_weight) by position in the segment arc.

    ``arc_position`` is the clause's fractional position in the segment arc
    (0.0 = open, 1.0 = peak/close); ``None`` leaves prosody at the base.
    Expressiveness rises smoothly toward the peak, bounded to the valid
    ``[0, 1]`` exaggeration range so the rise can never distort delivery.
    """
    if arc_position is None:
        return base_exag, base_cfg
    position = max(0.0, min(1.0, arc_position))
    exag = max(0.0, min(1.0, base_exag + _ARC_EXAGGERATION_GAIN * position))
    return exag, base_cfg


class TTSManager:
    """Manages TTS synthesis — primary backend from ``HAPAX_TTS_BACKEND``."""

    def __init__(
        self,
        voice_id: str = "af_heart",
        *,
        transport: str | None = None,
        server_socket_path: Path | str | None = None,
        request_deadline_s: float | None = None,
    ) -> None:
        self._voice_id = voice_id
        self._chatterbox_model = None
        self._kokoro_pipeline = None
        self._backend = resolve_backend_from_env()
        self._transport = (
            resolve_transport_from_env()
            if transport is None
            else _resolve_transport_value(transport)
        )
        self._server_socket_path = (
            resolve_server_socket_path()
            if server_socket_path is None
            else Path(server_socket_path).expanduser()
        )
        self._request_deadline_s = (
            resolve_request_deadline_s()
            if request_deadline_s is None
            else max(float(request_deadline_s), 0.001)
        )
        self._last_synthesis_backend: str | None = None
        self._last_server_liveness: dict[str, Any] | None = None

    @property
    def backend(self) -> str:
        """Configured primary backend (may demote to kokoro at preload)."""
        return self._backend

    @property
    def transport(self) -> str:
        """Where synthesis runs: ``local`` model owner or ``server`` client."""

        return self._transport

    @property
    def last_synthesis_backend(self) -> str | None:
        """Engine that produced the most recent PCM — fallback-aware.

        ``None`` until the first synthesis completes. This is the witness
        truth: with the chatterbox backend a per-call failure falls back to
        Kokoro, so the configured backend alone cannot say which engine
        actually spoke.
        """
        return self._last_synthesis_backend

    @property
    def last_server_liveness(self) -> dict[str, Any] | None:
        """Most recent server transport receipt, suitable for witness output."""

        if self._last_server_liveness is None:
            return None
        return dict(self._last_server_liveness)

    def preload(self) -> None:
        if self._transport == "server":
            if self._ping_server():
                log.info("TTS server reachable at %s", self._server_socket_path)
            else:
                log.warning("TTS server not reachable at %s", self._server_socket_path)
            return
        if self._backend == "kokoro":
            self._get_kokoro()
            log.info("Kokoro TTS ready (voice=%s, selected primary)", self._voice_id)
            return
        try:
            self._get_chatterbox()
            self._backend = "chatterbox"
            log.info("Chatterbox TTS ready (device=%s)", _CHATTERBOX_DEVICE)
        except Exception:
            log.warning("Chatterbox failed to load, falling back to Kokoro", exc_info=True)
            self._get_kokoro()
            self._backend = "kokoro"
            log.info("Kokoro TTS ready (voice=%s, fallback)", self._voice_id)

    def _get_chatterbox(self):
        if self._chatterbox_model is None:
            from chatterbox.tts import ChatterboxTTS

            self._chatterbox_model = ChatterboxTTS.from_pretrained(device=_CHATTERBOX_DEVICE)
        return self._chatterbox_model

    def _get_kokoro(self):
        if self._kokoro_pipeline is None:
            from kokoro import KPipeline

            self._kokoro_pipeline = KPipeline(lang_code="a", device="cpu")
        return self._kokoro_pipeline

    def synthesize(
        self,
        text: str,
        use_case: str = "conversation",
        *,
        speed: float = 1.0,
        interview_mode: bool = False,
        role: str | None = None,
        arc_position: float | None = None,
    ) -> bytes:
        if not text or not text.strip():
            return b""
        redaction = _speech_safety_censor(text)
        if redaction.was_modified:
            log.warning(
                "TTS safety gate redacted %d token(s) [%s]",
                redaction.hit_count,
                use_case,
            )
        lexicon = _speech_lexicon_apply(redaction.text)

        if self._transport == "server":
            return self._synthesize_via_server(
                lexicon.text,
                use_case=use_case,
                speed=speed,
                interview_mode=interview_mode,
                role=role,
                arc_position=arc_position,
            )

        if self._backend == "chatterbox":
            try:
                return self._synthesize_chatterbox(
                    lexicon.text,
                    interview_mode=interview_mode,
                    role=role,
                    arc_position=arc_position,
                )
            except Exception:
                log.warning("Chatterbox synthesis failed, falling back to Kokoro", exc_info=True)
                return self._synthesize_kokoro(lexicon.text, speed=speed)
        return self._synthesize_kokoro(lexicon.text, speed=speed)

    def _synthesize_chatterbox(
        self,
        text: str,
        *,
        interview_mode: bool = False,
        role: str | None = None,
        arc_position: float | None = None,
    ) -> bytes:
        model = self._get_chatterbox()
        voice_path = str(_VOICE_SAMPLE_PATH) if _VOICE_SAMPLE_PATH.exists() else None
        # Interview / dialogic roles deliver with restraint; everything else
        # uses the default base. Arc position then modulates expressiveness
        # continuously around that base.
        restrained = interview_mode or role == "interview"
        base_exag = _INTERVIEW_EXAGGERATION if restrained else _CHATTERBOX_EXAGGERATION
        base_cfg = _INTERVIEW_CFG_WEIGHT if restrained else _CHATTERBOX_CFG_WEIGHT
        exag, cfg = _arc_prosody(arc_position, base_exag=base_exag, base_cfg=base_cfg)
        wav = model.generate(
            text,
            audio_prompt_path=voice_path,
            exaggeration=exag,
            cfg_weight=cfg,
        )
        self._last_synthesis_backend = "chatterbox"
        audio = wav.squeeze().cpu().numpy().astype(np.float32)
        pcm = (audio * 32768).clip(-32768, 32767).astype(np.int16)
        if pcm.size == 0:
            log.warning("Chatterbox produced no audio for: %r", text[:50])
            return b""
        return pcm.tobytes()

    def _synthesize_kokoro(self, text: str, *, speed: float = 1.0) -> bytes:
        pipeline = self._get_kokoro()
        self._last_synthesis_backend = "kokoro"
        chunks: list[bytes] = []
        for _graphemes, _phonemes, audio in pipeline(text, voice=self._voice_id, speed=speed):
            if audio is not None:
                if hasattr(audio, "numpy"):
                    audio = audio.numpy()
                audio = np.asarray(audio, dtype=np.float32)
                pcm = (audio * 32768).clip(-32768, 32767).astype(np.int16)
                chunks.append(pcm.tobytes())
        if not chunks:
            log.warning("Kokoro produced no audio for: %r", text[:50])
            return b""
        return b"".join(chunks)

    def _ping_server(self) -> bool:
        request_id = f"tts-ping-{time.time_ns()}"
        started = time.monotonic()
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(min(self._request_deadline_s, 2.0))
                sock.connect(str(self._server_socket_path))
                payload = json.dumps(
                    {
                        "protocol": TTS_STREAM_PROTOCOL,
                        "op": "ping",
                        "request_id": request_id,
                    }
                ).encode("utf-8")
                sock.sendall(payload + b"\n")
                reader = _SocketBuffer(sock)
                header = json.loads(reader.read_line().decode("utf-8"))
        except (EOFError, OSError, RuntimeError, TimeoutError, json.JSONDecodeError) as exc:
            self._last_server_liveness = {
                "mode": "server",
                "status": "unreachable",
                "socket_path": str(self._server_socket_path),
                "request_id": request_id,
                "round_trip_ms": round((time.monotonic() - started) * 1000),
                "error": str(exc),
            }
            return False

        ok = header.get("status") == "ok" and header.get("op") == "pong"
        self._last_server_liveness = {
            "mode": "server",
            "status": "ok" if ok else "error",
            "socket_path": str(self._server_socket_path),
            "request_id": request_id,
            "round_trip_ms": round((time.monotonic() - started) * 1000),
            "backend": header.get("backend"),
            "queue_depth": header.get("queue_depth"),
            "error": None if ok else header.get("error", "invalid ping response"),
        }
        return ok

    def _synthesize_via_server(
        self,
        text: str,
        *,
        use_case: str,
        speed: float,
        interview_mode: bool,
        role: str | None,
        arc_position: float | None,
    ) -> bytes:
        request_id = f"tts-{time.time_ns()}"
        priority = priority_class_for_use_case(use_case)
        started = time.monotonic()
        request: dict[str, Any] = {
            "protocol": TTS_STREAM_PROTOCOL,
            "op": "synthesize",
            "request_id": request_id,
            "text": text,
            "use_case": use_case,
            "priority": priority,
            "deadline_s": self._request_deadline_s,
            "speed": speed,
            "interview_mode": interview_mode,
            "stream": True,
            "backend_hint": self._backend,
        }
        if role is not None:
            request["role"] = role
        if arc_position is not None:
            request["arc_position"] = arc_position

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self._request_deadline_s + _TTS_CLIENT_TIMEOUT_OVERHEAD_S)
                sock.connect(str(self._server_socket_path))
                sock.sendall(json.dumps(request).encode("utf-8") + b"\n")
                reader = _SocketBuffer(sock)
                header = json.loads(reader.read_line().decode("utf-8"))
                if header.get("status") != "ok":
                    self._record_server_error(
                        request_id=request_id,
                        started=started,
                        status=str(header.get("status") or "error"),
                        error=str(header.get("error") or "server error"),
                        priority=priority,
                    )
                    return b""

                chunks: list[bytes] = []
                pcm_len = 0
                while True:
                    frame = json.loads(reader.read_line().decode("utf-8"))
                    frame_type = frame.get("type")
                    if frame_type == "pcm":
                        size = int(frame.get("len", 0))
                        if size < 0:
                            raise RuntimeError("negative pcm frame length")
                        chunk = reader.read_exact(size)
                        chunks.append(chunk)
                        pcm_len += len(chunk)
                        continue
                    if frame_type == "done":
                        expected_len = int(frame.get("pcm_len", pcm_len))
                        if expected_len != pcm_len:
                            raise RuntimeError(
                                f"pcm length mismatch: expected {expected_len}, got {pcm_len}"
                            )
                        break
                    raise RuntimeError(f"unexpected tts frame type: {frame_type!r}")
        except (
            EOFError,
            OSError,
            RuntimeError,
            TimeoutError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            self._record_server_error(
                request_id=request_id,
                started=started,
                status="error",
                error=str(exc),
                priority=priority,
            )
            log.warning("TTS server synthesis failed: %s", exc)
            return b""

        backend = header.get("backend")
        self._last_synthesis_backend = str(backend) if backend else None
        self._last_server_liveness = {
            "mode": "server",
            "status": "ok",
            "socket_path": str(self._server_socket_path),
            "request_id": request_id,
            "protocol": header.get("protocol"),
            "priority": priority,
            "backend": backend,
            "queue_wait_ms": header.get("queue_wait_ms"),
            "synthesis_ms": header.get("synthesis_ms"),
            "round_trip_ms": round((time.monotonic() - started) * 1000),
            "pcm_bytes": pcm_len,
            "error": None,
        }
        return b"".join(chunks)

    def _record_server_error(
        self,
        *,
        request_id: str,
        started: float,
        status: str,
        error: str,
        priority: str,
    ) -> None:
        self._last_server_liveness = {
            "mode": "server",
            "status": status,
            "socket_path": str(self._server_socket_path),
            "request_id": request_id,
            "priority": priority,
            "round_trip_ms": round((time.monotonic() - started) * 1000),
            "error": error,
        }
