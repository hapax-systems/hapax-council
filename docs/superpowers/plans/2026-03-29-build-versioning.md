# Build Versioning & Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate build stomping between dev/prod and alpha/beta worktrees, make every running binary self-identifying, and enable instant rollback.

**Architecture:** Four layers — (1) vergen embeds git SHA + features at compile time, (2) `CARGO_TARGET_DIR` isolates prod builds from dev, (3) a justfile orchestrates build/install/rollback with pre-flight checks, (4) the rebuild timer delegates to the justfile.

**Tech Stack:** vergen-gitcl (Rust build deps), just (command runner), existing systemd timer

---

## File Structure

| File | Responsibility |
|------|---------------|
| `hapax-logos/src-tauri/build.rs` | Modify: add vergen git SHA + features emission |
| `hapax-logos/src-imagination/build.rs` | Create: vergen git SHA emission |
| `hapax-logos/src-tauri/Cargo.toml` | Modify: add vergen-gitcl build-dependency |
| `hapax-logos/src-imagination/Cargo.toml` | Modify: add vergen-gitcl build-dependency |
| `hapax-logos/src-tauri/src/commands/health.rs` | Modify: expose build info via IPC |
| `hapax-logos/src-imagination/src/main.rs` | Modify: --version flag + startup log |
| `hapax-logos/justfile` | Create: build orchestration recipes |
| `scripts/rebuild-logos.sh` | Modify: delegate to justfile |

---

### Task 1: Install just

- [ ] **Step 1: Install just via pacman**

```bash
sudo pacman -S just
```

- [ ] **Step 2: Verify**

```bash
just --version
```

Expected: `just 1.x.x`

---

### Task 2: Add vergen to hapax-logos (Tauri)

**Files:**
- Modify: `hapax-logos/src-tauri/Cargo.toml`
- Modify: `hapax-logos/src-tauri/build.rs`
- Modify: `hapax-logos/src-tauri/src/commands/health.rs`

- [ ] **Step 1: Add vergen-gitcl build-dependency**

In `hapax-logos/src-tauri/Cargo.toml`, add to `[build-dependencies]`:

```toml
[build-dependencies]
tauri-build = { version = "2.0", features = [] }
vergen-gitcl = { version = "1", features = ["build", "cargo"] }
```

- [ ] **Step 2: Update build.rs to emit vergen env vars**

Replace `hapax-logos/src-tauri/build.rs`:

```rust
use vergen_gitcl::{BuildBuilder, CargoBuilder, Emitter, GitclBuilder};

fn main() {
    // Emit build metadata as compile-time env vars
    let build = BuildBuilder::default().build_timestamp(true).build().unwrap();
    let git = GitclBuilder::default()
        .sha(true)
        .dirty(true)
        .branch(true)
        .build()
        .unwrap();
    let cargo = CargoBuilder::default().features(true).build().unwrap();

    Emitter::default()
        .add_instructions(&build)
        .unwrap()
        .add_instructions(&git)
        .unwrap()
        .add_instructions(&cargo)
        .unwrap()
        .emit()
        .unwrap();

    tauri_build::build();
}
```

- [ ] **Step 3: Expose build info in health command**

Read `hapax-logos/src-tauri/src/commands/health.rs`. Add a `get_build_info` command. If the file doesn't have existing health commands, add one:

```rust
use serde::Serialize;

#[derive(Debug, Serialize)]
pub struct BuildInfo {
    pub git_sha: &'static str,
    pub git_dirty: &'static str,
    pub git_branch: &'static str,
    pub build_timestamp: &'static str,
    pub cargo_features: &'static str,
}

#[tauri::command]
pub fn get_build_info() -> BuildInfo {
    BuildInfo {
        git_sha: env!("VERGEN_GIT_SHA"),
        git_dirty: option_env!("VERGEN_GIT_DIRTY").unwrap_or("unknown"),
        git_branch: option_env!("VERGEN_GIT_BRANCH").unwrap_or("detached"),
        build_timestamp: env!("VERGEN_BUILD_TIMESTAMP"),
        cargo_features: env!("VERGEN_CARGO_FEATURES"),
    }
}
```

Register `get_build_info` in `src-tauri/src/main.rs` alongside other commands in the `invoke_handler` macro.

- [ ] **Step 4: Build to verify vergen works**

```bash
cd hapax-logos && cargo build --release -p hapax-logos --features tauri/custom-protocol 2>&1 | tail -5
```

Expected: compiles without error, vergen emits env vars during build.

- [ ] **Step 5: Commit**

```bash
git add src-tauri/Cargo.toml src-tauri/build.rs src-tauri/src/commands/health.rs src-tauri/src/main.rs
git commit -m "feat(logos): embed git SHA + build info via vergen"
```

---

### Task 3: Add vergen to hapax-imagination

**Files:**
- Modify: `hapax-logos/src-imagination/Cargo.toml`
- Create: `hapax-logos/src-imagination/build.rs`
- Modify: `hapax-logos/src-imagination/src/main.rs`

- [ ] **Step 1: Add vergen-gitcl build-dependency**

