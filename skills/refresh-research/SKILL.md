---
name: refresh-research
description: "Load research context at session start. Auto-run when: working-mode is research (session-context surfaces it), operator says \"refresh research\" or \"research context\", or starting a voice grounding session. Invoke proactively without asking."
---

Load the current research state and context documents.

Step 1 — Read the research state file:

```bash
cat ~/projects/hapax-council/agents/hapax_daimonion/proofs/RESEARCH-STATE.md
```

Step 2 — Read the research index:

```bash
cat ~/projects/hapax-council/research/RESEARCH-INDEX.md
```

Step 3 — Based on the state file, identify which tier-2 documents are marked as "active" or "in-progress" and selectively read those (typically under `agents/hapax_daimonion/proofs/` and `research/`).

Step 4 — Summarize: current research position, active hypotheses, next steps, and open questions.

After any research session that produces decisions or implementation progress, update `RESEARCH-STATE.md` before ending.
