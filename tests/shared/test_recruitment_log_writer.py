"""Regression tests for the recruitment-log writer in `AffordancePipeline`.

The writer persists each `select()` winner to
``~/hapax-state/affordance/recruitment-log.jsonl`` so the preset-variety
baseline script can compute ``per_preset_activation_count`` and
``colorgrade_halftone_ratio``. The append must be:

- Non-blocking (fail-open on filesystem error)
- Disabled by ``HAPAX_RECRUITMENT_LOG=0``
- Top-1 winner only (survivors[1:] are tied for ranking but only the
  top is "applied" downstream)
- Lightweight (no embeddings)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from shared.affordance_pipeline import AffordancePipeline


@pytest.fixture
def recruit_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the writer to a temp file."""
    target = tmp_path / "recruitment-log.jsonl"
    import shared.affordance_pipeline as _ap

    monkeypatch.setattr(_ap, "RECRUITMENT_LOG_FILE", target)
    monkeypatch.delenv(_ap.RECRUITMENT_LOG_ENV, raising=False)
    return target


def test_writer_appends_winner_line(recruit_log: Path) -> None:
    pipeline = AffordancePipeline()
    entry = {
        "timestamp": 12345.6,
        "source": "test.source",
        "metric": "test_metric",
        "winners": [
            {"name": "node.colorgrade", "similarity": 0.81, "combined": 0.91},
            {"name": "fx.family.calm-textural", "similarity": 0.55, "combined": 0.66},
        ],
    }
    pipeline._persist_recruitment_winner(entry)
    line = recruit_log.read_text().strip()
    payload = json.loads(line)
    assert payload["capability_name"] == "node.colorgrade"
    assert payload["similarity"] == 0.81
    assert payload["combined"] == 0.91
    assert payload["timestamp"] == 12345.6
    assert payload["impingement_source"] == "test.source"
    assert payload["impingement_metric"] == "test_metric"
    assert "embedding" not in payload


def test_writer_disabled_via_env(recruit_log: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``HAPAX_RECRUITMENT_LOG=0`` short-circuits the writer."""
    import shared.affordance_pipeline as _ap

    monkeypatch.setenv(_ap.RECRUITMENT_LOG_ENV, "0")
    pipeline = AffordancePipeline()
    pipeline._persist_recruitment_winner({"timestamp": 1.0, "winners": [{"name": "x"}]})
    assert not recruit_log.exists()


def test_writer_handles_empty_winners_list(recruit_log: Path) -> None:
    """No winners → no write (degenerate cascade entry)."""
    pipeline = AffordancePipeline()
    pipeline._persist_recruitment_winner({"timestamp": 1.0, "winners": []})
    assert not recruit_log.exists()


def test_writer_swallows_filesystem_error(
    recruit_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OS errors must NOT raise into the recruitment hot path."""
    pipeline = AffordancePipeline()
    with patch.object(Path, "open", side_effect=OSError("disk full")):
        pipeline._persist_recruitment_winner({"timestamp": 1.0, "winners": [{"name": "x"}]})


def test_writer_appends_multiple_lines(recruit_log: Path) -> None:
    """Multiple writes accumulate as JSONL."""
    pipeline = AffordancePipeline()
    for i in range(5):
        pipeline._persist_recruitment_winner(
            {
                "timestamp": float(i),
                "source": f"src-{i}",
                "metric": "",
                "winners": [{"name": f"cap-{i}", "similarity": 0.5, "combined": 0.6}],
            }
        )
    lines = recruit_log.read_text().strip().splitlines()
    assert len(lines) == 5
    payloads = [json.loads(line) for line in lines]
    assert [p["capability_name"] for p in payloads] == [f"cap-{i}" for i in range(5)]


def test_writer_creates_parent_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Writer creates ``hapax-state/affordance/`` if missing."""
    target = tmp_path / "deeper" / "subdir" / "recruitment-log.jsonl"
    import shared.affordance_pipeline as _ap

    monkeypatch.setattr(_ap, "RECRUITMENT_LOG_FILE", target)
    pipeline = AffordancePipeline()
    pipeline._persist_recruitment_winner(
        {"timestamp": 1.0, "source": "s", "metric": "m", "winners": [{"name": "x"}]}
    )
    assert target.exists()
    assert json.loads(target.read_text().strip())["capability_name"] == "x"


def test_log_cascade_calls_writer(recruit_log: Path) -> None:
    """``_log_cascade`` (the in-process cascade tracker) routes to the
    persistent writer end-to-end so a real recruitment lands on disk."""
    from shared.affordance import SelectionCandidate
    from shared.impingement import Impingement, ImpingementType

    pipeline = AffordancePipeline()
    impingement = Impingement(
        timestamp=999.0,
        source="test.cascade",
        type=ImpingementType.PATTERN_MATCH,
        strength=0.5,
        content={"metric": "t"},
    )
    winners = [
        SelectionCandidate(capability_name="node.halftone", similarity=0.7, combined=0.8),
    ]
    pipeline._log_cascade(impingement, winners)
    line = recruit_log.read_text().strip()
    payload = json.loads(line)
    assert payload["capability_name"] == "node.halftone"
    assert payload["impingement_source"] == "test.cascade"