In `hapax-logos/src-imagination/Cargo.toml`, add:

```toml
[build-dependencies]
vergen-gitcl = { version = "1", features = ["build", "cargo"] }
```

- [ ] **Step 2: Create build.rs**

Create `hapax-logos/src-imagination/build.rs`:

```rust
use vergen_gitcl::{BuildBuilder, Emitter, GitclBuilder};

fn main() {
    let build = BuildBuilder::default().build_timestamp(true).build().unwrap();
    let git = GitclBuilder::default()
        .sha(true)
        .dirty(true)
        .build()
        .unwrap();

    Emitter::default()
        .add_instructions(&build)
        .unwrap()
        .add_instructions(&git)
        .unwrap()
        .emit()
        .unwrap();
}
```

- [ ] **Step 3: Add --version flag and startup log**

In `hapax-logos/src-imagination/src/main.rs`, near the top of `fn main()` (after env_logger init), add:

```rust
// Version info (embedded at compile time by vergen)
const GIT_SHA: &str = env!("VERGEN_GIT_SHA");
const BUILD_TS: &str = env!("VERGEN_BUILD_TIMESTAMP");

if std::env::args().any(|a| a == "--version") {
    println!("hapax-imagination {} (built {})", GIT_SHA, BUILD_TS);
    return;
}

log::info!("hapax-imagination {} (built {})", GIT_SHA, BUILD_TS);
```

- [ ] **Step 4: Build and test --version**

```bash
cargo build --release -p hapax-imagination 2>&1 | tail -3
./target/release/hapax-imagination --version
```

Expected: prints `hapax-imagination abc1234 (built 2026-03-29T...)`

- [ ] **Step 5: Commit**

```bash
git add src-imagination/Cargo.toml src-imagination/build.rs src-imagination/src/main.rs
git commit -m "feat(imagination): embed git SHA + --version flag via vergen"
```

---

### Task 4: Create justfile

**Files:**
- Create: `hapax-logos/justfile`

- [ ] **Step 1: Write the justfile**

Create `hapax-logos/justfile`:

```just
# Hapax Logos + Imagination build orchestration.
# Production builds use an isolated CARGO_TARGET_DIR to prevent
# stomping dev builds (which use the default ./target/).

set dotenv-load := false

prod_target := env("HOME") / ".cache/hapax/build-target"
bin_dir     := env("HOME") / ".local/bin"
state_dir   := env("HOME") / ".cache/hapax/rebuild"
repo_root   := justfile_directory() / ".."

export CARGO_TARGET_DIR := prod_target

# ── Info ──────────────────────────────────────────────────────────

# Show version of installed binaries
version:
    @{{bin_dir}}/hapax-imagination --version 2>/dev/null || echo "hapax-imagination: not installed"
    @strings {{bin_dir}}/hapax-logos 2>/dev/null | grep -oP 'VERGEN_GIT_SHA=\K[a-f0-9]+' | head -1 | xargs -I{} echo "hapax-logos {}" || echo "hapax-logos: not installed"

# ── Build ─────────────────────────────────────────────────────────

# Build frontend (Vite)
frontend:
    pnpm build

# Build imagination binary
imagination:
    cargo build --release -p hapax-imagination

# Build logos binary with bundled frontend
logos: frontend
    cargo build --release -p hapax-logos --features tauri/custom-protocol

# Build everything
build: imagination logos

# ── Install ───────────────────────────────────────────────────────

# Pre-flight checks
check:
    #!/usr/bin/env bash
    set -euo pipefail
    # Verify we're building from a clean main-based state
    cd {{repo_root}}
    SHA=$(git rev-parse HEAD)
    MAIN_SHA=$(git rev-parse origin/main 2>/dev/null || echo "unknown")
    if [ "$SHA" != "$MAIN_SHA" ]; then
        echo "WARNING: HEAD ($SHA) != origin/main ($MAIN_SHA)"
        echo "Building from non-main commit. Proceed with caution."
    fi
    # Verify binaries exist
    LOGOS="{{prod_target}}/release/hapax-logos"
    IMAG="{{prod_target}}/release/hapax-imagination"
    [ -f "$LOGOS" ] || { echo "ERROR: $LOGOS not found — run 'just build' first"; exit 1; }
    [ -f "$IMAG" ] || { echo "ERROR: $IMAG not found — run 'just build' first"; exit 1; }
    echo "Pre-flight OK: $(git log --oneline -1)"

# Build, check, and install with rollback backup
install: build check
    #!/usr/bin/env bash
    set -euo pipefail
    LOGOS_SRC="{{prod_target}}/release/hapax-logos"
    IMAG_SRC="{{prod_target}}/release/hapax-imagination"
    LOGOS_DST="{{bin_dir}}/hapax-logos"
    IMAG_DST="{{bin_dir}}/hapax-imagination"

    # Backup current binaries
    [ -f "$LOGOS_DST" ] && cp "$LOGOS_DST" "$LOGOS_DST.prev"
    [ -f "$IMAG_DST" ] && cp "$IMAG_DST" "$IMAG_DST.prev"

    # Stop services
    systemctl --user stop hapax-imagination.service 2>/dev/null || true

    # Atomic-ish install (cp + immediate restart)
    cp "$LOGOS_SRC" "$LOGOS_DST"
    cp "$IMAG_SRC" "$IMAG_DST"

    # Restart
    systemctl --user start hapax-imagination.service 2>/dev/null || true

    echo "Installed. Previous binaries saved as .prev"
    {{bin_dir}}/hapax-imagination --version 2>/dev/null || true

# ── Rollback ──────────────────────────────────────────────────────

# Restore previous binaries
rollback:
    #!/usr/bin/env bash
    set -euo pipefail
    LOGOS="{{bin_dir}}/hapax-logos"
    IMAG="{{bin_dir}}/hapax-imagination"
    [ -f "$LOGOS.prev" ] || { echo "No logos backup found"; exit 1; }
    [ -f "$IMAG.prev" ] || { echo "No imagination backup found"; exit 1; }

    systemctl --user stop hapax-imagination.service 2>/dev/null || true
    mv "$LOGOS.prev" "$LOGOS"
    mv "$IMAG.prev" "$IMAG"
    systemctl --user start hapax-imagination.service 2>/dev/null || true
    echo "Rolled back."
    $IMAG --version 2>/dev/null || true

# ── Clean ─────────────────────────────────────────────────────────

# Remove production build cache (does not affect dev target/)
clean:
    rm -rf {{prod_target}}
    echo "Cleaned {{prod_target}}"
```

