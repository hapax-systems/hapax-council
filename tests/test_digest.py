"""Tests for digest.py — schemas, formatters, collectors, notification.

LLM calls and external I/O are mocked.
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from agents.digest import (
    SYSTEM_PROMPT,
    Digest,
    DigestStats,
    NotableItem,
    collect_collection_stats,
    collect_recent_documents,
    format_digest_human,
    format_digest_md,
    send_notification,
)
from shared.fix_capabilities.background_admission import BackgroundCapabilityAdmission

# ── Schema tests ─────────────────────────────────────────────────────────────


def test_digest_stats_defaults():
    s = DigestStats()
    assert s.new_documents == 0
    assert s.collection_sizes == {}


def test_notable_item_schema():
    n = NotableItem(title="Research paper", source="paper.pdf", relevance="New ML technique")
    assert n.title == "Research paper"
    assert n.source == "paper.pdf"


def test_digest_json_round_trip():
    d = Digest(
        generated_at="2026-03-01T06:45:00Z",
        hours=24,
        headline="3 new documents ingested",
        summary="Light content activity overnight.",
        notable_items=[NotableItem(title="Paper", source="paper.pdf", relevance="Relevant")],
        suggested_actions=["Review new papers"],
    )
    data = json.loads(d.model_dump_json())
    assert data["headline"] == "3 new documents ingested"
    assert len(data["notable_items"]) == 1
    assert data["stats"]["new_documents"] == 0


def test_digest_with_stats():
    d = Digest(
        generated_at="2026-03-01T06:45:00Z",
        hours=24,
        headline="Active day",
        summary="Lots of new content.",
        stats=DigestStats(
            new_documents=15,
            collection_sizes={"documents": 1200, "profile-facts": 50},
        ),
    )
    assert d.stats.new_documents == 15
    assert d.stats.collection_sizes["documents"] == 1200


def test_digest_defaults():
    d = Digest(
        generated_at="2026-03-01T06:45:00Z",
        hours=24,
        headline="Nothing new",
        summary="Quiet period.",
    )
    assert d.notable_items == []
    assert d.suggested_actions == []
    assert d.stats.new_documents == 0


# ── Formatter tests ──────────────────────────────────────────────────────────


def _sample_digest() -> Digest:
    return Digest(
        generated_at="2026-03-01T06:45:00Z",
        hours=24,
        headline="5 new documents, 2 vault items processed",
        summary="Active content day. New research papers and vault notes ingested.",
        notable_items=[
            NotableItem(
                title="ML Survey 2026", source="ml-survey.pdf", relevance="Covers latest techniques"
            ),
            NotableItem(
                title="Meeting notes",
                source="meeting-2026-03-01.md",
                relevance="Contains action items",
            ),
        ],
        suggested_actions=[
            "Review ML survey for relevant sections",
            "Tag meeting notes with project references",
        ],
        stats=DigestStats(
            new_documents=5,
            collection_sizes={"documents": 1500, "profile-facts": 80},
        ),
    )


def test_format_digest_human_contains_headline():
    output = format_digest_human(_sample_digest())
    assert "5 new documents" in output


def test_format_digest_human_contains_stats():
    output = format_digest_human(_sample_digest())
    assert "5 new docs" in output
    assert "documents: 1500" in output


def test_format_digest_human_contains_notable():
    output = format_digest_human(_sample_digest())
    assert "ML Survey 2026" in output
    assert "Meeting notes" in output


def test_format_digest_human_contains_actions():
    output = format_digest_human(_sample_digest())
    assert "Review ML survey" in output
    assert "Tag meeting notes" in output


def test_format_digest_human_no_notable_when_empty():
    d = Digest(
        generated_at="2026-03-01T06:45:00Z",
        hours=24,
        headline="Quiet",
        summary="Nothing new.",
    )
    output = format_digest_human(d)
    assert "Notable" not in output


def test_format_digest_human_no_actions_when_empty():
    d = Digest(
        generated_at="2026-03-01T06:45:00Z",
        hours=24,
        headline="Quiet",
        summary="Nothing new.",
    )
    output = format_digest_human(d)
    assert "Actions" not in output


def test_format_digest_md_has_headers():
    output = format_digest_md(_sample_digest())
    assert "# Content Digest" in output
    assert "## Stats" in output
    assert "## Notable Items" in output
    assert "## Suggested Actions" in output


def test_format_digest_md_has_stats():
    output = format_digest_md(_sample_digest())
    assert "New documents: 5" in output
    assert "documents: 1500 points" in output


def test_format_digest_md_notable_items():
    output = format_digest_md(_sample_digest())
    assert "**ML Survey 2026**" in output
    assert "ml-survey.pdf" in output
    assert "Covers latest techniques" in output


def test_format_digest_md_no_notable_when_empty():
    d = Digest(
        generated_at="2026-03-01T06:45:00Z",
        hours=24,
        headline="Clean",
        summary="Nothing.",
    )
    output = format_digest_md(d)
    assert "Notable Items" not in output


def test_format_digest_md_unavailable_collection():
    d = Digest(
        generated_at="2026-03-01T06:45:00Z",
        hours=24,
        headline="Test",
        summary="Test.",
        stats=DigestStats(collection_sizes={"documents": -1}),
    )
    output = format_digest_md(d)
    assert "unavailable" in output


# ── Collector tests ──────────────────────────────────────────────────────────


@patch("agents.digest.get_qdrant")
def test_collect_recent_documents_returns_grouped(mock_qdrant):
    """Recent docs should be grouped by source file."""
    mock_client = MagicMock()
    mock_qdrant.return_value = mock_client

    now = time.time()
    mock_point_1 = MagicMock()
    mock_point_1.payload = {
        "source": "/data/paper.pdf",
        "filename": "paper.pdf",
        "ingested_at": now - 100,
        "text": "Chunk 1 text preview content here",
    }
    mock_point_2 = MagicMock()
    mock_point_2.payload = {
        "source": "/data/paper.pdf",
        "filename": "paper.pdf",
        "ingested_at": now - 100,
        "text": "Chunk 2 text preview content here",
    }
    mock_point_3 = MagicMock()
    mock_point_3.payload = {
        "source": "/data/notes.md",
        "filename": "notes.md",
        "ingested_at": now - 200,
        "text": "Notes text here",
    }
    mock_client.scroll.return_value = ([mock_point_1, mock_point_2, mock_point_3], None)

    docs = collect_recent_documents(hours=24)
    assert len(docs) == 2  # grouped by source
    paper = next(d for d in docs if d["filename"] == "paper.pdf")
    assert paper["chunk_count"] == 2


@patch("agents.digest.get_qdrant")
def test_collect_recent_documents_empty(mock_qdrant):
    """No recent documents returns empty list."""
    mock_client = MagicMock()
    mock_qdrant.return_value = mock_client
    mock_client.scroll.return_value = ([], None)

    docs = collect_recent_documents(hours=24)
    assert docs == []


@patch("agents.digest.get_qdrant")
def test_collect_recent_documents_handles_error(mock_qdrant):
    """Qdrant connection failure returns empty list."""
    mock_qdrant.side_effect = Exception("Connection refused")
    docs = collect_recent_documents(hours=24)
    assert docs == []


@patch("agents.digest.get_qdrant")
def test_collect_collection_stats_success(mock_qdrant):
    """Collection stats returns point counts."""
    mock_client = MagicMock()
    mock_qdrant.return_value = mock_client

    mock_count = MagicMock()
    mock_count.count = 100
    mock_client.count.return_value = mock_count

    stats = collect_collection_stats()
    assert stats["documents"] == 100
    assert stats["profile-facts"] == 100


@patch("agents.digest.get_qdrant")
def test_collect_collection_stats_partial_failure(mock_qdrant):
    """One failing collection doesn't prevent others."""
    mock_client = MagicMock()
    mock_qdrant.return_value = mock_client

    def count_side_effect(collection_name):
        if collection_name == "profile-facts":
            raise Exception("Not found")
        result = MagicMock()
        result.count = 50
        return result

    mock_client.count.side_effect = count_side_effect

    stats = collect_collection_stats()
    assert stats["documents"] == 50
    assert stats["profile-facts"] == -1


