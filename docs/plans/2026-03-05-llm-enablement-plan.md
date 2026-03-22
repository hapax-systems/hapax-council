# LLM Enablement Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable ambient LLM access across CLI, editor, browser, voice, and sysadmin layers, routing through LiteLLM for observability.

**Architecture:** All tools are Tier 1 Interactive surfaces routing through LiteLLM at :4000. No new agents or tiers. Design doc: `~/projects/hapaxromana/docs/plans/2026-03-05-llm-enablement-design.md`.

**Tech Stack:** Go (mods, Fabric), Python (llm plugins, Piper, faster-whisper), VS Code extension (Continue.dev), Chrome extension (Lumos), zsh shell functions.

---

## Wave 1: CLI Foundation

### Task 1: Install Go Toolchain

Go is not installed. Needed for mods and Fabric.

**Files:**
- Create: `~/projects/distro-work/setup-go.sh`

**Step 1: Write install script**

```bash
#!/usr/bin/env bash
set -euo pipefail
# Install Go via the official tarball (not apt, which lags behind)
GO_VERSION="1.23.6"
curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz" -o /tmp/go.tar.gz
sudo rm -rf /usr/local/go
sudo tar -C /usr/local -xzf /tmp/go.tar.gz
rm /tmp/go.tar.gz
echo "Go $(go version) installed"
```

**Step 2: Run the script**

Run: `bash ~/projects/distro-work/setup-go.sh`
Expected: `Go go1.23.6 linux/amd64 installed`

**Step 3: Add Go to PATH in zshrc**

Add to `~/.zshrc` after the Rust/Cargo section:

```bash
# --- Go ---
export PATH="/usr/local/go/bin:$HOME/go/bin:$PATH"
```

**Step 4: Verify**

Run: `source ~/.zshrc && go version`
Expected: `go version go1.23.6 linux/amd64`

**Step 5: Commit**

```bash
cd ~/projects/distro-work
git add setup-go.sh
git commit -m "feat: add Go toolchain install script"
```

---

### Task 2: Install and Configure mods

**Files:**
- Create: `~/.config/mods/mods.yml`

**Step 1: Install mods**

Run: `go install github.com/charmbracelet/mods@latest`
Expected: Binary at `~/go/bin/mods`

**Step 2: Verify install**

Run: `mods --version`
Expected: Version string (e.g., `mods v1.8.0`)

**Step 3: Write mods config**

Create `~/.config/mods/mods.yml`:

```yaml
default-model: sonnet
apis:
  litellm:
    base-url: http://localhost:4000/v1
    models:
      sonnet:
        aliases: [claude-sonnet, default]
        max-input-chars: 392000
      haiku:
        aliases: [claude-haiku, fast]
        max-input-chars: 392000
      coder:
        aliases: [qwen-coder-32b]
        max-input-chars: 128000
```

Note: mods reads `OPENAI_API_KEY` env var. For LiteLLM routing, this must be the LiteLLM key. We'll set it in Step 5.

**Step 4: Test with a simple pipe**

Run: `echo "What is 2+2?" | OPENAI_API_KEY=$(pass show litellm/master-key) mods`
Expected: Response containing "4"

**Step 5: Add mods env var to direnv-loaded shell**

The `OPENAI_API_KEY` for mods should come from the environment. Add to the default `.envrc` pattern or export globally. Since mods runs from any directory, add to `~/.zshrc`:

```bash
# --- LLM CLI tools (mods, llm, fabric) ---
export OPENAI_API_BASE="http://localhost:4000/v1"
export OPENAI_API_KEY="$(pass show litellm/master-key)"
```

**Step 6: Test without explicit key**

Run: `source ~/.zshrc && echo "hello" | mods "respond in one word"`
Expected: Single-word response

**Step 7: Commit config**

```bash
cd ~/projects/distro-work
mkdir -p configs/mods
cp ~/.config/mods/mods.yml configs/mods/mods.yml
git add configs/mods/mods.yml
git commit -m "feat: add mods config for LiteLLM routing"
```

---

### Task 3: Install and Configure Fabric

**Step 1: Install Fabric**

Run: `go install github.com/danielmiessler/fabric@latest`
Expected: Binary at `~/go/bin/fabric`

**Step 2: Run Fabric setup**

