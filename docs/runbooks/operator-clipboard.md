# Operator desktop clipboard

`hapax-clip TARGET [FILE|-]` sends exact UTF-8 text to an explicitly enrolled
operator desktop. Its default is literal text, preserving CR, LF, quotes,
metacharacters and Unicode. Empty text is valid; NUL, invalid UTF-8 and text over
1 MiB are refused. `--shell` and `--pwsh` deliberately format an executable
command for manual pasting; neither executes it. There is no payload preview.

This succeeds only after an independent native desktop readback matches the
request's bytes/hash and history exclusion. The receipt binds the request nonce,
public endpoint identity, actual desktop principal/session and process epoch.
The describe/write split refuses session changes and endpoint restarts.

This replaces the PR4796 / `2c94fef` route discovery and command-wrapping default.
KDE Connect share-text, first Wayland-socket discovery and Session-0 Windows
`Set-Clipboard` are not fallback routes. They did not establish the required
privacy/desktop receipt. Unknown, offline, locked or ambiguous destinations
fail with a next action. A timeout may occur after a write but before its ACK:
inspect the destination before explicitly retrying; no automatic retry follows.

## Enrollment and authority

Transport uses the operator's existing SSH credential. Enrollment declares a
replaceable host coordinate, public pinned ed25519 host key, public endpoint UUID
and expected desktop UID/SID. It contains no secret or copied master material.
Use exact enrollment names; no prefix, fuzzy name or guessed current machine.
Automatic current-device selection needs a separately witnessed operator-presence
binding and is intentionally not implemented by guessing online/unlocked hosts.

An agent using the existing trusted operator account can call this command. This
does not grant future untrusted fabric jobs an effect lease. Same-UID code and
root/administrator already have desktop authority; the endpoint is not a
containment boundary against them. Native history/cloud hints do not prevent
other applications, malware or operator-initiated paste from reading text.

Create `~/.config/hapax/clipboard-endpoints.json`, owned by the invoking user,
mode 0600, with this structure. Substitute verified bindings, not example keys:

```json
{
  "v": 1,
  "endpoints": {
    "client": {
      "platform": "wayland",
      "host": "verified-host-coordinate",
      "user": "desktop-user",
      "host_key": "ssh-ed25519 VERIFIED_PUBLIC_KEY",
      "endpoint": "PUBLIC_CANONICAL_UUID",
      "principal": "1000"
    }
  }
}
```

For Windows use `platform: windows` and the actual user SID as `principal`.
An optional `identity_file` is an absolute path to an existing owner-only SSH
private key; the CLI references it without printing or copying its bytes. SSH
disables ambient configuration/forwarding and uses only the declared pinned host
key. If the default identity is inappropriate, enroll the correct file explicitly.
Enrollment itself requires reading/verifying the actual host key through an
already trusted path. `ssh-keyscan` alone does not authenticate a replacement.

Install sender `hapax-clip` and `hapax_clip.py` together in `~/.local/bin/` from
the accepted commit; preserve any previous files and verify postimage hashes.
To send a string from an agent, supply stdin through the tool's input facility
or a pipe. Never interpolate sensitive text into shell commands or argv. An
existing private UTF-8 file may also be supplied. The optional `--receipt PATH`
stores metadata only in an owner-only directory/file and refuses symlink,
hardlink and public-mode files. Default stdout is also metadata only.
The payload SHA256 stays inside the encrypted request/readback comparison;
normal CLI output and receipts omit it to avoid offline guesses of short secrets.

## Wayland desktop endpoint

Requirements: an actual local unlocked KDE Wayland session, stock Python,
`loginctl`, `findmnt`, `wl-paste`, and `wl-copy` with measured `--sensitive`
support. Install accepted
`hapax_clip.py` and `hapax_clip_wayland.py` in
`~/.local/share/hapax/clipboard/`, and the accepted unit in
`~/.config/systemd/user/hapax-clipboard-wayland.service`. Preserve preimages.

Create owner-only `~/.config/hapax/clipboard-endpoint.json`:

```json
{"v":1,"endpoint":"PUBLIC_CANONICAL_UUID","principal":"1000"}
```

The UUID must match the sender's enrollment. Read back the actual desktop
user manager's `WAYLAND_DISPLAY` and `XDG_RUNTIME_DIR`; do not substitute the
first socket discovered under `/run/user/`. The endpoint binds one active
unlocked session and verifies compositor socket ownership. If multiple sessions
are active, or the binding is missing/stale, reconcile the desktop environment
before starting it. Start/enroll from that actual graphical user session:

```sh
systemctl --user daemon-reload
systemctl --user enable --now hapax-clipboard-wayland.service
systemctl --user status hapax-clipboard-wayland.service
```

The user unit follows `graphical-session.target`, has bounded resources, disables
swap and core dumps, and uses a mode-0600 Unix socket in a mode-0700 runtime
directory. IPC checks kernel `SO_PEERCRED`. Requests are serialized; expired or
already disconnected producers are refused before the write.

