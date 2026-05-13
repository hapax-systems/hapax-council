"""omg.lol statuslog public-safe fanout.

Periodic write of public-safe awareness summary to the operator's
omg.lol statuslog. Reads ``/dev/shm/hapax-awareness/state.json`` (the
canonical state spine), runs every block through
:func:`agents.operator_awareness.public_filter.public_filter`, then
posts a compact statuslog entry.

Constitutional invariants:

* **Server-side filter only.** ``public_filter`` is applied here on
  the daemon side; never trust a client to redact. The
  module-level test ``test_no_private_field_reaches_output`` pins
  this against accidental schema drift.
* **No marketing voice.** Status text is factual and ambient — no
  "today I felt..." prose. Anti-anthropomorphization is constitutional
  per the ``feedback_full_automation_or_no_engagement`` directive.
* **Append-only fanout.** No edit, no delete, no scheduled-summary
  cadence beyond the hourly tick. Operator never curates.
* **Skip-if-no-change.** Hash the rendered public payload; skip the
  POST when identical to the last successful post — saves API
  budget and prevents the statuslog from filling with noise during
  steady state.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any

import requests

from agents.operator_awareness.public_filter import public_filter
from agents.operator_awareness.state import AwarenessState
from agents.publication_bus.omg_statuslog_publisher import (
    OMG_STATUSLOG_API_URL,
    OmgLolStatuslogPublisher,
)
from agents.publication_bus.publisher_kit import PublisherPayload

log = logging.getLogger(__name__)

OMG_LOL_API_URL = OMG_STATUSLOG_API_URL

# Statuslog character budget. omg.lol's hard cap is ~500; we render
# under 280 (Mastodon-compatible) so cross-fanout (Bridgy etc.) is
# also safe. The renderer bails to a truncated form rather than
# splitting across multiple posts.
STATUS_TEXT_BUDGET = 280

DEFAULT_STATE_PATH = Path(
    os.environ.get(
        "HAPAX_AWARENESS_STATE_PATH",
        "/dev/shm/hapax-awareness/state.json",
    )
)

# Last-post hash sidecar — lives in tmpfs alongside the state spine.
# Used by skip-if-unchanged gating; absent on first run so the first
# tick always posts.
DEFAULT_LAST_HASH_PATH = Path(
    os.environ.get(
        "HAPAX_OMG_LOL_LAST_HASH_PATH",
        "/dev/shm/hapax-awareness/omg-lol-last-hash.txt",
    )
)


# Per-outcome posts counter. Optional dependency: minimal test envs
# may not have prometheus_client; the daemon still works in that case
# and falls back to log-only observability.
hapax_awareness_omg_lol_posts_total: Any = None
try:
    from prometheus_client import Counter as _OmgCounter

    hapax_awareness_omg_lol_posts_total = _OmgCounter(
        "hapax_awareness_omg_lol_posts_total",
        "omg.lol statuslog fanout post outcomes.",
        ["result"],
    )
except Exception:
    pass


def _record(result: str) -> None:
    if hapax_awareness_omg_lol_posts_total is None:
        return
    try:
        hapax_awareness_omg_lol_posts_total.labels(result=result).inc()
    except Exception:
        pass


def render_status(state: AwarenessState) -> str:
    """Render the public-safe awareness state as a status string.

    Format is fixed and deterministic — every consumer (omg.lol web
    UI, Bridgy fanout, Mastodon mirror) sees the same shape. The
    string MUST fit ``STATUS_TEXT_BUDGET`` so cross-surface posting
    doesn't truncate mid-content.
    """
    public = public_filter(state)
    parts: list[str] = []
    parts.append(f"hapax · {public.timestamp.strftime('%H:%MZ')}")
    if public.stream.live:
        parts.append("stream live")
    if public.daimonion_voice.stance and public.daimonion_voice.stance != "unknown":
        parts.append(f"stance {public.daimonion_voice.stance}")
    if public.health_system.overall_status not in ("unknown", ""):
        parts.append(f"health {public.health_system.overall_status}")
    if public.refusals_recent:
        parts.append(f"{len(public.refusals_recent)} refusals on file")
    body = " · ".join(parts)
    if len(body) > STATUS_TEXT_BUDGET:
        body = body[: STATUS_TEXT_BUDGET - 1] + "…"
    return body


def _content_hash(text: str) -> str:
    """Stable hash for the skip-if-unchanged gate."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_last_hash(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _write_last_hash(path: Path, value: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    except OSError:
        log.debug("could not persist omg.lol last-hash sidecar at %s", path)