# ── Notification tests ───────────────────────────────────────────────────────


@patch("agents._notify.send_notification")
def test_send_notification_calls_shared_notify(mock_notify):
    d = _sample_digest()
    send_notification(d)
    mock_notify.assert_called_once()
    kwargs = mock_notify.call_args
    assert kwargs[0][0] == "Content Digest"


@patch("agents._notify.send_notification")
def test_send_notification_includes_doc_count(mock_notify):
    d = _sample_digest()
    send_notification(d)
    message = mock_notify.call_args[0][1]
    assert "5 new document" in message


@patch("agents._notify.send_notification")
def test_send_notification_no_vault_items_when_zero(mock_notify):
    d = Digest(
        generated_at="2026-03-01T06:45:00Z",
        hours=24,
        headline="Test",
        summary="Test.",
        stats=DigestStats(new_documents=3),
    )
    send_notification(d)
    message = mock_notify.call_args[0][1]
    assert "vault" not in message.lower()


# ── System prompt tests ──────────────────────────────────────────────────────


def test_system_prompt_mentions_precision():
    assert "precision" in SYSTEM_PROMPT.lower()


def test_system_prompt_mentions_content():
    assert "content" in SYSTEM_PROMPT.lower() or "knowledge" in SYSTEM_PROMPT.lower()


