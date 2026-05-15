"""Tests for the governance perimeter budget and inventory script."""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.hapax_governance_perimeter import (
    classify_hooks,
    count_refusals,
    scan_ci_workflows,
    scan_implications,
)


def test_implication_parsing_array_format(tmp_path: Path) -> None:
    impl_file = tmp_path / "test-axiom.yaml"
    impl_file.write_text(
        yaml.dump(
            {
                "axiom_id": "test_axiom",
                "implications": [
                    {"id": "t1", "tier": "T0", "enforcement": "block"},
                    {"id": "t2", "tier": "T1", "enforcement": "review"},
                    {"id": "t3", "tier": "T2", "enforcement": "warn", "status": "retired"},
                ],
            }
        )
    )
    results = scan_implications(tmp_path)
    assert len(results) == 1
    s = results[0]
    assert s.axiom_id == "test_axiom"
    assert s.total == 3
    assert s.active == 2
    assert s.retired == 1
    assert s.t0 == 1
    assert s.t1 == 1
    assert s.t2 == 1


def test_implication_parsing_flat_format(tmp_path: Path) -> None:
    impl_file = tmp_path / "single-impl.yaml"
    impl_file.write_text(
        yaml.dump(
            {
                "implication_id": "su-flat-001",
                "axiom_id": "single_user",
                "tier": "T2",
                "enforcement": "review",
            }
        )
    )
    results = scan_implications(tmp_path)
    assert len(results) == 1
    assert results[0].total == 1
    assert results[0].active == 1
    assert results[0].t2 == 1


def test_hook_classification(tmp_path: Path) -> None:
    blocking = tmp_path / "pii-guard.sh"
    blocking.write_text("#!/bin/bash\nBLOCKED: PII detected\nexit 2\n")

    advisory = tmp_path / "axiom-audit.sh"
    advisory.write_text("#!/bin/bash\n# axiom audit log\necho audit\nexit 0\n")

    operational = tmp_path / "session-context.sh"
    operational.write_text("#!/bin/bash\necho context\n")

    b, a, o = classify_hooks(tmp_path)
    assert "pii-guard.sh" in b
    assert "axiom-audit.sh" in a
    assert "session-context.sh" in o


def test_refusal_brief_count(tmp_path: Path) -> None:
    (tmp_path / "refusal-a.md").write_text("# Refusal A")
    (tmp_path / "refusal-b.md").write_text("# Refusal B")
    (tmp_path / "_registry.yaml").write_text(
        yaml.dump({"refusals": {"surface-a": {"brief": "a.md"}, "surface-b": {"brief": "b.md"}}})
    )
    (tmp_path / "not-a-brief.txt").write_text("ignore")

    briefs, registry = count_refusals(tmp_path)
    assert briefs == 2
    assert registry == 2


def test_ci_workflow_detection(tmp_path: Path) -> None:
    (tmp_path / "sdlc-axiom-gate.yml").write_text("name: axiom gate")
    (tmp_path / "ci.yml").write_text("name: CI")
    (tmp_path / "vale-lint.yml").write_text("name: vale lint")
    (tmp_path / "deploy.yml").write_text("name: deploy")

    results = scan_ci_workflows(tmp_path)
    assert "sdlc-axiom-gate.yml" in results
    assert "vale-lint.yml" in results
    assert "deploy.yml" not in results


def test_check_mode_passes_with_data() -> None:
    from scripts.hapax_governance_perimeter import ImplicationStats, PerimeterReport, check_mode

    report = PerimeterReport()
    report.implications = [ImplicationStats(axiom_id="test", total=5, active=5)]
    report.hooks_blocking = ["test-gate.sh"]
    report.refusal_briefs = 1
    assert check_mode(report) == 0
