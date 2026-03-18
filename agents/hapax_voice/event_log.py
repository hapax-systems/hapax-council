"""Structured JSONL event log for voice daemon observability."""

from __future__ import annotations

import datetime
import json
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULT_DIR = Path.home() / ".local" / "share" / "hapax-voice"


class EventLog:
    """Appends structured JSON events to daily-rotated JSONL files.

    Each event includes ts, type, session_id, source_service, plus
    caller-provided fields. Writes are synchronous (append + flush).
    """

    def __init__(
        self,
        base_dir: Path = _DEFAULT_DIR,
        retention_days: int = 14,
        enabled: bool = True,
    ) -> None:
        self._base_dir = Path(base_dir)
        self._retention_days = retention_days
        self._enabled = enabled
        self._session_id: str | None = None
        self._current_date: str = ""
        self._file = None

    def set_session_id(self, session_id: str | None) -> None:
        """Update the current session ID (set to None when session closes)."""
        self._session_id = session_id

    def set_consent_fn(self, fn: object) -> None:
        """Set a callable that returns True when persistence is allowed.

        Used for consent curtailment: person-adjacent event fields are
        redacted when persistence is not allowed (guest present without consent).
        """
        self._consent_fn = fn

    # Event types that may contain person-adjacent data
    _PERSON_ADJACENT_EVENTS: frozenset[str] = frozenset(
        {
            "user_utterance",
            "assistant_response",
            "speaker_identified",
            "consent_pending",
            "consent_granted",
            "consent_refused",
            "face_event",
            "presence_transition",
            "presence_bayesian_transition",
        }
    )

    # Fields that should be redacted when consent is not granted
    _REDACT_FIELDS: frozenset[str] = frozenset(
        {
            "text",
            "transcript",
            "response",
            "utterance",
            "speaker",
        }
    )

    def emit(self, event_type: str, **fields) -> None:
        """Write a single event to the JSONL file."""
        if not self._enabled:
            return

        # Consent curtailment: redact person-adjacent fields when guest
        # is present without consent
        consent_fn = getattr(self, "_consent_fn", None)
        if (
            consent_fn is not None
            and event_type in self._PERSON_ADJACENT_EVENTS
            and not consent_fn()
        ):
            fields = {
                k: "[curtailed]" if k in self._REDACT_FIELDS else v for k, v in fields.items()
            }
            fields["consent_curtailed"] = True

        event = {
            "ts": time.time(),
            "type": event_type,
            "session_id": self._session_id,
            "source_service": "hapax-voice",
            **fields,
        }
        # Inject OTel trace context if an active span exists
        try:
            from opentelemetry import trace

            span = trace.get_current_span()
            ctx = span.get_span_context()
            if ctx and ctx.trace_id:
                event["trace_id"] = format(ctx.trace_id, "032x")
                event["span_id"] = format(ctx.span_id, "016x")
        except Exception:
            pass  # OTel unavailable or no active span — fail open
        try:
            f = self._get_file()
            f.write(json.dumps(event, default=str) + "\n")
            f.flush()
        except Exception as exc:
            log.debug("Failed to write event: %s", exc)

    def cleanup(self) -> None:
        """Remove event files older than retention_days."""
        cutoff = datetime.date.today() - datetime.timedelta(days=self._retention_days)
        for path in self._base_dir.glob("events-*.jsonl"):
            try:
                date_str = path.stem.replace("events-", "")
                file_date = datetime.date.fromisoformat(date_str)
                if file_date < cutoff:
                    path.unlink()
                    log.debug("Cleaned up old event log: %s", path.name)
            except (ValueError, OSError) as exc:
                log.debug("Cleanup skipped %s: %s", path.name, exc)

    def _get_file(self):
        """Return file handle for today's event log, rotating if needed."""
        today = datetime.date.today().isoformat()
        if today != self._current_date:
            if self._file is not None:
                self._file.close()
            self._base_dir.mkdir(parents=True, exist_ok=True)
            path = self._base_dir / f"events-{today}.jsonl"
            self._file = open(path, "a", encoding="utf-8")
            self._current_date = today
        return self._file

    def close(self) -> None:
        """Close the current file handle."""
        if self._file is not None:
            self._file.close()
            self._file = None
