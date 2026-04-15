"""Tests for shared.research_registry_schema.

Validates the pydantic model matches the on-disk YAML structure written
by scripts/research-registry.py's cmd_init + cmd_open. Tests round-trip
YAML serialization, condition_id pattern validation, nested model
validation, and the PR #792 bundle 2 §4 schema additions (parent /
sibling / collection timestamps).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from shared.research_registry_schema import (
    DirectiveEntry,
    PreRegistrationInfo,
    ResearchCondition,
    SubstrateInfo,
)


def _minimal_substrate() -> SubstrateInfo:
    return SubstrateInfo(
        model="Qwen3.5-9B-exl3-5.00bpw",
        backend="tabbyapi",
        route="local-fast|coding|reasoning",
    )


def _minimal_condition(
    condition_id: str = "cond-phase-a-baseline-qwen-001",
    claim_id: str = "claim-shaikh-sft-vs-dpo",
) -> ResearchCondition:
    return ResearchCondition(
        condition_id=condition_id,
        claim_id=claim_id,
        opened_at=datetime(2026, 4, 14, 7, 58, tzinfo=UTC),
        substrate=_minimal_substrate(),
        frozen_files=[
            "agents/hapax_daimonion/grounding_ledger.py",
            "agents/hapax_daimonion/conversation_pipeline.py",
        ],
    )


class TestCondition:
    def test_minimal_valid(self):
        cond = _minimal_condition()
        assert cond.condition_id == "cond-phase-a-baseline-qwen-001"
        assert cond.closed_at is None
        assert cond.notes == ""
        assert cond.pre_registration.filed is False

    def test_condition_id_pattern_accepts_valid(self):
        for cid in (
            "cond-test-001",
            "cond-phase-a-baseline-qwen-001",
            "cond-long-slug-with-dashes-042",
            "cond-a-000",
        ):
            ResearchCondition(
                condition_id=cid,
                claim_id="claim-test",
                opened_at=datetime.now(UTC),
                substrate=_minimal_substrate(),
            )

    def test_condition_id_pattern_rejects_invalid(self):
        for cid in (
            "cond-test",  # no suffix
            "test-001",  # no cond prefix
            "cond-test-abc",  # non-digit suffix
            "cond-test-1",  # 1-digit suffix (not 3)
            "cond--001",  # empty slug
            "cond-UPPER-001",  # uppercase slug
            "cond-test-0001",  # 4-digit suffix
        ):
            with pytest.raises(ValidationError):
                ResearchCondition(
                    condition_id=cid,
                    claim_id="claim-test",
                    opened_at=datetime.now(UTC),
                    substrate=_minimal_substrate(),
                )

    def test_substrate_extra_forbid(self):
        with pytest.raises(ValidationError):
            SubstrateInfo(
                model="x",
                backend="y",
                route="z",
                bogus="extra",  # type: ignore[call-arg]
            )

    def test_directive_sha256_format(self):
        DirectiveEntry(path="a/b.py", sha256="0" * 64)
        with pytest.raises(ValidationError):
            DirectiveEntry(path="a/b.py", sha256="too-short")
        with pytest.raises(ValidationError):
            DirectiveEntry(path="a/b.py", sha256="G" * 64)  # non-hex

    def test_pre_registration_default(self):
        cond = _minimal_condition()
        assert cond.pre_registration.filed is False
        assert cond.pre_registration.url is None
        assert cond.pre_registration.filed_at is None

    def test_pr_792_schema_additions_defaults(self):
        """parent_condition_id + sibling_condition_ids + collection_*."""
        cond = _minimal_condition()
        assert cond.parent_condition_id is None
        assert cond.sibling_condition_ids == []
        assert cond.collection_started_at is None
        assert cond.collection_halt_at is None

    def test_parent_condition_id_format(self):
        ResearchCondition(
            condition_id="cond-test-002",
            claim_id="claim-test",
            opened_at=datetime.now(UTC),
            substrate=_minimal_substrate(),
            parent_condition_id="cond-test-001",
        )
        with pytest.raises(ValidationError):
            ResearchCondition(
                condition_id="cond-test-002",
                claim_id="claim-test",
                opened_at=datetime.now(UTC),
                substrate=_minimal_substrate(),
                parent_condition_id="bogus",
            )

    def test_sibling_condition_ids_format(self):
        ResearchCondition(
            condition_id="cond-test-003",
            claim_id="claim-test",
            opened_at=datetime.now(UTC),
            substrate=_minimal_substrate(),
            sibling_condition_ids=["cond-test-001", "cond-test-002"],
        )
        with pytest.raises(ValidationError):
            ResearchCondition(
                condition_id="cond-test-003",
                claim_id="claim-test",
                opened_at=datetime.now(UTC),
                substrate=_minimal_substrate(),
                sibling_condition_ids=["cond-test-001", "bogus"],
            )


class TestYamlRoundTrip:
    def test_round_trip_minimal(self):
        original = _minimal_condition()
        yaml_text = original.to_yaml()
        parsed = ResearchCondition.from_yaml(yaml_text)
        assert parsed.condition_id == original.condition_id
        assert parsed.substrate.model == original.substrate.model
        assert parsed.frozen_files == original.frozen_files

    def test_round_trip_with_all_optional_fields(self):
        original = ResearchCondition(
            condition_id="cond-test-001",
            claim_id="claim-test",
            opened_at=datetime(2026, 4, 14, 12, 0, tzinfo=UTC),
            closed_at=datetime(2026, 4, 15, 12, 0, tzinfo=UTC),
            substrate=_minimal_substrate(),
            frozen_files=["a.py", "b.py"],
            directives_manifest=[DirectiveEntry(path="c.py", sha256="a" * 64)],
            parent_condition_id="cond-prior-001",
            sibling_condition_ids=["cond-sibling-001"],
            collection_started_at=datetime(2026, 4, 14, 13, 0, tzinfo=UTC),
            osf_project_id="abcde",
            pre_registration=PreRegistrationInfo(
                filed=True,
                url="https://osf.io/abcde",
                filed_at=datetime(2026, 4, 14, 14, 0, tzinfo=UTC),
            ),
            notes="test note",
        )
        yaml_text = original.to_yaml()
        parsed = ResearchCondition.from_yaml(yaml_text)
        assert parsed.parent_condition_id == "cond-prior-001"
        assert parsed.sibling_condition_ids == ["cond-sibling-001"]
        assert parsed.pre_registration.filed is True
        assert parsed.notes == "test note"

    def test_from_yaml_rejects_non_mapping(self):
        with pytest.raises(ValueError, match="mapping"):
            ResearchCondition.from_yaml("[1, 2, 3]")

    def test_from_yaml_rejects_unknown_key(self):
        yaml_text = _minimal_condition().to_yaml() + "\nbogus_field: 123\n"
        with pytest.raises(ValidationError):
            ResearchCondition.from_yaml(yaml_text)


class TestLiveConditionFileParse:
    """Regression pin: the on-disk condition.yaml at
    ``~/hapax-state/research-registry/cond-phase-a-baseline-qwen-001/``
    parses cleanly under this schema.

    Skipped if the file is absent (CI environment without a live
    registry). When present, confirms the schema matches reality.
    """

    def test_live_condition_parses(self, tmp_path):
        from pathlib import Path

        live = (
            Path.home()
            / "hapax-state"
            / "research-registry"
            / "cond-phase-a-baseline-qwen-001"
            / "condition.yaml"
        )
        if not live.is_file():
            pytest.skip("live condition.yaml not present in this environment")
        cond = ResearchCondition.from_yaml(live.read_text())
        assert cond.condition_id == "cond-phase-a-baseline-qwen-001"
        assert cond.substrate.model == "Qwen3.5-9B-exl3-5.00bpw"
        assert cond.substrate.backend == "tabbyapi"
        assert len(cond.frozen_files) >= 4
