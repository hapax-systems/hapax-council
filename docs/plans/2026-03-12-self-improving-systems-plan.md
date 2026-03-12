# Self-Improving Systems — Implementation Plan

**Date:** 2026-03-12
**Layer:** 3 of 3 (LLM-Driven SDLC)
**Status:** Plan
**Design doc:** `docs/plans/2026-03-12-self-improving-systems-design.md`
**Depends on:** Layer 1 (Reactive CI) + Layer 2 (Proactive SDLC) operational

---

## Phase 1: Instrument (Weeks 1-2)

### 1.1 Git Commit Tagging in health_monitor.py

**Goal:** Every health report includes the current `HEAD` commit hash, so regressions can be correlated with specific merges.

**Changes to `agents/health_monitor.py`:**

1. **Add `git_head` field to `HealthReport`** (line ~69):
   ```python
   class HealthReport(BaseModel):
       # ... existing fields ...
       git_head: str | None = None      # HEAD commit hash at time of check
       git_head_age_s: int | None = None  # seconds since HEAD commit
   ```

2. **Add `_get_git_head()` utility** after the existing utility functions (~line 191):
   ```python
   async def _get_git_head() -> tuple[str | None, int | None]:
       """Return (commit_hash, age_seconds) for current HEAD."""
       rc, sha, _ = await run_cmd(["git", "rev-parse", "HEAD"])
       if rc != 0:
           return None, None
       sha = sha.strip()[:12]
       rc2, ts_str, _ = await run_cmd(["git", "log", "-1", "--format=%ct", "HEAD"])
       if rc2 != 0:
           return sha, None
       try:
           age = int(time.time()) - int(ts_str.strip())
       except ValueError:
           age = None
       return sha, age
   ```

3. **Populate `git_head` in `run_all_checks()`** (the function that builds the final `HealthReport`):
   - Call `_get_git_head()` as part of the parallel check execution.
   - Set `report.git_head` and `report.git_head_age_s` before returning.

4. **Include in JSON output** — no changes needed since Pydantic serializes automatically.

**Test:** `test_health_monitor.py` — add a test that mocks `run_cmd` for git calls and verifies `git_head` appears in JSON output.

### 1.2 Incident Logging in alert_state.py

**Goal:** Every alert action is logged to a JSONL file for later analysis by the knowledge base builder.

**Changes to `shared/alert_state.py`:**

1. **Add incident log path constant** (top of file):
   ```python
   INCIDENT_LOG = Path("profiles/incidents.jsonl")
   ```

2. **Add `_log_incident()` function:**
   ```python
   def _log_incident(
       check_name: str,
       status: str,
       group: str,
       cycles: int,
       priority: str,
       action_type: str,  # "alert" | "recovery" | "escalation"
       message: str,
       git_head: str | None = None,
   ) -> None:
       """Append a structured incident record to JSONL log."""
       entry = {
           "timestamp": time.time(),
           "iso_time": datetime.now(UTC).isoformat(),
           "check_name": check_name,
           "status": status,
           "group": group,
           "cycles": cycles,
           "priority": priority,
           "action_type": action_type,
           "message": message,
           "git_head": git_head,
       }
       try:
           INCIDENT_LOG.parent.mkdir(parents=True, exist_ok=True)
           with INCIDENT_LOG.open("a", encoding="utf-8") as f:
               f.write(json.dumps(entry) + "\n")
       except OSError as exc:
           _log.warning("Failed to log incident: %s", exc)
   ```

3. **Call `_log_incident()` in `process_report()`:**
   - After building each alert action (line ~112-115): log with `action_type="alert"`.
   - After each recovery action (line ~78-83): log with `action_type="recovery"`.
   - On priority escalation (when priority changes from default to high/urgent): log with `action_type="escalation"`.

4. **Accept `git_head` parameter in `process_report()`:**
   ```python
   def process_report(
       report: dict,
       state_path: str | Path = "profiles/alert-state.json",
       git_head: str | None = None,  # NEW
   ) -> list[dict]:
   ```
   The watchdog script passes `report.get("git_head")` to this parameter.

5. **Add JSONL rotation** — same pattern as health-history.jsonl in the watchdog:
   ```python
   def rotate_incident_log(max_lines: int = 50_000, keep_lines: int = 25_000) -> None:
   ```

**Test:** `test_alert_state.py` — verify that `_log_incident` writes valid JSONL, verify `process_report` calls it on alert/recovery/escalation.

### 1.3 Fix Outcome Tracking

**Goal:** After the watchdog runs `--apply`, record whether the fix worked (health recovered on next check) or not.

