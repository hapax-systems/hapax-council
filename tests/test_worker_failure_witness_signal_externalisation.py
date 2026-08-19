"""The failure ledger must reference large raw signals, not re-embed them.

MEASURED 2026-08-19 on appendix before this change: ``failure-classification.jsonl``
was **732.7 MB across 3,614 records**, of which ``raw_signal`` was **731.1 MB
(99.8%)**. Only **11 of the 3,614 payloads were distinct** — one 186,359-character
string repeated **3,589 times**, a 328x dedupe ratio. The ledger re-embedded the
same error blob on every failure.

These tests pin the four properties that make the fix safe:

1. Large signals are externalised to a content-addressed blob.
2. **Losslessness** — the blob is byte-for-byte the original. Indirection, not
   truncation; the caller's contract is "one lossless line".
3. **Dedupe** — identical payloads collapse to one file, which is where the 328x
   comes from.
4. **Fail-open, narrowing** — if the blob cannot be written the payload stays
   INLINE (the previous behaviour) and the failure is recorded, never silent.

Small signals stay inline deliberately: they are worth more readable in the ledger
than deduplicated, and none of the bloat came from them.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from shared import worker_failure_witness as wfw

BIG = "E" * 200_000
SMALL = "boom"


@pytest.fixture(autouse=True)
def _blob_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "failure-signals"
    monkeypatch.setattr(wfw, "FAILURE_SIGNAL_BLOB_DIR", d)
    return d


def test_small_signal_stays_inline() -> None:
    out = wfw._externalise_raw_signal({"raw_signal": SMALL, "code": "X"})
    assert out["raw_signal"] == SMALL
    assert "raw_signal_ref" not in out


def test_large_signal_is_replaced_by_a_reference(_blob_dir: Path) -> None:
    out = wfw._externalise_raw_signal({"raw_signal": BIG, "code": "X"})
    assert "raw_signal" not in out
    ref = out["raw_signal_ref"]
    assert ref["sha256"] == hashlib.sha256(BIG.encode()).hexdigest()
    assert ref["bytes"] == len(BIG.encode())
    assert out["code"] == "X", "envelope fields must survive untouched"


def test_blob_is_byte_for_byte_lossless(_blob_dir: Path) -> None:
    """Indirection, not truncation. The original must be fully recoverable."""
    out = wfw._externalise_raw_signal({"raw_signal": BIG})
    blob = Path(out["raw_signal_ref"]["path"])
    assert blob.read_bytes() == BIG.encode()


def test_identical_payloads_collapse_to_one_blob(_blob_dir: Path) -> None:
    """This is where the measured 328x came from: 3,589 copies of one string."""
    refs = [wfw._externalise_raw_signal({"raw_signal": BIG})["raw_signal_ref"] for _ in range(5)]
    assert len({r["sha256"] for r in refs}) == 1
    assert len(list(_blob_dir.iterdir())) == 1, "identical payloads must not duplicate on disk"


def test_distinct_payloads_get_distinct_blobs(_blob_dir: Path) -> None:
    wfw._externalise_raw_signal({"raw_signal": BIG})
    wfw._externalise_raw_signal({"raw_signal": BIG + "different"})
    assert len(list(_blob_dir.iterdir())) == 2


def test_unwritable_blob_dir_keeps_payload_inline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail-open and NARROWING: degrade to the previous behaviour, and say so.

    Dropping the payload would be the widening failure — it would lose evidence
    that the pre-change code kept. Keeping it inline does strictly less.
    """
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("I am a file, not a directory")
    monkeypatch.setattr(wfw, "FAILURE_SIGNAL_BLOB_DIR", blocked / "sub")

    out = wfw._externalise_raw_signal({"raw_signal": BIG})
    assert out["raw_signal"] == BIG, "payload must NOT be lost when the blob write fails"
    assert "raw_signal_ref" not in out
    assert "raw_signal_ref_error" in out, "a swallowed failure must still be recorded"


def test_non_string_raw_signal_is_untouched() -> None:
    for value in (None, 123, {"a": 1}):
        payload = {"raw_signal": value}
        assert wfw._externalise_raw_signal(payload) == payload


