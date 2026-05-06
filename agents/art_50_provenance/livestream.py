"""C2PA live-video Verifiable Segment Info primitives.

This module implements the SW-side MVP for fMP4/CMAF HLS segments. It is
strict about the current production mismatch: Hapax still emits MPEG-TS via
``hlssink2``, so non-BMFF segments return an explicit blocked state and the
bytes are left untouched.

For BMFF media segments, the implementation writes a C2PA-shaped
``emsg`` box using the live-video Verifiable Segment Info profile:

* ``scheme_id_uri = "urn:c2pa:verifiable-segment-info"``
* ``value = "fseg"``
* ``version = 0``
* ``message_data = COSE_Sign1_Tagged(CBOR(segment-info-map))``

The session key is Ed25519 because the local runtime has ``cryptography`` but
not the full ``c2pa-python``/COSE/CBOR stack. The emitted structure is suitable
for deterministic local validation and keeps the production trust gap explicit:
it is not a substitute for C2PA Conformance Program certificate provisioning.
"""

from __future__ import annotations

import base64
import hashlib
import struct
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from agents.art_50_provenance.manifest import (
    C2PA_SPEC_VERSION,
    CLAIM_GENERATOR_NAME,
    CLAIM_GENERATOR_VERSION,
    DIGITAL_SOURCE_TYPE_TRAINED_ALGORITHMIC_MEDIA,
)
from agents.art_50_provenance.models import DEFAULT_V5_IDENTITIES

C2PA_VSI_SCHEME_ID_URI = "urn:c2pa:verifiable-segment-info"
C2PA_VSI_EMSG_VALUE = "fseg"
C2PA_COSE_SIGN1_TAG = 18
COSE_ALG_HEADER = 1
COSE_KID_HEADER = 4
COSE_ALG_EDDSA = -8
DEFAULT_STREAM_ID = "hapax-studio-hls"
DEFAULT_TIMESCALE = 1000
LIVE_CLAIM_GENERATOR_NAME = "hapax-art50-livestream"


class LiveSegmentSigningStatus(StrEnum):
    """Outcome of an attempted live segment signing step."""

    SIGNED_VSI_EMSG_PREVIEW = "signed_vsi_emsg_preview"
    BLOCKED_NOT_BMFF = "blocked_not_bmff"
    BLOCKED_NOT_MEDIA_SEGMENT = "blocked_not_media_segment"
    BLOCKED_MISSING_SIGNER = "blocked_missing_signer"
    SIGNING_ERROR = "signing_error"


class LiveSegmentVerificationStatus(StrEnum):
    """Local verifier outcome for a segment carrying C2PA live VSI."""

    VALID_PREVIEW = "valid_preview"
    INVALID = "invalid"
    MISSING_EMSG = "missing_emsg"


class BmffParseError(ValueError):
    """Raised when a byte string is not a parseable top-level BMFF segment."""


@dataclass(frozen=True)
class Mp4Box:
    """Parsed BMFF box span."""

    box_type: bytes
    start: int
    end: int
    payload_start: int

    @property
    def size(self) -> int:
        return self.end - self.start

    def payload(self, data: bytes) -> bytes:
        return data[self.payload_start : self.end]

    def raw(self, data: bytes) -> bytes:
        return data[self.start : self.end]


@dataclass(frozen=True)
class EmsgBox:
    """Parsed Event Message box fields used by C2PA live VSI."""

    box: Mp4Box
    version: int
    scheme_id_uri: str
    value: str
    timescale: int
    presentation_time_delta: int
    event_duration: int
    event_id: int
    message_data: bytes


@dataclass(frozen=True)
class CborTag:
    """Small internal representation for tagged CBOR values."""

    tag: int
    value: Any


@dataclass(frozen=True)
class LiveSegmentPublicKey:
    """A live-video session public key used for local VSI verification."""

    kid: bytes
    public_key_raw: bytes

    @classmethod
    def from_base64(cls, *, kid: str | bytes, public_key_b64: str) -> LiveSegmentPublicKey:
        return cls(kid=_kid_bytes(kid), public_key_raw=base64.b64decode(public_key_b64))

    @property
    def kid_text(self) -> str:
        return self.kid.decode("utf-8", errors="replace")

    @property
    def public_key_b64(self) -> str:
        return base64.b64encode(self.public_key_raw).decode("ascii")

    def verify(self, signature: bytes, message: bytes) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        Ed25519PublicKey.from_public_bytes(self.public_key_raw).verify(signature, message)


