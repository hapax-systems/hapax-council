#!/usr/bin/env python3
"""Pull HAN mail into a private foreign-data quarantine. No body interpretation.

Run from the repository with ``uv run python -m scripts.han_mail_pull``.
Credentials are obtained in process from hapax-secret, never from CLI arguments.
"""

from __future__ import annotations

import fcntl
import hashlib
import html
import json
import os
import re
import secrets
import smtplib
import ssl
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Callable
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesHeaderParser
from email.utils import parseaddr
from functools import partial
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx

from shared import chanc
from shared.public_gate_receipts import public_gate_authority_signature

MAX_BYTES = 256 * 1024
POLL_SECONDS = 300
LIMITS = {"lists": 288, "gets": 500, "deletes": 500, "receipts": 500}
HASH = re.compile(r"[0-9a-f]{64}\Z")
# A usable reply address for the intake auto-reply (§5: sent only to the address the message came
# from). Deliberately conservative — a non-address suppresses the reply rather than guessing.
ADDRESS = re.compile(r"\A[^@\s]+@[^@\s]+\.[^@\s]+\Z")
QUARANTINE = Path.home() / "hapax-state/han-mail/quarantine"
DEPLOYMENT = Path(__file__).resolve().parents[1] / "workers/han-mail-receive/deployment.toml"


class IntakeError(Exception):
    """Safe fixed-string diagnostic, without foreign text or credentials."""


class KV(Protocol):
    def list_keys(self, cursor: str) -> tuple[list[dict], str]: ...
    def get_value(self, key: str) -> bytes | None: ...
    def delete_value(self, key: str) -> None: ...


def fsync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def private_directory(directory: Path) -> None:
    if not directory.exists():
        private_directory(directory.parent)
        directory.mkdir(mode=0o700)
        fsync_directory(directory.parent)
    if directory.is_symlink() or not directory.is_dir():
        raise IntakeError("Quarantine path must be a real private directory")


def atomic_write(path: Path, value: bytes) -> None:
    """A completed call means both file bytes and rename are on durable storage."""
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_json(path: Path, value: dict) -> None:
    atomic_write(path, (json.dumps(value, ensure_ascii=True, sort_keys=True) + "\n").encode())


def read_json(path: Path, default: dict | None = None) -> dict:
    if not path.exists() and default is not None:
        return default.copy()
    try:
        if path.is_symlink():
            raise ValueError
        value = json.loads(path.read_bytes())
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, OSError) as exc:
        raise IntakeError("Invalid local intake state; preserve files and investigate") from exc


def safe_text(value: object, limit: int = 240) -> str:
    return " ".join(str(value).split())[:limit]


def subject_only(raw: bytes) -> str:
    # Pass ONLY the bounded header block to the parser, never the body or MIME parts.
    boundaries = [i for marker in (b"\r\n\r\n", b"\n\n") if (i := raw.find(marker)) >= 0]
    if not boundaries or min(boundaries) > 32768:
        return "(subject unavailable)"
    headers = BytesHeaderParser(policy=policy.default).parsebytes(
        raw[: min(boundaries)] + b"\r\n\r\n"
    )
    try:
        return safe_text(headers.get("Subject", "(no subject)"))
    except (ValueError, LookupError):
        return "(subject unavailable)"


def _reply_address(value: object) -> str:
    """The bare address to reply to, or "" if there is none usable. Suppresses rather than guesses."""
    if not isinstance(value, str):
        return ""
    _, addr = parseaddr(value)
    return addr if ADDRESS.match(addr) else ""


def intake_signals(raw: bytes) -> dict:
    """Header-only signals the receipt step needs: the Message-ID (for ``In-Reply-To``) and whether
    the message looks auto-generated or bulk, which suppresses the auto-reply so a receipt never
    starts a mail loop (§5). Parsed from the SAME bounded header block as the subject; never the
    body."""
    boundaries = [i for marker in (b"\r\n\r\n", b"\n\n") if (i := raw.find(marker)) >= 0]
    if not boundaries or min(boundaries) > 32768:
        return {"message_id": "", "loop_indicated": True}  # unparseable headers: do not auto-reply
    headers = BytesHeaderParser(policy=policy.default).parsebytes(
        raw[: min(boundaries)] + b"\r\n\r\n"
    )

    def header(name: str) -> str:
        try:
            value = headers.get(name)
        except (ValueError, LookupError):
            return ""
        return "" if value is None else safe_text(value, 320)

    auto_submitted = header("Auto-Submitted").lower()
    precedence = header("Precedence").lower()
    loop_indicated = (
        (bool(auto_submitted) and auto_submitted != "no")
        or precedence in {"bulk", "list", "junk", "auto_reply"}
        or bool(header("List-Id"))
        or bool(header("List-Unsubscribe"))
        or bool(header("X-Autoreply"))
        or bool(header("X-Autorespond"))
    )
    return {"message_id": header("Message-ID"), "loop_indicated": loop_indicated}


