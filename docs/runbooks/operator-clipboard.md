# Operator clipboard wire prerequisite

`hapax-clip TARGET [FILE|-]` sends exact literal UTF-8 to an explicitly enrolled
operator desktop. It preserves Unicode, quotes, CR/LF and metacharacters; empty
text is valid. NUL, invalid UTF-8 and more than 1 MiB are refused. FILE must be a
regular file and opens nonblocking; use stdin for streams. `--shell` or `--pwsh`
explicitly prepares a command for manual paste. Delivery never executes it.

This core defines the sender and local framed IPC contract. Native receivers,
durable desktop witnesses and governed deployment remain separate prerequisites.
A missing receiver fails closed. The original two-desktop commission stays open.

## Enrollment and privacy

Create owner-only `~/.config/hapax/clipboard-endpoints.json`, mode 0600:

```json
{"v":1,"endpoints":{"client":{"platform":"wayland","host":"verified-host","user":"desktop-user","host_key":"ssh-ed25519 VERIFIED_PUBLIC_KEY","endpoint":"CANONICAL_PUBLIC_UUID","principal":"1000"}}}
```

Windows uses `platform: windows` and the actual desktop SID. Optional
`identity_file` is an absolute path to an existing owner-only SSH key; enrollment
contains no secret values. Authenticate replacement host keys through an already
trusted path. Keyscan alone is insufficient.

Names match exactly. There is no current-device guess, KDE Connect fallback,
first-socket discovery or noninteractive Windows `Set-Clipboard`. Automatic
selection requires witnessed operator presence and must refuse ambiguity.
Trusted operator identity does not grant future untrusted workloads effect leases.

Describe/set binds endpoint, principal, session, process epoch and independent
request nonces. Success requires matching native byte/hash readback and observed
history exclusion. Digests stay inside encrypted transport; stdout and private
JSONL receipts omit content fingerprints, payload and previews. Input uses stdin
or framed IPC, never payload argv. Send sensitive strings through a tool's stdin
or a private file, without shell interpolation.

Each transport leg has a 12-second deadline, for up to 24 seconds total, pinned
public host keys, bounded replies and no ambient SSH configuration or forwarding.
Unknown, offline, locked, malformed or changed destinations fail with a specific
constant reason and next action; OS details and input paths stay private. A write
may precede a missing ACK: inspect the destination before explicitly retrying.
There is no automatic retry.

Receipts require private ownership/modes and reject symlinks/hardlinks. A
nonblocking append lock protects complete short writes; errors roll back the
incomplete record. Receipt failure after a validated ACK returns status 2 with
acknowledgement metadata on stdout and a repair action, without a second write.

History hints do not contain same-user applications or root. Paging, hibernation
and crash-image protection require separate device encryption acceptance.

## Governed deployment boundary

Use independently accepted, merged `origin/main` through the target's declared
activation binding, `~/.cache/hapax/source-activation/worktree`. The wrapper resolves
its symlink before locating its Python module. Do not install mutable source copies.

Backend slices must declare bounded target profiles, source/unit/build inventory,
exact accepted hashes, preimages and rollback. Personal clients must not inherit
Appendix's services or credential authority. Windows builds/tasks bind to a
commit-addressed accepted release. The fixed command targets
`Clipboard/current/hapax-clip-windows.exe`; that future selected-root alias requires
a governed writer, target/build/task hash attestation and drift refusal. This
core installs neither the alias nor an endpoint or deployment inventory.

After governed promotion, record the source SHA and launcher target:

```sh
readlink -f ~/.cache/hapax/source-activation/worktree
git -C ~/.cache/hapax/source-activation/worktree rev-parse HEAD
sha256sum ~/.cache/hapax/source-activation/worktree/scripts/{hapax-clip,hapax_clip.py}
readlink -f ~/.local/bin/hapax-clip
python3 ~/.cache/hapax/source-activation/worktree/scripts/hapax_clip.py --help
```

These checks do not prove desktop delivery or installed receiver health.

## Regression rechecks

From the source checkout:

```sh
git cat-file -e 2c94fef2741ef9e0f0fca7b45f08eb3f4b20986a:scripts/hapax_clip.py &&
uv run --no-sync pytest tests/scripts/test_hapax_clip.py -q
```

If history is missing, fetch advertised main history with
`git fetch --unshallow origin main` for a shallow clone, or
`git fetch origin main` for a full clone, then retry. The primary command requires
the predecessor object; ordinary shallow runs explicitly skip its tests.

Tests exercise literal boundaries, protocol/ACK identity, private files, FIFO
refusal, option injection, pinned commands, real CLI framing/enrollment/receipts,
timeouts, public errors and launcher symlinks. Actual PR4796 Git source demonstrates
the former executable default, newline conversion, preview/fingerprint and receipt
symlink regressions. Private source-copy mutations break socket ownership,
enrollment, ACK principal, receipt completion and locking; their safety witnesses
turn red while checkout bytes remain unchanged. Fixtures cause no native clipboard
or network effect. Real CLI tests distinguish ACK success from receipt failure.

Before parent closure, checked-in accepted backend helpers must witness unlocked
native desktops: hostile Unicode/metacharacters/mixed CR/LF, empty text, 1 MiB,
stale session/identity, malformed/invalid/oversized input and history/cloud exclusion.
Keep the prior clipboard only in helper memory; compare before restoring, preserve
a concurrent user copy and retain metadata only. Earlier private candidate receipts
cannot replace reproducible accepted-source activation witnesses.
