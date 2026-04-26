"""Tests for peer.py — per-session yaml read/write."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from hapax_swarm import RelayDir

if TYPE_CHECKING:
    from pathlib import Path


def test_peer_write_stamps_session_and_updated(tmp_path: Path) -> None:
    relay = RelayDir(tmp_path)
    relay.ensure()
    me = relay.peer("beta")
    me.write({"workstream": "obs"})

    loaded = yaml.safe_load((tmp_path / "beta.yaml").read_text())
    assert loaded["session"] == "beta"
    assert loaded["workstream"] == "obs"
    assert "updated" in loaded
    assert loaded["updated"].endswith("Z")


def test_peer_update_merges_existing_fields(tmp_path: Path) -> None:
    relay = RelayDir(tmp_path)
    relay.ensure()
    me = relay.peer("beta")
    me.write({"workstream": "obs", "focus": "first"})
    me.update(focus="second")

    payload = me.read()
    assert payload["workstream"] == "obs"
    assert payload["focus"] == "second"


def test_peer_currently_working_on_returns_record(tmp_path: Path) -> None:
    relay = RelayDir(tmp_path)
    relay.ensure()
    me = relay.peer("beta")
    me.write(
        {
            "currently_working_on": {
                "surface": "packages/hapax-swarm/",
                "branch_target": "beta/x",
            }
        }
    )
    record = me.currently_working_on
    assert record == {
        "surface": "packages/hapax-swarm/",
        "branch_target": "beta/x",
    }


def test_peer_read_missing_file_returns_empty(tmp_path: Path) -> None:
    relay = RelayDir(tmp_path)
    me = relay.peer("alpha")
    assert me.read() == {}
    assert me.currently_working_on is None
