"""The census writes a secret-scanned view and durable trend projection."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.entitlement_census import (
    CensusConfig,
    HostHoldings,
    SecretLeakError,
    attach_history,
    render_view,
    run_census,
    write_outputs,
)

NOW = datetime(2026, 9, 28, tzinfo=UTC)


def _run():
    config = CensusConfig.model_validate(
        {
            "schema": "hapax.entitlement_census.v1",
            "hosts": [{"host_id": "appendix", "transport": "local"}],
            "entitlements": [
                {
                    "entitlement_id": "sample",
                    "provider": "sample",
                    "kind": "cognition",
                    "cost_class": "subscription",
                }
            ],
        }
    )
    return run_census(
        config,
        now=NOW,
        holdings=[HostHoldings(host_id="appendix", reachable=True, observed_at=NOW)],
        registry={},
        ledger=None,
        prior_view=None,
        resolve_secret=lambda _: None,
        http_get=lambda *_: (_ for _ in ()).throw(AssertionError("unexpected network")),
        read_home_file=lambda _: None,
    )


def test_secret_in_any_rendered_output_writes_nothing(tmp_path: Path):
    run = _run()
    run.rows[0].facts["echo"] = "fixture-secret-value"
    run.secrets.remember("fixture-secret-value")
    with pytest.raises(SecretLeakError, match="nothing was written"):
        write_outputs(
            run, output_root=tmp_path / "out", projection_md=tmp_path / "view.md", now=NOW
        )
    assert not (tmp_path / "out").exists() and not (tmp_path / "view.md").exists()


def test_projection_contains_all_rows_and_appends_history(tmp_path: Path):
    run = _run()
    attach_history(run, now=NOW, prior=[], demand={"queued": {"queued": 2}}, witness={})
    root = tmp_path / "out"
    sink = tmp_path / "sink"
    sink.mkdir()
    outputs = write_outputs(
        run, output_root=root, projection_md=tmp_path / "view.md", now=NOW, history_sink_root=sink
    )
    view = json.loads(outputs["view.json"].read_text())
    assert [row["entitlement_id"] for row in view["rows"]] == ["sample"]
    assert view["trend"]["points"] == 1
    assert "sample" in outputs["view.md"].read_text()
    quantities = json.loads(outputs["measurements.json"].read_text())
    assert quantities["producer"] == "scripts/hapax-entitlement-census"
    assert "entitlement-census.history" in outputs
    assert render_view(run, now=NOW)["summary"]["rows"] == 1
