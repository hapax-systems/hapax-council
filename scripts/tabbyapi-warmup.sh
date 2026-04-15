#!/usr/bin/env bash
# tabbyapi-warmup.sh — Pre-trigger TabbyAPI hybrid-attention JIT compile
# on service start so the first real voice call does not pay the cold-start
# penalty. Called from tabbyapi.service ExecStartPost.
#
# Rationale: per beta's 2026-04-15 substrate research drop at
# docs/research/2026-04-15-substrate-reeval-post-hermes.md §1.5 + §9.1
# (fix #2), the exllamav3 hybrid-attention path for Qwen3.5-9B's Gated
# DeltaNet layers has a "shaky" JIT compile on first call per the
# upstream README (turboderp-org/exllamav3 version 0.0.23+). This warmup
# sends a no-op completion right after service start so the JIT compile
# happens under the service's systemd-managed startup window rather
# than on the first user-facing voice call.
#
# Flow:
#   1. Sleep briefly to let ExecStart's python3 main.py start the uvicorn
#      listener. Model load happens asynchronously (~40-50 s for the
#      current Qwen3.5-9B 5.0bpw).
#   2. Curl a no-op completion with --retry-connrefused and an extended
#      max-time, so curl waits for the HTTP listener to bind.
#   3. Exit 0 unconditionally — the warmup is best-effort. The `-` prefix
#      on ExecStartPost in the unit file makes failures non-fatal, but
#      setting exit 0 explicitly documents the intent.
#
# The warmup request:
#   - model: pinned to the current production substrate name. Update if
#     the substrate changes. (Tracked via the substrate research drop.)
#   - max_tokens: 1 (minimum inference work)
#   - stream: false (one-shot response)
#   - chat_template_kwargs.enable_thinking: false (matches the production
#     local-fast / coding LiteLLM route config at
#     ~/llm-stack/litellm-config.yaml lines 57-73; the thinking-off path
#     is what actually gets exercised in production, so that is what
#     should be JIT-warmed)

set -o pipefail

curl -s \
    --max-time 180 \
    --retry 60 \
    --retry-delay 3 \
    --retry-connrefused \
    -X POST http://localhost:5000/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{
          "model": "Qwen3.5-9B-exl3-5.00bpw",
          "messages": [{"role": "user", "content": "hi"}],
          "max_tokens": 1,
          "stream": false,
          "chat_template_kwargs": {"enable_thinking": false}
        }' \
    > /dev/null 2>&1

# Exit 0 unconditionally — warmup is best-effort.
exit 0
