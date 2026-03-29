# hapax-voice → hapax-daimonion Rename Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the voice daemon from `hapax-voice`/`hapax_voice` to `hapax-daimonion`/`hapax_daimonion` across all code, config, systemd, docs, and runtime paths.

**Architecture:** Mechanical rename in 4 layers: (1) hapax-council Python code + config, (2) systemd/infrastructure, (3) runtime data migration, (4) other repos. The Python module `agents.hapax_voice` becomes `agents.hapax_daimonion`. All filesystem paths (`~/.cache/hapax-voice/`, `~/.local/share/hapax-voice/`, `/dev/shm/hapax-voice/`, `/run/user/1000/hapax-voice.sock`) rename correspondingly.

**Tech Stack:** Python, bash, systemd, git, sed

**String mapping:**

| Old | New | Context |
|-----|-----|---------|
| `hapax_voice` | `hapax_daimonion` | Python module, imports, variable names |
| `hapax-voice` | `hapax-daimonion` | Systemd, paths, CLI, config, docs |
| `hapax voice` | `hapax daimonion` | Prose in docs (case-insensitive) |
| `Hapax Voice` | `Hapax Daimonion` | Titles, descriptions |
| `HAPAX_VOICE` | `HAPAX_DAIMONION` | Environment variables (if any) |
| `hapax-voice.service` | `hapax-daimonion.service` | Systemd unit name |
| `hapax-voice.sock` | `hapax-daimonion.sock` | Unix socket |
| `hapax-voice.pid` | `hapax-daimonion.pid` | PID file |
| `hapax-voice.env` | `hapax-daimonion.env` | Environment file (process-compose) |
| `VoiceConfig` | `DaimonionConfig` | Python class name |
| `voice_config` | `daimonion_config` | Python variable name |

**NOT renamed (conceptual, not identity):**
- Generic uses of "voice" that aren't part of the `hapax-voice` identity (e.g., "voice cloning", "voice interaction", "voice session", "voice chain", "voice grounding")
- `vocal_chain.py`, `voice_chain.py` — these are internal module names describing what they do, not identity
- The `hapax-voice-duck.conf` wireplumber config keeps its functional name (it ducks audio for voice output) — but the description updates

---

## Task 1: Create branch and rename directories (hapax-council)

**Files:**
- Rename: `agents/hapax_voice/` → `agents/hapax_daimonion/`
- Rename: `tests/hapax_voice/` → `tests/hapax_daimonion/`
- Rename: 19 root test files `tests/test_hapax_voice_*.py` → `tests/test_hapax_daimonion_*.py`

- [ ] **Step 1: Create feature branch**

```bash
cd ~/projects/hapax-council--beta
git checkout -b feat/rename-daimonion
```

- [ ] **Step 2: Rename agent directory**

```bash
git mv agents/hapax_voice agents/hapax_daimonion
```

- [ ] **Step 3: Rename test directory**

```bash
git mv tests/hapax_voice tests/hapax_daimonion
```

- [ ] **Step 4: Rename root-level test files**

```bash
for f in tests/test_hapax_voice_*.py; do
    git mv "$f" "${f/hapax_voice/hapax_daimonion}"
done
```

- [ ] **Step 5: Commit directory renames**

```bash
git commit -m "refactor: rename hapax_voice directories to hapax_daimonion"
```

---

## Task 2: Bulk find-replace in Python files (hapax-council)

All `.py` files in the repo. This is the largest task — ~300 files with import statements and path references.

**Replacements (order matters — longest first to avoid partial matches):**

1. `agents.hapax_voice` → `agents.hapax_daimonion` (Python imports)
2. `hapax_voice` → `hapax_daimonion` (module references, variable names, test names)
3. `hapax-voice` → `hapax-daimonion` (path strings, config keys, socket names)
4. `Hapax Voice` → `Hapax Daimonion` (docstrings, comments)

- [ ] **Step 1: Replace Python import paths**

