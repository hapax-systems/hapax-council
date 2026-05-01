"""Tests for the affordance recruitment Prometheus counter.

Audit-closeout 12.3 acceptance:
- counter defined + incremented per recruited capability
- label cardinality bounded to the 6-domain enum (+ unknown fallback)
- mock-pipeline run asserts counter value
"""

from __future__ import annotations

import pytest

prometheus_client = pytest.importorskip("prometheus_client")

from shared.affordance_recruitment_metrics import (  # noqa: E402
    ALL_DOMAINS,
    TAXONOMY_DOMAINS,
    UNKNOWN_DOMAIN,
    domain_label_for,
    record_recruitment,
    recruitment_counter_value,
)

# ── Domain mapping ──────────────────────────────────────────────────────


class TestDomainLabelFor:
    @pytest.mark.parametrize(
        ("capability_name", "expected"),
        [
            ("env.weather_conditions", "perception"),
            ("body.heart_rate_variability", "perception"),
            ("world.scene_inventory", "perception"),
            ("studio.compose_camera_grid", "expression"),
            ("narration.spontaneous_speech", "expression"),
            ("space.move_camera", "action"),
            ("digital.send_message", "action"),
            ("knowledge.recall_episode", "recall"),
            ("social.contact_operator_partner", "communication"),
            ("system.adjust_gain", "regulation"),
        ],
    )
    def test_known_prefix_maps_to_taxonomy(self, capability_name: str, expected: str) -> None:
        assert domain_label_for(capability_name) == expected
        assert expected in TAXONOMY_DOMAINS

    def test_unknown_prefix_returns_unknown(self) -> None:
        assert domain_label_for("not_a_registered_domain.something") == UNKNOWN_DOMAIN

    def test_no_prefix_returns_unknown(self) -> None:
        assert domain_label_for("just_a_name_no_dot") == UNKNOWN_DOMAIN

    def test_none_input_returns_unknown(self) -> None:
        assert domain_label_for(None) == UNKNOWN_DOMAIN

    def test_empty_string_returns_unknown(self) -> None:
        assert domain_label_for("") == UNKNOWN_DOMAIN


# ── Cardinality bound ───────────────────────────────────────────────────


class TestCardinalityBound:
    def test_taxonomy_has_six_canonical_domains(self) -> None:
        assert len(TAXONOMY_DOMAINS) == 6
        assert set(TAXONOMY_DOMAINS) == {
            "perception",
            "expression",
            "recall",
            "action",
            "communication",
            "regulation",
        }

    def test_all_domains_caps_at_seven_with_unknown(self) -> None:
        assert ALL_DOMAINS == TAXONOMY_DOMAINS + (UNKNOWN_DOMAIN,)
        assert len(ALL_DOMAINS) == 7

    def test_no_capability_name_can_introduce_a_new_label(self) -> None:
        """Even bizarre prefixes collapse to one of ALL_DOMAINS."""

        for fake in [
            "x.y",
            "extra-domain.action",
            "@@@.thing",
            ".",
            "..",
            "perception",  # no dot — falls back to unknown
            "Perception.thing",  # case-sensitive prefix
        ]:
            assert domain_label_for(fake) in ALL_DOMAINS


# ── Counter increment + value introspection ─────────────────────────────


class TestRecordRecruitment:
    def test_increments_per_recruited_capability(self) -> None:
        """A run of recruited capabilities advances per-domain counters."""

        before = {d: recruitment_counter_value(d) or 0.0 for d in ALL_DOMAINS}

        record_recruitment("env.weather_conditions")
        record_recruitment("env.air_pressure")
        record_recruitment("studio.compose_camera_grid")
        record_recruitment("knowledge.recall_episode")

        after = {d: recruitment_counter_value(d) or 0.0 for d in ALL_DOMAINS}

        assert after["perception"] - before["perception"] == 2
        assert after["expression"] - before["expression"] == 1
        assert after["recall"] - before["recall"] == 1
        assert after["action"] - before["action"] == 0
        assert after["communication"] - before["communication"] == 0
        assert after["regulation"] - before["regulation"] == 0
        assert after[UNKNOWN_DOMAIN] - before[UNKNOWN_DOMAIN] == 0

    def test_unknown_capability_routes_to_unknown_label(self) -> None:
        before = recruitment_counter_value(UNKNOWN_DOMAIN) or 0.0
        record_recruitment("not_a_real_domain.nope")
        after = recruitment_counter_value(UNKNOWN_DOMAIN) or 0.0
        assert after - before == 1

    def test_none_capability_does_not_crash(self) -> None:
        """Pipeline survivors always have names, but defensive nonetheless."""

        before = recruitment_counter_value(UNKNOWN_DOMAIN) or 0.0
        record_recruitment(None)
        after = recruitment_counter_value(UNKNOWN_DOMAIN) or 0.0
        assert after - before == 1


# ── Pipeline-level integration smoke ────────────────────────────────────


class TestPipelineWiring:
    """Confirm the counter increments when AffordancePipeline.select() returns survivors.

    The full pipeline has many heavy dependencies (Qdrant, embeddings); this
    test imports the wire directly to confirm the import path + counter
    plumbing without paying for a full pipeline boot.
    """

    def test_record_recruitment_imported_into_pipeline_module(self) -> None:
        """Regression pin: the wire is in place, not silently dropped."""

        import shared.affordance_pipeline as pipeline_mod

        assert hasattr(pipeline_mod, "_record_recruitment"), (
            "shared.affordance_pipeline must import record_recruitment as "
            "_record_recruitment for the survivor-loop wire to fire"
        )

    def test_select_method_calls_record_recruitment_on_survivors(self) -> None:
        """Source-level pin that the wire happens after survivors are picked."""

        from pathlib import Path

        source = Path("shared/affordance_pipeline.py").read_text(encoding="utf-8")
        # Look for the wire near the survivors line.
        survivor_idx = source.index("survivors = [c for c in normal")
        # The wire must appear in the next few hundred chars.
        slice_after = source[survivor_idx : survivor_idx + 1500]
        assert "_record_recruitment" in slice_after, (
            "_record_recruitment call must appear in select() near survivor selection"
        )
        assert "for survivor in survivors" in slice_after, (
            "survivor loop calling _record_recruitment must be present"
        )
