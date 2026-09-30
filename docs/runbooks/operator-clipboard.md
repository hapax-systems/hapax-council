# Operator clipboard wire prerequisite

`hapax-clip TARGET [FILE|-]` transfers exact literal UTF-8 through an explicitly
enrolled operator SSH route. CR/LF, quotes, Unicode and shell metacharacters are
preserved; empty text is valid. NUL, invalid UTF-8 and inputs larger than 1 MiB
are refused. `--shell` and `--pwsh` explicitly format a command for manual paste;
delivery never executes it. The default has no executable wrapper or preview.

This source slice defines the sender and framed local IPC contract. It does not
install or activate the Windows or Wayland desktop receivers. A missing receiver
fails closed. Native receivers, reproducible desktop witnesses, release bindings
and installation inventory are separate prerequisite source slices under the
original clipboard commission. Its full two-desktop exit predicate stays open.

## Exact enrollment and privacy

Create owner-only `~/.config/hapax/clipboard-endpoints.json`, mode 0600:

```json
{"v":1,"endpoints":{"client":{"platform":"wayland","host":"verified-host","user":"desktop-user","host_key":"ssh-ed25519 VERIFIED_PUBLIC_KEY","endpoint":"CANONICAL_PUBLIC_UUID","principal":"1000"}}}
```

For Windows, use `platform: windows` and the actual desktop SID. An optional
`identity_file` is the absolute path to an existing owner-only operator SSH key.
No secret value belongs in enrollment. Authenticate a host-key replacement through
an already trusted path; a keyscan alone does not establish that trust.

Names must match exactly. There is no guessed current device or fallback through
KDE Connect, first-socket discovery or noninteractive Windows `Set-Clipboard`.
Automatic selection needs a separate witnessed operator-presence binding and must
refuse ambiguity. Existing trusted operator identity is not a fabric-effect lease
for future untrusted workloads.

The describe/set exchange binds endpoint, principal, session, process epoch and
independent request nonces. A set succeeds only after the native receiver reports
matching bytes/hash and observed history exclusion. Content digests are checked
inside encrypted transport; normal stdout and optional private JSONL receipts omit
them to avoid offline guesses of short secrets. Receipts refuse unsafe ownership,
public modes, symlinks and hardlinks. Input travels on stdin and local framed IPC,
never payload argv or subprocess output. Sensitive strings must use a tool's stdin
facility or an existing private file, not shell interpolation.

Each describe/set transport has its own 12-second deadline (up to 24 seconds
for both transport legs), strict public host-key pinning, no ambient SSH
configuration or forwarding, and bounded reply sizes. Unknown, offline, malformed,
locked, changed-session or unacknowledged destinations fail with a public next
action. A timeout can occur after a write but before ACK; inspect the destination
before explicitly retrying. The sender does not retry automatically.

Native history hints are not containment against same-user applications or root.
Encrypted paging, hibernation and OS crash images belong to device encryption
acceptance; this core makes no claim about them.

## Governed source and deployment boundary

Use only merged, independently accepted `origin/main` through the target's
governed source activation binding:
`~/.cache/hapax/source-activation/worktree`. The wrapper resolves its symlink
before locating `hapax_clip.py`, so a governed launcher link refers to that
accepted release rather than an independent user-directory copy.

This PR does not enroll clipboard files in deployment inventory or activate any
endpoint. Do not manually copy the scripts into mutable user install directories.
The backend slices must declare the target's bounded deployment profile, source
and installed-unit/build inventory, exact release hashes, preimages and rollback
before production installation. Personal handhelds must not inherit Appendix's
unrelated services or credential authority. On Windows the native build and task
must bind to a commit-addressed accepted release, with selected-root and compiled
artifact hashes; a mutable executable beside arbitrary copied source is inadequate.
The fixed Windows command names `Clipboard/current/hapax-clip-windows.exe`.
That selected-root alias is a future backend prerequisite, not an installed or
verified release in this slice: its governed writer must select a commit-addressed
accepted build, attest the selected target/build/task hashes and fail closed on
drift before desktop activation. The alias name alone establishes none of this.

Recheck the source prerequisite after governed promotion:

```sh
readlink -f ~/.cache/hapax/source-activation/worktree
git -C ~/.cache/hapax/source-activation/worktree rev-parse HEAD
sha256sum ~/.cache/hapax/source-activation/worktree/scripts/{hapax-clip,hapax_clip.py}
readlink -f ~/.local/bin/hapax-clip
python3 ~/.cache/hapax/source-activation/worktree/scripts/hapax_clip.py --help
```

Record the actual source SHA and launcher target. A core merge or a help response
does not establish desktop delivery, installed receiver health or device acceptance.

## Regression rechecks

From this source checkout, run:

```sh
git cat-file -e 2c94fef2741ef9e0f0fca7b45f08eb3f4b20986a:scripts/hapax_clip.py
uv run --no-sync pytest tests/scripts/test_hapax_clip.py -q
```

Tests cover exact literal boundaries, malformed/duplicate protocol fields, typed
ACK identity, option injection, private receipt/enrollment files, framed IPC,
blocked-input and output/timeout limits, public next-action errors and symlinked
launcher resolution. Historical tests load the actual PR4796 source from Git
(`2c94fef2741ef9e0f0fca7b45f08eb3f4b20986a`) and demonstrate failures of the
former executable default, newline conversion, transcript fingerprint/preview
and symlink-following receipt behavior. They skip explicitly if that Git object
is absent in a shallow checkout; fetch its history to reproduce them. The
primary recheck above requires the Git object before running pytest, so that
acceptance command cannot silently omit the predecessor witnesses. No native
clipboard or network effect is produced by these predecessor tests.

Before closing the parent, accepted native backend witnesses must run from their
checked-in helpers on actual unlocked desktops. Required cases include hostile
Unicode/metacharacters/mixed newlines, empty text, 1 MiB, stale identity/session,
malformed/invalid/oversized input and native history/cloud exclusion. Preserve the
prior clipboard only in the desktop helper's memory, compare before restoration,
preserve a concurrent user copy, and retain metadata without clipboard contents.
The full candidate's earlier private witnesses remain historical evidence; they
cannot substitute for reproducible accepted-source activation checks.