def verify_local(path: Path, key: str, size: int) -> None:
    if path.is_symlink():
        raise IntakeError("Refusing symlink in quarantine")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if os.fstat(stream.fileno()).st_size != size or digest != key:
            raise IntakeError("Local quarantine hash mismatch; remote copy retained")
        os.fsync(stream.fileno())
    fsync_directory(path.parent)


def store_item(root: Path, key: str, raw: bytes, metadata: dict) -> dict:
    if not HASH.fullmatch(key) or len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != key:
        raise IntakeError("Remote message hash or size mismatch; remote copy retained")
    if metadata.get("schema") != 1 or metadata.get("size") != len(raw):
        raise IntakeError("Remote metadata schema or size mismatch; remote copy retained")
    raw_path = root / f"{key}.eml"
    item_path = root / f"{key}.json"
    if not raw_path.exists():
        atomic_write(raw_path, raw)
    verify_local(raw_path, key, len(raw))
    if item_path.exists():
        item = read_json(item_path)
        if (
            item.get("sha256") != key
            or item.get("size") != len(raw)
            or item.get("type") != "han.mail.foreign-data"
        ):
            raise IntakeError("Local metadata mismatch; remote copy retained")
        # Re-fsync a prior publication too, including recovery after interrupted rename.
        with item_path.open("rb") as stream:
            os.fsync(stream.fileno())
        fsync_directory(root)
        return item
    auth = metadata.get("auth", {})
    if not isinstance(auth, dict):
        raise IntakeError("Invalid authentication metadata; remote copy retained")
    allowed = {"pass", "fail", "softfail", "neutral", "none", "temperror", "permerror", "unknown"}
    signals = intake_signals(raw)
    item = {
        "type": "han.mail.foreign-data",
        "schema": 1,
        "trust": "foreign-untrusted",
        "body_access": "operator-only",
        "sender": safe_text(metadata.get("sender", "(unknown)"), 254),
        "recipient": safe_text(metadata.get("recipient", "(unknown)"), 254),
        "subject": subject_only(raw),
        "received_at": safe_text(metadata.get("received_at", "(unknown)"), 40),
        "auth": {
            name: auth.get(name) if auth.get(name) in allowed else "unknown"
            for name in ("spf", "dkim", "dmarc")
        },
        "auth_verdict": "unverified (header observations only)",
        "size": len(raw),
        "sha256": key,
        "kv_key": key,
        "raw_file": f"{key}.eml",
        "notified": False,
        "notification_attempts": 0,
        # §5 receipt bookkeeping. The handle/receipt_id are filled when the receipt is minted;
        # receipt_issued flips only on a successful send; receipt_suppressed records a terminal
        # no-reply decision (auto-generated/bulk mail, or no usable reply address) so it is not
        # retried. message_id rides into the reply's In-Reply-To.
        "message_id": signals["message_id"],
        "loop_indicated": signals["loop_indicated"],
        "receipt_issued": False,
        "receipt_suppressed": None,
    }
    write_json(item_path, item)
    return item


class Budget:
    """Persistent reservations before requests; crashes consume rather than reset quota."""

    def __init__(self, root: Path, clock: Callable[[], float] = time.time):
        self.path = root / "poll-state.json"
        self.clock = clock
        self.state = read_json(self.path, {})

    def reserve(self, operation: str) -> bool:
        now = self.clock()
        day = datetime.fromtimestamp(now, UTC).date().isoformat()
        old_day = self.state.get("day", "")
        if day < old_day:
            return False  # Clock rollback must not reset a spent budget.
        if day > old_day:
            self.state = {
                "day": day,
                "last_list": self.state.get("last_list", 0),
                "cursor": self.state.get("cursor", ""),
            }
        if self.state.get(operation, 0) >= LIMITS[operation]:
            return False
        if operation == "lists":
            if now - self.state.get("last_list", 0) < POLL_SECONDS:
                return False
            self.state["last_list"] = now
        self.state[operation] = self.state.get(operation, 0) + 1
        write_json(self.path, self.state)
        return True

    def cursor(self, value: str) -> None:
        self.state["cursor"] = value
        write_json(self.path, self.state)