```bash
cd ~/projects/hapax-council--beta
find . -name '*.py' -not -path './.git/*' -not -path '*__pycache__*' \
    -exec sed -i 's/agents\.hapax_voice/agents.hapax_daimonion/g' {} +
```

- [ ] **Step 2: Replace remaining hapax_voice (underscored)**

```bash
find . -name '*.py' -not -path './.git/*' -not -path '*__pycache__*' \
    -exec sed -i 's/hapax_voice/hapax_daimonion/g' {} +
```

- [ ] **Step 3: Replace hapax-voice (hyphenated) in Python files**

```bash
find . -name '*.py' -not -path './.git/*' -not -path '*__pycache__*' \
    -exec sed -i 's/hapax-voice/hapax-daimonion/g' {} +
```

- [ ] **Step 4: Replace "Hapax Voice" title case in Python files**

```bash
find . -name '*.py' -not -path './.git/*' -not -path '*__pycache__*' \
    -exec sed -i 's/Hapax Voice/Hapax Daimonion/g' {} +
```

- [ ] **Step 5: Verify no remaining references in Python**

```bash
grep -rn "hapax.voice\|hapax_voice\|hapax-voice" --include="*.py" . \
    | grep -v __pycache__ | grep -v '.git/'
```

Expected: zero matches (or only generic "voice" without "hapax" prefix).

- [ ] **Step 6: Commit Python changes**

```bash
git add -A
git commit -m "refactor: rename all hapax_voice Python references to hapax_daimonion"
```

---

## Task 3: Rename VoiceConfig class and related identifiers

The main config class `VoiceConfig` should become `DaimonionConfig`. Variables like `voice_config` become `daimonion_config`.

- [ ] **Step 1: Rename VoiceConfig class**

```bash
find . -name '*.py' -not -path './.git/*' -not -path '*__pycache__*' \
    -exec sed -i 's/VoiceConfig/DaimonionConfig/g' {} +
```

- [ ] **Step 2: Rename voice_config variables**

These are common in test files and the daemon entry point.

```bash
find . -name '*.py' -not -path './.git/*' -not -path '*__pycache__*' \
    -exec sed -i 's/voice_config/daimonion_config/g' {} +
```

- [ ] **Step 3: Verify no stale VoiceConfig references**

```bash
grep -rn "VoiceConfig\|voice_config" --include="*.py" . | grep -v __pycache__
```

Expected: zero matches.

- [ ] **Step 4: Commit class renames**

```bash
git add -A
git commit -m "refactor: rename VoiceConfig to DaimonionConfig"
```

---

## Task 4: Update systemd units (hapax-council repo)

**Files:**
- Rename: `systemd/units/hapax-voice.service` → `systemd/units/hapax-daimonion.service`
- Modify: `systemd/units/visual-layer-aggregator.service`
- Modify: `systemd/units/studio-compositor.service`
- Modify: `systemd/overrides/studio-compositor.service.d/ordering.conf`
- Modify: `systemd/overrides/hapax-stack.service.d/priority.conf`
- Modify: `systemd/hapax-rebuild-services.service`
- Modify: `systemd/README.md`

- [ ] **Step 1: Rename the service unit file**

```bash
git mv systemd/units/hapax-voice.service systemd/units/hapax-daimonion.service
```

- [ ] **Step 2: Update content of renamed service file**

In `systemd/units/hapax-daimonion.service`:
- `Description=Hapax Voice` → `Description=Hapax Daimonion`
- `python -m agents.hapax_voice` → `python -m agents.hapax_daimonion`
- `SyslogIdentifier=hapax-voice` → `SyslogIdentifier=hapax-daimonion`

```bash
sed -i 's/hapax-voice/hapax-daimonion/g; s/hapax_voice/hapax_daimonion/g; s/Hapax Voice/Hapax Daimonion/g' \
    systemd/units/hapax-daimonion.service
```