**Changes to `systemd/watchdogs/health-watchdog`:**

1. After the fix pipeline runs and the re-check completes (line ~34-47), log a fix outcome to `incidents.jsonl`:
   ```bash
   # Log fix outcome
   echo "$REPORT" | $UV run python -c "
   import sys, json
   from shared.alert_state import log_fix_outcome
   pre = json.load(sys.stdin)
   log_fix_outcome(pre, post_status='$STATUS2', git_head=pre.get('git_head'))
   " 2>/dev/null || true
   ```

2. **New function in `shared/alert_state.py`:**
   ```python
   def log_fix_outcome(
       pre_report: dict,
       post_status: str,
       git_head: str | None = None,
   ) -> None:
       """Log the outcome of a fix attempt."""
       pre_failed = [
           c["name"] for g in pre_report.get("groups", [])
           for c in g.get("checks", []) if c["status"] != "healthy"
       ]
       entry = {
           "timestamp": time.time(),
           "action_type": "fix_outcome",
           "pre_status": pre_report.get("overall_status"),
           "post_status": post_status,
           "fixed": post_status == "healthy",
           "checks_attempted": pre_failed,
           "git_head": git_head,
       }
       _log_incident_raw(entry)
   ```

### 1.4 DriftItem Extension with fix_type Field

**Goal:** Classify each drift item so the pipeline knows whether it can auto-fix, needs review, or is hands-off.

**Changes to `agents/drift_detector.py`:**

1. **Extend `DriftItem`** (currently at line ~54):
   ```python
   class DriftItem(BaseModel):
       severity: str = Field(description="high, medium, or low")
       category: str = Field(description="Category: ...")
       doc_file: str = Field(description="Which documentation file contains the drift")
       doc_claim: str = Field(description="What the documentation says")
       reality: str = Field(description="What the actual system state is")
       suggestion: str = Field(description="Suggested fix")
       # NEW FIELDS:
       fix_type: str = Field(
           default="doc",
           description="Fix target: doc (documentation change), code (application code), config (config file), infra (infrastructure/compose/systemd)"
       )
       source_files: list[str] = Field(
           default_factory=list,
           description="Relevant source file paths for code/config fixes"
       )
   ```

2. **Update LLM system prompt** (line ~130) to instruct the drift agent to populate `fix_type` and `source_files`.

3. **Update `--fix` logic** to use `fix_type` for routing (doc fixes auto-apply, others log for Phase 4).

**Test:** Update `test_drift_detector.py` to verify new fields are populated and serialized correctly.

---

## Phase 2: Auto-Remediation for Known Fixes (Weeks 3-4)

### 2.1 Timer-Based Auto-Fix Architecture

**Decision: systemd timer (existing `health-monitor.timer`).**

The existing infrastructure already runs health checks every 15 minutes via `health-monitor.timer` -> `health-monitor.service` -> `health-watchdog`. The watchdog already runs `--apply` on failures. Phase 2 extends this, not replaces it.

**No new timers needed.** Changes are to the watchdog and the fix pipeline:

1. **Watchdog enhancement** — after a fix attempt, if not all checks recover, retry once more after a 60-second delay (within the same watchdog invocation). Max 2 fix cycles per watchdog run.

2. **New auto-remediation systemd timer** (for faster response to regressions):
   - `health-monitor-fast.timer` — runs every 5 minutes, but only triggers if the last run exited non-zero (i.e., there are known failures).
   - Implementation: use `OnUnitActiveSec=5min` with a `ConditionPathExists=/tmp/hapax-health-degraded` flag file. The watchdog creates this file on non-healthy exit, removes it on healthy exit.
   - This avoids running 80+ checks every 5 minutes when everything is fine.

### 2.2 Circuit Breaker Implementation

**New module: `shared/circuit_breaker.py`**

```python
@dataclass
class CircuitState:
    check_name: str
    attempts: int = 0
    last_attempt: float = 0.0
    window_start: float = 0.0

class CircuitBreaker:
    """Track fix attempts per check. Max N attempts per window."""

    def __init__(
        self,
        max_attempts: int = 2,
        window_seconds: int = 86400,  # 24h
        state_path: Path = Path("profiles/circuit-breaker.json"),
    ): ...

    def can_attempt(self, check_name: str) -> bool:
        """Return True if the check has attempts remaining in the current window."""

    def record_attempt(self, check_name: str, success: bool) -> None:
        """Record a fix attempt. Resets on success."""

    def reset(self, check_name: str) -> None:
        """Manually reset a check's circuit breaker (operator override)."""
```

