import errno
import socket
from datetime import UTC, datetime
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from agents.art_50_provenance.fingerprint import compute_image_fingerprints
from agents.art_50_provenance.models import (
    DEFAULT_V5_IDENTITIES,
    Art50CredentialCertificate,
    C2paBinding,
    C2paSigningState,
    WatermarkRecord,
)
from agents.art_50_provenance.store import write_certificate
from agents.art_50_provenance.verify import (
    verify_certificate_payload,
    verify_image_bytes,
)
from agents.publication_bus.surface_registry import SURFACE_REGISTRY
from logos.api.routes import art_50_credentials as routes

UNVERIFIED = "structure_present_unverified"
CRYPTO_LIMIT = "cryptographic_verification_not_performed"
REQUIRED = (
    ("c2pa.ai-disclosure", "missing_c2pa_ai_disclosure"),
    ("c2pa.actions.v2", "missing_c2pa_actions_v2"),
    ("org.hapax.article50.watermark.v1", "missing_watermark_record"),
    ("org.hapax.article50.fingerprints.v1", "missing_fingerprint_record"),
    ("org.hapax.article50.identity.v1", "missing_v5_identities"),
)


def _require_testclient_ipc():
    # asyncio's cross-thread wakeup silently ignores denied socket writes, which
    # otherwise hangs TestClient. Check the actual transfer, not just allocation.
    operation = "socket.socketpair()"
    try:
        reader, writer = socket.socketpair()
        with reader, writer:
            operation = "socketpair.send()"
            writer.send(b"x")
            operation = "socketpair.recv()"
            assert reader.recv(1) == b"x"
    except OSError as exc:
        if exc.errno not in (errno.EPERM, errno.EACCES):
            raise
        pytest.skip(f"sandbox IPC limit: TestClient requires {operation}: {exc}")


@pytest.fixture
def sample(monkeypatch):
    monkeypatch.setattr("agents.art_50_provenance.fingerprint._native_pdq_hex", lambda image: None)
    image = Image.new("RGB", (64, 64), (23, 67, 111))
    variants = []
    for compression in (0, 9):
        out = BytesIO()
        image.save(out, format="PNG", compress_level=compression)
        variants.append(out.getvalue())
    fingerprint = compute_image_fingerprints(variants[0], mime_type="image/png")
    certificate = Art50CredentialCertificate(
        credential_id="crd_" + "0" * 24,
        issued_at=datetime(2026, 9, 5, tzinfo=UTC),
        customer_id="synthetic-probe",
        asset_id="synthetic-image",
        title="Unsigned test",
        source_fingerprint=fingerprint,
        output_fingerprint=fingerprint,
        watermark=WatermarkRecord(
            credential_id="crd_" + "0" * 24,
            disclosure_text="Synthetic metadata only",
            method="none",
            position="none",
            output_format="PNG",
            byte_length=len(variants[0]),
        ),
        c2pa=C2paBinding(
            status=C2paSigningState.SIGNED_EMBEDDED,
            signed_asset_sha256=None,
            detail="Declared only. No signature, signer or key exists.",
            manifest={
                "assertions": [{"label": label, "data": {}} for label, _ in REQUIRED[:-1]]
                + [
                    {
                        "label": REQUIRED[-1][0],
                        "data": {
                            "identities": [
                                identity.model_dump() for identity in DEFAULT_V5_IDENTITIES
                            ]
                        },
                    }
                ]
            },
        ),
    )
    return certificate, variants


@pytest.mark.parametrize("state", list(C2paSigningState))
def test_declared_signing_state_never_promotes_assurance(sample, state):
    certificate, _ = sample
    certificate.c2pa.status = state
    certificate = Art50CredentialCertificate.model_validate_json(certificate.model_dump_json())
    result = verify_certificate_payload(certificate)
    assert result.status.value == UNVERIFIED
    assert result.c2pa_status is state
    assert CRYPTO_LIMIT in result.reasons
    assert result.exact_sha256_match is None and result.phash_distance is None


