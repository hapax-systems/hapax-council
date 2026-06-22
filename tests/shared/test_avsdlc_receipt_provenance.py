"""AVSDLC visual-eval — receipt carries signed capture-provenance + perceptual digest.

Thin PR 2/N: the AVWitnessReceipt stops discarding the per-region perceptual
evidence at the receipt boundary. It now signs the capture ``via`` channel (so a
non-OBS capture can be rejected) and binds a deterministic ``perceptual_digest``
over the witness's per-region / per-artifact stats. Self-contained per convention.

cc-task: avsdlc-visual-eval-receipt-phase1 (CASE-AVSDLC-VISUAL-EVAL-20260621).
"""

from __future__ import annotations

from dataclasses import replace

from shared.avsdlc_witness import (
    build_receipt_from_witness,
    perceptual_digest_from_manifest,
    via_from_manifest,
)
from shared.governance.coord_capabilities import (
    mint_av_witness_receipt,
    parse_av_receipt,
    serialize_av_receipt,
    verify_av_witness_receipt,
)

KEY = b"operator-secret-key-0123456789abcdef"
NOW = 1_800_000_000.0
HASH = "a" * 64
HEAD = "9757f7bde"

_MANIFEST = {
    "overall": "PASS",
    "obs": {
        "via": "obs-websocket",
        "source": {
            "verdict": "MOVING",
            "mean_consecutive_delta": 1.2,
            "max_consecutive_delta": 3.4,
            "distinct": 6,
        },
    },
    "substrate": {
        "drift_currency": {
            "spatial_var": 12.3,
            "temporal_zone_moving_frac": 0.41,
            "byte_mad": 0.7,
        },
    },
}


def _receipt(via: str = "obs-websocket", perceptual_digest: str = "deadbeef"):
    return mint_av_witness_receipt(
        content_hash=HASH,
        active_source_head=HEAD,
        status="pass",
        obs_moving=True,
        ttl_s=1800.0,
        key=KEY,
        now=NOW,
        via=via,
        perceptual_digest=perceptual_digest,
    )


class TestViaFromManifest:
    def test_reads_recorded_via(self) -> None:
        assert via_from_manifest(_MANIFEST) == "obs-websocket"

    def test_unavailable_obs_is_empty(self) -> None:
        assert via_from_manifest({"obs": {"error": "x", "verdict": "OBS-UNAVAILABLE"}}) == ""

    def test_no_obs_is_empty(self) -> None:
        assert via_from_manifest({"overall": "PASS"}) == ""


class TestPerceptualDigest:
    def test_deterministic(self) -> None:
        assert perceptual_digest_from_manifest(_MANIFEST) == perceptual_digest_from_manifest(
            dict(_MANIFEST)
        )
        assert len(perceptual_digest_from_manifest(_MANIFEST)) == 64

    def test_changes_with_stats(self) -> None:
        m2 = {
            **_MANIFEST,
            "substrate": {
                "drift_currency": {
                    "spatial_var": 99.9,
                    "temporal_zone_moving_frac": 0.41,
                    "byte_mad": 0.7,
                }
            },
        }
        assert perceptual_digest_from_manifest(_MANIFEST) != perceptual_digest_from_manifest(m2)

    def test_empty_when_no_perceptual_stats(self) -> None:
        assert perceptual_digest_from_manifest({"overall": "PASS", "obs": {}}) == ""


class TestReceiptCarriesProvenance:
    def test_via_and_digest_signed_and_verify(self) -> None:
        r = _receipt()
        assert verify_av_witness_receipt(r, key=KEY, now=NOW + 60)
        assert r.via == "obs-websocket"
        assert r.perceptual_digest == "deadbeef"

    def test_serialize_parse_roundtrip_preserves(self) -> None:
        r = _receipt()
        loaded = parse_av_receipt(serialize_av_receipt(r))
        assert loaded is not None
        assert loaded.via == "obs-websocket"
        assert loaded.perceptual_digest == "deadbeef"
        assert verify_av_witness_receipt(loaded, key=KEY, now=NOW + 60)

    def test_tamper_via_rejected(self) -> None:
        assert not verify_av_witness_receipt(replace(_receipt(), via="x11"), key=KEY, now=NOW + 60)

    def test_tamper_perceptual_digest_rejected(self) -> None:
        assert not verify_av_witness_receipt(
            replace(_receipt(), perceptual_digest="0" * 8), key=KEY, now=NOW + 60
        )

    def test_backward_compatible_empty_via_digest_verify(self) -> None:
        # An old-format receipt (no via / perceptual_digest) still verifies when
        # require_via is off (staged rollout).
        r = _receipt(via="", perceptual_digest="")
        assert verify_av_witness_receipt(r, key=KEY, now=NOW + 60)


