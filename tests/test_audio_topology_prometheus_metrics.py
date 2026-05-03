"""Tests for cc-task audio-audit-E-topology-prometheus-metrics.

Pin the new audit-E metrics shape on top of the existing
`_write_topology_prom` payload contract:

  hapax_audio_topology_declared_links_total          (gauge)
  hapax_audio_topology_live_links_total{state}        (gauge, 3-way split)
  hapax_audio_topology_drift_total                    (counter)

Synthetic-drift-injection test exercises the metric values for each
state (present / missing / extra) so a future refactor that breaks
the math is caught at CI time, not after a stream incident.

The existing `_write_topology_prom` function is loaded directly from
the script via importlib (the script has no `.py` extension). All
metric assertions are against in-memory payload dicts; no PipeWire,
no node_exporter at CI time.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "hapax-audio-topology"


@pytest.fixture(scope="module")
def topology_module():
    """Load the extension-less script as a module.

    importlib.util.spec_from_file_location returns None when the path
    has no recognised suffix; SourceFileLoader is the canonical workaround
    for shebang-CLI-files-without-.py-extension.
    """
    loader = importlib.machinery.SourceFileLoader("hapax_audio_topology", str(SCRIPT))
    spec = importlib.util.spec_from_loader("hapax_audio_topology", loader)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO_ROOT))
    try:
        spec.loader.exec_module(mod)
    finally:
        if str(REPO_ROOT) in sys.path:
            sys.path.remove(str(REPO_ROOT))
    return mod


def _baseline_payload(declared_edge_count: int = 10, live_edge_count: int = 10) -> dict:
    """Build a minimal payload that satisfies _write_topology_prom's reads."""
    return {
        "live_matches_canonical": True,
        "edge_count_by_classification": {},
        "l12_forward_invariant": {"violations": []},
        "tts_broadcast_path": {"ok": True},
        "declared_edge_count": declared_edge_count,
        "live_edge_count": live_edge_count,
        "drift": {},
    }


class TestNewAuditEMetricsPresent:
    """Pin presence of the 3 new audit-E metric names + label sets."""

    def test_declared_links_total_metric_present(self, topology_module, tmp_path) -> None:
        payload = _baseline_payload(declared_edge_count=42)
        target = tmp_path / "topology.prom"
        topology_module._write_topology_prom(target, payload)
        content = target.read_text()
        assert "# HELP hapax_audio_topology_declared_links_total" in content
        assert "# TYPE hapax_audio_topology_declared_links_total gauge" in content
        assert "hapax_audio_topology_declared_links_total 42" in content

    def test_live_links_total_three_way_split_present(self, topology_module, tmp_path) -> None:
        payload = _baseline_payload()
        target = tmp_path / "topology.prom"
        topology_module._write_topology_prom(target, payload)
        content = target.read_text()
        assert "# HELP hapax_audio_topology_live_links_total" in content
        assert "# TYPE hapax_audio_topology_live_links_total gauge" in content
        for state in ("present", "missing", "extra"):
            assert f'hapax_audio_topology_live_links_total{{state="{state}"}}' in content, (
                f"missing live_links_total state={state!r}"
            )

    def test_drift_total_metric_present(self, topology_module, tmp_path) -> None:
        payload = _baseline_payload()
        target = tmp_path / "topology.prom"
        topology_module._write_topology_prom(target, payload)
        content = target.read_text()
        assert "# HELP hapax_audio_topology_drift_total" in content
        assert "# TYPE hapax_audio_topology_drift_total counter" in content
        assert "hapax_audio_topology_drift_total 0" in content


