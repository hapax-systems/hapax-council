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
    _head_lines,
    latest_model_observation,
    latest_rollout_observation,
)

NOW = datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC)


#: Sentinel for "omit the key entirely", distinct from a present-and-null `secondary`. Real
#: rollouts write the key explicitly as null, so that -- not omission -- is the fixture default.
_OMIT = object()


def _rollout(
    dir_: Path,
    *,
    at: datetime,
    used: float,
    window: int = 300,
    noise: str = "",
    limit_id: str | None = "codex",
    secondary: object = None,
) -> Path:
    """A rollout file shaped like the real thing: bulk content, then a rate_limits record.

    ``limit_id`` defaults to ``"codex"`` because that is what a real Codex rollout carries and
    what the module documents as the reading it trusts. The first version of this fixture OMITTED
    it while the reader did not check it — the fixture and the code agreed on an unsafe predicate,
    so the suite could not have caught the gap. ``limit_id=None`` and a foreign value are now
    both exercised below.

    ``secondary`` had exactly the same defect and for the same reason: the fixture emitted no
    second window while the reader consulted none, so a suite that looked thorough could not
    reach the state where the account is walled on the window nobody read. It now defaults to
    the real ordinary value (present, null) and the walled case is exercised below.
    """
    path = dir_ / "rollout-2026-08-10T00-00-00-test.jsonl"
    rows = []
    if noise:
        rows.append(json.dumps({"timestamp": at.isoformat(), "payload": {"content": noise}}))
    limits: dict = {"primary": {"used_percent": used, "window_minutes": window}}
    if secondary is not _OMIT:
        limits["secondary"] = secondary
    if limit_id is not None:
        limits["limit_id"] = limit_id
    rows.append(json.dumps({"timestamp": at.isoformat(), "payload": {"rate_limits": limits}}))
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


def _model_rollout(dir_: Path, *, model: str, effort: str | None, big_head: bool = True) -> Path:
    """A rollout shaped like the real thing: huge opening lines, model then effort a line apart."""
    path = dir_ / "rollout-2026-08-10T11-29-08-testsession.jsonl"
    rows = []
    if big_head:
        # Real rollouts carry the system prompt in the opening lines; "model" sat past 64KB.
        for _ in range(4):
            rows.append(json.dumps({"payload": {"content": "x" * 20000}}))
    rows.append(json.dumps({"payload": {"model": model}}))
    if effort is not None:
        rows.append(json.dumps({"payload": {"reasoning_effort": effort}}))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_effort_is_read_even_though_the_model_appears_first(tmp_path: Path) -> None:
    """Both axes, or the observation looks complete while missing half the routing decision.

    Measured on real rollouts 2026-08-10: the model is declared on line 5 and the reasoning effort
    on line 6. A reader that stops as soon as it has a model returns effort=None on every real
    file — which is exactly what the first version of this function did, and effort is the axis the
    operator actually raised (xhigh vs ultra).
    """
    _model_rollout(tmp_path, model="gpt-5.5", effort="xhigh")

    obs = latest_model_observation(tmp_path, now=NOW, max_age_seconds=86400 * 30)

    assert obs.model == "gpt-5.5"
    assert obs.reasoning_effort == "xhigh", "stopping at the model drops half the routing subject"


def test_model_is_found_past_the_first_64kb(tmp_path: Path) -> None:
    """A byte-capped head read would miss it; this is a LINE-bounded read for that reason."""
    _model_rollout(tmp_path, model="gpt-5.6", effort="ultra", big_head=True)

    obs = latest_model_observation(tmp_path, now=NOW, max_age_seconds=86400 * 30)

    assert obs.model == "gpt-5.6"
    assert obs.reasoning_effort == "ultra"


def test_a_session_with_no_recorded_model_refuses_rather_than_guessing(tmp_path: Path) -> None:
    """Silence must never read as a frontier model.

    A caller that treats "no observation" as "fine" reproduces the original defect, where nobody
    chose the model and everybody assumed it was the good one.
    """
    path = tmp_path / "rollout-2026-08-10T11-29-08-nomodel.jsonl"
    path.write_text(json.dumps({"payload": {"content": "no model here"}}) + "\n", encoding="utf-8")

    with pytest.raises(RolloutQuotaUnavailable, match="model"):
        latest_model_observation(tmp_path, now=NOW, max_age_seconds=86400 * 30)


