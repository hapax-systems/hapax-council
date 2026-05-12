---
title: "Sovereign edge case study pack"
date: 2026-05-12
type: application-pack
status: draft
authority_case: REQ-20260512-epistemic-audit-realignment
tags: [sovereign-edge, local-first, privacy, value-extraction]
---

# Sovereign Edge Case Study Pack

## Position

The sovereign-edge story is a case study in running useful AI agency close to
the operator: local-first state, local inference where available, local speech
and perception loops, and explicit cloud routing only when a task needs it.

The claim is intentionally bounded. This is not an air-gapped system, not a
benchmark report, and not a Token Capital proof. It is a support artifact for
the architecture that survived the May 2026 epistemic audit: a single-operator
environment where the default substrate is the operator's machine, the vault,
local services, local IPC, and governed handoff points.

## Case Study Boundary

| Boundary | In scope | Out of scope |
| --- | --- | --- |
| Operator model | One operator, one workstation-centered environment, no multi-user product promise. | Enterprise collaboration, role-based access control, or general SaaS deployment. |
| Privacy posture | Local/private by default: Obsidian vault, local Qdrant, local service bus, `/dev/shm` state, and systemd user services. | Claims that no data ever leaves the machine. Cloud model routes and external APIs exist and must be named when used. |
| Cloud routing | Explicit LiteLLM routes for cloud models through the model alias layer. | Hidden or accidental cloud fallback claims. If a workflow uses Claude, Gemini, GitHub, Google, YouTube, or another external API, say so. |
| Local inference | Local TabbyAPI route on `:5000`, CPU embedding through Ollama-compatible `nomic-embed-cpu`, local visual/speech runtimes. | Unverified throughput, latency, quality, or cost comparisons. |
| Evidence basis | Runtime configuration, service units, package tests, and audit-validated architecture notes. | Token compounding, corpus appreciation, or RAG utilization claims. |

## Runtime Inventory

| Surface | Local role | Evidence path | Claim discipline |
| --- | --- | --- | --- |
| LiteLLM gateway | Model route gateway on `http://localhost:4000`; exposes local and cloud aliases through `shared.config.MODELS`. | [`shared/config.py`](../../shared/config.py) | Cloud use is explicit by alias; do not imply every LLM call is local. |
| TabbyAPI | Local EXL3 inference service on `:5000`; repo service comment says Command-R residency is expected. | [`systemd/units/tabbyapi.service`](../../systemd/units/tabbyapi.service) | Claim local model residency only after checking `/v1/models`; do not claim performance without a receipt. |
| Ollama-compatible embedding | CPU embedding endpoint defaulting to `http://localhost:11434`; embedding model is `nomic-embed-cpu` with 768 dimensions. | [`shared/config.py`](../../shared/config.py) | This supports local document vectors; it is not a claim about answer quality. |
| Qdrant | Local vector database defaulting to `http://localhost:6333`. | [`shared/config.py`](../../shared/config.py) | Retrieval quality is under RAG repair; do not use Qdrant presence as proof of RAG correctness. |
| RAG ingest | Local watchdog using an isolated ingest venv, retry state, memory ceiling, and CPU quota. | [`systemd/units/rag-ingest.service`](../../systemd/units/rag-ingest.service) | Current RAG claims must remain measurement-gated by the epistemic repair track. |
| Logos API | Local FastAPI backend on `:8051`; starts from this repo with secrets injected from the user service environment. | [`systemd/units/logos-api.service`](../../systemd/units/logos-api.service) | Internal control plane, not a public API availability claim. |
| Daimonion | Persistent local voice daemon with local process supervision, STT/TTS working set limits, and programme auto-plan enabled. | [`systemd/units/hapax-daimonion.service`](../../systemd/units/hapax-daimonion.service) | Speech stack is a local runtime surface; publish no latency or accuracy numbers without a dated run. |
| Voice tiers | Local voice transformation catalog, including Kokoro raw/unadorned and processed tiers. | [`shared/voice_tier.py`](../../shared/voice_tier.py) | Good demo surface for local speech control; do not claim universal accessibility or intelligibility. |
| Watch receiver | LAN-local receiver on `:8042` for watch sensor summaries. | [`systemd/units/hapax-watch-receiver.service`](../../systemd/units/hapax-watch-receiver.service) | Operator biometric/context surface; keep public artifacts aggregate and redacted. |
| Visual layer aggregator | Local bridge from Logos/perception state to compositor overlay state. | [`systemd/units/visual-layer-aggregator.service`](../../systemd/units/visual-layer-aggregator.service) | Supports local visual evidence, not a cloud dashboard claim. |
| Studio compositor | GPU-accelerated local camera, recording, HLS, and overlay pipeline with watchdog liveness. | [`systemd/units/studio-compositor.service`](../../systemd/units/studio-compositor.service) | Public egress is separately readiness-gated; do not treat local rendering as public-safe. |
| Imagination surface | Local headless GPU visual surface writing frames for compositor consumption. | [`systemd/units/hapax-imagination.service`](../../systemd/units/hapax-imagination.service) | Visual expression surface; do not overstate semantic understanding. |

## Value Map

