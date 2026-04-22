from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from shared.ward_publisher_schemas import (
    RecentImpingementEntry,
    RecentImpingements,
)

log = logging.getLogger(__name__)
TOP_N = 6
TICK_INTERVAL_SEC = 0.5
TAIL_BYTES = 4096


class RecentImpingementsPublisher:
    """Reads top-N impingements by salience and writes to the compositor SHM.

    Runs as a background thread in the compositor process.
    """

    def __init__(self, src: Path, dst: Path) -> None:
        self.src = src
        self.dst = dst
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="recent-impingements-publisher", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("recent-impingements publisher tick failed")
            self._stop.wait(TICK_INTERVAL_SEC)

    def tick(self) -> None:
        if not self.src.exists():
            return
        with self.src.open("rb") as fh:
            fh.seek(max(0, self.src.stat().st_size - TAIL_BYTES))
            buf = fh.read().decode("utf-8", errors="replace")
        rows: list[tuple[float, RecentImpingementEntry]] = []
        for line in buf.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            family = obj.get("intent_family") or obj.get("family") or ""
            salience = float(obj.get("salience", 0.0))
            rows.append(
                (
                    salience,
                    RecentImpingementEntry(path=family, value=salience, family=family),
                )
            )
        rows.sort(key=lambda r: r[0], reverse=True)
        entries = [entry for _, entry in rows[:TOP_N]]
        payload = RecentImpingements(generated_at=time.time(), entries=entries)
        self._write(payload)

    def _write(self, payload: RecentImpingements) -> None:
        self.dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.dst.with_suffix(self.dst.suffix + ".tmp")
        tmp.write_text(payload.model_dump_json())
        tmp.replace(self.dst)
