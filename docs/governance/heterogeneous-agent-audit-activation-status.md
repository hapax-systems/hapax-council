# Heterogeneous Agent Audit — Activation Status

**Status:** DORMANT — trigger condition not met as of 2026-05-02.
**Owner:** Governance (single-operator doctrine).
**Spec:** `docs/superpowers/specs/2026-04-18-heterogeneous-agent-audit-design.md`.
**Companion runtime spec:** `docs/governance/cross-agent-audit.md` (Gemini call-site audit).
**cc-task:** `gemini-heterogeneous-agent-audit-activation-policy` (closed deferred 2026-05-02).

This doc tracks **when to activate** the dormant policy. The policy itself
(at `docs/policies/heterogeneous-agent-audit-policy.md`, NOT YET CREATED)
is authored at activation time per spec §4, not in advance.

---

## 1. Trigger condition

The policy activates when **a non-Claude agent is permitted to author
branches, commits, or PRs directly** (not via packet hand-off through a
Claude reviewer).

Per spec §1: codify the five-surface audit checklist for heterogeneous-agent
**output** (commits, plans, research, hooks, axioms) — meaning artifacts
authored BY the non-Claude agent that land in this repo's history.

The trigger is binary: read-only / packet-relay = dormant; direct authorship = active.

---

## 2. Current posture (2026-05-02)

Two Gemini-related capabilities exist, both read-only or packet-only:

| Capability | PR | Authorship | Triggers? |
|---|---|---|---|
| Read-only sidecar wrapper | #1888 | NO — Q&A only | NO |
| JR Team packet runner (`scripts/hapax-gemini-jr-team`) | #2019 | NO — writes review/scouting packets for Claude senior intake | NO |
| Direct branch/commit authorship | none | n/a | n/a |

Gemini's role today is **perception + advisory packet output**, not direct
repo authorship. The JR Team runner spec is explicit: *"packet-only Gemini
JR Team runner for read-only review/scouting/test-gap/extraction work …
write JR packets … for senior intake only"* (PR #2019 body). Senior intake
= Claude reads the packet and decides whether/how to action it. The packet
hand-off preserves Claude as the sole author of repo artifacts.

**Conclusion:** trigger condition is NOT MET. Policy stays dormant.

---

## 3. Concrete indicators that the trigger has fired

When ANY of these signals appear, this doc should be updated and the policy
activation procedure (§4) should run:

1. **New PR with non-Claude author trailer** (e.g., `Co-Authored-By: gemini-...`
   or absence of the Claude trailer) appears in the open / merged stream.
2. **New script that creates branches via Gemini directly** (e.g., a
   gemini-* runner that calls `git checkout -b` / `git commit` / `gh pr
   create` without packet → senior-intake → Claude commit handoff).
3. **Spec amendment removing the "packet-only" constraint** in PR #2019's
   spec lineage.
4. **Operator inflection** announcing "starting a new Gemini session" or
   equivalent heterogeneous-engagement framing.
5. **Hook adapter** (`hooks/scripts/gemini-tool-adapter.sh`) gains a path
   that emits `git`, `gh`, or other repo-mutating commands directly
   (today it gates Gemini tool calls but does not author repo state).

Detection on these signals is currently MANUAL — no `heterogeneous-agent-detect.sh`
hook exists yet (spec §5 puts it in the activation flow, not pre-activation).

---

## 4. Activation procedure (when trigger fires)

Per spec §6, in this order:

