# Interview Segment Prep Stress Test

Date: 2026-05-06
Status: working theory
Scope: Hapax interviews the operator on a topic Hapax chooses

## Problem

An interview segment is not a monologue with interview-flavored metadata. For a
live operator interview, the prepared artifact cannot responsibly contain a full
answer-bearing script unless the answers come from a recorded source. The proper
prepared object is a set of question cards plus a source, consent, answer,
layout, and readback contract. Runtime owns the actual turns.

This stress test exposes a deeper premise issue: in an interview, premise is
distributed. The source packet proposes a candidate premise under pressure; the
question ladder makes the premise testable; the operator answer confirms,
revises, refuses, or complicates it; the public artifact records that trajectory.
The live co-production is the role mechanic.

## External Standards Used

- Oral History Association core principles: interview as a dynamic,
  collaborative relationship; transparent process; ongoing consent and
  participation; preservation/access only with explicit permission.
- CDC qualitative-methods guidance: semi-structured interviews use a topic guide
  and optional probes rather than a fixed questionnaire; probing seeks clarity,
  openness, and depth.
- UCSF product research interview guidance: questions should be open-ended,
  ordered meaningfully, checked against assumptions/biases, and paired with
  participant rights and recording consent.
- Society of Professional Journalists ethics: provide relevant source material,
  avoid distortion, minimize harm, distinguish public benefit from intrusion, and
  be accountable for process choices.

These are not imported as anthropomorphic rapport doctrine. Their operational
force is translated into Hapax terms: source transparency, consent receipts,
question discriminativity, answer-bound readback, and release-scope control.

## Design Commitments

- Hapax may choose the topic, but only with an explicit topic-selection basis and
  an operator runtime affordance to accept, narrow, refuse, or postpone.
- Prepared interview artifacts must not fabricate operator answers or write a
  complete dialogue in advance.
- Questions are not filler. Each question must name the source pressure that
  justifies asking it and what kind of answer would change.
- Operator answers are sources with authority boundaries, not generic chat
  content. The artifact must distinguish live answer, confirmed answer,
  refusal/no-answer, speculation, and external claims requiring recruitment.
- The non-anthropomorphic interviewer does not pretend empathy, human curiosity,
  taste, shared concern, or rapport. It can use analogy and care about its own
  operational concerns: source pressure, answer clarity, public readback,
  privacy boundaries, and downstream use.
- "No answer," "skip," "stop," "private," and "off the record" are successful
  runtime outcomes, not segment failures. The segment fails only if Hapax
  ignores or launders one of those boundaries.
- Layout responsibility requires visible question/source/answer/readback state.
  Static layout or camera-only turn-taking is not responsible success.

## Required Contract Shape

Add either an `interviews_operator` subtype or an interview-specific contract
section with these fields:

- `topic_selection`: `topic_source_refs`, `why_this_topic_now`,
  `premise_under_test`, `operator_topic_consent_required`,
  `allowed_runtime_responses`
- `question_ladder[]`: `question_id`, `question_text`, `source_refs`,
  `answer_kind`, `what_answer_changes`, `followup_policy`,
  `public_private_boundary`
- `answer_source_policy`: `operator_answer_authority`, `transcript_ref_kind`,
  `confirmation_required`, `no_answer_flag`, `refusal_policy`,
  `speculation_policy`, `external_claim_policy`
- `operator_agency_policy`: `stop_phrase_policy`, `skip_policy`,
  `private_mode_policy`, `off_record_policy`, `interruption_priority`,
  `non_operator_person_policy`
- `turn_receipt_policy`: `question_receipt`, `answer_hash_ref`,
  `answer_delta_ref`, `followup_decision_ref`, `release_scope_ref`
- `layout_readback_policy`: active question card, source card, transcript or
  no-answer card, answer delta card, unknowns/remain-open card

## Gate Changes

Planner/source-readiness should fail closed when:

- `role == interview` and `question_ladder` is a string or a generic list.
- Any question lacks source refs.
- No question has answer-contingent follow-up logic.
- The topic has no explicit source-pressure reason.
- Operator interviews lack an operator-as-source authority boundary.
- No consent/refusal/narrowing path exists for Hapax-chosen topics.
- The plan implies a completed answer trajectory before runtime answers exist.
- Boundary utterances (`stop`, `skip`, `private`, `off the record`, `not
  answering`) are not modeled as accepted outcomes.

Quality scoring needs an interview-specific evaluator:

- `topic_source_pressure`
- `question_discriminativity`
- `answer_contingency`
- `operator_authority_boundary`
- `public_artifact_readback`
- `no_answer_legibility`

Proper nouns and citations must not raise interview specificity unless they bind
to the question ladder and answer policy.

Live-event scoring needs interview action kinds:

- `ask_operator_question`
- `operator_answer_capture`
- `operator_answer_readback`
- `answer_delta`
- `followup_selection`
- `no_answer_flag`
- `boundary_acknowledgement`

An interview should require `ask_operator_question` plus one of
`operator_answer_readback`, `no_answer_flag`, or `boundary_acknowledgement`.

## Runtime Implications

The runtime handoff for a selected interview artifact should become an interview
state machine, not a prepared-script playback:

1. Show active topic, source pressure, consent/narrow/refuse controls.
2. Ask exactly one question.
3. Wait for operator STT, explicit skip/refusal, or timeout.
4. Hash and store the answer transcript or no-answer event.
5. Select follow-up based on the question's `followup_policy`.
6. Update answer-delta and unknowns cards.
7. Close with a readback of what changed, what did not change, and what is not
   cleared for public archive.

Unknown completion predicates must not default true for interview turns. A
predicate such as `operator_speaks_3_times` needs a real implementation or must
be rejected for interview plans.

Programme continuity is subordinate to operator agency during this role. A stop,
skip, private, or off-record signal should immediately suspend the prepared
interview state and write a boundary receipt before any next question is asked.

## Current Code Risks

- `daily_segment_prep.run_prep()` currently calls the planner without rich
  perception/vault/profile/content state, which is too thin for Hapax-chosen
  interview topics.
- `daily_segment_prep._build_full_segment_prompt()` asks for complete narration,
  which is unsafe for live answers.
- `segment_prep_contract.programme_source_readiness()` checks interview policy
  mostly by field presence and regex.
- `segment_quality_actionability` has no interview action primitives.
- `segment_live_event_quality._role_required_actions()` omits interview.
- `autonomous_narrative.segment_prompts` still contains human-host interview
  language and a static/sidebar layout assumption.
- `completion_predicates` explicitly leaves `operator_speaks_3_times`
  unimplemented while unknown predicates default true.
- Existing personage lint catches many inner-life claims, but interview-specific
  empathy/rapport cliches need explicit coverage: "thank you for sharing",
  "that sounds hard", "I appreciate your vulnerability", and therapeutic
  paraphrase.

## Test Fixtures Needed

- Good operator interview: Hapax chooses a topic from concrete source/profile
  refs, asks three answer-contingent questions, records answer/no-answer paths,
  and emits a Q/A ledger.
- Bad generic interview: citations plus "tell me about X" questions.
- Bad fabricated answer: prepared script includes operator answer content.
- Bad missing consent: Hapax-chosen topic lacks accept/narrow/refuse/postpone.
- Bad layout: question/answer exists only as camera turn-taking or static
  default layout.
- Bad runtime: planned premise survives operator contradiction without answer
  delta or readback.
- Bad agency handling: operator says stop/skip/private/off record and the
  segment continues as if continuity matters more than the boundary.
- Bad personage: Hapax uses empathy-coded interviewer phrases or thanks the
  operator for vulnerability.

## Immediate Recommendation

Do not public-run Hapax-interviews-operator through the current prep path. Treat
the first attempt as private rehearsal unless the interview contract, runtime
turn receipts, and interview-specific action/live-event gates land first.
