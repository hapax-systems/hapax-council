"""Tests for ``agents.payment_processors.x402.models``.

Pin the wire-format invariants documented in
``docs/research/2026-05-01-x402-spec-current-research.md`` so any drift
in the upstream spec is detected before it reaches a publisher.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agents.payment_processors.x402.models import (
    Accept,
    Authorization,
    PayloadInner,
    PaymentPayload,
    PaymentRequired,
    ResourceRef,
    SettlementResponse,
    decode_payment_required,
    encode_payment_required,
    validate_caip_network,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _resource() -> ResourceRef:
    return ResourceRef(
        url="https://hapax.example/api/protected",
        description="Premium endpoint",
        mimeType="application/json",
    )


def _accept(network: str = "eip155:8453") -> Accept:
    return Accept(
        scheme="exact",
        network=network,
        amount="1000000",
        asset="0x036CbD53842c5426634e7929541eC2318f3dCF7e",
        payTo="0xRecipientAddress0000000000000000000000000",
        maxTimeoutSeconds=60,
        extra={"name": "USDC", "version": "2"},
    )


# ── ResourceRef ──────────────────────────────────────────────────────


class TestResourceRef:
    def test_minimal_construct(self) -> None:
        r = ResourceRef(url="https://x")
        assert r.url == "https://x"
        assert r.description == ""
        assert r.mimeType == "application/octet-stream"

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ResourceRef.model_validate({"url": "https://x", "extra_field": "no"})


# ── Accept ───────────────────────────────────────────────────────────


class TestAccept:
    def test_canonical_round_trip(self) -> None:
        a = _accept()
        json_str = a.model_dump_json()
        b = Accept.model_validate_json(json_str)
        assert a == b

    def test_scheme_must_be_exact(self) -> None:
        with pytest.raises(ValidationError, match="scheme"):
            Accept.model_validate({**_accept().model_dump(), "scheme": "upto"})

    def test_network_must_be_caip_eip155(self) -> None:
        with pytest.raises(ValidationError, match="CAIP"):
            Accept.model_validate({**_accept().model_dump(), "network": "solana:101"})

    def test_amount_must_be_integer_string(self) -> None:
        with pytest.raises(ValidationError, match="non-negative integer"):
            Accept.model_validate({**_accept().model_dump(), "amount": "1.5"})

    def test_amount_rejects_negative(self) -> None:
        with pytest.raises(ValidationError, match="non-negative integer"):
            Accept.model_validate({**_accept().model_dump(), "amount": "-1"})

    def test_max_timeout_seconds_positive(self) -> None:
        with pytest.raises(ValidationError):
            Accept.model_validate({**_accept().model_dump(), "maxTimeoutSeconds": 0})

    def test_extra_carries_arbitrary_dict(self) -> None:
        a = Accept.model_validate(
            {**_accept().model_dump(), "extra": {"hapax_license_class": "commercial"}}
        )
        assert a.extra["hapax_license_class"] == "commercial"


# ── PaymentRequired ──────────────────────────────────────────────────


class TestPaymentRequired:
    def test_round_trip(self) -> None:
        req = PaymentRequired(resource=_resource(), accepts=[_accept()])
        round = PaymentRequired.model_validate_json(req.model_dump_json())
        assert round == req

    def test_x402_version_pinned_to_2(self) -> None:
        with pytest.raises(ValidationError):
            PaymentRequired.model_validate(
                {"x402Version": 1, "resource": _resource().model_dump(), "accepts": []}
            )

    def test_empty_accepts_array_is_valid(self) -> None:
        """Decision A: refusal-as-data — empty accepts array is the
        canonical "I acknowledge x402 but have no compliant rails"
        signal. Must validate cleanly so the publisher can construct
        it."""
        req = PaymentRequired(resource=_resource(), accepts=[])
        assert req.accepts == []

    def test_default_error_message(self) -> None:
        req = PaymentRequired(resource=_resource())
        assert req.error == "payment required"


# ── Authorization + PayloadInner + PaymentPayload ────────────────────


class TestAuthorization:
    def test_from_alias_routes_to_from_address(self) -> None:
        a = Authorization.model_validate(
            {
                "from": "0xPayer",
                "to": "0xRecipient",
                "value": "1000000",
                "validAfter": "1714560000",
                "validBefore": "1714560060",
                "nonce": "0xdeadbeef",
            }
        )
        assert a.from_address == "0xPayer"

    def test_serialization_uses_from_alias(self) -> None:
        a = Authorization.model_validate(
            {
                "from": "0xPayer",
                "to": "0xRecipient",
                "value": "1000000",
                "validAfter": "1714560000",
                "validBefore": "1714560060",
                "nonce": "0xdeadbeef",
            }
        )
        # When dumping with by_alias=True, the JSON key is `from`,
        # matching the wire format.
        dumped = a.model_dump(by_alias=True)
        assert "from" in dumped
        assert dumped["from"] == "0xPayer"


class TestPaymentPayload:
    def _payload(self) -> PaymentPayload:
        return PaymentPayload(
            resource=_resource(),
            accepted=_accept(),
            payload=PayloadInner(
                signature="0xsig",
                authorization=Authorization.model_validate(
                    {
                        "from": "0xPayer",
                        "to": "0xRecipient",
                        "value": "1000000",
                        "validAfter": "1714560000",
                        "validBefore": "1714560060",
                        "nonce": "0xdeadbeef",
                    }
                ),
            ),
        )

    def test_round_trip(self) -> None:
        p = self._payload()
        # Use by_alias=True so `from_address` serializes as `from`,
        # then validate against the alias-aware model.
        s = p.model_dump_json(by_alias=True)
        round = PaymentPayload.model_validate_json(s)
        assert round == p

    def test_x402_version_pinned(self) -> None:
        with pytest.raises(ValidationError):
            PaymentPayload.model_validate(
                {**self._payload().model_dump(by_alias=True), "x402Version": 99}
            )


# ── SettlementResponse ───────────────────────────────────────────────


class TestSettlementResponse:
    def test_success_shape(self) -> None:
        s = SettlementResponse(
            success=True,
            transaction="0xtxhash",
            network="eip155:8453",
            payer="0xPayer",
        )
        assert s.success is True
        assert s.transaction == "0xtxhash"
        assert s.errorReason is None

    def test_failure_shape(self) -> None:
        s = SettlementResponse(
            success=False,
            errorReason="insufficient_funds",
            transaction="",
            network="eip155:8453",
            payer="0xPayer",
        )
        assert s.success is False
        assert s.errorReason == "insufficient_funds"

    def test_round_trip(self) -> None:
        s = SettlementResponse(
            success=True,
            transaction="0xtxhash",
            network="eip155:8453",
            payer="0xPayer",
        )
        assert SettlementResponse.model_validate_json(s.model_dump_json()) == s

    def test_network_validated_caip(self) -> None:
        with pytest.raises(ValidationError, match="CAIP"):
            SettlementResponse(
                success=True,
                transaction="0xtxhash",
                network="bitcoin:1",
                payer="0xPayer",
            )


# ── Base64 helpers ───────────────────────────────────────────────────


class TestBase64Helpers:
    def test_round_trip(self) -> None:
        req = PaymentRequired(resource=_resource(), accepts=[_accept()])
        encoded = encode_payment_required(req)
        decoded = decode_payment_required(encoded)
        assert decoded == req

    def test_decode_rejects_invalid_base64(self) -> None:
        with pytest.raises(Exception):  # binascii.Error or similar
            decode_payment_required("!!!not-base64!!!")

    def test_decode_validates_schema(self) -> None:
        import base64

        bogus = base64.b64encode(b'{"x402Version": 1, "resource": {"url": "x"}}').decode("ascii")
        with pytest.raises(ValidationError):
            decode_payment_required(bogus)

    def test_encoded_string_is_ascii(self) -> None:
        req = PaymentRequired(resource=_resource(), accepts=[_accept()])
        encoded = encode_payment_required(req)
        encoded.encode("ascii")  # must not raise


# ── validate_caip_network ────────────────────────────────────────────


class TestValidateCaipNetwork:
    @pytest.mark.parametrize(
        "valid",
        ["eip155:1", "eip155:8453", "eip155:84532", "eip155:137"],
    )
    def test_valid_eip155(self, valid: str) -> None:
        assert validate_caip_network(valid) == valid

    @pytest.mark.parametrize(
        "invalid",
        [
            "solana:101",
            "stellar:public",
            "eip155",
            "eip155:",
            "eip155:abc",
            "8453",
            "",
        ],
    )
    def test_rejects_non_eip155(self, invalid: str) -> None:
        with pytest.raises(ValueError, match="CAIP"):
            validate_caip_network(invalid)