1. **Author the policy doc** at `docs/policies/heterogeneous-agent-audit-policy.md`.
   Contents per spec §4 (under 150 lines):
   - §0 Scope (any non-Claude author).
   - §1 Inventory of existing audit affordances.
   - §2 Five-surface checklist (commits/PRs, plans, research, hooks, axioms).
   - §3 Review workflow (Gemini PR labeled `gemini-authored` → Claude
     `/pr-review-toolkit:review-pr all` → approve or request-changes).
   - §4 Relay protocol deltas (`relay/gemini.yaml`, `last_author_type` field).
   - §5 Activation procedure (this doc's §4).

2. **Create the detection hook** at `hooks/scripts/heterogeneous-agent-detect.sh`
   per spec §5. Initially advisory (`exit 0` regardless), guarded by
   `ADVISORY_ONLY=1` env var so the same script flips to blocking
   (`exit 2`) by toggling the env var.

3. **Register the hook** in `.claude/settings.json` PreToolUse matcher list
   for `Bash` matching `gh pr create` (and equivalent in `.gemini/settings.json`
   if that surface exists).

4. **Flip the hook from advisory to blocking** by setting `ADVISORY_ONLY=0`
   (or removing the guard) when the operator is ready to enforce.

5. **Add a one-line reference to council CLAUDE.md** §Active epics:
   > Heterogeneous-agent audit active. Policy: `docs/policies/heterogeneous-agent-audit-policy.md`.
   > Every non-Claude PR requires `/pr-review-toolkit:review-pr all` before merge.

6. **Optionally add `relay/gemini.yaml`** if Gemini participates in relay
   coordination — only if needed; minimum-viable activation skips this
   until a concrete coordination need appears.

Spec §6 final line: *"When the engagement ends (handoff collapse, operator
dismissal): revert all three changes in one commit, back to dormant."*

---

## 5. Why dormant by default (per spec §7 rejected alternatives)

The spec already rejected three alternatives the operator might be tempted
to revisit. Documented here so future-me doesn't re-evaluate from scratch:

- **Global CLAUDE.md meta-directive** — adds noise across all sessions;
  current steady state is Claude-only so the directive would fire zero
  times per week. Violates CLAUDE.md governance rubric
  (`docs/superpowers/specs/2026-04-13-claude-md-excellence-design.md`).
- **CODEOWNERS rule blocking non-Claude authors on `main`** — heavyweight
  for a dormant concern; false-positive blast radius includes all human
  commits passing through the shared git identity.
- **Scheduled cross-agent drift audit timer** — the one-shot drift audit
  at `docs/research/2026-04-15-gemini-claude-hook-drift-check.md` is
  sufficient until the next heterogeneous engagement.

The runtime LLM-call audit (Claude reviewing Gemini's vision/perception
output) is a SEPARATE concern, governed by `docs/governance/cross-agent-audit.md`
and `shared/audit_registry.py`. It does NOT need this policy to be active —
it's already implemented for runtime call-sites and is independent of repo
authorship.

---

## 6. Acceptance criteria mapping (cc-task closure)

| Criterion | Status |
|---|---|
| Confirm trigger condition: Gemini permitted to author branches/artifacts | NOT MET — read-only sidecar + packet-only JR runner only |
| Activate or update policy doc | DEFERRED — see §4 above; activation procedure documented but not run |
| Ensure detection/advisory/blocking matches current hooks | DEFERRED — hook does not yet exist; creation is part of activation |
| Require Codex/Claude review before merge for Gemini-authored artifacts | N/A while no Gemini-authored artifacts exist |
| Preserve single-operator doctrine + no new auth/users/roles | YES — all proposed activation steps preserve single-operator doctrine; no auth/users/roles added |
| Add or update relay fields for `last_author_type` only if needed | NOT NEEDED at dormant state; optional at activation per §4 step 6 |

The cc-task closes as **DEFERRED-WITH-CONCRETE-BLOCKERS**: activation
trigger documented (§3), activation procedure documented (§4), rationale
for staying dormant documented (§5). Future operator inflection or
spec-amendment that inverts the trigger condition is sufficient to flip
to active.

---

## 7. Cross-references

- Spec: `docs/superpowers/specs/2026-04-18-heterogeneous-agent-audit-design.md`
- Companion runtime spec: `docs/governance/cross-agent-audit.md`
- Sidecar wrapper PR: #1888
- JR Team runner PR: #2019
- Drift audit precedent: `docs/research/2026-04-15-gemini-claude-hook-drift-check.md`
- Handoff collapse history: `docs/superpowers/handoff/2026-04-16-lrr-single-session-takeover-handoff.md`
- Gemini delegation policy (operator-facing rules): `~/.claude/CLAUDE.md` § Gemini Delegation
