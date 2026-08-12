"""Fail-closed behaviour of the Claude transcript liveness observer.

Every test here pins a refusal except the first. That ratio is the point: the observer
exists so a cadence can mint honestly, which means it must decline far more often than it
speaks.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shared.claude_transcript_quota import (
    TRANSCRIPT_TAIL_BYTES,
    TranscriptQuotaUnavailable,
    latest_transcript_observation,
)

NOW = datetime(2026, 8, 11, 17, 0, 0, tzinfo=UTC)


def _turn(stamp: datetime, *, request_id: str = "req_abc", kind: str = "assistant") -> str:
    return json.dumps(
        {
            "type": kind,
            "requestId": request_id,
            "timestamp": stamp.isoformat().replace("+00:00", "Z"),
            "message": {"role": "assistant", "content": [{"type": "text", "text": "x"}]},
        }
    )


def _api_error_turn(
    stamp: datetime,
    *,
    status: int = 429,
    request_id: str = "req_011CdiW8GZnWNgHXsWSshnLf",
) -> str:
    """An API-ERROR assistant record, in the shape Claude Code actually writes.

    Field names and the coexistence of `requestId` with `isApiErrorMessage` were taken
    from real transcripts on this estate, not invented: 1,070 such records carry a
    requestId, across statuses including 429 and 401. Inventing this fixture from the
    happy path is precisely how the defect these tests pin got shipped.
    """
    return json.dumps(
        {
            "type": "assistant",
            "requestId": request_id,
            "timestamp": stamp.isoformat().replace("+00:00", "Z"),
            "isApiErrorMessage": True,
            "apiErrorStatus": status,
            "message": {"role": "assistant", "content": [{"type": "text", "text": "API Error"}]},
        }
    )


def _write(root: Path, name: str, lines: list[str]) -> Path:
    path = root / "proj" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_fresh_completed_turn_is_observed_and_stamped_with_the_turns_own_time(
    tmp_path: Path,
) -> None:
    """observed_at is the turn's timestamp, never `now` -- a later stamp overstates
    freshness and would hand the receipt a window its evidence does not support."""
    stamp = NOW - timedelta(seconds=120)
    _write(tmp_path, "a.jsonl", [_turn(stamp)])

    obs = latest_transcript_observation(root=tmp_path, now=NOW, max_age_seconds=900)

    assert obs.observed_at == stamp
    # The stamp is the turn's, not `now` -- 120 s in the past, which is the whole contract.
    assert (NOW - obs.observed_at).total_seconds() == pytest.approx(120.0)


def test_newest_turn_wins_across_files(tmp_path: Path) -> None:
    older = NOW - timedelta(seconds=600)
    newer = NOW - timedelta(seconds=30)
    _write(tmp_path, "a.jsonl", [_turn(older)])
    _write(tmp_path, "b.jsonl", [_turn(newer)])

    obs = latest_transcript_observation(root=tmp_path, now=NOW, max_age_seconds=900)

    assert obs.observed_at == newer


def test_absent_transcripts_refuse(tmp_path: Path) -> None:
    with pytest.raises(TranscriptQuotaUnavailable, match="no Claude Code transcripts"):
        latest_transcript_observation(root=tmp_path, now=NOW)


def test_stale_turn_refuses(tmp_path: Path) -> None:
    """The estate being idle is not evidence of headroom. This is the case that keeps a
    timer honest: no recent turn, no receipt."""
    _write(tmp_path, "a.jsonl", [_turn(NOW - timedelta(seconds=5000))])

    with pytest.raises(TranscriptQuotaUnavailable, match="beyond the"):
        latest_transcript_observation(root=tmp_path, now=NOW, max_age_seconds=900)


def test_future_turn_refuses_on_clock_skew(tmp_path: Path) -> None:
    """A record ahead of the clock is skew or forgery. Minting from it would produce a
    receipt that outlives its own evidence."""
    _write(tmp_path, "a.jsonl", [_turn(NOW + timedelta(seconds=3600))])

    with pytest.raises(TranscriptQuotaUnavailable, match="future"):
        latest_transcript_observation(root=tmp_path, now=NOW, max_age_seconds=900)


def test_a_turn_inside_skew_tolerance_is_accepted_but_never_credits_future_time(
    tmp_path: Path,
) -> None:
    """The reconciliation of the tolerance with the contract.

    A stamp 30 s ahead of the read is ordinary NTP behaviour on the host writing the
    transcript, so it is not refused. But crediting it verbatim would hand the receipt 30 s
    of window backed by nothing observed -- so `observed_at` is clamped to the read, and the
    witness label follows it rather than the raw stamp.
    """
    _write(tmp_path, "a.jsonl", [_turn(NOW + timedelta(seconds=30))])

    obs = latest_transcript_observation(root=tmp_path, now=NOW, max_age_seconds=900)

    assert obs.observed_at == NOW
    assert obs.witness == f"claude-subscription-headroom-observed-{NOW:%Y%m%dt%H%M%S}z".lower()


def test_a_429_is_never_read_as_headroom(tmp_path: Path) -> None:
    """The inversion this module exists to avoid, pinned.

    A 429 assistant record IS the quota wall. It carries `type: assistant`, a real
    `requestId` and a timestamp, so every check except the error discriminator passes it.
    Minting from one would report "subscription headroom observed" at the exact moment the
    subscription refused to serve.
    """
    _write(tmp_path, "a.jsonl", [_api_error_turn(NOW - timedelta(seconds=10), status=429)])

    with pytest.raises(TranscriptQuotaUnavailable, match="no completed assistant turn"):
        latest_transcript_observation(root=tmp_path, now=NOW, max_age_seconds=900)


def test_a_401_is_never_read_as_headroom(tmp_path: Path) -> None:
    """Not a denylist of one status: any provider failure is refused."""
    _write(tmp_path, "a.jsonl", [_api_error_turn(NOW - timedelta(seconds=10), status=401)])

    with pytest.raises(TranscriptQuotaUnavailable, match="no completed assistant turn"):
        latest_transcript_observation(root=tmp_path, now=NOW, max_age_seconds=900)


def test_an_unfamiliar_error_shape_fails_closed(tmp_path: Path) -> None:
    """Key-presence, not status-matching: an error field we have never seen still refuses."""
    line = json.dumps(
        {
            "type": "assistant",
            "requestId": "req_zzz",
            "timestamp": (NOW - timedelta(seconds=10)).isoformat().replace("+00:00", "Z"),
            "errorType": "some_future_failure_mode",
        }
    )
    _write(tmp_path, "a.jsonl", [line])

    with pytest.raises(TranscriptQuotaUnavailable, match="no completed assistant turn"):
        latest_transcript_observation(root=tmp_path, now=NOW, max_age_seconds=900)


def test_a_wall_after_the_last_success_refuses(tmp_path: Path) -> None:
    """This test asserted the opposite, and the opposite was wrong.

    It read "the error must be skipped and the older *successful* turn returned" — the behaviour
    codex-1 filed as a critical on PR #4555, correctly. Excluding errors from counting as
    successes is necessary and not sufficient: filtering makes a wall invisible, not harmless. A
    429 at 14:00 skipped, with a completed turn at 13:00 returned, mints "subscription headroom
    observed" from a moment strictly before the refusal it stepped over.

    This module's own docstring names that inversion — accepting a 429 "would mint headroom from
    the quota wall itself". Substituting an earlier success is the softer form of the same error:
    the wall still produces a positive receipt.

    A receipt answers whether the subscription is serving NOW. A completed turn is evidence the
    account was live at that instant; a later failure supersedes it.
    """
    served = NOW - timedelta(seconds=300)
    _write(
        tmp_path,
        "a.jsonl",
        [_turn(served), _api_error_turn(NOW - timedelta(seconds=5), status=429)],
    )

    with pytest.raises(TranscriptQuotaUnavailable, match="quota wall"):
        latest_transcript_observation(root=tmp_path, now=NOW, max_age_seconds=900)


def test_a_wall_before_the_last_success_is_history(tmp_path: Path) -> None:
    """Ordering is the whole predicate, so the other order must still succeed.

    A wall the account recovered from is history, and the later completed turn is the proof. If
    this refused too, the fix would be a blanket refusal wearing a predicate's clothes.
    """
    walled = NOW - timedelta(seconds=300)
    served = NOW - timedelta(seconds=5)
    _write(tmp_path, "a.jsonl", [_api_error_turn(walled, status=429), _turn(served)])

    obs = latest_transcript_observation(root=tmp_path, now=NOW, max_age_seconds=900)

    assert obs.observed_at == served


def test_turn_without_request_id_is_not_evidence(tmp_path: Path) -> None:
    """No requestId means the turn never round-tripped to the provider, so it witnesses
    nothing about whether the provider served anything."""
    line = json.dumps(
        {
            "type": "assistant",
            "timestamp": (NOW - timedelta(seconds=10)).isoformat().replace("+00:00", "Z"),
        }
    )
    _write(tmp_path, "a.jsonl", [line])

    with pytest.raises(TranscriptQuotaUnavailable, match="no completed assistant turn"):
        latest_transcript_observation(root=tmp_path, now=NOW, max_age_seconds=900)


def test_non_assistant_records_are_ignored(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "a.jsonl",
        [_turn(NOW - timedelta(seconds=10), kind="user")],
    )

    with pytest.raises(TranscriptQuotaUnavailable, match="no completed assistant turn"):
        latest_transcript_observation(root=tmp_path, now=NOW, max_age_seconds=900)


def test_malformed_lines_do_not_crash_the_scan(tmp_path: Path) -> None:
    stamp = NOW - timedelta(seconds=45)
    _write(tmp_path, "a.jsonl", ["{not json", "", "null", _turn(stamp)])

    obs = latest_transcript_observation(root=tmp_path, now=NOW, max_age_seconds=900)

    assert obs.observed_at == stamp


def test_no_transcript_content_reaches_the_observation(tmp_path: Path) -> None:
    """Transcripts hold operator prompts and model output. Only a timestamp may leave."""
    secret = "SUPER-SECRET-PROMPT-TEXT-do-not-persist"
    line = json.dumps(
        {
            "type": "assistant",
            "requestId": "req_zzz",
            "timestamp": (NOW - timedelta(seconds=20)).isoformat().replace("+00:00", "Z"),
            "cwd": "/home/someone/private-project",
            "message": {"role": "assistant", "content": [{"type": "text", "text": secret}]},
        }
    )
    _write(tmp_path, "a.jsonl", [line])

    obs = latest_transcript_observation(root=tmp_path, now=NOW, max_age_seconds=900)

    rendered = f"{obs!r} {obs.witness}"
    assert secret not in rendered
    assert "private-project" not in rendered
    assert "req_zzz" not in rendered


def test_witness_label_is_derived_from_the_timestamp_only(tmp_path: Path) -> None:
    """The witness must match the admission writer's allowlist regex, which refuses
    lane/tmux/session names outright."""
    stamp = datetime(2026, 8, 11, 16, 47, 25, tzinfo=UTC)
    _write(tmp_path, "a.jsonl", [_turn(stamp)])

    obs = latest_transcript_observation(root=tmp_path, now=stamp + timedelta(seconds=5))

    assert obs.witness == "claude-subscription-headroom-observed-20260811t164725z"


def test_newest_turn_in_a_large_transcript_is_found_from_the_tail(tmp_path: Path) -> None:
    """Transcripts have reached 1.19 GB on this estate; a whole-file read is a hazard, not a
    performance note. Bounding the read must not cost us the newest turn."""
    stamp = NOW - timedelta(seconds=15)
    filler = [json.dumps({"type": "user", "pad": "x" * 512}) for _ in range(4000)]
    _write(tmp_path, "a.jsonl", [*filler, _turn(stamp)])

    obs = latest_transcript_observation(root=tmp_path, now=NOW, max_age_seconds=900)

    assert obs.observed_at == stamp


def test_content_beyond_the_tail_bound_is_never_read(tmp_path: Path) -> None:
    """The bound itself, pinned by a turn the observer must NOT see.

    The test above passes under a whole-file read, so it pins nothing about boundedness.
    Here the *newest* turn sits at the head of the file, behind more than
    TRANSCRIPT_TAIL_BYTES of filler, and an older turn sits at the tail. A whole-file read
    returns the head turn; a bounded tail read returns the older one. Asserting the OLDER
    stamp is the only assertion that can distinguish them.
    """
    head_stamp = NOW - timedelta(seconds=10)
    tail_stamp = NOW - timedelta(seconds=300)
    pad = json.dumps({"type": "user", "pad": "x" * 1024})
    filler_lines = (TRANSCRIPT_TAIL_BYTES // (len(pad) + 1)) + 64
    filler = [pad] * filler_lines
    path = _write(tmp_path, "a.jsonl", [_turn(head_stamp), *filler, _turn(tail_stamp)])

    # The premise of the test: the head turn really is outside the window that gets read.
    assert path.stat().st_size > TRANSCRIPT_TAIL_BYTES

    obs = latest_transcript_observation(root=tmp_path, now=NOW, max_age_seconds=900)

    assert obs.observed_at == tail_stamp
    assert obs.observed_at != head_stamp


def test_a_session_scoped_scan_ignores_other_sessions(tmp_path: Path) -> None:
    """The narrowing that makes auth evidence apply to the turns being read.

    A fresher turn in another session was served under credentials the observing process never
    saw. Reading it pairs an auth check of THIS environment with a subject it never covered —
    the whole finding — and it fails silently, because the newer turn simply wins.
    """
    mine = "8e98d395-97d6-4ff0-9619-e61927dcfdb0"
    _write(tmp_path, f"{mine}.jsonl", [_turn(NOW - timedelta(seconds=300))])
    _write(tmp_path, "other-session.jsonl", [_turn(NOW - timedelta(seconds=5))])

    obs = latest_transcript_observation(
        root=tmp_path, now=NOW, max_age_seconds=900, session_id=mine
    )

    assert obs.observed_at == (NOW - timedelta(seconds=300)).replace(microsecond=0), (
        "a fresher turn from another session was used"
    )


def test_a_session_with_no_transcript_refuses_rather_than_widening(tmp_path: Path) -> None:
    """Falling back to every transcript on the host is the failure this scoping exists to
    prevent, so a missing session transcript must refuse rather than quietly scan wider."""
    _write(tmp_path, "other-session.jsonl", [_turn(NOW - timedelta(seconds=5))])

    with pytest.raises(TranscriptQuotaUnavailable, match="no transcript for session"):
        latest_transcript_observation(
            root=tmp_path, now=NOW, max_age_seconds=900, session_id="not-a-session"
        )


def test_a_wall_later_in_the_same_second_still_supersedes(tmp_path: Path) -> None:
    """The sub-second case, which whole-second truncation hid.

    Claude writes millisecond precision. Both stamps below truncate to the same second, so the
    strict `newest_wall > newest` comparison answered "no wall" and the receipt was minted from a
    success the refusal had already overtaken. This is the likeliest ordering in practice: a wall
    normally arrives immediately after the last turn the account was served.
    """
    served = NOW - timedelta(seconds=300)
    walled = served + timedelta(milliseconds=400)
    assert served.replace(microsecond=0) == walled.replace(microsecond=0), (
        "this test is meaningless unless both stamps fall inside one second"
    )
    _write(tmp_path, "a.jsonl", [_turn(served), _api_error_turn(walled, status=429)])

    with pytest.raises(TranscriptQuotaUnavailable, match="quota wall"):
        latest_transcript_observation(root=tmp_path, now=NOW, max_age_seconds=900)


def test_a_wall_earlier_in_the_same_second_does_not_block(tmp_path: Path) -> None:
    """The other direction, and why this is ordering rather than presence.

    A wall BEFORE the last success is history: the account recovered, and the success proves it.
    Full precision has to distinguish the two orderings inside one second, not refuse both.
    """
    walled = NOW - timedelta(seconds=300)
    served = walled + timedelta(milliseconds=400)
    _write(tmp_path, "a.jsonl", [_api_error_turn(walled, status=429), _turn(served)])

    obs = latest_transcript_observation(root=tmp_path, now=NOW, max_age_seconds=900)

    assert obs.observed_at == served.replace(microsecond=0)


def test_the_receipt_timestamp_is_still_whole_seconds(tmp_path: Path) -> None:
    """Precision is for ordering; the receipt format carries whole seconds.

    Truncating at the boundary rather than at parse time keeps both true, and rounding DOWN never
    buys window that was not witnessed.
    """
    served = NOW - timedelta(seconds=300) + timedelta(milliseconds=750)
    _write(tmp_path, "a.jsonl", [_turn(served)])

    obs = latest_transcript_observation(root=tmp_path, now=NOW, max_age_seconds=900)

    assert obs.observed_at.microsecond == 0
    assert obs.observed_at <= served
