# Handoff: Enforce LLM-Optimized Code Patterns

**Purpose:** Configure the codebase so all future code written by Claude Code (or any LLM agent) is optimized for LLM comprehension, not human readability. Enforcement, not guidelines.

**Prior work:** PRs #454-#458 restructured the codebase (self-contained packages, vendored deps, METADATA.yaml, type narrowing, monolith decomposition). This handoff specifies how to PREVENT regression and ENFORCE the patterns going forward.

---

## Context: The Enforcement Stack

Four layers, ordered by strength:

| Layer | Mechanism | When it fires | Can block? |
|-------|-----------|---------------|------------|
| 1 | CLAUDE.md directives | Session start (read once) | No — advisory only |
| 2 | PreToolUse hooks | Before every Edit/Write/Bash | **Yes** — exit 2 blocks |
| 3 | Pre-commit hooks | Before every git commit | **Yes** — non-zero blocks |
| 4 | basedpyright strict | Manual or CI run | **Yes** — errors block CI |

**Key insight:** PreToolUse hooks are the strongest mechanism. They fire before every single tool call. Claude cannot bypass them. Everything enforceable goes here. CLAUDE.md is for intent; hooks are for enforcement.

**Existing hooks (10 active):** axiom-scan, axiom-commit-scan, pip-guard, no-stale-branches, work-resolution-gate, registry-guard, safe-stash-guard, conductor-pre, pii-guard, branch-switch-guard. All at `$HAPAX_COUNCIL_DIR/hooks/scripts/`. Registered in `$HOME/.claude/settings.json` under `hooks.PreToolUse`.

---

## Task 1: Add `llm-file-size-gate.sh` PreToolUse Hook

**What it enforces:** No Python file may exceed 300 LOC after a Write or Edit. Forces modular code that fits in LLM context windows.

**Why 300 and not 200:** The restructuring showed that some class skeletons (daemon.py at 349, connectivity checks at 308) legitimately need 250-350 LOC. 300 catches genuine monoliths while allowing coherent single-class modules.

### Implementation

Create `$HAPAX_COUNCIL_DIR/hooks/scripts/llm-file-size-gate.sh`:

- Gates: Edit, Write, MultiEdit
- Reads `tool_input.file_path` and `tool_input.content` (Write) or `tool_input.new_string`/`tool_input.old_string` (Edit)
- For Write: counts lines in content, blocks if > 300
- For Edit: estimates result as `current_lines - old_lines + new_lines`, blocks if > 300
- Exempts: test files (`tests/`), generated files (`*.generated.py`), vendored shims (`_*.py`), non-Python files

Exit 2 with message: `"BLOCKED: File would be N lines (max 300). Split into smaller modules."`

### Registration

Add to `$HOME/.claude/settings.json` under `hooks.PreToolUse`:

```json
{
  "matcher": "Edit|Write|MultiEdit",
  "hooks": [{ "type": "command", "command": "$HAPAX_COUNCIL_DIR/hooks/scripts/llm-file-size-gate.sh" }]
}
```

Substitute `$HAPAX_COUNCIL_DIR` with the actual absolute path when registering.

### Verification

Test with a 350-line Python file write (should block) and a 50-line write (should allow). Test that `_*.py` vendored shims are exempt.

---

## Task 2: Add `llm-import-gate.sh` PreToolUse Hook

**What it enforces:** No new `from shared.` imports in consumer code (agents/, logos/). Only vendored shim files (`_*.py`) may import from shared/.

### Implementation

Create `$HAPAX_COUNCIL_DIR/hooks/scripts/llm-import-gate.sh`:

- Gates: Edit, Write, MultiEdit
- Reads `tool_input.file_path` — only checks `*/agents/*.py` and `*/logos/*.py`
- Reads `tool_input.new_string` or `tool_input.content`
- Greps for `^\s*from shared\.` in the new content
- Exempts: vendored shims (`_*.py`), files inside `shared/` itself, test files
- Exit 2 with message: `"BLOCKED: Consumer code must not import from shared/. Use vendored modules: from agents._config import X"`

### Registration

Same pattern as Task 1 — add to `hooks.PreToolUse` with matcher `Edit|Write|MultiEdit`.

---

## Task 3: Add `llm-metadata-gate.sh` PostToolUse Hook

**What it enforces:** When a new `__init__.py` is created in agents/, warns if no METADATA.yaml exists in that directory.

### Implementation

Create `$HAPAX_COUNCIL_DIR/hooks/scripts/llm-metadata-gate.sh`:

- Gates: Write (PostToolUse — advisory, not blocking)
- Triggers on `*/agents/*/__init__.py` file writes
- Checks if `dirname(file_path)/METADATA.yaml` exists
- If missing, prints warning with the exact command to generate it:
  `uv run python scripts/llm_metadata_gen.py agents.<name> --write`
- Always exits 0 (advisory only)

### Registration

Add to `$HOME/.claude/settings.json` under `hooks.PostToolUse`:

```json
{
  "matcher": "Write",
  "hooks": [{ "type": "command", "command": "$HAPAX_COUNCIL_DIR/hooks/scripts/llm-metadata-gate.sh" }]
}
```

---

## Task 4: Add pre-commit hook for LLM patterns

**What it enforces at commit time:** No staged Python files over 300 LOC (excluding tests/shims), Any type warnings in diff, METADATA.yaml presence for new packages.

### Implementation

Create `$HAPAX_COUNCIL_DIR/scripts/check-llm-patterns` (executable):

Three checks:
1. **Any types in diff:** `git diff --cached` for added lines containing `\bAny\b`. Advisory warning (does not block — some third-party stubs require Any).
2. **File size:** For each staged `.py` file (excluding tests/, `_*.py`), check `wc -l`. Block (exit 1) if any file > 300 LOC.
3. **METADATA.yaml:** For each staged `__init__.py` in `agents/*/`, check for sibling METADATA.yaml. Advisory warning.

