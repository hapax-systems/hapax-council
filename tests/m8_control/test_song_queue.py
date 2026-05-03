"""m8-song-queue-control — YAML loading + Pydantic + dispatch + rescan-script.

cc-task `m8-song-queue-control`. Tests:

  * YAML index loading (valid, missing, malformed, empty-projects-list)
  * Pydantic validation (empty-name rejected, negative duration rejected)
  * M8SongQueue.queue: known project dispatches button sequence; unknown
    project raises typed error; daemon error propagates as
    M8SongQueueError; empty button_sequence raises
  * Affordance registration
  * scripts/m8-rescan-projects.py: button-sequence computation
    correctness; M8-attached refusal; YAML emission shape
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

from agents.m8_control.song_queue import (
    DEFAULT_INDEX_PATH,
    M8ProjectEntry,
    M8ProjectIndex,
    M8SongQueue,
    M8SongQueueError,
    load_project_index,
)

# ── M8ProjectEntry / M8ProjectIndex Pydantic ────────────────────────


class TestPydanticSchema:
    def test_minimal_entry(self) -> None:
        e = M8ProjectEntry(name="x", button_sequence=["EDIT", "EDIT"])
        assert e.name == "x"
        assert e.button_sequence == ["EDIT", "EDIT"]

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(Exception):  # noqa: BLE001 — Pydantic ValidationError
            M8ProjectEntry(name="", button_sequence=["EDIT"])

    def test_negative_duration_rejected(self) -> None:
        with pytest.raises(Exception):
            M8ProjectEntry(name="x", duration_estimate_s=-1)

    def test_zero_tempo_rejected(self) -> None:
        with pytest.raises(Exception):
            M8ProjectEntry(name="x", tempo_bpm=0)

    def test_optional_fields_default(self) -> None:
        e = M8ProjectEntry(name="x")
        assert e.button_sequence == []
        assert e.duration_estimate_s is None
        assert e.tempo_bpm is None
        assert e.tonal_tags == []

    def test_default_index_path_constant(self) -> None:
        # Pin: scripts/m8-rescan-projects.py writes to this path; the
        # song_queue loader reads from this path. They must match.
        assert str(DEFAULT_INDEX_PATH) == "config/m8/project_index.yaml"


# ── load_project_index ──────────────────────────────────────────────


class TestLoadProjectIndex:
    def test_load_valid_yaml(self, tmp_path: Path) -> None:
        p = tmp_path / "idx.yaml"
        p.write_text(
            yaml.safe_dump(
                {
                    "projects": [
                        {"name": "alpha", "button_sequence": ["EDIT", "EDIT"]},
                        {"name": "beta", "button_sequence": ["EDIT", "DOWN", "EDIT"]},
                    ]
                }
            )
        )
        index = load_project_index(p)
        assert len(index.projects) == 2
        assert index.projects[0].name == "alpha"

    def test_load_empty_projects_list(self, tmp_path: Path) -> None:
        p = tmp_path / "idx.yaml"
        p.write_text("projects: []\n")
        index = load_project_index(p)
        assert index.projects == []

    def test_load_missing_file_raises_oserror(self, tmp_path: Path) -> None:
        with pytest.raises((FileNotFoundError, OSError)):
            load_project_index(tmp_path / "nope.yaml")

    def test_load_malformed_yaml_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.yaml"
        p.write_text("{not valid: yaml :{}")
        with pytest.raises(Exception):  # noqa: BLE001 — yaml.YAMLError
            load_project_index(p)


# ── M8SongQueue.queue with mocked client ────────────────────────────


class _RecordingClient:
    """Mock M8ControlClient that records each .button() invocation.

    By default ACKs `{"ok": True}`. Set `failure_at_step` to make a
    specific step return `{"ok": False, "error": "synthetic"}`.
    """

    def __init__(self, failure_at_step: int | None = None) -> None:
        self.calls: list[tuple[str, int]] = []
        self.failure_at_step = failure_at_step

    def button(self, name: str, *, hold_ms: int = 16) -> dict:
        self.calls.append((name, hold_ms))
        if self.failure_at_step is not None and len(self.calls) - 1 == self.failure_at_step:
            return {"ok": False, "error": "synthetic"}
        return {"ok": True}


class TestM8SongQueueDispatch:
    def _index(self) -> M8ProjectIndex:
        return M8ProjectIndex(
            projects=[
                M8ProjectEntry(
                    name="mood_drift_03",
                    button_sequence=["EDIT", "DOWN", "DOWN", "DOWN", "EDIT"],
                ),
                M8ProjectEntry(
                    name="wistful_amber_02",
                    button_sequence=["EDIT", "DOWN", "DOWN", "DOWN", "DOWN", "EDIT"],
                ),
            ]
        )

    def test_known_project_dispatches_full_sequence(self) -> None:
        client = _RecordingClient()
        queue = M8SongQueue(self._index(), client=client, hold_ms=80)
        result = queue.queue("mood_drift_03")
        assert result == {"ok": True, "project": "mood_drift_03", "steps": 5}
        # Button sequence dispatched in order with hold_ms=80.
        assert client.calls == [
            ("EDIT", 80),
            ("DOWN", 80),
            ("DOWN", 80),
            ("DOWN", 80),
            ("EDIT", 80),
        ]

    def test_unknown_project_raises_typed_error_no_dispatch(self) -> None:
        client = _RecordingClient()
        queue = M8SongQueue(self._index(), client=client)
        with pytest.raises(M8SongQueueError, match="unknown project"):
            queue.queue("nonexistent")
        assert client.calls == []  # nothing dispatched

    def test_empty_button_sequence_raises_no_dispatch(self) -> None:
        client = _RecordingClient()
        index = M8ProjectIndex(projects=[M8ProjectEntry(name="empty", button_sequence=[])])
        queue = M8SongQueue(index, client=client)
        with pytest.raises(M8SongQueueError, match="empty button_sequence"):
            queue.queue("empty")
        assert client.calls == []

    def test_daemon_error_at_step_propagates_as_typed_error(self) -> None:
        client = _RecordingClient(failure_at_step=2)
        queue = M8SongQueue(self._index(), client=client)
        with pytest.raises(M8SongQueueError, match="daemon error at step 2"):
            queue.queue("mood_drift_03")
        # Steps 0, 1, 2 attempted; step 2 fails; 3, 4 not attempted.
        assert len(client.calls) == 3

    def test_case_sensitive_name_match(self) -> None:
        """M8 file-browser names are case-sensitive on FAT32."""
        client = _RecordingClient()
        queue = M8SongQueue(self._index(), client=client)
        with pytest.raises(M8SongQueueError, match="unknown project"):
            queue.queue("MOOD_DRIFT_03")  # uppercase variant


# ── Affordance registration ─────────────────────────────────────────


def test_studio_m8_song_queue_affordance_registered() -> None:
    from shared.affordance_registry import STUDIO_AFFORDANCES

    names = {r.name for r in STUDIO_AFFORDANCES}
    assert "studio.m8_song_queue" in names
    record = next(r for r in STUDIO_AFFORDANCES if r.name == "studio.m8_song_queue")
    assert record.daemon == "m8_control"
    assert record.operational.consent_required is False


# ── scripts/m8-rescan-projects.py ──────────────────────────────────


def _load_rescan_script():
    """Import the rescan script as a module so we can test its helpers."""
    p = Path(__file__).resolve().parents[2] / "scripts" / "m8-rescan-projects.py"
    spec = importlib.util.spec_from_file_location("m8_rescan", p)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["m8_rescan"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


class TestRescanScript:
    def test_compute_button_sequence_first_project(self) -> None:
        mod = _load_rescan_script()
        # Index 0: just EDIT-then-EDIT (no DOWN steps).
        assert mod.compute_button_sequence(0) == ["EDIT", "EDIT"]

    def test_compute_button_sequence_third_project(self) -> None:
        mod = _load_rescan_script()
        # Index 2: EDIT + 2 DOWN + EDIT.
        assert mod.compute_button_sequence(2) == ["EDIT", "DOWN", "DOWN", "EDIT"]

    def test_render_yaml_shape(self) -> None:
        mod = _load_rescan_script()
        text = mod.render_yaml(["alpha_drift", "beta_pulse"])
        # Round-trip through Pydantic to confirm the YAML matches schema.
        import yaml as _yaml

        parsed = _yaml.safe_load(text)
        index = M8ProjectIndex.model_validate(parsed)
        assert [p.name for p in index.projects] == ["alpha_drift", "beta_pulse"]
        # Index 0 → ["EDIT", "EDIT"]; index 1 → ["EDIT", "DOWN", "EDIT"].
        assert index.projects[0].button_sequence == ["EDIT", "EDIT"]
        assert index.projects[1].button_sequence == ["EDIT", "DOWN", "EDIT"]

    def test_m8_attached_check_uses_symlink_path(self) -> None:
        mod = _load_rescan_script()
        # Symlink doesn't exist on the test runner, so should return False.
        assert mod.m8_is_usb_attached(Path("/nonexistent-m8-symlink")) is False

    def test_list_m8_projects_sorts_case_insensitive(self, tmp_path: Path) -> None:
        mod = _load_rescan_script()
        songs = tmp_path / "Songs"
        songs.mkdir()
        # Mixed case entries; M8 sorts case-insensitively.
        for name in ("Beta_Drift.m8s", "alpha_pulse.m8s", "Charlie_Wave.m8s"):
            (songs / name).write_bytes(b"")
        # Add a non-m8s file that should be skipped.
        (songs / "readme.txt").write_text("ignore me")
        names = mod.list_m8_projects(songs)
        # Stems only, sorted case-insensitively.
        assert names == ["alpha_pulse", "Beta_Drift", "Charlie_Wave"]
