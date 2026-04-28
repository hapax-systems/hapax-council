"""Regression tests for drift detector stale path and live-port probes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

# Import the registry first so direct probe-module imports do not trip the probe loader.
import agents.drift_detector.sufficiency_probes as _probe_registry  # noqa: F401
from agents.drift_detector import probes_alerting, probes_boundary
from agents.drift_detector.collectors_infra import collect_listening_ports_observation
from agents.drift_detector.scanners import scan_sufficiency_gaps
from agents.drift_detector.sufficiency_probes import ProbeResult, SufficiencyProbe


def _write_current_obsidian_plugin(root):
    src = root / "src"
    src.mkdir(parents=True)
    (src / "logos-client.ts").write_text(
        """
        import { requestUrl } from "obsidian";
        export class LogosClient {
          apiAvailable = false;
          updateBaseUrl(url: string): void {}
          private async get(path: string): Promise<unknown> {
            try {
              return await this.timedRequest(path);
            } catch (err) {
              this.apiAvailable = false;
              throw err;
            }
          }
          private timedRequest(url: string, timeoutMs = 8000): Promise<unknown> {
            return Promise.race([
              requestUrl({ url }),
              new Promise((_, reject) =>
                setTimeout(() => reject(new Error(`Request timeout: ${url}`)), timeoutMs),
              ),
            ]);
          }
        }
        """,
        encoding="utf-8",
    )
    (src / "types.ts").write_text(
        """
        export interface HapaxSettings {
          logosApiUrl: string;
        }
        export const DEFAULT_SETTINGS: HapaxSettings = {
          logosApiUrl: "http://localhost:8051",
        };
        """,
        encoding="utf-8",
    )
    (src / "settings.ts").write_text(
        """
        export class HapaxSettingTab {
          display(): void {
            new Setting(containerEl).setName("Logos API URL");
          }
        }
        """,
        encoding="utf-8",
    )
    (src / "main.ts").write_text(
        """
        const settings = await this.loadData();
        this.client = new LogosClient(settings.logosApiUrl);
        await this.saveData(this.settings);
        """,
        encoding="utf-8",
    )
    (src / "context-panel.ts").write_text(
        """
        export class HapaxView {
          private renderError(err: unknown): void {
            content.createEl("p", { text: `Hapax error: ${String(err)}` });
          }
          private async render(): Promise<void> {
            try {
              await this.buildHtml();
            } catch (err) {
              this.renderError(err);
            }
          }
        }
        """,
        encoding="utf-8",
    )


def test_health_monitor_package_layout_satisfies_alert_probe(tmp_path, monkeypatch):
    package = tmp_path / "agents" / "health_monitor"
    package.mkdir(parents=True)
    (package / "__main__.py").write_text("from .runner import main\n", encoding="utf-8")
    (package / "runner.py").write_text("ntfy_notify = 'notify'\n", encoding="utf-8")
    units = tmp_path / "systemd" / "units"
    units.mkdir(parents=True)
    (units / "health-monitor.service").write_text(
        "OnFailure=notify-failure@%n.service\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(probes_alerting, "AI_AGENTS_DIR", tmp_path)
    monkeypatch.setattr(
        probes_alerting.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="active\n", returncode=0),
    )

    met, evidence = probes_alerting._check_proactive_alert_surfacing()

    assert met is True
    assert "health_monitor package" in evidence
    assert "health_monitor.py not found" not in evidence


def test_health_monitor_live_timer_probe_is_inconclusive_when_systemctl_missing(
    tmp_path, monkeypatch
):
    package = tmp_path / "agents" / "health_monitor"
    package.mkdir(parents=True)
    (package / "__main__.py").write_text("notify = True\n", encoding="utf-8")

    monkeypatch.setattr(probes_alerting, "AI_AGENTS_DIR", tmp_path)

    def raise_missing(*args, **kwargs):
        raise FileNotFoundError("systemctl")

    monkeypatch.setattr(probes_alerting.subprocess, "run", raise_missing)

    met, evidence, status = probes_alerting._check_proactive_alert_surfacing()

    assert met is False
    assert status == "inconclusive"
    assert "could not query health-monitor.timer live state" in evidence


def test_obsidian_current_src_layout_satisfies_stale_provider_probes(tmp_path, monkeypatch):
    plugin = tmp_path / "obsidian-hapax"
    _write_current_obsidian_plugin(plugin)
    monkeypatch.setattr(probes_boundary, "OBSIDIAN_HAPAX_DIR", plugin)

    assert not (plugin / "src" / "providers").exists()
    assert not (plugin / "src" / "qdrant-client.ts").exists()

    direct_met, direct_evidence = probes_boundary._check_plugin_direct_api_support()
    degrade_met, degrade_evidence = probes_boundary._check_plugin_graceful_degradation()
    creds_met, creds_evidence = probes_boundary._check_plugin_credentials_in_settings()

    assert direct_met is True
    assert "providers directory not found" not in direct_evidence
    assert degrade_met is True
    assert "qdrant-client.ts not found" not in degrade_evidence
    assert creds_met is True
    assert "apiKey field not found" not in creds_evidence


@pytest.mark.asyncio
async def test_collect_listening_ports_includes_wildcard_binds(monkeypatch):
    ss_output = (
        "State   Recv-Q  Send-Q  Local Address:Port  Peer Address:Port Process\n"
        'LISTEN  0       2048    0.0.0.0:5000       0.0.0.0:* users:(("python3"))\n'
        'LISTEN  0       2048    0.0.0.0:8050       0.0.0.0:* users:(("python3"))\n'
        'LISTEN  0       2048    0.0.0.0:8051       0.0.0.0:* users:(("python3"))\n'
        'LISTEN  0       5       127.0.0.1:8055     0.0.0.0:* users:(("python3"))\n'
    )

    async def mock_run_cmd(cmd):
        return 0, ss_output, ""

    monkeypatch.setattr("agents.drift_detector.collectors_infra.run_cmd", mock_run_cmd)

    ports, status, error = await collect_listening_ports_observation()

    assert status == "observed"
    assert error == ""
    assert "0.0.0.0:5000" in ports
    assert "0.0.0.0:8050" in ports
    assert "0.0.0.0:8051" in ports


@pytest.mark.asyncio
async def test_collect_listening_ports_failure_is_inconclusive(monkeypatch):
    async def mock_run_cmd(cmd):
        return 1, "", "permission denied"

    monkeypatch.setattr("agents.drift_detector.collectors_infra.run_cmd", mock_run_cmd)

    ports, status, error = await collect_listening_ports_observation()

    assert ports == []
    assert status == "inconclusive"
    assert "permission denied" in error


def test_inconclusive_sufficiency_probe_becomes_low_severity():
    probe = SufficiencyProbe(
        id="probe-alert-004",
        axiom_id="executive_function",
        implication_id="ex-alert-004",
        level="system",
        question="Does health_monitor proactively push alerts?",
        check=lambda: (False, "unused"),
    )
    result = ProbeResult(
        probe_id="probe-alert-004",
        met=False,
        evidence="could not query health-monitor.timer live state",
        timestamp="2026-04-28T21:00:00+00:00",
        status="inconclusive",
    )

    with (
        patch("agents.drift_detector.sufficiency_probes.PROBES", [probe]),
        patch("agents.drift_detector.sufficiency_probes.run_probes", return_value=[result]),
    ):
        items = scan_sufficiency_gaps()

    assert len(items) == 1
    assert items[0].severity == "low"
    assert items[0].category == "axiom-sufficiency-inconclusive"
    assert items[0].reality.startswith("inconclusive:")
