# GLM-5.3 inert Arm A source packet

`scripts/hapax-glmcp-arm-a` constructs independent requests from a pinned
twelve-case manifest and records responses as data. There is no executor or
native agent harness. The response cannot supply a command, path, URL, import,
callback or next prompt. This measures fixed-input responses; it does not
establish Kimi operational parity or coordinator fitness.

This is source work under `glm53-seat-arm-a-inert-driver-20260929`,
`CASE-SYSTEM-INTEGRITY-20260611`, and the vault's
`coordinator-succession-20260924/GLM53-SEAT-ARM-A-INERT-DRIVER-BRIEF-20260929.md`.
Keep its PR held. Independent acceptance of the exact source and a separately
authorized activation with route/quota/authority admission precede live use.
`--execute` prevents an accidental invocation; it does not grant that admission.
This row authorizes no provider run, installation, scoring, stamp, merge or seat.

BACKED, source tier: the fixed import of `scripts/hapax-glmcp-reviewer` reuses
`read_secret`, `open_no_redirect`, `NoRedirectHTTPHandler` and
`_provider_observation`. It never calls the reviewer workflow or configuration
loader. No existing reviewer source or tests are changed; #4966 remains a
separate reserved packet. The import is private API coupling: independently
recheck this driver when those transport helpers change.

Bindings are fixed to `glmcp/api-key` through the existing secret resolver,
`https://api.z.ai/api/coding/paas/v4/chat/completions`, `glm-5.3`, nonstreaming,
thinking enabled, `reasoning_effort=max`, 32,768 completion tokens and a
900-second timeout. There are no endpoint/model overrides, review stop sequences,
tools, history, PAYG calls or retry branches. These explicit settings differ from
the old reviewer defaults and must be retained in later trial comparisons.

The caller supplies `--inputs`, its SHA-256, `--agents`, its SHA-256 and a new
`--output` directory. Every original system/user hash, combined byte length and
hash must match. The current shared body must match this checkout's authored
body and occur exactly once in each original system field, never in the user
field. The inspected original twelve packets already contain it: no extra
instruction message is added. Each request has exactly those two messages,
without stripping final LF or reading scoring keys/other prompt metadata.
The final serialized body on the request object is retained before transport.

Each attempt exclusively creates a private directory and reserves `manifest.json`
plus `01` through `12`, each with `.request.json`, `.response.json`, `.error.json`
and `.meta.json`. Writes use the open directory descriptor, exclusive no-follow
creation and one write per reserved file. A repeated or symlink output path
refuses; a spent attempt is never resumed or repaired. Empty reserved files
mean that evidence stage was not reached. Errors stop the remaining cases.
Keep the original GLM spent c01 and all refusal artifacts untouched.

Metadata includes source hashes, input/shared-body hashes and offsets, UTC times,
duration, final request hash, same-response model/id/finish/usage and status.
The response model is a provider field, not an independent weights attestation.
Offline fixtures cannot establish live served identity. Raw responses are stored
without execution. A credential echo is redacted and held; exception messages
and HTTP headers are never persisted. No Authorization header is written.

Offline verification calls the real `main` entrypoint and the existing transport
with local fake HTTP I/O, intercepting process, socket and filesystem effects.
Mutation runs additionally use `bwrap --unshare-net`, verifying a distinct
network namespace and empty route table before importing pytest. This physical
boundary remains in force if a mutated caller bypasses the fake opener. The
redirect test clears urllib's cached opener as well. The interrupted first
matrix is preserved separately; it is not a completed mutation receipt.
Synthetic fixtures run in CI. Set `HAPAX_ARM_A_ORIGINAL_INPUTS` to the original
vault `codex-seat-arm-a/inputs.manifest.json` for the twelve-case custody check.
Use a fresh `--basetemp` and pytest cache inside the task's authorized proof
directory; never reuse a spent test directory. Retain mutation logs separately
from independent source acceptance. The initial missing-file red proves only
test-first ordering; the first default-scratch runs were outside declared scope
and are preserved without promotion to scoped acceptance evidence.