def pull_item(kv: KV, root: Path, key: str, metadata: dict, budget: Budget) -> bool:
    if not budget.reserve("gets"):
        return False
    raw = kv.get_value(key)
    if raw is None:  # Eventually consistent list after an earlier successful delete.
        return True
    store_item(root, key, raw, metadata)
    # This order is mutation-tested: verified raw + durable typed metadata BEFORE delete.
    if budget.reserve("deletes"):
        kv.delete_value(key)
    return True


def send_mail_notification(title: str, message: str, **desktop_options) -> bool:
    """One ntfy attempt, then desktop fallback; only acceptance settles pending mail."""
    # Follow the council's NTFY_BASE_URL convention; appendix binds only on tailnet.
    base_url = os.environ.get("NTFY_BASE_URL", "http://100.85.131.41:8090").rstrip("/")
    try:
        # JSON preserves Unicode without putting foreign text in HTTP headers.
        # No redirects, proxies or immediate retries for this private notice.
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            response = client.post(
                base_url + "/",
                json={
                    "topic": "hapax-han-mail",
                    "title": title,
                    "message": message,
                    "priority": 4,
                    "tags": ["mail"],
                },
            )
        if 200 <= response.status_code < 300:
            return True
    except (httpx.HTTPError, ValueError):
        pass

    try:
        from shared.notify import send_notification

        return send_notification(title, message, **desktop_options)
    except Exception:
        # A broken desktop channel must leave the durable batch available for retry.
        return False


def notify_pending(root: Path, notify: Callable[..., bool]) -> int:
    """Surface one summary for the complete pending batch, at most once per poll."""
    pending = []
    for path in sorted(root.glob("*.json")):
        if not HASH.fullmatch(path.stem):
            continue
        item = read_json(path)
        if item.get("notified"):
            continue
        verify_local(root / f"{path.stem}.eml", path.stem, item["size"])
        item["notification_attempts"] += 1
        write_json(path, item)
        pending.append((path, item))
    if not pending:
        return 0

    # Keep the existing deterministic hash order; display only the first item's metadata.
    first_path, first = pending[0]
    count = len(pending)
    attempt = max(item["notification_attempts"] for _, item in pending)
    title = f"HAN mail — {count} pending foreign item(s) [{first_path.stem[:12]}]"
    if attempt > 1:
        title += f" (delivery retry {attempt})"
    # Explicit allowlist: no raw bytes, path dereference, body or MIME excerpt.
    message = "\n".join(
        [
            f"Sender: {html.escape(first['sender'])}",
            f"Subject: {html.escape(first['subject'])}",
            f"Auth: {first['auth_verdict']}; "
            + ", ".join(
                f"{name.upper()}={first['auth'][name]}" for name in ("spf", "dkim", "dmarc")
            ),
            f"Received: {html.escape(first['received_at'])}",
        ]
    )
    if notify(title, message, priority="high", tags=["mail"], technical=False):
        for path, item in pending:
            item["notified"] = True
            write_json(path, item)
        return count
    return 0


