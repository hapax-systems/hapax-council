"""The capability_shape WRITER — the half a schema field cannot deliver on its own.

Review round 1 on PR #4668 landed ``CapabilityShape`` on ``RouteEnvelope`` and
nothing that populates it. glm-1 called the predicate half-delivered, correctly:
the row's item 3 asks that the estate be able to answer *which capability shape
held this claim*, and a field no writer fills leaves that answer exactly where it
was — in the transcripts.

``capability_shape_from_env`` is the producer, and cc-claim stamps its rendering
into the claim's session-log line. These pin the producer's contract; the schema
side is pinned in test_route_metadata_capability_shape.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from shared.route_metadata_schema import CapabilityShape  # noqa: E402
from shared.session_identity import (  # noqa: E402
    capability_shape_from_env,
    format_capability_shape,
)


class TestProducer:
    def test_reads_the_dispatched_model_and_harness(self) -> None:
        shape = capability_shape_from_env(
            {
                "HAPAX_CLAUDE_MODEL": "claude-opus-5",
                "HAPAX_AGENT_INTERFACE": "claude",
                "HAPAX_CAPABILITY_ROUTE": "claude.review.opus",
            },
            scaffold_revision="284c8b44c",
        )
        assert shape == {
            "model_family": "claude-opus-5",
            "harness": "claude",
            "route": "claude.review.opus",
            "scaffold_revision": "284c8b44c",
        }

    def test_unknown_fields_are_none_not_guessed(self) -> None:
        """An unanswerable field is 'not recorded', never an invented default."""
        shape = capability_shape_from_env({})
        assert shape == {
            "model_family": None,
            "harness": None,
            "route": None,
            "scaffold_revision": None,
        }

    def test_explicit_capability_model_outranks_the_launcher_pin(self) -> None:
        shape = capability_shape_from_env(
            {"HAPAX_CAPABILITY_MODEL": "gpt-5.3-codex", "HAPAX_CLAUDE_MODEL": "opus"}
        )
        assert shape["model_family"] == "gpt-5.3-codex"

    def test_blank_values_do_not_count_as_recorded(self) -> None:
        shape = capability_shape_from_env({"HAPAX_AGENT_INTERFACE": "   "})
        assert shape["harness"] is None

    def test_producer_output_validates_against_the_schema(self) -> None:
        """Producer and schema must not drift into two shapes of the same name."""
        shape = capability_shape_from_env(
            {"HAPAX_CLAUDE_MODEL": "claude-opus-5", "HAPAX_AGENT_INTERFACE": "claude"}
        )
        model = CapabilityShape.model_validate(shape)
        assert model.model_family == "claude-opus-5"
        assert model.harness == "claude"

    def test_producer_emits_exactly_the_schema_field_set(self) -> None:
        """extra=forbid means a producer key the schema lacks is a hard failure."""
        assert set(capability_shape_from_env({})) == set(CapabilityShape.model_fields)


class TestRendering:
    def test_renders_only_recorded_fields(self) -> None:
        rendered = format_capability_shape(
            {
                "model_family": "claude-opus-5",
                "harness": None,
                "route": "r",
                "scaffold_revision": None,
            }
        )
        assert rendered == "model_family=claude-opus-5, route=r"

    def test_nothing_known_renders_empty(self) -> None:
        """So a caller can append unconditionally without recording an absence.

        `shape=()` in a session log would read as "the shape was measured and was
        empty", which is a different claim from "nothing recorded it".
        """
        assert format_capability_shape(capability_shape_from_env({})) == ""