@dataclass(frozen=True)
class LiveSegmentSigner:
    """Local Ed25519 session signer for the VSI MVP."""

    kid: bytes
    private_key_raw: bytes

    @classmethod
    def from_private_key_base64(
        cls, *, kid: str | bytes, private_key_b64: str
    ) -> LiveSegmentSigner:
        return cls(kid=_kid_bytes(kid), private_key_raw=base64.b64decode(private_key_b64))

    @property
    def kid_text(self) -> str:
        return self.kid.decode("utf-8", errors="replace")

    @property
    def private_key_b64(self) -> str:
        return base64.b64encode(self.private_key_raw).decode("ascii")

    @property
    def public_key(self) -> LiveSegmentPublicKey:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        private_key = Ed25519PrivateKey.from_private_bytes(self.private_key_raw)
        public_raw = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return LiveSegmentPublicKey(kid=self.kid, public_key_raw=public_raw)

    def sign(self, message: bytes) -> bytes:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        return Ed25519PrivateKey.from_private_bytes(self.private_key_raw).sign(message)


@dataclass(frozen=True)
class LiveSegmentSigningResult:
    """Result of signing or explicitly declining to sign one segment."""

    status: LiveSegmentSigningStatus
    output_bytes: bytes
    detail: str
    stream_id: str
    sequence_number: int | None
    manifest_id: str | None
    bmff_sha256: str | None
    mdat_sha256: str | None
    emsg_count: int
    latency_ms: float
    manifest_preview: dict[str, Any] | None = None
    segment_info: dict[str, Any] | None = None

    @property
    def signed(self) -> bool:
        return self.status is LiveSegmentSigningStatus.SIGNED_VSI_EMSG_PREVIEW

    def to_sidecar_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "2026-05-05.c2pa-live-vsi-mvp.v1",
            "status": self.status.value,
            "detail": self.detail,
            "stream_id": self.stream_id,
            "sequence_number": self.sequence_number,
            "manifest_id": self.manifest_id,
            "bmff_sha256": self.bmff_sha256,
            "mdat_sha256": self.mdat_sha256,
            "emsg_count": self.emsg_count,
            "latency_ms": round(self.latency_ms, 3),
            "c2pa": {
                "spec_version": C2PA_SPEC_VERSION,
                "live_vsi_scheme_id_uri": C2PA_VSI_SCHEME_ID_URI,
                "emsg_value": C2PA_VSI_EMSG_VALUE,
                "trust_note": (
                    "Local session-key preview; production trust requires C2PA trust-list "
                    "certificate provisioning and validator configuration."
                ),
            },
            "manifest_preview": self.manifest_preview,
            "segment_info": _json_safe(self.segment_info),
        }


@dataclass(frozen=True)
class LiveSegmentVerificationResult:
    """Local verification result for a live segment."""

    status: LiveSegmentVerificationStatus
    reasons: tuple[str, ...]
    stream_id: str | None
    sequence_number: int | None
    manifest_id: str | None
    bmff_sha256_match: bool | None
    signature_valid: bool | None
    emsg_count: int
    segment_info: dict[str, Any] | None = None