- [ ] **Step 3: Update dependency references in other units**

```bash
for f in systemd/units/visual-layer-aggregator.service \
         systemd/units/studio-compositor.service \
         systemd/overrides/studio-compositor.service.d/ordering.conf; do
    sed -i 's/hapax-voice/hapax-daimonion/g' "$f"
done
```

- [ ] **Step 4: Update rebuild-services unit**

```bash
sed -i 's/hapax-voice/hapax-daimonion/g; s/hapax_voice/hapax_daimonion/g' \
    systemd/hapax-rebuild-services.service
```

- [ ] **Step 5: Update systemd README**

```bash
sed -i 's/hapax-voice/hapax-daimonion/g; s/hapax_voice/hapax_daimonion/g; s/Hapax Voice/Hapax Daimonion/g' \
    systemd/README.md
```

- [ ] **Step 6: Commit systemd changes**

```bash
git add -A
git commit -m "refactor: rename hapax-voice systemd units to hapax-daimonion"
```

---

## Task 5: Update scripts (hapax-council)

**Files:**
- Modify: `scripts/smoke_test_voice.sh`
- Modify: `scripts/vram-watchdog.sh`
- Modify: `scripts/enroll_speaker.py`
- Modify: `scripts/generate_screen_context.py`
- Modify: `scripts/calibrate-contact-mic.py`
- Modify: `scripts/train_wake_word.py`
- Modify: `scripts/webcam_timelapse.py`
- Modify: `scripts/test_wake_handoff.py`
- Modify: `scripts/build_demo_kb.py`
- Modify: `scripts/cache-cleanup.sh`
- Modify: `scripts/rebuild-service.sh` (watch paths in comments)
- Rename: `scripts/smoke_test_voice.sh` → `scripts/smoke_test_daimonion.sh`

- [ ] **Step 1: Rename smoke test script**

```bash
git mv scripts/smoke_test_voice.sh scripts/smoke_test_daimonion.sh
```

- [ ] **Step 2: Bulk replace in all scripts**

```bash
find scripts/ -type f \( -name '*.sh' -o -name '*.py' \) \
    -exec sed -i 's/hapax-voice/hapax-daimonion/g; s/hapax_voice/hapax_daimonion/g; s/Hapax Voice/Hapax Daimonion/g' {} +
```

- [ ] **Step 3: Verify**

```bash
grep -rn "hapax.voice\|hapax_voice\|hapax-voice" scripts/ | grep -v __pycache__
```

Expected: zero matches.

- [ ] **Step 4: Commit script changes**

```bash
git add -A
git commit -m "refactor: rename hapax-voice references in scripts to hapax-daimonion"
```

---

## Task 6: Update CI, .gitignore, conftest, process-compose

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/lab-journal.yml`
- Modify: `.gitignore`
- Modify: `conftest.py`
- Modify: `tests/conftest.py`
- Modify: `tests/consent_strategies.py`
- Modify: `process-compose.yaml`

- [ ] **Step 1: Update CI workflows**

```bash
sed -i 's/hapax_voice/hapax_daimonion/g; s/hapax-voice/hapax-daimonion/g' \
    .github/workflows/ci.yml .github/workflows/lab-journal.yml
```

- [ ] **Step 2: Update .gitignore**

```bash
sed -i 's/hapax_voice/hapax_daimonion/g' .gitignore
```

- [ ] **Step 3: Update conftest files**

```bash
sed -i 's/hapax_voice/hapax_daimonion/g; s/hapax-voice/hapax-daimonion/g' \
    conftest.py tests/conftest.py tests/consent_strategies.py