# ── Pipeline tests (generate_digest with mocked deps) ──────────────────────

from unittest.mock import AsyncMock


class _FakeDigestResult:
    output = Digest(
        generated_at="2026-03-01T06:45:00Z",
        hours=24,
        headline="3 new documents",
        summary="Light content activity.",
    )


def _admitted_digest_admission() -> BackgroundCapabilityAdmission:
    return BackgroundCapabilityAdmission(
        capability_name="agents.digest.synthesis",
        route_id="api.headless.provider_gateway",
        model_alias="gemini-flash",
        admitted=True,
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
    )


def test_digest_admission_spec_classifies_local_and_provider_models():
    """Digest model selection must drive the admission surface before policy reads."""
    from agents.digest import _digest_admission_spec

    assert _digest_admission_spec("local-fast") == (
        "local_tool.local.worker",
        "none",
        "deterministic_ok",
    )
    assert _digest_admission_spec("gemini-flash") == (
        "api.headless.provider_gateway",
        "provider_spend",
        "frontier_required",
    )


def test_digest_admission_refuses_configured_route_model_mismatch(monkeypatch):
    """A configured route cannot override the route implied by the selected model.

    The selected model is resolved through the agent-free selector seam (no
    pre-instantiated agent to patch — admission must be computable with no
    agent in existence).
    """
    from agents.digest import DIGEST_LLM_ROUTE_ID_ENV, _admit_digest_synthesis

    monkeypatch.setenv(DIGEST_LLM_ROUTE_ID_ENV, "local_tool.local.worker")
    with patch("agents.digest._selected_digest_model_id", return_value="gemini-flash"):
        admission = _admit_digest_synthesis()

    assert admission.admitted is False
    assert admission.reason_codes == ("digest_route_model_mismatch",)
    assert "expected_route=api.headless.provider_gateway" in (admission.denied_reason or "")


def test_selected_digest_model_id_resolves_without_agent():
    """Model selection goes through the adaptive resolver + MODELS, agent-free."""
    from agents.digest import _selected_digest_model_id

    with (
        patch("shared.config.resolve_model_alias_adaptive", return_value="fast") as mock_resolve,
        patch("agents.digest.MODELS", {"fast": "gemini-flash"}),
        patch("agents.digest.Agent") as mock_agent_cls,
    ):
        assert _selected_digest_model_id() == "gemini-flash"

    mock_resolve.assert_called_once()
    mock_agent_cls.assert_not_called()


def test_digest_denied_admission_construction_raises():
    """_get_digest_agent refuses to bind a model for a denied admission."""
    from agents.digest import _get_digest_agent

    denied = BackgroundCapabilityAdmission(
        capability_name="agents.digest.synthesis",
        route_id="api.headless.provider_gateway",
        model_alias="gemini-flash",
        admitted=False,
        denied_reason="task_note_absent",
        reason_codes=("task_note_absent",),
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
    )
    with (
        patch("agents.digest.get_model") as mock_get_model,
        patch("agents.digest.Agent") as mock_agent_cls,
        pytest.raises(RuntimeError, match="requires admitted capability"),
    ):
        _get_digest_agent(denied)

    mock_get_model.assert_not_called()
    mock_agent_cls.assert_not_called()


def test_digest_admission_model_mismatch_fails_closed():
    """If adaptive selection shifted after admission, construction refuses to
    bind a model other than the admitted one (admit-A/bind-B TOCTOU)."""
    from agents.digest import _get_digest_agent

    with (
        patch("agents.digest._selected_digest_model_id", return_value="some-other-model"),
        patch("agents.digest.get_model") as mock_get_model,
        pytest.raises(RuntimeError, match="digest_model_admission_mismatch"),
    ):
        _get_digest_agent(_admitted_digest_admission())

    mock_get_model.assert_not_called()


def test_digest_module_import_binds_no_model():
    """Import purity: importing agents.digest constructs no Agent/model.

    Regression for the review-blocking finding — the module previously bound a
    model descriptor (and registered tools) at import, before any admission.
    """
    import importlib

    import agents.digest as digest_module

    with (
        patch("pydantic_ai.Agent") as mock_agent_cls,
        patch("shared.config.get_model") as mock_get_model,
        patch("shared.config.get_model_adaptive") as mock_adaptive,
    ):
        reloaded = importlib.reload(digest_module)
        assert reloaded._digest_agent is None
        mock_agent_cls.assert_not_called()
        mock_get_model.assert_not_called()
        mock_adaptive.assert_not_called()
    importlib.reload(digest_module)