def sign_live_segment(
    segment_bytes: bytes,
    *,
    signer: LiveSegmentSigner | None,
    stream_id: str = DEFAULT_STREAM_ID,
    sequence_number: int | None = None,
    target_duration_seconds: float = 2.0,
    manifest_id: str | None = None,
    now: datetime | None = None,
    timescale: int = DEFAULT_TIMESCALE,
) -> LiveSegmentSigningResult:
    """Add a C2PA live VSI ``emsg`` box to a BMFF media segment.

    Non-BMFF and non-media segments return blocked statuses with
    ``output_bytes`` equal to ``segment_bytes``.
    """

    started = time.perf_counter()
    issued_at = now or datetime.now(UTC)
    try:
        boxes = list(iter_top_level_boxes(segment_bytes))
    except BmffParseError as exc:
        return _blocked_signing_result(
            status=LiveSegmentSigningStatus.BLOCKED_NOT_BMFF,
            segment_bytes=segment_bytes,
            detail=str(exc),
            stream_id=stream_id,
            started=started,
        )

    box_types = {box.box_type for box in boxes}
    if b"moof" not in box_types or b"mdat" not in box_types:
        return _blocked_signing_result(
            status=LiveSegmentSigningStatus.BLOCKED_NOT_MEDIA_SEGMENT,
            segment_bytes=segment_bytes,
            detail="BMFF segment must contain top-level moof and mdat boxes",
            stream_id=stream_id,
            started=started,
            boxes=boxes,
        )

    if signer is None:
        return _blocked_signing_result(
            status=LiveSegmentSigningStatus.BLOCKED_MISSING_SIGNER,
            segment_bytes=segment_bytes,
            detail="live C2PA session signer is not configured",
            stream_id=stream_id,
            started=started,
            boxes=boxes,
        )

    try:
        effective_sequence = (
            _sequence_number_from_moof(segment_bytes, boxes) or sequence_number or 0
        )
        effective_manifest_id = manifest_id or _manifest_id(stream_id, effective_sequence)
        bmff_digest = bmff_sha256_excluding_c2pa_emsg(segment_bytes)
        mdat_digest = mdat_sha256(segment_bytes)
        segment_info = _segment_info_map(
            sequence_number=effective_sequence,
            manifest_id=effective_manifest_id,
            bmff_digest=bytes.fromhex(bmff_digest),
        )
        cose = _build_cose_sign1(segment_info=segment_info, signer=signer)
        emsg = build_c2pa_vsi_emsg_box(
            message_data=cose,
            target_duration_seconds=target_duration_seconds,
            timescale=timescale,
            event_id=effective_sequence,
        )
        output = _insert_emsg(segment_bytes, boxes=boxes, emsg_box=emsg)
        manifest_preview = build_live_manifest_preview(
            stream_id=stream_id,
            sequence_number=effective_sequence,
            manifest_id=effective_manifest_id,
            signer=signer,
            bmff_sha256=bmff_digest,
            mdat_sha256=mdat_digest,
            issued_at=issued_at,
        )
    except Exception as exc:
        return _blocked_signing_result(
            status=LiveSegmentSigningStatus.SIGNING_ERROR,
            segment_bytes=segment_bytes,
            detail=f"{type(exc).__name__}: {exc}",
            stream_id=stream_id,
            started=started,
            boxes=boxes,
        )

    return LiveSegmentSigningResult(
        status=LiveSegmentSigningStatus.SIGNED_VSI_EMSG_PREVIEW,
        output_bytes=output,
        detail="C2PA live VSI emsg preview inserted",
        stream_id=stream_id,
        sequence_number=effective_sequence,
        manifest_id=effective_manifest_id,
        bmff_sha256=bmff_digest,
        mdat_sha256=mdat_digest,
        emsg_count=count_c2pa_vsi_emsg_boxes(output),
        latency_ms=(time.perf_counter() - started) * 1000,
        manifest_preview=manifest_preview,
        segment_info=segment_info,
    )


