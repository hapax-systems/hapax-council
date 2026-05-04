"""End-to-end smoke test: director moves → segments.jsonl quality rating.

Cc-task ``director-moves-segment-smoke`` (operator outcome 3 follow-up).
Composes alpha's PR #2472 ``shared/segment_observability.py`` with the
director's existing intent emission so each iteration window resolves
into a ``SegmentEvent`` carrying a ``quality.director_moves`` rating.

Operator framing: "this is a segment + it happened/didn't + happened
well/not well". This test exercises all four "happened well/not well"
tiers (poor / acceptable / good / excellent) plus the lifecycle pair
(STARTED + HAPPENED), driven through the deterministic micromove path
and synthetic real-intent records — no LLM, GStreamer, or camera infra
required.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.studio_compositor.director_moves_quality import (
    assess_director_moves_quality,
)
from agents.studio_compositor.director_segment import record_director_segment
from shared.segment_observability import (
    QualityRating,
    SegmentLifecycle,
)

# ── Synthetic intent-record helpers ──────────────────────────────────────────


def _stale_intent_record() -> dict:
    """Mimic the director's stale-intent micromove fallback record shape.

    Mirrors ``director_loop._emit_micromove_fallback`` writing through
    ``_emit_intent_artifacts``: top-level
    ``synthetic_grounding_markers=["fallback.micromove.stale_intent"]``
    plus a single impingement also carrying the same fallback marker.
    """

    return {
        "activity": "observe",
        "stance": "nominal",
        "narrative_text": "[micromove:stale_intent] sweep emphasis across the chat-ambient ward",
        "grounding_provenance": [],
        "synthetic_grounding_markers": ["fallback.micromove.stale_intent"],
        "compositional_impingements": [
            {
                "narrative": "sweep emphasis across the chat-ambient ward",
                "intent_family": "overlay.emphasis",
                "material": "air",
                "salience": 0.35,
                "grounding_provenance": [],
                "synthetic_grounding_markers": ["fallback.micromove.stale_intent"],
            }
        ],
    }


def _good_record(family: str = "camera.hero", grounding: str = "visual.detected_action") -> dict:
    """A non-fallback record with at least one real grounding key.

    Uniformly real grounding plus no synthetic markers — qualifies for
    GOOD when the family count stays at 1, EXCELLENT when ≥2 distinct
    families are present across the window.
    """

    return {
        "activity": "react",
        "stance": "nominal",
        "narrative_text": "shift to closeup of the operator catching the lyric",
        "grounding_provenance": [grounding],
        "synthetic_grounding_markers": [],
        "compositional_impingements": [
            {
                "narrative": "show the operator reacting to the lyric",
                "intent_family": family,
                "material": "earth",
                "salience": 0.7,
                "grounding_provenance": [grounding],
                "synthetic_grounding_markers": [],
            }
        ],
    }


def _good_record_synthetic_only_impingement() -> dict:
    """Non-fallback at the top level, but the impingement has only synthetic markers.

    Disqualifies the record from EXCELLENT (uniform real grounding fails)
    while staying out of the fallback bucket — useful for ensuring GOOD
    is the right ceiling when grounding is mixed at the impingement
    level rather than the top level.
    """

    return {
        "activity": "observe",
        "stance": "nominal",
        "narrative_text": "settle the room without naming a perceptual key",
        "grounding_provenance": [],
        "synthetic_grounding_markers": [],
        "compositional_impingements": [
            {
                "narrative": "let the chrome breathe",
                "intent_family": "overlay.emphasis",
                "material": "air",
                "salience": 0.4,
                "grounding_provenance": [],
                "synthetic_grounding_markers": ["inferred.nominal.overlay.emphasis"],
            }
        ],
    }


def _write_records(path: Path, records: list[dict]) -> None:
    """Append records to a director-intent JSONL file (one record per line)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _read_segment_events(path: Path) -> list[dict]:
    """Parse every JSONL line in segments.jsonl into a list of dicts."""

    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        out.append(json.loads(stripped))
    return out


# ── 1. Quality assessor — direct-input tier coverage ─────────────────────────


