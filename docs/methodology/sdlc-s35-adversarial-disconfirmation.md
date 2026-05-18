---
stage: S3.5
title: Adversarial Disconfirmation
status: active
authority_case: CASE-DELIBERATIVE-COUNCIL-20260515
parent_spec: docs/superpowers/specs/2026-05-15-deliberative-council-engine-design.md
---

## S3.5 Adversarial Disconfirmation

Stage S3.5 sits between S3 (Review Synthesis) and S4 (Plan Acceptance). Its job
is to try to break claims before they advance to implementation authorization.
The council's posture in this stage is adversarial: search for counter-evidence,
test unstated assumptions, probe scope boundaries. A claim that survives is
stronger for it; a claim that doesn't is caught before it costs implementation
time.

### Trigger Conditions

S3.5 activates when any of the following hold:

1. **Research artifacts present.** The work item includes or references research
   findings, literature reviews, empirical claims, or theoretical commitments
   that could be wrong.

2. **Claim keywords detected.** The plan or spec text contains epistemic claims
   signaled by: "proves", "demonstrates", "shows that", "establishes",
   "confirms", "validates", "is consistent with", "evidence suggests".

3. **Complexity >= L.** The work item's effort class is `large` or above, and
   the risk tier is T1 or T2. Higher complexity amplifies the cost of acting on
   a false claim.

4. **Operator request.** The operator explicitly requests adversarial scrutiny
   via `--mode disconfirmation` or by naming S3.5 in a dispatch.

5. **Governance-sensitive flag.** The task's `risk_flags.governance_sensitive` or
   `risk_flags.public_claim_sensitive` is true. Claims that reach publication or
   governance surfaces must survive disconfirmation.

When none of these conditions hold, S3.5 is skipped and the pipeline proceeds
from S3 directly to S4.

### Behavior: Advisory vs. Blocking

S3.5 is **advisory by default**. The DisconfirmationReceipt is appended to the
authority case quality dossier and visible to the operator, but it does not gate
S4 acceptance.

S3.5 becomes **blocking** in two cases:

| Condition | Effect |
|-----------|--------|
| Verdict is `REFUTED` | S4 acceptance is blocked. The work item must be revised (recommendation: `retract` or `revise`) before re-entering S3.5. |
| Verdict is `INSUFFICIENT_EVIDENCE` and `governance_sensitive` is true | S4 acceptance is blocked. The claim must acquire adequate evidence before proceeding. |

`SURVIVED` and `CONTESTED` verdicts are advisory. A `CONTESTED` verdict with
recommendation `narrow` signals that the claim's scope should be tightened but
does not block advancement.

### Rubric

S3.5 uses the `DisconfirmationRubric` (4 axes, each scored 1-5):

| Axis | Question |
|------|----------|
| `evidence_adequacy` | Does the evidence actually support the claim as stated? |
| `counter_evidence_resilience` | Does the claim survive known counter-evidence and objections? |
| `scope_honesty` | Does the claim accurately bound what it covers and what it doesn't? |
| `falsifiability` | Could the claim be proven wrong? Is there a stated test? |

Scoring thresholds:

- **SURVIVED**: all axis scores >= 4. The claim withstood adversarial scrutiny.
- **REFUTED**: any axis score <= 2. At least one dimension failed under attack.
- **CONTESTED**: scores fall between thresholds. The claim has weaknesses but is
  not broken.
- **INSUFFICIENT_EVIDENCE**: council convergence is `HUNG`, or no valid scores
  were produced. The claim cannot be evaluated with available evidence.

### Output: DisconfirmationReceipt

