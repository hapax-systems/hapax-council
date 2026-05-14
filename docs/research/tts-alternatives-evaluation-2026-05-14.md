# TTS Alternatives Evaluation: Supertonic 3, Kokoro, and the 2026 Landscape

**Date**: 2026-05-14
**Request**: REQ-20260509234900 (Supertonic 3 and Kokoro TTS alternatives evaluation)
**Current Stack**: Chatterbox (primary, :4123) + Kokoro 82M (fallback, CPU)

## Executive Summary

The current dual-engine stack (Chatterbox primary + Kokoro fallback) is **well-positioned** in the 2026 landscape. Supertonic 3 is a credible alternative to Kokoro for the CPU fallback role, but does not clearly surpass it. The more interesting development is **Qwen3-TTS** for streaming quality.

## Engine Comparison Matrix

| Engine | Params | Hardware | Streaming | Cloning | Quality | Latency | License | Local |
|--------|--------|----------|-----------|---------|---------|---------|---------|-------|
| **Kokoro 82M** (current) | 82M | CPU | Chunked | No | Good | <0.3s | Apache 2.0 | ✅ |
| **Chatterbox** (current) | 500M | GPU | Yes | Excellent | Excellent | ~0.5s | Apache 2.0 | ✅ |
| **Supertonic 3** | 99M | CPU/ONNX | Yes | No | Good+ | ~0.3s | Proprietary* | ✅ |
| **Chatterbox-Turbo** | ~250M | GPU | Yes | Excellent | Very Good | ~0.3s | Apache 2.0 | ✅ |
| **Qwen3-TTS-0.6B** | 600M | GPU | Native | Yes | Excellent | <0.1s | Apache 2.0 | ✅ |
| **F5-TTS** | ~300M | GPU | Partial | Zero-shot | Excellent | ~0.5s | MIT | ✅ |
| **CosyVoice 2.0** | ~300M | GPU | Native | Yes | Very Good | ~0.2s | Apache 2.0 | ✅ |
| **Piper** | ~20M | CPU | Yes | No | Fair | <0.1s | MIT | ✅ |
| **MeloTTS** | ~100M | CPU | Yes | No | Good | ~0.2s | MIT | ✅ |
| **TADA TTS** (Hume) | ~200M | GPU | Yes | Zero-shot | Very Good | 0.09 RTF | Apache 2.0 | ✅ |

*Supertonic 3 licensing: from Supertone (Korean company), check commercial terms

## Detailed Assessment

### Supertonic 3 (Supertone)

**Strengths:**
- 31 languages (vs Kokoro's ~6)
- Expression tags (`<laugh>`, `<breath>`, `<sigh>`)
- ONNX runtime optimized, ~99M params
- On-device, zero cloud dependency

**Weaknesses:**
- Proprietary licensing (Supertone, Inc.) — commercial terms unclear
- No voice cloning capability
- Less community adoption than Kokoro
- Newer, less battle-tested in production

**Hapax Fit:** Could replace Kokoro as CPU fallback. The expression tags are interesting for non-anthropomorphic personage but would need evaluation against Hapax's specific voice commitments. The proprietary license is a risk.

### Qwen3-TTS-0.6B (Alibaba/Qwen)

**Strengths:**
- Sub-100ms streaming latency on compatible GPU
- Native streaming architecture (designed for it)
- Apache 2.0 license
- Very high naturalness scores
- Built on the Qwen3 LLM architecture (benefits from transformer advances)

**Weaknesses:**
- Requires GPU (600M params)
- Newer model, less production deployment evidence
- Alibaba origin may raise supply-chain concerns

**Hapax Fit:** Strong candidate for **upgrading the primary TTS slot** (currently Chatterbox). The streaming architecture and sub-100ms latency would improve the voice pipeline's responsiveness. Requires GPU but Hapax has GPU capacity.

### Chatterbox-Turbo (Resemble AI)

**Strengths:**
- Distilled one-step decoder (faster than original)
- Maintains excellent voice cloning
- Apache 2.0
- Reduced VRAM requirements

**Hapax Fit:** Direct upgrade to current Chatterbox. Same API surface, better performance. **Recommend evaluation.**

### TADA TTS (Hume AI)

**Strengths:**
- 0.09 RTF (extremely fast)
- Emotional expressiveness built-in
- Zero-shot cloning
- Multi-speaker support

**Hapax Fit:** Interesting for conversational agent pipeline. The emotional expressiveness aligns with Hapax's stimmung/affect systems.

## Recommendations

### Immediate (no code change)
1. **Evaluate Chatterbox-Turbo** as drop-in replacement for Chatterbox. Same API, better performance.

### Short-term research (1-2 sessions)
2. **Benchmark Qwen3-TTS-0.6B** against current Chatterbox on GPU. If streaming latency is confirmed sub-100ms, it's a strong primary candidate.
3. **Test Supertonic 3** expression tags with Hapax's voice personage. If expression control exceeds Kokoro, consider as CPU fallback.

### Not recommended
- **Piper**: Quality too low for Hapax's requirements.
- **MeloTTS**: Good but doesn't exceed Kokoro on any axis that matters.
- **ElevenLabs/Cloud TTS**: Violates locality and privacy principles.

### Preserve
- **Kokoro 82M as CPU fallback**: Proven, Apache 2.0, battle-tested. No urgent reason to replace.
- **Dual-engine architecture**: Primary (GPU) + fallback (CPU) is the right pattern.

## Personage Compatibility Notes

Hapax's voice commitments require non-anthropomorphic personage fidelity. Key considerations:
- Expression tags (Supertonic 3) could enable more controlled non-human vocal affect
- Voice cloning (Chatterbox, Qwen3-TTS) should be evaluated against the existing voice identity
- Speed is important but not at the cost of the voice's distinctive character
- Any engine change must be A/B tested against operator perception of voice identity

## Next Actions

1. Benchmark Chatterbox-Turbo as drop-in upgrade
2. GPU benchmark Qwen3-TTS-0.6B streaming latency
3. Record Supertonic 3 expression tag samples for personage evaluation
4. Update this document with benchmark results