# --------------------------------------------------------------------------
# Review findings from PR #4581 (CodeRabbit). Each of these pins a defect the
# original test suite could not reach.
# --------------------------------------------------------------------------


def test_lone_surrogates_survive_the_round_trip(_blob_dir: Path) -> None:
    """The original suite tested losslessness with ASCII only, so it could not fail.

    Python ``str`` admits lone surrogates — a subprocess whose bytes are decoded with
    ``errors="surrogateescape"`` produces them routinely, which is exactly how a raw
    failure signal gets captured. The first implementation encoded with
    ``errors="replace"``, turning each into "?", and THEN dropped the inline copy —
    silently destroying the only remaining copy while the suite stayed green because
    every fixture was ``"E" * 200_000``.
    """
    payload = "\ud800" * 5000 + "tail"
    out = wfw._externalise_raw_signal({"raw_signal": payload})
    assert "raw_signal_ref" in out, "should still externalise"
    recovered = wfw.read_raw_signal(out)
    assert recovered == payload, "lone surrogates must survive byte-for-byte"


def test_failed_replace_leaves_no_orphan_blob(
    _blob_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A storage failure must not GROW storage.

    If the temp write succeeds and ``os.replace`` fails, the payload-sized temp file
    would otherwise be orphaned in the blob dir on every retry.
    """

    def boom(*_a: object, **_k: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(wfw.os, "replace", boom)
    out = wfw._externalise_raw_signal({"raw_signal": BIG})

    assert out["raw_signal"] == BIG, "payload stays inline on failure"
    assert "raw_signal_ref_error" in out
    leftovers = list(_blob_dir.iterdir()) if _blob_dir.exists() else []
    assert leftovers == [], f"orphaned temp file(s): {leftovers}"


class TestReadRawSignal:
    """A format change with no reader is not forward-compatible, just broken later."""

    def test_reads_inline_shape(self) -> None:
        assert wfw.read_raw_signal({"raw_signal": SMALL}) == SMALL

    def test_reads_external_shape(self, _blob_dir: Path) -> None:
        out = wfw._externalise_raw_signal({"raw_signal": BIG})
        assert wfw.read_raw_signal(out) == BIG

    def test_rejects_wrong_sha(self, _blob_dir: Path) -> None:
        out = wfw._externalise_raw_signal({"raw_signal": BIG})
        out["raw_signal_ref"]["sha256"] = "0" * 64
        assert wfw.read_raw_signal(out) is None, "corruption must not be returned"

    def test_rejects_wrong_length(self, _blob_dir: Path) -> None:
        out = wfw._externalise_raw_signal({"raw_signal": BIG})
        out["raw_signal_ref"]["bytes"] = 1
        assert wfw.read_raw_signal(out) is None, "truncation must not be returned"

    def test_missing_blob_returns_none_not_raises(self, _blob_dir: Path) -> None:
        out = wfw._externalise_raw_signal({"raw_signal": BIG})
        Path(out["raw_signal_ref"]["path"]).unlink()
        assert wfw.read_raw_signal(out) is None

    def test_garbage_record_returns_none(self) -> None:
        for rec in ({}, {"raw_signal_ref": "not-a-mapping"}, {"raw_signal_ref": {}}):
            assert wfw.read_raw_signal(rec) is None


def test_record_written_to_ledger_is_small(tmp_path: Path, _blob_dir: Path) -> None:
    """End-to-end: the ledger LINE must shrink, which is the whole point."""
    receipt = wfw.FailureReceipt(raw_signal=BIG)
    ledger = tmp_path / "ledger.jsonl"
    assert wfw.append_failure_receipt_record(
        task_id="t",
        lane="l",
        returncode=1,
        receipt=receipt,
        now_iso="2026-08-19T00:00:00Z",
        ledger_path=ledger,
    )
    line = ledger.read_text().strip()
    assert len(line) < 2_000, f"ledger line still large: {len(line)} B"
    rec = json.loads(line)
    assert "raw_signal" not in rec
    assert Path(rec["raw_signal_ref"]["path"]).read_bytes() == BIG.encode()
