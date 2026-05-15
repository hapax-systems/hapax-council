"""End-to-end emission tests for ``structural_intent`` (HOMAGE Phase B0).

Pins the narrative-tier structural-intent write path from the director's
LLM response through to the JSONL observability log + the compositor SHM
files.

Motivation — `docs/research/2026-04-19-expert-system-blinding-audit.md`
§5.1 and `docs/research/2026-04-19-blinding-defaults-audit.md` §3
(ceremonial-defaults-2): the last 994 records in
``~/hapax-state/stream-experiment/director-intent.jsonl`` carried no
``structural_intent`` key at all, and
``/dev/shm/hapax-compositor/narrative-structural-intent.json`` was hours
stale. These tests pin:

1. The LLM's full-shape JSON payload with a populated ``structural_intent``
   round-trips through ``_parse_intent_from_llm`` without the field being
   dropped (parser correctness).
2. ``_emit_intent_artifacts`` writes the populated ``structural_intent``
   as an explicit key in the director-intent.jsonl record (serializer
   correctness via ``model_dump_for_jsonl``).
3. Even when the LLM omits ``structural_intent`` entirely, the Pydantic
   default container still serializes as a concrete object in JSONL — so
   researchers can always distinguish "LLM did not emit" from "writer
   dropped the key".
4. ``dispatch_structural_intent`` updates
   ``/dev/shm/hapax-compositor/narrative-structural-intent.json`` on
   every call, regardless of whether the LLM chose an explicit
   rotation-mode override. Previously the SHM write was gated on a valid
   ``homage_rotation_mode`` string, which left the file hours stale
   whenever the LLM emitted structural_intent without a rotation choice
   — the choreographer's narrative-tier freshness window treated that
   gap as "director is silent".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.studio_compositor import compositional_consumer as cc
from agents.studio_compositor import director_loop as dl
from shared.director_intent import (
    CompositionalImpingement,
    DirectorIntent,
    NarrativeStructuralIntent,
)
from shared.stimmung import Stance


def _populated_llm_payload() -> str:
    """Full-shape LLM JSON with a non-empty ``structural_intent``."""
    return json.dumps(
        {
            "activity": "music",
            "stance": "nominal",
            "narrative_text": "the record keeps going",
            "grounding_provenance": ["album.artist"],
            "compositional_impingements": [
                {
                    "narrative": "turntable focus",
                    "intent_family": "camera.hero",
                    "material": "water",
                    "salience": 0.7,
                    "grounding_provenance": ["visual.overhead_hand_zones.turntable"],
                }
            ],
            "structural_intent": {
                "homage_rotation_mode": "weighted_by_salience",
                "ward_emphasis": ["album_overlay", "vinyl_platter"],
                "ward_dispatch": [],
                "ward_retire": [],
                "placement_bias": {"album_overlay": "scale_1.15x"},
            },
        }
    )


def _populated_intent() -> DirectorIntent:
    """Construct a DirectorIntent directly with a populated structural_intent."""
    return DirectorIntent(
        activity="music",  # type: ignore[arg-type]
        stance=Stance.NOMINAL,
        narrative_text="the record keeps going",
        grounding_provenance=["album.artist"],
        compositional_impingements=[
            CompositionalImpingement(
                narrative="turntable focus",
                intent_family="camera.hero",
                material="water",
                salience=0.7,
                grounding_provenance=["visual.overhead_hand_zones.turntable"],
            )
        ],
        structural_intent=NarrativeStructuralIntent(
            homage_rotation_mode="weighted_by_salience",
            ward_emphasis=["album_overlay", "vinyl_platter"],
            placement_bias={"album_overlay": "scale_1.15x"},
        ),
    )


class TestParserPreservesStructuralIntent:
    """The LLM → DirectorIntent parser must preserve a populated
    ``structural_intent`` block without silently stripping it."""

    def test_full_shape_populates_structural_intent(self) -> None:
        intent = dl._parse_intent_from_llm(_populated_llm_payload())
        assert intent.structural_intent.homage_rotation_mode == "weighted_by_salience"
        assert intent.structural_intent.ward_emphasis == ["album_overlay", "vinyl_platter"]
        assert intent.structural_intent.placement_bias == {"album_overlay": "scale_1.15x"}

    def test_full_shape_missing_structural_intent_defaults_container(self) -> None:
        """When the LLM emits the rich shape but omits structural_intent, the
        Pydantic default container is used. This is legitimate behavior;
        what matters is that the serializer still emits the KEY with its
        default values so researchers can tell 'LLM omitted' apart from
        'writer dropped' at the JSONL layer."""
        payload = json.dumps(
            {
                "activity": "music",
                "stance": "nominal",
                "narrative_text": "the record keeps going",
                "grounding_provenance": ["album.artist"],
                "compositional_impingements": [
                    {
                        "narrative": "turntable focus",
                        "intent_family": "camera.hero",
                        "material": "water",
                        "salience": 0.5,
                        "grounding_provenance": ["x"],
                    }
                ],
            }
        )
        intent = dl._parse_intent_from_llm(payload)
        assert intent.structural_intent is not None
        assert intent.structural_intent.homage_rotation_mode is None
        assert intent.structural_intent.ward_emphasis == []


class TestJsonlEmitsStructuralIntent:
    """``_emit_intent_artifacts`` must write ``structural_intent`` as a
    first-class JSONL key — the audit's headline failure was 994/994
    records missing the key entirely."""

    @pytest.fixture
    def tmp_paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        jsonl = tmp_path / "director-intent.jsonl"
        narrative_state = tmp_path / "narrative-state.json"
        monkeypatch.setattr(dl, "_DIRECTOR_INTENT_JSONL", jsonl)
        monkeypatch.setattr(dl, "_NARRATIVE_STATE_PATH", narrative_state)
        # Prevent the DMN impingement-stream side-effect from polluting
        # /dev/shm during tests.
        monkeypatch.setattr(dl, "_DMN_IMPINGEMENTS_FILE", tmp_path / "dmn-impingements.jsonl")
        return jsonl

    def test_populated_structural_intent_lands_in_jsonl(self, tmp_paths: Path) -> None:
        intent = _populated_intent()
        dl._emit_intent_artifacts(intent, condition_id="cond-si-001")
        line = tmp_paths.read_text().strip()
        payload = json.loads(line)
        assert "structural_intent" in payload, (
            "structural_intent MUST be a first-class JSONL key "
            "(HOMAGE Phase B0: audit found 994/994 records missing it)"
        )
        si = payload["structural_intent"]
        assert si["homage_rotation_mode"] == "weighted_by_salience"
        assert si["ward_emphasis"] == ["album_overlay", "vinyl_platter"]
        assert si["placement_bias"] == {"album_overlay": "scale_1.15x"}

    def test_default_structural_intent_still_emits_key(self, tmp_paths: Path) -> None:
        """Even with the default empty container, the JSONL record must
        contain ``structural_intent`` as an explicit object — not a
        missing key. Researchers must be able to distinguish ``{}`` (LLM
        silent) from missing (writer dropped)."""
        intent = DirectorIntent(
            activity="observe",  # type: ignore[arg-type]
            stance=Stance.NOMINAL,
            narrative_text="no structural choice this tick",
            compositional_impingements=[
                CompositionalImpingement(
                    narrative="ambient hold",
                    intent_family="overlay.emphasis",
                    material="void",
                    salience=0.3,
                    grounding_provenance=["context.recent_reactions"],
                )
            ],
        )
        dl._emit_intent_artifacts(intent, condition_id="cond-si-002")
        payload = json.loads(tmp_paths.read_text().strip())
        assert "structural_intent" in payload
        si = payload["structural_intent"]
        # All fields present with their documented defaults.
        assert si["homage_rotation_mode"] is None
        assert si["ward_emphasis"] == []
        assert si["ward_dispatch"] == []
        assert si["ward_retire"] == []
        assert si["placement_bias"] == {}


class TestDispatchStructuralIntentShmWrite:
    """``dispatch_structural_intent`` must refresh
    ``narrative-structural-intent.json`` on every call — the audit found
    the file hours stale because the SHM write was gated on a valid
    rotation_mode string."""

    @pytest.fixture
    def shm_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        path = tmp_path / "narrative-structural-intent.json"
        # The function hard-codes the SHM path; redirect its I/O by
        # monkeypatching the Path class used inside dispatch_structural_intent
        # through the _atomic_write_json it reaches for. Easier: patch
        # the module's Path reference via a targeted replacement.
        original_atomic = cc._atomic_write_json
        captures: dict[str, dict] = {}

        def _capture_write(target: Path, payload: dict) -> None:
            # Redirect the narrative-structural-intent.json write into tmp_path
            # while letting every other caller (ward-properties, homage-pending)
            # behave normally.
            if str(target).endswith("narrative-structural-intent.json"):
                captures["shm"] = payload
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload), encoding="utf-8")
                return
            original_atomic(target, payload)

        monkeypatch.setattr(cc, "_atomic_write_json", _capture_write)
        # Also block the ward_properties writer to keep test side-effect-free.
        import agents.studio_compositor.ward_properties as wp

        monkeypatch.setattr(wp, "WARD_PROPERTIES_PATH", tmp_path / "ward-properties.json")
        monkeypatch.setattr(cc, "_SEGMENT_CUE_HOLD", tmp_path / "segment-cue-hold.json")
        monkeypatch.setattr(cc, "_ACTION_RECEIPTS_JSONL", tmp_path / "action-receipts.jsonl")
        return path

    def test_shm_written_when_rotation_mode_set(self, shm_path: Path) -> None:
        si = NarrativeStructuralIntent(
            homage_rotation_mode="weighted_by_salience",
            ward_emphasis=["album_overlay"],
        )
        cc.dispatch_structural_intent(si)
        assert shm_path.exists()
        payload = json.loads(shm_path.read_text())
        assert payload["homage_rotation_mode"] == "weighted_by_salience"
        assert isinstance(payload["updated_at"], (int, float))

    def test_shm_written_even_when_rotation_mode_none(self, shm_path: Path) -> None:
        """Regression pin for blinding-defaults-audit §3 /
        expert-system-blinding-audit §5.1. The SHM write MUST NOT be
        gated on a valid rotation_mode — the file's mtime is the
        choreographer's narrative-tier freshness signal, and gating the
        write makes "no explicit override" indistinguishable from
        "director stopped running" at the freshness layer."""
        si = NarrativeStructuralIntent(
            homage_rotation_mode=None,
            ward_emphasis=["album_overlay"],
        )
        cc.dispatch_structural_intent(si)
        assert shm_path.exists(), (
            "SHM file must update every tick — not only when rotation_mode is an explicit override"
        )
        payload = json.loads(shm_path.read_text())
        assert payload["homage_rotation_mode"] is None
        assert isinstance(payload["updated_at"], (int, float))

    def test_shm_written_even_when_structural_intent_empty(self, shm_path: Path) -> None:
        """Full default container — no rotation mode, no wards — still
        refreshes the SHM heartbeat."""
        cc.dispatch_structural_intent(NarrativeStructuralIntent())
        assert shm_path.exists()
        payload = json.loads(shm_path.read_text())
        assert payload["homage_rotation_mode"] is None

    def test_shm_normalizes_invalid_rotation_mode_to_none(self, shm_path: Path) -> None:
        """Unknown mode values still refresh the file with rotation_mode=None
        so the choreographer falls through to the structural tier rather
        than ever reading an out-of-alphabet mode literal."""
        cc.dispatch_structural_intent({"homage_rotation_mode": "bogus"})
        assert shm_path.exists()
        payload = json.loads(shm_path.read_text())
        assert payload["homage_rotation_mode"] is None


class TestEndToEndEmission:
    """LLM response string → DirectorIntent → JSONL + SHM, with every
    intermediate preserving the structural_intent data."""

    @pytest.fixture
    def wired(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
        jsonl = tmp_path / "director-intent.jsonl"
        shm = tmp_path / "narrative-structural-intent.json"
        monkeypatch.setattr(dl, "_DIRECTOR_INTENT_JSONL", jsonl)
        monkeypatch.setattr(dl, "_NARRATIVE_STATE_PATH", tmp_path / "narrative-state.json")
        monkeypatch.setattr(dl, "_DMN_IMPINGEMENTS_FILE", tmp_path / "dmn-impingements.jsonl")
        import agents.studio_compositor.ward_properties as wp

        monkeypatch.setattr(wp, "WARD_PROPERTIES_PATH", tmp_path / "ward-properties.json")

        original_atomic = cc._atomic_write_json

        def _capture_write(target: Path, payload: dict) -> None:
            if str(target).endswith("narrative-structural-intent.json"):
                shm.parent.mkdir(parents=True, exist_ok=True)
                shm.write_text(json.dumps(payload), encoding="utf-8")
                return
            original_atomic(target, payload)

        monkeypatch.setattr(cc, "_atomic_write_json", _capture_write)
        monkeypatch.setattr(cc, "_SEGMENT_CUE_HOLD", tmp_path / "segment-cue-hold.json")
        monkeypatch.setattr(cc, "_ACTION_RECEIPTS_JSONL", tmp_path / "action-receipts.jsonl")
        return {"jsonl": jsonl, "shm": shm}

    def test_full_round_trip(self, wired: dict[str, Path]) -> None:
        # LLM emits a populated rich-shape JSON.
        raw = _populated_llm_payload()
        intent = dl._parse_intent_from_llm(raw)
        dl._emit_intent_artifacts(intent, condition_id="end2end-001")

        # JSONL contains structural_intent with the LLM-provided values.
        jsonl_payload = json.loads(wired["jsonl"].read_text().strip())
        assert "structural_intent" in jsonl_payload
        si_jsonl = jsonl_payload["structural_intent"]
        assert si_jsonl["homage_rotation_mode"] == "weighted_by_salience"
        assert si_jsonl["ward_emphasis"] == ["album_overlay", "vinyl_platter"]

        # SHM file got refreshed with the LLM's rotation-mode choice.
        shm_payload = json.loads(wired["shm"].read_text())
        assert shm_payload["homage_rotation_mode"] == "weighted_by_salience"
