"""Observe Claude subscription liveness from Claude Code's own session transcripts.

The estate's ``claude.review.opus`` / ``claude.headless.full`` routes are held by a
short-lived quota-admission receipt whose default TTL is 900 s. Minting it by hand does
not survive a CI + review + queue pipeline: measured 2026-08-11, ``claude`` was blocked at
a merge-gate evaluation **if and only if** no receipt was fresh at that instant -- 27 of 27
evaluations on one PR, seven of them missing by five minutes or less, with seven-day
coverage of 38% and a worst dark gap of 11.5 hours.

This module supplies the observation a cadence can honestly stand on, so the receipt stops
being an attestation somebody types and becomes a measurement something reads.

**What is observed, precisely.** ``hapax-claude-subscription-quota-admission`` defines its
default observation as *"a real Claude invocation completed without a subscription quota
wall"*. A completed assistant turn in a Claude Code transcript **is** that event: the
provider served a request at that timestamp and did not refuse it. So the observation is a
*liveness* witness -- non-exhaustion at time T -- and it is produced as a by-product of
work the estate is already doing, at zero provider cost.

**What is NOT observed, and this matters.** Not headroom *magnitude*. Claude Code carries a
``rateLimits`` field in its transcript schema and it is ``null`` in **157 of 157** records
on this host; there are no usage/limit files under ``~/.claude``. So the codex
``--from-rollout`` path -- which reads a real ``used_percent`` out of provider-written
session records -- **does not transfer**. Anyone reading PR #4545's "Claude Code has the
equivalent" line as licence to build a magnitude reader from disk will find nothing there.
That claim is about HTTP response headers, which are not persisted.

Fail-closed, three ways, each tested:

* **absent** -- no transcript, no parseable turn: refuse.
* **stale** -- the freshest completed turn is older than the caller's window: refuse.
  This is the honest behaviour when the estate is idle, which is exactly when nothing is
  asking for the route.
* **future** -- a turn stamped more than ``FUTURE_SKEW_TOLERANCE_SECONDS`` ahead of now is
  clock skew or a forged record: refuse rather than mint a receipt that outlives its
  evidence. Inside that tolerance the record is accepted, because an NTP step on the host
  writing the transcript is ordinary, but ``observed_at`` is clamped to the moment of the
  read -- a future stamp can never buy window it did not witness.

Content safety: only a ``timestamp`` is ever lifted out. Prompts, model output, tool calls
and file contents are never read into the return value, and reads are bounded tail seeks --
transcripts reach hundreds of megabytes.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_TRANSCRIPT_ROOT = Path(
    os.environ.get("HAPAX_CLAUDE_TRANSCRIPT_ROOT", str(Path.home() / ".claude" / "projects"))
)

TRANSCRIPT_GLOB = "*/*.jsonl"

#: Newest-first cap on how many transcript files to open. The freshest turn is
#: overwhelmingly in the most recently modified sessions; scanning every file on a host
#: with hundreds of sessions is unbounded work for no additional evidence.
TRANSCRIPT_SCAN_LIMIT = 12

#: Bounded tail read. Transcripts routinely exceed 100 MB and have reached 1.19 GB on this
#: estate; never read one whole.
TRANSCRIPT_TAIL_BYTES = 256 * 1024

#: Default freshness window for the observation itself.
DEFAULT_MAX_OBSERVATION_AGE_SECONDS = 900

#: Tolerance for a turn stamped slightly ahead of the local clock. Beyond this the record
#: is refused rather than trusted.
FUTURE_SKEW_TOLERANCE_SECONDS = 60


class TranscriptQuotaUnavailable(ValueError):
    """No trustworthy liveness observation is available. Fail closed; mint nothing."""


@dataclass(frozen=True)
class TranscriptObservation:
    """A completed Claude turn, reduced to the only two facts that may leave this module."""

    observed_at: datetime
    #: Stable, non-identifying witness label. Contains no prompt, output, or path.
    witness: str


def _parse_utc(value: object, *, truncate: bool = True) -> datetime | None:
    """Parse a transcript timestamp.

    ``truncate`` drops microseconds, which is right for anything that reaches a receipt: the
    receipt format carries whole seconds. It is WRONG for ordering two records against each
    other. Claude writes millisecond precision, so a wall at ``12:00:00.900`` and a success at
    ``12:00:00.100`` both truncate to ``12:00:00``, and the strict ``>`` deciding "is the newest
    record a failure" answers no. The wall stays invisible for the whole second it shares with a
    success — which is exactly the second in which a wall is most likely to appear, since the
    refusal usually follows the last served turn immediately.
    """

    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    parsed = parsed.astimezone(UTC)
    return parsed.replace(microsecond=0) if truncate else parsed


#: Record keys whose presence marks an assistant record as a provider FAILURE rather than a
#: served response. A key-presence test rather than a status allowlist, so an unfamiliar
#: error shape fails closed instead of reading as success.
API_ERROR_MARKER_KEYS = ("isApiErrorMessage", "apiErrorStatus", "error", "errorType")


def _is_api_error_record(record: dict) -> bool:
    """True when the record is a provider failure, however it is spelled.

    The 429 case is why this exists: it is *literally* the quota wall, so accepting it
    would mint "headroom observed" from the refusal itself. 401s, 5xx and synthetic
    client-side error records are refused by the same test for the same reason — none is
    evidence that the subscription served anything.
    """

    for key in API_ERROR_MARKER_KEYS:
        if record.get(key):
            return True
    message = record.get("message")
    return isinstance(message, dict) and bool(
        message.get("error") or message.get("type") == "error"
    )


def _completed_turn_timestamp(line: str) -> datetime | None:
    """Return the timestamp of a *successfully served* assistant turn, or None.

    Deliberately narrow, and the narrowness is the whole safety argument:

    * ``type == "assistant"`` — user turns and tool results witness nothing about the
      provider.
    * **not an API-error record.** Claude writes failures as assistant records too.
      Measured on this estate 2026-08-11 across all 92 transcripts: **1,070 API-error
      records carry a ``requestId``**, including ``apiErrorStatus: 429``. Accepting one
      would mint "subscription headroom observed" from the quota wall itself — the exact
      inversion of this module's claim. Checked first, before anything else is considered.
      Re-derive with::

          cat ~/.claude/projects/*/*.jsonl \\
            | jq -c 'select(.type=="assistant" and .requestId and
                            (.isApiErrorMessage or .apiErrorStatus or .error))' | wc -l

      Scan the whole population, not a sample: the same query over an arbitrary 60-file
      subset returns 17, which reads as a curiosity rather than a hazard. The count drifts
      as transcripts are written and pruned; what must not drift is that it exceeds zero,
      which is the entire reason this branch exists.
    * ``requestId`` present — a record without one never round-tripped to the provider.
    * a parseable ``timestamp``.
    """

    if '"assistant"' not in line:
        return None
    try:
        record = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(record, dict):
        return None
    if record.get("type") != "assistant":
        return None
    if _is_api_error_record(record):
        return None
    if not record.get("requestId"):
        return None
    # Full precision: this value is compared against a wall's timestamp, and truncating both to
    # the second makes a later wall in the same second compare equal rather than greater.
    return _parse_utc(record.get("timestamp"), truncate=False)


def _api_error_timestamp(line: str) -> datetime | None:
    """The timestamp of a provider FAILURE record, or None — the mirror of the above.

    ``_is_api_error_record`` was used only to FILTER errors out of the success scan. Filtering
    makes a wall invisible; it does not make it harmless. A 429 at 14:00 followed by nothing was
    skipped, so a completed turn at 13:00 became the observation and the receipt read
    "subscription headroom observed" — minted from a moment strictly before the wall it ignored.

    A completed turn is evidence the account was live *at that instant*. A later failure
    supersedes it, because the question a receipt answers is whether the subscription is serving
    NOW, not whether it ever did.
    """

    if '"assistant"' not in line:
        return None
    try:
        record = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(record, dict):
        return None
    if record.get("type") != "assistant":
        return None
    if not _is_api_error_record(record):
        return None
    return _parse_utc(record.get("timestamp"), truncate=False)


def _tail_lines(path: Path, *, tail_bytes: int = TRANSCRIPT_TAIL_BYTES) -> list[str]:
    try:
        size = path.stat().st_size
    except OSError:
        return []
    try:
        with path.open("rb") as handle:
            if size > tail_bytes:
                handle.seek(size - tail_bytes)
                handle.readline()  # discard the partial line the seek landed inside
            payload = handle.read()
    except OSError:
        return []
    return payload.decode("utf-8", errors="replace").splitlines()


def latest_transcript_observation(
    *,
    root: Path | None = None,
    now: datetime | None = None,
    max_age_seconds: int = DEFAULT_MAX_OBSERVATION_AGE_SECONDS,
    scan_limit: int = TRANSCRIPT_SCAN_LIMIT,
    session_id: str = "",
) -> TranscriptObservation:
    """Freshest completed-turn witness, or raise :class:`TranscriptQuotaUnavailable`.

    ``session_id`` restricts the scan to one session's transcript, whose file is named for its
    id. That narrowing is what lets a caller pair this observation with an auth-surface check of
    its OWN environment: the observing process runs inside that session and inherits its
    environment, so the credential facts it can see are the ones those turns were served under.
    Scanning every transcript on the host breaks that pairing silently — the freshest turn may
    come from a session started with entirely different credentials, or by a different tool.
    """

    checked_at = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    search_root = root or DEFAULT_TRANSCRIPT_ROOT

    try:
        pattern = f"*/{session_id}.jsonl" if session_id else TRANSCRIPT_GLOB
        files = [p for p in search_root.glob(pattern) if p.is_file()]
    except OSError as exc:
        raise TranscriptQuotaUnavailable(
            f"transcript root unreadable: {type(exc).__name__}"
        ) from exc
    if not files:
        if session_id:
            raise TranscriptQuotaUnavailable(
                f"no transcript for session {session_id} under {search_root}; this session has "
                "not written one yet. Next: complete a turn in this session, then re-observe"
            )
        raise TranscriptQuotaUnavailable("no Claude Code transcripts found")

    files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)

    newest: datetime | None = None
    newest_wall: datetime | None = None
    for path in files[:scan_limit]:
        for line in _tail_lines(path):
            stamp = _completed_turn_timestamp(line)
            if stamp is not None and (newest is None or stamp > newest):
                newest = stamp
                continue
            wall = _api_error_timestamp(line)
            if wall is not None and (newest_wall is None or wall > newest_wall):
                newest_wall = wall

    if newest is None:
        raise TranscriptQuotaUnavailable("no completed assistant turn in the scanned transcripts")

    # A WALL AFTER YOUR LAST SUCCESS MEANS YOU ARE WALLED NOW.
    #
    # Errors were already excluded from counting as successes, which is necessary and was not
    # sufficient: filtering makes a wall invisible, not harmless. Skipping a 429 at 14:00 left a
    # completed turn at 13:00 as the freshest observation, and the receipt then attested headroom
    # from a moment strictly before the refusal it had just stepped over.
    #
    # Ordering is the whole predicate. A wall BEFORE the last success is history — the account
    # recovered, and the success proves it. A wall AFTER it is the current state.
    if newest_wall is not None and newest_wall > newest:
        raise TranscriptQuotaUnavailable(
            f"the newest provider record is a failure at {newest_wall.isoformat()}, after the "
            f"last completed turn at {newest.isoformat()}; that is a quota wall, not headroom. "
            "Next: complete a turn on this subscription, then re-observe"
        )

    age = (checked_at - newest).total_seconds()
    if age < -FUTURE_SKEW_TOLERANCE_SECONDS:
        raise TranscriptQuotaUnavailable(
            f"freshest completed turn is {abs(age):.0f}s in the future; refusing on clock skew"
        )
    if age > max_age_seconds:
        raise TranscriptQuotaUnavailable(
            f"freshest completed turn is {age:.0f}s old, beyond the {max_age_seconds}s window"
        )

    # Within tolerance a future stamp is accepted but never *credited*: clamping to
    # `checked_at` means sub-tolerance skew can shorten the receipt's window, never extend
    # it past the moment we actually looked. Without this, a turn stamped 59 s ahead buys
    # 59 s of window backed by nothing observed.
    # Truncated only here, at the boundary where the value becomes a receipt field. Ordering above
    # ran at full precision; a whole-second stamp is what the receipt format carries, and rounding
    # DOWN never buys window that was not witnessed.
    observed_at = min(newest, checked_at).replace(microsecond=0)

    return TranscriptObservation(
        observed_at=observed_at,
        witness=(
            "claude-subscription-headroom-observed-"
            f"{observed_at.strftime('%Y%m%dt%H%M%S').lower()}z"
        ),
    )