Run: `fabric --setup`

When prompted:
- API endpoint: `http://localhost:4000/v1`
- API key: output of `pass show litellm/master-key`
- Default model: `claude-sonnet`

**Step 3: Verify patterns are available**

Run: `fabric --listpatterns | head -20`
Expected: List of pattern names (extract_wisdom, summarize, improve_writing, etc.)

**Step 4: Test a pattern**

Run: `echo "The quick brown fox jumps over the lazy dog." | fabric --pattern summarize`
Expected: A summary response from the LLM

**Step 5: Commit config backup**

```bash
cd ~/projects/distro-work
mkdir -p configs/fabric
cp ~/.config/fabric/.env configs/fabric/env.example  # Redact key
sed -i 's/sk-.*$/LITELLM_API_KEY_HERE/' configs/fabric/env.example
git add configs/fabric/env.example
git commit -m "feat: add Fabric config template for LiteLLM routing"
```

---

### Task 4: Configure Simon Willison's llm CLI

The `llm` tool (v0.28) is installed but unconfigured — default model is gpt-4o-mini, no keys set, no plugins.

**Step 1: Set LiteLLM as the OpenAI-compatible backend**

Run:
```bash
llm keys set openai --value "$(pass show litellm/master-key)"
```
Expected: `Key set for openai`

**Step 2: Configure LiteLLM base URL**

The `llm` CLI uses `OPENAI_API_BASE` env var (already set in Task 2 Step 5). Verify:

Run: `llm -m gpt-4o-mini "say hello in one word"`
Expected: This should now route through LiteLLM. If it fails, the model name `gpt-4o-mini` may not be in LiteLLM's config. Use a known alias instead.

Run: `llm models default claude-sonnet`
Expected: Default model set

**Step 3: Verify default model works**

Run: `llm "What is 2+2?"`
Expected: Response via claude-sonnet through LiteLLM

**Step 4: Install llm-cmd plugin**

Run: `llm install llm-cmd`
Expected: Plugin installed

**Step 5: Test llm cmd**

Run: `llm cmd "list files larger than 100MB in home directory"`
Expected: Displays a `find` command for review, waits for Enter/Ctrl+C

**Step 6: Install llm-ollama plugin**

Run: `llm install llm-ollama`
Expected: Plugin installed. Ollama models now available.

**Step 7: Verify Ollama models visible**

Run: `llm ollama list-models`
Expected: Lists models pulled in Ollama (nomic-embed-text, qwen2.5-coder:32b, etc.)

**Step 8: Install llm-templates-fabric plugin**

Run: `llm install llm-templates-fabric`
Expected: Plugin installed

**Step 9: Verify Fabric templates accessible from llm**

Run: `llm templates list | grep summarize`
Expected: Shows `fabric:summarize` (or similar)

**Step 10: Commit**

```bash
cd ~/projects/distro-work
git add -A
git commit -m "feat: configure llm CLI with LiteLLM routing and plugins"
```

---

### Task 5: Add Shell Functions and Aliases

**Files:**
- Modify: `~/.zshrc`

**Step 1: Add LLM shell functions to zshrc**

Append to `~/.zshrc` after the existing aliases section:

```bash
# --- LLM Shell Functions ---
alias m='mods'

# Explain errors: run command, pipe stderr through LLM
explain() {
  local output
  output=$("$@" 2>&1)
  local exit_code=$?
  if [ $exit_code -ne 0 ]; then
    echo "$output"
    echo "---"
    echo "$output" | mods "Explain this error and suggest specific fixes. Be concise."
  else
    echo "$output"
  fi
}

# Diagnose systemd service logs
diagnose() {
  local unit="${1:?Usage: diagnose <unit> [timeframe]}"
  local since="${2:-1 hour ago}"
  journalctl -u "$unit" --since "$since" --no-pager | mods "Diagnose issues in these $unit logs. List problems found and specific fixes."
}

# Natural language to shell command
how() { llm cmd "$*"; }

# Docker container diagnosis
docker-diagnose() {
  docker inspect "${1:?Usage: docker-diagnose <container>}" | mods "Analyze this container's health, resource usage, restart history. Flag issues."
}

# Quick security audit of listening ports
security-audit() {
  ss -tlnp | mods "Audit these listening ports for a single-user workstation running Docker with all ports on 127.0.0.1. Flag anything exposed or unexpected."
}
```

