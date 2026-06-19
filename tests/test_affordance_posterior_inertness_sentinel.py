from __future__ import annotations

import json
from pathlib import Path

from shared.affordance_pipeline import ACTIVATION_STATE_PATH, AffordancePipeline
from shared.affordance_posterior_inertness_sentinel import ConsumerProbe, run_sentinel


def _reader(client_id: str, posterior_path: Path) -> AffordancePipeline:
    return AffordancePipeline(
        posterior_mode="reader",
        posterior_client_id=client_id,
        posterior_path=posterior_path,
    )


def test_sentinel_passes_when_all_consumer_paths_read_probe(tmp_path: Path) -> None:
    artifact_path = tmp_path / "sentinel-artifact.json"

    result = run_sentinel(
        posterior_path=tmp_path / "posterior.json",
        artifact_path=artifact_path,
        probe_tag="pytest_pass",
    )

    assert result["status"] == "PASS"
    assert {consumer["name"] for consumer in result["consumers"]} == {
        "daimonion",
        "fortress",
        "logos",
    }
    assert all(consumer["ok"] for consumer in result["consumers"])
    assert all(consumer["refresh_loaded_change"] for consumer in result["consumers"])

    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["status"] == "PASS"
    assert artifact["probe"]["capability_name"] == "inertness_sentinel_probe_pytest_pass"


def test_sentinel_default_uses_isolated_temp_posterior(tmp_path: Path) -> None:
    result = run_sentinel(
        artifact_path=tmp_path / "sentinel-artifact.json",
        probe_tag="pytest_default",
    )

    assert result["status"] == "PASS"
    assert Path(result["posterior_path"]) != ACTIVATION_STATE_PATH
    assert Path(result["posterior_path"]).exists()


def test_sentinel_refuses_live_posterior_without_explicit_opt_in(tmp_path: Path) -> None:
    result = run_sentinel(
        posterior_path=ACTIVATION_STATE_PATH,
        artifact_path=tmp_path / "sentinel-artifact.json",
        probe_tag="pytest_live_refusal",
    )

    assert result["status"] == "FAIL"
    assert result["consumers"] == []
    assert any(
        "refusing to write inertness probe to live posterior path" in error
        for error in result["errors"]
    )


def test_sentinel_fails_with_identifying_message_for_stale_consumer(tmp_path: Path) -> None:
    posterior_path = tmp_path / "posterior.json"
    stale_posterior_path = tmp_path / "stale-posterior.json"
    artifact_path = tmp_path / "sentinel-artifact.json"

    result = run_sentinel(
        posterior_path=posterior_path,
        artifact_path=artifact_path,
        probe_tag="pytest_fail",
        consumers=(
            ConsumerProbe("fresh-a", lambda path: _reader("fresh-a", path)),
            ConsumerProbe("stale-b", lambda _path: _reader("stale-b", stale_posterior_path)),
            ConsumerProbe("fresh-c", lambda path: _reader("fresh-c", path)),
        ),
    )

    assert result["status"] == "FAIL"
    assert any("stale-b: stale or missing posterior probe" in error for error in result["errors"])
    assert any("next action:" in error for error in result["errors"])
    stale = next(consumer for consumer in result["consumers"] if consumer["name"] == "stale-b")
    assert stale["ok"] is False


def test_sentinel_fails_with_next_action_when_consumers_empty(tmp_path: Path) -> None:
    result = run_sentinel(
        posterior_path=tmp_path / "posterior.json",
        artifact_path=tmp_path / "sentinel-artifact.json",
        probe_tag="pytest_empty",
        consumers=(),
    )

    assert result["status"] == "FAIL"
    assert any(
        "no posterior consumers configured; next action:" in error for error in result["errors"]
    )


def test_sentinel_fails_with_next_action_when_consumer_builder_raises(tmp_path: Path) -> None:
    def _broken_builder(_posterior_path: Path) -> AffordancePipeline:
        raise RuntimeError("boom")

    result = run_sentinel(
        posterior_path=tmp_path / "posterior.json",
        artifact_path=tmp_path / "sentinel-artifact.json",
        probe_tag="pytest_exception",
        consumers=(
            ConsumerProbe("broken", _broken_builder),
            ConsumerProbe("fresh", lambda path: _reader("fresh", path)),
        ),
    )

    assert result["status"] == "FAIL"
    assert any("broken: RuntimeError: boom; next action:" in error for error in result["errors"])
    fresh = next(consumer for consumer in result["consumers"] if consumer["name"] == "fresh")
    assert fresh["ok"] is True