def verify_live_segment(
    segment_bytes: bytes,
    *,
    public_keys_by_kid: Mapping[bytes | str, LiveSegmentPublicKey | bytes | str] | None = None,
) -> LiveSegmentVerificationResult:
    """Verify a segment signed by :func:`sign_live_segment`.

    This is a local preview verifier. It validates the C2PA ``emsg`` shape,
    the BMFF hash excluding C2PA ``emsg`` boxes, and the COSE Sign1 signature
    against provided session public keys.
    """

    try:
        boxes = list(iter_top_level_boxes(segment_bytes))
    except BmffParseError as exc:
        return LiveSegmentVerificationResult(
            status=LiveSegmentVerificationStatus.INVALID,
            reasons=(f"not_bmff:{exc}",),
            stream_id=None,
            sequence_number=None,
            manifest_id=None,
            bmff_sha256_match=None,
            signature_valid=None,
            emsg_count=0,
        )

    emsgs = [
        emsg for emsg in parse_emsg_boxes(segment_bytes, boxes=boxes) if _is_c2pa_vsi_emsg(emsg)
    ]
    if not emsgs:
        return LiveSegmentVerificationResult(
            status=LiveSegmentVerificationStatus.MISSING_EMSG,
            reasons=("missing_c2pa_vsi_emsg",),
            stream_id=None,
            sequence_number=None,
            manifest_id=None,
            bmff_sha256_match=None,
            signature_valid=None,
            emsg_count=0,
        )

    reasons: list[str] = []
    current_bmff_digest = bmff_sha256_excluding_c2pa_emsg(segment_bytes)
    for emsg in emsgs:
        decoded = _decode_cose_sign1(emsg.message_data)
        if decoded is None:
            reasons.append("invalid_cose_sign1")
            continue

        segment_info = decoded["segment_info"]
        kid = decoded["kid"]
        expected_digest = segment_info.get("bmffHash", {}).get("hash")
        bmff_match = (
            isinstance(expected_digest, bytes) and expected_digest.hex() == current_bmff_digest
        )
        public_key = _lookup_public_key(public_keys_by_kid or {}, kid)
        signature_valid: bool | None = None
        if public_key is None:
            reasons.append(f"missing_session_key:{kid.decode('utf-8', errors='replace')}")
        else:
            try:
                public_key.verify(decoded["signature"], decoded["sig_structure"])
                signature_valid = True
            except Exception:
                signature_valid = False
                reasons.append("signature_invalid")

        if not bmff_match:
            reasons.append("bmff_hash_mismatch")

        if bmff_match and signature_valid:
            return LiveSegmentVerificationResult(
                status=LiveSegmentVerificationStatus.VALID_PREVIEW,
                reasons=(),
                stream_id=None,
                sequence_number=segment_info.get("sequenceNumber"),
                manifest_id=segment_info.get("manifestId"),
                bmff_sha256_match=True,
                signature_valid=True,
                emsg_count=len(emsgs),
                segment_info=segment_info,
            )

        return LiveSegmentVerificationResult(
            status=LiveSegmentVerificationStatus.INVALID,
            reasons=tuple(reasons),
            stream_id=None,
            sequence_number=segment_info.get("sequenceNumber"),
            manifest_id=segment_info.get("manifestId"),
            bmff_sha256_match=bmff_match,
            signature_valid=signature_valid,
            emsg_count=len(emsgs),
            segment_info=segment_info,
        )

    return LiveSegmentVerificationResult(
        status=LiveSegmentVerificationStatus.INVALID,
        reasons=tuple(reasons) or ("no_decodable_c2pa_vsi_emsg",),
        stream_id=None,
        sequence_number=None,
        manifest_id=None,
        bmff_sha256_match=None,
        signature_valid=None,
        emsg_count=len(emsgs),
    )


def build_live_manifest_preview(
    *,
    stream_id: str,
    sequence_number: int,
    manifest_id: str,
    signer: LiveSegmentSigner,
    bmff_sha256: str,
    mdat_sha256: str | None,
    issued_at: datetime,
) -> dict[str, Any]:
    """Build the init-manifest preview that would carry live session keys."""

    identities = [identity.model_dump(mode="json") for identity in DEFAULT_V5_IDENTITIES]
    return {
        "claim_generator_info": [
            {
                "name": LIVE_CLAIM_GENERATOR_NAME,
                "version": CLAIM_GENERATOR_VERSION,
                "specVersion": C2PA_SPEC_VERSION,
            }
        ],
        "title": f"Hapax live HLS stream {stream_id}",
        "format": "video/mp4",
        "assertions": [
            {
                "label": "c2pa.actions.v2",
                "data": {
                    "actions": [
                        {
                            "action": "c2pa.created",
                            "digitalSourceType": DIGITAL_SOURCE_TYPE_TRAINED_ALGORITHMIC_MEDIA,
                            "softwareAgents": [
                                {
                                    "name": CLAIM_GENERATOR_NAME,
                                    "version": CLAIM_GENERATOR_VERSION,
                                },
                                {
                                    "name": LIVE_CLAIM_GENERATOR_NAME,
                                    "version": CLAIM_GENERATOR_VERSION,
                                },
                            ],
                            "parameters": {
                                "stream_id": stream_id,
                                "manifest_id": manifest_id,
                                "issued_at": _rfc3339(issued_at),
                            },
                        },
                        {
                            "action": "c2pa.published",
                            "softwareAgents": [
                                {
                                    "name": LIVE_CLAIM_GENERATOR_NAME,
                                    "version": CLAIM_GENERATOR_VERSION,
                                }
                            ],
                            "parameters": {
                                "stream_id": stream_id,
                                "sequence_number": sequence_number,
                            },
                        },
                    ]
                },
            },
            {
                "label": "c2pa.ai-disclosure",
                "data": {
                    "modelType": "c2pa.types.model.live-video-generator",
                    "contentProfile": {"humanOversightLevel": "prompt_guided"},
                    "visibleDisclosure": "AI",
                },
            },
            {
                "label": "org.hapax.article50.identity.v1",
                "data": {
                    "attribution_mode": "V5 unsettled-attribution",
                    "identities": identities,
                    "roles": {
                        "ingredient": "Hapax LLM stack",
                        "deployer": "Oudepode",
                    },
                    "pii_policy": "no customer PII fields in live manifest payload",
                },
            },
            {
                "label": "org.hapax.article50.live-session-keys.v1",
                "data": {
                    "kid": signer.kid_text,
                    "public_key_b64": signer.public_key.public_key_b64,
                    "algorithm": "Ed25519/COSE EdDSA preview",
                    "provisioning_state": "local_session_key_not_c2pa_trust_listed",
                },
            },
            {
                "label": "org.hapax.article50.live-segment.v1",
                "data": {
                    "stream_id": stream_id,
                    "sequence_number": sequence_number,
                    "manifest_id": manifest_id,
                    "bmff_sha256_excluding_c2pa_emsg": bmff_sha256,
                    "mdat_sha256": mdat_sha256,
                    "emsg_scheme_id_uri": C2PA_VSI_SCHEME_ID_URI,
                    "emsg_value": C2PA_VSI_EMSG_VALUE,
                },
            },
        ],
    }


