# Agentic-trust verifier provenance

Status: committed on feature branch (source land; not release/activation)  
Date: 2026-08-04  
Base commit: `fcb740f332c242820f13b6482fd8a998bbe8df8a`  
Task: `cc-task-agentic-trust-evidence-only-onboarding-20260804`

This is an unsigned local source-transformation record. It is not an in-toto
attestation, a SLSA provenance claim, a release receipt, or evidence that a
commit, push, PR, activation, admission, or deployment occurred. The record
separates source materials, transformations, outputs, and claim ceilings in the
same spirit as current provenance standards without borrowing their assurance
level.

## Lineage boundary

The package was prepared from selected material in the frozen recovery tree
`/var/tmp/mondlc-recovery-20260804T054951Z/hardened-build`. Exact source inputs
and the recovery handoff are preserved as non-importable text under
`provenance/recovery-inputs-v1/`; their content hashes must match the original
recovery paths. The recovery tree is not imported at runtime.

| Lineage artifact | SHA-256 |
|---|---|
| `RECOVERY-HANDOFF-20260804.md` | `369bd67ed984c15b3090b784e2f152c8f6775a96aa1ddbcb719b31966bdc0510` |
| technical-report `artifact.json` | `2086a20e4a7d90b6f318eee34633b90788096adc70668c6bbe0273653a4316c8` |
| technical-report `report.html` | `45d46dbe1933fad23b58c6d681a98d9bb87805910ac22ed5459e8e5d831551d4` |
| technical-report `source-notes.md` | `63971eb40bb421b81d2b656e5f4fd0026560ff6855bb1872e28378cd2ba5522d` |
| claims-v125 correction | `d8dbaa27e11572f42bda8c0b41a351ab3eb8adab85c21cb6ce1630852d2e958e` |

These hashes establish identity with the presently retained recovery files,
not authorship, chronology, legal clearance, or world truth. The source and
handoff may contain model-assisted work produced under operator direction; no
independent authorship or third-party-content audit is claimed here.

## Source transformations

| Recovery source | SHA-256 | Honest disposition |
|---|---|---|
| `src/conservatory/agentic_contract.py` | `d2ced4940dade61ba33f3e49e51dd7bcb309113bd8d5fc22f0617127e43664b4` | Dependency reduction, import adaptation, formatting, and local hardening into `contract.py`; not byte-exact |
| `src/conservatory/agentic_run_graph.py` | `ee5f4de4596734b67c51a49bae639a7c2de4c80bdb7d07143bb398d4289dc89d` | Semantic derivation with stricter invariants, bounded decoding, typed limits, import adaptation, and formatting; not byte-exact |
| `src/conservatory/evidence_store.py` | `8a553df116e4ea7c86aecd94b027d138477437116dbaa05f9dcf807fbdfe1643` | Manual read-side custody extraction into `custody.py`; writer/publication paths omitted; bounded revalidation added |
| `src/conservatory/terminal_bundle.py` | `c87947e7bc0ac1d55cc04854cf043213d20f1f8a68d8058d3796c88e2291652a` | Manual read-side terminal extraction into `terminal.py`; cross-bindings, typed failures, resource limits, and final sequential revalidation added |
| `src/conservatory/durable_jsonl_sink.py` | `24aca2721be382f6f9398d0c761c772bb40b7574e51fc7e8414e67bbde467b81` | No implementation copied; only `GENESIS_HASH = 0*64` and row schema version `1` retained in `_receipt_chain.py` |
| `tests/test_agentic_contract.py` | `4ab5708b116c0d506bac5662a7cd9d7392bf8289ba74318c8c28111382ea5928` | Adapted seed tests plus new local adversarial coverage; not byte-exact |
| `tests/test_agentic_run_graph.py` | `236c1a6664f283386e88b638e6f32fecdffc5d104c563a2cac6cc8980b632a38` | Adapted seed tests plus new local invariant/limit coverage; not byte-exact |

`errors.py`, `limits.py`, `evidence_receipt.py`, the JSON Schema, package
topology tests, migration-boundary tests, and additional adversarial tests are
new local work. `SealedEvidenceInventory.build` and
`AttemptWitnessPack.build` are pure in-memory value constructors; the package
contains no filesystem writer, publisher, runner, model caller, network client,
or subprocess launcher.

The canonical per-file output hashes and transformation classifications are in
`PROVENANCE.json`. Input copies are provenance material in the source
distribution only and are not installed in the wheel.

## Synthetic known-answer fixture

`tests/fixtures/golden-terminal-v3` is a synthetic known-answer fixture, not an
empirical run and not independent evidence. Its adjacent `anchors.json` is
self-coherent test data: replacing both the fixture and anchors can pass local
semantic tests. A separately located, canonical 54-file checksum list is
checked in at `provenance/golden-terminal-v3.sha256` and is validated by tests,
but it remains unsigned source-control evidence rather than an external anchor.
No deterministic fixture generator or generation receipt survives, so fixture
generation is not claimed reproducible.

## Claim ceiling

- This source-transformation record asserts no run result; it only declares the
  maximum claim a separately verified, caller-pinned receipt could carry.
- Caller digest matches do not authenticate anchor origin or prove pre-run chronology.
- Sequential held-descriptor checks do not make a mutable filesystem atomic or immutable.
- Internal custody consistency does not prove world truth or complete opaque-byte semantics.
- The verifier cannot prove that no model call occurred outside an exclusive append-before-send gateway.
- No application/admission binding, scalar score, efficacy, transfer, model-wide trust, market, KEEP, or PAYS claim follows.
- Energy/hardware fields are unverified technical annotations and cannot affect the evidence or authority path.
- `receipt_sha256` and `run_id` are opaque identity values, not policy evidence;
  only the namespaced `non_supply_evidence_ref` retains the native receipt type,
  and that type remains ineligible for freshness, confidence, equivalence, or authority effects.
- Reference namespacing is only syntactic containment. It cannot identify a
  digest deliberately relabeled under another namespace, authenticate an outer
  receipt producer, or replace a typed resolver/signature contract.
- Successful verification never authorizes a route, execution, spend, public egress, FSM mutation, or external action.

Build and test results are valid only when bound to the final source manifest
and distribution hashes in a separate build receipt. Any stale ignored
`dist/` artifact predating that receipt is non-representative.