**Integration points:**
- `shared/fix_capabilities/pipeline.py` — check `circuit_breaker.can_attempt()` before executing any fix.
- On circuit break (max attempts exceeded), create a GitHub issue with label `needs-human-fix` and notify via ntfy with `priority=urgent`.

**State persistence:** JSON file at `profiles/circuit-breaker.json`. Same atomic-write pattern as `alert_state.py`.

### 2.3 Modification Classification Matrix Enforcement

**New module: `shared/modification_classifier.py`**

```python
class ModificationClass(StrEnum):
    AUTO_FIX = "auto_fix"
    REVIEW_REQUIRED = "review_required"
    NEVER_MODIFY = "never_modify"

# Mapping from file path patterns to classification
CLASSIFICATION_RULES: list[tuple[str, ModificationClass]] = [
    ("docs/**", ModificationClass.AUTO_FIX),
    ("*.md", ModificationClass.AUTO_FIX),
    ("configs/**", ModificationClass.REVIEW_REQUIRED),
    ("tests/**", ModificationClass.REVIEW_REQUIRED),
    ("agents/**", ModificationClass.REVIEW_REQUIRED),
    ("shared/**", ModificationClass.REVIEW_REQUIRED),
    ("cockpit/**", ModificationClass.REVIEW_REQUIRED),
    # NEVER MODIFY — these are the oversight mechanisms
    ("agents/health_monitor.py", ModificationClass.NEVER_MODIFY),
    ("shared/alert_state.py", ModificationClass.NEVER_MODIFY),
    ("shared/axiom_*.py", ModificationClass.NEVER_MODIFY),
    ("shared/config.py", ModificationClass.NEVER_MODIFY),
    ("systemd/watchdogs/*", ModificationClass.NEVER_MODIFY),
    ("hapax-backup-*.sh", ModificationClass.NEVER_MODIFY),
]

def classify_path(path: str) -> ModificationClass:
    """Return the modification class for a file path (most specific match wins)."""

def classify_diff(diff_text: str) -> ModificationClass:
    """Return the most restrictive class across all files in a diff."""
```

**Enforcement:** Every auto-fix and auto-generated PR checks `classify_diff()` before proceeding. If any file is `NEVER_MODIFY`, the entire operation is blocked and an audit alert is raised.

### 2.4 Audit Logging Format

All automated actions logged to `profiles/audit.jsonl`:

```json
{
    "timestamp": "2026-03-15T10:30:00Z",
    "action": "auto_fix",
    "actor": "health-watchdog",
    "check_name": "docker.qdrant",
    "fix_applied": "docker compose restart qdrant",
    "classification": "auto_fix",
    "circuit_breaker": {"attempts": 1, "remaining": 1},
    "outcome": "success",
    "git_head": "a1b2c3d4e5f6",
    "duration_ms": 2340
}
```

**Implementation:** Add `_log_audit()` to a new `shared/audit.py` module. Called by the fix pipeline after every fix attempt (success or failure). Separate from `incidents.jsonl` — incidents are about what went wrong, audit is about what the system did about it.

---

## Phase 3: Auto-Revert + LLM Hotfix (Weeks 5-8)

### 3.1 Auto-Revert Engine

**New module: `agents/auto_revert.py`**

#### Commit Correlation Algorithm

```python
async def correlate_regression(
    check_name: str,
    failure_time: float,
    git_head: str,
    git_head_age_s: int,
    incident_log_path: Path,
) -> RegressionCorrelation | None:
    """Determine if a health check failure correlates with a recent commit.

    Returns RegressionCorrelation if:
    1. git_head_age_s < 1800 (commit is < 30 minutes old)
    2. The check was healthy in the previous incident log entry
    3. No other checks failed at the same time (rules out infrastructure-wide issues)

    Returns None if correlation is ambiguous or commit is too old.
    """
```

**Data flow:**
1. Health monitor report arrives with `git_head` and `git_head_age_s`.
2. Alert state machine detects a `healthy -> failed` transition.
3. `correlate_regression()` checks the three criteria above.
4. If correlated, proceed to revert workflow.

#### Revert Branch Workflow

```python
async def attempt_revert(correlation: RegressionCorrelation) -> RevertResult:
    """Create a revert branch, run tests, and open a PR if tests pass.

    Steps:
    1. git checkout -b auto-revert/{commit_sha[:8]} main
    2. git revert --no-edit {commit_sha}
    3. Run: uv run pytest tests/ --timeout=300
    4. If tests pass: push branch, create PR
    5. If tests fail: delete branch, escalate to human
    """
```