def iter_top_level_boxes(data: bytes) -> list[Mp4Box]:
    """Parse top-level BMFF boxes with strict size validation."""

    boxes = _iter_boxes(data, 0, len(data))
    if not boxes:
        raise BmffParseError("no BMFF boxes found")
    first_type = boxes[0].box_type
    if first_type not in {b"ftyp", b"styp", b"moov", b"moof", b"sidx"}:
        raise BmffParseError(f"unexpected first BMFF box type: {first_type!r}")
    return boxes


def bmff_sha256_excluding_c2pa_emsg(data: bytes) -> str:
    """Hash a BMFF segment while excluding C2PA live VSI ``emsg`` boxes."""

    boxes = iter_top_level_boxes(data)
    digest = hashlib.sha256()
    for box in boxes:
        if box.box_type == b"emsg":
            emsg = _parse_emsg_box(data, box)
            if emsg is not None and _is_c2pa_vsi_emsg(emsg):
                continue
        digest.update(box.raw(data))
    return digest.hexdigest()


def mdat_sha256(data: bytes) -> str | None:
    """Return a convenience SHA-256 over concatenated top-level ``mdat`` payloads."""

    boxes = iter_top_level_boxes(data)
    digest = hashlib.sha256()
    found = False
    for box in boxes:
        if box.box_type == b"mdat":
            digest.update(box.payload(data))
            found = True
    return digest.hexdigest() if found else None


def parse_emsg_boxes(data: bytes, *, boxes: list[Mp4Box] | None = None) -> list[EmsgBox]:
    """Return parseable top-level ``emsg`` boxes."""

    parsed_boxes = boxes if boxes is not None else iter_top_level_boxes(data)
    emsgs: list[EmsgBox] = []
    for box in parsed_boxes:
        if box.box_type != b"emsg":
            continue
        emsg = _parse_emsg_box(data, box)
        if emsg is not None:
            emsgs.append(emsg)
    return emsgs


def count_c2pa_vsi_emsg_boxes(data: bytes) -> int:
    return sum(1 for emsg in parse_emsg_boxes(data) if _is_c2pa_vsi_emsg(emsg))


def build_c2pa_vsi_emsg_box(
    *,
    message_data: bytes,
    target_duration_seconds: float,
    timescale: int = DEFAULT_TIMESCALE,
    event_id: int = 0,
) -> bytes:
    """Build a C2PA live VSI Event Message box using version 0 fields."""

    duration_ticks = max(1, round(target_duration_seconds * timescale))
    body = (
        b"\x00\x00\x00\x00"
        + C2PA_VSI_SCHEME_ID_URI.encode("utf-8")
        + b"\x00"
        + C2PA_VSI_EMSG_VALUE.encode("utf-8")
        + b"\x00"
        + struct.pack(">IIII", timescale, 0, duration_ticks, event_id)
        + message_data
    )
    return struct.pack(">I4s", len(body) + 8, b"emsg") + body