class TestAssessDirectorMovesQuality:
    """Each tier boundary verified against a hand-crafted record window."""

    def test_empty_window_is_unmeasured(self):
        assert assess_director_moves_quality([]) == QualityRating.UNMEASURED

    def test_all_stale_intent_is_poor(self):
        records = [_stale_intent_record() for _ in range(3)]
        assert assess_director_moves_quality(records) == QualityRating.POOR

    def test_one_stale_one_real_is_acceptable(self):
        records = [_stale_intent_record(), _good_record()]
        assert assess_director_moves_quality(records) == QualityRating.ACCEPTABLE

    def test_inferred_marker_at_top_level_is_acceptable(self):
        """Top-level ``inferred.<stance>.<family>`` markers also count as fallback."""

        record = _good_record()
        record["synthetic_grounding_markers"] = ["inferred.nominal.camera.hero"]
        assert assess_director_moves_quality([record]) == QualityRating.ACCEPTABLE

    def test_single_family_real_grounding_is_good(self):
        """Non-fallback + uniformly real but only one family → GOOD, not EXCELLENT.

        Composability requires ≥2 distinct intent_family across the window.
        """

        records = [_good_record() for _ in range(3)]
        assert assess_director_moves_quality(records) == QualityRating.GOOD

    def test_synthetic_only_impingement_caps_at_good(self):
        """Non-fallback top-level but synthetic-only impingements caps at GOOD."""

        records = [_good_record(), _good_record_synthetic_only_impingement()]
        # Two distinct families (camera.hero + overlay.emphasis), but the
        # second record's impingement has only synthetic markers → uniformly
        # real grounding fails → ceiling is GOOD.
        assert assess_director_moves_quality(records) == QualityRating.GOOD

    def test_multi_family_uniformly_real_is_excellent(self):
        """Non-fallback + uniformly real grounding + ≥2 families → EXCELLENT."""

        records = [
            _good_record(family="camera.hero", grounding="visual.detected_action"),
            _good_record(family="mood.tone_pivot", grounding="stimmung.dimensions.coherence"),
            _good_record(family="composition.reframe", grounding="visual.gaze_direction"),
        ]
        assert assess_director_moves_quality(records) == QualityRating.EXCELLENT


# ── 2. SegmentRecorder wiring — segments.jsonl receives the rating ───────────


@pytest.fixture
def segments_log(tmp_path: Path, monkeypatch) -> Path:
    """Route alpha's SegmentRecorder to a per-test segments.jsonl path."""

    target = tmp_path / "segments" / "segments.jsonl"
    monkeypatch.setenv("HAPAX_SEGMENTS_LOG", str(target))
    return target


@pytest.fixture
def director_intent_jsonl(tmp_path: Path) -> Path:
    """Per-test director-intent JSONL the recorder will read back from."""

    return tmp_path / "director-intent.jsonl"


