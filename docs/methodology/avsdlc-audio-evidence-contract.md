
---

## Audio Evidence Contract: AVSDLC-002

### Purpose

This contract defines what constitutes sufficient audio evidence for quality
review. It applies to all work items classified as having audio impact under
Gate 1 of the authority case, with particular emphasis on interview segment
requirements.

### Measurable Audio Quality Dimensions

#### 1. Broadcast Loudness and Dynamics

| Dimension | Standard | Target | Measurement method | Failure predicate |
|---|---|---|---|---|
| Integrated loudness (LUFS-I) | EBU R128 / ITU-R BS.1770-5 | [-16, -12] LUFS-I | `scripts/audio-measure.sh 30 hapax-broadcast-normalized.monitor` | Outside range on 30s representative sample |
| True peak (dBTP) | EBU R128 | <= -0.5 dBTP | Same measurement script | Exceeds -0.5 dBTP |
| Short-term loudness ceiling | EBU R128 | < -6 LUFS-S sustained >300ms | `lufs_panic_cap.py` real-time monitor | Panic cap triggers on normal program material |
| Loudness range (LRA) | EBU R128 s1 | 5-15 LU for mixed program | Extended measurement (5min+) | LRA < 3 (over-compressed) or > 20 (uncontrolled dynamics) |

#### 2. Signal Chain Integrity

| Dimension | Standard | Target | Measurement method | Failure predicate |
|---|---|---|---|---|
| Golden chain completeness | Hapax broadcast chain architecture | All stages present and connected | `scripts/hapax-audio-routing-check` | Any stage missing, bypassed, or disconnected |
| TTS capture path | AVSDLC-002 S5 ISAP | TTS output reaches broadcast-normalized via full chain | `pw-link -l` verification | TTS output bypasses MPC/L-12 analog path |
| Clipping/distortion | Broadcast engineering practice | No digital clipping, no analog overload (L-12 clip LED) | Listening check + L-12 meter visual inspection | Clip LED illumination, audible distortion |
| Noise floor | Broadcast engineering practice | Background noise inaudible during silence periods (< -60 dBFS) | Silence capture measurement | Audible noise during intended silence |
| Feedback detection | Broadcast engineering practice | No feedback loops in signal path | `feedback_loop_detector.py` real-time monitor | Feedback oscillation detected |

#### 3. TTS Voice Quality

| Dimension | Standard | Target | Measurement method | Failure predicate |
|---|---|---|---|---|
| Word intelligibility | Adapted: speech intelligibility research | WER <= 5% on representative utterances under stream conditions | Manual transcription spot-check against TTS input text | WER > 5% on spot-check sample |
| Phoneme accuracy | Adapted: phonetics | No systematic phoneme dropping or substitution | Listening check on known-difficult words (proper nouns, technical terms) | Consistent phoneme errors on same word class |
| Speaking rate consistency | Adapted: prosody research | Coefficient of variation of speaking rate <= 15% within a single utterance type | Rate measurement across 10+ utterances of same type | CV > 15% (erratic pacing) |
| Pitch range | Adapted: prosody research | F0 range sufficient for prosodic contour (not monotone), not excessive (not sing-song) | Pitch tracking on representative samples | Monotone (< 2 semitones range) or excessive (> 12 semitones within sentence) |
| Pause distribution | Adapted: prosody/broadcast pacing | Inter-sentence pauses 0.3-1.5s for declarative content; question-following pauses 1.5-4.0s in interview mode | Timing measurement | Pauses outside ranges for utterance type |

#### 4. Non-Anthropomorphic Voice Personage

These criteria derive from the non-anthropomorphic segment prep framework
(2026-05-06 spec) and the HARDM anti-anthropomorphization principle.

| Dimension | Standard | Target | Measurement method | Failure predicate |
|---|---|---|---|---|
| Empathy-coded language absence | Hapax-native: personage lint | Zero instances per segment | Automated lint + manual review | Any instance of: "I understand how you feel," "thank you for sharing," "that sounds hard," therapeutic paraphrase, concern-coded intonation |
| Operational vocabulary use | Hapax-native: segment prep framework | Operational terms ("the segment states," "source pressure") used instead of experiential terms ("I think," "I feel," "I believe") | Content review of TTS input text | Experiential self-attribution in TTS content |
| Voice identity consistency | Hapax-native | Same voice character across all utterances within a session | Listening check across session | Voice character shifts between utterances (different "personality") |
| Non-simulated rapport | Hapax-native: interview stress test spec | No simulated human interviewer rapport behaviors | Content + delivery review | Simulated warmth, concern, curiosity as personality traits rather than operational states |

#### 5. 60-Minute Sustained Quality (Interview-Specific)

Interview segments may run 30-60 minutes. Quality must not degrade over time.

| Dimension | Standard | Target | Measurement method | Failure predicate |
|---|---|---|---|---|
| Loudness stability | EBU R128 | LUFS-I drift <= 2 LU between first and last 5-minute windows | Compare measurements at session start vs. end | LUFS-I drift > 2 LU |
| TTS latency consistency | Hapax-native | TTS response latency does not degrade >50% vs. session start | Timestamp delta measurement (question end -> TTS start) | Latency doubles vs. first 10 minutes |
| Voice quality stability | Hapax-native | No perceptible voice quality degradation | Listening comparison: first 5 min vs. last 5 min | Audible quality difference (artifact increase, clarity decrease) |
| Spectral consistency | Adapted: broadcast engineering | Spectral centroid variance <= 20% across session (same utterance type) | Spectral analysis via audio self-perception daemon | Spectral drift > 20% for same utterance type |
| Silence handling | Hapax-native: interview stress test spec | Operator silence (thinking, refusing, skipping) does not trigger TTS timeout or rushed follow-up | Behavioral observation during silence periods | System interrupts operator silence before 4.0s minimum |

### Evidence Collection Protocol

For any work item with audio impact:

1. **Pre-change baseline:** capture current loudness, routing, and TTS quality measurements
2. **Post-change measurement:** capture same measurements after implementation
3. **Delta report:** document what changed and whether targets are still met
4. **Live witness (S7):** for changes affecting broadcast path, capture 30s+ of live broadcast audio and verify targets in real conditions

For interview-specific work:

5. **Extended session test:** run TTS for 15+ minutes and compare first-5-min vs. last-5-min quality
6. **Silence handling test:** verify system behavior during 5s, 10s, and 30s operator silences
7. **Pacing coherence test:** verify question-answer rhythm across 5+ question cycles

### Reference: Current TTS Engine Stack

As of 2026-05-14, per `docs/research/tts-alternatives-evaluation-2026-05-14.md`:

- **Primary:** Chatterbox (~500M params, GPU, excellent quality, voice cloning, ~0.5s latency)
- **Fallback:** Kokoro 82M (CPU, good quality, <0.3s latency)
- **Under evaluation:** Chatterbox-Turbo (drop-in upgrade candidate), Qwen3-TTS-0.6B (streaming latency candidate)

Any TTS engine change requires re-running the full audio evidence contract
against the new engine before release authorization.

### Failure Modes This Contract Prevents

1. Audio routing change ships without verification that the broadcast chain is complete.
2. TTS engine upgrade ships without A/B perceptual comparison.
3. Interview goes live with voice quality that degrades after 20 minutes.
4. Anthropomorphic language enters TTS content without being caught by review.
5. Loudness changes are accepted because "the LUFS meter says it's fine" while a listener can plainly hear something wrong (REQ-AVSDLC-010: metrics cannot override perceptual judgment).
6. A "small" audio change breaks the golden chain and nobody checks.

---
