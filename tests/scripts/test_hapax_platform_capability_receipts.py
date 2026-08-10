"""The codex quota surface must carry the OBSERVATION's timestamp, not the observer's.

`latest_rollout_observation` accepts a rollout snapshot up to DEFAULT_MAX_OBSERVATION_AGE_SECONDS
(3600s) old. The first version of this surface stamped it with the receipt-generation time under
`stale_after="15m"`, so a 59-minute-old observation was published as freshly observed and cleared
`account_live_quota_receipt_absent` for a further 15 minutes — roughly 74 minutes of real staleness
rendered as <=15.

Caught by codex-1 on PR #4545. The producer had no test file at all, which is how it shipped.

A note on what is testable here. The quota surface is constructed INLINE inside `build_receipt`,
whose other inputs are live CLI/wrapper probes. A test that rebuilds the surface by hand and
asserts the value it just passed in would be tautological — it would pass with the bug present.
So the guard is a call-site assertion over the source: the defect was a wrong ARGUMENT, and the
argument is what gets pinned. Extracting the surface construction into a testable function would
be the better fix; it is a refactor of a file under review and is left for a follow-up.
"""

from __future__ import annotations

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-platform-capability-receipts"


def test_the_quota_surface_binds_the_observation_time_not_the_receipt_time() -> None:
    """Pin the call site, because the bug was a wrong argument.

    `observed_at=observed_at` restamps a stale rollout as current; the correct binding names the
    observation. This is the same defect class as a conformance checker that skips its checks and
    still prints "conformant": a timestamp that describes the OBSERVER rather than the OBSERVATION.
    """
    source = SCRIPT.read_text(encoding="utf-8")

    assert "observed_at=rollout_quota.observed_at" in source, (
        "the codex quota surface must bind observed_at to the ROLLOUT observation; binding it to "
        "the receipt-generation time restamps stale data as fresh"
    )


def test_no_quota_surface_still_binds_the_receipt_generation_time() -> None:
    """The positive assertion alone would pass if BOTH bindings were present.

    A regression is likeliest as an addition — a second surface, or a reverted line left beside the
    fixed one — so assert the wrong binding is absent from the rollout branch rather than only that
    the right one is present.
    """
    source = SCRIPT.read_text(encoding="utf-8").splitlines()

    start = next((i for i, line in enumerate(source) if "rollout_quota is not None" in line), None)
    assert start is not None, "fixture drift: the rollout quota branch is gone"

    branch = "\n".join(source[start : start + 30])
    assert "observed_at=rollout_quota.observed_at" in branch
    assert "observed_at=observed_at" not in branch, (
        "the rollout branch must not stamp the receipt-generation time"
    )


def test_the_reader_still_bounds_observation_age() -> None:
    """The fix relies on the reader rejecting ancient snapshots; pin that too.

    Without a max age, an arbitrarily old observation would flow through carrying an
    honest-but-ancient timestamp, and freshness would rest entirely on downstream staleness checks
    noticing. Honest timestamps and a bounded reader are two halves of one guarantee.
    """
    from shared.codex_rollout_quota import DEFAULT_MAX_OBSERVATION_AGE_SECONDS

    assert 0 < DEFAULT_MAX_OBSERVATION_AGE_SECONDS <= 3600
