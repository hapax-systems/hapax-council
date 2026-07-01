"""Phase-5c tests for StructuralDirector."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from agents.studio_compositor import structural_director as sd
from shared.action_receipt import ActionReceipt, ActionReceiptStatus
from shared.fix_capabilities.background_admission import BackgroundCapabilityAdmission


class _FakeResponse:
    def __init__(self, content: bytes) -> None:
        self._content = content

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._content


@pytest.fixture(autouse=True)
def _redirect_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(sd, "_STRUCTURAL_INTENT_PATH", tmp_path / "intent.json")
    monkeypatch.setattr(sd, "_STRUCTURAL_INTENT_JSONL", tmp_path / "structural-intent.jsonl")
    monkeypatch.setattr(sd, "_ACTION_RECEIPTS_JSONL", tmp_path / "action-receipts.jsonl")
    return tmp_path


class TestParseStructuralIntent:
    def test_full_shape_parses(self):
        raw = json.dumps(
            {
                "scene_mode": "hardware-play",
                "preset_family_hint": "audio-reactive",
                "long_horizon_direction": "the vinyl session is starting; sit with it for a while",
            }
        )
        intent = sd.parse_structural_intent(raw)
        assert intent is not None
        assert intent.scene_mode == "hardware-play"
        assert intent.preset_family_hint == "audio-reactive"
        assert "vinyl" in intent.long_horizon_direction

    def test_missing_field_returns_none(self):
        raw = json.dumps({"scene_mode": "hardware-play"})  # missing others
        assert sd.parse_structural_intent(raw) is None

    def test_unknown_scene_mode_rejected(self):
        raw = json.dumps(
            {
                "scene_mode": "bogus",
                "preset_family_hint": "audio-reactive",
                "long_horizon_direction": "x",
            }
        )
        assert sd.parse_structural_intent(raw) is None

    def test_empty_string_returns_none(self):
        assert sd.parse_structural_intent("") is None

    def test_non_json_returns_none(self):
        assert sd.parse_structural_intent("not json") is None


class TestTickOnce:
    def test_tick_writes_intent_file_and_jsonl(self, tmp_path):
        def stub_llm(prompt: str) -> str:
            return json.dumps(
                {
                    "scene_mode": "hardware-play",
                    "preset_family_hint": "audio-reactive",
                    "long_horizon_direction": "vinyl session",
                }
            )

        d = sd.StructuralDirector(llm_fn=stub_llm)
        out = d.tick_once()
        assert out is not None
        assert (tmp_path / "intent.json").exists()
        persisted = json.loads((tmp_path / "intent.json").read_text())
        assert persisted["scene_mode"] == "hardware-play"
        # JSONL also appended
        jsonl_lines = (tmp_path / "structural-intent.jsonl").read_text().splitlines()
        assert len(jsonl_lines) == 1
        receipt = ActionReceipt.model_validate_json(
            (tmp_path / "action-receipts.jsonl").read_text().splitlines()[0]
        )
        assert receipt.request_id.startswith("structural-director:")
        assert receipt.status is ActionReceiptStatus.APPLIED
        assert receipt.structural_reflex is True
        assert receipt.learning_update_allowed is False
        assert receipt.can_support_affordance_success() is False

    def test_publish_failure_emits_error_receipt(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sd, "_STRUCTURAL_INTENT_PATH", tmp_path)

        def stub_llm(prompt: str) -> str:
            return json.dumps(
                {
                    "scene_mode": "hardware-play",
                    "preset_family_hint": "audio-reactive",
                    "long_horizon_direction": "vinyl session",
                }
            )

        d = sd.StructuralDirector(llm_fn=stub_llm)
        assert d.tick_once() is not None
        receipt = ActionReceipt.model_validate_json(
            (tmp_path / "action-receipts.jsonl").read_text().splitlines()[0]
        )
        assert receipt.status is ActionReceiptStatus.ERROR
        assert "structural_intent_publish_failed" in receipt.error_refs
        assert receipt.applied_refs == []


class TestDefaultLlmBackpressure:
    def test_default_llm_skips_when_local_route_lock_is_held(self):
        import agents.studio_compositor.director_loop as dl_mod

        assert dl_mod._DIRECTOR_LLM_LOCK.acquire(blocking=False)
        try:
            with patch("subprocess.run") as mock_pass:
                with patch("urllib.request.urlopen") as mock_urlopen:
                    assert sd._default_llm_fn("prompt") == ""
        finally:
            dl_mod._DIRECTOR_LLM_LOCK.release()

        mock_pass.assert_not_called()
        mock_urlopen.assert_not_called()

    def test_default_llm_refuses_when_background_admission_denies(self, monkeypatch):
        import agents.studio_compositor.director_loop as dl_mod

        monkeypatch.setattr(
            sd,
            "_admit_structural_llm",
            lambda _model: BackgroundCapabilityAdmission(
                capability_name="studio.structural_director.llm",
                route_id="local_tool.local.worker",
                model_alias="command-r-08-2024",
                admitted=False,
                denied_reason="test_denied",
                reason_codes=("test_denied",),
                mutation_surface="none",
                quality_floor="deterministic_ok",
            ),
        )

        with patch("subprocess.run") as mock_pass:
            with patch("urllib.request.urlopen") as mock_urlopen:
                assert sd._default_llm_fn("prompt") == ""

        mock_pass.assert_not_called()
        mock_urlopen.assert_not_called()
        assert dl_mod._DIRECTOR_LLM_LOCK.acquire(blocking=False)
        dl_mod._DIRECTOR_LLM_LOCK.release()

    def test_default_llm_sends_resolved_provider_gateway_model(self, monkeypatch):
        monkeypatch.setenv(sd.STRUCTURAL_MODEL_ENV, "fast")
        monkeypatch.setattr(
            sd,
            "_admit_structural_llm",
            lambda _model: BackgroundCapabilityAdmission(
                capability_name="studio.structural_director.llm",
                route_id="api.headless.provider_gateway",
                model_alias="gemini-flash",
                admitted=True,
                mutation_surface="provider_spend",
                quality_floor="frontier_required",
            ),
        )
        response = _FakeResponse(b'{"choices":[{"message":{"content":"ok"}}]}')
        with patch("subprocess.run") as mock_pass:
            mock_pass.return_value.stdout = "test-key\n"
            with patch("urllib.request.urlopen", return_value=response) as mock_urlopen:
                assert sd._default_llm_fn("prompt") == "ok"

        mock_urlopen.assert_called_once()
        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode())
        assert payload["model"] == "gemini-flash"
        assert payload["model"] != "fast"

    def test_structural_route_model_mismatch_denies_without_policy_call(self, monkeypatch):
        monkeypatch.setenv("HAPAX_STRUCTURAL_LLM_ROUTE_ID", "local_tool.local.worker")

        with patch(
            "agents.studio_compositor.structural_director.admit_background_capability"
        ) as gate:
            admission = sd._admit_structural_llm("balanced")

        gate.assert_not_called()
        assert admission.admitted is False
        assert admission.reason_codes == ("structural_route_model_mismatch",)
        assert "expected_route=api.headless.provider_gateway" in (admission.denied_reason or "")

    def test_default_llm_timeout_releases_local_route_lock(self, monkeypatch):
        import agents.studio_compositor.director_loop as dl_mod

        monkeypatch.setattr(
            sd,
            "_admit_structural_llm",
            lambda _model: BackgroundCapabilityAdmission(
                capability_name="studio.structural_director.llm",
                route_id="local_tool.local.worker",
                model_alias="command-r-08-2024",
                admitted=True,
                mutation_surface="none",
                quality_floor="deterministic_ok",
            ),
        )
        with patch("subprocess.run") as mock_pass:
            mock_pass.return_value.stdout = "test-key\n"
            with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
                with pytest.raises(TimeoutError):
                    sd._default_llm_fn("prompt")

        assert dl_mod._DIRECTOR_LLM_LOCK.acquire(blocking=False)
        dl_mod._DIRECTOR_LLM_LOCK.release()

    def test_structural_local_alias_resolves_to_registered_leaf(self, monkeypatch):
        monkeypatch.delenv(sd.STRUCTURAL_LLM_ROUTE_ID_ENV, raising=False)
        with patch(
            "agents.studio_compositor.structural_director.admit_background_capability"
        ) as gate:
            gate.return_value = BackgroundCapabilityAdmission(
                capability_name="studio.structural_director.llm",
                route_id="local_tool.local.worker",
                model_alias="command-r-08-2024",
                admitted=True,
                mutation_surface="none",
                quality_floor="deterministic_ok",
            )
            admission = sd._admit_structural_llm("local-fast")

        assert admission.admitted is True
        kwargs = gate.call_args.kwargs
        assert kwargs["route_id"] == "local_tool.local.worker"
        assert kwargs["model_alias"] == "command-r-08-2024"
        assert kwargs["mutation_surface"] == "none"
        assert kwargs["quality_floor"] == "deterministic_ok"

    def test_tick_once_catches_default_llm_timeout(self):
        director = sd.StructuralDirector(
            llm_fn=lambda _prompt: (_ for _ in ()).throw(TimeoutError("timed out"))
        )

        assert director.tick_once() is None

    def test_fallback_structural_request_ids_are_distinct(self, tmp_path):
        def stub_llm(prompt: str) -> str:
            return json.dumps(
                {
                    "scene_mode": "hardware-play",
                    "preset_family_hint": "audio-reactive",
                    "long_horizon_direction": "vinyl session",
                }
            )

        d = sd.StructuralDirector(llm_fn=stub_llm)
        d.tick_once()
        d.tick_once()
        receipts = [
            ActionReceipt.model_validate_json(line)
            for line in (tmp_path / "action-receipts.jsonl").read_text().splitlines()
        ]
        assert len({receipt.request_id for receipt in receipts}) == 2
        assert len({receipt.receipt_id for receipt in receipts}) == 2

    def test_llm_failure_returns_none_and_keeps_prior(self, tmp_path):
        def failing_llm(prompt: str) -> str:
            raise RuntimeError("simulated LLM failure")

        d = sd.StructuralDirector(llm_fn=failing_llm)
        assert d.tick_once() is None
        # No intent file written
        assert not (tmp_path / "intent.json").exists()

    def test_unparseable_response_returns_none(self, tmp_path):
        def bad_llm(prompt: str) -> str:
            return "just some prose with no json"

        d = sd.StructuralDirector(llm_fn=bad_llm)
        assert d.tick_once() is None

    def test_multiple_ticks_accumulate_jsonl(self, tmp_path):
        calls = [
            json.dumps(
                {
                    "scene_mode": "hardware-play",
                    "preset_family_hint": "audio-reactive",
                    "long_horizon_direction": "vinyl",
                }
            ),
            json.dumps(
                {
                    "scene_mode": "idle-ambient",
                    "preset_family_hint": "calm-textural",
                    "long_horizon_direction": "operator stepped away",
                }
            ),
        ]
        idx = [0]

        def seq_llm(prompt: str) -> str:
            out = calls[idx[0]]
            idx[0] += 1
            return out

        d = sd.StructuralDirector(llm_fn=seq_llm)
        d.tick_once()
        d.tick_once()
        jsonl_lines = (tmp_path / "structural-intent.jsonl").read_text().splitlines()
        assert len(jsonl_lines) == 2

    def test_intent_carries_emitted_at_and_condition(self, tmp_path, monkeypatch):
        def stub_llm(prompt: str) -> str:
            return json.dumps(
                {
                    "scene_mode": "desk-work",
                    "preset_family_hint": "warm-minimal",
                    "long_horizon_direction": "focused writing block",
                }
            )

        # HOMAGE Phase C2 opened `cond-phase-a-homage-active-001` and writes
        # the SHM research-marker on a running system. Point the marker path
        # at a nonexistent file so this unit test exercises the fallback
        # rather than the live /dev/shm state.
        monkeypatch.setattr(sd, "_RESEARCH_MARKER_PATH", tmp_path / "no-research-marker.json")

        d = sd.StructuralDirector(llm_fn=stub_llm)
        out = d.tick_once()
        assert out is not None
        assert out.emitted_at > 0
        # condition_id falls back to "none" without a research-marker
        assert out.condition_id in ("none", "")
