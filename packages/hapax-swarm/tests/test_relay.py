"""Tests for relay.py — directory layout + sibling discovery + claim conflict check."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from hapax_swarm import RelayDir

if TYPE_CHECKING:
    from pathlib import Path


def test_ensure_creates_subdirs(tmp_path: Path) -> None:
    relay = RelayDir(tmp_path)
    relay.ensure()
    for sub in ("queue", "inflections", "locks", "context"):
        assert (tmp_path / sub).is_dir()


def test_known_peers_discovers_yaml_files(tmp_path: Path) -> None:
    relay = RelayDir(tmp_path)
    relay.ensure()
    relay.peer("alpha").write({})
    relay.peer("beta").write({})
    relay.peer("delta").write({})
    (tmp_path / "glossary.yaml").write_text("- term: x\n")

    # glossary is reserved, not a peer
    assert relay.known_peers() == ["alpha", "beta", "delta"]


def test_invalid_peer_role_rejected(tmp_path: Path) -> None:
    relay = RelayDir(tmp_path)
    with pytest.raises(ValueError):
        relay.peer("../etc/passwd")
    with pytest.raises(ValueError):
        relay.peer(".hidden")
    with pytest.raises(ValueError):
        relay.peer("")


def test_find_conflicting_claims_exact_overlap(tmp_path: Path) -> None:
    relay = RelayDir(tmp_path)
    relay.ensure()
    relay.peer("alpha").write(
        {
            "currently_working_on": {
                "surface": "packages/hapax-swarm/",
                "branch_target": "alpha/x",
            }
        }
    )
    conflicts = relay.find_conflicting_claims("packages/hapax-swarm/", exclude_role="beta")
    assert len(conflicts) == 1
    assert conflicts[0][0] == "alpha"


def test_find_conflicting_claims_prefix_overlap(tmp_path: Path) -> None:
    relay = RelayDir(tmp_path)
    relay.ensure()
    relay.peer("alpha").write(
        {"currently_working_on": {"surface": "packages/", "branch_target": "alpha/x"}}
    )
    # peer claims a parent — beta wanting a child should still conflict
    conflicts = relay.find_conflicting_claims("packages/hapax-swarm/", exclude_role="beta")
    assert [r for r, _ in conflicts] == ["alpha"]

    # reverse: peer claims a child, beta wants the parent — also conflict
    relay.peer("alpha").write(
        {
            "currently_working_on": {
                "surface": "packages/hapax-swarm/",
                "branch_target": "alpha/x",
            }
        }
    )
    conflicts = relay.find_conflicting_claims("packages/", exclude_role="beta")
    assert [r for r, _ in conflicts] == ["alpha"]


def test_find_conflicting_claims_no_overlap(tmp_path: Path) -> None:
    relay = RelayDir(tmp_path)
    relay.ensure()
    relay.peer("alpha").write(
        {
            "currently_working_on": {
                "surface": "agents/studio_compositor/",
                "branch_target": "alpha/x",
            }
        }
    )
    conflicts = relay.find_conflicting_claims("packages/hapax-swarm/", exclude_role="beta")
    assert conflicts == []


def test_find_conflicting_claims_excludes_self(tmp_path: Path) -> None:
    relay = RelayDir(tmp_path)
    relay.ensure()
    relay.peer("beta").write(
        {
            "currently_working_on": {
                "surface": "packages/hapax-swarm/",
                "branch_target": "beta/x",
            }
        }
    )
    conflicts = relay.find_conflicting_claims("packages/hapax-swarm/", exclude_role="beta")
    assert conflicts == []


def test_find_conflicting_claims_skips_peers_with_no_claim(tmp_path: Path) -> None:
    relay = RelayDir(tmp_path)
    relay.ensure()
    relay.peer("alpha").write({"workstream": "x"})
    conflicts = relay.find_conflicting_claims("packages/hapax-swarm/", exclude_role="beta")
    assert conflicts == []