**PR template:**
```markdown
## [auto-revert] Revert {commit_sha[:8]}: {original_commit_message}

### Regression detected
- **Check:** {check_name}
- **Transition:** healthy -> {status}
- **Time since commit:** {age} minutes
- **Correlation confidence:** {confidence}

### Health check detail
{check.message}
{check.detail}

### Audit trail
- Incident ID: {incident_id}
- Circuit breaker state: {cb_state}
- Correlation algorithm: commit_age < 30min + healthy->failed transition

**This PR was auto-generated. Human review required before merge.**
```

**Circuit breaker:** Max 1 revert attempt per commit hash. Tracked in `circuit-breaker.json` with key `revert:{sha}`.

### 3.2 Hotfix Generator

**New module: `agents/hotfix_generator.py`**

#### Structured Context Format

```python
@dataclass
class HotfixContext:
    check_name: str
    status: str
    message: str
    detail: str | None
    remediation_attempted: str | None
    remediation_outcome: str | None
    recent_diff: str  # git diff HEAD~3..HEAD (last 3 commits)
    stack_trace: str | None
    similar_incidents: list[dict]  # from incident knowledge base
    relevant_source_files: list[str]  # identified by check group -> source mapping
```

#### LLM Prompt Design

```python
HOTFIX_SYSTEM_PROMPT = """\
You are a targeted hotfix generator for the hapax-council system.
You receive structured context about a health check failure and must generate
the minimal code change to fix the root cause.

CONSTRAINTS:
- Diff must be < 50 lines
- Fix must address root cause, not suppress the symptom
- Never modify: health_monitor.py, alert_state.py, axiom_*.py, config.py
- Never add broad exception handlers (except Exception: pass)
- Never remove or weaken existing tests
- Prefer the simplest correct fix

OUTPUT FORMAT:
Return a JSON object with:
  - files: list of {path, old_content, new_content} (unified diff format)
  - explanation: 2-3 sentences explaining the root cause and fix
  - confidence: float 0.0-1.0 (your confidence this is the right fix)
  - risk: "low" | "medium" | "high"
"""
```

#### Test Gate

```python
async def validate_hotfix(branch: str) -> ValidationResult:
    """Run the full validation suite on a hotfix branch.

    1. uv run pytest tests/ --timeout=300
    2. uv run ruff check . (no new lint violations)
    3. uv run pyright --outputjson (no new type errors)
    4. classify_diff() — verify no NEVER_MODIFY files touched
    5. Diff size check: max 50 lines changed
    6. Second LLM review (optional, Haiku): "Does this fix the root cause
       or just suppress the error?"
    """
```

#### PR Creation

```python
async def create_hotfix_pr(
    hotfix: HotfixResult,
    context: HotfixContext,
) -> str:  # returns PR URL
    """Create a PR with full audit trail.

    Branch naming: auto-hotfix/{check_name}-{timestamp}
    Labels: auto-hotfix, needs-review
    """
```

**Circuit breaker:** Max 2 hotfix attempts per check per 24h. After exhaustion, create GitHub issue with label `needs-human-fix`, full context attached.

### 3.3 Integration with Watchdog

Update `systemd/watchdogs/health-watchdog` flow:

```
1. Run health check (--json)
2. If failures exist:
   a. Run fix pipeline (--apply)
   b. Re-check
   c. If still failing AND git_head_age < 30min:
      → attempt_revert()
   d. If still failing AND revert not applicable:
      → generate_hotfix()
3. Log fix outcome
4. Process through alert state machine
```

---

## Phase 4: Drift-to-Refactor PRs (Weeks 5-8, parallel with Phase 3)

### 4.1 DriftItem Extensions Needed

Already covered in Phase 1.4. Additional changes for Phase 4:

1. **Add `auto_fixable` computed property to DriftItem:**
   ```python
   @property
   def auto_fixable(self) -> bool:
       return self.fix_type == "doc" and self.severity in ("medium", "low")
   ```

2. **Add `refactor_candidate` computed property:**
   ```python
   @property
   def refactor_candidate(self) -> bool:
       return (
           self.fix_type == "code"
           and self.severity == "high"
           and len(self.source_files) > 0
       )
   ```

3. **Extend `DriftReport`** with routing summary:
   ```python
   class DriftReport(BaseModel):
       # ... existing ...
       auto_fixable_count: int = 0
       refactor_candidates: int = 0
       review_required_count: int = 0
   ```

### 4.2 LLM Refactoring Agent Design