**Step 2: Reload and test**

Run: `source ~/.zshrc`

Run: `how "find files modified in the last day"`
Expected: Displays a `find` command for review

Run: `echo "test error" | m "what does this mean"`
Expected: LLM response about the text

**Step 3: Commit zshrc backup**

```bash
cd ~/projects/distro-work
cp ~/.zshrc configs/zshrc.backup
git add configs/zshrc.backup
git commit -m "feat: add LLM shell functions (explain, diagnose, how, docker-diagnose, security-audit)"
```

---

### Task 6: Wave 1 Verification

**Step 1: End-to-end pipe test**

Run: `cat /etc/os-release | mods "summarize this OS info in one sentence"`
Expected: Something like "Pop!_OS 24.04 LTS based on Ubuntu"

**Step 2: Fabric pattern test**

Run: `echo "LLMs are changing how developers write code by providing context-aware suggestions, automated refactoring, and natural language interfaces to complex toolchains." | fabric --pattern extract_wisdom`
Expected: Structured extraction of ideas/insights

**Step 3: llm cmd test**

Run: `llm cmd "show GPU memory usage"`
Expected: Suggests `nvidia-smi` command for review

**Step 4: Commit wave 1 completion note**

```bash
cd ~/projects/distro-work
cat > wave1-completion.md << 'EOF'
# Wave 1: CLI Foundation - Complete

Date: $(date +%Y-%m-%d)

## Installed
- Go 1.23.6
- mods (Charmbracelet) - Unix pipe LLM
- Fabric (Miessler) - prompt pattern library
- llm plugins: llm-cmd, llm-ollama, llm-templates-fabric

## Configured
- All tools route through LiteLLM at localhost:4000
- OPENAI_API_BASE and OPENAI_API_KEY set in ~/.zshrc
- mods config at ~/.config/mods/mods.yml
- llm default model: claude-sonnet

## Shell Functions Added
- m (alias for mods)
- explain() - error explanation
- diagnose() - systemd log diagnosis
- how() - NL to shell command
- docker-diagnose() - container analysis
- security-audit() - port audit
EOF
git add wave1-completion.md
git commit -m "docs: wave 1 CLI foundation complete"
```

---

## Wave 2: Editor + Browser

### Task 7: Install and Configure Continue.dev

**Files:**
- Create: Continue.dev config (flatpak VS Code path)

**Step 1: Install Continue extension**

Run: `flatpak run com.visualstudio.code --install-extension Continue.continue`
Expected: Extension installed successfully

**Step 2: Find the config path**

VS Code flatpak stores user data at `~/.var/app/com.visualstudio.code/`. The Continue config will be at:
`~/.var/app/com.visualstudio.code/config/Code/User/globalStorage/continue.continue/config.yaml`

If the directory doesn't exist yet, launch VS Code once, open the Continue sidebar (Ctrl+Shift+L), then close it. This creates the config directory.

Run: `flatpak run com.visualstudio.code &`
Wait for VS Code to open, open Continue sidebar, then close VS Code.

**Step 3: Write Continue config**

Create the config.yaml at the path from Step 2:

```yaml
models:
  - model: claude-sonnet
    title: Claude Sonnet (via LiteLLM)
    provider: openai
    apiBase: http://localhost:4000/v1
    apiKey: LITELLM_KEY_PLACEHOLDER
  - model: claude-haiku
    title: Claude Haiku (fast)
    provider: openai
    apiBase: http://localhost:4000/v1
    apiKey: LITELLM_KEY_PLACEHOLDER
  - model: qwen-coder-32b
    title: Qwen Coder (local)
    provider: openai
    apiBase: http://localhost:4000/v1
    apiKey: LITELLM_KEY_PLACEHOLDER

tabAutocompleteModel:
  model: claude-haiku
  provider: openai
  apiBase: http://localhost:4000/v1
  apiKey: LITELLM_KEY_PLACEHOLDER
```

Replace `LITELLM_KEY_PLACEHOLDER` with the actual key from `pass show litellm/master-key`.

Note: Continue.dev flatpak sandboxing may block localhost access. If it does, check `flatpak override` permissions:

Run: `flatpak override --user com.visualstudio.code --share=network`

**Step 4: Test in VS Code**

1. Open VS Code: `flatpak run com.visualstudio.code`
2. Open Continue sidebar (Ctrl+Shift+L)
3. Type "hello" in the chat
4. Verify response comes from Claude Sonnet via LiteLLM (check Langfuse traces at http://localhost:3000)

**Step 5: Commit config backup**

```bash
cd ~/projects/distro-work
mkdir -p configs/continue
# Copy config, redact key
cp ~/.var/app/com.visualstudio.code/config/Code/User/globalStorage/continue.continue/config.yaml configs/continue/config.yaml
sed -i 's/sk-[^ ]*/LITELLM_KEY_PLACEHOLDER/g' configs/continue/config.yaml
git add configs/continue/config.yaml
git commit -m "feat: add Continue.dev config for LiteLLM routing in VS Code"
```

---

### Task 8: Install Lumos Browser Extension

This is a manual Chrome extension install. Document the process.

**Step 1: Install Lumos from Chrome Web Store**

1. Open Chrome: `flatpak run com.google.Chrome`
2. Navigate to Chrome Web Store and search for "Lumos" by andrewnguonly
3. Install the extension

**Step 2: Configure Lumos**

1. Click the Lumos extension icon in Chrome toolbar
2. Set Ollama host: `http://localhost:11434`
3. Set embedding model: `nomic-embed-text`
4. Set chat model: `qwen2.5:7b` (lightweight for browser Q&A)

Note: Chrome flatpak may block localhost access. If Lumos can't reach Ollama:

Run: `flatpak override --user com.google.Chrome --share=network`

**Step 3: Test**

1. Navigate to any documentation page
2. Click Lumos icon
3. Ask "summarize this page"
4. Verify response

**Step 4: Document setup**

```bash
cd ~/projects/distro-work
cat > configs/lumos-setup.md << 'EOF'
# Lumos Chrome Extension Setup

1. Install from Chrome Web Store (search "Lumos" by andrewnguonly)
2. Ollama host: http://localhost:11434
3. Embedding model: nomic-embed-text
4. Chat model: qwen2.5:7b
5. If flatpak blocks localhost: flatpak override --user com.google.Chrome --share=network
EOF
git add configs/lumos-setup.md
git commit -m "docs: add Lumos browser extension setup notes"
```

---

### Task 9: Wave 2 Verification

**Step 1: Verify Continue.dev traces in Langfuse**

1. Open VS Code, use Continue chat
2. Open http://localhost:3000 (Langfuse)
3. Check traces — should see a trace from the Continue interaction routed through LiteLLM

**Step 2: Verify Lumos works with Ollama**

1. Open a web page in Chrome
2. Use Lumos to ask a question about the page content
3. Verify response is relevant

**Step 3: Commit wave 2 completion**

```bash
cd ~/projects/distro-work
cat > wave2-completion.md << 'EOF'
# Wave 2: Editor + Browser - Complete

## Installed
- Continue.dev VS Code extension
- Lumos Chrome extension

## Configured
- Continue.dev -> LiteLLM at localhost:4000 (traced in Langfuse)
  - Chat: claude-sonnet
  - Autocomplete: claude-haiku
  - Local coding: qwen-coder-32b
- Lumos -> Ollama at localhost:11434 (not traced, acceptable)
  - Embedding: nomic-embed-text
  - Chat: qwen2.5:7b
EOF
git add wave2-completion.md
git commit -m "docs: wave 2 editor + browser complete"
```

---

## Wave 3: Voice Input

### Task 10: Install and Test Voxtype

**Step 1: Install Voxtype**

Check latest install method at https://voxtype.io/. Likely:

Run: `curl -fsSL https://voxtype.io/install.sh | bash`

Or if a .deb or binary is provided:

Run: `wget -O /tmp/voxtype https://github.com/voxtype/voxtype/releases/latest/download/voxtype-linux-x86_64 && chmod +x /tmp/voxtype && sudo mv /tmp/voxtype /usr/local/bin/`

**Step 2: Test basic STT**

Run: `voxtype`
Expected: Starts listening. Speak, then check if text appears.

**Step 3: Test COSMIC key-release events**

Configure push-to-talk keybinding (e.g., Right Alt). Test:
1. Hold Right Alt
2. Speak
3. Release Right Alt
4. Check if text is typed/copied

If key-release events DON'T work (tap-to-talk fallback), proceed to Task 11 (faster-whisper fallback). If they DO work, skip Task 11.

**Step 4: Configure Voxtype for clipboard output**

Configure Voxtype to output transcribed text to clipboard via `wl-copy`. This allows voice -> clipboard -> existing hotkey scripts pipeline.

**Step 5: Commit**

```bash
cd ~/projects/distro-work
git add -A
git commit -m "feat: install Voxtype STT for push-to-talk voice input"
```

---

### Task 11: Fallback — faster-whisper + ydotool (only if Task 10 fails)

Skip this task if Voxtype works with COSMIC key-release events.

**Files:**
- Create: `~/projects/distro-work/voice-to-text.py`

**Step 1: Install faster-whisper**

Run: `uv tool install faster-whisper`

Or create a dedicated venv:
```bash
cd ~/projects/distro-work
uv venv .venv-voice
uv pip install faster-whisper sounddevice numpy
```

**Step 2: Write voice-to-text script**

```python
#!/usr/bin/env python3
"""Push-to-talk voice input using faster-whisper.
Hold a key (via ydotool monitoring), record, transcribe, copy to clipboard."""
import subprocess
import tempfile
import sys

def record_audio(duration_seconds=10, sample_rate=16000):
    """Record audio to a temp WAV file using arecord."""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    subprocess.run([
        "arecord", "-f", "S16_LE", "-r", str(sample_rate),
        "-c", "1", "-d", str(duration_seconds), tmp.name
    ], check=True, capture_output=True)
    return tmp.name

def transcribe(audio_path):
    """Transcribe using faster-whisper."""
    from faster_whisper import WhisperModel
    model = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")
    segments, _ = model.transcribe(audio_path)
    return " ".join(s.text for s in segments).strip()

def to_clipboard(text):
    """Copy text to Wayland clipboard."""
    subprocess.run(["wl-copy", text], check=True)

if __name__ == "__main__":
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    print(f"Recording for {duration}s...")
    audio = record_audio(duration)
    print("Transcribing...")
    text = transcribe(audio)
    print(f"Transcribed: {text}")
    to_clipboard(text)
    subprocess.run(["notify-send", "Voice", f"Copied: {text[:100]}"], check=True)
```

**Step 3: Test**

Run: `cd ~/projects/distro-work && uv run voice-to-text.py 3`
Expected: Records 3 seconds, transcribes, copies to clipboard

**Step 4: Commit**

```bash
cd ~/projects/distro-work
git add voice-to-text.py
git commit -m "feat: add faster-whisper voice-to-text fallback script"
```

---

### Task 12: Install Piper TTS

**Step 1: Install Piper**

Run: `uv tool install piper-tts`

Or download binary:
```bash
wget -O /tmp/piper.tar.gz https://github.com/rhasspy/piper/releases/latest/download/piper_linux_x86_64.tar.gz
tar -xzf /tmp/piper.tar.gz -C ~/.local/bin/
```

**Step 2: Download a voice model**

Run:
```bash
mkdir -p ~/models/piper
wget -O ~/models/piper/en_US-lessac-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
wget -O ~/models/piper/en_US-lessac-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
```

**Step 3: Test Piper**

Run: `echo "Hello, this is a test of the text to speech system." | piper --model ~/models/piper/en_US-lessac-medium.onnx --output-raw | aplay -r 22050 -f S16_LE -c 1`
Expected: Audio plays the sentence

**Step 4: Add speak function to zshrc**

Append to `~/.zshrc`:

```bash
# TTS: pipe text to speech
speak() {
  if [ -p /dev/stdin ]; then
    cat | piper --model ~/models/piper/en_US-lessac-medium.onnx --output-raw 2>/dev/null | aplay -r 22050 -f S16_LE -c 1 2>/dev/null
  else
    echo "$*" | piper --model ~/models/piper/en_US-lessac-medium.onnx --output-raw 2>/dev/null | aplay -r 22050 -f S16_LE -c 1 2>/dev/null
  fi
}
```

**Step 5: Test speak function**

Run: `source ~/.zshrc && echo "Testing text to speech" | speak`
Expected: Hears "Testing text to speech"

Run: `speak "This also works"`
Expected: Hears "This also works"

**Step 6: Commit**

```bash
cd ~/projects/distro-work
git add -A
git commit -m "feat: install Piper TTS with speak() shell function"
```

---

## Wave 4: Automation + Sysadmin

### Task 13: LLM-Enriched Health Alerts

**Files:**
- Modify: `~/projects/ai-agents/shared/notify.py`

**Step 1: Read current notify.py**

Read `~/projects/ai-agents/shared/notify.py` to understand the current notification interface.

**Step 2: Add LLM enrichment function**

Add a function that takes raw diagnostic context and pipes it through claude-haiku for actionable summarization before sending via ntfy. The function should:
- Accept a raw diagnostic string and a subject
- Call claude-haiku via LiteLLM to generate an actionable summary
- Fall back to raw message if LLM call fails
- Send via existing ntfy notification path

Implementation depends on the current notify.py structure. The key change: when health-monitor calls `notify()` with a failure, the message gets LLM-enriched first.

**Step 3: Test**

Run the health-monitor manually and verify enriched notifications:
```bash
cd ~/projects/ai-agents && uv run python -m agents.health_monitor
```

**Step 4: Commit**

```bash
cd ~/projects/ai-agents
git add shared/notify.py
git commit -m "feat: add LLM-enriched health alert notifications via claude-haiku"
```

---

### Task 14: Wave 4 Diagnostic Aliases (already done in Task 5)

The `diagnose()`, `docker-diagnose()`, and `security-audit()` functions were already added in Task 5. Verify they work now that mods is installed:

**Step 1: Test diagnose**

Run: `diagnose ollama "30 minutes ago"`
Expected: LLM analysis of Ollama container logs

**Step 2: Test docker-diagnose**

Run: `docker-diagnose ollama`
Expected: LLM analysis of container inspect output

**Step 3: Test security-audit**

Run: `security-audit`
Expected: LLM analysis of listening ports

---

### Task 15: Final Verification and Documentation

**Step 1: Update hapaxromana CLAUDE.md**

Verify that `~/projects/hapaxromana/CLAUDE.md` references the extended Tier 1 surfaces. This was already done during the brainstorming phase (agent-architecture.md updated). Verify:

Run: `grep "Extended Interactive Surfaces" ~/projects/hapaxromana/agent-architecture.md`
Expected: Section header found

**Step 2: Verify scout component registry**

Run: `grep "cli-llm-pipe\|cli-prompt-patterns\|editor-llm\|voice-stt" ~/projects/ai-agents/profiles/component-registry.yaml`
Expected: All four entries found (already added during brainstorming)

**Step 3: Write final completion doc**

```bash
cd ~/projects/distro-work
cat > llm-enablement-complete.md << 'EOF'
# LLM Enablement - All Waves Complete

Design: ~/projects/hapaxromana/docs/plans/2026-03-05-llm-enablement-design.md

## Wave 1: CLI Foundation
- mods, Fabric, llm-cmd, llm-ollama, llm-templates-fabric
- Shell functions: explain, diagnose, how, docker-diagnose, security-audit
- All routing through LiteLLM at :4000

## Wave 2: Editor + Browser
- Continue.dev in VS Code -> LiteLLM (traced in Langfuse)
- Lumos in Chrome -> Ollama direct

## Wave 3: Voice
- Voxtype (or faster-whisper fallback) for STT
- Piper for TTS via speak() function

## Wave 4: Automation
- LLM-enriched health alerts in shared/notify.py
- Diagnostic shell functions operational

## Cross-cutting
- All tools in ai-agents/profiles/component-registry.yaml for scout evaluation
- Architecture documented in hapaxromana/agent-architecture.md
- Global CLAUDE.md trimmed, points to hapaxromana as canonical source
EOF
git add llm-enablement-complete.md
git commit -m "docs: LLM enablement all waves complete"
```

**Step 4: Commit across repos**

```bash
cd ~/projects/hapaxromana
git add -A
git commit -m "docs: add LLM enablement design doc and Tier 1 surface expansion"

cd ~/projects/ai-agents
git add profiles/component-registry.yaml
git commit -m "feat: add Tier 1 CLI/editor/voice tools to scout component registry"
```
