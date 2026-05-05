from __future__ import annotations

import json
import struct
from datetime import UTC, datetime
from pathlib import Path

from agents.art_50_provenance.livestream import (
    C2PA_VSI_EMSG_VALUE,
    C2PA_VSI_SCHEME_ID_URI,
    LiveSegmentSigner,
    LiveSegmentSigningStatus,
    LiveSegmentVerificationStatus,
    bmff_sha256_excluding_c2pa_emsg,
    count_c2pa_vsi_emsg_boxes,
    parse_emsg_boxes,
    sign_live_segment,
    verify_live_segment,
)
from agents.art_50_provenance.reverie_overlay import (
    DEFAULT_AI_DISCLOSURE_SOURCE_ID,
    render_ai_disclosure_rgba,
    write_reverie_ai_disclosure_source,
)
from agents.art_50_provenance.trust_list import (
    TrustListRefreshStatus,
    load_trust_anchors_pem,
    refresh_trust_list,
)
from agents.studio_compositor.hls_archive import (
    c2pa_sidecar_path_for,
    sign_archived_hls_segment,
)


def _box(box_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", len(payload) + 8, box_type) + payload


def _minimal_fmp4_segment(*, sequence_number: int = 7, payload: bytes = b"frames") -> bytes:
    styp = _box(b"styp", b"msdh\x00\x00\x00\x00msdhmsix")
    mfhd = _box(b"mfhd", b"\x00\x00\x00\x00" + struct.pack(">I", sequence_number))
    moof = _box(b"moof", mfhd)
    mdat = _box(b"mdat", payload)
    return styp + moof + mdat


def _test_signer(kid: str = "hapax-live-test-key") -> LiveSegmentSigner:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_key = Ed25519PrivateKey.generate()
    raw = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return LiveSegmentSigner(kid=kid.encode("utf-8"), private_key_raw=raw)


def test_sign_live_fmp4_segment_adds_c2pa_vsi_emsg_and_verifies() -> None:
    segment = _minimal_fmp4_segment(sequence_number=42, payload=b"encoded frame bytes")
    signer = _test_signer("hapax-live-test")
    original_hash = bmff_sha256_excluding_c2pa_emsg(segment)

    result = sign_live_segment(
        segment,
        signer=signer,
        stream_id="test-stream",
        target_duration_seconds=4.0,
        now=datetime(2026, 5, 5, 3, 45, tzinfo=UTC),
    )

    assert result.status is LiveSegmentSigningStatus.SIGNED_VSI_EMSG_PREVIEW
    assert result.output_bytes != segment
    assert result.sequence_number == 42
    assert result.latency_ms < 500
    assert result.manifest_preview is not None
    assert count_c2pa_vsi_emsg_boxes(result.output_bytes) == 1
    assert bmff_sha256_excluding_c2pa_emsg(result.output_bytes) == original_hash

    emsg = parse_emsg_boxes(result.output_bytes)[0]
    assert emsg.version == 0
    assert emsg.scheme_id_uri == C2PA_VSI_SCHEME_ID_URI
    assert emsg.value == C2PA_VSI_EMSG_VALUE
    assert emsg.event_duration == 4000

    verification = verify_live_segment(
        result.output_bytes,
        public_keys_by_kid={signer.kid: signer.public_key},
    )
    assert verification.status is LiveSegmentVerificationStatus.VALID_PREVIEW
    assert verification.bmff_sha256_match is True
    assert verification.signature_valid is True
    assert verification.sequence_number == 42

    labels = {
        assertion["label"]
        for assertion in result.manifest_preview["assertions"]
        if isinstance(assertion, dict)
    }
    assert "c2pa.ai-disclosure" in labels
    assert "org.hapax.article50.identity.v1" in labels
    assert "org.hapax.article50.live-session-keys.v1" in labels


def test_sign_live_segment_fails_closed_for_mpeg_ts_bytes() -> None:
    segment = b"\x47" + (b"\x00" * 187)
    signer = _test_signer()

    result = sign_live_segment(segment, signer=signer)

    assert result.status is LiveSegmentSigningStatus.BLOCKED_NOT_BMFF
    assert result.output_bytes == segment
    assert result.emsg_count == 0


def test_sign_live_fmp4_segment_fails_closed_without_signer() -> None:
    segment = _minimal_fmp4_segment()

    result = sign_live_segment(segment, signer=None)

    assert result.status is LiveSegmentSigningStatus.BLOCKED_MISSING_SIGNER
    assert result.output_bytes == segment
    assert result.bmff_sha256 == bmff_sha256_excluding_c2pa_emsg(segment)


def test_hls_archive_hook_signs_fmp4_and_writes_sidecar(tmp_path: Path) -> None:
    segment_path = tmp_path / "segment00042.m4s"
    segment_path.write_bytes(_minimal_fmp4_segment(sequence_number=42))
    signer = _test_signer("archive-hook")

    result = sign_archived_hls_segment(segment_path, signer=signer, target_duration_seconds=4.0)

    assert result.status is LiveSegmentSigningStatus.SIGNED_VSI_EMSG_PREVIEW
    assert count_c2pa_vsi_emsg_boxes(segment_path.read_bytes()) == 1
    sidecar = c2pa_sidecar_path_for(segment_path)
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["sidecar_kind"] == "art50_c2pa_live_vsi"
    assert payload["status"] == "signed_vsi_emsg_preview"
    verification = verify_live_segment(
        segment_path.read_bytes(),
        public_keys_by_kid={signer.kid: signer.public_key},
    )
    assert verification.status is LiveSegmentVerificationStatus.VALID_PREVIEW


def test_hls_archive_hook_records_ts_fail_closed_without_mutating(tmp_path: Path) -> None:
    segment_path = tmp_path / "segment00001.ts"
    original = b"\x47" + (b"\x00" * 187)
    segment_path.write_bytes(original)
    signer = _test_signer("archive-hook")

    result = sign_archived_hls_segment(segment_path, signer=signer)

    assert result.status is LiveSegmentSigningStatus.BLOCKED_NOT_BMFF
    assert segment_path.read_bytes() == original
    payload = json.loads(c2pa_sidecar_path_for(segment_path).read_text(encoding="utf-8"))
    assert payload["status"] == "blocked_not_bmff"


def test_refresh_trust_list_writes_cache_and_uses_cached_fallback(tmp_path: Path) -> None:
    pem = (
        b"-----BEGIN CERTIFICATE-----\nMIIBfakeC2PATrustAnchorForTests\n-----END CERTIFICATE-----\n"
    )
    cache_path = tmp_path / "trust" / "C2PA-TRUST-LIST.pem"

    class Response:
        content = pem

        def raise_for_status(self) -> None:
            return None

    def ok_get(url: str, *, timeout: float) -> Response:
        assert url.startswith("https://")
        assert timeout == 10.0
        return Response()

    result = refresh_trust_list(cache_path=cache_path, get=ok_get)

    assert result.status is TrustListRefreshStatus.REFRESHED
    assert result.anchor_count == 1
    assert load_trust_anchors_pem(cache_path) == pem.decode("utf-8")

    def failing_get(url: str, *, timeout: float) -> Response:
        raise RuntimeError("network down")

    fallback = refresh_trust_list(cache_path=cache_path, get=failing_get)

    assert fallback.status is TrustListRefreshStatus.CACHED_FALLBACK
    assert fallback.anchor_count == 1


def test_reverie_ai_disclosure_overlay_source_protocol(tmp_path: Path) -> None:
    rgba = render_ai_disclosure_rgba(width=320, height=180)
    assert len(rgba) == 320 * 180 * 4
    assert any(alpha > 0 for alpha in rgba[3::4])

    source_dir = write_reverie_ai_disclosure_source(
        sources_dir=tmp_path / "sources",
        width=320,
        height=180,
        opacity=0.9,
    )

    assert source_dir.name == DEFAULT_AI_DISCLOSURE_SOURCE_ID
    assert (source_dir / "frame.rgba").stat().st_size == 320 * 180 * 4
    manifest = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_id"] == DEFAULT_AI_DISCLOSURE_SOURCE_ID
    assert manifest["content_type"] == "rgba"
    assert manifest["opacity"] == 0.9
    assert manifest["z_order"] >= 900
    assert {"art50", "ai-disclosure", "eu-ai-act"} <= set(manifest["tags"])
