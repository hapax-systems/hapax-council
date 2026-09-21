"""``capability_shape`` — the condition vector a capability number must carry.

Claim and dispatch metadata keyed on role + session identity, so the estate could
not answer "which capability shape held this claim" without transcript
archaeology. Lanes are ephemeral containers and roles are string identifiers
(operator ruling accepted 2026-09-12); the shape is what a measurement is
actually about, and item 8 of the 2026-09-12T20:22Z acceptance receipt requires
every capability number to carry its condition vector.

The field is additive and optional by construction — ``route_metadata_schema``
stays at 1 and no existing row becomes invalid — which these pins assert in both
directions.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from shared.route_metadata_schema import CapabilityShape, RouteEnvelope  # noqa: E402


class TestOptionality:
    def test_envelope_without_a_shape_is_valid(self) -> None:
        """Every row minted before this field must still validate."""
        assert RouteEnvelope().capability_shape is None

    def test_absent_field_is_not_recorded_rather_than_a_default_shape(self) -> None:
        """A fabricated default would be a measurement claim nobody made."""
        env = RouteEnvelope()
        assert env.capability_shape is None
        dumped = env.model_dump()
        assert dumped["capability_shape"] is None

    def test_partial_shape_is_valid(self) -> None:
        """A row that knows its model but not its scaffold must still record that."""
        shape = CapabilityShape(model_family="claude-opus-5")
        assert shape.model_family == "claude-opus-5"
        assert shape.scaffold_revision is None

    def test_schema_version_is_unchanged(self) -> None:
        """Additive means additive: consumers pinned to 1 keep working."""
        assert RouteEnvelope().route_envelope_schema == 1


class TestAcceptance:
    def test_full_shape_round_trips(self) -> None:
        env = RouteEnvelope(
            capability_shape=CapabilityShape(
                model_family="claude-opus-5",
                harness="claude",
                route="claude.review.opus",
                scaffold_revision="4962bdda5",
            )
        )
        again = RouteEnvelope.model_validate(env.model_dump())
        assert again.capability_shape == env.capability_shape

    def test_shape_accepts_a_plain_mapping(self) -> None:
        """Frontmatter arrives as nested dicts, not constructed models."""
        env = RouteEnvelope.model_validate(
            {"capability_shape": {"model_family": "gpt-5.3-codex", "harness": "codex"}}
        )
        assert env.capability_shape is not None
        assert env.capability_shape.harness == "codex"

    def test_unknown_shape_key_is_refused(self) -> None:
        """extra=forbid: a typo'd key must fail loudly, not vanish into the row."""
        with pytest.raises(ValidationError):
            CapabilityShape(model_familly="claude-opus-5")  # type: ignore[call-arg]

    def test_shape_is_frozen(self) -> None:
        """A condition vector that can be edited after the fact describes nothing."""
        shape = CapabilityShape(model_family="claude-opus-5")
        with pytest.raises(ValidationError):
            shape.model_family = "claude-sonnet-5"  # type: ignore[misc]


class TestScope:
    def test_credential_location_is_not_a_field(self) -> None:
        """The fourth term of capability identity is deliberately absent.

        This envelope lands in vault notes that sync. A field whose legitimate
        values are pointers into a secret store is one careless writer away from
        carrying the secret itself, so the omission is a decision — and this pin
        is what makes someone argue for it rather than quietly add it.
        """
        assert "credential_location" not in CapabilityShape.model_fields
