# Session Protocol: Data Collection

## Pre-Session Checklist

```
1. Daemon active:     process-compose process list (voice = running)
   Fallback:          systemctl --user is-active hapax-voice
2. Presence:          cat ~/.cache/hapax-voice/perception-state.json | jq .presence_state
   Must be:           "PRESENT"
3. Langfuse:          curl -s http://127.0.0.1:3000/api/public/health
   Must return:       {"status":"OK"}
4. Redis policy:      docker exec redis redis-cli -a redissecret CONFIG GET maxmemory-policy
   Must be:           noeviction
5. Experiment config: cat ~/.cache/hapax/voice-experiment.json
   Verify:            correct phase and component flags
6. Code state:        git log --oneline -1
   Must match:        the frozen commit hash for this collection phase
```

## Session Rules

- **Minimum 5 turns** per session for inclusion in primary analysis
- Talk naturally — do not perform for the experiment
- If the session dies before 5 turns (crash, timeout, lost connection),
  note it and start a new session. The short session is flagged, not excluded.
- Multi-speaker sessions are allowed but must be flagged
- No debugging or system testing during data collection sessions

## Post-Session Checklist

```
1. Wait 30 seconds for Langfuse batch flush
2. Verify all turns have scores:
   - context_anchor_success present
   - turn_pair_coherence present (Cycle 2+)
   - frustration_score present
   - total_latency_ms > 0
3. If scores missing: check docker logs langfuse-worker for errors
4. Save session JSON to proofs/claim-*/data/
5. Commit with descriptive message
6. Push to main
```

## Code Freeze Rules

During data collection:

**ALLOWED** (not experiment variables):
- Langfuse infrastructure fixes (Redis, trace export)
- Wake word fuzzy matching additions
- TTS/audio quality fixes that don't affect response content

**NOT ALLOWED** (experiment variables):
- Token limits or word cutoff changes
- System prompt modifications
- Scoring function changes
- Tool enable/disable
- Any change to the conversation thread mechanism
- Any change to how scores are computed

**If in doubt**: don't change it. Document the issue and fix after collection.

## Deviation Documentation

Any deviation from this protocol during collection must be logged:

| Session | Deviation | When Decided | Impact Assessment |
|---------|-----------|-------------|-------------------|
| (fill)  | (fill)    | (fill)      | (fill)            |
