from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT = REPO_ROOT / "systemd" / "units" / "llm-cost-alert.service"


def test_llm_cost_alert_waits_for_secrets_and_skips_when_dependencies_unready() -> None:
    text = UNIT.read_text(encoding="utf-8")

    assert "Wants=hapax-secrets.service" in text
    assert "After=network-online.target docker.service hapax-secrets.service" in text
    assert "EnvironmentFile=-%t/hapax-secrets.env" in text
    assert "PASSWORD_STORE_DIR" not in text
    assert "GNUPGHOME" not in text
    assert "pass show" not in text
    assert 'grep -q "^LANGFUSE_PUBLIC_KEY=." %t/hapax-secrets.env' in text
    assert 'grep -q "^LANGFUSE_SECRET_KEY=." %t/hapax-secrets.env' in text
    assert "degraded readiness: Langfuse credentials unavailable" in text
    assert "deadline=$((SECONDS + 60))" in text
    assert "curl -s --connect-timeout 1 --max-time 2" in text
    assert "http://localhost:3000" in text
    assert "Langfuse unavailable at http://localhost:3000 after 60s" in text
    assert "ExecStart=%h/projects/distro-work/scripts/llm-cost-alert.sh" in text
