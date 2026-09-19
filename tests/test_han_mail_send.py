"""All SMTP is loopback-only. No production credentials or notification writes."""

from __future__ import annotations

import io
import json
import multiprocessing
import os
import smtplib
import socket
import socketserver
import ssl
import subprocess
import threading
from pathlib import Path

import pytest

from scripts import han_mail_send as mail

RAW = (
    b"From: HAN <hrl-han@hapaxresearch.com>\n"
    b"To: Local sink <sink@fixture.hapaxresearch.com>\n"
    b"Subject: Synthetic loopback test\n\n"
    b"Synthetic text, never delivered.\n. Dot stuffing test.\n" + mail.SLOT + b"\n"
)


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    original = socket.create_connection

    def loopback_only(address, *args, **kwargs):
        assert address[0] in ("127.0.0.1", "::1"), "Tests must never contact a mail provider"
        return original(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", loopback_only)
    monkeypatch.setattr(mail, "command", lambda args: pytest.fail("Unmocked host/secret probe"))


def receipt_for(candidate):
    receipt = {
        "type": "han.mail.authorization",
        "schema": 1,
        "h0": candidate.h0,
        "envelope": candidate.envelope(),
        "authorized_at": "2026-09-19T12:00:00+00:00",
        "nonce": "synthetic",
        "method": "foreground-tty-y",
    }
    receipt["id"] = mail.digest(mail.encoded(receipt))
    return receipt


@pytest.fixture
def approved(monkeypatch):
    # This substitutes local synthetic operator presence, never an actual receipt.
    monkeypatch.setattr(mail, "require_operator_terminal", lambda: None)
    monkeypatch.setattr(mail, "preconditions", lambda: None)
    candidate = mail.parse_candidate(RAW)
    return candidate, receipt_for(candidate)


class Terminal(io.StringIO):
    def __init__(self, text="", tty=True, fd=0):
        super().__init__(text)
        self.tty = tty
        self.fd = fd

    def isatty(self):
        return self.tty

    def fileno(self):
        return self.fd


def terminals(monkeypatch, input_tty=True, output_tty=True, answer="y\n"):
    for name in mail.AGENT_MARKERS:
        monkeypatch.delenv(name, raising=False)
    stdin = Terminal(answer, input_tty)
    stdout = Terminal(tty=output_tty, fd=1)
    monkeypatch.setattr(mail.sys, "stdin", stdin)
    monkeypatch.setattr(mail.sys, "stdout", stdout)
    monkeypatch.setattr(mail.os, "ttyname", lambda fd: "/dev/pts/synthetic")
    monkeypatch.setattr(mail.os, "tcgetpgrp", lambda fd: os.getpgrp())
    return stdout


@pytest.mark.parametrize("input_tty,output_tty", [(False, True), (True, False), (False, False)])
def test_no_tty_refuses(monkeypatch, input_tty, output_tty):
    terminals(monkeypatch, input_tty, output_tty)
    with pytest.raises(mail.Refused, match="TTY"):
        mail.authorize(mail.parse_candidate(RAW))


def test_agent_even_with_tty_refuses(monkeypatch):
    terminals(monkeypatch)
    monkeypatch.setenv("CODEX_THREAD_ID", "synthetic-agent")
    with pytest.raises(mail.Refused, match="Agent session"):
        mail.authorize(mail.parse_candidate(RAW))


@pytest.mark.parametrize("different_tty", [False, True])
def test_terminal_must_match_and_be_foreground(monkeypatch, different_tty):
    terminals(monkeypatch)
    if different_tty:
        monkeypatch.setattr(mail.os, "ttyname", lambda fd: str(fd))
    else:
        monkeypatch.setattr(mail.os, "tcgetpgrp", lambda fd: -1)
    with pytest.raises(mail.Refused, match="foreground terminal"):
        mail.require_operator_terminal()


@pytest.mark.parametrize("answer", ["", "\n", "n\n", "yes\n"])
def test_default_no(monkeypatch, answer):
    terminals(monkeypatch, answer=answer)
    with pytest.raises(mail.Refused, match="declined"):
        mail.authorize(mail.parse_candidate(RAW))


def test_authorization_displays_exact_candidate_hash_envelope(monkeypatch):
    output = terminals(monkeypatch)
    candidate = mail.parse_candidate(RAW)
    receipt = mail.authorize(candidate)
    shown = output.getvalue()
    assert RAW.decode() in shown
    assert candidate.h0 in shown
    assert json.dumps(candidate.envelope()) in shown
    assert receipt["h0"] == candidate.h0
    assert receipt["id"] == mail.digest(
        mail.encoded({k: v for k, v in receipt.items() if k != "id"})
    )


def test_gate_round_trip_and_every_outside_slot_byte():
    candidate = mail.parse_candidate(RAW)
    receipt = receipt_for(candidate)
    filled = RAW.replace(mail.SLOT, mail.filled_slot(receipt))
    assert mail.gate_output(filled, receipt) == candidate
    start = filled.index(mail.filled_slot(receipt))
    end = start + len(mail.filled_slot(receipt))
    for index in range(len(filled)):
        if start <= index < end:
            continue
        changed = filled[:index] + bytes([filled[index] ^ 1]) + filled[index + 1 :]
        with pytest.raises(mail.Refused):
            mail.gate_output(changed, receipt)
    with pytest.raises(mail.Refused, match="mismatch"):
        mail.gate_output(filled.replace(b"Synthetic text", b"Altered text"), receipt)


def test_unfilled_slot_refuses():
    with pytest.raises(mail.Refused, match="Unfilled"):
        mail.gate_output(RAW, receipt_for(mail.parse_candidate(RAW)))


@pytest.mark.parametrize(
    "change",
    [
        lambda raw: raw.replace(mail.SLOT, b""),
        lambda raw: raw + mail.SLOT + b"\n",
        lambda raw: raw.replace(b"From:", b"Sender:"),
        lambda raw: b"Resent-To: sink@fixture.hapaxresearch.com\n" + raw,
        lambda raw: b"Bcc: sink@fixture.hapaxresearch.com\n" + raw,
        lambda raw: b"From: hrl-han@hapaxresearch.com\n" + raw,
        lambda raw: raw.replace(
            b"To: Local sink <sink@fixture.hapaxresearch.com>", b"To: [contact to be supplied]"
        ),
        lambda raw: raw.replace(b"sink@fixture.hapaxresearch.com", b"user@example.com"),
        lambda raw: raw.replace(b"sink@fixture.hapaxresearch.com", b"sink@localhost"),
        lambda raw: raw.replace(b"sink@fixture.hapaxresearch.com", b"sink@fixture.invalid"),
        lambda raw: raw.replace(
            b"sink@fixture.hapaxresearch.com", b"a@hapaxresearch.com, b@hapaxresearch.com"
        ),
        lambda raw: raw.replace(b"Subject:", b" Subject:"),
        lambda raw: raw.replace(b"Synthetic text", b"\x1b[2J"),
        lambda raw: raw.replace(b"Synthetic text", "hidden\u202e".encode()),
        lambda raw: raw.replace(b"\n\n", b"\r\n\r\n", 1),
    ],
)
def test_ambiguous_candidate_refuses(change):
    with pytest.raises(mail.Refused):
        mail.parse_candidate(change(RAW))


def test_placeholder_recipient_refuses():
    with pytest.raises(mail.Refused, match="placeholder"):
        mail.parse_candidate(RAW.replace(b"sink@fixture.hapaxresearch.com", b"sink@example.org"))


def test_frozen_candidate_copy(tmp_path):
    source = os.environ.get("HAN_MAIL_CANDIDATE_FIXTURE")
    if not source:
        pytest.skip("Private frozen candidate supplied only during commissioned local validation")
    raw = Path(source).read_bytes()
    # Dispatch-pinned SHA-256 of the draft, not a credential.
    assert (
        mail.digest(raw)
        == (
            "3e55da135c42c5f8fc3cb339da24ee61d1f3e5850b20aada768ee7de2e9b34b0"  # pragma: allowlist secret
        )
    )
    copy = tmp_path / "candidate.eml"
    copy.write_bytes(raw)
    with pytest.raises(mail.Refused):
        mail.parse_candidate(copy.read_bytes())
    # Only a copy's placeholder is substituted; H0 is deliberately different.
    candidate = mail.parse_candidate(
        raw.replace(
            b"To: [Rune project contact address to be supplied/verified]",
            b"To: sink@fixture.hapaxresearch.com",
        )
    )
    receipt = receipt_for(candidate)
    filled = candidate.raw.replace(mail.SLOT, mail.filled_slot(receipt))
    assert mail.gate_output(filled, receipt) == candidate
    with pytest.raises(mail.Refused, match="mismatch"):
        mail.gate_output(filled.replace(b"Hello,", b"Hallo,"), receipt)
    assert copy.read_bytes() == raw == Path(source).read_bytes()


@pytest.fixture
def readiness(monkeypatch, tmp_path):
    units = {
        "han-mail-pull.service": "LoadState=loaded\nResult=success\nActiveState=inactive",
        "han-mail-pull.timer": "LoadState=loaded\nActiveState=active\nUnitFileState=enabled",
    }
    monkeypatch.setattr(mail, "command", lambda args: units[args[3]])
    notice = tmp_path / "notice.json"
    notice.write_text(
        json.dumps(
            {
                "task": "han-mail-receive-capability-20260919",
                "notified_after": True,
                "raw_hash_verified_before_after": True,
                "first_notified": 1,
                "publish_responses": [{"http": 200}],
            }
        )
    )
    monkeypatch.setattr(mail, "NOTIFICATION_TEST", notice)
    records = {
        (f"{s}._domainkey.hapaxresearch.com", "CNAME"): [
            f"{s}._domainkey.synthetic.domains.proton.ch"
        ]
        for s in ("protonmail", "protonmail2", "protonmail3")
    }
    records[("hapaxresearch.com", "TXT")] = ["v=spf1 include:_spf.protonmail.ch ~all"]
    records[("_dmarc.hapaxresearch.com", "TXT")] = ["v=DMARC1; p=none"]
    monkeypatch.setattr(mail, "dns_records", lambda name, kind: records[(name, kind)])
    return units, notice, records


def test_preconditions_green(readiness):
    mail.preconditions()


@pytest.mark.parametrize(
    "failure",
    ["service_missing", "timer_missing", "timer_inactive", "service_failed", "notification"],
)
def test_receive_preconditions_independently_refuse(readiness, failure):
    units, notice, _ = readiness
    if failure == "notification":
        notice.unlink()
    elif failure == "service_failed":
        units["han-mail-pull.service"] = "LoadState=loaded\nResult=exit-code"
    elif failure == "timer_inactive":
        units["han-mail-pull.timer"] = (
            "LoadState=loaded\nActiveState=inactive\nUnitFileState=enabled"
        )
    else:
        unit = "han-mail-pull.service" if failure == "service_missing" else "han-mail-pull.timer"
        units[unit] = units[unit].replace("LoadState=loaded", "LoadState=not-found")
    with pytest.raises(mail.Refused, match="[Rr]eceive|Notification"):
        mail.preconditions()


@pytest.mark.parametrize("record", ["protonmail", "protonmail2", "protonmail3", "spf", "dmarc"])
def test_dns_preconditions_independently_refuse(readiness, record):
    _, _, records = readiness
    key = (f"{record}._domainkey.hapaxresearch.com", "CNAME")
    if record == "spf":
        key = ("hapaxresearch.com", "TXT")
    elif record == "dmarc":
        key = ("_dmarc.hapaxresearch.com", "TXT")
    records[key] = []
    with pytest.raises(mail.Refused, match="DKIM|SPF|DMARC"):
        mail.preconditions()


def test_spf_include_after_all_refused(readiness):
    readiness[2][("hapaxresearch.com", "TXT")] = ["v=spf1 -all include:_spf.protonmail.ch"]
    with pytest.raises(mail.Refused, match="SPF"):
        mail.preconditions()


def test_dns_txt_chunks(monkeypatch):
    monkeypatch.setattr(
        mail, "command", lambda args: '"v=spf1 " "include:_spf.protonmail.ch ~all"\n'
    )
    assert mail.dns_records("hapaxresearch.com", "TXT") == [
        "v=spf1 include:_spf.protonmail.ch ~all"
    ]


class SMTPHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.server.connections += 1
        self.wfile.write(b"220 localhost synthetic\r\n")
        while line := self.rfile.readline():
            verb = line.split(b" ", 1)[0].strip().upper()
            self.server.commands.append(verb)  # Never record AUTH payload.
            if verb == b"EHLO":
                self.wfile.write(
                    b"250-localhost\r\n250-STARTTLS\r\n250-8BITMIME\r\n250 AUTH PLAIN\r\n"
                )
            elif verb == b"STARTTLS":
                self.wfile.write(b"220 upgrade\r\n")
                self.connection = self.server.tls.wrap_socket(self.connection, server_side=True)
                self.rfile = self.connection.makefile("rb")
                self.wfile = self.connection.makefile("wb", buffering=0)
            elif verb == b"AUTH":
                assert isinstance(self.connection, ssl.SSLSocket)
                self.wfile.write(b"235 authenticated\r\n")
            elif verb in (b"MAIL", b"RCPT"):
                self.server.envelopes.append(line.strip())
                self.wfile.write(b"250 ok\r\n")
            elif verb == b"DATA":
                self.wfile.write(b"354 data\r\n")
                chunks = []
                while (chunk := self.rfile.readline()) != b".\r\n":
                    if not chunk:
                        return
                    chunks.append(chunk[1:] if chunk.startswith(b"..") else chunk)
                self.server.messages.append(b"".join(chunks))
                if self.server.drop_after_data:
                    return
                self.wfile.write(b"250 accepted\r\n")
            else:
                self.wfile.write(b"250 ok\r\n")


@pytest.fixture
def smtp_server(tmp_path, monkeypatch):
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    # Ephemeral local test certificate; existing openssl only, nothing installed.
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, key)
    trusted = ssl.create_default_context(cafile=str(cert))
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), SMTPHandler)
    server.daemon_threads = True
    server.tls = tls
    server.connections = 0
    server.commands, server.messages, server.envelopes = [], [], []
    server.drop_after_data = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_connect = smtplib.SMTP.connect

    def local_connect(client, host, port, *args, **kwargs):
        assert (host, port) == (mail.SMTP_HOST, 587)
        client._host = "127.0.0.1"
        return original_connect(client, *server.server_address)

    monkeypatch.setattr(smtplib.SMTP, "connect", local_connect)
    monkeypatch.setattr(mail.ssl, "create_default_context", lambda: trusted)
    monkeypatch.setattr(mail, "command", lambda args: "synthetic-local-test-value")
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_local_smtp_acceptance_and_single_use(approved, smtp_server, tmp_path):
    candidate, receipt = approved
    root = tmp_path / "outbound"
    result = mail.submit(candidate, receipt, root)
    assert result["status"] == "smtp_accepted"
    assert result["delivery"] == "unestablished"
    assert result["settlement"] == "pending_sent_copy"
    directory = root / candidate.h0
    intent = json.loads((directory / "intent.json").read_bytes())
    wire = smtp_server.messages[0]
    assert mail.digest(wire) == intent["wire_sha256"]
    assert mail.digest(candidate.raw.replace(mail.SLOT, mail.filled_slot(receipt))) == intent["h1"]
    assert mail.SLOT not in wire
    assert b". Dot stuffing test.\r\n" in wire
    assert smtp_server.commands[:4] == [b"EHLO", b"STARTTLS", b"EHLO", b"AUTH"]
    assert smtp_server.envelopes[0].startswith(b"mail FROM:<hrl-han@hapaxresearch.com>")
    assert smtp_server.envelopes[1] == b"rcpt TO:<sink@fixture.hapaxresearch.com>"
    with pytest.raises(mail.Refused, match="reuse"):
        mail.submit(candidate, receipt, root)
    assert len(smtp_server.messages) == smtp_server.connections == 1