def test_emitted_limitations_preserve_bounded_meaning(sample):
    certificate, _ = sample
    # Pin complete statements, including their negations: keyword presence alone
    # would accept inverted claims or an appended, contradictory assurance claim.
    assert certificate.model_dump(mode="json")["limitations"] == [
        "This packet is Article 50 audit-trail evidence, not legal advice.",
        "All C2PA signing states, including signed_embedded, are issuance declarations; "
        "local packet checks do not verify signatures, signer trust or attribution "
        "and never establish valid_signed.",
        "Identity-name presence does not establish authorship or attribution.",
        "A perceptual match is only perceptual-hash proximity, not byte identity "
        "or signed provenance.",
        "The fallback PDQ-DCT hash is not native PDQ and must be replaced or accepted by a "
        "production owner before claiming native PDQ coverage.",
        "No court-admissibility or forensic-authenticity claim is made.",
    ]


@pytest.mark.parametrize(
    "distance,status,comparison_reason",
    [
        pytest.param(4, UNVERIFIED, "perceptual_match_only", id="at-threshold"),
        pytest.param(3, UNVERIFIED, "perceptual_match_only", id="adjacent-inside"),
        pytest.param(5, "invalid", "image_fingerprint_mismatch", id="adjacent-outside"),
        pytest.param(64, "invalid", "image_fingerprint_mismatch", id="distant"),
    ],
)
def test_phash_default_threshold_boundary(sample, monkeypatch, distance, status, comparison_reason):
    certificate, variants = sample
    recorded = certificate.output_fingerprint
    # Control the observed hashes while exercising the real Hamming distance and
    # default threshold (4). SHA inequality forces the perceptual comparison path.
    observed = recorded.model_copy(
        update={
            "sha256": "f" * 64,
            "phash": f"{int(recorded.phash, 16) ^ ((1 << distance) - 1):016x}",
        }
    )
    assert observed.sha256 != recorded.sha256
    monkeypatch.setattr(
        "agents.art_50_provenance.verify.compute_image_fingerprints", lambda *a, **kw: observed
    )
    result = verify_image_bytes(certificate, variants[1])
    assert result.phash_distance == distance
    assert result.exact_sha256_match is False
    assert result.status.value == status
    assert result.reasons == (CRYPTO_LIMIT, "exact_sha256_mismatch", comparison_reason)


def test_same_pixels_different_bytes_are_only_a_perceptual_match(sample):
    certificate, variants = sample
    assert variants[0] != variants[1]
    with Image.open(BytesIO(variants[0])) as first, Image.open(BytesIO(variants[1])) as second:
        assert first.tobytes() == second.tobytes()
    result = verify_image_bytes(certificate, variants[1])
    assert result.status.value == UNVERIFIED
    assert result.exact_sha256_match is False and result.phash_distance == 0
    assert "exact_sha256_mismatch" in result.reasons
    assert "perceptual_match_only" in result.reasons
    assert CRYPTO_LIMIT in result.reasons


def test_exact_byte_match_does_not_verify_provenance(sample):
    certificate, variants = sample
    result = verify_image_bytes(certificate, variants[0])
    assert result.status.value == UNVERIFIED
    assert result.exact_sha256_match is True and result.phash_distance == 0
    assert CRYPTO_LIMIT in result.reasons
    assert "perceptual_match_only" not in result.reasons
    assert "exact_sha256_mismatch" not in result.reasons


@pytest.mark.parametrize("label,reason", REQUIRED)
def test_each_required_record_is_checked(sample, label, reason):
    certificate, _ = sample
    certificate.c2pa.manifest["assertions"] = [
        item for item in certificate.c2pa.manifest["assertions"] if item["label"] != label
    ]
    result = verify_certificate_payload(certificate)
    assert result.status.value == "invalid"
    assert reason in result.reasons
    assert CRYPTO_LIMIT in result.reasons


def test_missing_required_identity_name_is_checked(sample):
    certificate, _ = sample
    certificate.c2pa.manifest["assertions"][-1]["data"]["identities"].pop()
    result = verify_certificate_payload(certificate)
    assert result.status.value == "invalid" and "missing_v5_identities" in result.reasons


def test_empty_assertion_data_and_untrusted_attribution_do_not_gain_assurance(sample):
    certificate, _ = sample
    for item in certificate.c2pa.manifest["assertions"][-1]["data"]["identities"]:
        item["role"] = "unsupported attribution"
        item["assertion_kind"] = "entity"
    certificate.c2pa.signed_asset_sha256 = "f" * 64
    result = verify_certificate_payload(certificate)
    assert result.status.value == UNVERIFIED
    assert CRYPTO_LIMIT in result.reasons


