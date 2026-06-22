"""AVSDLC runtime-witness receipt emission — the producer side of Tier-C.

The independent witness observes the live substrate/OBS, computes a content
hash over the deployed gamedir, and emits an HMAC-signed ``AVWitnessReceipt``
that the release gate VERIFIES (it never mints its own verdict). A genuine PASS
requires the witness ``overall == PASS`` AND the OBS source MOVING (reached air).

cc-task: avsdlc-enforcement-witness-v1 (CASE-AVSDLC-ENFORCEMENT-20260621).
Self-contained per workspace convention.
"""

from __future__ import annotations

import json
from pathlib import Path

from shared.avsdlc_witness import (
    build_receipt_from_witness,
    emit_receipt,
    gamedir_content_hash,
    read_active_source_head,
    receipt_status_from_manifest,
)
from shared.governance.coord_capabilities import (
    read_av_receipt_file,
    verify_av_witness_receipt,
)

KEY = b"operator-secret-key-0123456789abcdef"
NOW = 1_800_000_000.0


def _gamedir(root: Path, files: dict[str, bytes]) -> Path:
    for rel, data in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return root


_MOVING = {"overall": "PASS", "obs": {"source": {"verdict": "MOVING"}}}
_FROZEN = {"overall": "FAIL", "obs": {"source": {"verdict": "FROZEN"}}}


# ── content hash ──────────────────────────────────────────────────────


class TestContentHash:
    def test_same_bytes_same_hash(self, tmp_path: Path) -> None:
        a = _gamedir(tmp_path / "a", {"maps/x.bsp": b"\x00\x01", "progs.dat": b"abc"})
        b = _gamedir(tmp_path / "b", {"maps/x.bsp": b"\x00\x01", "progs.dat": b"abc"})
        assert gamedir_content_hash(a) == gamedir_content_hash(b)
        assert len(gamedir_content_hash(a)) == 64

    def test_changed_byte_changes_hash(self, tmp_path: Path) -> None:
        a = _gamedir(tmp_path / "a", {"maps/x.bsp": b"\x00\x01"})
        b = _gamedir(tmp_path / "b", {"maps/x.bsp": b"\x00\x02"})
        assert gamedir_content_hash(a) != gamedir_content_hash(b)

    def test_renamed_path_changes_hash(self, tmp_path: Path) -> None:
        a = _gamedir(tmp_path / "a", {"maps/x.bsp": b"data"})
        b = _gamedir(tmp_path / "b", {"maps/y.bsp": b"data"})
        assert gamedir_content_hash(a) != gamedir_content_hash(b)

    def test_absent_dir_is_empty(self, tmp_path: Path) -> None:
        assert gamedir_content_hash(tmp_path / "nope") == ""

    def test_present_but_empty_dir_is_unverifiable(self, tmp_path: Path) -> None:
        # M4 / MEDIUM-1: a present-but-empty gamedir means the witness saw no
        # deployed bytes — that must be unverifiable (""), not a stable hash.
        d = tmp_path / "empty"
        d.mkdir()
        assert gamedir_content_hash(d) == ""

    def test_symlink_not_followed(self, tmp_path: Path) -> None:
        # M4: a symlink must not pull bytes from OUTSIDE the gamedir into the
        # hash (that would let an external file forge/track the binding).
        outside = tmp_path / "secret.bin"
        outside.write_bytes(b"SECRET-EXTERNAL-BYTES")
        gd = tmp_path / "gd"
        gd.mkdir()
        (gd / "link").symlink_to(outside)
        # only a symlink → no real deployed bytes → unverifiable.
        assert gamedir_content_hash(gd) == ""


# ── active source head ────────────────────────────────────────────────


class TestActiveSourceHead:
    def test_reads_head(self, tmp_path: Path) -> None:
        cj = tmp_path / "current.json"
        cj.write_text(json.dumps({"active_source_head": "9757f7bde"}))
        assert read_active_source_head(cj) == "9757f7bde"

    def test_missing_returns_empty(self, tmp_path: Path) -> None:
        assert read_active_source_head(tmp_path / "nope.json") == ""


# ── manifest → (status, obs_moving) ───────────────────────────────────


class TestReceiptStatusFromManifest:
    def test_pass_and_moving(self) -> None:
        assert receipt_status_from_manifest(_MOVING) == ("pass", True)

    def test_fail_overall(self) -> None:
        status, _ = receipt_status_from_manifest(_FROZEN)
        assert status == "fail"

    def test_obs_frozen_is_not_moving(self) -> None:
        _, moving = receipt_status_from_manifest(
            {"overall": "PASS", "obs": {"source": {"verdict": "FROZEN"}}}
        )
        assert moving is False

    def test_pass_without_obs_is_not_moving(self) -> None:
        _, moving = receipt_status_from_manifest({"overall": "PASS", "obs": {}})
        assert moving is False


