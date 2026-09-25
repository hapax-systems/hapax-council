"""The lightweight extraction retains the existing immutable wire contract."""

import pytest
from pydantic import ValidationError

from shared.content_address import ContentAddress
from shared.execution_admission import ContentAddress as AdmissionAddress
from shared.execution_admission import _FrozenModel


def test_existing_admission_import_keeps_type_and_serialized_reference():
    assert AdmissionAddress is ContentAddress
    assert ContentAddress.model_config == _FrozenModel.model_config
    wire = {"ref": "owned/résultat.json", "sha256": "a" * 64}
    address = AdmissionAddress.model_validate(wire)
    assert address.model_dump(mode="json") == wire
    assert ContentAddress.model_validate_json(address.model_dump_json()) == address


@pytest.mark.parametrize("ref", ["", " ", "\tref", "ref ", "ref\n", chr(0xD800)])
def test_invalid_reference_is_rejected(ref):
    with pytest.raises(ValidationError):
        ContentAddress(ref=ref, sha256="a" * 64)


@pytest.mark.parametrize("digest", ["", "a" * 63, "a" * 65, "A" * 64, "g" * 64])
def test_digest_requires_exact_lowercase_sha256(digest):
    with pytest.raises(ValidationError):
        ContentAddress(ref="result.json", sha256=digest)


def test_reference_cannot_add_fields_or_change_after_validation():
    with pytest.raises(ValidationError):
        ContentAddress(ref="result.json", sha256="a" * 64, may_authorize=True)
    address = ContentAddress(ref="result.json", sha256="a" * 64)
    with pytest.raises(ValidationError):
        address.ref = "replacement.json"


@pytest.mark.parametrize(
    "ref",
    [
        "plain",
        "résultat",
        "inside\nnewline",
        "inside\0nul",
        "inside\ttab",
        "",
        " ",
        "\tref",
        "ref\n",
        chr(0xD800),
    ],
)
def test_extraction_agrees_with_existing_wire_string_rule(ref):
    from shared.execution_admission import _nonblank

    try:
        expected = _nonblank(ref)
    except ValueError:
        with pytest.raises(ValidationError):
            ContentAddress(ref=ref, sha256="a" * 64)
    else:
        assert ContentAddress(ref=ref, sha256="a" * 64).ref == expected
