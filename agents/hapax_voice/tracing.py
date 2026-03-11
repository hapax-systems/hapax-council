"""Langfuse trace integration for hapax-voice observability."""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

try:
    from langfuse import Langfuse
except ImportError:
    Langfuse = None


@dataclass
class NoOpSpan:
    """No-op span for when tracing is disabled."""

    def span(self, name: str, **kwargs: Any) -> NoOpSpan:
        return self

    def end(self, **kwargs: Any) -> None:
        pass

    def update(self, **kwargs: Any) -> None:
        pass


class VoiceTracer:
    """Wraps Langfuse SDK for hapax-voice trace creation.

    Fail-open: if Langfuse is unreachable, credentials missing, or SDK
    unavailable, all methods become no-ops. Never crashes the daemon.
    """

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled and Langfuse is not None
        self._client: Any | None = None

    def _get_client(self) -> Any | None:
        if not self._enabled:
            return None
        if self._client is not None:
            return self._client
        try:
            pk = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
            sk = os.environ.get("LANGFUSE_SECRET_KEY", "")
            host = os.environ.get("LANGFUSE_HOST", "http://localhost:3000")
            if not pk or not sk:
                log.debug("Langfuse credentials not set, tracing disabled")
                self._enabled = False
                return None
            self._client = Langfuse(public_key=pk, secret_key=sk, host=host)
            log.info("Langfuse tracing initialized")
            return self._client
        except Exception as exc:
            log.warning("Langfuse initialization failed: %s", exc)
            self._enabled = False
            return None

    @contextlib.contextmanager
    def trace_analysis(
        self,
        *,
        presence_score: str = "unknown",
        images_sent: int = 0,
        session_id: str | None = None,
        activity_mode: str = "unknown",
        session_active: bool = False,
    ) -> Generator[Any, None, None]:
        client = self._get_client()
        if client is None:
            yield NoOpSpan()
            return
        try:
            trace = client.trace(
                name="workspace_analysis",
                session_id=session_id,
                tags=["hapax-voice"],
                metadata={
                    "source_service": "hapax-voice",
                    "presence_score": presence_score,
                    "images_sent": images_sent,
                    "activity_mode": activity_mode,
                    "session_active": session_active,
                },
            )
            yield trace
            trace.update(status_message="completed")
        except Exception as exc:
            log.debug("Trace analysis error: %s", exc)
            yield NoOpSpan()

    @contextlib.contextmanager
    def trace_session(
        self,
        *,
        session_id: str,
        trigger: str,
    ) -> Generator[Any, None, None]:
        client = self._get_client()
        if client is None:
            yield NoOpSpan()
            return
        try:
            trace = client.trace(
                name="voice_session",
                session_id=session_id,
                tags=["hapax-voice"],
                metadata={"source_service": "hapax-voice", "trigger": trigger},
            )
            yield trace
        except Exception as exc:
            log.debug("Trace session error: %s", exc)
            yield NoOpSpan()

    @contextlib.contextmanager
    def trace_delivery(
        self,
        *,
        session_id: str | None,
        presence_score: str,
        gate_reason: str,
        notification_priority: str,
    ) -> Generator[Any, None, None]:
        client = self._get_client()
        if client is None:
            yield NoOpSpan()
            return
        try:
            trace = client.trace(
                name="proactive_delivery",
                session_id=session_id,
                tags=["hapax-voice"],
                metadata={
                    "source_service": "hapax-voice",
                    "presence_score": presence_score,
                    "gate_reason": gate_reason,
                    "notification_priority": notification_priority,
                },
            )
            yield trace
        except Exception as exc:
            log.debug("Trace delivery error: %s", exc)
            yield NoOpSpan()

    def flush(self, timeout_s: float = 5.0) -> None:
        """Flush pending traces with timeout to prevent hanging."""
        if self._client is None:
            return
        import threading

        t = threading.Thread(target=self._do_flush, daemon=True)
        t.start()
        t.join(timeout=timeout_s)
        if t.is_alive():
            log.warning("Langfuse flush timed out after %.1fs", timeout_s)

    def _do_flush(self) -> None:
        try:
            self._client.flush()
        except Exception:
            pass
