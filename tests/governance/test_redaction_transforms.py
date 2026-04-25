"""AUDIT-22 Phase A — RedactionTransform registry + named transforms.

Pins the registry's API + the three initial transforms (``legal_name``,
``email_address``, ``gps_coordinate``). Phase A ships the registry +
transforms + tests; Phase B (follow-on) wires the registry into
``_apply_redactions`` so contract entries that name transforms apply
to string content uniformly.
"""

from __future__ import annotations

import pytest

from shared.governance.publication_allowlist import (
    REDACTION_TRANSFORMS,
    RedactionTransformNotFound,
    apply_named_transform,
)


class TestRegistryShape:
    def test_three_transforms_registered(self) -> None:
        assert "operator_legal_name" in REDACTION_TRANSFORMS
        assert "email_address" in REDACTION_TRANSFORMS
        assert "gps_coordinate" in REDACTION_TRANSFORMS

    def test_unknown_transform_raises(self) -> None:
        with pytest.raises(RedactionTransformNotFound):
            apply_named_transform("not_a_real_transform", "anything")

    def test_legacy_legal_name_alias_not_registered(self) -> None:
        """AUDIT-22 Phase B-2 rename: ``legal_name`` is gone, replaced
        by ``operator_legal_name`` (matches contract entry naming)."""
        assert "legal_name" not in REDACTION_TRANSFORMS


class TestOperatorLegalNameTransform:
    """``operator_legal_name`` redacts the operator's name as supplied
    via ``HAPAX_OPERATOR_NAME`` env var. Mirrors the AUDIT-05 guard in
    ``shared/governance/omg_referent.py`` but at the publication-
    allowlist layer (defense-in-depth)."""

    def test_match_substituted_with_redacted_marker(self, monkeypatch) -> None:
        monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Real Person")
        out = apply_named_transform("operator_legal_name", "by Real Person, today")
        assert "Real Person" not in out
        assert "[REDACTED]" in out

    def test_case_insensitive_match(self, monkeypatch) -> None:
        monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Real Person")
        out = apply_named_transform("operator_legal_name", "BY REAL PERSON, TODAY")
        assert "REAL PERSON" not in out
        assert "[REDACTED]" in out

    def test_no_env_var_passthrough(self, monkeypatch) -> None:
        monkeypatch.delenv("HAPAX_OPERATOR_NAME", raising=False)
        out = apply_named_transform("operator_legal_name", "by Real Person")
        assert out == "by Real Person"

    def test_empty_env_var_passthrough(self, monkeypatch) -> None:
        monkeypatch.setenv("HAPAX_OPERATOR_NAME", "")
        out = apply_named_transform("operator_legal_name", "by Real Person")
        assert out == "by Real Person"


class TestEmailAddressTransform:
    """``email_address`` redacts any RFC-5322-shaped email in the
    content. Catches accidental leaks via copy-paste (eg. operator
    accidentally pasting a contact email into a livestream caption)."""

    def test_simple_email_redacted(self) -> None:
        out = apply_named_transform("email_address", "contact me at user@example.com today")
        assert "user@example.com" not in out
        assert "[REDACTED]" in out

    def test_multiple_emails_all_redacted(self) -> None:
        out = apply_named_transform("email_address", "from a@x.org to b+tag@y.co.uk via c.d@e.io")
        assert "a@x.org" not in out
        assert "b+tag@y.co.uk" not in out
        assert "c.d@e.io" not in out

    def test_no_email_passthrough(self) -> None:
        out = apply_named_transform("email_address", "no email surface here")
        assert out == "no email surface here"

    def test_word_with_at_but_no_dot_not_matched(self) -> None:
        """``foo@bar`` (no dot) is not a real email; leave alone."""
        out = apply_named_transform("email_address", "see @username on the platform")
        assert out == "see @username on the platform"


class TestGpsCoordinateTransform:
    """``gps_coordinate`` redacts decimal-degree pairs (``lat, lon``) and
    explicit lat/lon-prefixed forms. Catches accidental geo leaks
    from GPS-tagged photo captions or live-location descriptions."""

    def test_decimal_pair_redacted(self) -> None:
        out = apply_named_transform("gps_coordinate", "near 37.7749, -122.4194 today")
        assert "37.7749" not in out
        assert "-122.4194" not in out
        assert "[REDACTED]" in out

    def test_no_coordinates_passthrough(self) -> None:
        out = apply_named_transform("gps_coordinate", "nothing geographic here")
        assert out == "nothing geographic here"

    def test_plain_numbers_not_matched(self) -> None:
        """Pure numbers without the ``,`` decimal-degree shape stay."""
        # "version 1.0" is not a coordinate
        out = apply_named_transform("gps_coordinate", "version 1.0 release")
        assert out == "version 1.0 release"


class TestStringContentInvariant:
    """All transforms operate on string content and return string."""

    @pytest.mark.parametrize("name", ["operator_legal_name", "email_address", "gps_coordinate"])
    def test_returns_string(self, name: str) -> None:
        out = apply_named_transform(name, "some content")
        assert isinstance(out, str)

    @pytest.mark.parametrize("name", ["operator_legal_name", "email_address", "gps_coordinate"])
    def test_empty_input_returns_empty(self, name: str) -> None:
        out = apply_named_transform(name, "")
        assert out == ""
