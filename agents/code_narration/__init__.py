"""LRR Phase 9 hook 1 — daimonion code-narration impingement producer.

Detects when the operator is actively working on code (editor window focused
+ recent file changes in project dirs) and emits low-strength impingements
to ``/dev/shm/hapax-dmn/impingements.jsonl``. Daimonion's existing consumer
picks them up; CPAL speaks them through the operator's TTS path.

Design contract (per research doc 2026-04-15-daimonion-code-narration-prep.md):

- Source: ``code_narration`` — distinct from other sensor/pattern sources so
  consent gates + cooldown policies can treat it specifically if needed.
- Modality: auditory by virtue of strength + source; CPAL is the consumer.
  The producer does not encode modality directly — that's a consumer concern.
- Strength: 0.25 (low) — code-narration should be ambient, not interrupting.
  Above the boredom floor but below any urgent signal.
- Throttling: one narration per project directory per 120s, enforced by the
  producer's persisted ``last_narrated_at`` map.

No LLM-synthesized narrative in this iteration. Template form:
  ``"Working on {file} in {project} — {change_summary}"``
Full LLM-driven narrative is a Phase 9 follow-up; this ships the integration
path first.

Not in scope:
- Consumer-side whitelist / consent gate for code_narration (may be added
  if consumer filtering is observed to be needed once this runs live).
- Stream-mode-aware gating (the transcript firewall §4.B will add read-
  side gates; this producer writes regardless — the write-side invariant
  from spec §3.4.B ("writes continue unchanged") is preserved).
"""