def emit_receipts(
    root: Path,
    budget: Budget,
    clock: Callable[[], float] = time.time,
    *,
    send_receipt: Callable[..., bool],
    persist_intake: Callable[..., None],
    key: bytes,
    terms_digest: str,
    withdrawal_instructions: str,
) -> int:
    """Issue at most one §5 intake receipt per quarantined message, as a side effect of the pull.

    Idempotent: each item is handled exactly once. The random handle (D4) and the create-once intake
    record are established BEFORE the first send and made durable on the item, so a failed send, a
    replayed store, or a re-run reuses the same handle and never produces a second receipt.
    ``receipt_issued`` flips only on a successful send; a terminal suppression (auto-generated or
    bulk mail, or no usable reply address) is recorded and never retried. Each send reserves a budget
    leg (B3/B9); when the cap is reached the remaining items wait for the next pull.

    ``send_receipt`` and ``persist_intake`` are injected: the keeper-signed create-once receipt record
    and the SMTP send are the Worker's I/O, wired by the caller. ``key`` is the keeper key for the
    salted commitment (D4).
    """
    issued = 0
    for path in sorted(root.glob("*.json")):
        if not HASH.fullmatch(path.stem):
            continue
        item = read_json(path)
        if item.get("receipt_issued") or item.get("receipt_suppressed"):
            continue
        content_digest = path.stem
        reply_to = _reply_address(item.get("sender", ""))
        if item.get("loop_indicated") or not reply_to:
            # §5 suppression: never auto-reply to auto-generated/bulk mail (a loop) or when there is
            # no usable reply address. Terminal — recorded so it is not retried.
            item["receipt_suppressed"] = (
                "loop-indicated" if item.get("loop_indicated") else "no-reply-address"
            )
            write_json(path, item)
            continue
        # Reserve a send leg first (B3/B9); when the cap is reached the remaining items wait for the
        # next pull, and no intake record is minted for a message whose receipt cannot be sent now.
        if not budget.reserve("receipts"):
            break
        # Mint the random handle and persist the intake binding + receipt record ONCE, durable before
        # the send, so a failed send or a re-run reuses them (one receipt per inbound).
        if not item.get("handle"):
            handle = chanc.generate_handle()
            salt = secrets.token_bytes(16)
            commitment = chanc.salted_commitment(content_digest, salt=salt, key=key)
            receipt = chanc.build_intake_receipt(
                handle=handle,
                content_digest=content_digest,
                issued_at=datetime.fromtimestamp(clock(), UTC),
                terms_digest=terms_digest,
            )
            persist_intake(
                handle=handle,
                content_digest=content_digest,
                commitment=commitment,
                salt_hex=salt.hex(),
                from_address=reply_to,
                receipt=receipt,
            )
            item["handle"] = handle
            item["receipt_id"] = receipt["receipt_id"]
            item["receipt_issued_at"] = receipt["issued_at"]
            write_json(path, item)
        receipt = chanc.build_intake_receipt(
            handle=item["handle"],
            content_digest=content_digest,
            issued_at=datetime.fromisoformat(item["receipt_issued_at"]),
            terms_digest=terms_digest,
        )
        subject, body = chanc.format_receipt_email(
            receipt, withdrawal_instructions=withdrawal_instructions
        )
        if send_receipt(
            to=reply_to,
            subject=subject,
            body=body,
            headers={"Auto-Submitted": "auto-replied", "In-Reply-To": item.get("message_id", "")},
        ):
            item["receipt_issued"] = True
            write_json(path, item)
            issued += 1
    return issued


# --- slice B: the live receipt path, armed only by an explicit runtime switch ---------------------
# RUNTIME SPLIT (seat 2026-10-05T00:07Z): merging this must NOT arm live sending. ``main()`` builds
# the emitter only when the switch below is set; that switch is a SEPARATE authorized runtime act.
# Disarmed, the pull behaves exactly as before: no key read, no record written, nothing sent.
RECEIPT_ARM_ENV = "HAN_MAIL_RECEIPT_SEND"
#: The DEDICATED intake-receipt keeper key (seat ruling 2026-10-04T20:02Z). Never the
#: claim-verification-council key: a SEEN receipt to a stranger is a different authority.
KEEPER_KEY_NAME = "chanc-intake-receipt-hmac"
RECEIPT_SENDER = "hrl-han@hapaxresearch.com"
SUBMISSION_HOST = "smtp.protonmail.ch"
SUBMISSION_PORT = 587
SUBMISSION_SECRET = "proton-smtp-hrl-han"  # pragma: allowlist secret — a FileStore key NAME
INTAKE_RECORDS = Path.home() / "hapax-state/han-mail/intake"
OUTBOUND_RECORDS = Path.home() / "hapax-state/han-mail/outbound"
#: The local copy of the corrections terms (component 4 publishes the identical text to /about/,
#: so the digest the sender is shown resolves to the page). Absent => the emitter fails closed.
CHANC_TERMS = Path.home() / "hapax-state/han-mail/terms.md"
_ARMED = frozenset({"1", "true", "yes", "on"})


def receipt_send_armed() -> bool:
    """True only when the operator's runtime switch is set. Unset or falsy is the default."""
    return os.environ.get(RECEIPT_ARM_ENV, "").strip().lower() in _ARMED


