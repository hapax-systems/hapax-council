"""Category-D operational mail processor.

Parses TLS-expiry warnings (Let's Encrypt), GitHub Dependabot alerts,
and Porkbun DNS / domain-renewal notices into structured operational
events. Writes one JSONL row per event to
``/dev/shm/hapax-mail-monitor/operational-events.jsonl``; the
operator-awareness aggregator consumes that file with a seven-day
age-out and projects counters only onto the canonical awareness spine.

Constitutional fit:
- **Full-automation**: mail is parsed and surfaced as awareness counter
  only. No "ack" / "dismiss" buttons (those would be HITL).
- **Anti-anthropomorphization**: factual structured records, not
  narrative.
- **Refusal-as-data**: 7d age-out is the load-bearing anti-HITL
  primitive — counters age out, operator never has to "clear".

Spec: ``docs/research/2026-04-25-mail-monitoring.md`` § Per-purpose
flow design (Category D).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from prometheus_client import Counter

log = logging.getLogger(__name__)


EVENTS_DIR = Path("/dev/shm/hapax-mail-monitor")
EVENTS_FILE_NAME = "operational-events.jsonl"

OPERATIONAL_KIND_TLS = "tls_expiry"
OPERATIONAL_KIND_DEPENDABOT = "dependabot"
OPERATIONAL_KIND_DNS = "dns"

# Chronicle salience floor for operational events, by kind. All values
# >= 0.7 (the chronicle-ticker ward's _SALIENCE_THRESHOLD) so every
# operational event surfaces; severity ranks by infrastructure impact.
_OPERATIONAL_EVENT_SALIENCE: dict[str, float] = {
    # Security alerts are top priority — Dependabot CVE notices.
    OPERATIONAL_KIND_DEPENDABOT: 0.9,
    # Cert renewal notices — expired certs break HTTPS.
    OPERATIONAL_KIND_TLS: 0.85,
    # DNS changes — notable for routing diagnosis.
    OPERATIONAL_KIND_DNS: 0.8,
}

_LETSENCRYPT_SENDER = "noreply@letsencrypt.org"
_GITHUB_SENDER = "noreply@github.com"
_PORKBUN_SENDER = "support@porkbun.com"

_DEPENDABOT_SUBJECT_RE = re.compile(r"\[GitHub\]\s+Dependabot\s+alert", re.IGNORECASE)
_LETSENCRYPT_DOMAIN_RE = re.compile(
    r"certificate(?:\s+for)?\s+([a-z0-9][a-z0-9.-]*\.[a-z]{2,})", re.IGNORECASE
)
_DEPENDABOT_REPO_RE = re.compile(r"\bin\s+([a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+)")
_DEPENDABOT_SEVERITY_RE = re.compile(
    r"\b(critical|high|moderate|medium|low)\s+severity", re.IGNORECASE
)
_PORKBUN_DOMAIN_RE = re.compile(r":\s*([a-z0-9][a-z0-9.-]*\.[a-z]{2,})", re.IGNORECASE)


OPERATIONAL_EVENTS_COUNTER = Counter(
    "hapax_mail_monitor_operational_events_total",
    "Operational mail events surfaced by the processor.",
    ["kind", "source"],
)
for _kind in (OPERATIONAL_KIND_TLS, OPERATIONAL_KIND_DEPENDABOT, OPERATIONAL_KIND_DNS):
    for _source in ("letsencrypt", "github", "porkbun"):
        OPERATIONAL_EVENTS_COUNTER.labels(kind=_kind, source=_source)


def _addr(sender: str | None) -> str:
    if not sender:
        return ""
    angle = re.search(r"<([^>]+)>", sender)
    return (angle.group(1) if angle else sender).strip().lower()


def classify_operational_kind(message: dict[str, Any]) -> str | None:
    """Return one of OPERATIONAL_KIND_* or None if message isn't operational."""
    addr = _addr(message.get("sender"))
    subject = message.get("subject") or ""
    if addr == _LETSENCRYPT_SENDER:
        return OPERATIONAL_KIND_TLS
    if addr == _PORKBUN_SENDER:
        return OPERATIONAL_KIND_DNS
    if addr == _GITHUB_SENDER and _DEPENDABOT_SUBJECT_RE.search(subject):
        return OPERATIONAL_KIND_DEPENDABOT
    return None