# ── build + emit ──────────────────────────────────────────────────────


class TestBuildAndEmit:
    def test_pass_moving_receipt_verifies(self) -> None:
        receipt = build_receipt_from_witness(
            _MOVING,
            content_hash="a" * 64,
            active_source_head="9757f7bde",
            ttl_s=1800.0,
            key=KEY,
            now=NOW,
        )
        assert verify_av_witness_receipt(receipt, key=KEY, now=NOW + 60)

    def test_frozen_receipt_does_not_verify(self) -> None:
        receipt = build_receipt_from_witness(
            _FROZEN,
            content_hash="a" * 64,
            active_source_head="9757f7bde",
            ttl_s=1800.0,
            key=KEY,
            now=NOW,
        )
        assert not verify_av_witness_receipt(receipt, key=KEY, now=NOW + 60)

    def test_emit_writes_verifiable_receipt_bound_to_gamedir(self, tmp_path: Path) -> None:
        gamedir = _gamedir(tmp_path / "screwm", {"maps/x.bsp": b"\x00\x01", "progs.dat": b"abc"})
        current = tmp_path / "current.json"
        current.write_text(json.dumps({"active_source_head": "9757f7bde"}))
        out = tmp_path / "receipt.json"

        receipt = emit_receipt(
            gamedir=gamedir,
            current_json=current,
            manifest=_MOVING,
            out_path=out,
            key=KEY,
            ttl_s=1800.0,
            now=NOW,
        )

        loaded = read_av_receipt_file(out)
        assert loaded is not None
        assert verify_av_witness_receipt(loaded, key=KEY, now=NOW + 60)
        # the receipt is bound to the actual deployed bytes
        assert loaded.content_hash == gamedir_content_hash(gamedir)
        assert verify_av_witness_receipt(
            loaded, key=KEY, now=NOW + 60, content_hash=gamedir_content_hash(gamedir)
        )
        assert receipt.active_source_head == "9757f7bde"


class TestIntentFieldsFromFrame:
    """PR 4b: the witness binds (intent_hash, intent_pass) from a declared record +
    a captured frame. The hash is derived from the DECLARED record (frame-independent,
    so the gate can re-derive it from frontmatter); the verdict depends on the frame."""

    def _record(self) -> str:
        return json.dumps(
            {
                "predicates": [
                    {
                        "pov_label": "cam0",
                        "region": "entity_core",
                        "metric": "luma",
                        "op": "<=",
                        "target": 10.0,
                        "direction": "decrease",
                        "critical": True,
                    }
                ],
                "aggregation_floor": 0.75,
            }
        )

    def test_satisfying_frame_confirms(self) -> None:
        import numpy as np

        from shared.avsdlc_visual_intent import intent_hash_from_record, parse_intent_record
        from shared.avsdlc_witness import intent_fields_from_record_and_frame

        dark = np.zeros((100, 100, 3), dtype=np.uint8)  # entity_core luma ~0 <= 10
        declared = self._record()
        h, passed = intent_fields_from_record_and_frame(declared, dark, "cam0")
        assert h == intent_hash_from_record(parse_intent_record(declared))
        assert passed is True

    def test_contradicting_frame_rejects(self) -> None:
        import numpy as np

        from shared.avsdlc_witness import intent_fields_from_record_and_frame

        bright = np.full((100, 100, 3), 200, dtype=np.uint8)  # entity_core luma 200 > 10
        h, passed = intent_fields_from_record_and_frame(self._record(), bright, "cam0")
        assert h  # hash derived from the declared record, independent of the frame
        assert passed is False

    def test_unparseable_record_binds_no_intent(self) -> None:
        import numpy as np

        from shared.avsdlc_witness import intent_fields_from_record_and_frame

        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        h, passed = intent_fields_from_record_and_frame("{not json", frame, "cam0")
        assert h == "" and passed is False

    def test_malformed_frame_does_not_crash(self) -> None:
        import numpy as np

        from shared.avsdlc_witness import intent_fields_from_record_and_frame

        # None / wrong-shape frames must degrade to (declared_hash, False), never
        # raise — the witness producer must never crash the observe path.
        for bad in (None, np.zeros((10,), dtype=np.uint8)):
            h, passed = intent_fields_from_record_and_frame(  # type: ignore[arg-type]
                self._record(), bad, "cam0"
            )
            assert passed is False
            assert h  # the declared record still hashes (frame-independent)
