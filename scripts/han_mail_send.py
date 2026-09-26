#!/usr/bin/env python3
"""Operator-triggered HAN mail submission; no daemon, retry, or mailbox reader.

Use ``uv run --no-sync python -m scripts.han_mail_send CANDIDATE --dry-run``.
TTY checks are a workflow guard, not proof of human presence under a shared UID.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import smtplib
import ssl
import stat
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser
from email.utils import format_datetime
from pathlib import Path

SENDER = "hrl-han@hapaxresearch.com"
DOMAIN = "hapaxresearch.com"
SMTP_HOST = "smtp.protonmail.ch"
SLOT = b"[SEND-TIME: authorized by the operator on <date>; authorization receipt <hash>]"
STATE = Path.home() / "hapax-state/han-mail/outbound"
NOTIFICATION_TEST = Path("/store-fast/tmp/han-mail/ntfy-completion-receipt.json")
TASK = "han-mail-send-capability-20260919"
PARENT = "30-areas/hapax/frame/han-to-han/DETERMINATION-han-to-han-and-capability-io-20260919.md"
AGENT_MARKERS = (
    "HAPAX_AGENT_NAME",
    "HAPAX_AGENT_ROLE",
    "HAPAX_SESSION_ID",
    "CODEX_SESSION_ID",
    "CODEX_THREAD_ID",
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
)


class Refused(Exception):
    """Fixed diagnostics safe to display without SMTP responses or secrets."""


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=True) + "\n").encode()


@dataclass(frozen=True)
class Candidate:
    raw: bytes
    h0: str
    sender: str
    recipient: str
    subject: str
    newline: bytes

    def envelope(self) -> dict:
        return {"from": self.sender, "to": self.recipient, "subject": self.subject}


def parse_candidate(raw: bytes) -> Candidate:
    if not raw or len(raw) > 256 * 1024:
        raise Refused("Candidate size refused; supply a plain-text message below 256 KiB.")
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        raise Refused("Candidate encoding refused; use UTF-8 plain text.") from None
    if any(unicodedata.category(c).startswith("C") and c not in "\r\n\t" for c in text):
        raise Refused("Candidate contains invisible/control characters; remove them before review.")
    newline = b"\r\n" if b"\r\n" in raw else b"\n"
    if (
        b"\r" in raw.replace(b"\r\n", b"")
        or (newline == b"\r\n" and b"\n" in raw.replace(newline, b""))
        or not raw.endswith(newline)
    ):
        raise Refused(
            "Candidate line endings refused; use consistent LF or CRLF and a final newline."
        )
    head, separator, body = raw.partition(newline * 2)
    if not separator or not body:
        raise Refused("Candidate needs headers, a blank line, and a body.")
    if any(len(line) > 998 for line in raw.split(newline)):
        raise Refused("Candidate line exceeds SMTP limit; wrap it before authorization.")
    if body.split(newline).count(SLOT) != 1 or raw.count(b"[SEND-TIME:") != 1:
        raise Refused(
            "Candidate needs exactly one unfilled SEND-TIME slot line; restore the template."
        )
    # A deliberately small plain-text format: no Sender/Resent/Cc/Bcc, duplicate
    # headers, MIME ambiguity, encoded words, or parser recovery/folding.
    lines = head.split(newline)
    if len(lines) != 3 or any(b":" not in line or line[:1] in b" \t" for line in lines):
        raise Refused("Ambiguous headers; use exactly one From, To, and Subject without folding.")
    names = [line.split(b":", 1)[0].lower() for line in lines]
    if sorted(names) != [b"from", b"subject", b"to"] or not head.isascii() or b"=?" in head:
        raise Refused("Ambiguous headers; use only plain ASCII From, To, and Subject.")
    message = BytesParser(policy=policy.default).parsebytes(head + newline * 2)
    if message.defects or any(header.defects for header in message.values()):
        raise Refused("Malformed envelope; supply one verified recipient and unambiguous headers.")
    addresses = []
    for name in ("From", "To"):
        header = message[name]
        if len(header.addresses) != 1 or any(group.display_name for group in header.groups):
            raise Refused("Ambiguous envelope; use one explicit From and one verified To address.")
        address = header.addresses[0].addr_spec
        if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+", address):
            raise Refused(
                "Recipient is a placeholder or invalid; supply the verified contact address."
            )
        addresses.append(address)
    sender, recipient = addresses
    if sender != SENDER:
        raise Refused("Sender refused; use the HAN address hrl-han@hapaxresearch.com.")
    domain = recipient.rsplit("@", 1)[1].lower()
    labels = domain.split(".")
    if (
        len(labels) < 2
        or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", x) for x in labels)
        or labels[-1] in {"invalid", "test", "example", "localhost"}
        or any(
            domain == d or domain.endswith("." + d)
            for d in ("example.com", "example.net", "example.org")
        )
        or any(x in recipient.lower() for x in ("placeholder", "to-be-supplied", "to-be-verified"))
    ):
        raise Refused("Recipient is a placeholder; supply and verify the actual contact address.")
    subject = str(message["Subject"])
    if not subject.strip():
        raise Refused("Subject is empty; supply the intended subject before authorization.")
    return Candidate(raw, digest(raw), sender, recipient, subject, newline)


def require_operator_terminal() -> None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise Refused(
            "Authorization requires TTY stdin AND stdout; operator must run from a terminal."
        )
    if any(os.environ.get(name) for name in AGENT_MARKERS):
        raise Refused(
            "Agent session cannot authorize; operator must use a separate terminal session."
        )
    try:
        if os.ttyname(sys.stdin.fileno()) != os.ttyname(sys.stdout.fileno()):
            raise OSError
        if os.tcgetpgrp(sys.stdin.fileno()) != os.getpgrp():
            raise OSError
    except (OSError, ValueError):
        raise Refused(
            "Authorization needs the same foreground terminal on stdin and stdout."
        ) from None


def authorize(candidate: Candidate) -> dict:
    require_operator_terminal()
    print(candidate.raw.decode("utf-8"), end="")
    print(f"\nH0: {candidate.h0}\nEnvelope: {json.dumps(candidate.envelope())}")
    print(
        "Authorize these exact bytes and this envelope for one submission? [y/N] ",
        end="",
        flush=True,
    )
    if sys.stdin.readline().strip().lower() != "y":
        raise Refused("Authorization declined; no receipt minted and no SMTP connection opened.")
    require_operator_terminal()
    receipt = {
        "type": "han.mail.authorization",
        "schema": 1,
        "h0": candidate.h0,
        "envelope": candidate.envelope(),
        "authorized_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "nonce": os.urandom(16).hex(),
        "method": "foreground-tty-y",
    }
    receipt["id"] = digest(encoded(receipt))
    return receipt


def filled_slot(receipt: dict) -> bytes:
    return (
        f"[SEND-TIME: authorized by the operator on {receipt['authorized_at']}; "
        f"authorization receipt {receipt['id']}]"
    ).encode("ascii")


def gate_output(filled: bytes, receipt: dict) -> Candidate:
    """Email egress binding: reverse ONLY the deterministic receipt slot to H0."""
    try:
        payload = {k: v for k, v in receipt.items() if k != "id"}
        if digest(encoded(payload)) != receipt["id"]:
            raise ValueError
        datetime.fromisoformat(receipt["authorized_at"])
        replacement = filled_slot(receipt)
        if SLOT in filled or filled.count(replacement) != 1:
            raise Refused(
                "Unfilled or mismatched send-time slot; prepare again from the authorized candidate."
            )
        restored = filled.replace(replacement, SLOT, 1)
        candidate = parse_candidate(restored)
        if candidate.h0 != receipt["h0"] or candidate.envelope() != receipt["envelope"]:
            raise Refused(
                "H0/envelope mismatch; changed bytes require a new operator authorization."
            )
        return candidate
    except (KeyError, TypeError, ValueError, UnicodeError):
        raise Refused(
            "Invalid authorization receipt; preserve it and obtain fresh operator authorization."
        ) from None


def command(args: list[str]) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=15, check=False)
        if result.returncode:
            raise OSError
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        raise Refused(
            "Precondition probe failed; restore the named local service or public DNS lookup."
        ) from None


def check_receive() -> None:
    for unit in ("han-mail-pull.service", "han-mail-pull.timer"):
        try:
            values = dict(
                line.split("=", 1)
                for line in command(
                    [
                        "systemctl",
                        "--user",
                        "show",
                        unit,
                        "--property=LoadState,ActiveState,UnitFileState,Result",
                    ]
                ).splitlines()
                if "=" in line
            )
        except Refused:
            values = {}
        if values.get("LoadState") != "loaded":
            raise Refused(
                "Receive units missing; review and install PR #4696 service and timer before sending."
            )
        if unit.endswith(".timer") and (
            values.get("ActiveState") != "active" or values.get("UnitFileState") != "enabled"
        ):
            raise Refused(
                "Receive timer is not live; enable/start the reviewed han-mail-pull.timer."
            )
        if unit.endswith(".service") and values.get("Result") != "success":
            raise Refused(
                "Receive service failed; repair it and verify a successful pull before sending."
            )
    try:
        receipt = json.loads(NOTIFICATION_TEST.read_bytes())
        passed = (
            receipt["task"] == "han-mail-receive-capability-20260919"
            and receipt["notified_after"] is True
            and receipt["raw_hash_verified_before_after"] is True
            and receipt["first_notified"] == 1
            and any(200 <= item["http"] < 300 for item in receipt["publish_responses"])
        )
    except (OSError, ValueError, KeyError, TypeError):
        passed = False
    if not passed:
        raise Refused(
            "Notification test missing/failed; complete PR #4696 synthetic ntfy test and retain its receipt."
        )


def dns_records(name: str, kind: str) -> list[str]:
    # Public resolver, bounded time, no credential/provider API, no runtime changes.
    answer = command(["dig", "@1.1.1.1", "+time=3", "+tries=1", "+short", name, kind])
    records = []
    for line in answer.splitlines():
        if kind == "TXT":
            chunks = re.findall(r'"([^"\\]*)"', line)
            if chunks:
                records.append("".join(chunks))
        else:
            records.append(line.rstrip(".").lower())
    return records


def check_dns() -> None:
    for selector in ("protonmail", "protonmail2", "protonmail3"):
        records = dns_records(f"{selector}._domainkey.{DOMAIN}", "CNAME")
        if len(records) != 1 or not re.fullmatch(
            rf"{selector}\._domainkey\.[a-z0-9-]+\.domains\.proton\.ch", records[0]
        ):
            raise Refused(
                "Proton DKIM CNAME missing/invalid; publish all three exact Proton-provided targets."
            )
    spf = [r for r in dns_records(DOMAIN, "TXT") if r.lower().startswith("v=spf1 ")]
    terms = spf[0].lower().split() if len(spf) == 1 else []
    include = "include:_spf.protonmail.ch"
    if include not in terms or any(
        t.lstrip("+-~?") == "all" for t in terms[: terms.index(include)]
    ):
        raise Refused(
            "Proton SPF missing/ambiguous; add its include to the single existing SPF record."
        )
    dmarc = [r for r in dns_records(f"_dmarc.{DOMAIN}", "TXT") if r.startswith("v=DMARC1;")]
    if len(dmarc) != 1 or not re.search(
        r"(?:^|;)\s*p=(?:none|quarantine|reject)\s*(?:;|$)", dmarc[0]
    ):
        raise Refused(
            "DMARC missing/invalid; publish a valid single DMARC record, initially p=none."
        )


def preconditions() -> None:
    check_receive()
    check_dns()


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def private_directory(path: Path) -> None:
    if path.resolve() != path.absolute():
        raise Refused("Outbound custody path contains a symlink; restore a private real directory.")
    if not path.parent.exists():
        private_directory(path.parent)
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise Refused(
            "Outbound custody is not private; restore owner-only mode 0700 before sending."
        )
    fsync_directory(path.parent)


def immutable(path: Path, value: bytes) -> None:
    """Publish complete fsynced bytes once; collision is NEVER permission to send."""
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fchmod(stream.fileno(), 0o400)
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            raise Refused(
                "Existing intent/receipt/start blocks reuse; preserve the ledger and reconcile, never retry blind."
            ) from None
        fsync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def connect_proton() -> smtplib.SMTP:
    require_operator_terminal()
    try:
        token = command(["hapax-secret", "proton-smtp-hrl-han"])
    except Refused:
        raise Refused(
            "SMTP credential unavailable; operator must provision proton-smtp-hrl-han via hapax-secret."
        ) from None
    if not token:
        raise Refused(
            "SMTP credential empty; operator must provision proton-smtp-hrl-han via hapax-secret."
        )
    client = smtplib.SMTP(timeout=30)
    try:
        client.connect(SMTP_HOST, 587)
        if client.ehlo()[0] != 250:
            raise OSError
        client.starttls(context=ssl.create_default_context())
        if client.ehlo()[0] != 250 or not client.has_extn("8bitmime"):
            raise OSError
        client.login(SENDER, token)
        return client
    except Exception:
        client.close()
        raise Refused(
            "SMTP setup failed before send; check Proton submission, STARTTLS, and stored token."
        ) from None


def submit(candidate: Candidate, receipt: dict, root: Path) -> dict:
    """One atomic receipt owner and intent owner, even for direct concurrent callers.

    The Python API is not a security boundary against same-UID code execution.
    There is intentionally no CLI that imports/mints/replays a receipt.
    """
    require_operator_terminal()
    filled = candidate.raw.replace(SLOT, filled_slot(receipt), 1)
    verified = gate_output(filled, receipt)
    if verified != candidate:
        raise Refused(
            "Candidate changed; obtain a new authorization for the exact candidate bytes."
        )
    preconditions()  # Recheck after potentially long operator review.
    private_directory(root)
    receipts = root / "receipts"
    private_directory(receipts)
    immutable(receipts / f"{receipt['id']}.json", encoded(receipt))
    message_dir = root / candidate.h0
    private_directory(message_dir)
    message_id = f"<{receipt['id']}@{DOMAIN}>"
    date = format_datetime(datetime.fromisoformat(receipt["authorized_at"]))
    transport_headers = (
        f"Date: {date}\r\nMessage-ID: {message_id}\r\n"
        'MIME-Version: 1.0\r\nContent-Type: text/plain; charset="utf-8"\r\n'
        "Content-Transfer-Encoding: 8bit\r\n"
    ).encode("ascii")
    wire = transport_headers + filled.replace(candidate.newline, b"\r\n")
    intent = {
        "type": "han.mail.intent",
        "schema": 1,
        "task": TASK,
        "authority_case": "CASE-SYSTEM-INTEGRITY-20260611",
        "parent_spec": PARENT,
        "h0": candidate.h0,
        "h1": digest(filled),
        "wire_sha256": digest(wire),
        "receipt_id": receipt["id"],
        "envelope": candidate.envelope(),
        "message_id": message_id,
        "transport": "proton-smtp-starttls",
    }
    immutable(message_dir / "intent.json", encoded(intent))
    immutable(message_dir / "candidate.eml", candidate.raw)
    immutable(message_dir / "submitted.eml", wire)
    # Claim is consumed before connection/setup too. Pre-send failure needs a
    # separate reviewed disposition, not a --force or replay switch.
    client = None
    started = False
    try:
        client = connect_proton()
        immutable(message_dir / "send-started.json", encoded({"receipt_id": receipt["id"]}))
        started = True
        client.sendmail(
            candidate.sender, [candidate.recipient], wire, mail_options=["BODY=8BITMIME"]
        )
        outcome = {
            "status": "smtp_accepted",
            "delivery": "unestablished",
            "settlement": "pending_sent_copy",
        }
    except Exception:
        outcome = {
            "status": "ambiguous" if started else "pre_send_failed",
            "delivery": "unestablished",
            "settlement": "pending_operator_reconciliation",
        }
    finally:
        if client is not None:
            # No QUIT failure can downgrade an observed DATA 250.
            client.close()
    immutable(message_dir / "outcome.json", encoded(outcome))
    return {**outcome, "h0": candidate.h0, "h1": intent["h1"], "receipt_id": receipt["id"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate/preflight only; no authorization, state, token, or SMTP",
    )
    args = parser.parse_args(argv)
    try:
        if not args.dry_run:
            require_operator_terminal()
        candidate = parse_candidate(args.candidate.read_bytes())
        preconditions()
        if args.dry_run:
            print(
                json.dumps(
                    {"status": "dry_run", "h0": candidate.h0, "envelope": candidate.envelope()}
                )
            )
            return 0
        receipt = authorize(candidate)
        # The reviewed in-memory snapshot is what leaves, never a second file read.
        result = submit(candidate, receipt, STATE)
        print(json.dumps(result))
        if result["status"] != "smtp_accepted":
            print("Preserve the ledger; reconcile with the operator before any new submission.")
            return 1
        print("SMTP accepted; delivery is unestablished. Separate Sent-copy settlement remains.")
        return 0
    except Refused as exc:
        print(f"HAN mail send refused: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print(
            "HAN mail send stopped; preserve outbound state and reconcile any send-started record before retry.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
