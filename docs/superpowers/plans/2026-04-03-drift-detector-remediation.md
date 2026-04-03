# Drift Detector Remediation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the drift detector so its output is actionable — eliminate noise, remove dead config, correct scheduling, and deduplicate paths.

**Architecture:** The drift detector (`agents/drift_detector/`) compares documentation claims against live infrastructure. It has a hybrid pipeline: 6 deterministic scanners run first, then an LLM (gemini-flash via pydantic-ai) compares docs against an infrastructure manifest. Output goes to `profiles/drift-report.json` and `profiles/drift-history.jsonl`. A systemd timer triggers the watchdog script. Currently 173 items, 130 of which are coverage-gap noise from an ill-fitted registry rule. Five of ten configured doc sources are dead paths. The timer fires weekly but the manifest claims 12h/twice-daily. Two path aliases resolve to the same directory, producing duplicate items.

**Tech Stack:** Python 3.12, Pydantic, pydantic-ai, YAML, systemd timers, bash watchdog

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `agents/drift_detector/docs.py` | Modify | Remove 5 dead doc paths, add current sources, deduplicate HAPAX_REPO_DIRS, update EXPECTED_DEVICES |
| `agents/drift_detector/config.py` | Modify | Remove legacy aliases, remove dead MODELS entries, fix vendored comment |
| `agents/manifests/drift_detector.yaml` | Modify | Correct schedule from 12h to weekly |
| `document-registry.yaml` (hapax-constitution) | Modify | Add `exclude_patterns` to agent coverage rule |
| `agents/drift_detector/registry_checks.py` | Modify | Support `exclude_patterns` in coverage rules |
| `tests/test_drift_detector.py` | Modify | Add test for exclude_patterns |
| `tests/test_registry_checks.py` | Modify | Add test for exclude_patterns filtering |

---

### Task 1: Fix Coverage Rule Noise (130 → ~5 items)

The agent coverage rule in `document-registry.yaml` demands every discovered agent appear in `## Key Modules`. CLAUDE.md documents 7 shared modules, not 45 agents — the rule is ill-fitted. Two changes: add `exclude_patterns` support to registry_checks, and add sensible excludes to the registry.

**Files:**
- Modify: `agents/drift_detector/document_registry.py:33` (CoverageRule dataclass)
- Modify: `agents/drift_detector/registry_checks.py:86-148` (check_coverage_rules)
- Modify: `~/projects/hapax-constitution/docs/document-registry.yaml` (coverage_rules section)
- Test: `tests/test_registry_checks.py`

- [ ] **Step 1: Write the failing test for exclude_patterns**

In `tests/test_registry_checks.py`, add:

```python
def test_coverage_rule_exclude_patterns():
    """Coverage rules with exclude_patterns skip matching CIs."""
    from agents.drift_detector.document_registry import CoverageRule, DocumentRegistry, load_registry
    from agents.drift_detector.registry_checks import check_coverage_rules

    yaml_content = """
version: 2
archetypes: {}
repos: {}
coverage_rules:
  - ci_type: agent
    reference_doc: /tmp/test-doc.md
    reference_section: ""
    match_by: name
    severity: medium
    description: "Every agent must be documented"
    exclude_patterns:
      - "*-sync"
      - "demo*"
mutual_awareness: []
"""
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("# Doc\n## Agents\n- briefing\n- profiler\n")
        doc_path = f.name

    try:
        registry = load_registry(yaml_content=yaml_content)
        assert registry is not None

        # These agents exist but should be excluded by patterns
        discovered = {
            "agent": ["briefing", "chrome-sync", "gdrive-sync", "demo", "demo-eval", "profiler"],
        }

        items = check_coverage_rules(registry, discovered_cis=discovered)

        # chrome-sync and gdrive-sync excluded by *-sync
        # demo and demo-eval excluded by demo*
        # briefing and profiler are in the doc
        # So: 0 items expected
        assert len(items) == 0, f"Expected 0 items, got {len(items)}: {[i.reality for i in items]}"
    finally:
        Path(doc_path).unlink(missing_ok=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_registry_checks.py::test_coverage_rule_exclude_patterns -v`
