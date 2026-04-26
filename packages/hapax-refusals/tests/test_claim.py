"""ClaimSpec model tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hapax_refusals.claim import ClaimSpec


class TestClaimSpec:
    def test_constructs_with_required_fields(self) -> None:
        c = ClaimSpec(
            name="vinyl_is_playing",
            posterior=0.42,
            proposition="Vinyl is currently playing.",
        )
        assert c.name == "vinyl_is_playing"
        assert c.posterior == 0.42

    def test_posterior_below_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClaimSpec(name="x", posterior=-0.1, proposition="p")

    def test_posterior_above_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClaimSpec(name="x", posterior=1.1, proposition="p")

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClaimSpec(name="", posterior=0.5, proposition="p")

    def test_empty_proposition_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClaimSpec(name="x", posterior=0.5, proposition="")

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClaimSpec(  # type: ignore[call-arg]
                name="x",
                posterior=0.5,
                proposition="p",
                extra="boom",
            )

    def test_frozen(self) -> None:
        c = ClaimSpec(name="x", posterior=0.5, proposition="p")
        with pytest.raises(ValidationError):
            c.posterior = 0.9  # type: ignore[misc]