```

- [ ] **Step 4: Update process-compose.yaml**

```bash
sed -i 's/hapax-voice/hapax-daimonion/g; s/hapax_voice/hapax_daimonion/g; s/Hapax Voice/Hapax Daimonion/g' \
    process-compose.yaml
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: rename hapax-voice in CI, config, and process-compose"
```

---

## Task 7: Update Rust/frontend code

**Files:**
- Modify: `hapax-logos/src-tauri/src/commands/system_flow.rs`

- [ ] **Step 1: Update Rust perception state path**

In `hapax-logos/src-tauri/src/commands/system_flow.rs:113`:
```
"{}/.cache/hapax-voice/perception-state.json"
```
→
```
"{}/.cache/hapax-daimonion/perception-state.json"
```

```bash
sed -i 's/hapax-voice/hapax-daimonion/g' \
    hapax-logos/src-tauri/src/commands/system_flow.rs
```

- [ ] **Step 2: Check for any other frontend references**

```bash
grep -rn "hapax.voice\|hapax_voice\|hapax-voice" hapax-logos/src/ hapax-logos/src-tauri/src/ \
    --include="*.ts" --include="*.tsx" --include="*.rs" 2>/dev/null
```

Expected: zero matches.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "refactor: rename hapax-voice path in Tauri Rust code"
```

---

## Task 8: Update documentation (hapax-council)

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: All `.md` files under `docs/`
- Modify: All `.md` files under `agents/hapax_daimonion/` (already renamed dir)
- Modify: `agents/hapax_daimonion/LAYER_STATUS.yaml`
- Modify: `agents/hapax_daimonion/DESIGN-conversational-continuity.md`
- Modify: Research proofs in `agents/hapax_daimonion/proofs/`

- [ ] **Step 1: Bulk replace in all markdown files**

```bash
find . -name '*.md' -not -path './.git/*' \
    -exec sed -i 's/hapax_voice/hapax_daimonion/g; s/hapax-voice/hapax-daimonion/g; s/Hapax Voice/Hapax Daimonion/g; s/hapax voice/hapax daimonion/g' {} +
```

- [ ] **Step 2: Update YAML files**

```bash
find . -name '*.yaml' -o -name '*.yml' | grep -v .git | grep -v node_modules | \
    xargs sed -i 's/hapax_voice/hapax_daimonion/g; s/hapax-voice/hapax-daimonion/g; s/Hapax Voice/Hapax Daimonion/g'
```

- [ ] **Step 3: Verify no remaining references in docs**

```bash
grep -rn "hapax.voice\|hapax_voice\|hapax-voice" --include="*.md" --include="*.yaml" --include="*.yml" . \
    | grep -v .git/ | grep -v node_modules
```

Expected: zero matches (or only generic "voice" without "hapax" prefix).

- [ ] **Step 4: Commit documentation changes**

```bash
git add -A
git commit -m "docs: rename hapax-voice references to hapax-daimonion"
```

---

## Task 9: Run tests and fix breakage

- [ ] **Step 1: Run ruff lint**

```bash
uv run ruff check . 2>&1 | head -50
```

Fix any import errors from the rename.

- [ ] **Step 2: Run ruff format**

```bash
uv run ruff format .
```

- [ ] **Step 3: Run pyright type check**

```bash
uv run pyright 2>&1 | head -50
```

- [ ] **Step 4: Run the test suite (excluding LLM-tagged tests)**

```bash
uv run pytest tests/ -q --ignore=tests/hapax_daimonion --ignore=tests/contract \
    --ignore=tests/test_hapax_daimonion_pipecat_tts.py \
    --ignore=tests/test_hapax_daimonion_pipeline.py \
    -x 2>&1 | tail -30
```

- [ ] **Step 5: Run daimonion-specific tests**

```bash
uv run pytest tests/hapax_daimonion/ -q -x 2>&1 | tail -30
```

- [ ] **Step 6: Fix any failures**

Common issues:
- Hardcoded strings in test assertions that reference old name
- Fixtures or mocks patching old module paths
- `conftest.py` stub imports using old paths

- [ ] **Step 7: Commit fixes**

```bash
git add -A
git commit -m "fix: resolve test failures from daimonion rename"
```

