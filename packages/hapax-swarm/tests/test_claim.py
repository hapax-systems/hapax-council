"""Tests for claim_before_parallel_work."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from hapax_swarm import ClaimConflict, RelayDir, claim_before_parallel_work

if TYPE_CHECKING:
    from pathlib import Path


def test_claim_writes_record_when_no_conflict(tmp_path: Path) -> None:
    relay = RelayDir(tmp_path)
    relay.ensure()

    record = claim_before_parallel_work(
        relay,
        role="beta",
        surface="packages/hapax-swarm/",
        branch_target="beta/hapax-swarm-pypi",
    )
    assert record["surface"] == "packages/hapax-swarm/"
    assert record["branch_target"] == "beta/hapax-swarm-pypi"
    assert "claimed_at" in record

    on_disk = relay.peer("beta").currently_working_on
    assert on_disk == record


def test_claim_raises_on_sibling_overlap(tmp_path: Path) -> None:
    relay = RelayDir(tmp_path)
    relay.ensure()
    relay.peer("alpha").write(
        {
            "currently_working_on": {
                "surface": "packages/",
                "branch_target": "alpha/x",
            }
        }
    )

    with pytest.raises(ClaimConflict) as excinfo:
        claim_before_parallel_work(
            relay,
            role="beta",
            surface="packages/hapax-swarm/",
            branch_target="beta/y",
        )
    assert excinfo.value.surface == "packages/hapax-swarm/"
    assert [r for r, _ in excinfo.value.conflicts] == ["alpha"]


def test_claim_preserves_existing_peer_fields(tmp_path: Path) -> None:
    relay = RelayDir(tmp_path)
    relay.ensure()
    relay.peer("beta").write({"workstream": "obs"})

    claim_before_parallel_work(
        relay,
        role="beta",
        surface="packages/hapax-swarm/",
        branch_target="beta/x",
    )
    payload = relay.peer("beta").read()
    assert payload["workstream"] == "obs"
    assert payload["currently_working_on"]["surface"] == "packages/hapax-swarm/"


def test_claim_with_extra_fields(tmp_path: Path) -> None:
    relay = RelayDir(tmp_path)
    relay.ensure()
    record = claim_before_parallel_work(
        relay,
        role="beta",
        surface="packages/hapax-swarm/",
        branch_target="beta/x",
        extra={"task_id": "leverage-workflow-hapax-swarm-pypi"},
    )
    assert record["task_id"] == "leverage-workflow-hapax-swarm-pypi"