def test_ambiguous_smtp_no_retry(approved, smtp_server, tmp_path):
    candidate, receipt = approved
    smtp_server.drop_after_data = True
    root = tmp_path / "outbound"
    result = mail.submit(candidate, receipt, root)
    assert result["status"] == "ambiguous"
    assert json.loads((root / candidate.h0 / "outcome.json").read_bytes())["status"] == "ambiguous"
    with pytest.raises(mail.Refused, match="reuse"):
        mail.submit(candidate, receipt, root)
    assert len(smtp_server.messages) == smtp_server.connections == 1


def test_pre_send_failure_separate(approved, monkeypatch, tmp_path):
    def fail():
        raise OSError("synthetic secret must not escape")

    monkeypatch.setattr(mail, "connect_proton", fail)
    candidate, receipt = approved
    root = tmp_path / "outbound"
    result = mail.submit(candidate, receipt, root)
    assert result["status"] == "pre_send_failed"
    assert not (root / candidate.h0 / "send-started.json").exists()
    assert b"synthetic secret" not in (root / candidate.h0 / "outcome.json").read_bytes()


def test_intent_durable_before_smtp(approved, monkeypatch, tmp_path):
    candidate, receipt = approved
    root = tmp_path / "outbound"
    observed = []

    def before_connect():
        directory = root / candidate.h0
        observed.append(
            {
                "h0": json.loads((directory / "intent.json").read_bytes())["h0"],
                "wire": (directory / "submitted.eml").is_file(),
                "receipt": (root / "receipts" / f"{receipt['id']}.json").is_file(),
            }
        )
        raise OSError("stop before connection")

    monkeypatch.setattr(mail, "connect_proton", before_connect)
    assert mail.submit(candidate, receipt, root)["status"] == "pre_send_failed"
    assert observed == [{"h0": candidate.h0, "wire": True, "receipt": True}]


