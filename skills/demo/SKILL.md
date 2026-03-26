---
name: demo
description: Generate an audience-tailored system demo. Auto-run when: operator mentions showing the system to someone, preparing a presentation, or demonstrating capabilities. Suggest when a significant new feature is completed. Invoke proactively without asking.
---

Generate a demo from a natural language request. Examples:

- `/demo the entire system for my partner`
- `/demo health monitoring for a technical peer`
- `/demo the agent architecture for my manager --format video`
- `/demo the system for alexis --format app`

Available formats: `slides` (default), `video` (requires Chatterbox TTS), `markdown-only`, `app` (in-browser live demo).

**App format** (recommended for live demos):
- Generates narration audio via Kokoro TTS (local, no Docker needed)
- Produces an `app-script.json` with timed terrain actions
- Play via: `http://localhost:5173/?demo={demo-name}`
- Press Space to start, Escape to stop
- No Playwright, no external process — the React app drives itself

Prerequisites for app format:
- Logos API running: `cd ~/projects/hapax-council && uv run logos-api`
- hapax-logos web running (dev server on :5173)

Prerequisites for video format:
- hapax-logos web running: `cd ~/projects/hapax-council/hapax-logos && npm run dev`
- Chatterbox TTS running: `cd ~/llm-stack && docker compose --profile tts up -d chatterbox`

Run the demo agent:

```bash
cd ~/projects/hapax-council && LITELLM_API_KEY=$(pass show litellm/master-key) uv run python -m agents.demo "{user_request}" --format app
```

After generation, report the output directory and activation URL. For app format: `http://localhost:5173/?demo={demo-dir-name}`. For video: note the MP4 path. For slides: note the PDF path.
