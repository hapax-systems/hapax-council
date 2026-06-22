# Interview Segment System — Complete Build-Out

> **Authority Case:** CASE-INTERVIEW-SEGMENT-SYSTEM-20260518
> **Risk Tier:** T2_MODERATE
> **Stage:** S6_IMPLEMENTATION (authorized)

**Goal:** Complete the interview segment system so Hapax can produce and conduct open-style interviews with the operator on the livestream.

**Architecture:** Three tiers across compositor wards, prep pipeline, composition, layout, conversation config, and S-4 voice chain.

---

## Tier 1: NEED (Blockers)

### N1: Interview Wards (3 Cairo sources)
Programme-interview-profile.json declares wards: question_card, transcript_card, unknowns_card. These don't exist in the compositor. Each extends HomageTransitionalSource, reads from SHM state files, polls at 1Hz.
- Files: agents/studio_compositor/interview_question_ward.py, interview_transcript_ward.py, interview_unknowns_ward.py
- Pattern: SegmentContentWard (agents/studio_compositor/segment_content_ward.py)
- SHM: /dev/shm/hapax-compositor/interview-state.json (written by interview conductor)

### N2: Compositor Interview Layout
config/compositor-layouts/segment-interview.json doesn't exist. Positions the 3 interview wards + camera feeds.
- Pattern: segment-tier.json structure with sources, surfaces, tags
- Tags: ["segment", "responsible-layout", "interview"]

### N3: Interview Prep Entry Point
daily_segment_prep.py has no interview handling. Needs question_ladder generation from asset resolver, answer_source_policy, interview artifact emission.
- File: agents/hapax_daimonion/daily_segment_prep.py
- Pattern: follows tier_list/lecture prep paths

### N4: Voice Pipeline PR Merge
PR #3458 (planner executor + Chatterbox TTS) must merge. Without it, daemon crash-loops.

### N5: Torch/Torchvision Pin
chatterbox-tts pulls incompatible torchvision. Needs proper version constraint.

---

## Tier 2: SHOULD DO (Quality)

### S1: Interview Compass Agent
Pre-interview preparation assembling direction from chronicle events, open CC-tasks, sprint state, stimmung trends, profile gaps. Runs 30min before interview.
- File: logos/interview.py (extend generate_interview_plan)

### S2: Interview-Mode Routing Enforcement
Verify interview_mode flag propagates from active INTERVIEW programme through conversation pipeline to model_router. Command-R for grounding.
- Files: agents/hapax_daimonion/conversation_pipeline.py, model_router.py

### S3: Productive Silence Calibration
Programme-interview-profile.json says silence_timeout_s: 180. Verify conversation pipeline reads and respects this. Current default is 15s.
- File: agents/hapax_daimonion/cpal/runner.py

### S4: Reference Voice Tuning for Interview
Exaggeration/cfg_weight (0.35/0.4) may need interview-specific values. Conversational speech has different timbral needs than segment narration.
- File: agents/hapax_daimonion/tts.py

### S5: Stream Deck Interview Preset
One-button interview activation: stream mode public, interview layout, suppress autonomous narration, arm silence window.
- File: config/streamdeck.yaml

### S6: Thread Persistence Verification
max_turns: 120 in profile. Verify compaction threshold doesn't trigger mid-interview.
- File: agents/hapax_daimonion/conversation_pipeline.py

---

## Tier 3: IDEALLY DO (Excellence)

### I1: S-4 Voice Modulation During Interview
VOICE-SELF-MOD scene activates during interview. Information density → Mosaic wet, stimmung tension → Ring resonance. Importance → processing reduction.
- Files: shared/s4_scenes.py (done), agents/hapax_daimonion/s4_voice_modulator.py, shared/s4_midi.py

### I2: Real-Time Answer Delta Display
answer_delta_card ward renders LIVE knowledge model changes after each operator answer.
- File: agents/studio_compositor/interview_answer_delta_ward.py
- SHM: /dev/shm/hapax-compositor/interview-answer-delta.json

### I3: Contradiction Visual Feedback
source_card highlights conflicting profile facts when check_contradictions detects a mismatch.
- File: agents/studio_compositor/interview_source_ward.py

### I4: Question Tree with Branching
Replace flat InterviewPlan topics with QuestionTreeNode follow-up branches based on answer patterns.
- File: logos/interview.py

### I5: Post-Interview Knowledge Flush
Verify facts/insights flush to profiler pipeline on interview completion.
- File: logos/interview.py (flush_to_profiler path)

### I6: AVSDLC Audio Evidence Collection
WER ≤ 5%, phoneme accuracy, speaking rate consistency, 60min LUFS-I drift ≤ 2 LU.
- Per docs/methodology/avsdlc-audio-evidence-contract.md §5

### I7: Audience Metadata
programme_banner_ward shows interview topic. Chat system knows interview is active.
- Files: agents/studio_compositor/programme_banner_ward.py, shared/programme.py

### I8: Async Cloud Research During Interview
Background Qdrant/web/vault lookups fired from operator answers, results integrated into subsequent questions.
- File: logos/interview.py (integrate with affordance pipeline)

---

## Task Dependency Graph

```
N4 (PR merge) ─┐
N5 (torch pin) ─┤
                ├→ N1 (wards) → N2 (layout) → N3 (prep entry) → TRIAL RUN
                │
S1 (compass) ───┤
S2 (routing) ───┤
S3 (silence) ───┤   (parallel, improve quality)
S4 (voice) ─────┤
S5 (streamdeck) ┤
S6 (persistence)┘
                
I1-I8 (excellence) → after trial run validates Tier 1+2
```

## Estimated Total: ~8-10 days across all three tiers.
