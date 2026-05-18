from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "hooks" / "scripts" / "session-context.sh"


def test_session_context_calls_mq_consumer_before_legacy_relay_fallbacks() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    mq_index = text.index("hapax-mq-consume")
    inbox_index = text.index("hapax-relay-inbox")
    broadcast_index = text.index("P0 BROADCAST INBOX")
    request_intake_index = text.index("request-intake-consumer")

    assert mq_index < inbox_index
    assert mq_index < broadcast_index
    assert mq_index < request_intake_index
    assert '"$MQ_CONSUMER" --role "$ROLE" --limit 8 --timeout 2' in text
    assert "2>/dev/null || true" in text