class TestSyntheticDriftInjection:
    """The math contract the systemd timer's metrics depend on."""

    def test_no_drift_yields_present_equals_declared(self, topology_module, tmp_path) -> None:
        payload = _baseline_payload(declared_edge_count=15, live_edge_count=15)
        topology_module._write_topology_prom(tmp_path / "t.prom", payload)
        content = (tmp_path / "t.prom").read_text()
        assert 'hapax_audio_topology_live_links_total{state="present"} 15' in content
        assert 'hapax_audio_topology_live_links_total{state="missing"} 0' in content
        assert 'hapax_audio_topology_live_links_total{state="extra"} 0' in content
        assert "hapax_audio_topology_drift_total 0" in content

    def test_synthetic_missing_edge_increments_missing(self, topology_module, tmp_path) -> None:
        payload = _baseline_payload(declared_edge_count=10, live_edge_count=8)
        payload["drift"] = {
            "classified_missing_edges": [
                {"edge": "src-a → dst-x", "classification": "expected"},
                {"edge": "src-b → dst-y", "classification": "expected"},
            ],
        }
        topology_module._write_topology_prom(tmp_path / "t.prom", payload)
        content = (tmp_path / "t.prom").read_text()
        assert 'hapax_audio_topology_live_links_total{state="missing"} 2' in content
        assert 'hapax_audio_topology_live_links_total{state="present"} 8' in content
        assert "hapax_audio_topology_drift_total 2" in content

    def test_synthetic_extra_edge_increments_extra_and_alert_axis(
        self, topology_module, tmp_path
    ) -> None:
        """state='extra' > 0 is the alert axis Auditor E asked for —
        an unexpected new link is the leak-shaped failure mode."""
        payload = _baseline_payload(declared_edge_count=10, live_edge_count=12)
        payload["drift"] = {
            "unclassified_added_edges": [
                {"edge": "stranger-1 → broadcast"},
                {"edge": "stranger-2 → broadcast"},
            ],
        }
        topology_module._write_topology_prom(tmp_path / "t.prom", payload)
        content = (tmp_path / "t.prom").read_text()
        assert 'hapax_audio_topology_live_links_total{state="extra"} 2' in content
        assert 'hapax_audio_topology_live_links_total{state="missing"} 0' in content
        assert 'hapax_audio_topology_live_links_total{state="present"} 10' in content
        assert "hapax_audio_topology_drift_total 2" in content

    def test_combined_missing_and_extra(self, topology_module, tmp_path) -> None:
        payload = _baseline_payload(declared_edge_count=10, live_edge_count=10)
        payload["drift"] = {
            "classified_missing_edges": [{"edge": "a → b"}],
            "classified_added_edges": [{"edge": "c → d"}],
        }
        topology_module._write_topology_prom(tmp_path / "t.prom", payload)
        content = (tmp_path / "t.prom").read_text()
        assert 'hapax_audio_topology_live_links_total{state="missing"} 1' in content
        assert 'hapax_audio_topology_live_links_total{state="extra"} 1' in content
        assert 'hapax_audio_topology_live_links_total{state="present"} 9' in content
        assert "hapax_audio_topology_drift_total 2" in content


class TestExistingMetricsPreserved:
    """Pin: the audit-E additions must not regress the existing metrics."""

    def test_existing_metrics_still_emitted(self, topology_module, tmp_path) -> None:
        payload = _baseline_payload()
        topology_module._write_topology_prom(tmp_path / "t.prom", payload)
        content = (tmp_path / "t.prom").read_text()
        for metric in (
            "hapax_audio_topology_live_matches_canonical",
            "hapax_audio_topology_drift_edge_count",
            "hapax_audio_topology_l12_invariant_violations",
            "hapax_audio_topology_tts_broadcast_path_ok",
        ):
            assert metric in content, f"existing metric {metric!r} regressed"


class TestTimerCadence:
    """Pin the Auditor E cadence (30s) so a future revert is caught."""

    def test_timer_cadence_is_30s(self) -> None:
        timer = REPO_ROOT / "systemd" / "units" / "hapax-audio-topology-verify.timer"
        content = timer.read_text()
        assert "OnUnitActiveSec=30s" in content, (
            "Auditor E required the verify timer at 30s; current value is "
            "different. If the cadence is intentionally relaxed back, also "
            "update the audit-E task closure note in MEMORY.md."
        )