Expected: FAIL — `exclude_patterns` not recognized by load_registry or check_coverage_rules

- [ ] **Step 3: Add exclude_patterns to CoverageRule dataclass**

In `agents/drift_detector/document_registry.py`, modify `CoverageRule`:

```python
@dataclass
class CoverageRule:
    """A CI-to-document coverage assertion."""

    ci_type: str = ""
    reference_doc: str = ""
    reference_section: str = ""
    match_by: str = "name"
    severity: str = "medium"
    description: str = ""
    exclude_patterns: list[str] = field(default_factory=list)
```

And in `load_registry()`, in the coverage_rules parsing block (~line 108-118), add:

```python
    for rule_data in data.get("coverage_rules", []):
        reg.coverage_rules.append(
            CoverageRule(
                ci_type=rule_data.get("ci_type", ""),
                reference_doc=rule_data.get("reference_doc", ""),
                reference_section=rule_data.get("reference_section", ""),
                match_by=rule_data.get("match_by", "name"),
                severity=rule_data.get("severity", "medium"),
                description=rule_data.get("description", ""),
                exclude_patterns=rule_data.get("exclude_patterns", []),
            )
        )
```

- [ ] **Step 4: Add exclude_patterns filtering to check_coverage_rules**

In `agents/drift_detector/registry_checks.py`, add a helper and modify check_coverage_rules:

```python
import fnmatch

def _is_excluded(name: str, patterns: list[str]) -> bool:
    """Check if a CI name matches any exclude pattern (fnmatch glob)."""
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)
```

Then in `check_coverage_rules`, before the inner loop over ci_names (~line 131), filter:

```python
        for ci_name in ci_names:
            if _is_excluded(ci_name, rule.exclude_patterns):
                continue
            # ... rest of existing logic
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_registry_checks.py::test_coverage_rule_exclude_patterns -v`
Expected: PASS

- [ ] **Step 6: Update document-registry.yaml with exclude_patterns**

In `~/projects/hapax-constitution/docs/document-registry.yaml`, modify the agent coverage rule:

```yaml
  - ci_type: agent
    reference_doc: ~/projects/hapax-council/CLAUDE.md
    reference_section: "## Key Modules"
    match_by: name
    severity: medium
    description: "Every council agent must be referenced in CLAUDE.md"
    exclude_patterns:
      - "*-sync"       # 10 sync agents — utility tier, not architectural
      - "demo*"        # demo pipeline agents
      - "video-*"      # video capture/processing
      - "audio-*"      # audio processing
      - "code-review"  # CI-only agent
      - "sdlc-*"       # CI pipeline agents
      - "retroactive-*"  # batch labeling
      - "alignment-*"  # experimental
      - "flow-*"       # journaling
      - "browser-*"    # experimental
      - "storage-*"    # infrastructure
      - "weather-*"    # utility
      - "screen-*"     # utility
      - "watch-*"      # hardware receiver
      - "health-*"     # infrastructure
      - "av-*"         # experimental
```

- [ ] **Step 7: Run full registry check tests**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_registry_checks.py -v`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add agents/drift_detector/document_registry.py agents/drift_detector/registry_checks.py tests/test_registry_checks.py
git commit -m "feat(drift): add exclude_patterns to coverage rules, reduce noise from 130→~5 items"
```

Note: The document-registry.yaml change is in hapax-constitution — commit separately there.

---

### Task 2: Remove Dead Doc Paths and Deduplicate Repo Dirs

5 of 10 entries in DOC_FILES are dead (old Cursor-era rules paths). HAPAX_REPO_DIRS has `hapax-council` twice (via `AI_AGENTS_DIR` and `HAPAX_SYSTEM_DIR`). `obsidian-hapax` points to wrong location.

**Files:**
- Modify: `agents/drift_detector/docs.py:22-56`
- Modify: `agents/drift_detector/config.py:40-49`

- [ ] **Step 1: Clean up config.py legacy aliases**

In `agents/drift_detector/config.py`, replace lines 40-49:

```python
# Project directories
HAPAX_COUNCIL_DIR: Path = HAPAX_PROJECTS_DIR / "hapax-council"
HAPAX_CONSTITUTION_DIR: Path = HAPAX_PROJECTS_DIR / "hapax-constitution"
OBSIDIAN_HAPAX_DIR: Path = HAPAX_COUNCIL_DIR / "obsidian-hapax"

# Legacy aliases (used by docs.py and other modules)
AI_AGENTS_DIR: Path = HAPAX_COUNCIL_DIR
HAPAXROMANA_DIR: Path = HAPAX_CONSTITUTION_DIR
LOGOS_WEB_DIR: Path = HAPAX_COUNCIL_DIR / "hapax-logos"
HAPAX_VSCODE_DIR: Path = HAPAX_COUNCIL_DIR / "vscode"
```

Remove `HAPAX_SYSTEM_DIR` entirely — it was identical to `HAPAX_COUNCIL_DIR` and caused the duplicate.

- [ ] **Step 2: Fix DOC_FILES — remove dead paths, add current sources**

In `agents/drift_detector/docs.py`, replace lines 22-34:

```python
DOC_FILES = [
    CLAUDE_CONFIG_DIR / "CLAUDE.md",
    HAPAXROMANA_DIR / "CLAUDE.md",
    HAPAXROMANA_DIR / "agent-architecture.md",
    HAPAXROMANA_DIR / "operations-manual.md",
    HAPAXROMANA_DIR / "README.md",
    AI_AGENTS_DIR / "CLAUDE.md",
    AI_AGENTS_DIR / "docs" / "logos-design-language.md",
    AI_AGENTS_DIR / "systemd" / "README.md",
]
```

This removes 5 dead `rules/` paths and adds 2 current sources (design language, systemd README).

- [ ] **Step 3: Fix HAPAX_REPO_DIRS — deduplicate, fix obsidian-hapax path**

In `agents/drift_detector/docs.py`, replace lines 42-49 and remove the `HAPAX_SYSTEM_DIR` import:

```python
HAPAX_REPO_DIRS = [
    AI_AGENTS_DIR,
    HAPAXROMANA_DIR,
    LOGOS_WEB_DIR,
    OBSIDIAN_HAPAX_DIR,
    HAPAX_VSCODE_DIR,
]
```

This removes the duplicate `HAPAX_SYSTEM_DIR` entry. The old list had 6 entries with 2 resolving to hapax-council — now 5 unique dirs.

Update the import at the top of docs.py to remove `HAPAX_SYSTEM_DIR`:

```python
from .config import (
    AI_AGENTS_DIR,
    CLAUDE_CONFIG_DIR,
    HAPAX_HOME,
    HAPAXROMANA_DIR,
    LOGOS_WEB_DIR,
    OBSIDIAN_HAPAX_DIR,
    HAPAX_VSCODE_DIR,
)
```

- [ ] **Step 4: Update EXPECTED_DEVICES**

In `agents/drift_detector/docs.py`, replace lines 37-40. Since the Pi fleet handles camera monitoring now and USB paths change with port mapping, remove hardware device checks entirely:

```python
# Hardware devices removed — Pi fleet handles camera monitoring (see pi-edge/).
EXPECTED_DEVICES: dict[str, str] = {}
```

- [ ] **Step 5: Verify docs load correctly**

Run: `cd ~/projects/hapax-council && uv run python -c "from agents.drift_detector.docs import DOC_FILES, HAPAX_REPO_DIRS; print(f'DOC_FILES: {len(DOC_FILES)}'); [print(f'  {\"EXISTS\" if p.is_file() else \"MISSING\"}: {p}') for p in DOC_FILES]; print(f'REPO_DIRS: {len(HAPAX_REPO_DIRS)}'); [print(f'  {p}') for p in HAPAX_REPO_DIRS]" 2>&1 | grep -v LITELLM`
Expected: All DOC_FILES exist, no duplicates in REPO_DIRS

