---
name: vram
description: Show detailed VRAM analysis. Use when the user asks about GPU memory, VRAM, model loading capacity, or runs /vram.
---

Show detailed VRAM analysis:

1. Run `nvidia-smi` and parse output
2. List all Ollama loaded models: `curl -s http://localhost:11434/api/ps`
3. Check if TabbyAPI is running on port 5000
4. Estimate available VRAM for additional tasks
5. Recommend which models can be loaded concurrently
