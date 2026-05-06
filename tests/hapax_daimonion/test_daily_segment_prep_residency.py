from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agents.hapax_daimonion import daily_segment_prep as prep


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = json.dumps(payload).encode()

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def test_prep_model_is_command_r_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HAPAX_SEGMENT_PREP_MODEL", raising=False)
    assert prep._prep_model() == prep.RESIDENT_PREP_MODEL

    monkeypatch.setenv("HAPAX_SEGMENT_PREP_MODEL", "not-command-r")
    with pytest.raises(RuntimeError, match="resident Command-R"):
        prep._prep_model()


def test_prep_llm_timeout_preserves_long_resident_generation() -> None:
    assert prep._PREP_LLM_TIMEOUT_S >= 900


def test_daily_prep_source_has_no_model_swap_or_fallback_paths() -> None:
    source = Path(prep.__file__).read_text(encoding="utf-8")
    forbidden = [
        "/v1/model/load",
        "/v1/model/unload",
        "_swap_tabby_model",
        "qwen",
        "HAPAX_LITELLM_URL",
        "chat_template_kwargs",
        "enable_thinking",
    ]
    source_lower = source.lower()
    for item in forbidden:
        assert item.lower() not in source_lower


def test_content_programming_sources_share_resident_command_r_route() -> None:
    checked_paths = [
        Path("agents/programme_manager/planner.py"),
        Path("agents/hapax_daimonion/autonomous_narrative/compose.py"),
        Path("agents/metadata_composer/composer.py"),
    ]
    forbidden_active_paths = [
        "import litellm",
        "litellm.completion",
        "HAPAX_LITELLM",
        "MODELS['local-fast']",
        'MODELS["local-fast"]',
        "MODELS['balanced']",
        'MODELS["balanced"]',
        "openai/{MODELS",
        "chat_template_kwargs",
        "enable_thinking",
        "/v1/model/load",
        "/v1/model/unload",
        "Qwen3.",
    ]

    for path in checked_paths:
        source = path.read_text(encoding="utf-8")
        assert "call_resident_command_r" in source
        for item in forbidden_active_paths:
            assert item not in source

    metadata_source = Path("agents/metadata_composer/composer.py").read_text(encoding="utf-8")
    assert "_call_llm_balanced" not in metadata_source


def test_batch_prep_script_has_no_model_or_service_swap_paths() -> None:
    source = Path("scripts/batch_prep_segments.sh").read_text(encoding="utf-8")
    forbidden = [
        "/v1/model/load",
        "/v1/model/unload",
        "restart_tabby",
        "pkill",
        "fuser",
        "docker pause",
        "systemctl --user stop",
        "qwen",
    ]
    source_lower = source.lower()
    for item in forbidden:
        assert item.lower() not in source_lower
    assert f'RESIDENT_PREP_MODEL="{prep.RESIDENT_PREP_MODEL}"' in source


def test_call_llm_refuses_wrong_resident_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        url = getattr(req, "full_url", str(req))
        if url.endswith("/v1/model"):
            return _FakeResponse({"id": "wrong-model"})
        raise AssertionError("chat endpoint should not be called on residency mismatch")

    monkeypatch.delenv("HAPAX_SEGMENT_PREP_MODEL", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="already serving"):
        prep._call_llm("hello")


