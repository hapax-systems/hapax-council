"""JSONL runner for the content-programme conversion broker."""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from shared.content_programme_run_store import ContentProgrammeRunEnvelope
from shared.conversion_broker import (
    DEFAULT_CANDIDATE_PATH,
    DEFAULT_PUBLIC_EVENT_PATH,
    ConversionBroker,
    ConversionBrokerMetrics,
)
from shared.format_public_event_adapter import ProgrammeBoundaryEvent

log = logging.getLogger(__name__)

DEFAULT_TICK_S = 30.0


def _default_state_root() -> Path:
    env = os.environ.get("HAPAX_STATE")
    if env:
        return Path(env)
    return Path.home() / "hapax-state"


DEFAULT_RUN_ENVELOPE_PATH = _default_state_root() / "content-programme-runs" / "envelopes.jsonl"
DEFAULT_BOUNDARY_EVENT_PATH = _default_state_root() / "content-programme-runs" / "boundaries.jsonl"
DEFAULT_CURSOR_PATH = (
    Path.home() / ".cache" / "hapax" / "conversion-broker-processed-boundaries.json"
)


class ConversionBrokerRunner:
    """Tail canonical programme run/boundary JSONL files and broker conversions."""

    def __init__(
        self,
        *,
        run_envelope_path: Path = DEFAULT_RUN_ENVELOPE_PATH,
        boundary_event_path: Path = DEFAULT_BOUNDARY_EVENT_PATH,
        public_event_path: Path = DEFAULT_PUBLIC_EVENT_PATH,
        candidate_path: Path = DEFAULT_CANDIDATE_PATH,
        cursor_path: Path = DEFAULT_CURSOR_PATH,
        broker: ConversionBroker | None = None,
        metrics: ConversionBrokerMetrics | None = None,
        tick_s: float = DEFAULT_TICK_S,
    ) -> None:
        self.run_envelope_path = run_envelope_path
        self.boundary_event_path = boundary_event_path
        self.cursor_path = cursor_path
        self.tick_s = max(1.0, tick_s)
        self._stop_evt = threading.Event()
        self.broker = broker or ConversionBroker(
            public_event_path=public_event_path,
            candidate_path=candidate_path,
            metrics=metrics,
        )

    def run_once(self) -> int:
        """Process unseen boundaries whose source run envelope is available."""

        runs = _load_run_envelopes(self.run_envelope_path)
        if not runs:
            return 0
        processed = _load_cursor(self.cursor_path)
        handled = 0
        for boundary in _iter_boundary_events(self.boundary_event_path):
            key = _boundary_key(boundary)
            if key in processed:
                continue
            run = runs.get(boundary.run_id)
            if run is None:
                log.warning(
                    "boundary %s references missing run %s; leaving unprocessed",
                    boundary.boundary_id,
                    boundary.run_id,
                )
                continue
            try:
                decision = self.broker.process_boundary(
                    run,
                    boundary,
                    generated_at=datetime.now(UTC),
                )
            except Exception:  # noqa: BLE001
                log.exception("conversion broker failed for boundary %s", boundary.boundary_id)
                continue
            processed.add(key)
            _save_cursor(self.cursor_path, processed)
            handled += 1
            log.info(
                "processed boundary=%s run=%s candidates=%d public_events=%d",
                boundary.boundary_id,
                run.run_id,
                len(decision.candidates),
                len(decision.public_events),
            )
        return handled

    def run_forever(self) -> None:
        """Run the broker loop until SIGTERM/SIGINT."""

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, lambda *_: self.stop())
            except ValueError:
                pass
        log.info(
            "conversion_broker starting, runs=%s boundaries=%s cursor=%s tick=%.1fs",
            self.run_envelope_path,
            self.boundary_event_path,
            self.cursor_path,
            self.tick_s,
        )
        while not self._stop_evt.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001
                log.exception("conversion broker tick failed; continuing")
            self._stop_evt.wait(self.tick_s)

    def stop(self) -> None:
        self._stop_evt.set()


def _load_run_envelopes(path: Path) -> dict[str, ContentProgrammeRunEnvelope]:
    runs: dict[str, ContentProgrammeRunEnvelope] = {}
    for run in _iter_jsonl_model(path, ContentProgrammeRunEnvelope):
        runs[run.run_id] = run
    return runs


def _iter_boundary_events(path: Path) -> Iterator[ProgrammeBoundaryEvent]:
    yield from _iter_jsonl_model(path, ProgrammeBoundaryEvent)


def _iter_jsonl_model[T: BaseModel](path: Path, model: type[T]) -> Iterator[T]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    except OSError:
        log.warning("failed to read JSONL path %s", path, exc_info=True)
        return
    for line_number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("skipping invalid JSON in %s:%d", path, line_number)
            continue
        try:
            yield model.model_validate(item)
        except ValidationError:
            log.warning("skipping invalid record in %s:%d", path, line_number, exc_info=True)


def _boundary_key(boundary: ProgrammeBoundaryEvent) -> str:
    return f"{boundary.run_id}:{boundary.boundary_id}:{boundary.duplicate_key}"


def _load_cursor(path: Path) -> set[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return set()
    if isinstance(payload, list):
        return {item for item in payload if isinstance(item, str)}
    if isinstance(payload, dict):
        keys = payload.get("processed_boundary_keys", [])
        if isinstance(keys, list):
            return {item for item in keys if isinstance(item, str)}
    return set()


def _save_cursor(path: Path, keys: set[str]) -> None:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "processed_boundary_keys": sorted(keys),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


__all__ = [
    "DEFAULT_BOUNDARY_EVENT_PATH",
    "DEFAULT_CURSOR_PATH",
    "DEFAULT_RUN_ENVELOPE_PATH",
    "DEFAULT_TICK_S",
    "ConversionBrokerRunner",
]
