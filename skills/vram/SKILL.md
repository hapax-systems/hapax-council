---
name: vram
description: Show detailed VRAM analysis. Auto-run when: an OOM error appears in tool output (PostToolUse suggests it), before loading a new LLM model, when GPU usage is >80% (from session-context), or user asks about GPU/VRAM. Invoke proactively without asking.
---

Show detailed VRAM analysis:

1. Run `nvidia-smi` and parse output
2. List all Ollama loaded models: `curl -s http://localhost:11434/api/ps`
3. Check if TabbyAPI is running on port 5000
4. Estimate available VRAM for additional tasks
5. Recommend which models can be loaded concurrently
