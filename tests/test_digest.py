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
            collection_sizes={"documents": 1200, "samples": 50},
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
            collection_sizes={"documents": 1500, "samples": 80, "claude-memory": 200},
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
    assert stats["samples"] == 100
    assert stats["claude-memory"] == 100


@patch("agents.digest.get_qdrant")
def test_collect_collection_stats_partial_failure(mock_qdrant):
    """One failing collection doesn't prevent others."""
    mock_client = MagicMock()
    mock_qdrant.return_value = mock_client

    def count_side_effect(collection_name):
        if collection_name == "samples":
            raise Exception("Not found")
        result = MagicMock()
        result.count = 50
        return result

    mock_client.count.side_effect = count_side_effect

    stats = collect_collection_stats()
    assert stats["documents"] == 50
    assert stats["samples"] == -1


# ── Notification tests ───────────────────────────────────────────────────────


@patch("shared.notify.send_notification")
def test_send_notification_calls_shared_notify(mock_notify):
    d = _sample_digest()
    send_notification(d)
    mock_notify.assert_called_once()
    kwargs = mock_notify.call_args
    assert kwargs[0][0] == "Content Digest"


@patch("shared.notify.send_notification")
def test_send_notification_includes_doc_count(mock_notify):
    d = _sample_digest()
    send_notification(d)
    message = mock_notify.call_args[0][1]
    assert "5 new document" in message


@patch("shared.notify.send_notification")
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


@pytest.mark.asyncio
@patch("agents.digest.collect_recent_documents")
@patch("agents.digest.collect_collection_stats")
@patch("agents.digest.digest_agent")
async def test_generate_digest_pipeline(
    mock_agent,
    mock_stats,
    mock_docs,
):
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
    mock_stats.return_value = {"documents": 1500, "samples": 80}
    mock_agent.run = AsyncMock(return_value=_FakeDigestResult())

    digest = await generate_digest(hours=24)
    assert digest.hours == 24
    assert digest.stats.new_documents == 1
    assert digest.stats.collection_sizes["documents"] == 1500
    assert digest.generated_at.endswith("Z")


@pytest.mark.asyncio
@patch("agents.digest.collect_recent_documents")
@patch("agents.digest.collect_collection_stats")
@patch("agents.digest.digest_agent")
async def test_generate_digest_empty_results(
    mock_agent,
    mock_stats,
    mock_docs,
):
    """Pipeline handles no new content gracefully."""
    from agents.digest import generate_digest

    mock_docs.return_value = []
    mock_stats.return_value = {"documents": 100}
    mock_agent.run = AsyncMock(return_value=_FakeDigestResult())

    digest = await generate_digest(hours=24)
    assert digest.stats.new_documents == 0

    # Prompt should mention "No new documents"
    prompt = mock_agent.run.call_args[0][0]
    assert "No new documents" in prompt


@pytest.mark.asyncio
@patch("agents.digest.collect_recent_documents")
@patch("agents.digest.collect_collection_stats")
@patch("agents.digest.digest_agent")
async def test_generate_digest_llm_failure_graceful(
    mock_agent,
    mock_stats,
    mock_docs,
):
    """Pipeline handles LLM failure gracefully."""
    from agents.digest import generate_digest

    mock_docs.return_value = []
    mock_stats.return_value = {}
    mock_agent.run = AsyncMock(side_effect=Exception("LLM timeout"))

    digest = await generate_digest(hours=24)
    assert "unavailable" in digest.headline.lower() or "error" in digest.headline.lower()
    assert digest.stats.new_documents == 0


@pytest.mark.asyncio
@patch("agents.digest.collect_recent_documents")
@patch("agents.digest.collect_collection_stats")
@patch("agents.digest.digest_agent")
async def test_generate_digest_prompt_includes_collection_stats(
    mock_agent,
    mock_stats,
    mock_docs,
):
    """Pipeline includes collection size stats in prompt."""
    from agents.digest import generate_digest

    mock_docs.return_value = []
    mock_stats.return_value = {"documents": 1500, "samples": 80, "claude-memory": 200}
    mock_agent.run = AsyncMock(return_value=_FakeDigestResult())

    await generate_digest(hours=24)
    prompt = mock_agent.run.call_args[0][0]
    assert "1500 points" in prompt
    assert "80 points" in prompt