### Registration

Add to `.pre-commit-config.yaml`:

```yaml
  - repo: local
    hooks:
      - id: llm-patterns
        name: LLM-optimized code patterns
        entry: scripts/check-llm-patterns
        language: script
        always_run: true
        pass_filenames: false
```

---

## Task 5: Switch to basedpyright with `reportExplicitAny`

**What it enforces:** Explicit `Any` type annotations produce warnings. Standard pyright rejected `reportAny` (issue #6165). basedpyright (community fork) adds it as a drop-in replacement.

### Implementation

```bash
uv add --dev basedpyright
```

Replace `pyrightconfig.json`:

```json
{
    "include": ["agents", "logos"],
    "exclude": ["tests", "shared", "**/__pycache__"],
    "pythonVersion": "3.12",
    "typeCheckingMode": "basic",
    "reportExplicitAny": "warning",
    "reportMissingImports": false,
    "reportMissingTypeStubs": false
}
```

**Why `"warning"` not `"error"`:** 81 existing `Any` types are genuinely dynamic (GStreamer, ML models, hardware). Start with warnings, escalate after fixing.

**Why basic not strict:** Strict enables dozens of reports simultaneously. Enable incrementally.

### Verification

```bash
uv run basedpyright agents/drift_detector/  # Should show 0 errors (no Any types)
uv run basedpyright agents/ 2>&1 | grep "Any" | wc -l  # Should show ~81 warnings
```

---

## Task 6: Add LLM-Optimization Section to CLAUDE.md

Append to `$HAPAX_COUNCIL_DIR/CLAUDE.md`:

```markdown
## LLM-Optimized Code Patterns

All code is written for LLM comprehension. These patterns are enforced by hooks.

**Self-contained modules:**
- Every agent is a self-contained package with vendored dependencies
- No `from shared.` imports in consumer code (use `from agents._X` vendored modules)
- Cross-agent imports forbidden — vendor needed schemas

**File size:**
- No Python file over 300 LOC (enforced by `llm-file-size-gate.sh`)
- Split by concern before continuing if a file grows beyond 300

**Type density:**
- Zero explicit `Any` types (enforced by basedpyright `reportExplicitAny`)
- Use concrete types, tagged unions with `Literal`, or Protocol classes
- 81 legacy `Any` in GStreamer/ML/hardware — do not add new ones

**METADATA.yaml:**
- Every agent package must have a `METADATA.yaml`
- Generate: `uv run python scripts/llm_metadata_gen.py agents.<name> --write`
- Validate: `uv run python scripts/llm_validate.py`

**No dynamic dispatch:**
- No `__getattr__` for lazy loading
- No registry-based dispatch — use explicit function calls
- All code paths statically traceable

**Vendored dependencies:**
- 66 shims at `agents/_*.py`, 40 at `logos/_*.py`
- New vendored modules: `agents/_<module>.py` with underscore prefix
- Generate: `uv run python scripts/llm_vendor.py agents.<name> --apply`

**Token budget:**
- Check: `uv run python scripts/llm_import_graph.py --module <name>`
- Target: <5K tokens per self-contained package
```

---

## Task 7: Verification Script

Create `$HAPAX_COUNCIL_DIR/scripts/check-llm-invariants` (executable):

Validates all LLM-optimization invariants in one run:

1. **File size:** Find all `.py` files over 300 LOC (excluding tests, shims). Report count and names.
2. **shared/ imports:** Grep for `from shared.` in consumer code (not shims). Any match = FAIL.
3. **Any types:** Count explicit `Any` in agents/logos/. Compare against baseline (81). Warn if increased.
4. **METADATA.yaml coverage:** For each `agents/*/` package, check for METADATA.yaml. Report missing.
5. **MANIFEST.json sync:** Compare MANIFEST.json package count against actual METADATA.yaml file count.

Exit 0 if no errors (warnings OK). Exit non-zero if hard violations found.

### Usage

```bash
bash scripts/check-llm-invariants
# Output:
# === LLM Codebase Invariant Check ===
# 1. File size: WARN: 56 files over 300 LOC (pre-existing)
# 2. shared/ imports: OK (0 in consumer code)
# 3. Any types: OK (81, at baseline)
# 4. METADATA.yaml: OK (90 files, 2 packages missing)
# 5. MANIFEST.json: OK (85 packages indexed)
# === Summary ===
# Errors: 0, Warnings: 58
# Status: PASS
```

---

## Implementation Order

| # | Task | Type | Effort |
|---|------|------|--------|
| 1 | `llm-file-size-gate.sh` | PreToolUse hook | 15 min |
| 2 | `llm-import-gate.sh` | PreToolUse hook | 15 min |
| 3 | `llm-metadata-gate.sh` | PostToolUse hook | 10 min |
| 4 | `check-llm-patterns` | Pre-commit hook | 15 min |
| 5 | basedpyright | Type checker config | 20 min |
| 6 | CLAUDE.md update | Documentation | 10 min |
| 7 | `check-llm-invariants` | Verification script | 10 min |

**Total: ~1.5 hours.** One commit per task, each independently valid.

---

## What This Does NOT Enforce

These mechanisms enforce patterns for **new code**. They do not retroactively fix:

- 81 existing `Any` types (basedpyright warns but doesn't block)
- 56 existing files over 500 LOC (hook only blocks NEW writes over 300)
- 22 vendored shims that still import from shared/ (exempt by design)
- 15 files over 1000 LOC (pre-existing, not caught by hook unless rewritten)

To address pre-existing violations, run `scripts/check-llm-invariants` periodically and fix warnings incrementally.