Every S3.5 run produces a `DisconfirmationReceipt` with the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `claim` | str | The claim under scrutiny, verbatim. |
| `source_refs` | tuple[str] | References to source material supporting the claim. |
| `verdict` | DisconfirmationVerdict | `survived` / `contested` / `refuted` / `insufficient_evidence` |
| `recommendation` | DisconfirmationRecommendation | `accept` / `narrow` / `revise` / `retract` |
| `evidence_for` | tuple[str] | Research findings supporting the claim. |
| `evidence_against` | tuple[str] | Research findings contradicting the claim. |
| `counter_arguments` | tuple[str] | Adversarial challenges raised during deliberation. |
| `scores` | dict[str, int] | Per-axis scores from final aggregation. |
| `confidence_bands` | dict[str, tuple[int, int]] | Per-axis confidence intervals. |
| `attacks_attempted` | tuple[str] | Adversarial attacks the council tried. |
| `attacks_survived` | tuple[str] | Attacks the claim withstood (score held >= 4). |
| `convergence_status` | ConvergenceStatus | `converged` / `contested` / `hung` |
| `receipt` | dict | Full deliberation transcript (phases, models, tool calls). |

### Verdict Semantics

**SURVIVED** receipts must document what was tried and why it failed to break the
claim. The `attacks_attempted` and `attacks_survived` fields are mandatory
non-empty for this verdict. A SURVIVED claim is not proven true - it means the
council could not break it with available tools and knowledge.

**REFUTED** receipts must include specific counter-evidence in
`evidence_against` and the adversarial exchange that produced the refutation in
`counter_arguments`. A REFUTED claim has a concrete identified failure, not
merely low confidence.

**CONTESTED** receipts indicate mixed signals. Some axes survived, others did
not. The recommendation is `narrow` - tighten the claim's scope to the
dimensions that survived.

**INSUFFICIENT_EVIDENCE** receipts indicate the council could not form a
judgment. This is not the same as contested - it means the claim's evidence base
is too thin for any verdict. The recommendation is `revise` - gather more
evidence before resubmitting.

### Integration with Existing Stages

```text
S1 Research
  |
  v
S2 Plan Draft
  |
  v
S3 Review Synthesis
  |
  v
S3.5 Adversarial Disconfirmation  <- this stage
  |
  v (advisory, or blocking if REFUTED / governance INSUFFICIENT_EVIDENCE)
S4 Plan Acceptance
  |
  v
S5 Implementation Authorization
  |
  v
S6 Implementation
  |
  v
S7 Runtime Verification
  |
  v
S8 Release
  |
  v
S9 Post-Merge
```

S3.5 consumes S3 outputs (review synthesis, evidence gathered during research)
and feeds into S4. If S3.5 blocks, the work item returns to S2 (plan draft) or
S1 (research) depending on the recommendation:

| Recommendation | Return to |
|----------------|-----------|
| `accept` | S4 (proceed) |
| `narrow` | S2 (tighten scope, re-draft) |
| `revise` | S1 (gather more evidence) |
| `retract` | Work item closed or replaced |

### Invocation

Programmatic invocation is available from the mode module:

```python
from agents.deliberative_council.modes.disconfirmation import disconfirm

receipt = await disconfirm(
    claim="The reactive engine handles all cascade events within 200ms",
    source_refs=("agents/reactive_engine/cascade.py", "docs/architecture/reactive.md"),
)
```

CLI wiring for:

```bash
uv run python -m agents.deliberative_council \
  --mode disconfirmation \
  --claim "The reactive engine handles all cascade events within 200ms" \
  --source-refs agents/reactive_engine/cascade.py docs/architecture/reactive.md
```

is intentionally deferred until the governing task scope authorizes mutation of
`agents/deliberative_council/__main__.py`.

### Governance Scope Blocker

The current task authorizes mutation of only:

- `agents/deliberative_council/modes/disconfirmation.py`
- `docs/methodology/sdlc-s35-adversarial-disconfirmation.md`

The task acceptance criteria also name package CLI wiring and deterministic test
entry points. Those require changes outside the declared mutation scope
(`agents/deliberative_council/__main__.py` and test files), so they must be
completed under a follow-up task or an explicit scope expansion.

### Limitations

- S3.5 evaluates claims against available evidence. It cannot surface evidence
  the council's tools cannot reach (e.g., runtime measurements not yet captured,
  external systems not indexed).
- The council's adversarial posture is bounded by the models' capabilities. A
  claim may survive S3.5 and still be wrong if the counter-evidence requires
  domain expertise the models lack.
- S3.5 does not replace operator judgment. SURVIVED is "the council couldn't
  break it," not "it's true." REFUTED is "the council found a specific problem,"
  not "it's false beyond repair."