def load_signer_from_env() -> LiveSegmentSigner | None:
    """Load the optional live segment signer from environment variables."""

    import os

    key_b64 = os.environ.get("HAPAX_ART50_LIVE_SIGNING_PRIVATE_KEY_B64")
    if not key_b64:
        return None
    kid = os.environ.get("HAPAX_ART50_LIVE_SIGNING_KID", "hapax-live-session")
    return LiveSegmentSigner.from_private_key_base64(kid=kid, private_key_b64=key_b64)


def write_signed_segment(path: Path, result: LiveSegmentSigningResult) -> None:
    """Atomically replace ``path`` with signed bytes."""

    tmp = path.with_name(f".{path.name}.c2pa.tmp")
    tmp.write_bytes(result.output_bytes)
    tmp.replace(path)


def _blocked_signing_result(
    *,
    status: LiveSegmentSigningStatus,
    segment_bytes: bytes,
    detail: str,
    stream_id: str,
    started: float,
    boxes: list[Mp4Box] | None = None,
) -> LiveSegmentSigningResult:
    bmff_digest: str | None = None
    mdat_digest: str | None = None
    emsg_count = 0
    if boxes is not None:
        try:
            bmff_digest = bmff_sha256_excluding_c2pa_emsg(segment_bytes)
            mdat_digest = mdat_sha256(segment_bytes)
            emsg_count = count_c2pa_vsi_emsg_boxes(segment_bytes)
        except BmffParseError:
            pass
    return LiveSegmentSigningResult(
        status=status,
        output_bytes=segment_bytes,
        detail=detail,
        stream_id=stream_id,
        sequence_number=None,
        manifest_id=None,
        bmff_sha256=bmff_digest,
        mdat_sha256=mdat_digest,
        emsg_count=emsg_count,
        latency_ms=(time.perf_counter() - started) * 1000,
    )


def _insert_emsg(data: bytes, *, boxes: list[Mp4Box], emsg_box: bytes) -> bytes:
    moof = next(box for box in boxes if box.box_type == b"moof")
    insertion_offset = moof.start
    return data[:insertion_offset] + emsg_box + data[insertion_offset:]


def _segment_info_map(
    *,
    sequence_number: int,
    manifest_id: str,
    bmff_digest: bytes,
) -> dict[str, Any]:
    return {
        "sequenceNumber": sequence_number,
        "manifestId": manifest_id,
        "bmffHash": {
            "alg": "sha256",
            "name": "Hapax C2PA live VSI fMP4 segment hash",
            "hash": bmff_digest,
            "exclusions": [
                {
                    "xpath": "/emsg",
                    "data": [
                        {
                            "offset": 0,
                            "value": C2PA_VSI_SCHEME_ID_URI,
                        }
                    ],
                }
            ],
        },
    }


def _build_cose_sign1(
    *,
    segment_info: dict[str, Any],
    signer: LiveSegmentSigner,
) -> bytes:
    protected = _cbor_encode({COSE_ALG_HEADER: COSE_ALG_EDDSA})
    payload = _cbor_encode(segment_info)
    sig_structure = _cbor_encode(["Signature1", protected, b"", payload])
    signature = signer.sign(sig_structure)
    cose = CborTag(
        C2PA_COSE_SIGN1_TAG,
        [
            protected,
            {COSE_KID_HEADER: signer.kid},
            payload,
            signature,
        ],
    )
    return _cbor_encode(cose)


def _decode_cose_sign1(message_data: bytes) -> dict[str, Any] | None:
    try:
        decoded, offset = _cbor_decode(message_data, 0)
        if offset != len(message_data):
            return None
        if not isinstance(decoded, CborTag) or decoded.tag != C2PA_COSE_SIGN1_TAG:
            return None
        if not isinstance(decoded.value, list) or len(decoded.value) != 4:
            return None
        protected, unprotected, payload, signature = decoded.value
        if not isinstance(protected, bytes) or not isinstance(unprotected, dict):
            return None
        if not isinstance(payload, bytes) or not isinstance(signature, bytes):
            return None
        protected_map, protected_end = _cbor_decode(protected, 0)
        if protected_end != len(protected) or not isinstance(protected_map, dict):
            return None
        if protected_map.get(COSE_ALG_HEADER) != COSE_ALG_EDDSA:
            return None
        kid = unprotected.get(COSE_KID_HEADER)
        if not isinstance(kid, bytes):
            return None
        segment_info, payload_end = _cbor_decode(payload, 0)
        if payload_end != len(payload) or not isinstance(segment_info, dict):
            return None
        sig_structure = _cbor_encode(["Signature1", protected, b"", payload])
    except (IndexError, UnicodeDecodeError, ValueError, struct.error):
        return None
    return {
        "protected": protected_map,
        "kid": kid,
        "segment_info": segment_info,
        "signature": signature,
        "sig_structure": sig_structure,
    }