**New module: `agents/refactor_agent.py`**

```python
REFACTOR_SYSTEM_PROMPT = """\
You are a code refactoring agent for the hapax-council system.
You receive a drift item describing a discrepancy between documentation
and implementation, along with the relevant source files.

Your task: modify the source code to match what the documentation describes
(documentation is the source of truth for intended behavior).

CONSTRAINTS:
- Only modify files listed in source_files
- Never modify oversight files (health_monitor, alert_state, axiom_*, config.py)
- Preserve all existing tests (they must still pass)
- Keep changes minimal and focused on the drift item
- Follow existing code style (ruff-formatted, type-annotated)

OUTPUT: Same format as hotfix generator (file diffs + explanation).
"""

async def generate_refactor(
    drift_item: DriftItem,
    architecture_docs: dict[str, str],
) -> RefactorResult:
    """Generate a refactoring patch for a code-type drift item.

    1. Load source files referenced in drift_item.source_files
    2. Load architecture docs for context
    3. Call LLM with structured prompt
    4. Validate output through test gate
    5. Run axiom compliance check
    """
```

**Model selection:** Use Sonnet (via LiteLLM at localhost:4000) for refactoring. Cheaper than Opus and sufficient for constrained code changes.

### 4.3 Axiom Compliance Integration

Every refactoring PR passes through `shared/axiom_enforcement.py`:

```python
from shared.axiom_enforcement import check_full, ComplianceResult

async def axiom_gate(diff_text: str, description: str) -> ComplianceResult:
    """Check whether a proposed change complies with all axioms.

    Uses check_full (cold path) since this is not latency-sensitive.
    Blocks the PR if any T0 axiom is violated.
    """
    result = check_full(description)
    if not result.compliant:
        # Log violation to audit trail
        # Do NOT proceed with PR
        pass
    return result
```

**Integration with VetoChain** (`shared/capabilities/health_veto.py`):
- The `compliance_veto` function already exists.
- Wrap the refactor pipeline in a VetoChain that includes `compliance_veto` with the loaded axiom rules.
- If vetoed, log the violation and create a GitHub issue instead of a PR.

### 4.4 Drift-to-Refactor Workflow

Update `agents/drift_detector.py` to add a `--refactor` mode:

```
drift_detector --refactor
  1. Run standard drift analysis
  2. Filter for refactor_candidate items
  3. For each candidate:
     a. classify_diff() pre-check on source_files
     b. generate_refactor()
     c. axiom_gate()
     d. validate (pytest, ruff, pyright)
     e. create PR with labels: auto-refactor, drift-fix, needs-review
```

**Trigger:** New systemd timer `drift-refactor.timer` running monthly (or on-demand via `--refactor` flag). Separate from the weekly drift detection run.

---

## Phase 5: Continuous Learning (Weeks 9-12)

### 5.1 Incident Knowledge Base Schema and Storage

**Initial storage: YAML** (migrate to Qdrant if > 500 patterns, per design doc).

**File:** `~/.cache/hapax-council/incident-knowledge.yaml`

```yaml
version: 1
last_updated: "2026-04-01T10:00:00Z"
patterns:
  - id: "qdrant-connection-refused"
    failure_signature:
      check: "connectivity.qdrant"
      status: "failed"
      message_pattern: "connection refused"
    root_causes:
      - description: "Docker container crashed"
        frequency: 12
      - description: "Port conflict with another service"
        frequency: 2
    fixes:
      - action: "docker_restart"
        params: {container: "qdrant"}
        success_rate: 0.92
        last_verified: "2026-03-28"
        times_used: 12
        times_succeeded: 11
      - action: "docker_compose_up"
        params: {service: "qdrant"}
        success_rate: 1.0
        last_verified: "2026-03-15"
        times_used: 3
        times_succeeded: 3
    related_commits: []
    last_occurrence: "2026-03-28T14:30:00Z"
    total_occurrences: 14

  - id: "ollama-model-missing"
    failure_signature:
      check: "ollama.models"
      status: "failed"
      message_pattern: "model .* not found"
    root_causes:
      - description: "Model evicted after Docker restart"
        frequency: 5
    fixes:
      - action: "ollama_pull"
        params: {model: "$MATCH_GROUP_1"}  # extract from message_pattern
        success_rate: 1.0
        times_used: 5
        times_succeeded: 5
    related_commits: []
    last_occurrence: "2026-03-25T09:00:00Z"
    total_occurrences: 5
```

**Pydantic models for the knowledge base:**

