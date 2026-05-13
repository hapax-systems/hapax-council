"""OmgNowSync — renders the /now page and publishes to omg.lol.

Soft state readers are injected so tests can drive the daemon with
mocked state. The default production wiring uses
:func:`agents.omg_now_sync.data.load_*` functions against the canonical
paths (``~/.cache/hapax/working-mode``, ``/dev/shm/hapax-dmn/stimmung.json``,
``/dev/shm/hapax-chronicle/events.jsonl``).

Content-hash dedup: rendering excludes the timestamp so wall-clock
change alone doesn't trigger a republish. State changes
(mode/stimmung/chronicle events) do trigger.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from agents.omg_now_sync.data import NowState
from agents.publication_bus.omg_now_publisher import OmgLolNowPublisher
from agents.publication_bus.publisher_kit import PublisherPayload
from shared.governance.omg_referent import OperatorNameLeak, safe_render

log = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

DEFAULT_ADDRESS = "hapax"
DEFAULT_STATE_FILE = Path.home() / ".cache" / "hapax" / "hapax-omg-now-sync" / "state.json"
DEFAULT_WORKING_MODE_FILE = Path.home() / ".cache" / "hapax" / "working-mode"
DEFAULT_STIMMUNG_FILE = Path("/dev/shm/hapax-dmn/stimmung.json")
DEFAULT_CHRONICLE_FILE = Path("/dev/shm/hapax-chronicle/events.jsonl")

try:
    from prometheus_client import Counter

    _NOW_SYNC_TOTAL = Counter(
        "hapax_broadcast_omg_now_syncs_total",
        "omg.lol /now sync attempts by outcome.",
        ["result"],
    )

    def _record(outcome: str) -> None:
        _NOW_SYNC_TOTAL.labels(result=outcome).inc()
except ImportError:

    def _record(outcome: str) -> None:
        log.debug("prometheus_client unavailable; metric dropped (%s)", outcome)


def _jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["md", "j2", "html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_now_markdown(state: NowState) -> str:
    """Render the /now template against a state snapshot."""
    env = _jinja_env()
    template = env.get_template("now.md.j2")
    return template.render(state=state)


def _content_hash_input(state: NowState) -> str:
    """Serialize the state excluding the timestamp so wall-clock alone
    never drives a republish. Chronicle events, mode, and stimmung
    changes produce a different hash as expected."""
    payload = state.model_dump(mode="json")
    payload.pop("timestamp_iso", None)
    return json.dumps(payload, sort_keys=True)


class OmgNowSync:
    """Publish the /now page when underlying state changes.

    Parameters:
        client:          an :class:`OmgLolClient` (may be disabled)
        state_file:      persistence for the last-publish content hash
        now_fn:          callable returning an ISO-8601 timestamp
        read_working_mode, read_stimmung, read_chronicle_recent:
                         injected state readers
        address:         omg.lol address (default ``hapax``)
    """

    def __init__(
        self,
        *,
        client: Any,
        state_file: Path,
        now_fn: Callable[[], str],
        read_working_mode: Callable[[], str],
        read_stimmung: Callable[[], dict | None],
        read_chronicle_recent: Callable[[], list[dict]],
        address: str = DEFAULT_ADDRESS,
    ) -> None:
        self.client = client
        self.state_file = state_file
        self._now_fn = now_fn
        self._read_working_mode = read_working_mode
        self._read_stimmung = read_stimmung
        self._read_chronicle_recent = read_chronicle_recent
        self.address = address

    def _read_state(self) -> dict:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write_state(self, state: dict) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_name(f"{self.state_file.name}.tmp.{uuid.uuid4().hex}")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self.state_file)

    def build_state(self) -> NowState:
        return NowState(
            working_mode=self._read_working_mode(),
            stimmung=self._read_stimmung(),
            chronicle_recent=self._read_chronicle_recent(),
            timestamp_iso=self._now_fn(),
        )

    def run_once(self, *, dry_run: bool = False) -> str:
        """Run one publish cycle. Returns one of:
        ``"published"`` | ``"skipped"`` | ``"dry-run"`` |
        ``"client-disabled"`` | ``"failed"``.
        """
        state = self.build_state()
        markdown = render_now_markdown(state)
        content_sha = hashlib.sha256(_content_hash_input(state).encode("utf-8")).hexdigest()

        persisted = self._read_state()
        if persisted.get("last_content_sha256") == content_sha:
            log.info("omg-now: unchanged since last publish (sha %s…)", content_sha[:8])
            _record("skipped")
            return "skipped"

        if dry_run:
            log.info(
                "omg-now: dry-run — mode=%s, chronicle=%d events",
                state.working_mode,
                len(state.chronicle_recent),
            )
            _record("dry-run")
            return "dry-run"

        if not getattr(self.client, "enabled", False):
            log.warning("omg-now: client disabled — skipping publish")
            _record("client-disabled")
            return "client-disabled"

        # AUDIT-05: scan rendered markdown for legal-name leak before
        # publishing. The /now page aggregates chronicle events whose
        # narrative may contain operator-name surface forms.
        try:
            markdown = safe_render(markdown, segment_id=content_sha)
        except OperatorNameLeak:
            log.warning("omg-now: legal-name leak detected — DROPPING publish")
            _record("legal-name-leak")
            return "legal-name-leak"

        result = OmgLolNowPublisher(client=self.client).publish(
            PublisherPayload(target=self.address, text=markdown, metadata={"listed": True})
        )
        if not result.ok:
            log.warning("omg-now: publication-bus publish failed: %s", result.detail)
            _record("failed")
            return "failed"

        persisted["last_content_sha256"] = content_sha
        persisted["last_timestamp_iso"] = state.timestamp_iso
        self._write_state(persisted)
        log.info(
            "omg-now: published — mode=%s, chronicle=%d",
            state.working_mode,
            len(state.chronicle_recent),
        )
        _record("published")
        return "published"


def _default_sync(address: str = DEFAULT_ADDRESS) -> OmgNowSync:
    """Production wiring — readers point at canonical paths on this host."""
    from agents.omg_now_sync.data import (
        load_chronicle_recent,
        load_stimmung,
        load_working_mode,
    )
    from shared.omg_lol_client import OmgLolClient

    def _now_iso() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    return OmgNowSync(
        client=OmgLolClient(address=address),
        state_file=DEFAULT_STATE_FILE,
        now_fn=_now_iso,
        read_working_mode=lambda: load_working_mode(DEFAULT_WORKING_MODE_FILE),
        read_stimmung=lambda: load_stimmung(DEFAULT_STIMMUNG_FILE),
        read_chronicle_recent=lambda: load_chronicle_recent(
            DEFAULT_CHRONICLE_FILE,
            now_iso=_now_iso(),
            window_minutes=30,
            min_salience=0.6,
        ),
        address=address,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="single cycle (default)")
    mode.add_argument("--dry-run", action="store_true", help="render + hash; skip POST")
    p.add_argument("--address", default=DEFAULT_ADDRESS)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    sync = _default_sync(address=args.address)
    outcome = sync.run_once(dry_run=args.dry_run)
    print(outcome)
    return 0


if __name__ == "__main__":
    sys.exit(main())
