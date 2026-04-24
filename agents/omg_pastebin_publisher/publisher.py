"""PastebinArtifactPublisher — weekly chronicle digest publisher.

Phase A scope: one category only (chronicle.weekly_digest). The
architecture is modular so other categories land as follow-up PRs
adding new `build_*_digest` / `build_*_slug` pairs that share the
same publisher class.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from shared.governance.publication_allowlist import check as allowlist_check

log = logging.getLogger(__name__)

SURFACE = "omg-lol-pastebin"
DEFAULT_ADDRESS = "hapax"
DEFAULT_CHRONICLE_FILE = Path("/dev/shm/hapax-chronicle/events.jsonl")
DEFAULT_STATE_FILE = Path.home() / ".cache" / "hapax" / "hapax-omg-pastebin" / "state.json"

try:
    from prometheus_client import Counter

    _PUBLISH_TOTAL = Counter(
        "hapax_broadcast_omg_pastebin_publishes_total",
        "omg.lol pastebin artifact publishes by category + outcome.",
        ["category", "result"],
    )

    def _record(category: str, outcome: str) -> None:
        _PUBLISH_TOTAL.labels(category=category, result=outcome).inc()
except ImportError:

    def _record(category: str, outcome: str) -> None:
        log.debug("prometheus_client unavailable; metric dropped")


# ── Chronicle digest ────────────────────────────────────────────────────


def build_chronicle_slug(week_start: date) -> str:
    """Deterministic slug for a chronicle weekly digest.

    ISO week numbers; same week always produces the same slug so
    re-publish is idempotent.
    """
    iso_year, iso_week, _ = week_start.isocalendar()
    return f"chronicle-{iso_year}-w{iso_week:02d}"


def build_chronicle_digest(
    *,
    events: list[dict[str, Any]],
    week_start: date,
    min_salience: float = 0.7,
) -> str:
    """Render a plain-text digest of high-salience chronicle events for
    the given ISO week. Returns empty string when no events qualify."""
    window_start = datetime.combine(week_start, datetime.min.time(), tzinfo=UTC)
    window_end = window_start + timedelta(days=7)

    filtered = []
    for ev in events:
        ts_str = ev.get("ts", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        salience = ev.get("salience", 0.0)
        if not isinstance(salience, (int, float)) or salience < min_salience:
            continue
        if not (window_start <= ts < window_end):
            continue
        filtered.append((ts, ev))

    if not filtered:
        return ""

    filtered.sort(key=lambda pair: pair[0])
    iso_year, iso_week, _ = week_start.isocalendar()

    lines = [
        f"# hapax chronicle — {iso_year} week {iso_week:02d}",
        "",
        f"{len(filtered)} high-salience moments ({min_salience:.2f} threshold).",
        "",
    ]
    for ts, ev in filtered:
        stamp = ts.strftime("%Y-%m-%d %H:%M")
        summary = ev.get("summary") or ev.get("narrative") or "(untitled)"
        source = ev.get("source", "unknown")
        lines.append(f"- {stamp} — [{source}] {summary}")

    lines.append("")
    lines.append(f"_digest compiled: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}_")
    return "\n".join(lines) + "\n"


def _load_events(path: Path) -> list[dict[str, Any]]:
    """Soft-read JSONL event log; skip malformed lines."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return []
    out: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


