"""Tests for shared.labeled_trace.

70-LOC consent-label-aware /dev/shm trace I/O. Untested before this
commit. Embeds/extracts ConsentLabel + provenance in a ``_consent``
envelope so labels survive JSON serialisation across processes.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from shared.governance.consent_label import ConsentLabel
from shared.labeled_trace import (
    deserialize_label,
    read_labeled_trace,
    serialize_label,
    write_labeled_trace,
)


def _label_with(owner: str, readers: list[str]) -> ConsentLabel:
    return ConsentLabel(frozenset({(owner, frozenset(readers))}))


# ── serialize_label ────────────────────────────────────────────────


class TestSerialize:
    def test_none_returns_none(self) -> None:
        assert serialize_label(None) is None

    def test_bottom_label_serialises_to_empty_list(self) -> None:
        result = serialize_label(ConsentLabel.bottom())
        assert result is not None
        assert result["label"] == []
        assert result["provenance"] == []
        assert "labeled_at" in result

    def test_label_serialises_owner_and_sorted_readers(self) -> None:
        label = _label_with("alice", ["zeta", "alpha", "midas"])
        result = serialize_label(label, provenance=frozenset({"src1", "src2"}))
        assert result is not None
        # Readers should be sorted
        assert result["label"][0]["owner"] == "alice"
        assert result["label"][0]["readers"] == ["alpha", "midas", "zeta"]
        # Provenance sorted
        assert result["provenance"] == ["src1", "src2"]


# ── deserialize_label ──────────────────────────────────────────────


class TestDeserialize:
    def test_none_yields_bottom_label(self) -> None:
        label, prov = deserialize_label(None)
        assert label == ConsentLabel.bottom()
        assert prov == frozenset()

    def test_round_trip_preserves_label(self) -> None:
        original = _label_with("alice", ["alpha", "midas"])
        serialized = serialize_label(original, provenance=frozenset({"src"}))
        label, prov = deserialize_label(serialized)
        assert label == original
        assert prov == frozenset({"src"})

    def test_entry_without_owner_skipped(self) -> None:
        """Entries with empty owner are dropped (defensive parse)."""
        consent_data = {
            "label": [
                {"owner": "", "readers": ["x"]},
                {"owner": "alice", "readers": ["alpha"]},
            ],
            "provenance": [],
        }
        label, _prov = deserialize_label(consent_data)
        assert label.policies == frozenset({("alice", frozenset({"alpha"}))})

    def test_provenance_coerced_to_strings(self) -> None:
        """Numeric or otherwise-non-string provenance entries are
        stringified."""
        consent_data = {"label": [], "provenance": [1, 2, "three"]}
        _label, prov = deserialize_label(consent_data)
        assert prov == frozenset({"1", "2", "three"})


# ── write_labeled_trace + read_labeled_trace ──────────────────────


class TestWriteRead:
    def test_round_trip_data_and_label(self, tmp_path: Path) -> None:
        path = tmp_path / "trace.json"
        label = _label_with("alice", ["alpha"])
        write_labeled_trace(path, {"k": "v", "n": 7}, label, frozenset({"src1"}))
        data, returned_label = read_labeled_trace(path, stale_s=60.0)
        assert data == {"k": "v", "n": 7}
        assert returned_label == label

    def test_consent_envelope_stripped_from_data(self, tmp_path: Path) -> None:
        """The `_consent` envelope is removed from the returned data dict
        so callers see only their own payload."""
        path = tmp_path / "trace.json"
        write_labeled_trace(path, {"x": 1}, _label_with("a", ["b"]))
        data, _ = read_labeled_trace(path, stale_s=60.0)
        assert "_consent" not in data

    def test_atomic_write_no_partial(self, tmp_path: Path) -> None:
        path = tmp_path / "trace.json"
        write_labeled_trace(path, {"k": "v"}, _label_with("a", ["b"]))
        # No leftover .tmp.
        assert not path.with_suffix(".tmp").exists()

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        path = tmp_path / "deep" / "nested" / "trace.json"
        write_labeled_trace(path, {"k": "v"}, None)
        assert path.exists()

    def test_missing_file_returns_none_pair(self, tmp_path: Path) -> None:
        data, label = read_labeled_trace(tmp_path / "nope.json", stale_s=60.0)
        assert data is None
        assert label is None

    def test_stale_file_returns_none_pair(self, tmp_path: Path) -> None:
        path = tmp_path / "stale.json"
        write_labeled_trace(path, {"k": "v"}, _label_with("a", ["b"]))
        # Backdate the file 1000 seconds.
        old_ts = time.time() - 1000
        os.utime(path, (old_ts, old_ts))
        data, label = read_labeled_trace(path, stale_s=10.0)
        assert data is None
        assert label is None

    def test_invalid_json_returns_none_pair(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{ invalid")
        data, label = read_labeled_trace(path, stale_s=60.0)
        assert data is None
        assert label is None

    def test_no_label_yields_bottom_label(self, tmp_path: Path) -> None:
        """Trace written with label=None deserialises to bottom label."""
        path = tmp_path / "trace.json"
        write_labeled_trace(path, {"k": "v"}, None)
        data, label = read_labeled_trace(path, stale_s=60.0)
        assert data == {"k": "v"}
        assert label == ConsentLabel.bottom()


# ── External-shape contract (data only, no envelope) ──────────────


class TestEnvelopeShape:
    def test_consent_envelope_present_in_serialized_form(self, tmp_path: Path) -> None:
        """A reader using raw json.loads should see the _consent key —
        only the labeled_trace API strips it."""
        path = tmp_path / "trace.json"
        write_labeled_trace(path, {"k": "v"}, _label_with("a", ["b"]))
        raw = json.loads(path.read_text())
        assert "_consent" in raw
        assert raw["_consent"]["label"][0]["owner"] == "a"
