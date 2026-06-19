from __future__ import annotations

import json
import threading
import time

import pytest

from shared.affordance_pipeline import AffordancePipeline
from shared.affordance_posterior_store import (
    POSTERIOR_OWNER_DRAIN_LOCK_TIMEOUT_ENV,
    POSTERIOR_UPDATE_LOCK_TIMEOUT_ENV,
    POSTERIOR_UPDATE_LOG_MAX_BYTES_ENV,
    PosteriorLockError,
    append_posterior_update,
    posterior_file_lock,
    posterior_update_log_path,
)


def test_invalid_posterior_mode_raises() -> None:
    with pytest.raises(ValueError, match="unknown posterior_mode"):
        AffordancePipeline(posterior_mode="writer")  # type: ignore[arg-type]


def test_local_mode_updates_private_state_without_journal(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "affordance-activation-state.json"
    monkeypatch.setattr("shared.affordance_pipeline.ACTIVATION_STATE_PATH", state_file)

    local = AffordancePipeline()
    local.record_outcome("speech_production", success=True, context={"mode": "rnd"})

    assert local._activation["speech_production"].use_count == 1
    assert local._context_associations[("rnd", "speech_production")] == 0.1
    assert not posterior_update_log_path(state_file).exists()


def test_reader_record_outcome_queues_without_private_activation_mutation(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "affordance-activation-state.json"
    monkeypatch.setattr("shared.affordance_pipeline.ACTIVATION_STATE_PATH", state_file)

    reader = AffordancePipeline(posterior_mode="reader", posterior_client_id="daimonion-test")
    reader.record_outcome("speech_production", success=True, context={"mode": "rnd"})

    assert "speech_production" not in reader._activation
    updates = posterior_update_log_path(state_file)
    lines = updates.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["kind"] == "record_outcome"
    assert event["source"] == "daimonion-test"
    assert event["capability_name"] == "speech_production"
    assert event["success"] is True
    assert event["context"] == {"mode": "rnd"}


def test_owner_drains_reader_updates_into_existing_posterior_shape(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "affordance-activation-state.json"
    monkeypatch.setattr("shared.affordance_pipeline.ACTIVATION_STATE_PATH", state_file)

    reader = AffordancePipeline(posterior_mode="reader", posterior_client_id="fortress-test")
    reader.record_outcome("fortress_governance", success=False, context={"source": "dmn"})

    owner = AffordancePipeline(posterior_mode="owner", posterior_client_id="reverie-test")
    owner.save_activation_state()

    data = json.loads(state_file.read_text(encoding="utf-8"))
    state = data["activations"]["fortress_governance"]
    assert state["use_count"] == 1
    assert state["ts_alpha"] >= 1.0
    assert state["ts_beta"] > 1.0
    assert data["associations"]["dmn|fortress_governance"] < 0.0
    assert posterior_update_log_path(state_file).read_text(encoding="utf-8") == ""


def test_reader_journaled_outcome_matches_local_update_math(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "affordance-activation-state.json"
    monkeypatch.setattr("shared.affordance_pipeline.ACTIVATION_STATE_PATH", state_file)

    local = AffordancePipeline()
    local.record_outcome("fortress_governance", success=False, context={"source": "dmn"})

    reader = AffordancePipeline(posterior_mode="reader", posterior_client_id="fortress-test")
    reader.record_outcome("fortress_governance", success=False, context={"source": "dmn"})
    owner = AffordancePipeline(posterior_mode="owner", posterior_client_id="reverie-test")
    owner.save_activation_state()

    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data == {
        "activations": {
            "fortress_governance": local._activation["fortress_governance"].model_dump()
        },
        "associations": {
            f"{cue}|{capability}": strength
            for (cue, capability), strength in local._context_associations.items()
        },
    }


def test_owner_save_preserves_existing_posterior_serialization_shape(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "affordance-activation-state.json"
    monkeypatch.setattr("shared.affordance_pipeline.ACTIVATION_STATE_PATH", state_file)

    owner = AffordancePipeline(posterior_mode="owner", posterior_client_id="reverie-test")
    owner.record_outcome("speech_production", success=True, context={"mode": "rnd"})
    owner.save_activation_state()

    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert set(data) == {"activations", "associations"}
    assert data["activations"] == {
        "speech_production": owner._activation["speech_production"].model_dump()
    }
    assert data["associations"] == {"rnd|speech_production": 0.1}


def test_reader_save_raises_detectable_error(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_file = tmp_path / "affordance-activation-state.json"
    monkeypatch.setattr("shared.affordance_pipeline.ACTIVATION_STATE_PATH", state_file)

    reader = AffordancePipeline(posterior_mode="reader", posterior_client_id="logos-test")

    with pytest.raises(PosteriorLockError, match="read-only"):
        reader.save_activation_state()


def test_concurrent_posterior_write_is_blocked(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_file = tmp_path / "affordance-activation-state.json"
    monkeypatch.setattr("shared.affordance_pipeline.ACTIVATION_STATE_PATH", state_file)

    owner = AffordancePipeline(posterior_mode="owner", posterior_client_id="reverie-test")
    owner.record_success("content.imagination_image")

    with posterior_file_lock(state_file):
        with pytest.raises(PosteriorLockError, match="posterior lock held"):
            owner.save_activation_state()


def test_direct_reader_update_append_lock_timeout_is_detectable(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "affordance-activation-state.json"
    monkeypatch.setenv(POSTERIOR_UPDATE_LOCK_TIMEOUT_ENV, "0")

    with posterior_file_lock(posterior_update_log_path(state_file)):
        with pytest.raises(PosteriorLockError, match="posterior lock held"):
            append_posterior_update(
                state_file,
                {
                    "kind": "record_outcome",
                    "source": "daimonion-test",
                    "capability_name": "speech_production",
                    "success": True,
                },
            )


def test_direct_reader_update_append_respects_incoming_size_cap(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "affordance-activation-state.json"
    monkeypatch.setenv(POSTERIOR_UPDATE_LOG_MAX_BYTES_ENV, "120")

    with pytest.raises(PosteriorLockError, match="posterior update log exceeds cap"):
        append_posterior_update(
            state_file,
            {
                "kind": "record_outcome",
                "source": "logos-test",
                "capability_name": "logos_rule",
                "success": True,
                "context": {"oversized": "x" * 200},
            },
        )
    assert not posterior_update_log_path(state_file).exists()


def test_reader_pipeline_drops_and_counts_contended_update_without_raising(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "affordance-activation-state.json"
    monkeypatch.setattr("shared.affordance_pipeline.ACTIVATION_STATE_PATH", state_file)
    monkeypatch.setenv(POSTERIOR_UPDATE_LOCK_TIMEOUT_ENV, "0")
    reader = AffordancePipeline(posterior_mode="reader", posterior_client_id="daimonion-test")

    with posterior_file_lock(posterior_update_log_path(state_file)):
        reader.record_outcome("speech_production", success=True)

    assert reader._posterior_update_failures == 1


def test_owner_drains_decay_and_context_delta_updates(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "affordance-activation-state.json"
    monkeypatch.setattr("shared.affordance_pipeline.ACTIVATION_STATE_PATH", state_file)

    reader = AffordancePipeline(posterior_mode="reader", posterior_client_id="logos-test")
    reader._queue_posterior_update(
        "decay_unused",
        capability_names=["logos_rule"],
        gamma=0.5,
    )
    reader.update_context_association("rnd", "logos_rule", delta=0.2)
    reader.decay_associations(factor=0.5)

    owner = AffordancePipeline(posterior_mode="owner", posterior_client_id="reverie-test")
    owner.save_activation_state()

    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data["activations"]["logos_rule"]["ts_alpha"] == 2.0
    assert data["activations"]["logos_rule"]["ts_beta"] == 1.0
    assert data["associations"] == {"rnd|logos_rule": 0.1}


def test_owner_drain_waits_for_brief_reader_journal_contention(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "affordance-activation-state.json"
    monkeypatch.setattr("shared.affordance_pipeline.ACTIVATION_STATE_PATH", state_file)
    monkeypatch.setenv(POSTERIOR_OWNER_DRAIN_LOCK_TIMEOUT_ENV, "0.5")
    append_posterior_update(
        state_file,
        {
            "kind": "record_outcome",
            "source": "fortress-test",
            "capability_name": "fortress_governance",
            "success": True,
        },
    )
    update_path = posterior_update_log_path(state_file)
    ready = threading.Event()

    def hold_journal_briefly() -> None:
        with posterior_file_lock(update_path):
            ready.set()
            time.sleep(0.05)

    holder = threading.Thread(target=hold_journal_briefly)
    holder.start()
    try:
        assert ready.wait(timeout=1.0)

        owner = AffordancePipeline(posterior_mode="owner", posterior_client_id="reverie-test")
        owner.save_activation_state()
    finally:
        holder.join(timeout=1.0)

    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data["activations"]["fortress_governance"]["use_count"] == 1
    assert update_path.read_text(encoding="utf-8") == ""


def test_reader_reload_replaces_pruned_owner_associations(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "affordance-activation-state.json"
    monkeypatch.setattr("shared.affordance_pipeline.ACTIVATION_STATE_PATH", state_file)

    owner = AffordancePipeline(posterior_mode="owner", posterior_client_id="reverie-test")
    owner.update_context_association("stale", "logos_rule", delta=0.5)
    owner.save_activation_state()
    reader = AffordancePipeline(posterior_mode="reader", posterior_client_id="logos-test")
    assert reader._context_associations == {("stale", "logos_rule"): 0.5}

    owner._context_associations.clear()
    owner.save_activation_state()
    reader.load_activation_state()

    assert reader._context_associations == {}


def test_reader_scoring_refreshes_posterior_when_mtime_changes(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "affordance-activation-state.json"
    monkeypatch.setattr("shared.affordance_pipeline.ACTIVATION_STATE_PATH", state_file)

    owner = AffordancePipeline(posterior_mode="owner", posterior_client_id="reverie-test")
    owner.record_success("speech_production")
    owner.save_activation_state()
    reader = AffordancePipeline(posterior_mode="reader", posterior_client_id="logos-test")
    assert reader.get_activation_state("speech_production").use_count == 1

    owner.record_success("speech_production")
    owner.save_activation_state()
    reader._posterior_last_refresh_check = 0.0
    reader._prepare_posterior_for_scoring()

    assert reader.get_activation_state("speech_production").use_count == 2