def test_distant_image_still_fails_the_comparison(sample):
    certificate, _ = sample
    out = BytesIO()
    image = Image.new("RGB", (64, 64))
    image.putdata([(x * 17 % 256, x * 31 % 256, x * 47 % 256) for x in range(4096)])
    image.save(out, format="PNG")
    result = verify_image_bytes(certificate, out.getvalue())
    assert result.exact_sha256_match is False and result.phash_distance > 4
    assert result.status.value == "invalid" and "image_fingerprint_mismatch" in result.reasons
    assert "exact_sha256_mismatch" in result.reasons and CRYPTO_LIMIT in result.reasons


@pytest.mark.parametrize("prefix", ["/v1/credential/verify/", "/api/art-50/credential/verify/"])
@pytest.mark.parametrize("state", list(C2paSigningState))
def test_both_http_routes_preserve_the_bounded_result(sample, monkeypatch, prefix, state):
    certificate, _ = sample
    certificate.c2pa.status = state
    monkeypatch.setattr(routes, "load_certificate", lambda credential_id: certificate)
    app = FastAPI()
    app.include_router(routes.router)
    _require_testclient_ipc()
    with TestClient(app) as client:
        response = client.get(prefix + certificate.credential_id)
    assert response.status_code == 200
    result = response.json()
    assert result == verify_certificate_payload(certificate).model_dump(mode="json")
    assert result["status"] == UNVERIFIED and CRYPTO_LIMIT in result["reasons"]
    assert result["exact_sha256_match"] is None and result["phash_distance"] is None


@pytest.mark.parametrize("prefix", ["/v1/credential/verify/", "/api/art-50/credential/verify/"])
def test_missing_packet_remains_404(monkeypatch, prefix):
    monkeypatch.setattr(routes, "load_certificate", lambda credential_id: None)
    app = FastAPI()
    app.include_router(routes.router)
    _require_testclient_ipc()
    with TestClient(app) as client:
        response = client.get(prefix + "crd_" + "0" * 24)
    assert response.status_code == 404


def test_route_aliases_and_missing_id_contract(sample, tmp_path, monkeypatch):
    """Run: env -u HAPAX_GLMCP_MODEL -u HAPAX_GLMCP_REVIEW_MODEL -u HAPAX_GLMCP_REVIEW_PAYG_FALLBACK -u HAPAX_GLMCP_REVIEW_ALLOW_NON_CODING_PLAN_MODEL LITELLM_LOCAL_MODEL_COST_MAP=True UV_CACHE_DIR=/store-fast/tmp/uv-cache-verify uv run pytest -q -p no:cacheprovider -rs tests/agents/art_50_provenance/test_verification_assurance.py::test_route_aliases_and_missing_id_contract

    Mount the app's production router in an isolated FastAPI test app, with only
    synthetic packet storage under tmp_path; no app lifespan or live server.
    Denied socketpair IPC is a sandbox limit, never evidence of route success.
    """
    # Registration remains checkable even where the HTTP exercise must skip.
    assert {(route.path, "GET" in route.methods) for route in routes.router.routes} == {
        ("/v1/credential/verify/{credential_id}", True),
        ("/api/art-50/credential/verify/{credential_id}", True),
    }
    certificate, _ = sample
    monkeypatch.setenv("HAPAX_STATE", str(tmp_path))
    write_certificate(certificate, state_root=tmp_path)
    app = FastAPI()
    app.include_router(routes.router)
    _require_testclient_ipc()
    with TestClient(app) as client:
        responses = [
            client.get(prefix + certificate.credential_id)
            for prefix in ("/v1/credential/verify/", "/api/art-50/credential/verify/")
        ]
        missing = [
            client.get(prefix + "crd_" + "f" * 24)
            for prefix in ("/v1/credential/verify/", "/api/art-50/credential/verify/")
        ]

    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    assert responses[0].json() == verify_certificate_payload(certificate).model_dump(mode="json")
    assert [response.status_code for response in missing] == [404, 404]
    assert [response.json() for response in missing] == [
        {"detail": "credential packet not found"},
        {"detail": "credential packet not found"},
    ]


def test_public_scope_starts_with_the_bounded_predicate():
    note = SURFACE_REGISTRY["art-50-credential-verify"].scope_note
    assert "label/name presence" in note[:100]
    assert "signatures unverified" in note[:100]
