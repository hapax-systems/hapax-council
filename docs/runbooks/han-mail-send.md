# HAN mail submission

Source task: `han-mail-send-capability-20260919`,
`CASE-SYSTEM-INTEGRITY-20260611`. Parent: the 2026-09-19 HAN determination,
sections 3c and 4. This is ordinary outbound correspondence, not the retired
operator-act broker. Runtime activation and the first real send remain separate
operator acts. This task installs nothing and sends no real mail.

## Authorization boundary — unresolved human-presence claim

The command requires TTY stdin **and** stdout, the same terminal device, a
foreground process group, and an explicit `y` after showing the complete candidate,
H0, and envelope. It refuses known agent session environment markers. Both the
direct submit and credential/connection entry points repeat the terminal guard.
There is no `--yes`, receipt-import, SMTP-host override, or retry switch.

Ordinary piped/headless agent invocation therefore refuses before reading the
credential or opening SMTP. **TTY presence is not proof of operator presence.**
An agent with arbitrary execution under the same OS account can allocate a PTY,
change its environment, modify/import Python, and access the same credential
store. The task's premise that agents cannot acquire a TTY is false in the current
runtime. Environment checks are additional workflow guards, not attestation.
Receipt SHA-256 binds bytes; it is not a signature proving who answered.

Do not accept this source as proof that an agent cannot authorize. Production
qualification of that stronger claim remains blocked on an operator/coordinator
decision: accept the cooperative workflow boundary, or separately commission
operator presence and credential custody outside agent control. No OS identity,
hardware authorization, broker, or new authority was invented in this source task.

## Operator procedure after governed review

1. Have the receive owner install the reviewed #4696 `han-mail-pull.service`
   and `.timer`, enable/start the timer, and verify successful pulls. Preserve
   the sibling's successful synthetic ntfy receipt at
   `/store-fast/tmp/han-mail/ntfy-completion-receipt.json`; absence or malformed
   evidence refuses. That receipt records server acceptance, not phone delivery.
   The operator still subscribes the phone to `hapax-han-mail` on the tailnet ntfy
   server. This sender does not read any quarantined body or emit a test notice.
2. Publish the three Proton-provided DKIM CNAMEs, one SPF record containing
   `include:_spf.protonmail.ch` before any `all` mechanism, and valid DMARC.
   Runtime queries use public DNS at `1.1.1.1` and fail closed. An observed CNAME
   target is not proof that Proton actually signed a particular message.
3. Confirm the HAN address and its FileStore reference `proton-smtp-hrl-han`.
   Provision it with `hapax-secret` from the operator's own terminal if needed.
   The command captures the credential in process; it never prints it or stores
   it in the ledger. No fallback account or transport exists.
4. Make a private **copy** of the frozen v3.1 candidate. Supply/verify the real
   recipient in that copy; the new H0 necessarily differs from the frozen
   placeholder draft's `3e55da13…`. Keep exactly the unfilled SEND-TIME line.
   Reverify any time-sensitive claims in the message before authorizing it.
5. Validate without credentials, receipts, state writes, or any SMTP connection:

   ```sh
   uv run --no-sync python -m scripts.han_mail_send /private/candidate.eml --dry-run
   ```

6. After resolving the authorization boundary above, the operator runs the same
   command without `--dry-run` in a separate terminal, reads the complete message
   and envelope, and answers `y` once. Any other answer refuses. The immutable
   in-memory snapshot shown to the operator is the candidate submitted.

Only UTF-8 plain text with exactly one ASCII From, To and Subject header is
supported. Additional, folded, duplicate, MIME, Sender, Resent, Cc and Bcc headers
are refused. So are placeholders, control/bidi characters, ambiguous addresses,
mixed line endings, missing final newline, and oversized messages/lines.

Transport is fixed to Proton submission on port 587, verified STARTTLS then AUTH,
with explicit MAIL FROM and RCPT TO. See [Proton's submission documentation](https://proton.me/support/smtp-submission)
and [domain authentication guidance](https://proton.me/support/anti-spoofing-custom-domain).
Existing paid entitlement is used; this adds no provider spend.

## Bytes and durability

H0 hashes the entire original candidate file, including From, To, Subject and the
unfilled slot. A receipt binds H0, the parsed explicit envelope, UTC authorization
time and a nonce; its ID hashes that receipt payload. Only the SEND-TIME line is
filled from the receipt. `gate_output` restores that one deterministic line and
recomputes H0 immediately before intent publication. H1 hashes the filled file.
Transport adds Date, Message-ID and fixed plain-text MIME headers, and normalizes
line endings to CRLF; `wire_sha256` separately binds these exact submitted bytes.
SMTP dot stuffing is transport framing, removed by the receiver.

The private `~/hapax-state/han-mail/outbound/` ledger holds:

- `receipts/<receipt-id>.json`: create-once authorization/attempt reservation.
- `<H0>/intent.json`: immutable envelope, H0, H1, wire hash, Message-ID, receipt,
  task, AuthorityCase, parent spec and transport.
- `<H0>/candidate.eml` and `submitted.eml`: private recovery snapshots.
- `<H0>/send-started.json`: durable stop signal before MAIL FROM/RCPT TO/DATA.
- `<H0>/outcome.json`: observed outcome, never a delivery claim.

Private directories are mode 0700, facts 0400. Complete temporary files are
fsynced and linked into place exclusively, then the directory is fsynced. The
winning intent creator alone proceeds; even identical existing records refuse.
This provides process/crash arbitration without a reusable lock-file permission.
It is application immutability, not protection against the account owner deleting
the ledger. Keep all records private, including the candidate and recipient.

Connection/TLS/AUTH failure records `pre_send_failed`; failure once the transaction
may have begun records `ambiguous`. DATA 250 records `smtp_accepted`,
`delivery=unestablished`, `settlement=pending_sent_copy`. There are no automatic
retries. A process death after `send-started` with no outcome is ambiguous. Even
a crash or setup failure before it consumes the existing receipt/intent and
blocks automatic resubmission. An outcome persistence failure likewise leaves
the existing intent as a stop signal.

## Separate settlement

Preserve the entire ledger after any failure or uncertainty. The operator later
checks the exact Proton Sent copy against Message-ID, explicit From/To/Subject,
body including the receipt slot, and the retained submitted message. Proton can
add transport headers; raw provider bytes need not have the same wire hash. Record
the evidence and grade separately; neither a matching Sent copy nor SMTP 250
proves delivery/read. Missing, duplicated, or mismatched evidence stays ambiguous.
This tool deliberately has no mailbox reader, settlement writer, or resend/reset
command. Any retry after a failure needs a separate governed disposition; deleting
records or perturbing candidate bytes to evade the stop signal is not recovery.

## Local verification

```sh
uv run --no-sync pytest -q tests/test_han_mail_send.py
uv run --no-sync python scripts/han_mail_send_mutations.py
```

Tests use a local ephemeral SMTP server with STARTTLS and a temporary certificate,
synthetic credentials and explicit rejection of non-loopback connections. They
cover accepted versus lost DATA responses, concurrent processes, process death,
single-use records, every byte outside the slot, and independent preconditions.
The mutation runner alters isolated source copies, never production code/state.
To verify the private frozen draft, set `HAN_MAIL_CANDIDATE_FIXTURE` to a private
copy; its whole-file hash is checked, its placeholder is refused, and only the
test copy's recipient is substituted. The real draft is not published in this PR.
