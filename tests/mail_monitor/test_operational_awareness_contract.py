"""CI guard for mail-monitor operational awareness Phase 2.

The chosen architecture is the canonical awareness spine, not a
bespoke mail endpoint. Operator-facing mail awareness may expose only
counters, timestamps, and the operational category enum; it must not
surface mail content or introduce acknowledge/dismiss controls.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from agents.operator_awareness.state import MailBlock, OperationalAlertsBlock

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_mail_awareness_schema_is_counters_only() -> None:
    assert set(MailBlock.model_fields) == {
        "public",
        "operational_alerts",
        "operational_alerts_total",
        "last_operational_alert_at",
        "last_operational_alert_kind",
    }
    assert set(OperationalAlertsBlock.model_fields) == {
        "tls_expiry",
        "dependabot",
        "dns",
    }

    forbidden_fragments = {
        "sender",
        "subject",
        "body",
        "header",
        "message",
        "gmail",
        "email",
        "excerpt",
    }
    field_names = {
        *MailBlock.model_fields,
        *OperationalAlertsBlock.model_fields,
    }
    for field_name in field_names:
        assert all(fragment not in field_name for fragment in forbidden_fragments)


def test_bespoke_mail_categories_endpoint_remains_retired() -> None:
    awareness_route = REPO_ROOT / "logos" / "api" / "routes" / "awareness.py"
    text = awareness_route.read_text(encoding="utf-8")
    assert "/awareness/mail/categories" not in text
    assert "/awareness/mail/refusal-feedback" not in text


def test_operational_awareness_surfaces_are_read_only() -> None:
    surface_paths = [
        REPO_ROOT / "scripts" / "waybar" / "hapax-waybar-operational-alerts",
        REPO_ROOT
        / "hapax-logos"
        / "src"
        / "components"
        / "sidebar"
        / "MailOperationalAlertsView.tsx",
    ]
    forbidden_tokens = (
        "<button",
        "onClick",
        "invoke(",
        "plugin:opener",
        "window.open",
        "on-click",
        "exec-if",
    )
    for path in surface_paths:
        text = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in text, f"{path} contains read/write affordance token {token!r}"


def test_waybar_operational_alerts_reads_mail_block(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "mail": {
                    "operational_alerts_total": 2,
                    "operational_alerts": {
                        "tls_expiry": 1,
                        "dependabot": 0,
                        "dns": 1,
                    },
                    "last_operational_alert_kind": "dns",
                    "last_operational_alert_at": "2026-04-30T12:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )
    script = REPO_ROOT / "scripts" / "waybar" / "hapax-waybar-operational-alerts"
    env = {**os.environ, "HAPAX_AWARENESS_STATE_PATH": str(state), "HAPAX_AWARENESS_TTL_S": "300"}
    result = subprocess.run(
        [str(script)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )
    payload = json.loads(result.stdout)
    assert payload["text"] == "ops 2"
    assert payload["class"] == "degraded"
    assert "tls 1" in payload["tooltip"]
    assert "dns 1" in payload["tooltip"]
