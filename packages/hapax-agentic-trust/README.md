# hapax-agentic-trust

`hapax-agentic-trust` is an execution-inert verifier for one narrow question:
does an already-produced agentic experiment bundle close over its declared
contracts, exact local bytes, custody inventory, receipt chain, and terminal
outcomes?

It is not a runner, benchmark, allocator, scorer, route, worker, adapter,
watcher, or policy engine. It has no network, subprocess, model, GPU,
Council-runtime, or Spine dependency. Its only top-level operation is
`verify_terminal_projection`, which reads a caller-named local bundle and
returns a frozen, no-authority value projection.

## Observation boundary

The verifier is Linux/POSIX-specific. It holds a directory descriptor, refuses
symlink traversal, checks content, size, mode, link count, and path/inode
binding, revalidates the complete inventory after semantic analysis, and then
rereads the named terminal object before returning.

Those are sequential observations on a mutable filesystem, not an atomic
snapshot. Mode `0400` and one hard link do not make a file immutable; mutation
between observations or after return cannot be excluded. Decision-grade
retention therefore requires a separately established read-only snapshot or
other independently immutable custody. The returned Python value is frozen;
the source filesystem is not made immutable by this library.

## Caller digest pins and claim ceiling

A native `AgenticTrustEvidenceReceiptV1` requires three expected SHA-256 values
together:

- the terminal bundle digest;
- the evidence-root digest; and
- the manifest-snapshot artifact digest.

With all three values omitted, `verify_terminal_projection()` can return only
diagnostic, unanchored mechanical closure. That projection cannot mint a native
receipt. Supplying only some of the three values is rejected.

The verifier establishes only that these caller-supplied values match the
observed content under the SHA-256 assumption. It does not authenticate their
origin, prove that the manifest digest existed before execution, or establish
independent custody. The receipt says this explicitly:

- `anchor_origin_status = caller_supplied_not_authenticated`;
- `chronology_status = not_verified`; and
- `custody_observation_status = sequential_revalidation_not_filesystem_immutability`.

The receipt is demand-ineligible and has no route, policy effect, spend
authority, public-egress authority, scalar score, PAYS/KEEP state, admission
binding, or model-wide claim. `may_authorize_external_action` is always false.
A future application/admission claim would require its own independently
custodied tuple and observer/threat contract.

`receipt_sha256` is content identity, not a typed policy reference. External
citations must use `non_supply_evidence_ref`, whose
`agentic-trust-evidence-receipt-v1:` namespace preserves the native receipt
class and its `policy_effect = none` boundary. Bare receipt digests and bare
`run_id` values carry no provenance type and must not be copied into freshness,
confidence, equivalence, availability, or authority evidence fields.
Namespacing is syntactic containment, not authenticity: once a digest is
deliberately relabeled under an unrelated namespace, its origin cannot be
recovered from the string alone. Any effect-bearing outer receipt therefore
needs its own authenticated producer and scope contract; this package does not
provide one.

Energy and hardware values are optional, caller-supplied technical annotations
without meter identity or measurement provenance. They are bound by the full
receipt digest but excluded from `mechanical_evidence_sha256`, so
they cannot change validity, disposition, efficacy, allocation, promotion,
stopping, quota, payback, or authority. Thermal or capacity control needs a
separate measurement contract. Every receipt fixes
`technical_telemetry_origin_status = caller_supplied_not_authenticated` and
`technical_telemetry_measurement_status = not_verified`.

`parse_unverified()` checks canonical structure and internal arithmetic only.
JSON Schema validation checks the structural vocabulary but not every native
cross-field invariant. A content digest is not issuer authenticity. Evidence
use must call `from_bytes_verified()` or `verify_against_projection()` with a
held-fd projection; an invented envelope can otherwise be structurally valid.

## Explicit use

```python
from pathlib import Path

from hapax_agentic_trust import verify_terminal_projection

projection = verify_terminal_projection(
    Path("/custody/root"),
    "terminal/bundle.json",
    expected_bundle_sha256="...",
    expected_evidence_root_sha256="...",
    expected_manifest_snapshot_artifact_sha256="...",
)
```

There is no console script, automatic import, background observer, filesystem
writer, publisher, executor, or runtime registration. Pure in-memory value
constructors remain internal. Council inventory integration records the
library only as `evidence_only_non_supply`.

## Source, provenance, and license

This package is landed as Council source on the feature branch (PR landing
path only). It is not a release, activation, or admitted runtime dependency.
Human-readable provenance is in [PROVENANCE.md](PROVENANCE.md), and the
machine-readable source/transformation record is in
[PROVENANCE.json](PROVENANCE.json). The package is governed by the Council's
PolyForm Strict 1.0.0 license.
