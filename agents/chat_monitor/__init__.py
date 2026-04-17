"""LRR Phase 9 §3.1 — chat monitor structural analyzer.

Reads YouTube live-chat messages (already collected upstream by
``scripts/chat-monitor.py``) and emits a compact structural summary to
``/dev/shm/hapax-chat-signals.json``. Downstream consumers — stimmung
collector, director-loop activity selector, attention-bid source —
read that SHM to reason about audience engagement *without* touching
individual messages (no sentiment, no per-author state, consent-safe).

Structural metrics only, per spec §3.1:

* thread_count: how many parallel conversation threads are active in
  the window (embedding-cluster proxy).
* novelty_rate: ratio of novel bigrams in the window (0-1).
* participant_diversity: unique-author count / message count (0-1).
* semantic_coherence: mean pairwise cosine similarity across messages
  (0-1); higher = audience talking about one thing.

Pure functions. Injection seams for tests. The ``chat-monitor.py``
script can adopt these helpers directly; until it does, the SHM file
is produced by the script's existing flow.
"""