```python
# shared/incident_knowledge.py

class FailureSignature(BaseModel):
    check: str
    status: str
    message_pattern: str  # regex pattern

class RootCause(BaseModel):
    description: str
    frequency: int = 0

class FixRecord(BaseModel):
    action: str
    params: dict[str, str] = {}
    success_rate: float = 0.0
    last_verified: str = ""
    times_used: int = 0
    times_succeeded: int = 0

class IncidentPattern(BaseModel):
    id: str
    failure_signature: FailureSignature
    root_causes: list[RootCause] = []
    fixes: list[FixRecord] = []
    related_commits: list[str] = []
    last_occurrence: str = ""
    total_occurrences: int = 0

class IncidentKnowledgeBase(BaseModel):
    version: int = 1
    last_updated: str = ""
    patterns: list[IncidentPattern] = []

    def find_matching(self, check: str, status: str, message: str) -> list[IncidentPattern]:
        """Find patterns whose failure_signature matches the given check failure."""

    def update_from_incident(self, incident: dict) -> None:
        """Update pattern stats from a logged incident."""

    def best_fix(self, pattern_id: str) -> FixRecord | None:
        """Return the fix with highest success_rate for a pattern."""
```

### 5.2 Pattern Extraction Pipeline

**New module: `agents/incident_analyzer.py`**

**Trigger:** Weekly via new systemd timer `incident-analysis.timer` (Sunday 04:00, after drift detection at 03:00).

**Pipeline:**

1. **Extract raw data:** Read `profiles/incidents.jsonl` and `profiles/audit.jsonl` for the past week.

2. **Cluster incidents:** Group by `check_name` + status. Identify recurring patterns (same check failing > 2 times in a week).

3. **LLM analysis** (Haiku, ~$0.05/run):
   ```python
   PATTERN_EXTRACTION_PROMPT = """\
   Analyze these health check incidents from the past week.
   Identify recurring failure patterns and their most effective fixes.

   For each pattern, provide:
   - A short ID (kebab-case)
   - The failure signature (check name, status, message pattern as regex)
   - Likely root causes
   - Which fixes worked and which didn't

   Incidents:
   {incidents_json}

   Existing patterns (update, don't duplicate):
   {existing_patterns_json}
   """
   ```

4. **Merge with existing knowledge base:** Update `success_rate`, `times_used`, add new patterns. Never delete existing patterns (they may be rare but valid).

5. **Validate:** Ensure all `message_pattern` fields are valid regexes. Ensure `success_rate` is computed correctly from `times_used` / `times_succeeded`.

6. **Write updated knowledge base** to YAML.

### 5.3 Chaos Testing Scripts

**Directory:** `scripts/chaos/`

**Principle:** Lightweight chaos only. Stop/start containers, not corrupt data. Never target the host OS.

**Example scripts:**

1. **`chaos-docker-restart.sh`** — Randomly restart one of the CORE_CONTAINERS:
   ```bash
   #!/usr/bin/env bash
   # Pick a random container and restart it. Verify health monitor detects and recovers.
   CONTAINERS=(qdrant ollama postgres litellm)
   TARGET=${CONTAINERS[$RANDOM % ${#CONTAINERS[@]}]}
   echo "Chaos: restarting $TARGET"
   docker stop "$TARGET"
   sleep 30
   # Run health check — should detect failure
   uv run python -m agents.health_monitor --json | jq '.overall_status'
   # Let watchdog auto-fix
   sleep 60
   # Verify recovery
   uv run python -m agents.health_monitor --json | jq '.overall_status'
   ```

2. **`chaos-port-conflict.sh`** — Temporarily bind a port used by a service, verify detection:
   ```bash
   # Bind port 6333 (Qdrant) temporarily
   python3 -c "import socket; s=socket.socket(); s.bind(('',6333)); input('Press enter to release')" &
   PID=$!
   docker restart qdrant  # will fail to bind
   sleep 10
   uv run python -m agents.health_monitor --check docker,qdrant --json
   kill $PID
   ```

3. **`chaos-disk-pressure.sh`** — Create a large temp file to trigger disk warnings:
   ```bash
   # Create 50GB sparse file (doesn't use real space on btrfs)
   fallocate -l 50G /tmp/chaos-disk-test
   uv run python -m agents.health_monitor --check disk --json
   rm /tmp/chaos-disk-test
   ```

4. **`chaos-validate-recovery.py`** — End-to-end chaos test that:
   - Records baseline health
   - Introduces a fault
   - Waits for watchdog cycle (or triggers manually)
   - Verifies recovery
   - Checks incident log for correct entries
   - Checks audit log for correct fix recording

