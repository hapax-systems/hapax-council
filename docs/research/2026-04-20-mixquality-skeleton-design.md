# MixQuality Skeleton — Design Anchor for Operator's "Mix ALWAYS Good" Invariant

**Date:** 2026-04-20
**Status:** Skeleton — schema + module stub + integration map; impl in follow-up PRs.
**Cascade ask:** "MixQuality (§10.8) is a composite metric: if not implemented, the audit fails SPEC. Start the MixQuality infrastructure design even if the actual impl waits — it's core to the operator's 'mix ALWAYS good' invariant. Commit the skeleton."
**Operator anchor:** "verify the audio interactions are clean, intentional, and driven by the director loop and content programming successfully in such a way that the mix is ALWAYS good."

---

## §1. What MixQuality answers

A single 0..1 gauge — `hapax_mix_quality{window}` — that says "is the broadcast
mix currently good?" The gauge collapses six independent sub-scores so the
operator (and any downstream gating logic, like a "go-live" pre-flight) can
read one number instead of inspecting the whole audio graph.

Below 0.7 → operator-visible warning. Below 0.5 → recommend manual intervention
or fallback to a known-safe mix preset.

The single number is intentionally tight; the six sub-scores are how a human
debugs a low MixQuality reading.

---

## §2. Six sub-scores (matches dynamic-audit §10.1–10.7 framing)

Each emits its own gauge plus contributes to the aggregate.

| Sub-score | Gauge | Range | Pass band | Source |
|-----------|-------|-------|-----------|--------|
| **Loudness conformance** | `hapax_mix_loudness_lufs` | LUFS | -16 to -14 (YouTube target) | EBU R128 meter on the broadcast sink monitor |
| **Source balance** | `hapax_mix_source_balance` | 0..1 | ≥0.7 | Per-source RMS envelope diff vs declared mix preset |
| **Speech clarity** | `hapax_mix_speech_clarity` | 0..1 | ≥0.8 | Concurrent-speaker overlap detector (silence-vs-overlap ratio in voice-active windows) |
| **Intentionality coverage** | `hapax_mix_intentionality_coverage` | 0..1 | ≥0.95 | Fraction of broadcast frames where every audible source has an attribution tag |
| **Dynamic range** | `hapax_mix_dynamic_range_db` | dB | 7..14 | PLR (peak-to-loudness ratio) over rolling window |
| **AV coherence** | `hapax_mix_av_coherence` | 0..1 | ≥0.6 | Cross-correlation between visually-emphasised ward and audio-energy spectrum |

The six sub-scores cover the six failure modes the operator's invariant
distinguishes. They are independent — a stream with great loudness and
poor speech-clarity is still "bad" by the operator's standard.

---

## §3. Aggregate formula (v0)

```
mix_quality = min(
    band(loudness, target=-15, tolerance=1),
    source_balance,
    speech_clarity,
    intentionality_coverage,
    saturating(dynamic_range, 7..14),
    av_coherence,
)
```

`min()` is intentional: the operator's invariant is "mix is ALWAYS good", so
ONE bad sub-score sinks the aggregate. Future iterations may replace with a
weighted geometric mean once we have data on which sub-score correlates best
with the operator's subjective "this sounds bad" reaction.

---

## §4. Where the skeleton lives

```
agents/studio_compositor/mix_quality/
├── __init__.py           # public: MixQuality, sub_scores
├── aggregate.py          # MixQuality dataclass + aggregate formula
├── meters/               # one file per sub-score
│   ├── loudness.py       # EBU R128 LUFS meter (uses pyloudnorm or libebur128)
│   ├── source_balance.py # per-source RMS envelope vs preset
│   ├── speech_clarity.py # VAD overlap detector
│   ├── intentionality.py # source-attribution-tag coverage
│   ├── dynamic_range.py  # PLR computation
│   └── av_coherence.py   # cross-correlation with visual emphasis
└── publisher.py          # 1Hz tick that writes /dev/shm/hapax-mix-quality.json + emits Prom gauges
```

Skeleton (this PR) ships `aggregate.py` + `__init__.py` only. Each sub-score
is a separate follow-up commit so they can be reviewed and instrumented
independently, and so a partially-implemented set still produces a valid
MixQuality (other meters return `None` and the aggregate skips them).

---

## §5. Integration points

- **PipeWire monitor sinks** — each sub-score taps `hapax-livestream.monitor`
  via `pw-cat --record --target hapax-livestream.monitor` to a short ring buffer.
- **Director-loop side** — `mix_quality_gauge` is read by `structural_director`
  to bias `intent_family="audio.*"` recruitments when MixQuality dips.
- **Operator UI** — Logos surface displays the aggregate gauge + the six
  sub-scores in a small mix-health panel.
- **Pre-live gate** — go-live blocks if MixQuality < 0.7 sustained for 30 s
  during pre-flight.
- **Cascade §13** — AV-coherence sub-score becomes the data source for
  cascade's cross-surface coherence audit.

---

## §6. Phased rollout

| Phase | Deliverable | Effort estimate |
|-------|-------------|-----------------|
| 0 (this PR) | Skeleton: aggregate.py stub + design doc | <1 hr |
| 1 | Loudness meter (EBU R128) + publisher | 4–6 hr |
| 2 | Source balance + speech clarity (uses existing VAD) | 4–6 hr |
| 3 | Intentionality coverage (needs source-attribution registry first) | 8–12 hr |
| 4 | Dynamic range + AV-coherence | 6–8 hr |
| 5 | Director-loop gating + Logos UI panel | 4–6 hr |
| 6 | Pre-live gate integration | 2–3 hr |

Total: ~30–40 hr of focused implementation across ~6 PRs after this one.

---

## §7. Open design questions (defer to ops)

1. **Aggregate floor** — `min()` is conservative. Is operator OK that one bad
   sub-score sinks the whole gauge, or prefer geometric mean once we have data?
2. **AV-coherence definition** — should "visually emphasised ward" mean the
   ward with the largest emphasis envelope, OR the ward whose render activity
   has highest delta this tick?
3. **Window sizes** — sub-scores have different natural windows (loudness 3s,
   AV-coherence 5s, balance 60s). Should the published gauge be the latest
   tick or a rolling smoothed value?
4. **Failure modes** — when a sub-score meter crashes (e.g., LUFS lib not
   installed), should the aggregate exclude it (graceful degrade) or set
   MixQuality to 0 (strict fail-closed)?

These choices block Phase 1 implementation. Default in skeleton:
- min() aggregate
- "visually emphasised" = largest emphasis_envelope value
- 5s rolling window
- Graceful degrade (None excluded, log warning)

---

## §8. References

- `docs/research/2026-04-20-dynamic-livestream-audit-catalog.md` §10
- `~/.cache/hapax/relay/cascade-to-alpha-dynamic-audit-execution-20260420.yaml`
- `config/pipewire/README.md` — PipeWire sink topology
- `agents/studio_compositor/audio_ducking.py` — existing audio-state observer pattern