def test_call_llm_uses_resident_command_r_body_and_records_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bodies: list[dict[str, Any]] = []
    chat_timeouts: list[float] = []

    def fake_urlopen(req: Any, timeout: float) -> _FakeResponse:
        url = getattr(req, "full_url", str(req))
        if url.endswith("/v1/model"):
            return _FakeResponse({"id": prep.RESIDENT_PREP_MODEL})
        chat_timeouts.append(timeout)
        bodies.append(json.loads(req.data.decode()))
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.delenv("HAPAX_SEGMENT_PREP_MODEL", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    session = prep._new_prep_session()
    assert (
        prep._call_llm(
            "hello",
            prep_session=session,
            phase="compose",
            programme_id="prog-1",
            max_tokens=77,
        )
        == "ok"
    )

    assert bodies == [
        {
            "model": prep.RESIDENT_PREP_MODEL,
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 77,
            "temperature": 0.7,
        }
    ]
    assert chat_timeouts == [prep._PREP_LLM_TIMEOUT_S]
    assert session["llm_calls"] == [
        {
            "call_index": 1,
            "phase": "compose",
            "programme_id": "prog-1",
            "model_id": prep.RESIDENT_PREP_MODEL,
            "prompt_sha256": prep._sha256_text("hello"),
            "prompt_chars": 5,
            "called_at": session["llm_calls"][0]["called_at"],
        }
    ]


def _valid_artifact(**overrides: Any) -> dict[str, Any]:
    prompt_sha256 = prep._sha256_text("prompt")
    seed_sha256 = prep._sha256_text("seed")
    segment_beats = ["Beat one"]
    prepared_script = ["Place Test item in S-tier because the ranking makes the claim visible."]
    actionability = prep.validate_segment_actionability(prepared_script, segment_beats)
    layout = prep.validate_layout_responsibility(actionability["beat_action_intents"])
    source_hashes = prep._source_hashes_from_fields(
        programme_id="prog-1",
        role="rant",
        topic="Test topic",
        segment_beats=segment_beats,
        seed_sha256=seed_sha256,
        prompt_sha256=prompt_sha256,
    )
    payload: dict[str, Any] = {
        "schema_version": prep.PREP_ARTIFACT_SCHEMA_VERSION,
        "authority": prep.PREP_ARTIFACT_AUTHORITY,
        "programme_id": "prog-1",
        "role": "rant",
        "topic": "Test topic",
        "segment_beats": segment_beats,
        "prepared_script": prepared_script,
        "segment_quality_rubric_version": prep.QUALITY_RUBRIC_VERSION,
        "actionability_rubric_version": prep.ACTIONABILITY_RUBRIC_VERSION,
        "layout_responsibility_version": prep.LAYOUT_RESPONSIBILITY_VERSION,
        "hosting_context": layout["hosting_context"],
        "segment_quality_report": prep.score_segment_quality(prepared_script, segment_beats),
        "beat_action_intents": actionability["beat_action_intents"],
        "actionability_alignment": {
            "ok": actionability["ok"],
            "removed_unsupported_action_lines": actionability["removed_unsupported_action_lines"],
        },
        "beat_layout_intents": layout["beat_layout_intents"],
        "layout_decision_contract": layout["layout_decision_contract"],
        "runtime_layout_validation": layout["runtime_layout_validation"],
        "layout_decision_receipts": layout["layout_decision_receipts"],
        "prepped_at": "2026-05-05T00:00:00+00:00",
        "prep_session_id": "segment-prep-test",
        "model_id": prep.RESIDENT_PREP_MODEL,
        "prompt_sha256": prompt_sha256,
        "seed_sha256": seed_sha256,
        "source_hashes": source_hashes,
        "source_provenance_sha256": prep._sha256_json(source_hashes),
        "llm_calls": [
            {
                "call_index": 1,
                "phase": "compose",
                "programme_id": "prog-1",
                "model_id": prep.RESIDENT_PREP_MODEL,
                "prompt_sha256": prompt_sha256,
                "prompt_chars": 123,
                "called_at": "2026-05-05T00:00:00+00:00",
            }
        ],
        "beat_count": 1,
        "avg_chars_per_beat": len(prepared_script[0]),
        "refinement_applied": True,
    }
    payload.update(overrides)
    payload["artifact_sha256"] = prep._artifact_hash(payload)
    return payload


def _valid_artifact_for(
    programme_id: str,
    *,
    topic: str | None = None,
    segment_beats: list[str] | None = None,
    prepared_script: list[str] | None = None,
) -> dict[str, Any]:
    topic = topic or f"Topic for {programme_id}"
    segment_beats = segment_beats or ["Beat one"]
    prepared_script = prepared_script or [
        f"Place {programme_id} in S-tier because the ranking makes the claim visible."
    ]
    payload = _valid_artifact(
        programme_id=programme_id,
        topic=topic,
        segment_beats=segment_beats,
        prepared_script=prepared_script,
    )
    actionability = prep.validate_segment_actionability(prepared_script, segment_beats)
    layout = prep.validate_layout_responsibility(actionability["beat_action_intents"])
    source_hashes = prep._source_hashes_from_fields(
        programme_id=programme_id,
        role=str(payload["role"]),
        topic=topic,
        segment_beats=segment_beats,
        seed_sha256=str(payload["seed_sha256"]),
        prompt_sha256=str(payload["prompt_sha256"]),
    )
    payload["beat_action_intents"] = actionability["beat_action_intents"]
    payload["actionability_alignment"] = {
        "ok": actionability["ok"],
        "removed_unsupported_action_lines": actionability["removed_unsupported_action_lines"],
    }
    payload["beat_layout_intents"] = layout["beat_layout_intents"]
    payload["layout_decision_contract"] = layout["layout_decision_contract"]
    payload["runtime_layout_validation"] = layout["runtime_layout_validation"]
    payload["layout_decision_receipts"] = layout["layout_decision_receipts"]
    payload["source_hashes"] = source_hashes
    payload["source_provenance_sha256"] = prep._sha256_json(source_hashes)
    payload["llm_calls"][0]["programme_id"] = programme_id
    payload["beat_count"] = len(segment_beats)
    payload["avg_chars_per_beat"] = round(
        sum(len(item) for item in prepared_script) / max(len(prepared_script), 1)
    )
    payload["artifact_sha256"] = prep._artifact_hash(payload)
    return payload


def _write_artifact(base: Path, payload: dict[str, Any], *, manifest: bool = True) -> Path:
    today = prep._today_dir(base)
    path = today / "prog-1.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    if manifest:
        (today / "manifest.json").write_text(
            json.dumps({"programmes": [path.name]}),
            encoding="utf-8",
        )
    return path


def test_load_prepped_programmes_accepts_valid_provenance(tmp_path: Path) -> None:
    _write_artifact(tmp_path, _valid_artifact())

    loaded = prep.load_prepped_programmes(tmp_path)

    assert len(loaded) == 1
    assert loaded[0]["programme_id"] == "prog-1"
    assert loaded[0]["accepted"] is True
    assert loaded[0]["acceptance_gate"] == "daily_segment_prep.load_prepped_programmes"


def test_load_prepped_programmes_rejects_old_actionability_semantics(tmp_path: Path) -> None:
    payload = _valid_artifact()
    payload["actionability_rubric_version"] = prep.ACTIONABILITY_RUBRIC_VERSION - 1
    path = tmp_path / "prog-1.json"

    assert (
        prep._artifact_rejection_reason(
            payload,
            path=path,
            manifest_programmes={path.name},
        )
        == "unsupported actionability rubric"
    )


@pytest.mark.parametrize(
    ("payload", "manifest"),
    [
        (_valid_artifact(model_id="wrong-model"), True),
        (_valid_artifact(prep_session_id=""), True),
        (_valid_artifact(llm_calls=[]), True),
        (
            _valid_artifact(
                llm_calls=[
                    {
                        "call_index": 2,
                        "phase": "compose",
                        "programme_id": "prog-1",
                        "model_id": prep.RESIDENT_PREP_MODEL,
                        "prompt_sha256": prep._sha256_text("prompt"),
                        "called_at": "2026-05-05T00:00:00+00:00",
                    },
                    {
                        "call_index": 1,
                        "phase": "refine",
                        "programme_id": "prog-1",
                        "model_id": prep.RESIDENT_PREP_MODEL,
                        "prompt_sha256": prep._sha256_text("refine prompt"),
                        "called_at": "2026-05-05T00:01:00+00:00",
                    },
                ]
            ),
            True,
        ),
        (_valid_artifact(source_hashes={}), True),
        (_valid_artifact(topic="Tampered topic"), True),
        (_valid_artifact(prepared_script=[]), True),
        (_valid_artifact(beat_layout_intents=[]), True),
        (_valid_artifact(layout_name="default"), True),
        (
            _valid_artifact(
                runtime_layout_validation={
                    "status": "complete",
                    "layout_success": True,
                }
            ),
            True,
        ),
        (_valid_artifact(), False),
    ],
)
def test_load_prepped_programmes_rejects_invalid_provenance(
    tmp_path: Path,
    payload: dict[str, Any],
    manifest: bool,
) -> None:
    _write_artifact(tmp_path, payload, manifest=manifest)

    assert prep.load_prepped_programmes(tmp_path) == []


def test_load_prepped_programmes_rejects_layout_responsibility_failure(
    tmp_path: Path,
) -> None:
    payload = _valid_artifact()
    payload["runtime_layout_validation"]["ok"] = False
    payload["runtime_layout_validation"]["violations"] = [
        {"reason": "unsupported_layout_need", "beat_index": 0}
    ]
    payload["artifact_sha256"] = prep._artifact_hash(payload)
    _write_artifact(tmp_path, payload)

    assert prep.load_prepped_programmes(tmp_path) == []


def test_load_prepped_programmes_rejects_hash_mismatch(tmp_path: Path) -> None:
    payload = _valid_artifact()
    payload["prepared_script"] = ["Tampered."]
    _write_artifact(tmp_path, payload)

    assert prep.load_prepped_programmes(tmp_path) == []


def test_load_prepped_programmes_rejects_stale_declared_action_intents(
    tmp_path: Path,
) -> None:
    payload = _valid_artifact()
    payload["beat_action_intents"][0]["intents"].append(
        {
            "kind": "chat_poll",
            "expected_effect": "chat.poll.requested",
            "target": "chat",
            "evidence_ref": "beat:0:intent:chat_poll",
        }
    )
    payload["artifact_sha256"] = prep._artifact_hash(payload)
    _write_artifact(tmp_path, payload)

    assert prep.load_prepped_programmes(tmp_path) == []


def test_run_prep_appends_manifest_without_readmitting_invalid_or_unlisted_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import agents.programme_manager.planner as planner_module

    today = prep._today_dir(tmp_path)
    existing_path = today / "prog-1.json"
    invalid_path = today / "prog-invalid.json"
    unlisted_path = today / "prog-unlisted.json"
    quarantine_path = today / "prog-quarantine.actionability-invalid.json"
    existing_path.write_text(json.dumps(_valid_artifact_for("prog-1")), encoding="utf-8")
    invalid_payload = _valid_artifact_for("prog-invalid")
    invalid_payload["model_id"] = "wrong-model"
    invalid_payload["artifact_sha256"] = prep._artifact_hash(invalid_payload)
    invalid_path.write_text(json.dumps(invalid_payload), encoding="utf-8")
    unlisted_path.write_text(json.dumps(_valid_artifact_for("prog-unlisted")), encoding="utf-8")
    quarantine_path.write_text(
        json.dumps({"not_loadable_reason": "actionability alignment failed"}),
        encoding="utf-8",
    )
    (today / "manifest.json").write_text(
        json.dumps(
            {
                "programmes": [
                    existing_path.name,
                    invalid_path.name,
                    quarantine_path.name,
                ]
            }
        ),
        encoding="utf-8",
    )

    planned_programmes = [
        SimpleNamespace(
            programme_id="prog-2",
            role=SimpleNamespace(value="rant"),
            content=SimpleNamespace(
                narrative_beat="Second accepted topic",
                segment_beats=["Second beat"],
            ),
        ),
        SimpleNamespace(
            programme_id="prog-3",
            role=SimpleNamespace(value="rant"),
            content=SimpleNamespace(
                narrative_beat="Third accepted topic",
                segment_beats=["Third beat"],
            ),
        ),
    ]

    class FakePlanner:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def plan(self, *, show_id: str) -> SimpleNamespace:  # noqa: ARG002
            return SimpleNamespace(programmes=planned_programmes)

    def fake_prep_segment(
        programme: SimpleNamespace,
        prep_dir: Path,
        *,
        prep_session: dict[str, Any],
    ) -> Path:
        path = prep_dir / f"{programme.programme_id}.json"
        payload = _valid_artifact_for(
            programme.programme_id,
            topic=programme.content.narrative_beat,
            segment_beats=list(programme.content.segment_beats),
        )
        payload["prep_session_id"] = prep_session["prep_session_id"]
        payload["model_id"] = prep_session["model_id"]
        payload["llm_calls"][0]["model_id"] = prep_session["model_id"]
        payload["artifact_sha256"] = prep._artifact_hash(payload)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    monkeypatch.setattr(prep, "MAX_SEGMENTS", 2)
    monkeypatch.setattr(
        prep,
        "_new_prep_session",
        lambda: {
            "prep_session_id": "segment-prep-new",
            "model_id": prep.RESIDENT_PREP_MODEL,
            "llm_calls": [],
        },
    )
    monkeypatch.setattr(prep, "_assert_resident_prep_model", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(planner_module, "ProgrammePlanner", FakePlanner)
    monkeypatch.setattr(prep, "prep_segment", fake_prep_segment)
    monkeypatch.setattr(prep, "_upsert_programmes_to_qdrant", lambda *_args, **_kwargs: None)

    saved = prep.run_prep(tmp_path)

    assert [path.name for path in saved] == ["prog-2.json", "prog-3.json"]
    manifest = json.loads((today / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["programmes"] == ["prog-1.json", "prog-2.json", "prog-3.json"]
    assert manifest["run_saved_programmes"] == ["prog-2.json", "prog-3.json"]
    assert [item["programme_id"] for item in prep.load_prepped_programmes(tmp_path)] == [
        "prog-1",
        "prog-2",
        "prog-3",
    ]


def test_prep_segment_quarantines_actionability_invalid_script(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    programme = SimpleNamespace(
        programme_id="prog-invalid-action",
        role=SimpleNamespace(value="tier_list"),
        content=SimpleNamespace(
            narrative_beat="Unsupported clip claim",
            segment_beats=["Make the claim without unsupported visuals"],
        ),
    )
    session = {
        "prep_session_id": "segment-prep-test",
        "model_id": prep.RESIDENT_PREP_MODEL,
        "llm_calls": [],
    }

    monkeypatch.setattr(prep, "_build_seed", lambda _programme: "seed")
    monkeypatch.setattr(
        prep,
        "_build_full_segment_prompt",
        lambda _programme, _seed: "prompt",
    )
    monkeypatch.setattr(
        prep,
        "_call_llm",
        lambda _prompt, **_kwargs: json.dumps(
            [
                "Show the clip on screen before ranking the evidence. "
                "The source only supports the narrow provenance claim."
            ]
        ),
    )
    monkeypatch.setattr(prep, "_refine_script", lambda script, _programme, **_kwargs: script)
    monkeypatch.setattr(prep, "_emit_self_evaluation", lambda *_args, **_kwargs: None)

    saved = prep.prep_segment(programme, tmp_path, prep_session=session)

    assert saved is None
    assert not (tmp_path / "prog-invalid-action.json").exists()
    diagnostic_path = tmp_path / "prog-invalid-action.actionability-invalid.json"
    assert diagnostic_path.exists()
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    assert diagnostic["not_loadable_reason"] == "actionability alignment failed"
    assert diagnostic["actionability_alignment"]["ok"] is False
    assert diagnostic["actionability_alignment"]["removed_unsupported_action_lines"]


def test_prep_segment_quarantines_responsible_spoken_only_script(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    programme = SimpleNamespace(
        programme_id="prog-spoken-only",
        role=SimpleNamespace(value="rant"),
        content=SimpleNamespace(
            narrative_beat="Spoken only argument",
            segment_beats=["argue the point without visible evidence"],
        ),
    )
    session = {
        "prep_session_id": "segment-prep-test",
        "model_id": prep.RESIDENT_PREP_MODEL,
        "llm_calls": [],
    }

    monkeypatch.setattr(prep, "_build_seed", lambda _programme: "seed")
    monkeypatch.setattr(
        prep,
        "_build_full_segment_prompt",
        lambda _programme, _seed: "prompt",
    )
    monkeypatch.setattr(
        prep,
        "_call_llm",
        lambda _prompt, **_kwargs: json.dumps(
            [
                "This beat makes a spoken argument about stream quality. "
                "It states a consequence, names a problem, and stays entirely in narration."
            ]
        ),
    )
    monkeypatch.setattr(prep, "_refine_script", lambda script, _programme, **_kwargs: script)
    monkeypatch.setattr(prep, "_emit_self_evaluation", lambda *_args, **_kwargs: None)

    saved = prep.prep_segment(programme, tmp_path, prep_session=session)

    assert saved is None
    assert not (tmp_path / "prog-spoken-only.json").exists()
    diagnostic_path = tmp_path / "prog-spoken-only.layout-invalid.json"
    assert diagnostic_path.exists()
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    assert diagnostic["not_loadable_reason"] == "layout responsibility failed"
    assert diagnostic["layout_responsibility"]["ok"] is False
    assert "unsupported_layout_need" in {
        item["reason"] for item in diagnostic["layout_responsibility"]["violations"]
    }


def test_prep_segment_rejects_unsafe_programme_id_before_writing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    programme = SimpleNamespace(
        programme_id="../escape",
        role=SimpleNamespace(value="tier_list"),
        content=SimpleNamespace(
            narrative_beat="Unsafe path",
            segment_beats=["This should not be composed"],
        ),
    )
    called = False

    def fail_if_called(*_args: Any, **_kwargs: Any) -> str:
        nonlocal called
        called = True
        return "[]"

    monkeypatch.setattr(prep, "_call_llm", fail_if_called)

    saved = prep.prep_segment(
        programme,
        tmp_path,
        prep_session={
            "prep_session_id": "segment-prep-test",
            "model_id": prep.RESIDENT_PREP_MODEL,
            "llm_calls": [],
        },
    )

    assert saved is None
    assert called is False
    assert not (tmp_path.parent / "escape.json").exists()


def test_load_prepped_programmes_rejects_programme_id_filename_mismatch(
    tmp_path: Path,
) -> None:
    payload = _valid_artifact_for("prog-safe")
    path = _write_artifact(tmp_path, payload)
    mismatch_path = path.with_name("prog-other.json")
    path.rename(mismatch_path)
    (path.parent / "manifest.json").write_text(
        json.dumps({"programmes": [mismatch_path.name]}),
        encoding="utf-8",
    )

    assert prep.load_prepped_programmes(tmp_path) == []


def test_qdrant_upsert_indexes_only_valid_saved_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import shared.affordance_pipeline as affordance_pipeline
    import shared.config as shared_config

    today = prep._today_dir(tmp_path)
    valid_path = today / "prog-1.json"
    invalid_path = today / "prog-2.json"
    valid_path.write_text(json.dumps(_valid_artifact(programme_id="prog-1")), encoding="utf-8")
    invalid_path.write_text(
        json.dumps(_valid_artifact(programme_id="prog-2", model_id="wrong-model")),
        encoding="utf-8",
    )
    (today / "manifest.json").write_text(
        json.dumps({"programmes": [valid_path.name, invalid_path.name]}),
        encoding="utf-8",
    )

    captured: dict[str, Any] = {}

    def fake_embed_batch(texts: list[str], *, prefix: str) -> list[list[float]]:
        captured["texts"] = texts
        captured["prefix"] = prefix
        return [[0.1, 0.2] for _ in texts]

    class FakeQdrant:
        def upsert(self, *, collection_name: str, points: list[Any]) -> None:
            captured["collection_name"] = collection_name
            captured["points"] = points

    monkeypatch.setattr(affordance_pipeline, "embed_batch_safe", fake_embed_batch)
    monkeypatch.setattr(shared_config, "get_qdrant", lambda: FakeQdrant())

    programmes = [
        SimpleNamespace(
            programme_id="prog-1",
            role=SimpleNamespace(value="rant"),
            content=SimpleNamespace(narrative_beat="Test topic", segment_beats=["Beat one"]),
        ),
        SimpleNamespace(
            programme_id="prog-2",
            role=SimpleNamespace(value="rant"),
            content=SimpleNamespace(narrative_beat="Bad topic", segment_beats=["Beat two"]),
        ),
    ]

    prep._upsert_programmes_to_qdrant(programmes, [valid_path, invalid_path])

    points = captured["points"]
    assert len(points) == 1
    payload = points[0].payload
    assert payload["programme_id"] == "prog-1"
    assert payload["accepted"] is True
    assert payload["authority"] == prep.PREP_ARTIFACT_AUTHORITY
    assert payload["artifact_path"] == str(valid_path)
    assert payload["source_provenance_sha256"]
    assert payload["hosting_context"] == prep.RESPONSIBLE_HOSTING_CONTEXT
    assert payload["beat_layout_intents"]
