---
name: demo
description: Generate an audience-tailored system demo. Use when the user asks to produce a demo, create a presentation, or runs /demo.
---

Generate a demo from a natural language request. Examples:

- `/demo the entire system for my partner`
- `/demo health monitoring for a technical peer`
- `/demo the agent architecture for my manager --format video`

Available formats: `slides` (default), `video` (requires Chatterbox TTS), `markdown-only`.

Prerequisites for video format:
- Logos web running: `cd ~/projects/hapax-council/hapax-logos && pnpm dev`
- Chatterbox TTS running: `cd ~/llm-stack && docker compose --profile tts up -d chatterbox`

Run the demo agent:

```bash
cd ~/projects/hapax-council && LITELLM_API_KEY=$(pass show litellm/master-key) uv run python -m agents.demo "{user_request}"
```

After generation, report the output directory and list generated files. If format is video, note the MP4 path. If format is slides, note the PDF path.