class TestRequireVia:
    def test_require_via_rejects_non_obs(self) -> None:
        assert not verify_av_witness_receipt(
            _receipt(via="x11"), key=KEY, now=NOW + 60, require_via=True
        )

    def test_require_via_rejects_empty(self) -> None:
        assert not verify_av_witness_receipt(
            _receipt(via=""), key=KEY, now=NOW + 60, require_via=True
        )

    def test_require_via_accepts_obs(self) -> None:
        assert verify_av_witness_receipt(
            _receipt(via="obs-websocket"), key=KEY, now=NOW + 60, require_via=True
        )


class TestBuildReceiptBindsProvenance:
    def test_build_from_manifest_binds_via_and_digest(self) -> None:
        r = build_receipt_from_witness(
            _MANIFEST,
            content_hash=HASH,
            active_source_head=HEAD,
            ttl_s=1800.0,
            key=KEY,
            now=NOW,
        )
        assert r.via == "obs-websocket"
        assert r.perceptual_digest == perceptual_digest_from_manifest(_MANIFEST)
        assert verify_av_witness_receipt(r, key=KEY, now=NOW + 60)


class TestReceiptBindsIntentHash:
    # PR 3/N adds intent_hash as a SIGNED field — TAMPER-EVIDENCE only (the HMAC
    # covers it). Intent<->bytes CORRESPONDENCE (the authored record's hash ==
    # receipt.intent_hash, evaluated against the realized vector) is PR 4/N gate
    # logic — NOT established here.
    def _intent_receipt(self, intent_hash: str = "i" * 64):
        return mint_av_witness_receipt(
            content_hash=HASH,
            active_source_head=HEAD,
            status="pass",
            obs_moving=True,
            ttl_s=1800.0,
            key=KEY,
            now=NOW,
            intent_hash=intent_hash,
        )

    def test_intent_hash_in_signing_payload(self) -> None:
        assert self._intent_receipt()._signing_payload()["intent_hash"] == "i" * 64

    def test_round_trip_with_intent_hash(self) -> None:
        loaded = parse_av_receipt(serialize_av_receipt(self._intent_receipt()))
        assert loaded is not None
        assert loaded.intent_hash == "i" * 64
        assert verify_av_witness_receipt(loaded, key=KEY, now=NOW + 60)

    def test_tamper_intent_hash_fails_verify(self) -> None:
        r = self._intent_receipt("a" * 64)
        assert not verify_av_witness_receipt(
            replace(r, intent_hash="b" * 64), key=KEY, now=NOW + 60
        )

    def test_missing_intent_field_defaults_empty(self) -> None:
        r = mint_av_witness_receipt(
            content_hash=HASH,
            active_source_head=HEAD,
            status="pass",
            obs_moving=True,
            ttl_s=1800.0,
            key=KEY,
            now=NOW,
        )
        data = dict(r._signing_payload())
        data["signature"] = r.signature
        data.pop("intent_hash", None)
        loaded = parse_av_receipt(data)
        assert loaded is not None and loaded.intent_hash == ""

    def test_empty_intent_receipt_verifies_unchanged(self) -> None:
        # A non-visual AV release (no intent) mints with intent_hash="" and
        # verifies exactly as a pre-intent receipt — backward-compatible.
        r = mint_av_witness_receipt(
            content_hash=HASH,
            active_source_head=HEAD,
            status="pass",
            obs_moving=True,
            ttl_s=1800.0,
            key=KEY,
            now=NOW,
        )
        assert r.intent_hash == ""
        assert verify_av_witness_receipt(r, key=KEY, now=NOW + 60)
