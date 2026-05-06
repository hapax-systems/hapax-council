"""Tests for shared.incidents."""

from shared.incidents import IncidentPhase, IncidentTracker


class TestIncidentTracker:
    def test_open_incident(self, tmp_path):
        t = IncidentTracker(state_path=tmp_path / "inc.json")
        inc = t.open_incident("docker.qdrant", "Container down")
        assert inc.phase == IncidentPhase.OPEN
        assert inc.check_name == "docker.qdrant"
        assert len(inc.timeline) == 1
        assert inc.timeline[0].event_type == "opened"

    def test_open_returns_existing(self, tmp_path):
        t = IncidentTracker(state_path=tmp_path / "inc.json")
        inc1 = t.open_incident("docker.qdrant")
        inc2 = t.open_incident("docker.qdrant")
        assert inc1.id == inc2.id  # same incident returned

    def test_resolve_incident(self, tmp_path):
        t = IncidentTracker(state_path=tmp_path / "inc.json")
        t.open_incident("docker.qdrant")
        resolved = t.resolve("docker.qdrant", "Auto-fixed")
        assert resolved is not None
        assert resolved.phase == IncidentPhase.RESOLVED
        assert resolved.resolved_at != ""
        assert resolved.duration_minutes() is not None

    def test_acknowledge(self, tmp_path):
        t = IncidentTracker(state_path=tmp_path / "inc.json")
        inc = t.open_incident("docker.qdrant")
        assert t.acknowledge(inc.id) is True
        assert t.get_by_id(inc.id).phase == IncidentPhase.ACKNOWLEDGED

    def test_persistence_roundtrip(self, tmp_path):
        path = tmp_path / "inc.json"
        t1 = IncidentTracker(state_path=path)
        t1.open_incident("docker.qdrant", "Down")
        t1.save()

        t2 = IncidentTracker(state_path=path)
        assert len(t2.get_open()) == 1
        assert t2.get_open()[0].check_name == "docker.qdrant"


import pytest


@pytest.mark.parametrize(
    "payload,kind",
    [("null", "null"), ('"a"', "string"), ("{}", "dict"), ("42", "int")],
)
def test_load_non_list_root_yields_empty(tmp_path, payload, kind):
    """Pin IncidentTracker._load against non-list JSON. The list-comp
    iteration over data raised TypeError on non-iterable roots; the
    (json.JSONDecodeError, OSError) catch missed it."""
    path = tmp_path / "inc.json"
    path.write_text(payload)
    t = IncidentTracker(state_path=path)
    assert t.get_open() == [], f"non-list root={kind} must yield empty"


def test_load_list_with_garbage_entry_skips_garbage(tmp_path):
    """Pin: malformed entries inside the list are skipped per-entry,
    not crashing the whole load via Pydantic ValidationError."""
    import json

    path = tmp_path / "inc.json"
    path.write_text(json.dumps(["garbage-string", {"id": "x"}]))
    t = IncidentTracker(state_path=path)
    # Both entries are malformed (string isn't a dict; {id:x} missing
    # required fields), so loaded count is 0 — but the function must
    # not have raised.
    assert t.get_open() == []
