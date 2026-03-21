---
title: "Running Observations"
---

## 2026-03-20

- Cycle 1 Phase B complete. 20 sessions. BF=3.66 on word overlap metric.
  Effect +0.029 vs target +0.150. Metric is wrong — word overlap penalizes
  good grounding (abstraction, synthesis, paraphrase all reduce overlap).
- Sustained 0.7-0.8 anchor sequences in Phase B sessions 2-4 during deep
  discussion — never seen in baseline. The thread IS doing something.
- Confabulation is a recurring theme (sessions 7, 12, 17). Hapax fabricates
  visual perception, calendar events, system status when tools disabled.
  Separate from grounding but revealed BY grounding (thread enables
  multi-turn accountability).
- Session 4: co-developed Bayesian mode/tool selection concept. The system
  being tested helped design the next thing to test. Recursion.
- Session 5 (baseline): "trying to think clearly in a room full of alarms."
  Emergent self-reflection without any continuity features. The architecture
  itself enables grounding the counter-position cannot replicate.
- Phase A' reversal needed before pilot is complete. Mandatory defense
  against operator awareness confound.

## 2026-03-19

- Built experiment infrastructure: stats.py, experiment_runner.py,
  eval_grounding.py, trajectory scores, turn-pair coherence.
- Fixed 8 voice pipeline bugs: timeout recovery, response length,
  pre-roll buffer, echo feedback, tool hallucination, Whisper prompting,
  wake word matching, presence-consent integration.
- Collected 17 baseline sessions. Key finding: grounding does NOT improve
  within sessions (trajectory -0.241). Turn 0 always strongest (neutral
  default, no thread to anchor to).
- Gemini system prompt leak (clipboard capture) demonstrates all 5 failure
  modes of profile-retrieval in a single "set an alarm" interaction.