def _secret(name: str) -> str | None:
    """Read one FileStore value in process. Never logged, never echoed, never printed."""
    try:
        result = subprocess.run(["hapax-secret", name], capture_output=True, text=True, check=False)
    except OSError:
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def keeper_key() -> bytes | None:
    """The dedicated keeper key, resolved by NAME at run time (seat ruling 2026-10-05T00:19:27Z).

    Returns None when it is absent. The caller fails CLOSED — no receipt — rather than signing
    with anything else, and this function never generates, prints or persists a key.
    """
    value = _secret(KEEPER_KEY_NAME)
    return value.encode() if value else None


def smtp_credential() -> str | None:
    """The Proton submission credential. None when unprovisioned; the send fails closed."""
    return _secret(SUBMISSION_SECRET)


def chanc_terms() -> tuple[str, str] | None:
    """``(terms_digest, withdrawal_instructions)`` from the local terms copy, or None."""
    try:
        text = CHANC_TERMS.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.strip():
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest(), text


def persist_intake(
    *,
    handle: str,
    content_digest: str,
    commitment: str,
    salt_hex: str,
    from_address: str,
    receipt: dict,
    key: bytes,
    root: Path | None = None,
) -> None:
    """Create-once, HMAC-signed receipt record, keyed to the KEYED digest (§4, Q11).

    The plain content digest never enters the record: the file name and the record's own
    ``keyed_digest`` are the HMAC of the content digest under the keeper key, the ``commitment``
    binds the message without revealing it, and the stored receipt carries its identity with
    ``content_digest`` dropped. §4 keeps the plain digest in exactly two places — the quarantine
    file name and the receipt the sender holds — and this permanent record must not be a third.
    The record is signed under the existing public-gate receipt contract, with the dedicated keeper
    key as the secret. Create-once: an existing record for the same message is a refusal.
    """
    root = INTAKE_RECORDS if root is None else root  # resolved at call time, not at import
    keyed = chanc.keyed_digest(content_digest, key=key)
    record = {
        "type": "han.mail.intake-record",
        "schema": 1,
        "handle": handle,
        "keyed_digest": keyed,
        "commitment": commitment,
        "salt_hex": salt_hex,
        "from_address": from_address,
        "receipt": {name: value for name, value in receipt.items() if name != "content_digest"},
    }
    record["authority_signature"] = public_gate_authority_signature(record, key.decode("utf-8"))
    private_directory(root)
    path = root / f"{keyed}.json"
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise IntakeError(
            "Intake receipt record already exists for this message; preserve it and reconcile"
        ) from None
    fsync_directory(root)