def _iter_boxes(data: bytes, start: int, end: int) -> list[Mp4Box]:
    boxes: list[Mp4Box] = []
    offset = start
    while offset < end:
        remaining = end - offset
        if remaining < 8:
            raise BmffParseError(f"trailing {remaining} bytes after BMFF boxes")
        size = struct.unpack_from(">I", data, offset)[0]
        box_type = data[offset + 4 : offset + 8]
        header = 8
        if size == 1:
            if remaining < 16:
                raise BmffParseError("large-size BMFF box header is truncated")
            size = struct.unpack_from(">Q", data, offset + 8)[0]
            header = 16
        elif size == 0:
            size = remaining
        if size < header:
            raise BmffParseError(f"invalid BMFF box size {size} for {box_type!r}")
        box_end = offset + size
        if box_end > end:
            raise BmffParseError(f"BMFF box {box_type!r} overruns segment")
        boxes.append(
            Mp4Box(box_type=box_type, start=offset, end=box_end, payload_start=offset + header)
        )
        offset = box_end
    return boxes


def _parse_emsg_box(data: bytes, box: Mp4Box) -> EmsgBox | None:
    payload = box.payload(data)
    if len(payload) < 4:
        return None
    version = payload[0]
    if version != 0:
        return None
    offset = 4
    scheme, offset = _read_c_string(payload, offset)
    value, offset = _read_c_string(payload, offset)
    if len(payload) - offset < 16:
        return None
    timescale, presentation_delta, event_duration, event_id = struct.unpack_from(
        ">IIII", payload, offset
    )
    offset += 16
    return EmsgBox(
        box=box,
        version=version,
        scheme_id_uri=scheme,
        value=value,
        timescale=timescale,
        presentation_time_delta=presentation_delta,
        event_duration=event_duration,
        event_id=event_id,
        message_data=payload[offset:],
    )


def _read_c_string(data: bytes, offset: int) -> tuple[str, int]:
    end = data.index(0, offset)
    return data[offset:end].decode("utf-8"), end + 1


def _is_c2pa_vsi_emsg(emsg: EmsgBox) -> bool:
    return (
        emsg.version == 0
        and emsg.scheme_id_uri == C2PA_VSI_SCHEME_ID_URI
        and emsg.value == C2PA_VSI_EMSG_VALUE
    )


def _sequence_number_from_moof(data: bytes, boxes: list[Mp4Box]) -> int | None:
    moof = next((box for box in boxes if box.box_type == b"moof"), None)
    if moof is None:
        return None
    try:
        children = _iter_boxes(data, moof.payload_start, moof.end)
    except BmffParseError:
        return None
    mfhd = next((box for box in children if box.box_type == b"mfhd"), None)
    if mfhd is None or mfhd.end - mfhd.payload_start < 8:
        return None
    return struct.unpack_from(">I", data, mfhd.payload_start + 4)[0]


def _manifest_id(stream_id: str, sequence_number: int) -> str:
    value = uuid.uuid5(uuid.NAMESPACE_URL, f"hapax-live-vsi:{stream_id}:{sequence_number}")
    return f"urn:c2pa:{value}"


def _kid_bytes(kid: str | bytes) -> bytes:
    return kid if isinstance(kid, bytes) else kid.encode("utf-8")


def _lookup_public_key(
    public_keys_by_kid: Mapping[bytes | str, LiveSegmentPublicKey | bytes | str],
    kid: bytes,
) -> LiveSegmentPublicKey | None:
    raw = public_keys_by_kid.get(kid)
    if raw is None:
        raw = public_keys_by_kid.get(kid.decode("utf-8", errors="replace"))
    if raw is None:
        return None
    if isinstance(raw, LiveSegmentPublicKey):
        return raw
    if isinstance(raw, bytes):
        return LiveSegmentPublicKey(kid=kid, public_key_raw=raw)
    return LiveSegmentPublicKey.from_base64(kid=kid, public_key_b64=raw)