@pytest.mark.asyncio
@patch("agents.digest.collect_recent_documents")
@patch("agents.digest.collect_collection_stats")
@patch("agents.digest._get_digest_agent")
async def test_generate_digest_pipeline(
    mock_get_agent,
    mock_stats,
    mock_docs,
):
    mock_agent = mock_get_agent.return_value  # the factory's constructed agent
    """End-to-end pipeline test with all I/O mocked."""
    from agents.digest import generate_digest

    mock_docs.return_value = [
        {
            "filename": "paper.pdf",
            "chunk_count": 3,
            "source": "/data/paper.pdf",
            "ingested_at": 0,
            "text_preview": "...",
        },
    ]
    mock_stats.return_value = {"documents": 1500, "profile-facts": 80}
    mock_agent.run = AsyncMock(return_value=_FakeDigestResult())

    with patch("agents.digest._admit_digest_synthesis", return_value=_admitted_digest_admission()):
        digest = await generate_digest(hours=24)
    assert digest.hours == 24
    assert digest.stats.new_documents == 1
    assert digest.stats.collection_sizes["documents"] == 1500
    assert digest.generated_at.endswith("Z")


@pytest.mark.asyncio
@patch("agents.digest.collect_recent_documents")
@patch("agents.digest.collect_collection_stats")
@patch("agents.digest._get_digest_agent")
async def test_generate_digest_empty_results(
    mock_get_agent,
    mock_stats,
    mock_docs,
):
    mock_agent = mock_get_agent.return_value  # the factory's constructed agent
    """Pipeline handles no new content gracefully."""
    from agents.digest import generate_digest

    mock_docs.return_value = []
    mock_stats.return_value = {"documents": 100}
    mock_agent.run = AsyncMock(return_value=_FakeDigestResult())

    with patch("agents.digest._admit_digest_synthesis", return_value=_admitted_digest_admission()):
        digest = await generate_digest(hours=24)
    assert digest.stats.new_documents == 0

    # Prompt should mention "No new documents"
    prompt = mock_agent.run.call_args[0][0]
    assert "No new documents" in prompt


@pytest.mark.asyncio
@patch("agents.digest.collect_recent_documents")
@patch("agents.digest.collect_collection_stats")
@patch("agents.digest._get_digest_agent")
async def test_generate_digest_llm_failure_graceful(
    mock_get_agent,
    mock_stats,
    mock_docs,
):
    mock_agent = mock_get_agent.return_value  # the factory's constructed agent
    """Pipeline handles LLM failure gracefully."""
    from agents.digest import generate_digest

    mock_docs.return_value = []
    mock_stats.return_value = {}
    mock_agent.run = AsyncMock(side_effect=Exception("LLM timeout"))

    with patch("agents.digest._admit_digest_synthesis", return_value=_admitted_digest_admission()):
        digest = await generate_digest(hours=24)
    assert "unavailable" in digest.headline.lower() or "error" in digest.headline.lower()
    assert digest.stats.new_documents == 0


@pytest.mark.asyncio
@patch("agents.digest.collect_recent_documents")
@patch("agents.digest.collect_collection_stats")
@patch("agents.digest._get_digest_agent")
async def test_generate_digest_admission_denial_skips_llm(
    mock_get_agent,
    mock_stats,
    mock_docs,
):
    mock_agent = mock_get_agent.return_value  # the factory's constructed agent
    """Capability denial should degrade without invoking the digest agent."""
    from agents.digest import generate_digest

    mock_docs.return_value = []
    mock_stats.return_value = {}
    mock_agent.run = AsyncMock()
    denied = BackgroundCapabilityAdmission(
        capability_name="agents.digest.synthesis",
        route_id="api.headless.provider_gateway",
        model_alias="gemini-flash",
        admitted=False,
        denied_reason="task_note_absent",
        reason_codes=("task_note_absent",),
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
    )

    with patch("agents.digest._admit_digest_synthesis", return_value=denied):
        digest = await generate_digest(hours=24)

    mock_agent.run.assert_not_called()
    assert "unavailable" in digest.headline.lower()
    assert "task_note_absent" in digest.summary


@pytest.mark.asyncio
@patch("agents.digest.collect_recent_documents")
@patch("agents.digest.collect_collection_stats")
@patch("agents.digest._get_digest_agent")
async def test_generate_digest_prompt_includes_collection_stats(
    mock_get_agent,
    mock_stats,
    mock_docs,
):
    mock_agent = mock_get_agent.return_value  # the factory's constructed agent
    """Pipeline includes collection size stats in prompt."""
    from agents.digest import generate_digest

    mock_docs.return_value = []
    mock_stats.return_value = {"documents": 1500, "samples": 80, "claude-memory": 200}
    mock_agent.run = AsyncMock(return_value=_FakeDigestResult())

    with patch("agents.digest._admit_digest_synthesis", return_value=_admitted_digest_admission()):
        await generate_digest(hours=24)
    prompt = mock_agent.run.call_args[0][0]
    assert "1500 points" in prompt
    assert "80 points" in prompt
