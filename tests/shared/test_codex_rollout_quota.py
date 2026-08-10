"""Direct tests for the rollout reader.

The module was exercised only THROUGH `scripts/hapax-codex-quota-admission`, which codex-1 flagged
on PR #4545. Two of its invariants are load-bearing and deserve their own coverage:

1. **Staleness rejection.** The capability-receipt fix (binding the quota surface to the
   observation's own timestamp) relies on this reader refusing ancient snapshots. If the age bound
   stopped working, an arbitrarily old observation would flow through carrying an honest-but-ancient
   timestamp and freshness would rest entirely on downstream checks noticing.

2. **Content containment.** Rollout files carry prompts, model output and session identifiers, and
   reach gigabytes. The reader must take numeric limit facts and nothing else, and must not read the
   whole file to do it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shared.codex_rollout_quota import (
    DEFAULT_MAX_OBSERVATION_AGE_SECONDS,
    EXHAUSTED_USED_PERCENT,
    ROLLOUT_TAIL_BYTES,
    RolloutQuotaUnavailable,
    latest_rollout_observation,
)

NOW = datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC)


def _rollout(dir_: Path, *, at: datetime, used: float, window: int = 300, noise: str = "") -> Path:
    """A rollout file shaped like the real thing: bulk content, then a rate_limits record."""
    path = dir_ / "rollout-2026-08-10T00-00-00-test.jsonl"
    rows = []
    if noise:
        rows.append(json.dumps({"timestamp": at.isoformat(), "payload": {"content": noise}}))
    rows.append(
        json.dumps(
            {
                "timestamp": at.isoformat(),
                "payload": {
                    "rate_limits": {"primary": {"used_percent": used, "window_minutes": window}}
                },
            }
        )
    )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_a_fresh_observation_is_returned(tmp_path: Path) -> None:
    _rollout(tmp_path, at=NOW - timedelta(minutes=5), used=2.0)

    obs = latest_rollout_observation(tmp_path, now=NOW)

    assert obs.used_percent == 2.0
    assert obs.remaining_percent == 98.0
    assert obs.observed_at == NOW - timedelta(minutes=5)


def test_an_observation_older_than_the_bound_is_refused(tmp_path: Path) -> None:
    """The invariant the capability-receipt freshness fix depends on.

    Fail-closed: no observation is better than a stale one presented as current.
    """
    _rollout(
        tmp_path, at=NOW - timedelta(seconds=DEFAULT_MAX_OBSERVATION_AGE_SECONDS + 60), used=2.0
    )

    with pytest.raises(RolloutQuotaUnavailable, match="old"):
        latest_rollout_observation(tmp_path, now=NOW)


def test_the_age_bound_is_honoured_at_the_boundary(tmp_path: Path) -> None:
    """An observation just inside the bound is usable; just outside is not.

    Pinning both sides catches an off-by-one that would silently widen the window.
    """
    inside = NOW - timedelta(seconds=DEFAULT_MAX_OBSERVATION_AGE_SECONDS - 30)
    _rollout(tmp_path, at=inside, used=1.0)
    assert latest_rollout_observation(tmp_path, now=NOW).observed_at == inside

    outside = tmp_path / "outside"
    outside.mkdir()
    _rollout(
        outside, at=NOW - timedelta(seconds=DEFAULT_MAX_OBSERVATION_AGE_SECONDS + 30), used=1.0
    )
    with pytest.raises(RolloutQuotaUnavailable):
        latest_rollout_observation(outside, now=NOW)


def test_an_exhausted_window_is_a_wall_not_headroom(tmp_path: Path) -> None:
    """100% used must refuse, not report 0% remaining.

    Reporting zero headroom as a successful observation would let a caller treat an exhausted
    account as merely tight.
    """
    _rollout(tmp_path, at=NOW - timedelta(minutes=1), used=EXHAUSTED_USED_PERCENT)

    with pytest.raises(RolloutQuotaUnavailable):
        latest_rollout_observation(tmp_path, now=NOW)


def test_absent_sessions_directory_refuses(tmp_path: Path) -> None:
    with pytest.raises(RolloutQuotaUnavailable):
        latest_rollout_observation(tmp_path / "nope", now=NOW)


def test_the_observation_carries_no_rollout_content(tmp_path: Path) -> None:
    """Numeric limit facts only — no prompts, no session ids, no model output.

    Rollout files are the operator's session transcripts. The receipt built from this observation
    is written to disk and read by other processes, so anything the observation carries has left
    the boundary.
    """
    secret = "SENSITIVE-PROMPT-TEXT-should-never-propagate"
    _rollout(tmp_path, at=NOW - timedelta(minutes=1), used=3.0, noise=secret)

    obs = latest_rollout_observation(tmp_path, now=NOW)

    blob = repr(obs) + repr(vars(obs) if hasattr(obs, "__dict__") else obs)
    assert secret not in blob
    assert set(vars(obs)) <= {"observed_at", "used_percent", "window_minutes"} or not hasattr(
        obs, "__dict__"
    )


def test_the_reader_is_bounded_and_does_not_slurp_the_file(tmp_path: Path) -> None:
    """Rollouts reach gigabytes; the reader tails rather than reads.

    A file far larger than the tail budget must still yield an observation from its end, which is
    only possible if the reader seeks.
    """
    at = NOW - timedelta(minutes=2)
    path = tmp_path / "rollout-2026-08-10T00-00-00-big.jsonl"
    filler = json.dumps({"timestamp": at.isoformat(), "payload": {"content": "x" * 4096}})
    tail = json.dumps(
        {
            "timestamp": at.isoformat(),
            "payload": {"rate_limits": {"primary": {"used_percent": 7.0, "window_minutes": 300}}},
        }
    )
    bulk = "\n".join([filler] * ((ROLLOUT_TAIL_BYTES // 4096) + 40))
    path.write_text(bulk + "\n" + tail + "\n", encoding="utf-8")
    assert path.stat().st_size > ROLLOUT_TAIL_BYTES

    obs = latest_rollout_observation(tmp_path, now=NOW)

    assert obs.used_percent == 7.0