**Schedule:** Manual only (not automated). Run before releasing a new phase to validate the pipeline.

---

## Phase 6: Graduated Autonomy (Weeks 13+)

### 6.1 Auto-Merge Criteria by Category

| Category | Auto-Merge Criteria | Soak Period | Human Override |
|----------|-------------------|-------------|----------------|
| Doc-only fixes | `classify_diff() == AUTO_FIX` AND confidence > 0.9 AND diff < 20 lines | None | Always available via PR comment |
| Config fixes | `classify_diff() == REVIEW_REQUIRED` AND all tests pass AND health check passes | 30 minutes | Must approve within soak period |
| Test additions | Tests pass AND mutation score > 50% AND no existing tests modified | 30 minutes | Must approve within soak period |
| Application code | Never auto-merge | N/A | Always required |
| Reverts | Never auto-merge | N/A | Urgent review requested |

### 6.2 Soak Period Implementation

**New module: `shared/soak.py`**

```python
@dataclass
class SoakEntry:
    pr_number: int
    branch: str
    merged_at: float  # timestamp
    soak_until: float  # timestamp
    category: str
    health_baseline: dict  # health report at merge time
    checks_passed: int = 0  # number of health checks passed during soak
    reverted: bool = False

class SoakManager:
    """Track merged PRs during their soak period.

    State file: profiles/soak-state.json
    """

    def __init__(self, state_path: Path = Path("profiles/soak-state.json")): ...

    def register_merge(self, pr: int, branch: str, category: str, soak_minutes: int = 30) -> None:
        """Register a newly merged PR for soak monitoring."""

    def check_soak(self, current_report: dict) -> list[SoakEntry]:
        """Check all soaking PRs against current health.

        Returns entries that have degraded (need revert).
        """

    def complete_soak(self, pr: int) -> None:
        """Mark a PR as having passed its soak period."""
```

**Integration:** The watchdog checks `soak_manager.check_soak()` on every run. If any soaking PR shows health degradation, it triggers the auto-revert engine for that PR's merge commit.

### 6.3 Revert Rate Tracking

**Key metric:** `revert_rate = reverts_triggered / total_auto_merges` over a rolling 30-day window.

**Implementation:**

1. **Track in `profiles/autonomy-metrics.jsonl`:**
   ```json
   {"timestamp": "...", "event": "auto_merge", "pr": 42, "category": "doc", "confidence": 0.95}
   {"timestamp": "...", "event": "auto_revert", "pr": 42, "cause": "health_degradation", "soak_elapsed_min": 12}
   ```

2. **Thresholds:**
   - If revert_rate > 10%: disable auto-merge for that category, notify operator.
   - If revert_rate > 20%: disable all auto-merge, create GitHub issue `autonomy-regression`.
   - If revert_rate stays < 5% for 30 days: consider expanding auto-merge criteria (operator decision, not automated).

3. **Dashboard:** Expose metrics via the cockpit API (`/api/autonomy-metrics`) for the React SPA. Shows:
   - Rolling 30-day revert rate per category
   - Total auto-merges vs reverts
   - Soak period pass/fail ratio
   - Hotfix acceptance rate

---

## Phase 7: Dependencies on Layers 1 and 2

### Layer 1 (Reactive CI) — Required Before Phase 3

Phase 3 (auto-revert and hotfix) requires:

1. **CI pipeline running on every push/PR** — auto-revert creates branches and PRs. The CI must run `pytest`, `ruff`, `pyright` on those branches to validate them. Without CI, there is no automated test gate.

2. **Branch protection on `main`** — PRs must not be mergeable without passing CI. This is the safety net that prevents auto-generated broken code from landing.

3. **GitHub Actions workflow** — specifically:
   - `pytest` with the full test suite
   - `ruff check` for lint
   - `pyright` for type checking
   - Status checks required for merge

**Minimum Layer 1 deliverables before Phase 3 can start:**
- `.github/workflows/ci.yml` with pytest + ruff + pyright
- Branch protection rule on `main` requiring CI pass
- `gh` CLI authenticated and working (for PR creation)

### Layer 2 (Proactive SDLC) — Required Before Phase 4

Phase 4 (drift-to-refactor) requires:

1. **Coverage reporting** — to prioritize which drift items to fix first (high-coverage areas are safer to refactor).

2. **Mutation testing infrastructure** — Phase 4 generates code changes. Mutation testing validates that existing tests actually catch regressions in the modified code.