def test_process_crash_after_start_blocks_restart(approved, smtp_server, monkeypatch, tmp_path):
    candidate, receipt = approved
    root = tmp_path / "outbound"

    def crash(*args, **kwargs):
        raise SystemExit("synthetic process death")

    monkeypatch.setattr(smtplib.SMTP, "sendmail", crash)
    with pytest.raises(SystemExit):
        mail.submit(candidate, receipt, root)
    assert (root / candidate.h0 / "send-started.json").exists()
    assert not (root / candidate.h0 / "outcome.json").exists()
    with pytest.raises(mail.Refused, match="reuse"):
        mail.submit(candidate, receipt, root)
    assert smtp_server.connections == 1


@pytest.mark.parametrize("distinct_receipts", [False, True])
def test_two_processes_only_one_submission(approved, smtp_server, tmp_path, distinct_receipts):
    candidate, receipt = approved
    root = tmp_path / "outbound"
    context = multiprocessing.get_context("fork")
    barrier, results = context.Barrier(2), context.Queue()

    second = receipt.copy()
    if distinct_receipts:
        second["nonce"] = "second-synthetic-authorization"
        second["id"] = mail.digest(mail.encoded({k: v for k, v in second.items() if k != "id"}))

    def attempt(authorization):
        barrier.wait(timeout=10)
        try:
            results.put(mail.submit(candidate, authorization, root)["status"])
        except mail.Refused:
            results.put("refused")

    processes = [context.Process(target=attempt, args=(r,)) for r in (receipt, second)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0
    assert sorted(results.get(timeout=1) for _ in processes) == ["refused", "smtp_accepted"]
    assert len(smtp_server.messages) == smtp_server.connections == 1


def test_dry_run_no_receipt_secret_or_smtp(monkeypatch, readiness, tmp_path, capsys):
    candidate = tmp_path / "candidate.eml"
    candidate.write_bytes(RAW)
    monkeypatch.setattr(mail, "STATE", tmp_path / "outbound")
    assert mail.main([str(candidate), "--dry-run"]) == 0
    assert not mail.STATE.exists()
    assert '"status": "dry_run"' in capsys.readouterr().out


def test_symlink_custody_refuses(approved, tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "outbound"
    link.symlink_to(target)
    with pytest.raises(mail.Refused, match="symlink"):
        mail.submit(*approved, link)


def test_direct_api_no_tty_refuses(monkeypatch, tmp_path):
    terminals(monkeypatch, input_tty=False)
    candidate = mail.parse_candidate(RAW)
    with pytest.raises(mail.Refused, match="TTY"):
        mail.submit(candidate, receipt_for(candidate), tmp_path / "outbound")
    with pytest.raises(mail.Refused, match="TTY"):
        mail.connect_proton()


def test_outcome_write_failure_blocks_resubmission(approved, smtp_server, monkeypatch, tmp_path):
    candidate, receipt = approved
    root = tmp_path / "outbound"
    original = mail.immutable

    def fail_outcome(path, value):
        if path.name == "outcome.json":
            raise OSError("synthetic disk failure")
        original(path, value)

    monkeypatch.setattr(mail, "immutable", fail_outcome)
    with pytest.raises(OSError):
        mail.submit(candidate, receipt, root)
    assert (root / candidate.h0 / "send-started.json").exists()
    with pytest.raises(mail.Refused, match="reuse"):
        mail.submit(candidate, receipt, root)
    assert len(smtp_server.messages) == 1


def test_main_sends_reviewed_snapshot_even_if_file_changes(
    approved, smtp_server, monkeypatch, tmp_path
):
    candidate, receipt = approved
    path = tmp_path / "candidate.eml"
    path.write_bytes(candidate.raw)
    monkeypatch.setattr(mail, "STATE", tmp_path / "outbound")

    def simulated_operator(snapshot):
        assert snapshot == candidate
        path.write_bytes(candidate.raw.replace(b"Synthetic text", b"Changed after review"))
        return receipt

    monkeypatch.setattr(mail, "authorize", simulated_operator)
    assert mail.main([str(path)]) == 0
    assert b"Changed after review" not in smtp_server.messages[0]
    assert b"Synthetic text" in smtp_server.messages[0]


def test_receipt_envelope_tampering_refused():
    candidate = mail.parse_candidate(RAW)
    receipt = receipt_for(candidate)
    receipt["envelope"]["to"] = "changed@fixture.hapaxresearch.com"
    # Even a internally consistent record must bind the actual candidate envelope.
    receipt["id"] = mail.digest(mail.encoded({k: v for k, v in receipt.items() if k != "id"}))
    with pytest.raises(mail.Refused, match="mismatch"):
        mail.gate_output(RAW.replace(mail.SLOT, mail.filled_slot(receipt)), receipt)


def test_no_starttls_never_authenticates(approved, monkeypatch):
    calls = []

    class NoTLS:
        def connect(self, host, port):
            calls.append("connect")

        def ehlo(self):
            return 250, b"local"

        def starttls(self, **kwargs):
            raise smtplib.SMTPNotSupportedError("synthetic TLS absence")

        def login(self, *args):
            calls.append("AUTH")

        def close(self):
            calls.append("close")

    monkeypatch.setattr(mail, "command", lambda args: "synthetic-value")
    monkeypatch.setattr(mail.smtplib, "SMTP", lambda **kwargs: NoTLS())
    with pytest.raises(mail.Refused, match="SMTP setup failed"):
        mail.connect_proton()
    assert calls == ["connect", "close"]