def test_the_model_observation_carries_no_session_content(tmp_path: Path) -> None:
    """Identifiers only — same containment rule as the quota path."""
    secret = "SENSITIVE-PROMPT-should-never-propagate"
    path = tmp_path / "rollout-2026-08-10T11-29-08-secret.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"payload": {"content": secret}}),
                json.dumps({"payload": {"model": "gpt-5.5", "reasoning_effort": "xhigh"}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    obs = latest_model_observation(tmp_path, now=NOW, max_age_seconds=86400 * 30)

    assert secret not in repr(obs)
    assert set(vars(obs)) == {"observed_at", "model", "reasoning_effort"}


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
            "payload": {
                "rate_limits": {
                    "limit_id": "codex",
                    "primary": {"used_percent": 7.0, "window_minutes": 300},
                }
            },
        }
    )
    bulk = "\n".join([filler] * ((ROLLOUT_TAIL_BYTES // 4096) + 40))
    path.write_text(bulk + "\n" + tail + "\n", encoding="utf-8")
    assert path.stat().st_size > ROLLOUT_TAIL_BYTES

    obs = latest_rollout_observation(tmp_path, now=NOW)

    assert obs.used_percent == 7.0


# ── The subscription discriminator ─────────────────────────────────
#
# The module's opening line names `limit_id: "codex"` as the reading it trusts, and the reader
# did not check it: any `payload.rate_limits` mapping with a primary window could be minted as
# Codex subscription headroom. The fixture above OMITTED the field, so the suite agreed with the
# code on an unsafe predicate and could not have caught it. Both halves are pinned now.


def test_a_foreign_limit_id_is_not_codex_headroom(tmp_path: Path) -> None:
    """A reading from another capacity pool is not a weaker claim, it is a false one."""
    _rollout(tmp_path, at=NOW - timedelta(minutes=2), used=7.0, limit_id="anthropic")
    with pytest.raises(RolloutQuotaUnavailable):
        latest_rollout_observation(tmp_path, now=NOW)


def test_an_absent_limit_id_is_treated_as_not_codex(tmp_path: Path) -> None:
    """Absent is not permission. Failing closed costs one skipped rollout; failing open mints
    an admission nobody can trace back to a pool, which the estate then routes work against."""
    _rollout(tmp_path, at=NOW - timedelta(minutes=2), used=7.0, limit_id=None)
    with pytest.raises(RolloutQuotaUnavailable):
        latest_rollout_observation(tmp_path, now=NOW)


def test_the_discriminator_tolerates_case_and_surrounding_space(tmp_path: Path) -> None:
    _rollout(tmp_path, at=NOW - timedelta(minutes=2), used=7.0, limit_id=" Codex ")
    assert latest_rollout_observation(tmp_path, now=NOW).used_percent == 7.0


# ── The head-read byte cap ─────────────────────────────────────────


def test_one_enormous_opening_line_does_not_defeat_the_byte_cap(tmp_path: Path) -> None:
    """The OOM shape, pinned.

    `for line in handle` materialises a whole line before the loop can consult the byte counter,
    so a rollout whose FIRST line is enormous allocated far past the cap — reproducing the 1.19GB
    incident the module docstring claims is bounded. The bound was real for many-small-lines and
    absent for the one shape that actually caused the outage.
    """
    path = tmp_path / "rollout-2026-08-10T00-00-00-huge.jsonl"
    cap = 64 * 1024
    path.write_text("x" * (cap * 8) + "\n" + '{"a": 1}\n', encoding="utf-8")

    lines = _head_lines(path, max_lines=12, max_bytes=cap)

    assert sum(len(line) for line in lines) <= cap, "the reader allocated past its own cap"


def test_the_head_reader_still_returns_ordinary_leading_lines(tmp_path: Path) -> None:
    """The cap must not cost the reader its actual job."""
    path = tmp_path / "rollout-2026-08-10T00-00-00-small.jsonl"
    path.write_text("".join(f'{{"n": {i}}}\n' for i in range(20)), encoding="utf-8")

    lines = _head_lines(path, max_lines=5, max_bytes=1 << 20)

    assert len(lines) == 5
    assert lines[0].strip() == '{"n": 0}'
    assert lines[4].strip() == '{"n": 4}'


# ── mtime ranks the files; the record timestamp decides ────────────


def _rollout_named(dir_: Path, name: str, *, at: datetime, used: float, mtime: float) -> Path:
    """One rollout with an explicit filesystem mtime, so ranking and content can disagree."""
    import os

    path = dir_ / name
    path.write_text(
        json.dumps(
            {
                "timestamp": at.isoformat(),
                "payload": {
                    "rate_limits": {
                        "limit_id": "codex",
                        "primary": {"used_percent": used, "window_minutes": 300},
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    os.utime(path, (mtime, mtime))
    return path


def test_a_newer_wall_is_not_masked_by_an_older_reading_in_a_newer_file(tmp_path: Path) -> None:
    """The defect: `if best is not None: break` made the newest-record comparison unreachable.

    Stopping at the first rollout that yielded anything meant the winner was whichever file the
    filesystem touched last, not whichever observation Codex recorded last. Those disagree, and the
    consequence is asymmetric: a newer quota WALL in the second-ranked file is masked by an older
    healthy reading in the first, and the caller mints an admission against headroom that is gone.
    """
    healthy_at = NOW - timedelta(minutes=30)
    wall_at = NOW - timedelta(minutes=2)
    # The healthy reading is OLDER by record but its file is touched LAST, so it ranks first.
    _rollout_named(
        tmp_path, "rollout-2026-08-10T00-00-00-a.jsonl", at=healthy_at, used=5.0, mtime=2000.0
    )
    _rollout_named(
        tmp_path,
        "rollout-2026-08-10T00-00-00-b.jsonl",
        at=wall_at,
        used=EXHAUSTED_USED_PERCENT,
        mtime=1000.0,
    )

    with pytest.raises(RolloutQuotaUnavailable, match="exhausted"):
        latest_rollout_observation(tmp_path, now=NOW)


def test_the_newest_record_wins_when_it_is_the_healthy_one(tmp_path: Path) -> None:
    """The same rule in the other direction, so the fix is not a bias toward refusing."""
    wall_at = NOW - timedelta(minutes=30)
    healthy_at = NOW - timedelta(minutes=2)
    _rollout_named(
        tmp_path,
        "rollout-2026-08-10T00-00-00-a.jsonl",
        at=wall_at,
        used=EXHAUSTED_USED_PERCENT,
        mtime=2000.0,
    )
    _rollout_named(
        tmp_path, "rollout-2026-08-10T00-00-00-b.jsonl", at=healthy_at, used=6.0, mtime=1000.0
    )

    assert latest_rollout_observation(tmp_path, now=NOW).used_percent == 6.0


def test_a_full_secondary_window_is_a_wall_even_when_the_primary_reads_empty(
    tmp_path: Path,
) -> None:
    """The measured state, not a hypothetical.

    This host's rollouts carry 779 records with ``secondary.used_percent == 100.0``, and among
    them are records reading ``primary: {used_percent: 0.0, window_minutes: 300}``. Reading only
    the primary reported maximum headroom at the moment the account was fully walled.
    """

    _rollout(
        tmp_path,
        at=NOW - timedelta(minutes=5),
        used=0.0,
        secondary={"used_percent": 100.0, "window_minutes": 10080},
    )

    with pytest.raises(RolloutQuotaUnavailable, match="secondary window is exhausted"):
        latest_rollout_observation(tmp_path, now=NOW)


def test_a_healthy_secondary_window_still_admits(tmp_path: Path) -> None:
    _rollout(
        tmp_path,
        at=NOW - timedelta(minutes=5),
        used=4.0,
        secondary={"used_percent": 12.0, "window_minutes": 10080},
    )

    assert latest_rollout_observation(tmp_path, now=NOW).used_percent == 4.0


def test_a_null_secondary_window_is_not_a_hole(tmp_path: Path) -> None:
    """202,022 of this host's records read ``"secondary": null``.

    A plan with a single window has nothing to violate, so the ordinary case must keep
    admitting -- a second window check that refused everything would be a wall of its own.
    """

    _rollout(tmp_path, at=NOW - timedelta(minutes=5), used=4.0, secondary=None)

    assert latest_rollout_observation(tmp_path, now=NOW).used_percent == 4.0


def test_an_absent_secondary_key_is_treated_like_a_null_one(tmp_path: Path) -> None:
    _rollout(tmp_path, at=NOW - timedelta(minutes=5), used=4.0, secondary=_OMIT)

    assert latest_rollout_observation(tmp_path, now=NOW).used_percent == 4.0


@pytest.mark.parametrize(
    "secondary",
    [
        "100",
        {"window_minutes": 10080},
        {"used_percent": "unknown", "window_minutes": 10080},
        {"used_percent": None},
    ],
)
def test_an_unreadable_secondary_window_refuses_rather_than_admitting_on_the_primary(
    tmp_path: Path, secondary: object
) -> None:
    """An unparseable window is an unknown window, not an empty one.

    Falling back to "admit on the primary alone" here would widen the failure path -- the code
    would attempt MORE on damaged data than it does on intact data, which is the shape of an
    unsound fallback rather than of failure handling.
    """

    _rollout(tmp_path, at=NOW - timedelta(minutes=5), used=1.0, secondary=secondary)

    with pytest.raises(RolloutQuotaUnavailable, match="secondary window"):
        latest_rollout_observation(tmp_path, now=NOW)