---

## Task 10: Create runtime migration script

A one-shot script to migrate runtime data directories on the live system.

**Files:**
- Create: `scripts/migrate-voice-to-daimonion.sh`

- [ ] **Step 1: Write migration script**

```bash
#!/usr/bin/env bash
# One-shot migration: move hapax-voice runtime data to hapax-daimonion.
# Run once after deploying the rename. Idempotent — safe to re-run.
set -euo pipefail

echo "=== Migrating hapax-voice → hapax-daimonion runtime data ==="

# Stop the daemon first
systemctl --user stop hapax-voice.service 2>/dev/null || true

# 1. Cache directory
if [ -d "$HOME/.cache/hapax-voice" ]; then
    mkdir -p "$HOME/.cache/hapax-daimonion"
    cp -a "$HOME/.cache/hapax-voice/"* "$HOME/.cache/hapax-daimonion/" 2>/dev/null || true
    echo "  ✓ ~/.cache/hapax-voice → ~/.cache/hapax-daimonion"
fi

# 2. Local share directory
if [ -d "$HOME/.local/share/hapax-voice" ]; then
    mkdir -p "$HOME/.local/share/hapax-daimonion"
    cp -a "$HOME/.local/share/hapax-voice/"* "$HOME/.local/share/hapax-daimonion/" 2>/dev/null || true
    echo "  ✓ ~/.local/share/hapax-voice → ~/.local/share/hapax-daimonion"
fi

# 3. Config directory
if [ -d "$HOME/.config/hapax-voice" ]; then
    mkdir -p "$HOME/.config/hapax-daimonion"
    cp -a "$HOME/.config/hapax-voice/"* "$HOME/.config/hapax-daimonion/" 2>/dev/null || true
    echo "  ✓ ~/.config/hapax-voice → ~/.config/hapax-daimonion"
fi

# 4. Shared memory (ephemeral — just create the new dir)
mkdir -p /dev/shm/hapax-daimonion

# 5. Clean up old socket and PID
rm -f /run/user/$(id -u)/hapax-voice.sock
rm -f /run/user/$(id -u)/hapax-voice.pid

# 6. Install new systemd unit, remove old
echo "  Installing hapax-daimonion.service..."
UNIT_SRC="$HOME/projects/hapax-council/systemd/units/hapax-daimonion.service"
UNIT_DST="$HOME/.config/systemd/user/hapax-daimonion.service"
if [ -f "$UNIT_SRC" ]; then
    cp "$UNIT_SRC" "$UNIT_DST"
fi
systemctl --user disable hapax-voice.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/hapax-voice.service"

# 7. Update dependency units
for unit in visual-layer-aggregator.service studio-compositor.service; do
    src="$HOME/projects/hapax-council/systemd/units/$unit"
    dst="$HOME/.config/systemd/user/$unit"
    [ -f "$src" ] && cp "$src" "$dst"
done

# 8. Update overrides
OVERRIDE_DIR="$HOME/.config/systemd/user/studio-compositor.service.d"
OVERRIDE_SRC="$HOME/projects/hapax-council/systemd/overrides/studio-compositor.service.d/ordering.conf"
if [ -f "$OVERRIDE_SRC" ]; then
    mkdir -p "$OVERRIDE_DIR"
    cp "$OVERRIDE_SRC" "$OVERRIDE_DIR/ordering.conf"
fi

# 9. Update rebuild-services unit
REBUILD_SRC="$HOME/projects/hapax-council/systemd/hapax-rebuild-services.service"
REBUILD_DST="$HOME/.config/systemd/user/hapax-rebuild-services.service"
[ -f "$REBUILD_SRC" ] && cp "$REBUILD_SRC" "$REBUILD_DST"

# 10. Reload and start
systemctl --user daemon-reload
systemctl --user enable hapax-daimonion.service
systemctl --user start hapax-daimonion.service

echo ""
echo "=== Migration complete ==="
echo "Old directories preserved (remove manually when confirmed working):"
echo "  rm -rf ~/.cache/hapax-voice"
echo "  rm -rf ~/.local/share/hapax-voice"
echo "  rm -rf ~/.config/hapax-voice"
```