class PastebinArtifactPublisher:
    """Publish chronicle-weekly-digest pastes to omg.lol.

    Parameters:
        client:                  OmgLolClient (may be disabled)
        state_file:              per-publish state (idempotence tracking)
        read_events:             callable returning list[dict] events
        now_fn:                  callable returning current UTC datetime
        address:                 omg.lol address (default ``hapax``)
        min_salience:            event threshold for inclusion (default 0.7)
    """

    CATEGORY_CHRONICLE = "chronicle.weekly_digest"

    def __init__(
        self,
        *,
        client: Any,
        state_file: Path,
        read_events: Callable[[], list[dict[str, Any]]],
        now_fn: Callable[[], datetime],
        address: str = DEFAULT_ADDRESS,
        min_salience: float = 0.7,
    ) -> None:
        self.client = client
        self.state_file = state_file
        self._read_events = read_events
        self._now_fn = now_fn
        self.address = address
        self.min_salience = min_salience

    def _read_state(self) -> dict:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write_state(self, state: dict) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self.state_file)

    def publish_chronicle_week(self, week_start: date, *, dry_run: bool = False) -> str:
        """Compose + publish (or update) the digest for the given ISO week.

        Returns one of ``"published"`` | ``"unchanged"`` | ``"empty"`` |
        ``"allowlist-denied"`` | ``"client-disabled"`` | ``"dry-run"`` |
        ``"failed"``.
        """
        events = self._read_events()
        content = build_chronicle_digest(
            events=events, week_start=week_start, min_salience=self.min_salience
        )
        if not content:
            _record(self.CATEGORY_CHRONICLE, "empty")
            return "empty"

        slug = build_chronicle_slug(week_start)

        allow = allowlist_check(
            SURFACE,
            self.CATEGORY_CHRONICLE,
            {"summary": f"{slug}: {len(events)} events"},
        )
        if allow.decision == "deny":
            log.info("omg-pastebin: allowlist denied chronicle digest (%s)", allow.reason)
            _record(self.CATEGORY_CHRONICLE, "allowlist-denied")
            return "allowlist-denied"

        state_key = f"digest_sha_{slug}"
        import hashlib

        content_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        persisted = self._read_state()
        if persisted.get(state_key) == content_sha:
            _record(self.CATEGORY_CHRONICLE, "unchanged")
            return "unchanged"

        if dry_run:
            log.info(
                "omg-pastebin: dry-run — chronicle digest %s (sha %s…)",
                slug,
                content_sha[:8],
            )
            _record(self.CATEGORY_CHRONICLE, "dry-run")
            return "dry-run"

        if not getattr(self.client, "enabled", False):
            log.warning("omg-pastebin: client disabled — skipping publish")
            _record(self.CATEGORY_CHRONICLE, "client-disabled")
            return "client-disabled"

        resp = self.client.set_paste(self.address, content=content, title=slug, listed=True)
        if resp is None:
            log.warning("omg-pastebin: set_paste returned None (%s)", slug)
            _record(self.CATEGORY_CHRONICLE, "failed")
            return "failed"

        persisted[state_key] = content_sha
        self._write_state(persisted)
        log.info("omg-pastebin: published chronicle digest %s", slug)
        _record(self.CATEGORY_CHRONICLE, "published")
        return "published"

    def publish_current_week(self, *, dry_run: bool = False) -> str:
        """Convenience: publish digest for the ISO week containing now."""
        now = self._now_fn()
        iso_year, iso_week, _ = now.isocalendar()
        # Monday of the ISO week.
        week_start = date.fromisocalendar(iso_year, iso_week, 1)
        return self.publish_chronicle_week(week_start, dry_run=dry_run)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--week", help="ISO week-start date YYYY-MM-DD; defaults to current week")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--address", default=DEFAULT_ADDRESS)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    from shared.omg_lol_client import OmgLolClient

    publisher = PastebinArtifactPublisher(
        client=OmgLolClient(address=args.address),
        state_file=DEFAULT_STATE_FILE,
        read_events=lambda: _load_events(DEFAULT_CHRONICLE_FILE),
        now_fn=lambda: datetime.now(UTC),
        address=args.address,
    )

    if args.week:
        week_start = date.fromisoformat(args.week)
        outcome = publisher.publish_chronicle_week(week_start, dry_run=args.dry_run)
    else:
        outcome = publisher.publish_current_week(dry_run=args.dry_run)

    print(outcome)
    return 0


if __name__ == "__main__":
    sys.exit(main())
