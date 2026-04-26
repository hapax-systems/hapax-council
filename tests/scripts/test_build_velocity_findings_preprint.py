"""Pure-composition tests for ``scripts/build-velocity-findings-preprint.py``."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "build-velocity-findings-preprint.py"


@pytest.fixture(scope="module")
def script_module():
    """Load the script as a module so its helpers are testable."""
    spec = importlib.util.spec_from_file_location("build_velocity_findings_preprint", SCRIPT_PATH)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_velocity_findings_preprint"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TestBuildArtifact:
    def test_artifact_has_required_fields(self, script_module) -> None:
        artifact = script_module.build_artifact()
        assert artifact.slug == "velocity-findings-2026-04-25"
        assert "velocity" in artifact.title.lower()
        assert len(artifact.abstract) > 100  # Real abstract, not placeholder
        assert len(artifact.body_md) > 1000  # Real body from research drop

    def test_targets_zenodo_doi_surface(self, script_module) -> None:
        artifact = script_module.build_artifact()
        assert "zenodo-doi" in artifact.surfaces_targeted

    def test_approval_state_is_approved(self, script_module) -> None:
        # The artifact is shipped already-approved; the orchestrator
        # only dispatches APPROVED artifacts.
        from shared.preprint_artifact import ApprovalState

        artifact = script_module.build_artifact()
        assert artifact.approval == ApprovalState.APPROVED

    def test_body_md_includes_headline_metrics(self, script_module) -> None:
        # Pin the source-doc-to-body wiring: the §1 headline metrics
        # must round-trip through to the artifact body so reviewers can
        # see the substrate in the deposit description.
        artifact = script_module.build_artifact()
        for needle in ("PRs/day", "commits/day", "LOC churn", "research drops"):
            assert needle in artifact.body_md, f"missing headline metric: {needle}"

    def test_missing_source_raises(self, script_module, tmp_path) -> None:
        # Calling with a non-existent source path is a hard error
        # (better to fail fast than ship an empty deposit).
        bogus = tmp_path / "missing.md"
        with pytest.raises(FileNotFoundError):
            script_module.build_artifact(source_path=bogus)


class TestAbstractContent:
    def test_abstract_includes_quantitative_claims(self, script_module) -> None:
        # The abstract is the first thing a reviewer + a citing
        # downstream tool sees; it must carry the headline numbers.
        for needle in ("30 PRs", "47%", "21.8%"):
            assert needle in script_module.ABSTRACT, f"abstract missing: {needle}"

    def test_abstract_under_max_length(self, script_module) -> None:
        # PreprintArtifact.abstract has max_length=4096 in the schema;
        # our composed abstract must fit comfortably.
        assert len(script_module.ABSTRACT) < 4000