- [ ] **Step 2: Make executable and commit**

```bash
chmod +x scripts/migrate-voice-to-daimonion.sh
git add scripts/migrate-voice-to-daimonion.sh
git commit -m "feat: add one-shot migration script for voice→daimonion runtime data"
```

---

## Task 11: Update wireplumber config

**Files:**
- Modify: `~/.config/wireplumber/wireplumber.conf.d/50-hapax-voice-duck.conf` (system config, not in repo)

- [ ] **Step 1: Update wireplumber description**

In `~/.config/wireplumber/wireplumber.conf.d/50-hapax-voice-duck.conf`:
- Update comment: `Hapax Voice` → `Hapax Daimonion`
- Update `node.description`: `"Hapax Voice Assistant"` → `"Hapax Daimonion Assistant"`
- Keep filename as `50-hapax-voice-duck.conf` (functional name, describes what it does)

```bash
sed -i 's/Hapax Voice/Hapax Daimonion/g' \
    ~/.config/wireplumber/wireplumber.conf.d/50-hapax-voice-duck.conf
```

---

## Task 12: PR and merge (hapax-council)

- [ ] **Step 1: Final verification**

```bash
# Ensure no stale references remain
grep -rn "hapax.voice\b\|hapax_voice\|hapax-voice" --include="*.py" --include="*.rs" \
    --include="*.service" --include="*.timer" --include="*.sh" --include="*.yaml" \
    --include="*.yml" --include="*.toml" . 2>/dev/null \
    | grep -v .git/ | grep -v __pycache__ | grep -v node_modules | grep -v target/
```

Expected: zero matches.

- [ ] **Step 2: Push and create PR**

```bash
git push -u origin feat/rename-daimonion
gh pr create --title "refactor: rename hapax-voice to hapax-daimonion" \
    --body "$(cat <<'PREOF'
## Summary
- Rename `agents/hapax_voice/` → `agents/hapax_daimonion/` (105 Python modules, 25 backends, 6 salience modules)
- Rename `tests/hapax_voice/` → `tests/hapax_daimonion/` (145 test files) + 19 root test files
- Update all imports, path strings, systemd units, scripts, CI, docs
- Systemd: `hapax-voice.service` → `hapax-daimonion.service`
- Runtime paths: `~/.cache/hapax-daimonion/`, `~/.local/share/hapax-daimonion/`, `/dev/shm/hapax-daimonion/`
- Migration script: `scripts/migrate-voice-to-daimonion.sh`

## Test plan
- [ ] `uv run ruff check .` — zero errors
- [ ] `uv run pytest tests/ -q` — all passing
- [ ] `scripts/migrate-voice-to-daimonion.sh` — daemon starts under new name
- [ ] `systemctl --user status hapax-daimonion` — active

🤖 Generated with [Claude Code](https://claude.com/claude-code)
PREOF
)"
```

- [ ] **Step 3: Monitor CI, fix failures, merge when green**

- [ ] **Step 4: Run migration script on live system**

```bash
bash scripts/migrate-voice-to-daimonion.sh
```

- [ ] **Step 5: Notify alpha to rebase**

Update `beta.yaml` noting the merge so alpha rebases onto main.

---

## Task 13: Update other repos (separate PRs)

Each repo gets its own branch and PR. These are documentation-only changes.

### 13a: hapax-constitution

```bash
cd ~/projects/hapax-constitution
git checkout -b docs/rename-daimonion
find . -name '*.md' -o -name '*.yaml' -o -name '*.yml' | xargs \
    sed -i 's/hapax_voice/hapax_daimonion/g; s/hapax-voice/hapax-daimonion/g; s/Hapax Voice/Hapax Daimonion/g'
git add -A && git commit -m "docs: rename hapax-voice to hapax-daimonion"
git push -u origin docs/rename-daimonion
gh pr create --title "docs: rename hapax-voice to hapax-daimonion" --body "Tracks council rename PR."
```