def _receipt_message(
    *, sender: str, to: str, subject: str, body: str, headers: dict
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    for name, value in headers.items():
        if value:
            message[name] = value
    message.set_content(body)
    return message


class ReceiptTransportError(IntakeError):
    """A submission failure BEFORE the SMTP transaction started. Safe to retry."""


def _proton_transport(sender: str, token: str, message: EmailMessage) -> None:
    """One Proton submission over STARTTLS. Never retries internally.

    Raises ``ReceiptTransportError`` only when nothing was submitted — connect, STARTTLS or login
    failed, so a later attempt cannot duplicate a receipt. Anything raised once ``send_message``
    has begun is left as-is: the caller must treat that as ambiguous.
    """
    try:
        client = smtplib.SMTP(SUBMISSION_HOST, SUBMISSION_PORT, timeout=30)
    except OSError as exc:
        raise ReceiptTransportError("submission connection failed before send") from exc
    try:
        try:
            client.ehlo()
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
            client.login(sender, token)
        except (OSError, smtplib.SMTPException) as exc:
            raise ReceiptTransportError("submission setup failed before send") from exc
        client.send_message(message)
    finally:
        client.close()


#: The outcome states of one submission attempt.
OUTCOME_ACCEPTED = "accepted"
OUTCOME_AMBIGUOUS = "ambiguous"
OUTCOME_PRE_SEND_FAILED = "pre_send_failed"


def send_receipt(
    *,
    to: str,
    subject: str,
    body: str,
    headers: dict,
    sender: str = RECEIPT_SENDER,
    root: Path | None = None,
    transport: Callable[..., None] | None = None,
    credential: Callable[[], str | None] | None = None,
) -> bool:
    """One submission for one receipt. True only on an observed acceptance.

    One send per message, and the guard is durable BEFORE the transaction starts: an immutable
    ``<message_key>.intent.json`` first, so a crash at any point after the attempt begins still
    refuses a replay — the window in which a second receipt could reach a stranger. The separate
    ``<message_key>.outcome.json`` records ``accepted``, ``ambiguous`` (a failure after the
    transaction started, never retried blind), or ``pre_send_failed`` — the only state a later pull
    may retry. Absent credential: no connection, no record.
    """
    root = OUTBOUND_RECORDS if root is None else root  # resolved at call time, not at import
    credential = credential if credential is not None else smtp_credential
    token = credential()
    if not token:
        return False  # Fail closed: no credential, no connection, no record.
    message_key = hashlib.sha256(
        b"\0".join(part.encode("utf-8") for part in (to, subject, body))
    ).hexdigest()
    private_directory(root)
    intent_path = root / f"{message_key}.intent.json"
    outcome_path = root / f"{message_key}.outcome.json"
    if (
        intent_path.exists()
        and read_json(outcome_path, {}).get("outcome") != OUTCOME_PRE_SEND_FAILED
    ):
        return False  # Attempted, and not provably unsubmitted: never a second send.
    message = _receipt_message(sender=sender, to=to, subject=subject, body=body, headers=headers)
    send = transport if transport is not None else _proton_transport
    try:
        with intent_path.open("x", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {"type": "han.mail.receipt-intent", "schema": 1, "to": to}, sort_keys=True
                )
                + "\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
        fsync_directory(root)
    except FileExistsError:
        pass  # A retry after a provably pre-send failure reuses the original intent.
    try:
        send(sender, token, message)
    except ReceiptTransportError:
        write_json(outcome_path, {"outcome": OUTCOME_PRE_SEND_FAILED, "to": to})
        return False  # Nothing was submitted, so a later pull may retry.
    except (IntakeError, OSError, smtplib.SMTPException):
        write_json(outcome_path, {"outcome": OUTCOME_AMBIGUOUS, "to": to})
        return False
    write_json(outcome_path, {"outcome": OUTCOME_ACCEPTED, "to": to})
    return True


def build_receipt_emitter(
    root: Path,
    clock: Callable[[], float] = time.time,
    *,
    terms_digest: str,
    withdrawal_instructions: str,
    send: Callable[..., bool] | None = None,
    persist: Callable[..., None] | None = None,
    key_resolver: Callable[[], bytes | None] | None = None,
) -> Callable[..., int] | None:
    """The §5 receipt emitter, or None when it must not run.

    Two refusals, both fail-closed and neither destructive: the runtime switch is unset (the
    default — merging this slice does not arm sending), or the dedicated keeper key is absent (no
    receipt is signed with anything else, and nothing is sent). Neither refusal marks an item
    suppressed, so the message is simply handled at a later pull once the condition clears.
    """
    if not receipt_send_armed():
        return None
    key = (key_resolver if key_resolver is not None else keeper_key)()
    if key is None:
        print(
            "HAN mail pull: intake keeper key unavailable; no receipt issued. "
            f"Next action: provision {KEEPER_KEY_NAME} in the FileStore via hapax-secret.",
            file=sys.stderr,
        )
        return None
    return partial(
        emit_receipts,
        send_receipt=send if send is not None else send_receipt,
        persist_intake=persist if persist is not None else partial(persist_intake, key=key),
        key=key,
        terms_digest=terms_digest,
        withdrawal_instructions=withdrawal_instructions,
    )


def run_once(
    kv: KV,
    root: Path,
    notify: Callable[..., bool],
    clock: Callable[[], float] = time.time,
    emit: Callable[..., int] | None = None,
) -> dict:
    private_directory(root)
    if root.stat().st_mode & 0o077:
        raise IntakeError("Quarantine must have mode 0700")
    with (root / ".pull.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        budget = Budget(root, clock)
        pulled = 0
        failure = None
        try:
            if budget.reserve("lists"):
                keys, cursor = kv.list_keys(budget.state.get("cursor", ""))
                complete = True
                for entry in keys:
                    key = entry.get("name", "")
                    if not HASH.fullmatch(key):  # Never fetch rate state as foreign mail.
                        continue
                    if not pull_item(kv, root, key, entry.get("metadata", {}), budget):
                        complete = False
                        break
                    pulled += 1
                if complete:
                    budget.cursor(cursor)
        except (IntakeError, OSError) as exc:
            failure = exc
        # Durable pending notifications survive deletes, outages and process crashes.
        sent = notify_pending(root, notify)
        # Receipt emission is a batch side effect too (§5); its durable per-item flags survive a
        # later pull failure, so it runs on the same best-effort footing as the notification.
        emitted = emit(root, budget, clock) if emit is not None else None
        if failure is not None:
            raise failure
        result = {"pulled": pulled, "notified": sent}
        if emitted is not None:
            result["receipts"] = emitted
        return result


class CloudflareKV:
    def __init__(self, namespace: str):
        def secret(name: str) -> str:
            result = subprocess.run(
                ["hapax-secret", name], capture_output=True, text=True, check=False
            )
            if result.returncode or not result.stdout.strip():
                raise IntakeError("Credential unavailable from hapax-secret")
            return result.stdout.strip()

        account = secret("cloudflare-api-account_id")
        self.client = httpx.Client(
            base_url="https://api.cloudflare.com/client/v4",
            headers={"Authorization": "Bearer " + secret("cloudflare-api-api_token")},
            timeout=30,
            follow_redirects=False,
        )
        self.base = f"/accounts/{account}/storage/kv/namespaces/{namespace}"
        subscriptions = self._json("GET", f"/accounts/{account}/subscriptions")["result"]
        if any("worker" in json.dumps(x.get("rate_plan", {})).lower() for x in subscriptions):
            raise IntakeError(
                "STOP: Workers subscription present; re-establish zero-spend authorization"
            )

    def _json(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self.client.request(method, path, **kwargs)
            response.raise_for_status()
            data = response.json()
            if not data.get("success"):
                raise ValueError
            return data
        except (httpx.HTTPError, ValueError) as exc:
            raise IntakeError(
                "Cloudflare request refused; no automatic retry or plan upgrade"
            ) from exc

    def list_keys(self, cursor: str) -> tuple[list[dict], str]:
        params = {"limit": "1000"}
        if cursor:
            params["cursor"] = cursor
        data = self._json("GET", self.base + "/keys", params=params)
        return data["result"], data.get("result_info", {}).get("cursor", "")

    def get_value(self, key: str) -> bytes | None:
        try:
            with self.client.stream(
                "GET", self.base + "/values/" + quote(key, safe="")
            ) as response:
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                chunks = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise IntakeError("Remote value exceeds message size cap")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPError as exc:
            raise IntakeError("Cloudflare value request refused; remote copy retained") from exc

    def delete_value(self, key: str) -> None:
        self._json("DELETE", self.base + "/values/" + quote(key, safe=""))


def _armed_emitter() -> Callable[..., int] | None:
    """The emitter ``main()`` hands to ``run_once``.

    None unless the runtime switch is set AND the terms copy and keeper key both resolve. Disarmed
    returns before reading a file or a key; every refusal leaves the pull non-emitting (fail closed).
    """
    if not receipt_send_armed():
        return None
    terms = chanc_terms()
    if terms is None:
        print(
            "HAN mail pull: corrections terms copy missing; no receipt issued. "
            f"Next action: publish the corrections terms copy at {CHANC_TERMS}.",
            file=sys.stderr,
        )
        return None
    return build_receipt_emitter(
        QUARANTINE, terms_digest=terms[0], withdrawal_instructions=terms[1]
    )


def main() -> int:
    os.umask(0o077)
    try:
        # Fixed production path: no CLI switch can redirect mail into an agent-read repo/vault.
        if QUARANTINE.resolve() != QUARANTINE:
            raise IntakeError("Quarantine path must not resolve through symlinks")
        config = tomllib.loads(DEPLOYMENT.read_text())
        kv = CloudflareKV(config["namespace_id"])
        result = run_once(kv, QUARANTINE, send_mail_notification, emit=_armed_emitter())
        print(json.dumps(result))  # Counts only; no foreign metadata in journal output.
        return 0
    except IntakeError as exc:
        print(f"HAN mail pull stopped: {exc}")
        return 1
    except (OSError, ValueError, KeyError):
        print(
            "HAN mail pull stopped; preserve quarantine and inspect service/API configuration. No automatic retry or upgrade."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
