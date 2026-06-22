---
case_id: CASE-AVSDLC-ENFORCEMENT-20260621
version: 0
stage: S5_AUTHORIZATION_PACKET
status: implementation_authorized
created_utc: 2026-06-22T00:43:11Z
originator: cc-cns-mig
methodology: hapax-sdlc
risk_tier: T1_LOW
source_mutation_authorized: true
docs_mutation_authorized: true
vault_mutation_authorized: true
implementation_authorized: true
release_authorized: false
public_current: false
axiom_mutation_authorized: false
plan_accepted: true
plan_grants_implementation_authority: true
axiom_compliance_checked: true
axiom_compliance_result: "All 5 axioms satisfied (single_user, executive_function, corporate_boundary, interpersonal_transparency, management_governance). No auth/roles added; the receipt key is the operator's existing coord key; errors include next actions; no employer data; no persistent non-operator state; LLMs prepare/humans deliver is unaffected."
consent_contract_required: false
source_mutation_scope: "shared/release_gate.py, shared/governance/coord_capabilities.py, shared/avsdlc_witness.py, scripts/screwm-cns-witness.py, scripts/avsdlc-runtime-witness-daemon.py, systemd/units/hapax-avsdlc-runtime-witness.service, tests/hooks/test_avsdlc_enforcement.py, tests/shared/test_avsdlc_witness.py, evidence/CASE-AVSDLC-ENFORCEMENT-20260621.md"
implementation_scope: "AVSDLC Tier-C enforcement, thin PR 1/N: replace the self-attested runtime-media witness check in the universal release gate with a verified HMAC-signed AVWitnessReceipt (content-hash + active-source-head + OBS-MOVING bound); close the avsdlc_axes:none opt-out for real AV source-path mutations; add the independent runtime-witness producer (screwm-cns-witness --emit-receipt + a standalone daemon/unit that signs per-content-hash receipts and raises P0+RED on live regression). The gates VERIFY; the authoring session cannot mint its own visual verdict."
parent_spec: "~/Documents/Personal/30-areas/hapax/avsdlc-enforcement-design-2026-06-21.md"
---

# CASE-AVSDLC-ENFORCEMENT-20260621

## Purpose

The audio-visual SDLC (AVSDLC) is enforced by a single PR-time, **self-attested**
checkpoint: `shared/release_gate.py` accepted *any* non-empty frontmatter string
as witness evidence (`_has_any_field`), and the witness scripts/dossiers were
never read by code. The live Screwm deploy path (edit on the detached deploy
worktree → recompile → `systemctl restart hapax-darkplaces-v4l2`) opens no PR and
crosses zero blocking AVSDLC gate. By contrast the code SDLC blocks at five tiers
and verifies *independently-executed* artifacts. This case authorizes closing
that gap so a visual/AV release verdict must be EARNED by an independent witness,
not self-declared — the honesty-of-the-integration-surface principle made
mechanical.

## Governing Principles

- executive_function (95): Zero-config; errors include next actions.
- single_user (100): No auth/roles added — reuses the operator's existing coord key.
- interpersonal_transparency (88): A signed receipt that corresponds to live
  reality replaces an unverifiable claim — the gate cannot pretend.
- no_expert_system_rules: enforcement binds to PERCEIVED runtime evidence
  (content-hash + OBS-moving), not hardcoded if-then verdicts.

## Risk Assessment

T1_LOW — additive, reversible, fully test-covered. `shared/release_gate.py` is
the universal PR gate (high fan-out), so the change is deliberately
**backward-compatible and staged**:

- Only the `runtime_media_witness` channel becomes receipt-verified; `visual`/
  `audio` axis witnesses are unchanged (follow-up).
- Hard rejection of legacy plain-string attestation is gated behind
  `require_signed_witness` (**default OFF** until the runtime-witness daemon is
  proven emitting in production), so the change does not wedge any live AV merge
  or closure on landing.
- When the signing key is unavailable, receipt verification fails closed for the
  receipt but degrades to the legacy presence check (INV-5 graceful degradation).
- The no-axes opt-out is closed only for unambiguous AV *source* paths; test
  files are excluded (regression-guarded).
- **Architectural invariant honored:** NO fail-closed ExecStartPre gate is added
  at the live darkplaces restart (that would crash-loop air, since the asset
  install runs inside the v4l2 unit's `ExecStart` with `Restart=always`).
  Enforcement is at the PR/durability boundary; the runtime-witness is a
  standalone observer, never a restart gate.

No axiom or governance-spec modification. All changes revert by commit.

## Research Evidence (S1 Complete)

- `wf_da83946e` — verified the under-enforcement gap (one self-attested control
  vs the SDLC's five verified tiers; the live deploy path bypasses it entirely).
- `wf_4233ae14` — produced the four-tier remediation design (advisory deploy-verb
  gate + ledger; content-hash provenance stamp; **Tier-C BLOCKING** receipt
  verification; independent runtime-witness daemon). Parent spec:
  `~/Documents/Personal/30-areas/hapax/avsdlc-enforcement-design-2026-06-21.md`.

## Plan (S2) — this thin PR (1/N): Tier-C verifier + the independent producer

1. **Receipt substrate** (`shared/governance/coord_capabilities.py`): a signed,
   frozen `AVWitnessReceipt` mirroring the existing `EscapeGrant`/`DispatchCapability`
   HMAC discipline — binds `content_hash` + `active_source_head` + `status` +
   `obs_moving`; a genuine PASS requires `status == pass` AND `obs_moving`.
2. **Gate verification** (`shared/release_gate.py`): the runtime-media witness is
   verified as a receipt (forged / stale / RED / OBS-frozen → blocked); the
   `avsdlc_axes: none` opt-out no longer covers real AV source-path mutations;
   staged `require_signed_witness` switch.
3. **Producer** (`shared/avsdlc_witness.py` + `scripts/screwm-cns-witness.py
   --emit-receipt` + `scripts/avsdlc-runtime-witness-daemon.py` +
   `systemd/units/hapax-avsdlc-runtime-witness.service`): the independent witness
   computes the deployed-gamedir content hash, signs a receipt, and raises P0+RED
   on a live regression. Independent-executor parity with CI.
4. **Tests** (`tests/hooks/test_avsdlc_enforcement.py`,
   `tests/shared/test_avsdlc_witness.py`): forged/stale/RED/OBS-frozen receipts
   fail; a fresh signed PASS bound to the content-hash verifies; the AV source
   path cannot opt out; legacy attestation accepted only when not strict.

**Out of scope (follow-up PRs, per parent_spec):** Tier-A deploy-verb gate +
ledger; Tier-B provenance stamp in the install script; precheck committed-bytes
match + autoqueue/post-merge-deploy wiring; the `screwm-deploy` wrapper; the
gamedir reconcile timer; the governance doc; flipping `require_signed_witness` on.

## Success Criteria

1. `uv run pytest tests/hooks/test_avsdlc_enforcement.py tests/shared/test_avsdlc_witness.py` green.
2. `ruff check` clean on all touched files.
3. A forged / empty / RED / OBS-frozen runtime-media witness no longer passes
   `evaluate_avsdlc_release_gate`.
4. A real AV source-path mutation declaring `avsdlc_axes: none` yields
   `required=True` (cannot opt out).
5. No existing release-gate / precheck / reconciler test regresses (backward
   compatible; staged switch default-off).