### 13b: hapax-officium

```bash
cd ~/projects/hapax-officium
git checkout -b docs/rename-daimonion
find docs/ -name '*.md' | xargs sed -i 's/hapax_voice/hapax_daimonion/g; s/hapax-voice/hapax-daimonion/g'
git add -A && git commit -m "docs: rename hapax-voice to hapax-daimonion"
git push -u origin docs/rename-daimonion
gh pr create --title "docs: rename hapax-voice to hapax-daimonion" --body "Tracks council rename PR."
```

### 13c: hapax-watch

```bash
cd ~/projects/hapax-watch
git checkout -b docs/rename-daimonion
find docs/ -name '*.md' | xargs sed -i 's/hapax_voice/hapax_daimonion/g; s/hapax-voice/hapax-daimonion/g; s/Hapax Voice/Hapax Daimonion/g'
git add -A && git commit -m "docs: rename hapax-voice to hapax-daimonion"
git push -u origin docs/rename-daimonion
gh pr create --title "docs: rename hapax-voice to hapax-daimonion" --body "Tracks council rename PR."
```

### 13d: distro-work

```bash
cd ~/projects/distro-work
git checkout -b docs/rename-daimonion
find . -name '*.sh' -o -name '*.md' | xargs \
    sed -i 's/hapax_voice/hapax_daimonion/g; s/hapax-voice/hapax-daimonion/g; s/Hapax Voice/Hapax Daimonion/g'
git add -A && git commit -m "docs: rename hapax-voice to hapax-daimonion"
git push -u origin docs/rename-daimonion
gh pr create --title "docs: rename hapax-voice to hapax-daimonion" --body "Tracks council rename PR."
```

### 13e: hapax-mcp

Check for references:

```bash
cd ~/projects/hapax-mcp
grep -rn "hapax_voice\|hapax-voice" --include="*.py" --include="*.md" .
```

If found, same pattern: branch, sed, commit, PR.

---

## Task 14: Update relay and memory files

**Files:**
- Modify: `~/.cache/hapax/relay/onboarding-alpha.md`
- Modify: `~/.cache/hapax/relay/onboarding-beta.md`
- Modify: `~/.cache/hapax/relay/context/*.md` (all handoff docs)
- Modify: `~/.cache/hapax/relay/queue/*.yaml` (any voice references)
- Modify: `~/.cache/hapax/relay/convergence.log`
- Modify: `~/.claude/projects/-home-hapax-projects/memory/MEMORY.md` (update references)

- [ ] **Step 1: Update relay files**

```bash
find ~/.cache/hapax/relay/ -type f \( -name '*.md' -o -name '*.yaml' -o -name '*.log' \) \
    -exec sed -i 's/hapax_voice/hapax_daimonion/g; s/hapax-voice/hapax-daimonion/g; s/Hapax Voice/Hapax Daimonion/g' {} +
```

- [ ] **Step 2: Update memory files**

Review and update any memory files that reference hapax-voice.

---

## Risk Notes

1. **VoiceConfig rename**: Any external tools or scripts referencing `VoiceConfig` by string (e.g., YAML config files loading classes by name) will break. Check `~/.config/hapax-voice/config.yaml` if it exists.
2. **Langfuse traces**: Historical traces will reference `hapax_voice`. No action needed — these are historical records.
3. **Qdrant collections**: If any collection metadata references `hapax_voice`, it's read-only historical data.
4. **Journal logs**: `journalctl -u hapax-voice` will show old logs. New logs under `hapax-daimonion`.
5. **Old data dirs preserved**: Migration script copies, doesn't move. Manual cleanup after verification.