3. **Scheduled drift detection** — already exists (`drift-detector.timer`), but Layer 2 adds structured reporting that Phase 4 consumes.

**Minimum Layer 2 deliverables before Phase 4 can start:**
- Coverage reporting integrated into CI
- `mutmut` or `cosmic-ray` configured and runnable
- Drift detector producing structured JSON output (already done)

### Cross-Layer Integration Points

| This Layer (3) Component | Depends On | From Layer |
|--------------------------|-----------|------------|
| Auto-revert PR creation | CI pipeline, branch protection | Layer 1 |
| Hotfix test gate | CI pipeline (pytest + ruff + pyright) | Layer 1 |
| Refactor validation | Mutation testing | Layer 2 |
| Test generation quality gate | Mutation testing | Layer 2 |
| Soak period health comparison | Health history (existing) | Already built |
| Axiom compliance gate | Axiom enforcement (existing) | Already built |
| Circuit breaker | Alert state (existing) | Already built |
| Fix pipeline | Fix capabilities (existing) | Already built |

### Phasing Recommendation

```
Week 1-2:   Phase 1 (Instrument)         — no Layer 1/2 deps
Week 3-4:   Phase 2 (Auto-Remediation)    — no Layer 1/2 deps
Week 3-4:   Layer 1 must be operational   — parallel work
Week 5-8:   Phase 3 (Auto-Revert)         — requires Layer 1
Week 5-8:   Phase 4 (Drift-to-Refactor)   — requires Layer 2
Week 9-12:  Phase 5 (Continuous Learning) — requires Phase 2-3 data
Week 13+:   Phase 6 (Graduated Autonomy)  — requires all previous phases stable
```

---

## File Inventory (New and Modified)

### New Files
| File | Phase | Purpose |
|------|-------|---------|
| `shared/circuit_breaker.py` | 2 | Fix attempt rate limiting |
| `shared/modification_classifier.py` | 2 | File path classification matrix |
| `shared/audit.py` | 2 | Structured audit logging |
| `agents/auto_revert.py` | 3 | Commit correlation + revert workflow |
| `agents/hotfix_generator.py` | 3 | LLM-generated targeted fixes |
| `agents/refactor_agent.py` | 4 | Drift-to-refactor LLM agent |
| `shared/incident_knowledge.py` | 5 | Knowledge base models + queries |
| `agents/incident_analyzer.py` | 5 | Weekly pattern extraction |
| `shared/soak.py` | 6 | Soak period tracking |
| `scripts/chaos/*.sh` | 5 | Chaos testing scripts |
| `systemd/units/incident-analysis.timer` | 5 | Weekly pattern extraction timer |

### Modified Files
| File | Phase | Changes |
|------|-------|---------|
| `agents/health_monitor.py` | 1 | Add `git_head`, `git_head_age_s` to HealthReport |
| `shared/alert_state.py` | 1 | Add incident JSONL logging, `log_fix_outcome()` |
| `agents/drift_detector.py` | 1, 4 | Add `fix_type`, `source_files` to DriftItem; add `--refactor` mode |
| `systemd/watchdogs/health-watchdog` | 1, 3 | Pass git_head, integrate auto-revert/hotfix |
| `shared/fix_capabilities/pipeline.py` | 2 | Integrate circuit breaker |
| `shared/fix_capabilities/__init__.py` | 2 | No changes (capabilities already registered) |

### State Files (Runtime, Not Committed)
| File | Phase | Purpose |
|------|-------|---------|
| `profiles/incidents.jsonl` | 1 | Incident log |
| `profiles/audit.jsonl` | 2 | Audit trail |
| `profiles/circuit-breaker.json` | 2 | Circuit breaker state |
| `profiles/soak-state.json` | 6 | Soak period tracking |
| `profiles/autonomy-metrics.jsonl` | 6 | Auto-merge/revert metrics |
| `~/.cache/hapax-council/incident-knowledge.yaml` | 5 | Knowledge base |

### Test Files
| File | Phase | Tests |
|------|-------|-------|
| `tests/test_circuit_breaker.py` | 2 | Window expiry, max attempts, reset |
| `tests/test_modification_classifier.py` | 2 | Path classification, NEVER_MODIFY enforcement |
| `tests/test_auto_revert.py` | 3 | Commit correlation, revert workflow (mocked git) |
| `tests/test_hotfix_generator.py` | 3 | Context assembly, diff size limit, test gate |
| `tests/test_incident_knowledge.py` | 5 | Pattern matching, success rate computation |
| `tests/test_soak.py` | 6 | Soak registration, degradation detection |
