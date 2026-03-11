# Health Monitor Fix System Redesign

## Problem

The health monitor's fix system is a bolted-on afterthought. Remediations are hardcoded bash strings in a `CheckResult.remediation` field, executed blindly via `bash -c` with a 30-second timeout. Problems:

- No system awareness — the GPU VRAM fix is a template placeholder that doesn't know which models are loaded.
- No post-fix verification at the Python level (watchdog does bash-level re-check).
- No safety gates — destructive commands run without review.
- No structured actions — just opaque strings.
- The watchdog bash script reimplements retry logic that belongs in Python.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| LLM evaluator frequency | Every 15-min cycle | Autonomous fix proposals without operator intervention |
| Action system | Capability-based modules | Extensible, independently testable, clean domain separation |
| Destructive handling | Notify via ntfy, drop proposal | Re-proposed next cycle if problem persists; no pending queue complexity |
| System context for LLM | Check result + targeted live probe | Each capability defines a `gather_context()` that gathers exactly what the LLM needs |
| Type system | Full Pydantic throughout | Consistent with codebase conventions; typed actions, probes, proposals |

## Architecture

Health checks remain 100% deterministic. When checks fail, a new pipeline runs:

```
CheckResult (unhealthy)
  → Capability registry matches check by group/name
  → capability.gather_context() runs live probe (e.g., ollama ps, docker ps)
  → LLM evaluator sees CheckResult + ProbeResult + available Actions
  → Returns FixProposal (action_type, params, rationale, safety)
  → capability.validate() confirms action is in allowed set
  → If safe: auto-execute via capability.execute(), re-check
  → If destructive: ntfy notification, drop proposal
```

The existing `CheckResult.remediation` field stays as a hint the LLM can consider.

## Capability Modules

```
shared/fix_capabilities/
  __init__.py          # Registry: discover + load capabilities, map check groups
  base.py              # Base classes: Capability, Action, ProbeResult, FixProposal, Safety
  evaluator.py         # Pydantic-ai agent (balanced/sonnet via LiteLLM)
  docker_cap.py        # Container restart, prune, stop
  systemd_cap.py       # Reload, restart units, reset-failed
  ollama_cap.py        # Stop model, pull model, list loaded
  filesystem_cap.py    # Clear cache dirs, prune logs, fix permissions
```

Each capability defines:

- **Actions:** Pydantic models with typed parameters and safety classification (SAFE/DESTRUCTIVE)
- **ProbeResult:** Typed model for live system state gathered when a check fails
- **gather_context():** Runs targeted commands, returns ProbeResult
- **validate():** Confirms a FixProposal uses a valid action with valid params
- **execute():** Runs the action, returns ExecutionResult with success/failure

The `__init__.py` registry maps health check groups to capabilities. Multiple checks can share a capability (e.g., all Docker-related checks route to `docker_cap`).

## LLM Evaluator

A pydantic-ai agent using the `balanced` model (claude-sonnet via LiteLLM).

**Input:** Structured prompt with CheckResult, ProbeResult, available Action schemas, and remediation hint.

**Output type:**

```python
class FixProposal(BaseModel):
    capability: str           # e.g., "ollama"
    action_type: str          # e.g., "StopModel"
    params: dict[str, Any]    # e.g., {"model_name": "deepseek-r1:14b"}
    rationale: str            # why this fix
    safety: Safety            # LLM's assessment, validated against Action's classification
```

**Batching:** One LLM call per failing check. Keeps context small and proposals focused.

**Cost:** Worst case 41 calls/cycle. Realistic: 0-3 failures/cycle, negligible at sonnet pricing.

## Execution Modes

**`--fix` (interactive):** Probe → evaluate → display proposal → prompt accept/reject → execute → re-check → report.

**`--fix --apply` (autonomous, watchdog timer):** Safe actions auto-execute. Destructive actions trigger ntfy with proposal details, then drop. Post-fix re-check automatic. Failures included in notification.

**`--fix --dry-run`:** Full pipeline including LLM evaluation, no execution. Shows what would happen.

## Watchdog Simplification

`health-watchdog` bash script drops 3-attempt backoff logic and `fix-attempts.json` tracking. Becomes a thin wrapper: `uv run python -m agents.health_monitor --fix --apply`. Python pipeline handles retries — if a check still fails, next 15-minute cycle re-evaluates with fresh context. LLM may propose a different action.

## Testing

All LLM calls mocked. Each layer tested independently:

- **Capability tests:** `gather_context()`, `validate()`, `execute()` per capability with mocked subprocess
- **Evaluator tests:** Valid proposals execute, destructive proposals notify, invalid proposals rejected, malformed output handled, probe failures skip gracefully
- **Pipeline integration tests:** End-to-end flow, mode behavior (apply/dry-run), capability routing, multiple failures processed independently
