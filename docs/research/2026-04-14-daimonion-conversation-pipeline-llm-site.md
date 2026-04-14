# daimonion conversation pipeline has a second LLM call site — extends drop #9

**Date:** 2026-04-14
**Author:** delta (beta role)
**Scope:** Surfaced during a voice-pipeline audit. Drop #9's
council-wide prompt-cache audit inspected
`agents/hapax_daimonion/pipeline.py` (the pipecat-based
builder) and marked daimonion as a pipecat-LLMService site.
**`conversation_pipeline.py:1013` is a second, independent
LLM path inside the same package** that calls
`litellm.acompletion` directly and was not in drop #9's
table. Asks: what does that path look like, and does the
drop #9 fix apply?
**Register:** scientific, neutral
**Status:** correction to drop #9's inventory — adds one
caller site, same fix pattern

## Headline

**Three findings.**

1. **`agents/hapax_daimonion/conversation_pipeline.py:1013`
   calls `await litellm.acompletion(**kwargs)` directly**,
   not via pipecat's OpenAILLMService. Drop #9 audited
   only `pipeline.py:94 _build_llm` which is the pipecat
   LLMService construction — the actual per-turn LLM call
   in production lives in this 1886-line conversation
   pipeline. **Drop #9's caller inventory is missing this
   row.**