def parse_letsencrypt(message: dict[str, Any]) -> dict[str, Any]:
    subject = message.get("subject") or ""
    match = _LETSENCRYPT_DOMAIN_RE.search(subject)
    return {"domain": match.group(1) if match else None}


def parse_dependabot(message: dict[str, Any]) -> dict[str, Any]:
    subject = message.get("subject") or ""
    body = message.get("body") or ""
    repo_match = _DEPENDABOT_REPO_RE.search(body) or _DEPENDABOT_REPO_RE.search(subject)
    severity_match = _DEPENDABOT_SEVERITY_RE.search(subject) or _DEPENDABOT_SEVERITY_RE.search(body)
    return {
        "repo": repo_match.group(1) if repo_match else None,
        "severity": severity_match.group(1).lower() if severity_match else None,
    }


def parse_porkbun(message: dict[str, Any]) -> dict[str, Any]:
    subject = message.get("subject") or ""
    match = _PORKBUN_DOMAIN_RE.search(subject)
    return {"domain": match.group(1) if match else None}


def _parser_for(kind: str):
    return {
        OPERATIONAL_KIND_TLS: parse_letsencrypt,
        OPERATIONAL_KIND_DEPENDABOT: parse_dependabot,
        OPERATIONAL_KIND_DNS: parse_porkbun,
    }[kind]


def _source_label(kind: str) -> str:
    return {
        OPERATIONAL_KIND_TLS: "letsencrypt",
        OPERATIONAL_KIND_DEPENDABOT: "github",
        OPERATIONAL_KIND_DNS: "porkbun",
    }[kind]


def _seen_message(events_path: Path, message_id: str) -> bool:
    """Idempotency: return True iff the JSONL log already has this messageId."""
    if not events_path.exists() or not message_id:
        return False
    target = json.dumps(message_id)  # quoted, escaped
    with events_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if target in line:
                return True
    return False


def process_operational(message: dict[str, Any]) -> bool:
    """Persist a Category-D operational event; return True iff written."""
    kind = classify_operational_kind(message)
    if kind is None:
        return False

    payload = _parser_for(kind)(message)
    message_id = message.get("id") or message.get("messageId")
    events_path = EVENTS_DIR / EVENTS_FILE_NAME

    if _seen_message(events_path, str(message_id)):
        return True  # idempotent skip

    event = {
        "ts": time.time(),
        "kind": kind,
        "source": _source_label(kind),
        "message_id": message_id,
        "payload": payload,
    }
    try:
        EVENTS_DIR.mkdir(parents=True, exist_ok=True)
        with events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")
    except OSError:
        log.exception("operational: failed to append event for %s", message_id)
        return False

    OPERATIONAL_EVENTS_COUNTER.labels(kind=kind, source=_source_label(kind)).inc()
    _emit_chronicle(event)
    return True


def _emit_chronicle(event: dict[str, Any]) -> None:
    """Best-effort chronicle event so adjacent daemons can react."""
    try:
        from shared.chronicle import ChronicleEvent, current_otel_ids
        from shared.chronicle import record as chronicle_record

        trace_id, span_id = current_otel_ids()
        chronicle_record(
            ChronicleEvent(
                ts=event["ts"],
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=None,
                source="mail_monitor_operational",
                event_type="operational.event",
                payload={
                    "kind": event["kind"],
                    "source_label": event["source"],
                    "message_hash": hashlib.sha1(
                        str(event.get("message_id") or "").encode("utf-8"),
                        usedforsecurity=False,
                    ).hexdigest()[:8],
                    "salience": _OPERATIONAL_EVENT_SALIENCE.get(event["kind"], 0.75),
                },
            )
        )
    except Exception:
        log.warning("operational: chronicle emission failed", exc_info=True)


__all__ = [
    "EVENTS_DIR",
    "EVENTS_FILE_NAME",
    "OPERATIONAL_EVENTS_COUNTER",
    "OPERATIONAL_KIND_DEPENDABOT",
    "OPERATIONAL_KIND_DNS",
    "OPERATIONAL_KIND_TLS",
    "classify_operational_kind",
    "parse_dependabot",
    "parse_letsencrypt",
    "parse_porkbun",
    "process_operational",
]