class TestRecordDirectorSegmentLifecycle:
    """STARTED + HAPPENED pair, with the right director_moves rating on exit."""

    def test_happened_with_excellent_rating(
        self,
        segments_log: Path,
        director_intent_jsonl: Path,
    ):
        with record_director_segment(
            programme_role="director_moves_smoke",
            topic_seed="excellent-tier",
            intent_jsonl_path=director_intent_jsonl,
        ) as event:
            _write_records(
                director_intent_jsonl,
                [
                    _good_record(family="camera.hero", grounding="visual.detected_action"),
                    _good_record(
                        family="mood.tone_pivot",
                        grounding="stimmung.dimensions.coherence",
                    ),
                ],
            )
            assert event.programme_role == "director_moves_smoke"
            assert event.topic_seed == "excellent-tier"

        events = _read_segment_events(segments_log)
        # Two events: STARTED + HAPPENED, same segment_id.
        assert len(events) == 2
        started, ended = events
        assert started["lifecycle"] == SegmentLifecycle.STARTED.value
        assert ended["lifecycle"] == SegmentLifecycle.HAPPENED.value
        assert started["segment_id"] == ended["segment_id"]
        assert ended["quality"]["director_moves"] == QualityRating.EXCELLENT.value

    def test_happened_with_poor_rating_for_stale_intent(
        self,
        segments_log: Path,
        director_intent_jsonl: Path,
    ):
        with record_director_segment(
            programme_role="director_moves_smoke",
            topic_seed="poor-tier",
            intent_jsonl_path=director_intent_jsonl,
        ):
            _write_records(
                director_intent_jsonl,
                [_stale_intent_record() for _ in range(3)],
            )

        events = _read_segment_events(segments_log)
        assert events[-1]["quality"]["director_moves"] == QualityRating.POOR.value

    def test_happened_with_good_rating_when_single_family(
        self,
        segments_log: Path,
        director_intent_jsonl: Path,
    ):
        with record_director_segment(
            programme_role="director_moves_smoke",
            topic_seed="good-tier",
            intent_jsonl_path=director_intent_jsonl,
        ):
            _write_records(
                director_intent_jsonl,
                [_good_record() for _ in range(3)],
            )

        events = _read_segment_events(segments_log)
        assert events[-1]["quality"]["director_moves"] == QualityRating.GOOD.value

    def test_happened_with_acceptable_when_mixed(
        self,
        segments_log: Path,
        director_intent_jsonl: Path,
    ):
        with record_director_segment(
            programme_role="director_moves_smoke",
            topic_seed="acceptable-tier",
            intent_jsonl_path=director_intent_jsonl,
        ):
            _write_records(
                director_intent_jsonl,
                [_stale_intent_record(), _good_record(), _good_record()],
            )

        events = _read_segment_events(segments_log)
        assert events[-1]["quality"]["director_moves"] == QualityRating.ACCEPTABLE.value

    def test_unmeasured_when_window_emits_no_records(
        self,
        segments_log: Path,
        director_intent_jsonl: Path,
    ):
        """A segment with no director output exits HAPPENED but UNMEASURED."""

        with record_director_segment(
            programme_role="director_moves_smoke",
            topic_seed="empty-window",
            intent_jsonl_path=director_intent_jsonl,
        ):
            pass

        events = _read_segment_events(segments_log)
        assert events[-1]["lifecycle"] == SegmentLifecycle.HAPPENED.value
        assert events[-1]["quality"]["director_moves"] == QualityRating.UNMEASURED.value

    def test_didnt_happen_still_carries_quality_rating(
        self,
        segments_log: Path,
        director_intent_jsonl: Path,
    ):
        """An exception inside the body emits DIDNT_HAPPEN with the partial-window rating."""

        class _BoomError(RuntimeError):
            pass

        with pytest.raises(_BoomError):
            with record_director_segment(
                programme_role="director_moves_smoke",
                topic_seed="exception-tier",
                intent_jsonl_path=director_intent_jsonl,
            ):
                _write_records(
                    director_intent_jsonl,
                    [
                        _good_record(family="camera.hero", grounding="visual.detected_action"),
                        _good_record(
                            family="mood.tone_pivot",
                            grounding="stimmung.dimensions.coherence",
                        ),
                    ],
                )
                raise _BoomError("director iteration aborted")

        events = _read_segment_events(segments_log)
        assert len(events) == 2
        assert events[0]["lifecycle"] == SegmentLifecycle.STARTED.value
        assert events[-1]["lifecycle"] == SegmentLifecycle.DIDNT_HAPPEN.value
        # Even on the failure path, the partial intents the body managed
        # to emit get scored — DIDNT_HAPPEN is still informative.
        assert events[-1]["quality"]["director_moves"] == QualityRating.EXCELLENT.value


# ── 3. End-to-end via _emit_micromove_fallback (no LLM) ──────────────────────


class TestEndToEndMicromoveFallback:
    """The director's deterministic micromove path goes start-to-finish through
    SegmentRecorder and lands the right rating on segments.jsonl.

    Drives ``DirectorLoop._emit_micromove_fallback`` directly with
    ``reason="stale_intent"`` so every record in the window carries the
    stale-intent fallback marker — verifies the POOR tier all the way
    from real director emission through the assessor to alpha's segment
    log.
    """

    def test_stale_intent_window_lands_poor(
        self,
        tmp_path: Path,
        monkeypatch,
        segments_log: Path,
    ):
        from agents.studio_compositor import director_loop as dl

        # Redirect the director's JSONL emission to a per-test path so the
        # smoke test does not contaminate (or read) the operator's live
        # ``~/hapax-state/stream-experiment/director-intent.jsonl``.
        intent_path = tmp_path / "director-intent.jsonl"
        narrative_state_path = tmp_path / "narrative-state.json"
        monkeypatch.setattr(dl, "_DIRECTOR_INTENT_JSONL", intent_path)
        monkeypatch.setattr(dl, "_NARRATIVE_STATE_PATH", narrative_state_path)

        loop = dl.DirectorLoop(video_slots=[], reactor_overlay=None)

        with record_director_segment(
            programme_role="director_moves_smoke",
            topic_seed="micromove-stale-intent",
            intent_jsonl_path=intent_path,
        ):
            for _ in range(3):
                loop._emit_micromove_fallback(reason="stale_intent", condition_id="smoke")

        # Confirm the director did emit records into the temp JSONL.
        emitted = intent_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(emitted) >= 3, "director failed to emit micromove fallback records"

        events = _read_segment_events(segments_log)
        assert events, "no segment events landed on segments.jsonl"
        ended = events[-1]
        assert ended["lifecycle"] == SegmentLifecycle.HAPPENED.value
        assert ended["quality"]["director_moves"] == QualityRating.POOR.value
        assert ended["programme_role"] == "director_moves_smoke"
        assert ended["topic_seed"] == "micromove-stale-intent"
