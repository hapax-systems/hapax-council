"""StatuslogPoster — autonomous statuslog publisher."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.publication_bus.publisher_kit import PublisherPayload
from shared.governance.omg_referent import OperatorNameLeak, safe_render
from shared.governance.publication_allowlist import check as allowlist_check
from shared.omg_statuslog_public_event_adapter import (
    StatuslogCandidate,
    select_statuslog_postable_events,
)
from shared.research_vehicle_public_event import ResearchVehiclePublicEvent

log = logging.getLogger(__name__)

SURFACE = "omg-lol-statuslog"
DEFAULT_STATE_FILE = Path.home() / ".cache" / "hapax" / "hapax-omg-statuslog" / "state.json"
DEFAULT_ADDRESS = "hapax"
MAX_STATUS_LEN = 280

try:
    from prometheus_client import Counter

    _POST_TOTAL = Counter(
        "hapax_broadcast_omg_statuslog_posts_total",
        "omg.lol /statuses autonomous posts by outcome.",
        ["result"],
    )

    def _record(outcome: str) -> None:
        _POST_TOTAL.labels(result=outcome).inc()
except ImportError:

    def _record(outcome: str) -> None:
        log.debug("prometheus_client unavailable; metric dropped (%s)", outcome)


def _compose_status_text(event: dict, *, llm_call: Any | None = None) -> str:
    """Default composer — thin wrapper around the LLM call that tolerates
    LLM failures by returning an empty string.

    Production callers can swap in the full ``metadata_composer`` cross-
    surface composer; for statuslog-v1 the simpler path (direct LLM call
    with a short scientific-register prompt) is enough. The poster's
    ``compose_fn`` injection makes this swap trivial.
    """
    if llm_call is None:
        # No LLM provided; echo the event summary if short enough, else empty.
        summary = event.get("summary") or event.get("narrative") or ""
        if 0 < len(summary) <= MAX_STATUS_LEN:
            return summary
        return ""

    prompt = (
        "Compose a single status update (<= 280 characters, one line, "
        "scientific register, no emoji) reflecting this chronicle event:\n\n"
        f"{json.dumps(event, indent=2)}"
    )
    try:
        out = llm_call(prompt)
    except Exception as e:  # noqa: BLE001 — LLM failures must not crash the poster
        log.warning("omg-statuslog: LLM compose failed: %s", e)
        return ""
    if not isinstance(out, str):
        return ""
    return out.strip()


def _read_rvpe_jsonl(path: Path) -> list[ResearchVehiclePublicEvent]:
    """Read RVPE JSONL rows, skipping malformed lines."""
    events: list[ResearchVehiclePublicEvent] = []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return events
    for line_no, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            events.append(ResearchVehiclePublicEvent.model_validate_json(stripped))
        except ValueError:
            log.warning("omg-statuslog: skipping invalid RVPE row %s:%d", path, line_no)
    return events


def _summary_from_candidate(candidate: StatuslogCandidate) -> str:
    event = candidate.event
    if event.chapter_ref is not None and event.chapter_ref.label:
        return event.chapter_ref.label
    if event.public_url:
        return f"{event.event_type}: {event.public_url}"
    return f"{event.event_type} from {event.source.producer}"


def _rvpe_cli_success(outcome: str) -> bool:
    return outcome.startswith("rejected:") or outcome in {
        "posted",
        "duplicate-event",
        "low-salience",
        "cap-exceeded",
        "debounced",
    }


class StatuslogPoster:
    """Post autonomous statuses to omg.lol /statuses.

    Uses injection for ``now_fn`` + ``compose_fn`` so tests can drive
    the poster deterministically without an LLM or wall-clock dependency.

    Parameters:
        client:          credential/enabled-state carrier (may be disabled)
        publisher:       publication-bus publisher that owns public egress
        state_file:      persistence for last-post timestamp + daily count
        min_interval_s:  min seconds between posts (default 14400 = 4h)
        daily_cap:       max posts per UTC day (default 3)
        min_salience:    salience floor to consider posting (default 0.75)
        now_fn:          callable returning wall-clock epoch seconds
        compose_fn:      callable(event: dict) -> str; returns status text
        address:         omg.lol address (default ``hapax``)
    """

    def __init__(
        self,
        *,
        client: Any,
        publisher: Any,
        state_file: Path,
        min_interval_s: int = 14400,
        daily_cap: int = 3,
        min_salience: float = 0.75,
        now_fn: Callable[[], float],
        compose_fn: Callable[[dict], str],
        address: str = DEFAULT_ADDRESS,
    ) -> None:
        self.client = client
        self.publisher = publisher
        self.state_file = state_file
        self.min_interval_s = min_interval_s
        self.daily_cap = daily_cap
        self.min_salience = min_salience
        self._now_fn = now_fn
        self._compose_fn = compose_fn
        self.address = address

    # ── state ────────────────────────────────────────────────────────

    def _read_state(self) -> dict:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {"last_post_ts": 0.0, "day_key": "", "day_count": 0}

    def _write_state(self, state: dict) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self.state_file)

    def _day_key(self, now: float) -> str:
        return datetime.fromtimestamp(now, tz=UTC).strftime("%Y-%m-%d")

    # ── gates ────────────────────────────────────────────────────────

    def _event_already_posted(self, event_id: str) -> bool:
        if not event_id:
            return False
        state = self._read_state()
        if state.get("last_event_id") == event_id:
            return True
        posted_event_ids = state.get("posted_event_ids")
        return isinstance(posted_event_ids, list) and event_id in posted_event_ids

    def can_post_now(self) -> bool:
        """Compose + post gates without the actual call — useful for
        tests that want to probe rate-limit state."""
        now = self._now_fn()
        state = self._read_state()
        last = state.get("last_post_ts", 0.0)
        if now - last < self.min_interval_s:
            return False
        today = self._day_key(now)
        day_count = state.get("day_count", 0) if state.get("day_key") == today else 0
        return day_count < self.daily_cap

    # ── main post flow ───────────────────────────────────────────────

    def post(self, event: dict) -> str:
        """Consider + post one chronicle event. Returns one of:
        ``"posted"`` | ``"low-salience"`` | ``"cap-exceeded"`` |
        ``"debounced"`` | ``"duplicate-event"`` | ``"compose-empty"`` |
        ``"allowlist-denied"`` | ``"client-disabled"`` | ``"failed"``.
        """
        salience = event.get("salience", 0.0)
        if not isinstance(salience, (int, float)) or salience < self.min_salience:
            _record("low-salience")
            return "low-salience"

        event_id = str(event.get("event_id") or "")
        if self._event_already_posted(event_id):
            _record("duplicate-event")
            return "duplicate-event"

        now = self._now_fn()
        state = self._read_state()
        last = state.get("last_post_ts", 0.0)
        if now - last < self.min_interval_s:
            _record("debounced")
            return "debounced"

        today = self._day_key(now)
        day_count = state.get("day_count", 0) if state.get("day_key") == today else 0
        if day_count >= self.daily_cap:
            _record("cap-exceeded")
            return "cap-exceeded"

        # Allowlist before any composition — deny short-circuits LLM cost.
        allow = allowlist_check(
            SURFACE,
            str(event.get("event_type") or "chronicle.high_salience"),
            {
                "summary": event.get("summary", ""),
                "source": event.get("source", ""),
                "event": event,
            },
        )
        if allow.decision == "deny":
            log.info("omg-statuslog: allowlist denied (%s)", allow.reason)
            _record("allowlist-denied")
            return "allowlist-denied"

        text = self._compose_fn(event)
        if not text:
            _record("compose-empty")
            return "compose-empty"
        if len(text) > MAX_STATUS_LEN:
            text = text[: MAX_STATUS_LEN - 1].rstrip() + "…"

        # AUDIT-05: substitute {operator} via OperatorReferentPicker +
        # scan for legal-name leak before publishing. LLM-composed text
        # is the highest-risk path in the OMG cascade — fail-closed if
        # the legal name slips through HAPAX_OPERATOR_NAME guard.
        try:
            text = safe_render(text, segment_id=str(event.get("event_id", "")) or None)
        except OperatorNameLeak:
            log.warning("omg-statuslog: legal-name leak detected — DROPPING post")
            _record("legal-name-leak")
            return "legal-name-leak"

        if not getattr(self.client, "enabled", False):
            log.warning("omg-statuslog: client disabled — skipping post")
            _record("client-disabled")
            return "client-disabled"

        result = self.publisher.publish(
            PublisherPayload(
                target=self.address,
                text=text,
                metadata={"skip_mastodon_post": True},
            )
        )
        if result.refused:
            _record("allowlist-denied")
            return "allowlist-denied"
        if not result.ok:
            _record("failed")
            return "failed"

        state["last_post_ts"] = now
        state["day_key"] = today
        state["day_count"] = day_count + 1
        if event_id:
            posted_event_ids = state.get("posted_event_ids")
            if not isinstance(posted_event_ids, list):
                posted_event_ids = []
            if event_id not in posted_event_ids:
                posted_event_ids.append(event_id)
            state["posted_event_ids"] = posted_event_ids[-256:]
            state["last_event_id"] = event_id
        self._write_state(state)
        _record("posted")
        log.info("omg-statuslog: posted (day %s, %d/%d)", today, day_count + 1, self.daily_cap)
        return "posted"

    def post_candidate(self, candidate: StatuslogCandidate) -> str:
        event = candidate.event.model_dump(mode="json")
        event.setdefault("summary", _summary_from_candidate(candidate))
        event["gate_move"] = candidate.move.model_dump(mode="json")
        return self.post(event)

    def post_rvpe_events(self, events: Iterable[ResearchVehiclePublicEvent]) -> dict[str, str]:
        candidates, rejections = select_statuslog_postable_events(events)
        outcomes: dict[str, str] = {
            rejection.event_id: f"rejected:{rejection.state}" for rejection in rejections
        }
        for candidate in candidates:
            outcomes[candidate.event.event_id] = self.post_candidate(candidate)
        return outcomes


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--event-json", help="path to JSON file with one manual chronicle event")
    source.add_argument("--rvpe-jsonl", help="path to ResearchVehiclePublicEvent JSONL rows")
    p.add_argument("--address", default=DEFAULT_ADDRESS)
    p.add_argument("--dry-run", action="store_true", help="run gates + compose; skip post")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    import time

    from agents.publication_bus.omg_statuslog_publisher import OmgLolStatuslogPublisher
    from shared.omg_lol_client import OmgLolClient

    client = OmgLolClient(address=args.address)
    publisher = OmgLolStatuslogPublisher(token=client.api_key)

    def _compose(event: dict) -> str:
        # Production default: use the event summary as-is (truncated).
        # Future: wire into shared.config.get_model_adaptive for LLM polish.
        return _compose_status_text(event, llm_call=None)

    poster = StatuslogPoster(
        client=client,
        publisher=publisher,
        state_file=DEFAULT_STATE_FILE,
        now_fn=time.time,
        compose_fn=_compose,
        address=args.address,
    )

    if args.dry_run:
        if args.event_json:
            event = json.loads(Path(args.event_json).read_text(encoding="utf-8"))
            can = poster.can_post_now()
            text = _compose(event)
            print(f"can-post: {can}; compose-length: {len(text)}")
        else:
            events = _read_rvpe_jsonl(Path(args.rvpe_jsonl))
            candidates, rejections = select_statuslog_postable_events(events)
            print(json.dumps({"candidates": len(candidates), "rejections": len(rejections)}))
        return 0

    if args.event_json:
        event = json.loads(Path(args.event_json).read_text(encoding="utf-8"))
        outcome = poster.post(event)
        print(outcome)
        return (
            0
            if outcome in ("posted", "low-salience", "cap-exceeded", "debounced", "duplicate-event")
            else 1
        )

    events = _read_rvpe_jsonl(Path(args.rvpe_jsonl))
    outcomes = poster.post_rvpe_events(events)
    print(json.dumps(outcomes, sort_keys=True))
    return 0 if all(_rvpe_cli_success(outcome) for outcome in outcomes.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
