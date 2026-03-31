# Audit & Smoketest: LLM-Optimized Codebase Restructuring

**Purpose:** Verify functional parity after the LLM-optimized codebase restructuring (PRs #454-#458). Every import path, CLI entry point, systemd service, API route, reactive engine rule, and timer agent must work exactly as before.

**Prior work:** 4 decomposed packages, 106 vendored shim modules, split files in daimonion/logos/visual_layer_aggregator, 287→81 Any type narrowing, 90 METADATA.yaml files.

**Approach:** Bottom-up. Start with import smoke tests (cheapest), then unit tests, then integration tests, then live service verification.

---

## Layer 1: Import Smoke Tests

Every re-exported symbol must be importable from its original path. If any of these fail, backward compatibility is broken.

### 1.1 Decomposed packages — backward compat imports

Each decomposed package has an `__init__.py` that re-exports symbols. Verify every symbol that external code relied on.

```bash
# drift_detector
uv run python -c "
from agents.drift_detector import DriftItem, DriftReport, DriftReport
from agents.drift_detector import scan_axiom_violations, scan_sufficiency_gaps
from agents.drift_detector import load_docs, DOC_FILES
from agents.drift_detector import drift_agent
print('drift_detector: OK')
"

# health_monitor
uv run python -c "
from agents.health_monitor import run_cmd, http_get
from agents.health_monitor import CheckResult, Status, CHECK_REGISTRY
from agents.health_monitor import run_checks, format_results, run_fixes
print('health_monitor: OK')
"

# studio_compositor
uv run python -c "
from agents.studio_compositor import StudioCompositor
from agents.studio_compositor import load_config, compute_tile_layout
print('studio_compositor: OK')
"

# visual_layer_aggregator
uv run python -c "
from agents.visual_layer_aggregator import VisualLayerAggregator
print('visual_layer_aggregator: OK')
"
```

**If any fail:** The `__init__.py` re-exports are incomplete. Add the missing symbol to the package's `__init__.py`.

### 1.2 Vendored shim modules — import chain

Every vendored shim must be importable. These replaced `from shared.X import Y` with `from agents._X import Y`.

```bash
# Batch test all 66 agents/_*.py shims
uv run python -c "
import importlib, pathlib, sys
shims = sorted(p.stem for p in pathlib.Path('agents').glob('_*.py') if p.stem != '__init__')
failed = []
for name in shims:
    try:
        importlib.import_module(f'agents.{name}')
    except Exception as e:
        failed.append((name, str(e)[:80]))
print(f'agents/_*.py: {len(shims) - len(failed)}/{len(shims)} OK')
for name, err in failed:
    print(f'  FAIL: agents.{name}: {err}')
"

# Batch test all 40 logos/_*.py shims
uv run python -c "
import importlib, pathlib
shims = sorted(p.stem for p in pathlib.Path('logos').glob('_*.py') if p.stem != '__init__')
failed = []
for name in shims:
    try:
        importlib.import_module(f'logos.{name}')
    except Exception as e:
        failed.append((name, str(e)[:80]))
print(f'logos/_*.py: {len(shims) - len(failed)}/{len(shims)} OK')
for name, err in failed:
    print(f'  FAIL: logos.{name}: {err}')
"
```

**If any fail:** The shim has a broken import chain. Read the shim file, find the `from shared.*` import that fails, and either inline the needed code or wrap in try/except.

### 1.3 Cross-module imports — consumers of decomposed packages

Other agents import from the decomposed packages. Verify every known cross-import.

```bash
uv run python -c "
# health_monitor consumers
from agents.health_monitor import run_cmd, http_get  # used by introspect
from agents.health_monitor import CHECK_REGISTRY  # used by tools, probes
from agents.health_monitor import run_checks, run_fixes  # used by demo_pipeline

# drift_detector consumers (mostly internal)
from agents.drift_detector.models import DriftItem, DriftReport
from agents.drift_detector.models import InfrastructureManifest

print('cross-module imports: OK')
"
```

### 1.4 Split file imports — daimonion, logos, visual_layer_aggregator

Files that were split into siblings (not converted to packages) must still export their symbols from the original module path.

```bash
uv run python -c "
# daimonion daemon (was __main__.py, now split across 17 files)
from agents.hapax_daimonion.__main__ import VoiceDaemon
from agents.hapax_daimonion.daemon import VoiceDaemon

# reactive rules (was 1 file, now 4)
from logos.engine.reactive_rules import register_rules

# chat_agent (split to chat_helpers.py)
from logos.chat_agent import ChatAgent

print('split file imports: OK')
"
```

---

## Layer 2: Unit Test Suite

Run the full test suite. Compare pass/fail counts against the pre-restructure baseline.

### 2.1 Core test suite (restructured modules)

```bash
# Decomposed packages
uv run pytest tests/test_drift_detector.py tests/test_drift_detector_memory.py -v
uv run pytest tests/test_health_monitor.py tests/test_health_monitor_pipeline.py -v
uv run pytest tests/test_studio_compositor.py tests/test_scratch_pipeline.py -v

# Daimonion (largest test surface)
uv run pytest tests/hapax_daimonion/ \
    --ignore=tests/hapax_daimonion/test_tracing.py \
    --ignore=tests/hapax_daimonion/test_tracing_flush_timeout.py \
    --ignore=tests/hapax_daimonion/test_tracing_robustness.py \
    -q

# Logos engine + API
uv run pytest tests/test_reactive_engine.py tests/test_reactive_rules.py -v 2>&1 || true
uv run pytest tests/logos/ -v 2>&1 || true
```

**Expected:**
- drift_detector: 44 pass
- health_monitor: 66+ pass (was 125 before split, some in separate files)
- studio_compositor: 45 pass
- daimonion: 1817+ pass

### 2.2 Full test suite

```bash
uv run pytest tests/ -q \
    --ignore=tests/hapax_daimonion/test_tracing.py \
    --ignore=tests/hapax_daimonion/test_tracing_flush_timeout.py \
    --ignore=tests/hapax_daimonion/test_tracing_robustness.py \
    --timeout=60 2>&1 | tail -10
```

**Document:** Total passed, failed, errors, skipped. Compare against pre-restructure numbers. Any NEW failures are regressions from the restructuring.

### 2.3 Test mock target audit

The restructuring changed import paths, which means `unittest.mock.patch()` targets changed. If a test patches `agents.drift_detector.get_model` but the function now lives at `agents.drift_detector.agent.get_model`, the mock silently does nothing — the test passes but doesn't actually test what it claims.

```bash
# Find all patch() calls and verify their targets exist
uv run python -c "
import ast, pathlib

patches = []
for f in sorted(pathlib.Path('tests').rglob('*.py')):
    try:
        tree = ast.parse(f.read_text())
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # Match patch('some.module.path') or @patch('some.module.path')
            if isinstance(func, ast.Attribute) and func.attr == 'patch':
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        patches.append((str(f), arg.value, arg.lineno))

# Verify each target is importable
import importlib
failed = []
for filepath, target, line in patches:
    parts = target.rsplit('.', 1)
    if len(parts) != 2:
        continue
    module_path, attr_name = parts
    try:
        mod = importlib.import_module(module_path)
        if not hasattr(mod, attr_name):
            failed.append((filepath, line, target, 'attribute not found'))
    except ImportError as e:
        failed.append((filepath, line, target, f'import failed: {e}'))

print(f'Patch targets: {len(patches)} total, {len(patches) - len(failed)} valid, {len(failed)} broken')
for filepath, line, target, reason in failed[:20]:
    print(f'  {filepath}:{line} — {target} — {reason}')
"
```

**If any fail:** The mock target is stale. Update the patch target to the new module path where the function actually lives after decomposition.

---

## Layer 3: CLI Entry Points

Every `python -m agents.X` must work. These are the entry points for systemd services and manual invocation.

### 3.1 Module entry points

```bash
# Each should print help or run briefly without error
for mod in \
    agents.drift_detector \
    agents.health_monitor \
    agents.studio_compositor \
    agents.hapax_daimonion \
    agents.fortress \
    agents.visual_layer_aggregator \
    agents.session_conductor \
    agents.studio_fx \
    agents.dmn \
    agents.dev_story \
; do
    echo -n "$mod: "
    uv run python -m $mod --help >/dev/null 2>&1 && echo "OK" || echo "FAIL (may not support --help)"
done
```

### 3.2 Agent direct invocation

```bash
# health_monitor — should produce JSON output
uv run python -m agents.health_monitor --json 2>&1 | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'health_monitor: {len(d)} results')" 2>&1 || echo "health_monitor: FAIL"

# drift_detector — should at least parse without error (may fail on LLM call)
uv run python -m agents.drift_detector --json 2>&1 | head -3

# introspect — should produce manifest
uv run python -m agents.introspect --json 2>&1 | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'introspect: {d.get(\"hostname\", \"?\")} — {len(d.get(\"containers\",[]))} containers')" 2>&1 || echo "introspect: FAIL"
```

---

## Layer 4: Logos API

The FastAPI server imports from many restructured modules.

### 4.1 API startup

```bash
# Start the API and verify it responds
timeout 10 uv run logos-api &
API_PID=$!
sleep 3
curl -s http://localhost:8051/api/health | python3 -c "import json,sys; print(json.load(sys.stdin))" 2>&1 || echo "API health: FAIL"
kill $API_PID 2>/dev/null
```

### 4.2 API route imports

```bash
# Verify every route module imports cleanly
uv run python -c "
import importlib
routes = [
    'logos.api.routes.accommodations', 'logos.api.routes.agents',
    'logos.api.routes.chat', 'logos.api.routes.consent',
    'logos.api.routes.copilot', 'logos.api.routes.data',
    'logos.api.routes.demos', 'logos.api.routes.engine',
    'logos.api.routes.flow', 'logos.api.routes.fortress',
    'logos.api.routes.governance', 'logos.api.routes.logos',
    'logos.api.routes.nudges', 'logos.api.routes.pi',
    'logos.api.routes.profile', 'logos.api.routes.query',
    'logos.api.routes.scout', 'logos.api.routes.sprint',
    'logos.api.routes.stimmung', 'logos.api.routes.studio',
    'logos.api.routes.studio_effects', 'logos.api.routes.working_mode',
]
failed = []
for r in routes:
    try:
        importlib.import_module(r)
    except Exception as e:
        failed.append((r, str(e)[:80]))
print(f'API routes: {len(routes) - len(failed)}/{len(routes)} OK')
for r, e in failed:
    print(f'  FAIL: {r}: {e}')
"
```

### 4.3 Reactive engine rules

```bash
uv run python -c "
from logos.engine.reactive_rules import register_rules
class FakeRegistry:
    rules = []
    def register(self, rule): self.rules.append(rule)
r = FakeRegistry()
register_rules(r)
print(f'Reactive engine: {len(r.rules)} rules registered')
"
```

---

## Layer 5: Live Service Verification

Verify systemd services can start with the restructured code. This layer requires running services.

### 5.1 Service startup

```bash
# Restart each service that uses restructured code and check status
for svc in logos-api hapax-daimonion studio-compositor visual-layer-aggregator; do
    echo -n "$svc: "
    systemctl --user restart $svc 2>&1
    sleep 2
    systemctl --user is-active $svc 2>&1
done
```

### 5.2 Health monitor timer

```bash
# Trigger health monitor and verify output
systemctl --user start health-monitor.service
sleep 5
journalctl --user -u health-monitor.service --since "1 min ago" --no-pager | tail -5
```

### 5.3 Timer agents (sampling)

Test a sample of timer agents that use restructured code:

```bash
for timer in drift-detector daily-briefing profile-update scout; do
    echo -n "$timer: "
    systemctl --user start ${timer}.service 2>&1
    sleep 3
    systemctl --user is-active ${timer}.service 2>&1 || \
    journalctl --user -u ${timer}.service --since "1 min ago" -n 1 --no-pager 2>&1
done
```

---

## Layer 6: Vendored Module Fidelity

Verify vendored shims produce identical behavior to the original shared/ modules.

### 6.1 Config parity

```bash
uv run python -c "
from agents._config import get_model, PROFILES_DIR, HAPAX_HOME
from shared.config import get_model as orig_get_model, PROFILES_DIR as orig_PROFILES_DIR, HAPAX_HOME as orig_HAPAX_HOME

assert str(PROFILES_DIR) == str(orig_PROFILES_DIR), f'PROFILES_DIR mismatch: {PROFILES_DIR} vs {orig_PROFILES_DIR}'
assert str(HAPAX_HOME) == str(orig_HAPAX_HOME), f'HAPAX_HOME mismatch: {HAPAX_HOME} vs {orig_HAPAX_HOME}'

# get_model should return same type with same model ID
m1 = get_model('fast')
m2 = orig_get_model('fast')
assert type(m1).__name__ == type(m2).__name__, f'get_model type mismatch: {type(m1)} vs {type(m2)}'
print('config parity: OK')
"
```

### 6.2 Operator parity

```bash
uv run python -c "
from agents._operator import get_system_prompt_fragment
from shared.operator import get_system_prompt_fragment as orig

# Compare output for a known agent
v1 = get_system_prompt_fragment('drift-detector')
v2 = orig('drift-detector')
assert v1 == v2, f'system prompt mismatch for drift-detector'
print('operator parity: OK')
"
```

### 6.3 Governance parity

```bash
uv run python -c "
from agents._governance import ConsentLabel, ConsentContract, ConsentRegistry
from shared.governance.consent_label import ConsentLabel as OrigLabel
from shared.governance.consent import ConsentRegistry as OrigRegistry

# Verify enum values match
assert set(dir(ConsentLabel)) == set(dir(OrigLabel)), 'ConsentLabel API mismatch'
print('governance parity: OK')
"
```

### 6.4 Notify parity

```bash
uv run python -c "
from agents._notify import send_notification
from shared.notify import send_notification as orig
import inspect

# Compare function signatures
sig1 = inspect.signature(send_notification)
sig2 = inspect.signature(orig)
assert str(sig1) == str(sig2), f'send_notification signature mismatch: {sig1} vs {sig2}'
print('notify parity: OK')
"
```

---

## Layer 7: METADATA.yaml Validation

### 7.1 Schema validation

```bash
uv run python scripts/llm_validate.py
```

**Expected:** All 90 METADATA.yaml files valid. 19 self-contained, 66 with internal deps (vendored shims).

### 7.2 Token baseline comparison

```bash
uv run python scripts/llm_import_graph.py --baseline
uv run python scripts/llm_validate.py --compare-baseline
```

### 7.3 MANIFEST.json integrity

```bash
uv run python -c "
import json, yaml
from pathlib import Path

manifest = json.loads(Path('MANIFEST.json').read_text())
metadata_files = sorted(Path('.').rglob('METADATA.yaml'))
metadata_files = [p for p in metadata_files if 'node_modules' not in str(p)]

manifest_packages = set(manifest['packages'].keys())
actual_packages = set(str(p.parent) for p in metadata_files)

missing_from_manifest = actual_packages - manifest_packages
extra_in_manifest = manifest_packages - actual_packages

print(f'MANIFEST.json: {len(manifest_packages)} packages')
print(f'METADATA.yaml files: {len(actual_packages)}')
if missing_from_manifest:
    print(f'MISSING from MANIFEST: {missing_from_manifest}')
if extra_in_manifest:
    print(f'EXTRA in MANIFEST (stale): {extra_in_manifest}')
if not missing_from_manifest and not extra_in_manifest:
    print('MANIFEST.json is in sync with METADATA.yaml files')
"
```

---

## Layer 8: Ruff + Type Checking

### 8.1 Ruff lint

```bash
uv run ruff check agents/ logos/ scripts/
```

### 8.2 Ruff format

```bash
uv run ruff format --check agents/ logos/ scripts/
```

### 8.3 Any type audit

```bash
# Count and list remaining Any types
grep -rn ": Any\|-> Any\|\[Any\]" agents/ logos/ --include="*.py" | grep -v __pycache__ | grep -v "shared/" | wc -l
echo "Any types (target: 81, should not have increased)"
```

---

## Checklist Summary

| Layer | Check | Pass Criteria |
|-------|-------|---------------|
| 1.1 | Decomposed package imports | All 4 packages importable from original paths |
| 1.2 | Vendored shim imports | All 106 shims importable |
| 1.3 | Cross-module imports | All known cross-imports work |
| 1.4 | Split file imports | Daimonion, logos, VLA split files importable |
| 2.1 | Core tests | drift_detector 44, health_monitor 66+, studio_compositor 45, daimonion 1817+ |
| 2.2 | Full test suite | No NEW failures vs pre-restructure baseline |
| 2.3 | Mock target audit | All patch() targets resolve to real attributes |
| 3.1 | CLI --help | All 10 module entry points respond |
| 3.2 | CLI invocation | health_monitor, drift_detector, introspect produce output |
| 4.1 | API startup | logos-api starts and responds on :8051 |
| 4.2 | API route imports | All 22 route modules import cleanly |
| 4.3 | Reactive engine | register_rules() registers 14 rules |
| 5.1 | Service startup | logos-api, daimonion, studio-compositor, VLA start |
| 5.2 | Health monitor timer | Produces structured results |
| 5.3 | Timer agents | Sample of 4 timers execute |
| 6.1 | Config parity | Vendored vs shared produce identical values |
| 6.2 | Operator parity | System prompt fragments match |
| 6.3 | Governance parity | ConsentLabel API surface matches |
| 6.4 | Notify parity | Function signatures match |
| 7.1 | Schema validation | 90/90 METADATA.yaml valid |
| 7.2 | Token baseline | Regenerated and compared |
| 7.3 | MANIFEST integrity | In sync with METADATA.yaml files |
| 8.1 | Ruff lint | Zero errors in agents/ logos/ scripts/ |
| 8.2 | Ruff format | Zero format violations |
| 8.3 | Any audit | Count = 81 (not increased) |

---

## Regression Triage

If a failure is found:

1. **Import error in a shim** → The shim references a shared/ symbol that moved or was renamed. Fix: update the import in the shim file.
2. **Import error in a decomposed package** → Missing re-export in `__init__.py`. Fix: add the symbol to the package's `__init__.py`.
3. **Test failure with correct assertion but wrong mock** → The patch target is stale. The mock patches the old path but the function now lives at a new path. Fix: update the `patch()` target string.
4. **Test failure with wrong assertion** → Actual behavioral regression from the restructuring. Investigate which split introduced the bug.
5. **Service won't start** → Import chain broken at startup. Run `uv run python -m agents.<name>` to see the traceback, fix the import.
6. **Vendored parity mismatch** → The vendored copy diverged from shared/ during the restructuring. Compare the two files, reconcile.
