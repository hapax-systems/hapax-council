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
recheck this driver with both commands below when those transport helpers change.

Bindings are fixed to `glmcp/api-key` through the existing secret resolver,
`https://api.z.ai/api/coding/paas/v4/chat/completions`, `glm-5.3`, nonstreaming,
thinking enabled, `reasoning_effort=max`, 32,768 completion tokens and a
900-second timeout. There are no endpoint/model overrides, review stop sequences,
tools, history, PAYG calls or retry branches. These explicit settings differ from
the old reviewer defaults and must be retained in later trial comparisons.

The caller supplies `--inputs`, its SHA-256, `--agents`, its SHA-256 and a new
`--output` directory. The manifest bytes must also match the source-pinned
`APPROVED_INPUTS_SHA256`; a caller's matching hash cannot authorize a replacement.
There is no CLI/environment override for that pin. Its original source is the
vault's `frame/capability-onboarding/claude-sonnet-5-5-20260928/codex-seat-arm-a/inputs.manifest.json`.
Every original system/user hash, combined byte length and
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
Synthetic fixtures run in CI with a test-only pin; the substitution test keeps
the production pin. CI deselects the `contract` custody test and proves no private
input custody. **Source acceptance requires the vault gate below**, which includes
that test and fails if its binding is absent, unreadable or substituted. It never
skips for missing inputs. Both commands use fake credentials and HTTP responses;
neither runs the provider trial. The original custody test keeps the production
pin and compares all twelve final wire messages, including final LF, against the
private originals. Never commit those originals or treat synthetic success as custody.

From the claimed checkout, bind `PERSONAL_VAULT_PATH` to the declared vault. Run
each command with a fresh proof path; `mkdir` refuses reuse. Default CI recheck:

```bash
arm_proof="$PERSONAL_VAULT_PATH/30-areas/hapax/frame/coordinator-succession-20260924/glm53-inert-source-proof-20260929/recheck-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -m 700 "$arm_proof" && uv run --no-sync pytest tests/scripts/test_hapax_glmcp_arm_a.py -q --basetemp="$arm_proof/tmp" -o cache_dir="$arm_proof/cache"
```

Required vault gate (zero skips; includes custody even when generic CI is green):

```bash
export HAPAX_ARM_A_ORIGINAL_INPUTS="$PERSONAL_VAULT_PATH/30-areas/hapax/frame/capability-onboarding/claude-sonnet-5-5-20260928/codex-seat-arm-a/inputs.manifest.json"
arm_proof="$PERSONAL_VAULT_PATH/30-areas/hapax/frame/coordinator-succession-20260924/glm53-inert-source-proof-20260929/custody-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -m 700 "$arm_proof" && bwrap --unshare-net --bind / / --dev-bind /dev /dev --proc /proc --die-with-parent -- .venv/bin/python -m pytest tests/scripts/test_hapax_glmcp_arm_a.py -q -m '' --basetemp="$arm_proof/tmp" -o cache_dir="$arm_proof/cache"
```

Unsetting `HAPAX_ARM_A_ORIGINAL_INPUTS` and repeating the vault gate with fresh
scratch must fail the custody test, never skip it. Preserve that negative receipt
alongside the actual original-input pass and manifest/file hash metadata.
Use fresh authorized scratch for every mutation; redirect mutants require the
network namespace isolation above. Retain mutation logs separately
from independent source acceptance. The initial missing-file red proves only
test-first ordering; the first default-scratch runs were outside declared scope
and are preserved without promotion to scoped acceptance evidence.