def _rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, dict):
        return {str(_json_safe(k)): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _cbor_encode(value: Any) -> bytes:
    if isinstance(value, CborTag):
        return _cbor_head(6, value.tag) + _cbor_encode(value.value)
    if isinstance(value, bool):
        return b"\xf5" if value else b"\xf4"
    if value is None:
        return b"\xf6"
    if isinstance(value, int):
        if value >= 0:
            return _cbor_head(0, value)
        return _cbor_head(1, -1 - value)
    if isinstance(value, bytes):
        return _cbor_head(2, len(value)) + value
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        return _cbor_head(3, len(encoded)) + encoded
    if isinstance(value, (list, tuple)):
        return _cbor_head(4, len(value)) + b"".join(_cbor_encode(item) for item in value)
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda item: _cbor_encode(item[0]))
        body = b"".join(_cbor_encode(key) + _cbor_encode(item_value) for key, item_value in items)
        return _cbor_head(5, len(items)) + body
    raise TypeError(f"unsupported CBOR value: {type(value).__name__}")


def _cbor_head(major: int, value: int) -> bytes:
    if value < 24:
        return bytes([(major << 5) | value])
    if value <= 0xFF:
        return bytes([(major << 5) | 24, value])
    if value <= 0xFFFF:
        return bytes([(major << 5) | 25]) + struct.pack(">H", value)
    if value <= 0xFFFFFFFF:
        return bytes([(major << 5) | 26]) + struct.pack(">I", value)
    return bytes([(major << 5) | 27]) + struct.pack(">Q", value)


def _cbor_decode(data: bytes, offset: int = 0) -> tuple[Any, int]:
    if offset >= len(data):
        raise ValueError("CBOR decode past end")
    initial = data[offset]
    offset += 1
    major = initial >> 5
    additional = initial & 0x1F
    value, offset = _cbor_read_uint(data, offset, additional)
    if major == 0:
        return value, offset
    if major == 1:
        return -1 - value, offset
    if major == 2:
        end = offset + value
        if end > len(data):
            raise ValueError("CBOR byte string overruns input")
        return data[offset:end], end
    if major == 3:
        end = offset + value
        if end > len(data):
            raise ValueError("CBOR text string overruns input")
        return data[offset:end].decode("utf-8"), end
    if major == 4:
        items: list[Any] = []
        for _ in range(value):
            item, offset = _cbor_decode(data, offset)
            items.append(item)
        return items, offset
    if major == 5:
        mapping: dict[Any, Any] = {}
        for _ in range(value):
            key, offset = _cbor_decode(data, offset)
            item, offset = _cbor_decode(data, offset)
            mapping[key] = item
        return mapping, offset
    if major == 6:
        tagged, offset = _cbor_decode(data, offset)
        return CborTag(tag=value, value=tagged), offset
    if major == 7:
        if additional == 20:
            return False, offset
        if additional == 21:
            return True, offset
        if additional == 22:
            return None, offset
    raise ValueError(f"unsupported CBOR major/additional: {major}/{additional}")


def _cbor_read_uint(data: bytes, offset: int, additional: int) -> tuple[int, int]:
    if additional < 24:
        return additional, offset
    if additional == 24:
        return data[offset], offset + 1
    if additional == 25:
        return struct.unpack_from(">H", data, offset)[0], offset + 2
    if additional == 26:
        return struct.unpack_from(">I", data, offset)[0], offset + 4
    if additional == 27:
        return struct.unpack_from(">Q", data, offset)[0], offset + 8
    raise ValueError("indefinite-length CBOR is not supported")


__all__ = [
    "C2PA_VSI_EMSG_VALUE",
    "C2PA_VSI_SCHEME_ID_URI",
    "DEFAULT_STREAM_ID",
    "LIVE_CLAIM_GENERATOR_NAME",
    "BmffParseError",
    "LiveSegmentPublicKey",
    "LiveSegmentSigner",
    "LiveSegmentSigningResult",
    "LiveSegmentSigningStatus",
    "LiveSegmentVerificationResult",
    "LiveSegmentVerificationStatus",
    "bmff_sha256_excluding_c2pa_emsg",
    "build_c2pa_vsi_emsg_box",
    "build_live_manifest_preview",
    "count_c2pa_vsi_emsg_boxes",
    "iter_top_level_boxes",
    "load_signer_from_env",
    "mdat_sha256",
    "parse_emsg_boxes",
    "sign_live_segment",
    "verify_live_segment",
    "write_signed_segment",
]
