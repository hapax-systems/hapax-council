# Vocal Chain Imagination Integration — Context Injection + Proactive Utterance

## Summary

Sub-project 3 of 3. Imagination bus fragments influence the voice daemon's conversation pipeline in two ways: low/medium-salience fragments inject into the conversation LLM's context as "Current Thoughts" (shaping what the system says), and high-salience fragments can trigger proactive utterance (the system speaks unprompted when conditions are right).

## Context Injection

The conversation LLM's system prompt gains a dynamic "Current Thoughts" section, populated from the imagination bus's `stream.jsonl` on every conversation turn.

### Source

Read `/dev/shm/hapax-imagination/stream.jsonl` — last 5 lines (most recent fragments). Sub-millisecond read.

### Salience-Graded Framing

Fragments are formatted with salience-dependent framing:

- **salience < 0.4** — "(background)" prefix. Passive context. The LLM sees them but isn't instructed to act on them. Subtle influence on word choice, framing, awareness.
- **salience 0.4-0.6** — "(active thought)" prefix. Actively framed as recent thoughts the system may reference if relevant to conversation. If the operator asks what the system is thinking about, draw from these.
- **salience > 0.6** — these have already escalated to impingements and are handled by the cascade/proactive path. Still included in context for coherence.

### Format

```
## Current Thoughts
These are things you've been thinking about recently.

- (background) The desk has been quiet for a while, weather is clearing.
- (background) The operator's heart rate has been steady at 68 bpm.
- (active thought) A connection between the drift report and the scout evaluation
  for local-llm-coding — both suggest consolidating inference infrastructure.
```

### Integration

Injected via the existing system prompt assembly in the conversation pipeline. No new LLM agent — augments the existing one. Assembled fresh on each conversation turn (not cached).

## Proactive Utterance

When imagination produces something worth saying out loud, the system initiates a conversational turn without being prompted.

### Trigger Path

```
Imagination loop → fragment salience ≥ 0.8 → escalation to impingement (existing)
    → ProactiveGate.should_speak() checks pass
    → generate utterance from fragment narrative + content references
    → speak via existing TTS pipeline
    → MIDI vocal chain already active from same impingement (cross-modal)
```

### Proactive Gate

All conditions must be true:

| Condition | Source | Check |
|-----------|--------|-------|
| High salience | Fragment | `salience >= 0.8` |
| Operator present | Perception state | `activity` not in ("idle", "away", "unknown") |
| Operator not speaking | VAD state | No active voice activity detected |
| Conversational gap | Voice daemon state | Last utterance (either direction) > 30s ago |
| TPN not active | DMN state | `tpn_active == False` |
| Cooldown elapsed | ProactiveGate internal | Last proactive utterance > 120s ago |

### Utterance Generation

The fragment's narrative and content references are formatted as a conversation prompt:

```
You just had a thought worth sharing with the operator. Express it naturally
and concisely — 1-3 sentences. Don't announce that you had a thought; just
share the insight as if continuing a natural conversation.

The thought: {fragment.narrative}

Related content: {resolved content reference summaries}
```

This goes through the normal conversation LLM → TTS pipeline. The MIDI vocal chain is simultaneously active from the same impingement — the voice sounds energized/engaged, not flat.

### Cooldown

120 seconds after a proactive utterance before another can occur. Prevents the system from repeatedly initiating. Resets on operator-initiated conversation (if the operator starts talking, the cooldown clears — the system shouldn't hold back in an active conversation).

## File Layout

| File | Responsibility |
|------|---------------|
| `agents/imagination_context.py` | `format_imagination_context(stream_path) -> str` — read stream.jsonl, format salience-graded prompt section |
| `agents/proactive_gate.py` | `ProactiveGate` class — gate checks for proactive utterance |
| `tests/test_imagination_context.py` | Context formatting, salience grading, empty stream, malformed lines |
| `tests/test_proactive_gate.py` | Each gate condition independently, combined pass/fail, cooldown behavior |

## Integration Points (modifications, not new files)

- Voice daemon conversation pipeline: inject `format_imagination_context()` into system prompt assembly
- Imagination loop escalation path: call `ProactiveGate.should_speak()` on high-salience fragments

These integration modifications are deferred to a separate voice daemon wiring task after all 3 sub-projects are complete.

## Testing

### imagination_context.py
- Empty stream: returns minimal "Current Thoughts" section with "(mind is quiet)"
- Single fragment: correctly formatted with salience prefix
- Multiple fragments: last 5 only, ordered recent-last
- Salience grading: < 0.4 gets "(background)", 0.4-0.6 gets "(active thought)", > 0.6 gets "(active thought)"
- Malformed lines in stream.jsonl: skipped without error

### proactive_gate.py
- Gate passes when all conditions met
- Gate fails on each individual condition:
  - Salience too low (0.7)
  - Operator not present
  - Operator speaking (VAD active)
  - Recent utterance (< 30s gap)
  - TPN active
  - Cooldown not elapsed
- Cooldown resets on operator-initiated conversation
- Cooldown elapsed after 120s