| Value axis | Case study claim | Evidence to show | What not to say |
| --- | --- | --- | --- |
| Privacy | The default architecture keeps memory, retrieval state, voice runtime, perception state, and orchestration inside local services unless a route explicitly crosses a boundary. | Configured localhost endpoints, systemd user units, local vault/Qdrant paths, and model alias tables. | "No data leaves the machine" or "privacy guaranteed." |
| Latency | Edge placement makes latency observable and tunable because sensors, voice, IPC, model routes, and visual surfaces are in one local control plane. | `/dev/shm` bridges, local service ports, watchdogs, and dated latency receipts when available. | Any numeric latency claim without a current measurement. |
| Resilience | Core surfaces are supervised by systemd user units with restart policies, memory ceilings, watchdogs, and local degradation paths. | Unit files, journal receipts, and service status snapshots. | "Always available" or "fault tolerant" without soak evidence. |
| Data locality | Work state and long-term memory are file/vault/Qdrant centered, with local ingestion and local embeddings as first-class paths. | `shared.config` paths, RAG source directories, Qdrant settings, and ingest state receipts. | "RAG works" or "corpus value compounds" before the RAG recovery reports are green. |
| Operator sovereignty | The operator can inspect, stop, restart, and patch the runtime because the control plane is local files, local services, and local repos. | `systemctl --user`, journal logs, task files, PRs, hooks, and service definitions. | Multi-operator governance, enterprise admin, or managed-service claims. |

## Separation From Token Capital

Sovereign edge is validated as an architecture story, not as an economic theory.
It should be kept separate from Token Capital until the RAG repair track
produces measured corpus utilization and retrieval quality.

Allowed sovereign-edge claims:

- "The system routes many critical loops through local services and local
  state."
- "Cloud models are explicit route choices, not the default assumption for
  every surface."
- "The architecture makes privacy, latency, resilience, and data-locality
  inspectable because the relevant control points are local."
- "The case study is N=1 and single-operator by design."

Disallowed or measurement-gated claims:

- "Tokens compound in value through reuse."
- "The corpus proves economic appreciation."
- "RAG retrieval demonstrates the system's memory advantage."
- "Local inference is faster, cheaper, or better than cloud inference" without
  dated benchmark receipts.
- "The system is air-gapped, compliant, certified, or enterprise-ready."

## Publication Outline

Working title: **Sovereign Edge AI: A Local-First Case Study in Private Agency**

1. **The frame:** Why local-first AI is not nostalgia. It is an engineering
   stance: default local state, explicit external routes, inspectable
   boundaries.
2. **The case:** A single-operator system with local services for memory,
   voice, perception, visuals, publication gates, and task coordination.
3. **The control plane:** systemd user units, file/vault state, Qdrant, LiteLLM
   aliases, TabbyAPI, Ollama-compatible embeddings, `/dev/shm` bridges.
4. **The boundary:** Cloud routes exist and are useful, but they are named
   routes through the model gateway rather than an ambient assumption.
5. **The value:** privacy by default, inspectable latency, service-level
   resilience, and data locality.
6. **The audit lesson:** Token Capital claims are paused because RAG evidence
   failed; sovereign-edge claims survive because they are architectural and
   directly inspectable.
7. **What to copy:** local service inventory, explicit route table, evidence
   receipts, and no unmeasured performance claims.

One-paragraph abstract:

> This case study describes a single-operator AI environment built around
> sovereign edge constraints: local memory, local service supervision, local
> speech and perception loops, local embedding and retrieval infrastructure, and
> explicit cloud routes for tasks that need larger models. The result is not an
> air-gapped product or an enterprise compliance story. It is a practical
> pattern for making privacy, latency, resilience, and data locality inspectable
> in an AI system that remains useful under real operational constraints.

## Artifact Checklist

Minimum publication pack:

- [ ] Architecture diagram showing local services, local state, and explicit
      cloud exits.
- [ ] Current model inventory receipt:
      `curl -s http://localhost:5000/v1/models` and local embedding model check.
- [ ] Service inventory receipt:
      `systemctl --user status tabbyapi logos-api hapax-daimonion rag-ingest`
      plus the visual stack surfaces used in the demo.
- [ ] Local data path receipt for vault, RAG sources, Qdrant endpoint, and
      `/dev/shm` bridge files.
- [ ] Cloud-route disclosure table listing which workflows use local routes,
      Claude/Gemini routes, GitHub, Google, YouTube, or other external APIs.
- [ ] Privacy redaction pass for screenshots, logs, watch data, voice
      transcripts, and camera frames.
- [ ] Latency/performance section marked "not measured" unless a dated
      benchmark file is attached.
- [ ] Token Capital exclusion note: no compounding, appreciation, or RAG memory
      proof claims in this artifact.
- [ ] Companion demo script with three scenes: local model route, local voice
      loop, local visual/perception state.
- [ ] Final claim scan:
      `rg -n "air-gapped|guarantee|certified|compliant|Token Capital|token compounding|RAG proves|faster|cheaper|better" docs/applications docs/publication-drafts`

## Verification

This pack is docs-only. Suggested local verification:

```bash
git diff --check
```

Suggested evidence refresh before any public derivative:

```bash
curl -s http://localhost:5000/v1/models
systemctl --user status tabbyapi logos-api hapax-daimonion rag-ingest
systemctl --user status hapax-watch-receiver visual-layer-aggregator studio-compositor
```
