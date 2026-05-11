"""Tests for hermeneutic spiral persistence — cross-cycle fore-understanding."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from shared.hermeneutic_spiral import (
    COLLECTION_NAME,
    HermeneuticDelta,
    _embed_text,
    _point_id,
    compute_hermeneutic_delta,
    persist_source_consequences,
    retrieve_fore_understanding,
)


def _sample_map() -> list[dict]:
    return [
        {
            "beat_index": 0,
            "source_ref": "vault:zuboff-note",
            "evidence_ref": "prepared_script[0]",
            "consequence": "ranking_or_order_changed",
            "changed_dimensions": ["claim", "ranking"],
            "advisory_only": True,
        },
        {
            "beat_index": 2,
            "source_ref": "vault:nancy-corps-sonore",
            "evidence_ref": "prepared_script[2]",
            "consequence": "claim_shape_changed",
            "changed_dimensions": ["claim"],
            "advisory_only": True,
        },
    ]


def test_point_id_is_deterministic() -> None:
    a = _point_id("prog-1", "vault:zuboff", 0)
    b = _point_id("prog-1", "vault:zuboff", 0)
    assert a == b


def test_point_id_varies_with_inputs() -> None:
    a = _point_id("prog-1", "vault:zuboff", 0)
    b = _point_id("prog-1", "vault:zuboff", 1)
    c = _point_id("prog-2", "vault:zuboff", 0)
    assert a != b
    assert a != c


def test_embed_text_includes_role_topic_consequence() -> None:
    entry = {
        "source_ref": "vault:zuboff",
        "consequence": "ranking_or_order_changed",
        "changed_dimensions": ["claim", "ranking"],
    }
    text = _embed_text(entry, topic="surveillance capitalism", role="tier_list")
    assert "tier_list" in text
    assert "surveillance capitalism" in text
    assert "vault:zuboff" in text
    assert "ranking_or_order_changed" in text


def test_persist_returns_zero_on_empty_map() -> None:
    result = persist_source_consequences(
        [],
        programme_id="p1",
        role="tier_list",
        topic="test",
        prep_session_id="s1",
    )
    assert result == 0


@patch("shared.config.get_qdrant")
@patch("shared.config.embed_batch_safe")
def test_persist_upserts_points(mock_embed: MagicMock, mock_qdrant: MagicMock) -> None:
    mock_embed.return_value = [[0.1] * 768, [0.2] * 768]
    client = MagicMock()
    mock_qdrant.return_value = client

    result = persist_source_consequences(
        _sample_map(),
        programme_id="prog-1",
        role="tier_list",
        topic="surveillance capitalism",
        prep_session_id="sess-1",
    )

    assert result == 2
    client.upsert.assert_called_once()
    call_args = client.upsert.call_args
    assert call_args.kwargs["collection_name"] == COLLECTION_NAME
    points = call_args.kwargs["points"]
    assert len(points) == 2
    assert points[0].payload["source_ref"] == "vault:zuboff-note"
    assert points[0].payload["programme_id"] == "prog-1"
    assert points[1].payload["source_ref"] == "vault:nancy-corps-sonore"


@patch("shared.config.embed_batch_safe")
def test_persist_returns_zero_on_embedding_failure(mock_embed: MagicMock) -> None:
    mock_embed.return_value = None

    result = persist_source_consequences(
        _sample_map(),
        programme_id="p1",
        role="tier_list",
        topic="test",
        prep_session_id="s1",
    )
    assert result == 0


@patch("shared.config.get_qdrant")
@patch("shared.config.embed")
def test_retrieve_queries_qdrant(mock_embed: MagicMock, mock_qdrant: MagicMock) -> None:
    mock_embed.return_value = [0.1] * 768

    mock_point = MagicMock()
    mock_point.id = "point-1"
    mock_point.score = 0.85
    mock_point.payload = {
        "source_ref": "vault:zuboff",
        "consequence_kind": "ranking_or_order_changed",
        "programme_id": "old-prog",
    }

    mock_result = MagicMock()
    mock_result.points = [mock_point]

    client = MagicMock()
    client.query_points.return_value = mock_result
    mock_qdrant.return_value = client

    priors = retrieve_fore_understanding(topic="surveillance capitalism", role="tier_list")

    assert len(priors) == 1
    assert priors[0]["source_ref"] == "vault:zuboff"
    assert priors[0]["_point_id"] == "point-1"
    assert priors[0]["_score"] == 0.85
    client.query_points.assert_called_once()


def test_compute_delta_new_consequence() -> None:
    current = _sample_map()
    priors: list[dict] = []

    deltas = compute_hermeneutic_delta(
        current,
        priors,
        programme_id="prog-1",
        role="tier_list",
        topic="test",
    )

    assert len(deltas) == 2
    assert all(isinstance(d, HermeneuticDelta) for d in deltas)
    assert deltas[0].delta_kind == "new_consequence"
    assert deltas[0].source_ref == "vault:zuboff-note"
    assert deltas[0].prior_encounter_ids == ()


def test_compute_delta_reinforced_when_same_consequence_kind() -> None:
    current = _sample_map()[:1]
    priors = [
        {
            "source_ref": "vault:zuboff-note",
            "consequence_kind": "ranking_or_order_changed",
            "changed_dimensions": ["claim", "ranking"],
            "_point_id": "prior-1",
        }
    ]

    deltas = compute_hermeneutic_delta(
        current,
        priors,
        programme_id="prog-2",
        role="tier_list",
        topic="test",
    )

    assert len(deltas) == 1
    assert deltas[0].delta_kind == "reinforced_consequence"
    assert deltas[0].prior_encounter_ids == ("prior-1",)


def test_compute_delta_revised_when_different_consequence_kind() -> None:
    current = [
        {
            "beat_index": 0,
            "source_ref": "vault:zuboff-note",
            "evidence_ref": "prepared_script[0]",
            "consequence": "scope_or_refusal_changed",
            "changed_dimensions": ["claim", "scope"],
            "advisory_only": True,
        }
    ]
    priors = [
        {
            "source_ref": "vault:zuboff-note",
            "consequence_kind": "ranking_or_order_changed",
            "changed_dimensions": ["claim", "ranking"],
            "_point_id": "prior-1",
        }
    ]

    deltas = compute_hermeneutic_delta(
        current,
        priors,
        programme_id="prog-3",
        role="tier_list",
        topic="test",
    )

    assert len(deltas) == 1
    assert deltas[0].delta_kind == "revised_consequence"
    assert "Revised" in deltas[0].summary


def test_compute_delta_novel_dimension() -> None:
    current = [
        {
            "beat_index": 0,
            "source_ref": "vault:new-source",
            "evidence_ref": "prepared_script[0]",
            "consequence": "visible_or_layout_obligation_changed",
            "changed_dimensions": ["layout_need"],
            "advisory_only": True,
        }
    ]
    priors = [
        {
            "source_ref": "vault:other-source",
            "consequence_kind": "ranking_or_order_changed",
            "changed_dimensions": ["claim", "ranking"],
            "_point_id": "prior-1",
        }
    ]

    deltas = compute_hermeneutic_delta(
        current,
        priors,
        programme_id="prog-4",
        role="tier_list",
        topic="test",
    )

    assert len(deltas) == 1
    assert deltas[0].delta_kind == "novel_dimension"
    assert "layout_need" in deltas[0].changed_dimensions


def test_compute_delta_skips_entries_without_source_ref() -> None:
    current = [{"beat_index": 0, "consequence": "claim_shape_changed"}]

    deltas = compute_hermeneutic_delta(
        current,
        [],
        programme_id="prog-5",
        role="tier_list",
        topic="test",
    )

    assert len(deltas) == 0


def test_persist_call_is_after_segment_save_in_prep_segment() -> None:
    """persist_source_consequences must run AFTER the segment file is saved."""
    from pathlib import Path

    source = (Path(__file__).parents[2] / "agents/hapax_daimonion/daily_segment_prep.py").read_text(
        encoding="utf-8"
    )
    save_pos = source.find("tmp.replace(out_path)")
    persist_pos = source.find("persist_source_consequences(", save_pos)
    assert save_pos > 0, "segment save not found"
    assert persist_pos > save_pos, (
        "persist_source_consequences must appear after segment save "
        f"(save at {save_pos}, persist at {persist_pos})"
    )


def test_planner_accepts_fore_understanding_kwarg() -> None:
    """ProgrammePlanner.plan() must accept fore_understanding."""
    import inspect

    from agents.programme_manager.planner import ProgrammePlanner

    sig = inspect.signature(ProgrammePlanner.plan)
    assert "fore_understanding" in sig.parameters


def test_run_prep_calls_retrieve_broad_fore_understanding() -> None:
    """run_prep must call _retrieve_broad_fore_understanding before planner."""
    from pathlib import Path

    source = (Path(__file__).parents[2] / "agents/hapax_daimonion/daily_segment_prep.py").read_text(
        encoding="utf-8"
    )
    assert "_retrieve_broad_fore_understanding()" in source
    fore_pos = source.find("_retrieve_broad_fore_understanding()")
    planner_pos = source.find("planner.plan(", fore_pos)
    assert planner_pos > fore_pos, "fore_understanding retrieval must precede planner call"
