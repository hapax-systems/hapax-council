#!/usr/bin/env bash
# session-standing-rulings.sh — SessionStart hook: the operator's standing rulings.
#
# Prints the accepted wording (row E7, its R6) and nothing else: three rulings, each quoted
# from its stored record with the record's sha256 cited. It is its own hook so that its
# output stays short enough to be shown whole. Claude Code saves a long hook output to a
# file and shows the model only its opening ~2,000 characters, and session-context.sh's
# preamble runs far past that in this repository.
#
# The text is pinned by tests/hooks/test_session_standing_rulings.py. Change it only with a
# newly accepted wording. The hook reads nothing, so it behaves the same for every
# SessionStart source and payload.
cat <<'STANDING_RULINGS'
## Standing operator rulings

Quoted from the stored records. Where following a quoted ruling would break an authored instruction, the authored instruction governs; two texts that only speak to the same situation do not conflict.

- 2026-10-10T14:39:22.241Z (sha256 c1ad9cb1…), answering a session that had stopped to ask the operator to choose how to get a post through a publish gate that a stopped service was blocking, although its own option (a) kept that service off and would still go through independent review, with three more decisions queued for the operator: "first of all, *I* did not stop litellm. second, I never expressed any opinion of litellm in general. third, you cannot stop moving for these kinds of questions. I am not a gate. i am not an epistemic gate. i am not an operational gate. hrl-Han has operations and standards."
- 2026-10-11T18:29:29.411Z (sha256 105d538c…; REQ-20261011T1829), answering a status reply that said a naming-convention recommendation and nine more decisions were waiting on the operator: "I want to make a point: this and other things *like* it do *not* need to go back to me. These are *decicions*. Why is it assumed that I am more capable at rendering these *types* of decisions than the epistemic operations than we have fashioned? I am not an epistemic authority."
- 2026-10-11T18:33:08.902Z (sha256 f1fe77f9…) and 18:33:51.248Z (sha256 eae9853f…; REQ-20261011T1833), two messages sent 42 seconds apart after native harness memory notes had been written (grouped here by the author): "memory is an inappropriate place for almost anything. whatever is in memory cannot be operationalized. this is not the first time we have noted this about native harnesses and capability shapes" and "memory.md is a liability"
STANDING_RULINGS
