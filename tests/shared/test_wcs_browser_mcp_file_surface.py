"""Tests for browser/MCP/file WCS read-surface fixture evaluation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.capability_classification_inventory import (
    PublicClaimPolicy,
    SurfaceFamily,
    load_capability_classification_inventory,
)
from shared.wcs_browser_mcp_file_surface import (
    SourceSurfaceRecord,
    WCSBrowserMCPFileSurfaceError,
    evaluate_surface,
    load_wcs_browser_mcp_file_surface_fixtures,
)


def _fixtures():
    return load_wcs_browser_mcp_file_surface_fixtures()


def test_fixture_loads_all_required_surface_and_witness_classes() -> None:
    fixtures = _fixtures()
    evaluations = fixtures.evaluate_all()

    assert len(fixtures.surfaces) >= 7
    assert "browser.playwright.current_page" in evaluations
    assert "public_source.tavily.result" in evaluations
    assert "file.local_repo.missing" in evaluations
    assert fixtures.fail_closed_policy == {
        "path_or_url_name_grants_public_claim": False,
        "missing_source_read_allows_claim": False,
        "stale_source_allows_claim": False,
        "private_vault_surface_public_by_default": False,
        "tool_success_is_truth": False,
    }


def test_surface_records_consume_capability_classification_rows() -> None:
    fixtures = _fixtures()
    inventory = load_capability_classification_inventory()

    for surface in fixtures.surfaces:
        row = inventory.require_row(surface.classification_row_id)
        assert row.surface_family is not None

    assert inventory.require_row("capability.browser.playwright_state").surface_family is (
        SurfaceFamily.BROWSER_SURFACE
    )
    assert inventory.require_row("capability.file.local_repo_read").surface_family is (
        SurfaceFamily.FILE
    )
    assert inventory.require_row("capability.obsidian.vault_note_read").surface_family is (
        SurfaceFamily.OBSIDIAN_NOTE
    )
    assert inventory.require_row("capability.command.output_reference").surface_family is (
        SurfaceFamily.COMMAND_OUTPUT
    )


def test_public_source_and_browser_claims_require_gate_citation_and_fresh_read() -> None:
    fixtures = _fixtures()
    evaluations = fixtures.evaluate_all()

    browser = evaluations["browser.playwright.current_page"]
    tavily = evaluations["public_source.tavily.result"]

    assert browser.can_support_private_evidence is True
    assert browser.can_support_public_claim is True
    assert browser.blocked_reasons == []
    assert tavily.can_support_public_claim is True

    browser_surface = fixtures.require_surface("browser.playwright.current_page")
    without_gate_or_citation = browser_surface.model_copy(
        update={"grounding_gate_ref": None, "citation_refs": []}
    )
    blocked = evaluate_surface(without_gate_or_citation, fixtures.witness_probes_by_id())

    assert blocked.can_support_public_claim is False
    assert "public_claim_requires_grounding_gate" in blocked.blocked_reasons
    assert "public_claim_requires_citation_refs" in blocked.blocked_reasons


def test_mcp_docs_and_command_output_do_not_expand_to_public_authority() -> None:
    fixtures = _fixtures()
    evaluations = fixtures.evaluate_all()
    context7 = evaluations["mcp.context7.docs"]
    command = evaluations["command.git_diff_check.stale"]

    assert context7.can_support_private_evidence is True
    assert context7.can_support_public_claim is False
    assert context7.classification_public_claim_policy == PublicClaimPolicy.EVIDENCE_BOUND_ONLY
    assert "classification_not_public_claim_authority" in context7.blocked_reasons

    assert command.can_support_private_evidence is False
    assert command.can_support_public_claim is False
    assert {"command_output_stale", "source_not_fresh", "source_stale"} <= set(
        command.blocked_reasons
    )


def test_private_tool_and_vault_reads_stay_private_only() -> None:
    evaluations = _fixtures().evaluate_all()
    tool = evaluations["tool.query_scene_state.private"]
    vault = evaluations["obsidian.active_task.private_note"]

    assert tool.can_support_private_evidence is True
    assert tool.can_support_public_claim is False
    assert {"public_scope_private", "classification_not_public_claim_authority"} <= set(
        tool.blocked_reasons
    )

    assert vault.can_support_private_evidence is True
    assert vault.can_support_public_claim is False
    assert {"vault_private_only", "public_scope_private", "source_private_only"} <= set(
        vault.blocked_reasons
    )


def test_missing_unavailable_and_permission_blocked_surfaces_emit_blockers() -> None:
    evaluations = _fixtures().evaluate_all()

    missing = evaluations["file.local_repo.missing"]
    unavailable = evaluations["mcp.context7.unavailable"]
    permission_blocked = evaluations["file.private.permission_blocked"]

    assert missing.can_support_private_evidence is False
    assert {"file_path_not_found", "source_read_missing", "source_not_found"} <= set(
        missing.blocked_reasons
    )
    assert unavailable.can_support_public_claim is False
    assert {"tool_unavailable", "source_read_missing"} <= set(unavailable.blocked_reasons)
    assert permission_blocked.can_support_private_evidence is False
    assert "source_permission_blocked" in permission_blocked.blocked_reasons


def test_classification_family_mismatch_fails_closed() -> None:
    fixtures = _fixtures()
    surface = fixtures.require_surface("file.local_repo.missing").model_copy(
        update={
            "classification_row_id": "capability.mcp.context7_docs",
            "blocked_reasons": ["file_path_not_found"],
        }
    )

    evaluation = evaluate_surface(surface, fixtures.witness_probes_by_id())

    assert evaluation.can_support_private_evidence is False
    assert evaluation.can_support_public_claim is False
    assert "classification_family_mismatch" in evaluation.blocked_reasons


def test_fixture_loader_rejects_unknown_probe_reference(tmp_path: Path) -> None:
    fixtures = _fixtures()
    payload = fixtures.model_dump(mode="json", by_alias=True)
    payload["surfaces"][0]["witness_probe_ids"] = ["probe.missing.unknown"]
    path = tmp_path / "bad-wcs-browser-mcp-file.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(WCSBrowserMCPFileSurfaceError):
        load_wcs_browser_mcp_file_surface_fixtures(path)


def test_public_claim_request_for_private_scope_requires_block_reason() -> None:
    surface = _fixtures().require_surface("obsidian.active_task.private_note")
    payload = surface.model_dump(mode="json")
    payload["blocked_reasons"] = []

    with pytest.raises(ValueError, match="unsafe public-claim requests require blocked_reasons"):
        SourceSurfaceRecord.model_validate(payload)
