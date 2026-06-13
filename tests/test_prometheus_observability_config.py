"""Pins for config/prometheus/ (W4-PROM-ZERO-RULES, W4-EXPORTERS-UNSCRAPED).

Audit v2 witnessed the live Prometheus with **zero rule groups**
(``/api/v1/rules`` -> ``{"groups":[]}``), no ``rule_files`` stanza at
all, and three live hapax exporters (:9483 daimonion CPAL, :9484
lufs-panic-cap, :9498 youtube telemetry) running unscraped. The repo
previously versioned NO prometheus config — the deployed file lived
only at podium:/home/hapax/llm-stack/prometheus.yml.

These tests pin the repo SSOT introduced by
audit-w4-observability-honesty-20260611: the config parses, carries
>=3 alert rules (the task's exit predicate), registers the three
exporters, and never inlines a credential. Live-state rechecks
(rules API >=1 group, targets health=up) are post-merge deploy
evidence in the task's findings.json, not CI assertions.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PROM_DIR = REPO_ROOT / "config" / "prometheus"
PROM_YML = PROM_DIR / "prometheus.yml"
RULES_YML = PROM_DIR / "rules" / "hapax-observability.yml"

REQUIRED_EXPORTER_TARGETS = {
    "host.docker.internal:9483",  # daimonion CPAL telemetry
    "host.docker.internal:9484",  # lufs-panic-cap
    "host.docker.internal:9498",  # youtube telemetry
}


def _prom_config() -> dict:
    return yaml.safe_load(PROM_YML.read_text())


def _rules_config() -> dict:
    return yaml.safe_load(RULES_YML.read_text())


def _all_rules() -> list[dict]:
    return [r for g in _rules_config().get("groups", []) for r in g.get("rules", [])]


class TestScrapeConfig:
    def test_config_parses_and_loads_rule_files(self) -> None:
        cfg = _prom_config()
        assert cfg.get("rule_files"), (
            "prometheus.yml has no rule_files stanza — this is exactly the "
            "zero-rules live state the W4 audit witnessed; alert rules would "
            "be dead weight on disk"
        )

    def test_live_exporters_are_scraped(self) -> None:
        cfg = _prom_config()
        targets = {
            t
            for job in cfg.get("scrape_configs", [])
            for sc in job.get("static_configs", [])
            for t in sc.get("targets", [])
        }
        missing = REQUIRED_EXPORTER_TARGETS - targets
        assert not missing, (
            f"live exporters still unscraped (W4-EXPORTERS-UNSCRAPED): {sorted(missing)}"
        )

    def test_litellm_scrape_authenticates_via_credentials_file(self) -> None:
        """The litellm target 401s without auth (W4.3). The fix is a
        credentials_file the operator materializes at deploy — the key
        itself must NEVER be committed."""
        cfg = _prom_config()
        litellm = [j for j in cfg.get("scrape_configs", []) if j.get("job_name") == "litellm"]
        assert litellm, "litellm scrape job disappeared"
        auth = litellm[0].get("authorization", {})
        assert auth.get("credentials_file"), "litellm job lacks authorization.credentials_file"
        assert "credentials" not in auth or not auth.get("credentials"), (
            "litellm job inlines a credential — secrets never live in the repo"
        )

    def test_no_inline_secrets_anywhere(self) -> None:
        text = PROM_YML.read_text()
        assert "sk-" not in text and "Bearer " not in text


class TestAlertRules:
    def test_at_least_three_alert_rules(self) -> None:
        """The task exit predicate: >=3 alert rules live (was ZERO)."""
        alerts = [r for r in _all_rules() if "alert" in r]
        assert len(alerts) >= 3, f"only {len(alerts)} alert rules; exit predicate needs >=3"

    def test_every_rule_has_expr_and_summary(self) -> None:
        for rule in _all_rules():
            assert rule.get("expr"), f"rule {rule.get('alert')} missing expr"
            assert rule.get("annotations", {}).get("summary"), (
                f"rule {rule.get('alert')} missing annotations.summary — an "
                f"alert nobody can read is alert fatigue in waiting"
            )

    def test_echo_leak_rule_matches_probe_calibration(self) -> None:
        """The Prometheus rule and the probe's ntfy threshold must agree;
        a drifting pair would alert on different realities."""
        leak = [r for r in _all_rules() if r.get("alert") == "HapaxPrivateBroadcastEchoLeak"]
        assert leak, "HapaxPrivateBroadcastEchoLeak rule missing"
        assert "0.15" in leak[0]["expr"]

    def test_probe_staleness_rule_exists(self) -> None:
        """Inertness detection — the audit's universal class: the rule
        that fires when the echo probe itself stops reporting."""
        stale = [r for r in _all_rules() if r.get("alert") == "HapaxEchoProbeStale"]
        assert stale, "HapaxEchoProbeStale rule missing"
        assert "collect_ts" in stale[0]["expr"]

    def test_probe_staleness_rule_covers_absent_series(self) -> None:
        """`time() - metric > 300` is an EMPTY vector when the series never
        existed (textfile orphaned, collector unconfigured) — the alert
        would stay silent in exactly the W4-TEXTFILE-ORPHAN failure mode.
        The absent() arm makes missing-entirely fire too."""
        stale = [r for r in _all_rules() if r.get("alert") == "HapaxEchoProbeStale"][0]
        assert "absent(hapax_private_broadcast_echo_collect_ts)" in stale["expr"]
