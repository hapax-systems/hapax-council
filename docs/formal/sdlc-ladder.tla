---------------------------- MODULE sdlc_ladder ----------------------------
(***************************************************************************)
(* Formal model of the Hapax SDLC statechart (coordination reform master   *)
(* design section 4.2 / 4.5).  Stages S0..S11, the S3.5 disconfirmation     *)
(* branch, and a BLOCKED pseudo-state with an operator escape edge.         *)
(*                                                                          *)
(* ADVISORY-WITH-LEDGER ONLY (NEW-1).  TLC findings inform the operator and *)
(* are appended to the ledger; they MUST NOT gate the reform that fixes the *)
(* statechart.  A failing or timed-out proof raises a flagged advisory,     *)
(* never a release/merge block — a self-blocking proof gate would rebuild   *)
(* the freeze-blocks-thaw meta-catch-22 in the verification layer.          *)
(*                                                                          *)
(* The runtime companions of these invariants live in                      *)
(* shared/sdlc_invariants.py (pure, advisory trace checks) — that is where  *)
(* INV-4 and INV-5 (process-level properties, below) are actually checked.  *)
(*                                                                          *)
(* Naming note: the design's filename is sdlc-ladder.tla; the TLA+ module   *)
(* identifier must use an underscore (TLA+ identifiers forbid '-').  To run *)
(* TLC, point it at a copy named sdlc_ladder.tla (the deferred CI sub-slice *)
(* handles this rename).                                                    *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS Tasks   \* the (finite) set of in-flight task identifiers

Stages == {"S0", "S1", "S2", "S3", "S3_5", "S4", "S5", "S6",
           "S7", "S8", "S9", "S10", "S11", "BLOCKED"}
Terminal == {"S11"}
Blocked  == {"BLOCKED"}

\* Legal successors of a stage: forward ladder, the S3 -> S3.5 disconfirmation
\* branch, the S6/S7 -> BLOCKED fall, and the BLOCKED -> {S6, S0} operator escape.
\* S11 is the sole terminal (its empty successor set is permitted by INV-1).
Next(s) ==
    CASE s = "S0"      -> {"S1"}
      [] s = "S1"      -> {"S2"}
      [] s = "S2"      -> {"S3"}
      [] s = "S3"      -> {"S4", "S3_5"}
      [] s = "S3_5"    -> {"S4", "S0"}
      [] s = "S4"      -> {"S5"}
      [] s = "S5"      -> {"S6"}
      [] s = "S6"      -> {"S7", "BLOCKED"}
      [] s = "S7"      -> {"S8", "BLOCKED"}
      [] s = "S8"      -> {"S9"}
      [] s = "S9"      -> {"S10"}
      [] s = "S10"     -> {"S11"}
      [] s = "S11"     -> {}            \* terminal
      [] s = "BLOCKED" -> {"S6", "S0"}  \* operator escape — always non-empty
      [] OTHER         -> {}

VARIABLE stage   \* stage[t] is the current stage of task t

TypeOK == stage \in [Tasks -> Stages]
Init   == stage = [t \in Tasks |-> "S0"]

\* A task advances along any legal transition (this also realises the escape
\* from BLOCKED, since BLOCKED's successors are non-empty).
Step(t) == \E s2 \in Next(stage[t]) : stage' = [stage EXCEPT ![t] = s2]

\* A non-terminal, non-blocked task may fall to BLOCKED (a gate refusal).
Fall(t) == /\ stage[t] \notin (Terminal \cup Blocked)
           /\ stage' = [stage EXCEPT ![t] = "BLOCKED"]

Nxt == \E t \in Tasks : Step(t) \/ Fall(t)

\* Weak fairness on advancement gives every task the chance to make progress,
\* which is what makes the liveness property (INV-2) meaningful.
Fairness == \A t \in Tasks : WF_stage(Step(t))
Spec     == Init /\ [][Nxt]_stage /\ Fairness

(*-------------------------------- INVARIANTS -----------------------------*)

\* INV-1 Deadlock-freedom: from every reachable state, every non-terminal
\* task has at least one enabled transition (no non-terminal dead-end).
INV1_DeadlockFreedom ==
    \A t \in Tasks : (stage[t] \in Terminal) \/ (Next(stage[t]) # {})

\* INV-3 Escape: every BLOCK state has a transition out (an operator can
\* always leave it).  No escape hatch is a sink.
INV3_Escape ==
    \A t \in Tasks : (stage[t] \in Blocked) => (Next(stage[t]) # {})

\* INV-2 Liveness (temporal property, checked against Spec): every task
\* eventually reaches a terminal stage.
INV2_Liveness == \A t \in Tasks : <>(stage[t] \in Terminal)

(*------------------------- PROCESS-LEVEL INVARIANTS ----------------------*)
(* INV-4 Authority-always-escapable and INV-5 Cognition-always-writable are *)
(* properties of the ENFORCEMENT process, not of this statechart: the       *)
(* escape must work with the kernel DOWN (reversible work fails open,        *)
(* irreversible fails closed) and cognition surfaces are always writable.    *)
(* They cannot be expressed over `stage` alone, so they ship as the runtime  *)
(* trace checks check_inv4_authority_escapable / check_inv5_cognition_       *)
(* writable in shared/sdlc_invariants.py, exercised by a daemon-down chaos   *)
(* test.  See master design section 4.5.                                     *)
=============================================================================