def fanout(
    state: AwarenessState,
    *,
    address: str,
    token: str,
    last_hash_path: Path = DEFAULT_LAST_HASH_PATH,
    skip_mastodon: bool = True,
    timeout_s: float = 10.0,
    session: requests.Session | None = None,
) -> str:
    """Post one public-safe status entry. Return the outcome label.

    Outcome labels (also recorded on
    :data:`hapax_awareness_omg_lol_posts_total`):

    * ``ok`` — POST returned 2xx; sidecar updated
    * ``skipped`` — payload hash matches the last successful post
    * ``http_error`` — non-2xx response from omg.lol
    * ``network_error`` — request raised (timeout, DNS, etc.)
    """
    text = render_status(state)
    h = _content_hash(text)
    if _read_last_hash(last_hash_path) == h:
        _record("skipped")
        return "skipped"

    publisher = OmgLolStatuslogPublisher(session=session or requests)
    result = publisher.publish(
        PublisherPayload(
            target=address,
            text=text,
            metadata={
                "token": token,
                "skip_mastodon_post": skip_mastodon,
                "timeout_s": timeout_s,
            },
        )
    )
    if result.ok:
        _write_last_hash(last_hash_path, h)
        _record("ok")
        return "ok"
    if result.refused:
        _record("refused")
        return "refused"
    if result.detail.startswith("network_error"):
        _record("network_error")
        return "network_error"
    if result.detail.startswith("http_error"):
        _record("http_error")
        return "http_error"
    _record("error")
    return "error"


def fanout_once(
    state_path: Path = DEFAULT_STATE_PATH,
    *,
    address: str | None = None,
    token: str | None = None,
    last_hash_path: Path = DEFAULT_LAST_HASH_PATH,
) -> str:
    """Single-tick fanout entry — read state.json + post once.

    Reads the canonical awareness state from ``state_path``,
    pulls credentials from ``HAPAX_OMG_LOL_ADDRESS`` and
    ``HAPAX_OMG_LOL_TOKEN`` env vars when not passed explicitly
    (the systemd timer wires this via the secrets EnvironmentFile),
    and delegates to :func:`fanout`. Designed for hourly invocation
    from ``hapax-omg-lol-fanout.service`` — exits 0 on any outcome
    (fanout treats network errors as "skip this hour" to avoid
    timer-restart loops on transient API outages).

    Returns the same outcome label as :func:`fanout`, plus
    ``"no_state"`` when the awareness spine hasn't published yet
    and ``"no_creds"`` when env vars are missing.
    """
    if address is None:
        address = os.environ.get("HAPAX_OMG_LOL_ADDRESS", "")
    if token is None:
        token = os.environ.get("HAPAX_OMG_LOL_TOKEN", "")
    if not address or not token:
        log.info("omg.lol fanout skipped: missing address/token env vars")
        _record("no_creds")
        return "no_creds"
    if not state_path.exists():
        log.info("omg.lol fanout skipped: %s does not exist yet", state_path)
        _record("no_state")
        return "no_state"
    try:
        state = AwarenessState.model_validate_json(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("omg.lol fanout skipped: cannot parse %s", state_path, exc_info=True)
        _record("no_state")
        return "no_state"
    return fanout(
        state,
        address=address,
        token=token,
        last_hash_path=last_hash_path,
    )


def main() -> int:
    """CLI entry: ``uv run python -m agents.operator_awareness.omg_lol_fanout``."""
    logging.basicConfig(
        level=os.environ.get("HAPAX_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    outcome = fanout_once()
    log.info("omg.lol fanout outcome: %s", outcome)
    # Always exit 0 — the systemd timer should fire on cadence, not
    # crash-restart on a single bad tick. Outcomes are visible via
    # the Prometheus counter + journalctl.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_LAST_HASH_PATH",
    "DEFAULT_STATE_PATH",
    "OMG_LOL_API_URL",
    "STATUS_TEXT_BUDGET",
    "fanout",
    "fanout_once",
    "hapax_awareness_omg_lol_posts_total",
    "main",
    "render_status",
]
