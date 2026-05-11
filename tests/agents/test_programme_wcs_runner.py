"""Readiness tests for the programme WCS runner path."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agents.hapax_daimonion import programme_loop
from agents.hapax_daimonion.autonomous_narrative import compose as compose_mod
from agents.programme_manager.manager import BoundaryTrigger, ProgrammeManager
from agents.programme_manager.transition import TransitionChoreographer
from shared.programme import (
    Programme,
    ProgrammeAssetAttribution,
    ProgrammeBeatCard,
    ProgrammeContent,
    ProgrammeLivePrior,
    ProgrammeRole,
    ProgrammeStatus,
    ProgrammeSuccessCriteria,
)
from shared.programme_store import ProgrammePlanStore


class _Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(autouse=True)
def _reset_beat_transition_state() -> Iterator[None]:
    compose_mod._last_beat_by_programme.clear()
    yield
    compose_mod._last_beat_by_programme.clear()


def _programme(
    programme_id: str,
    *,
    status: ProgrammeStatus = ProgrammeStatus.PENDING,
    started_at: float | None = None,
    topic: str = "WCS public-mode readiness",
) -> Programme:
    return Programme(
        programme_id=programme_id,
        role=ProgrammeRole.TIER_LIST,
        status=status,
        planned_duration_s=360.0,
        actual_started_at=started_at,
        content=ProgrammeContent(
            declared_topic=topic,
            source_uri=f"https://example.invalid/{programme_id}",
            narrative_beat=f"Rank programme runner blockers for {topic}.",
            source_refs=[f"vault:{programme_id}:source"],
            evidence_refs=[f"wcs:{programme_id}:witness"],
            source_packet_refs=[{"source_packet_ref": f"packet:{programme_id}:evidence"}],
            role_contract={
                "source_packet_refs": [f"role-contract:{programme_id}:packet"],
                "role_live_bit_mechanic": "rank readiness blockers from witnessed WCS evidence",
            },
            asset_attributions=[
                ProgrammeAssetAttribution(
                    source_ref=f"asset:{programme_id}:tier-card",
                    asset_kind="text",
                    title="Readiness tier card",
                    resolver_ref=f"resolver:{programme_id}:asset",
                    rights_summary="operator-authored fixture asset",
                )
            ],
            segment_beats=[
                "hook: name the public-mode runner question",
                "criteria: rank grounding, witnesses, rights, and WCS health",
                "close: state which blocker keeps public mode held",
            ],
            segment_beat_durations=[30.0, 45.0, 60.0],
            beat_cards=[
                ProgrammeBeatCard(
                    beat_index=0,
                    beat_id="hook",
                    title="Hook",
                    prior_summary="Open with the runner readiness question.",
                    evidence_refs=[f"wcs:{programme_id}:witness"],
                ),
                ProgrammeBeatCard(
                    beat_index=1,
                    beat_id="criteria",
                    title="Criteria",
                    prior_summary="Compare each public-mode gate against its evidence.",
                    evidence_refs=[f"packet:{programme_id}:evidence"],
                ),
            ],
            live_priors=[
                ProgrammeLivePrior(
                    prior_id="hook-prior",
                    beat_index=0,
                    text="The run only becomes public after grounding and WCS evidence agree.",
                    evidence_refs=[f"wcs:{programme_id}:witness"],
                ),
                ProgrammeLivePrior(
                    prior_id="criteria-prior",
                    beat_index=1,
                    text="Witnesses and rights outrank engagement signals in the readiness order.",
                    evidence_refs=[f"packet:{programme_id}:evidence"],
                ),
            ],
            beat_action_intents=[
                {
                    "beat_index": 1,
                    "intents": [
                        {
                            "kind": "compare_readiness_gates",
                            "expected_effect": "criterion boundary is explicit",
                        }
                    ],
                }
            ],
        ),
        success=ProgrammeSuccessCriteria(
            completion_predicates=[],
            abort_predicates=[],
            min_duration_s=0.0,
            max_duration_s=900.0,
        ),
        parent_show_id="show-wcs-readiness",
    )


def _store(tmp_path: Path) -> ProgrammePlanStore:
    return ProgrammePlanStore(path=tmp_path / "programmes.jsonl")


def test_programmes_load_from_store_with_wcs_content_contract(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add(_programme("prog-wcs-hook"))
    store.add(_programme("prog-wcs-criteria"))

    loaded = ProgrammePlanStore(path=store.path).all()

    assert [programme.programme_id for programme in loaded] == [
        "prog-wcs-hook",
        "prog-wcs-criteria",
    ]
    assert all(programme.role is ProgrammeRole.TIER_LIST for programme in loaded)
    assert all(programme.content.segment_beats for programme in loaded)
    assert loaded[0].content.beat_cards[0].prior_summary == (
        "Open with the runner readiness question."
    )
    assert loaded[1].content.live_priors[1].text.startswith("Witnesses and rights outrank")


def test_programme_sequence_steps_through_planned_boundaries(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add(_programme("prog-wcs-hook"))
    store.add(_programme("prog-wcs-criteria"))
    clock = _Clock()
    manager = ProgrammeManager(
        store=store,
        choreographer=TransitionChoreographer(impingements_file=tmp_path / "impingements.jsonl"),
        now_fn=clock,
    )

    first = manager.tick()
    clock.advance(361.0)
    second = manager.tick()

    assert first.trigger is BoundaryTrigger.PLANNED
    assert first.to_programme is not None
    assert first.to_programme.programme_id == "prog-wcs-hook"
    assert second.trigger is BoundaryTrigger.PLANNED
    assert second.from_programme is not None
    assert second.from_programme.programme_id == "prog-wcs-hook"
    assert second.to_programme is not None
    assert second.to_programme.programme_id == "prog-wcs-criteria"
    assert store.get("prog-wcs-hook").status is ProgrammeStatus.COMPLETED  # type: ignore[union-attr]
    assert store.active_programme().programme_id == "prog-wcs-criteria"  # type: ignore[union-attr]


def test_current_beat_content_resolves_to_ward_payload() -> None:
    active = _programme(
        "prog-wcs-criteria",
        status=ProgrammeStatus.ACTIVE,
        started_at=1_000.0,
    )

    payload = programme_loop._active_segment_payload(active, "tier_list", 1)

    assert payload["programme_id"] == "prog-wcs-criteria"
    assert payload["role"] == "tier_list"
    assert payload["ward_profile"] == "ranked_tiers"
    assert payload["current_beat_index"] == 1
    assert payload["current_beat_cards"][0]["beat_id"] == "criteria"
    assert payload["current_beat_live_priors"][0]["prior_id"] == "criteria-prior"
    assert payload["current_beat_action_intents"][0]["beat_index"] == 1
    assert set(payload["source_refs"]) >= {
        "https://example.invalid/prog-wcs-criteria",
        "vault:prog-wcs-criteria:source",
        "wcs:prog-wcs-criteria:witness",
        "packet:prog-wcs-criteria:evidence",
        "role-contract:prog-wcs-criteria:packet",
        "asset:prog-wcs-criteria:tier-card",
        "resolver:prog-wcs-criteria:asset",
    }


def test_timing_transitions_fire_from_declared_beat_durations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = _programme(
        "prog-wcs-timed",
        status=ProgrammeStatus.ACTIVE,
        started_at=1_000.0,
    )

    monkeypatch.setattr(compose_mod.time, "time", lambda: 1_005.0)
    assert compose_mod.check_beat_transition(active) == (True, 0)

    monkeypatch.setattr(compose_mod.time, "time", lambda: 1_029.0)
    assert compose_mod.check_beat_transition(active) == (False, 0)

    monkeypatch.setattr(compose_mod.time, "time", lambda: 1_031.0)
    assert compose_mod.check_beat_transition(active) == (True, 1)

    monkeypatch.setattr(compose_mod.time, "time", lambda: 1_074.0)
    assert compose_mod.check_beat_transition(active) == (False, 1)

    monkeypatch.setattr(compose_mod.time, "time", lambda: 1_076.0)
    assert compose_mod.check_beat_transition(active) == (True, 2)
