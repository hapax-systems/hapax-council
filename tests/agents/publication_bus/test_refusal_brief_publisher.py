"""Tests for ``agents.publication_bus.refusal_brief_publisher``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.publication_bus.publisher_kit import PublisherPayload
from agents.publication_bus.publisher_kit.allowlist import load_allowlist
from agents.publication_bus.refusal_brief_publisher import (
    REFUSAL_DEPOSIT_SURFACE,
    REFUSAL_DEPOSIT_TYPE,
    RefusalBriefPublisher,
    RefusedTaskSummary,
    compose_refusal_related_identifiers,
    scan_refused_cc_tasks,
)
from agents.publication_bus.related_identifier import (
    IdentifierType,
    RelationType,
)


def _mock_response(status_code: int, json_data: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    response.text = ""
    return response


class TestSurfaceMetadata:
    def test_surface_name_is_zenodo_refusal_deposit(self) -> None:
        assert RefusalBriefPublisher.surface_name == REFUSAL_DEPOSIT_SURFACE
        assert REFUSAL_DEPOSIT_SURFACE == "zenodo-refusal-deposit"

    def test_requires_legal_name(self) -> None:
        # Zenodo deposit creators array uses formal name
        assert RefusalBriefPublisher.requires_legal_name is True


class TestComposeRelatedIdentifiers:
    def test_includes_target_surface_as_is_required_by(self) -> None:
        edges = compose_refusal_related_identifiers(
            target_surface_doi="10.5281/zenodo.PLACEHOLDER-bandcamp",
            sibling_refusal_dois=[],
        )
        assert any(
            e.relation_type == RelationType.IS_REQUIRED_BY
            and e.identifier == "10.5281/zenodo.PLACEHOLDER-bandcamp"
            for e in edges
        )

    def test_includes_siblings_as_is_obsoleted_by(self) -> None:
        edges = compose_refusal_related_identifiers(
            target_surface_doi="10.5281/zenodo.PLACEHOLDER-target",
            sibling_refusal_dois=[
                "10.5281/zenodo.SIBLING-1",
                "10.5281/zenodo.SIBLING-2",
            ],
        )
        sibling_edges = [e for e in edges if e.relation_type == RelationType.IS_OBSOLETED_BY]
        assert len(sibling_edges) == 2
        assert {e.identifier for e in sibling_edges} == {
            "10.5281/zenodo.SIBLING-1",
            "10.5281/zenodo.SIBLING-2",
        }

    def test_all_edges_use_doi_identifier_type(self) -> None:
        edges = compose_refusal_related_identifiers(
            target_surface_doi="10.5281/zenodo.X",
            sibling_refusal_dois=["10.5281/zenodo.Y"],
        )
        assert all(e.identifier_type == IdentifierType.DOI for e in edges)


class TestScanRefusedCcTasks:
    def test_scans_refused_tasks(self, tmp_path: Path) -> None:
        active = tmp_path / "active"
        active.mkdir()
        (active / "task-A.md").write_text(
            "---\n"
            "type: cc-task\n"
            "task_id: task-A\n"
            "title: 'Refused A'\n"
            "automation_status: REFUSED\n"
            "refusal_reason: 'Bandcamp has no upload API'\n"
            "---\n\nbody A\n"
        )
        (active / "task-B.md").write_text(
            "---\n"
            "type: cc-task\n"
            "task_id: task-B\n"
            "title: 'Live B'\n"
            "automation_status: FULL_AUTO\n"
            "---\n\nbody B\n"
        )
        (active / "task-C.md").write_text(
            "---\n"
            "type: cc-task\n"
            "task_id: task-C\n"
            "title: 'Refused C'\n"
            "automation_status: REFUSED\n"
            "refusal_reason: 'TOS prohibits'\n"
            "---\n\nbody C\n"
        )
        results = list(scan_refused_cc_tasks(active))
        assert len(results) == 2
        slugs = {r.task_id for r in results}
        assert slugs == {"task-A", "task-C"}

    def test_returns_empty_on_missing_dir(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist"
        results = list(scan_refused_cc_tasks(missing))
        assert results == []

    def test_skips_files_without_refusal_status(self, tmp_path: Path) -> None:
        active = tmp_path / "active"
        active.mkdir()
        (active / "task-A.md").write_text("---\ntype: cc-task\nautomation_status: FULL_AUTO\n---\n")
        results = list(scan_refused_cc_tasks(active))
        assert results == []

    def test_extracts_refusal_reason(self, tmp_path: Path) -> None:
        active = tmp_path / "active"
        active.mkdir()
        (active / "task-A.md").write_text(
            "---\n"
            "type: cc-task\n"
            "task_id: task-A\n"
            "title: 'Refused A'\n"
            "automation_status: REFUSED\n"
            "refusal_reason: 'Specific reason here'\n"
            "---\n"
        )
        result = next(iter(scan_refused_cc_tasks(active)))
        assert result.refusal_reason == "Specific reason here"


class TestPublisher:
    def test_missing_zenodo_token_returns_refused(self) -> None:
        RefusalBriefPublisher.allowlist = load_allowlist(REFUSAL_DEPOSIT_SURFACE, ["task-A"])
        publisher = RefusalBriefPublisher(zenodo_token="")
        result = publisher.publish(
            PublisherPayload(
                target="task-A",
                text="Refusal text",
                metadata={"title": "Refused: Foo"},
            )
        )
        assert result.refused is True
        assert "credential" in result.detail.lower() or "token" in result.detail.lower()

    @patch("agents.publication_bus.refusal_brief_publisher.requests")
    def test_zenodo_201_returns_ok(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(
            201, json_data={"id": 123, "doi": "10.5281/zenodo.123"}
        )
        RefusalBriefPublisher.allowlist = load_allowlist(REFUSAL_DEPOSIT_SURFACE, ["task-A"])
        publisher = RefusalBriefPublisher(zenodo_token="t")
        result = publisher.publish(
            PublisherPayload(
                target="task-A",
                text="Refusal body",
                metadata={"title": "Refused: bandcamp", "creator": "Operator Legal Name"},
            )
        )
        assert result.ok is True

    @patch("agents.publication_bus.refusal_brief_publisher.requests")
    def test_zenodo_4xx_returns_error(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(400, {"error": "bad"})
        RefusalBriefPublisher.allowlist = load_allowlist(REFUSAL_DEPOSIT_SURFACE, ["task-A"])
        publisher = RefusalBriefPublisher(zenodo_token="t")
        result = publisher.publish(PublisherPayload(target="task-A", text="body"))
        assert result.error is True

    def test_allowlist_deny_short_circuits(self) -> None:
        RefusalBriefPublisher.allowlist = load_allowlist(REFUSAL_DEPOSIT_SURFACE, [])
        publisher = RefusalBriefPublisher(zenodo_token="t")
        result = publisher.publish(PublisherPayload(target="task-A", text="body"))
        assert result.refused is True

    @patch("agents.publication_bus.refusal_brief_publisher.requests")
    def test_request_exception_returns_error(self, mock_requests: MagicMock) -> None:
        import requests as _requests_lib

        mock_requests.post.side_effect = _requests_lib.RequestException("offline")
        mock_requests.RequestException = _requests_lib.RequestException
        RefusalBriefPublisher.allowlist = load_allowlist(REFUSAL_DEPOSIT_SURFACE, ["task-A"])
        publisher = RefusalBriefPublisher(zenodo_token="t")
        result = publisher.publish(PublisherPayload(target="task-A", text="body"))
        assert result.error is True

    @patch("agents.publication_bus.refusal_brief_publisher.requests")
    def test_payload_has_resource_type_refusal(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(201, {"id": 1})
        RefusalBriefPublisher.allowlist = load_allowlist(REFUSAL_DEPOSIT_SURFACE, ["task-A"])
        publisher = RefusalBriefPublisher(zenodo_token="t")
        publisher.publish(
            PublisherPayload(
                target="task-A",
                text="body",
                metadata={"title": "T"},
            )
        )
        kwargs = mock_requests.post.call_args.kwargs
        body = kwargs.get("json", {})
        # Refusal Briefs carry the deposit-type tag in metadata.keywords
        # for DataCite discoverability.
        assert REFUSAL_DEPOSIT_TYPE in str(body)


class TestSurfaceRegistryEntry:
    def test_zenodo_refusal_deposit_in_surface_registry(self) -> None:
        from agents.publication_bus.surface_registry import (
            SURFACE_REGISTRY,
            AutomationStatus,
        )

        assert REFUSAL_DEPOSIT_SURFACE in SURFACE_REGISTRY
        spec = SURFACE_REGISTRY[REFUSAL_DEPOSIT_SURFACE]
        assert spec.automation_status == AutomationStatus.FULL_AUTO


class TestRefusedTaskSummary:
    def test_dataclass_has_required_fields(self) -> None:
        summary = RefusedTaskSummary(
            task_id="bandcamp-upload",
            title="Bandcamp upload",
            refusal_reason="No upload API",
            file_path=Path("/tmp/foo.md"),
        )
        assert summary.task_id == "bandcamp-upload"
        assert summary.title == "Bandcamp upload"
        assert summary.refusal_reason == "No upload API"