2. **The kwargs include `max_tokens: _TIER_MAX_TOKENS[tier]`,
   `temperature: 0.7`, `stream: True`, `tools:
   recruited_tools`, `timeout: 15`.** Messages are
   assembled from a running conversation history plus,
   when a screen is injected at line 611, a base64 PNG
   image block. **Plain string system content, no
   `cache_control` annotation** — same gap as
   director_loop (drop #8) and the sites in drop #9.
3. **Vision-injected turns are unusually expensive** —
   base64 PNG frames added to the user message can run
   50-200 kB of text tokens each, on top of the
   conversation history and tools. Cost per turn on
   vision-enabled conversations can easily exceed a
   director_loop reaction's cost by 2-3×.

**Net impact.** The voice conversation hot path — the
thing that fires every user turn — has the same prompt-
cache gap as director_loop. Drop #9's bundled prompt-cache
sweep should include this site. Fixing it buys the same
25-50% input-token reduction as the other Anthropic-routed
LLM call sites.

## 1. The hot-path LLM call

```python
# agents/hapax_daimonion/conversation_pipeline.py:984-1013
kwargs = {
    "model": f"openai/{_model}",         # e.g. "openai/claude-sonnet"
    "messages": _messages,                # ← system + history + user
    "stream": True,
    "max_tokens": _TIER_MAX_TOKENS.get(
        getattr(self, "_turn_model_tier", ""), _MAX_RESPONSE_TOKENS
    ),
    "temperature": 0.7,
    "api_base": _voice_litellm_base,
    "api_key": os.environ.get("LITELLM_API_KEY", "not-set"),
}
if self.tools and self._tool_recruitment_gate:
    recruited_names = self._tool_recruitment_gate.recruit(_last_user_text)
    if recruited_names:
        kwargs["tools"] = [
            t for t in self.tools if t["function"]["name"] in recruited_names
        ]
elif self.tools:
    kwargs["tools"] = self.tools

kwargs["timeout"] = 15
response = await litellm.acompletion(**kwargs)
```

Notable:

- **Direct `litellm.acompletion`** — same shape as
  `fortress/deliberation.py:157` from drop #9 § row 5.
- **Tool recruitment gate** — only recruited tools are
  included in the request. That's a meaningful cost
  optimization (the drop-9-audit message payload doesn't
  carry all 31 tool schemas on every turn, just the
  recruited subset).
- **15-second timeout** — hard cap on LLM turn latency.
  For a voice conversation that's already at the edge of
  what's tolerable. If the LLM times out, the turn fails
  and the TTS gets nothing.
- **Model alias from `_model` variable** — dynamic,
  set by a tier router (`_turn_model_tier`).

The `_messages` list construction happens earlier — system
prompt, conversation history, optional screen injection at
line 608-614:

```python
# agents/hapax_daimonion/conversation_pipeline.py:608-614 (abbreviated)
if screen_injected:
    user_content_parts.append({
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{screen_injected}"},
    })
```

## 2. Cost profile per turn

Assuming a typical voice turn:

- System prompt (persona + tool schemas + operator context):
  ~3 000 tokens
- Running conversation history (last N turns): ~1 500 tokens
- User utterance: ~50 tokens
- Recruited tool schemas (gate reduces from 31 to ~3-5):
  ~500 tokens
- **Without screen injection: ~5 000 prompt tokens/turn**

With screen injection:

- Plus base64 PNG of screen capture (typically 50-200 kB
  of base64 text, depending on resolution)
- At ~3 chars/token avg for base64: ~16 000-65 000 tokens
- **With screen injection: ~21 000-70 000 prompt tokens/turn**

Vision turns are 4-14× more expensive than text-only turns.

## 3. Drop #9 extension

Adding row 6 to the drop #9 caller inventory:

| # | file | client | cache_control? | fix effort |
|---|---|---|---|---|
| **6** (new) | `agents/hapax_daimonion/conversation_pipeline.py:984-1013` | `litellm.acompletion` direct | **no** | **S** — same structured-content-block swap as director_loop |

Drop #9 § row 2 still applies to `pipeline.py:109` which
is the pipecat-based path — but that's a separate pipeline,
likely for a different dispatch mode (not the primary
conversation hot path). Worth clarifying in drop #9's
table that daimonion has **two** LLM paths, not one.

**The fix for this site is identical** to director_loop's
3-JSON-key change from drop #8:

```python
# Before
_messages = [
    {"role": "system", "content": system_prompt_string},
    ...
]

# After
_messages = [
    {
        "role": "system",
        "content": [
            {
                "type": "text",
                "text": system_prompt_string,
                "cache_control": {"type": "ephemeral"},
            }
        ],
    },
    ...
]
```

Caveat: when screen injection adds a vision block, the
**image is NOT cacheable** because it changes per turn.
Only the text system prompt prefix is cacheable. That's
actually fine — Anthropic's prompt cache matches on
prefix bytes, and the text block before the image block
stays cached.

## 4. Other daimonion perf observations (noted, not drops)

Scanning `conversation_pipeline.py` for additional
observations:

- **Memory footprint**: live `systemctl show` reports
  `MemoryCurrent=2.6 GB`. That's Whisper STT model
  (large-v3, ~3 GB peak on GPU) plus conversation
  history caches plus Python overhead. Not alarming.
- **CPU cumulative**: 3917 s over session uptime. High
  because whisper inference runs on GPU but the
  pipeline driver is Python-side and accumulates CPU
  time on every STT/LLM/TTS hop.
- **15-second LLM timeout** is worth flagging — if
  LiteLLM's fallback chain kicks in after a timeout,
  the voice turn is already dead. For
  reliability-critical conversations, a shorter primary
  timeout (~8 s) with an explicit fallback dispatch
  might be cleaner.

None of these rise to a full drop on their own. Flagging
for awareness.

## 5. Follow-ups

1. **Extend drop #9's sweep** to include
   `conversation_pipeline.py:984-1013`. Same 3-JSON-key
   fix. Should ship with the director_loop fix as part
   of a bundled prompt-cache pass.
2. **Drop #9 table correction**: daimonion has two LLM
   paths (`pipeline.py` pipecat + `conversation_pipeline.py`
   direct-litellm). Current table rows 2 (pipecat) stays;
   add row 6 (this drop).
3. **Optional**: measure current daimonion LLM cost
   separately from director_loop in LiteLLM spendlogs
   (once drop #19 § 3 budget verification lands). Voice
   turns and director reactions have very different
   cost profiles due to the vision injection.

## 6. References

- `agents/hapax_daimonion/conversation_pipeline.py:608-614`
  — screen image injection site
- `agents/hapax_daimonion/conversation_pipeline.py:984-1013`
  — the `litellm.acompletion` call
- `agents/hapax_daimonion/pipeline.py:94-139` — the
  separate pipecat-based pipeline (drop #9 row 2)
- Drop #9 `2026-04-14-prompt-cache-audit.md` — the
  original audit this drop extends
- Drop #8 `2026-04-14-director-loop-prompt-cache-gap.md`
  — the fix pattern
- `systemctl --user show hapax-daimonion.service` at
  2026-04-14T16:50 UTC — MemoryCurrent 2.6 GB,
  CPUUsageNSec 3917 s cumulative