- [ ] **Step 6: Run existing tests**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_drift_detector.py -v -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add agents/drift_detector/docs.py agents/drift_detector/config.py
git commit -m "fix(drift): remove 5 dead doc paths, deduplicate repo dirs, drop stale hardware checks"
```

---

### Task 3: Clean Up Vendored Config

`config.py` says "Vendored from shared/config.py" but has diverged. Dead model aliases, no LITELLM_KEY fallback to pass.

**Files:**
- Modify: `agents/drift_detector/config.py:1-78`

- [ ] **Step 1: Fix config.py header and model aliases**

In `agents/drift_detector/config.py`, replace line 1:

```python
"""Path constants and model factory for drift detector."""
```

Replace the MODELS dict (lines 55-62) — keep only what's used:

```python
MODELS: dict[str, str] = {
    "fast": "gemini-flash",
}
```

- [ ] **Step 2: Verify agent still loads**

Run: `cd ~/projects/hapax-council && uv run python -c "from agents.drift_detector.config import get_model; m = get_model('fast'); print(f'Model: {m}')" 2>&1 | grep -v LITELLM`
Expected: Model object prints without error

- [ ] **Step 3: Commit**

```bash
git add agents/drift_detector/config.py
git commit -m "fix(drift): clean vendored config, remove dead model aliases"
```

---

### Task 4: Fix Manifest Schedule Claims

The manifest claims "12h", "every 6 hours", and "twice daily (03:00 and 15:00)" — but the actual timer is `OnCalendar=Sun *-*-* 03:00:00` (weekly). The overrides for dev/rnd add Wednesday. Research mode (current) has no override installed.

**Files:**
- Modify: `agents/manifests/drift_detector.yaml`

- [ ] **Step 1: Correct the manifest**

In `agents/manifests/drift_detector.yaml`, fix schedule and narrative:

Replace line 27:
```yaml
  interval: weekly
```

Replace lines 46-58 (the narrative field):
```yaml
narrative: >-
  The Drift Detector compares documentation against actual system state, finding
  places where the two have diverged. It runs weekly (Sunday 03:00), consuming
  the infrastructure manifest and checking it against docs, configs, and README
  files. In dev/rnd mode, it runs twice weekly (Wednesday + Sunday). It produces
  a drift report with specific correction suggestions but never auto-applies
  fixes — the operator reviews and decides.
```

Replace line 73:
```yaml
  schedule_label: Weekly (Sun 03:00), twice-weekly in dev/rnd
```

Replace line 87:
```yaml
  - The drift detector timer runs weekly (Sunday 03:00).
```

- [ ] **Step 2: Commit**

```bash
git add agents/manifests/drift_detector.yaml
git commit -m "docs(drift): correct schedule claims — weekly, not 12h/twice-daily"
```

---

### Task 5: Verify End-to-End

Run the full drift detector and confirm the noise reduction.

**Files:** None (verification only)

- [ ] **Step 1: Run deterministic scanners only (fast)**

```bash
cd ~/projects/hapax-council && uv run python -c "
from agents.drift_detector.scanners import scan_sufficiency_gaps, check_doc_freshness, check_screen_context_drift, check_project_memory, scan_axiom_violations
from agents.drift_detector.registry_checks import check_document_registry
items = (scan_axiom_violations() + scan_sufficiency_gaps() + check_doc_freshness()
         + check_screen_context_drift() + check_project_memory() + check_document_registry())
from collections import Counter
cats = Counter(i.category for i in items)
print(f'Total deterministic: {len(items)}')
print(f'Categories: {dict(cats)}')
highs = [i for i in items if i.severity == 'high']
print(f'High: {len(highs)}')
for h in highs:
    print(f'  [{h.category}] {h.doc_claim[:80]}')
" 2>&1 | grep -v -e LITELLM -e warnings
```

Expected: coverage-gap count drops from 130 to ~5-10. Total under 50.

- [ ] **Step 2: Check for duplicate project_memory items**

In the output above, verify `missing_project_memory` items don't contain duplicates for the same file path. Previously hapax-council/CLAUDE.md appeared twice.

- [ ] **Step 3: Commit any remaining fixes**

If verification reveals issues, fix and commit.