The endpoint owns one `wl-copy --foreground --sensitive` process. Payload input
uses a memory file descriptor, never argv. The stock native helper stages stdin
in a temporary file before unlinking it, so `TMPDIR` is explicitly confined to
an owner-only directory on verified `tmpfs`. There is no disk fallback. Staging
must already be unlinked before acknowledgment; helper failures clean the owned
RAM directory. A separate `wl-paste` reads exact text and
`x-kde-passwordManagerHint=secret`; the native owner and unlocked session are
rechecked. No GUI callback queue or hidden focus window is needed.

KDE's [history model](https://invent.kde.org/plasma/plasma-workspace/-/blob/master/klipper/historymodel.cpp)
excludes a clipboard with that secret hint before insertion into history. Other
compositors need a measured native exclusion mechanism before enrollment; the
current Wayland acceptance applies to KDE. The native
[wl-copy implementation](https://github.com/bugaevc/wl-clipboard/blob/master/src/wl-copy.c)
supplies the sensitive hint before text is offered. The earlier windowless GTK
candidate failed actual desktop acceptance and is not an activated fallback.

## Windows desktop endpoint

Install accepted `hapax-clip-windows.cs` and `hapax-clip-windows.ps1` together in
`%LOCALAPPDATA%\Hapax\Clipboard`. Protect the directory with the operator user's
ACL; other ordinary users must not be able to replace scripts/enrollment. Add
`endpoint.json` using the same three fields above and the actual desktop SID.
The interactive server validates that SID, a nonzero active WTS session and the
unlocked input desktop. The Session-0 SSH client only relays framed input through
the owner's named pipe; it never calls a Session-0 clipboard setter.

Build the native stdin relay from the same accepted C# source with
`hapax-clip-windows.ps1 -Mode Build`, preserving any previous executable first.
Bind the compiler result and source hashes in the activation receipt. The fixed
SSH command invokes that executable with `--client`. It borrows the inherited
OpenSSH pipe handle and explicitly uses overlapped I/O. The synchronous .NET
console reader failed at one 32 KiB packet in the native candidate; the corrected
reader passed the full 1.4 MiB framed request. No payload belongs in a PowerShell
command, encoded command, temporary disk file or process argument.

From the operator's actual Windows user session, enroll a **limited** interactive
logon task. Preserve/export any existing task before replacement. The action is:

```text
powershell.exe -NoProfile -NonInteractive -STA -File "%LOCALAPPDATA%\Hapax\Clipboard\hapax-clip-windows.ps1" -Mode Server
```

Expand the absolute path in the task definition. Use Interactive logon type,
limited run level, a logon delay sufficient for the desktop to become active,
and IgnoreNew instance policy. Do not use SYSTEM or store an account password.
Start the task and inspect its state/actual desktop ACK before claiming
activation. A locked desktop refuses writes; the server remains alive to serve
the same session after unlocking. A user switch/session restart must fail the
old binding and start the new user's enrolled endpoint. A failed startup should
be diagnosed and restarted from the actual unlocked desktop.

The pipe ACL and impersonated peer SID limit IPC to the enrolled user. Native
clipboard data is immediate `CF_UNICODETEXT` owned by a hidden message window.
The endpoint publishes these
[Microsoft exclusion formats](https://learn.microsoft.com/en-us/windows/win32/dataxchg/clipboard-formats)
before text and verifies them after independent readback:

- `ExcludeClipboardContentFromMonitorProcessing`
- `CanIncludeInClipboardHistory` as DWORD zero
- `CanUploadToCloudClipboard` as DWORD zero

UTF-16 conversion preserves exact UTF-8-representable text, including CR/LF.
The clipboard sequence number must remain unchanged through readback and
exclusion checks. Competing writes are refused, not overwritten/retried.
Pipe reads/writes/connects have deadlines and size limits; errors are generic
and cannot include payload or base64. The server keeps no history or log.

The application avoids persistent payload files and native clipboard history;
this does not assert encrypted RAM, page files, hibernation images or a protected
OS crash snapshot. Those belong to the device encryption/recovery plan. Existing
same-user desktop applications can also read the ordinary clipboard.

## Verify and roll back

Run focused tests:

```sh
uv run --no-sync pytest tests/scripts/test_hapax_clip.py tests/scripts/test_hapax_clip_wayland.py -q
```

Before production activation, use owned bounded candidate endpoints in the
actual desktop sessions. Send nonsecret Unicode/quotes/metacharacters, mixed
CR/LF, empty text and the 1 MiB boundary through the SSH sender. Verify native
byte/hash ACK and history formats. Send stale epoch/session, duplicate fields,
oversized/invalid input and wrong-principal requests; none may acknowledge an
effect. Unit tests separately check actual Unix peer credentials, private
receipts and bounded subprocess output/time. Verify exact installed source and
task/unit hashes; a compiled DLL, running process or PTY OSC52 alone is not a
desktop receipt.

Candidate witnesses keep any prior clipboard only in memory. Compare the
current clipboard against the owned probe before restoring; preserve a
concurrent user copy. Do not export clipboard history or prior contents into
evidence. Stop/remove only owned candidate services/tasks after receipt and
preserve their failed/successful metadata. Accepted-source review/release and
production activation remain separate predicates.

Rollback stops/disables only the enrolled owned endpoint unit/task and restores
its exact guarded preimages/enrollment. Do not kill other desktop processes,
alter global login cleanup or guess a fallback route. Restore sender preimages
only if the current files still match the owned installed postimages.