- [ ] **Step 2: Test the justfile**

```bash
cd hapax-logos
just version
just build 2>&1 | tail -5
just check
```

- [ ] **Step 3: Commit**

```bash
git add justfile
git commit -m "feat(logos): justfile for build orchestration with isolated CARGO_TARGET_DIR"
```

---

### Task 5: Update rebuild-logos.sh to use justfile

**Files:**
- Modify: `scripts/rebuild-logos.sh`

- [ ] **Step 1: Replace inline build commands with justfile call**

The rebuild script keeps its git-fetch + SHA-check logic (lines 1-61) but replaces the build+install section (lines 63-96) with a `just install` call.

Replace lines 63-96 of `scripts/rebuild-logos.sh` with:

```bash
# Build and install via justfile (isolated CARGO_TARGET_DIR, rollback backup)
cd "$CARGO_DIR"
if just install 2>"$STATE_DIR/build.log"; then
    echo "$CURRENT_SHA" > "$SHA_FILE"
    VERSION=$(just version 2>/dev/null | head -1)
    logger -t "$LOG_TAG" "rebuild complete — $VERSION"
    ntfy "Logos rebuild complete" "${CURRENT_SHA:0:8} installed" "default" "white_check_mark"
else
    logger -t "$LOG_TAG" "build failed — see $STATE_DIR/build.log"
    ntfy "Logos rebuild FAILED" "See ~/.cache/hapax/rebuild/build.log" "high" "x"
fi
```

- [ ] **Step 2: Verify the full script is coherent**

Read the complete script. Ensure the git-fetch preamble (lines 1-61) flows into the new just call, and the branch-restore postamble (lines 98-102) still runs.

- [ ] **Step 3: Test the timer manually**

```bash
bash scripts/rebuild-logos.sh
```

Expected: fetches main, calls `just install`, builds with isolated target dir, installs with .prev backup.

- [ ] **Step 4: Commit**

```bash
git add scripts/rebuild-logos.sh
git commit -m "refactor: rebuild-logos delegates to justfile"
```

---

### Task 6: Verify isolation

- [ ] **Step 1: Confirm prod and dev use different target dirs**

```bash
# Prod target (from justfile)
ls ~/.cache/hapax/build-target/release/hapax-logos 2>/dev/null && echo "PROD target exists"

# Dev target (from pnpm tauri dev)
ls hapax-logos/target/debug/hapax-logos 2>/dev/null && echo "DEV target exists"

# They should be completely separate
echo "Prod: $(stat -c %i ~/.cache/hapax/build-target/release/hapax-logos 2>/dev/null)"
echo "Dev:  $(stat -c %i hapax-logos/target/release/hapax-logos 2>/dev/null)"
```

Expected: different inodes (or only one exists). They must never be the same directory.

- [ ] **Step 2: Verify --version on running binary**

```bash
~/.local/bin/hapax-imagination --version
```

Expected: `hapax-imagination abc1234f (built 2026-03-29T14:00:00+00:00)`

- [ ] **Step 3: Verify rollback works**

```bash
cd hapax-logos
just rollback
~/.local/bin/hapax-imagination --version
```

Expected: prints the previous version's SHA.

```bash
# Restore the new version
just install
```

- [ ] **Step 4: Final commit — systemd units with visual-stack target**

Stage the systemd unit changes (PartOf, Wants for visual-stack.target) that were started earlier in this session:

```bash
git add systemd/units/hapax-visual-stack.target systemd/units/hapax-logos.service systemd/hapax-imagination.service systemd/units/hapax-dmn.service
git commit -m "feat: hapax-visual-stack.target groups visual pipeline services"
```

---
