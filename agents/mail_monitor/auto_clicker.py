"""Category A processor — auto-click verify links under a 5-condition gate.

Spec: ``docs/specs/2026-04-25-mail-monitor.md`` §4.

Auto-clicker closes the loop when an outbound Hapax action (e.g. a
Zenodo deposit) generates a confirmation email with a click-through
verify URL. Clicking through is purely automatic when the 5 conditions
in :func:`evaluate_gate` all hold; any failure path is silent — the
operator is never paged to "approve a click", because that would
defeat the whole point of automation.

## The five conditions (ALL must be true)

1. **Auth pass.** ``Authentication-Results`` reports ``dkim=pass``,
   ``spf=pass``, AND ``dmarc=pass`` for the message's envelope-from.
2. **Sender allowlist.** ``allowlists.yaml::allow_senders`` lists the
   exact envelope-from address.
3. **Link allowlist + scheme.** First HTTPS URL in the body has its
   host in ``allowlists.yaml::allow_link_domains``. At most one
   ``Location:`` redirect is followed; the target host must also be
   allowlisted.
4. **Outbound correlation.** A record in
   ``~/.cache/mail-monitor/pending-actions.jsonl`` matches by
   sender-domain within ±10 minutes of message receipt.
5. **Working-mode opt-in.** ``hapax-working-mode == "rnd"`` OR the
   correlated pending-action sets ``auto_unattended: true``.

## Cross-task surface

Pending-actions writers live in the originating Hapax daemons (Zenodo
deposit publisher, OSF connect, ORCID consent flow). Those writers
are *out of scope* for this commit — this module only reads
``pending-actions.jsonl``. Until those daemons ship the writer-side,
condition 4 will fail for every message → no auto-click → no
regression risk.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any

import requests
import yaml
from prometheus_client import Counter

from agents.mail_monitor.audit import audit_call

log = logging.getLogger(__name__)

ALLOWLISTS_PATH = Path(__file__).parent / "allowlists.yaml"
PENDING_ACTIONS_PATH = Path("~/.cache/mail-monitor/pending-actions.jsonl").expanduser()
WORKING_MODE_PATH = Path("~/.cache/hapax/working-mode").expanduser()

CORRELATION_WINDOW_S = 10 * 60  # ±10 min per spec §4 condition 4

_HTTPS_URL_RE = re.compile(r"https://[^\s<>\"']+", re.IGNORECASE)
# ``Authentication-Results`` typically reads
# ``mx.host.example; dkim=pass header.i=@example.com; spf=pass smtp.mailfrom=@…``
_AUTH_RES_RE = re.compile(r"\b(dkim|spf|dmarc)\s*=\s*(\w+)", re.IGNORECASE)

AUTO_CLICK_COUNTER = Counter(
    "hapax_mail_monitor_auto_click_total",
    "Auto-click attempts by outcome and (when failed) the failing condition.",
    labelnames=("result", "condition"),
)
for _result, _condition in (
    ("clicked", ""),
    ("skipped", "auth"),
    ("skipped", "sender"),
    ("skipped", "link"),
    ("skipped", "correlation"),
    ("skipped", "working_mode"),
    ("skipped", "no_url"),
    ("skipped", "config"),
    ("error", "redirect"),
    ("error", "http"),
):
    AUTO_CLICK_COUNTER.labels(result=_result, condition=_condition)


class GateResult:
    """Lightweight (named) result for :func:`evaluate_gate`.

    Not a dataclass to avoid pulling Pydantic into this hot path.
    """

    __slots__ = ("passed", "failed_condition", "url", "redirected_to")

    def __init__(
        self,
        *,
        passed: bool,
        failed_condition: str = "",
        url: str | None = None,
        redirected_to: str | None = None,
    ) -> None:
        self.passed = passed
        self.failed_condition = failed_condition
        self.url = url
        self.redirected_to = redirected_to


def _load_allowlists(path: Path = ALLOWLISTS_PATH) -> dict[str, list[str]]:
    raw = yaml.safe_load(path.read_text())
    return {
        "allow_senders": [s.lower() for s in raw.get("allow_senders", [])],
        "allow_link_domains": [d.lower() for d in raw.get("allow_link_domains", [])],
    }


def _check_auth(headers: dict[str, str]) -> bool:
    """Return True iff ``Authentication-Results`` shows pass for all three."""
    raw = headers.get("Authentication-Results") or headers.get("authentication-results")
    if not raw:
        return False
    results: dict[str, str] = {}
    for match in _AUTH_RES_RE.finditer(raw):
        method = match.group(1).lower()
        verdict = match.group(2).lower()
        # Don't overwrite if a later instance reports a worse verdict.
        if results.get(method) != "fail":
            results[method] = verdict
    return all(results.get(m) == "pass" for m in ("dkim", "spf", "dmarc"))


def _check_sender(envelope_from: str | None, allow_senders: list[str]) -> bool:
    if not envelope_from:
        return False
    return envelope_from.strip().lower() in allow_senders


def _extract_first_https(body: str | None) -> str | None:
    if not body:
        return None
    match = _HTTPS_URL_RE.search(body)
    return match.group(0) if match else None


def _domain_in(host: str | None, allow_link_domains: list[str]) -> bool:
    if not host:
        return False
    return host.lower() in allow_link_domains


def _resolve_one_redirect(
    url: str, allow_link_domains: list[str], *, timeout_s: float = 10.0
) -> tuple[str | None, str | None]:
    """HEAD-probe ``url``; if it 301/302s, return the redirect target.

    Returns ``(final_url, redirected_to)``: ``final_url`` is the URL we
    intend to GET. ``redirected_to`` is non-None when the request 3xx'd.
    Returns ``(None, None)`` when the redirect lands on a non-allowlisted
    host (caller treats that as a gate fail).
    """
    parsed_initial = urllib.parse.urlparse(url)
    if parsed_initial.scheme != "https":
        return None, None
    if not _domain_in(parsed_initial.hostname, allow_link_domains):
        return None, None

    try:
        head = requests.head(url, allow_redirects=False, timeout=timeout_s)
    except requests.RequestException as exc:
        log.warning("auto-click HEAD probe failed for %s: %s", url, exc)
        return None, None

    if 300 <= head.status_code < 400:
        target = head.headers.get("Location")
        if not target:
            return None, None
        # Resolve relative redirects against the originating host.
        target_abs = urllib.parse.urljoin(url, target)
        target_parsed = urllib.parse.urlparse(target_abs)
        if target_parsed.scheme != "https":
            return None, None
        if not _domain_in(target_parsed.hostname, allow_link_domains):
            return None, None
        return target_abs, target_abs

    return url, None


def _check_correlation(
    sender_domain: str,
    *,
    now: float | None = None,
    path: Path = PENDING_ACTIONS_PATH,
) -> dict[str, Any] | None:
    """Find a pending-actions record matching ``sender_domain`` within window.

    Returns the matched record dict on success, ``None`` if no match.
    The pending-actions writer (operator-side daemons) is out of scope
    for this PR; this read path is forward-compatible.
    """
    if not path.exists():
        return None
    cutoff_lo = (now if now is not None else time.time()) - CORRELATION_WINDOW_S
    cutoff_hi = (now if now is not None else time.time()) + CORRELATION_WINDOW_S
    sender_domain = sender_domain.lower()
    try:
        with path.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                rec_sender = (record.get("sender_domain") or "").lower()
                if rec_sender != sender_domain:
                    continue
                rec_ts = record.get("ts") or record.get("expires") or 0
                try:
                    rec_ts_f = float(rec_ts)
                except (TypeError, ValueError):
                    continue
                if cutoff_lo <= rec_ts_f <= cutoff_hi:
                    return record
    except OSError as exc:
        log.warning("pending-actions read failed: %s", exc)
        return None
    return None


def _check_working_mode(
    pending_record: dict[str, Any] | None,
    *,
    path: Path = WORKING_MODE_PATH,
) -> bool:
    """Return True iff working-mode is ``rnd`` OR record opts in unattended."""
    if pending_record and pending_record.get("auto_unattended") is True:
        return True
    try:
        mode = path.read_text().strip().lower()
    except OSError:
        # Conservative: missing working-mode file → assume research → block.
        return False
    return mode == "rnd"


def _sender_domain(envelope_from: str | None) -> str | None:
    if not envelope_from:
        return None
    if "@" not in envelope_from:
        return None
    return envelope_from.split("@", 1)[1].strip().lower()


def evaluate_gate(
    message: dict[str, Any],
    *,
    allowlists: dict[str, list[str]] | None = None,
    now: float | None = None,
    pending_actions_path: Path = PENDING_ACTIONS_PATH,
    working_mode_path: Path = WORKING_MODE_PATH,
) -> GateResult:
    """Run the 5-condition gate. Returns :class:`GateResult` (no IO if fail)."""
    al = allowlists if allowlists is not None else _load_allowlists()

    # 1. auth
    headers = message.get("headers") or {}
    if not _check_auth(headers):
        AUTO_CLICK_COUNTER.labels(result="skipped", condition="auth").inc()
        return GateResult(passed=False, failed_condition="auth")

    # 2. sender
    envelope_from = message.get("envelope_from")
    if not _check_sender(envelope_from, al["allow_senders"]):
        AUTO_CLICK_COUNTER.labels(result="skipped", condition="sender").inc()
        return GateResult(passed=False, failed_condition="sender")

    # 3. link allowlist + redirect resolution
    body = message.get("body_text") or ""
    url = _extract_first_https(body)
    if url is None:
        AUTO_CLICK_COUNTER.labels(result="skipped", condition="no_url").inc()
        return GateResult(passed=False, failed_condition="no_url")

    final_url, redirected_to = _resolve_one_redirect(url, al["allow_link_domains"])
    if final_url is None:
        AUTO_CLICK_COUNTER.labels(result="skipped", condition="link").inc()
        return GateResult(passed=False, failed_condition="link", url=url)

    # 4. correlation
    sender_domain = _sender_domain(envelope_from)
    if sender_domain is None:
        AUTO_CLICK_COUNTER.labels(result="skipped", condition="sender").inc()
        return GateResult(passed=False, failed_condition="sender")
    pending_record = _check_correlation(sender_domain, now=now, path=pending_actions_path)
    if pending_record is None:
        AUTO_CLICK_COUNTER.labels(result="skipped", condition="correlation").inc()
        return GateResult(passed=False, failed_condition="correlation", url=final_url)

    # 5. working-mode / opt-in
    if not _check_working_mode(pending_record, path=working_mode_path):
        AUTO_CLICK_COUNTER.labels(result="skipped", condition="working_mode").inc()
        return GateResult(passed=False, failed_condition="working_mode", url=final_url)

    return GateResult(passed=True, url=final_url, redirected_to=redirected_to)


def execute_click(url: str, *, timeout_s: float = 15.0) -> bool:
    """Issue the verify GET and audit. Returns True on 2xx."""
    try:
        resp = requests.get(url, timeout=timeout_s, allow_redirects=False)
    except requests.RequestException as exc:
        AUTO_CLICK_COUNTER.labels(result="error", condition="http").inc()
        log.warning("auto-click GET failed for %s: %s", url, exc)
        return False
    ok = 200 <= resp.status_code < 300
    if ok:
        AUTO_CLICK_COUNTER.labels(result="clicked", condition="").inc()
    else:
        AUTO_CLICK_COUNTER.labels(result="error", condition="http").inc()
    audit_call(
        "messages.modify",
        label="Hapax/Verify",
        scope="auto-click",
        result="ok" if ok else "error",
        extra={"url_host": urllib.parse.urlparse(url).hostname, "status": resp.status_code},
    )
    return ok


def process_message(message: dict[str, Any]) -> bool:
    """Top-level: gate-check + (on pass) execute the click. Idempotent on
    seen-set in callers; this function does not dedup."""
    result = evaluate_gate(message)
    if not result.passed:
        log.debug(
            "auto-click skipped: condition=%s url=%s",
            result.failed_condition,
            result.url,
        )
        return False
    assert result.url is not None  # gate guarantees
    return execute_click(result.url)
