"""Spec audit — verify operational invariants of the Hapax circulatory systems.

Checks structural specs (code patterns that must exist) and runtime specs
(live system state that must be valid). Returns a conformity report.

Usage:
    from shared.spec_audit import audit_structural, audit_runtime, SpecReport

    # Structural audit (no running system needed)
    report = audit_structural()

    # Runtime audit (checks live state files)
    report = audit_runtime()
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SpecResult:
    """Result of checking a single spec."""

    spec_id: str
    system: str
    tier: str
    passed: bool
    details: str = ""


@dataclass
class SpecReport:
    """Complete audit report."""

    results: list[SpecResult] = field(default_factory=list)
    timestamp: float = 0.0

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def vital_failures(self) -> list[SpecResult]:
        return [r for r in self.results if not r.passed and r.tier == "V0"]

    @property
    def essential_failures(self) -> list[SpecResult]:
        return [r for r in self.results if not r.passed and r.tier == "V1"]

    def summary(self) -> str:
        lines = [f"Spec Audit: {self.passed}/{len(self.results)} passed"]
        if self.vital_failures:
            lines.append(f"  VITAL FAILURES ({len(self.vital_failures)}):")
            for r in self.vital_failures:
                lines.append(f"    [{r.spec_id}] {r.details}")
        if self.essential_failures:
            lines.append(f"  ESSENTIAL FAILURES ({len(self.essential_failures)}):")
            for r in self.essential_failures:
                lines.append(f"    [{r.spec_id}] {r.details}")
        quality = [r for r in self.results if not r.passed and r.tier == "V2"]
        if quality:
            lines.append(f"  QUALITY ISSUES ({len(quality)}):")
            for r in quality:
                lines.append(f"    [{r.spec_id}] {r.details}")
        return "\n".join(lines)


# ── Structural Checks ────────────────────────────────────────────────────────


def _check_file_contains(path: Path, patterns: list[str]) -> tuple[bool, str]:
    """Check that a file contains all required patterns."""
    if not path.exists():
        return False, f"file not found: {path}"
    text = path.read_text()
    missing = [p for p in patterns if p not in text]
    if missing:
        return False, f"missing patterns: {missing}"
    return True, "all patterns found"


def audit_structural(project_root: Path | None = None) -> SpecReport:
    """Run structural spec checks (static analysis, no running system needed)."""
    root = project_root or Path(__file__).parent.parent
    report = SpecReport(timestamp=time.time())

    # st-consumer-coverage-001: all agents use get_system_prompt_fragment
    agents_dir = root / "agents"
    if agents_dir.exists():
        agent_files = list(agents_dir.glob("*.py"))
        # Check which agent files create pydantic-ai Agent() objects
        agents_with_agent = []
        agents_with_fragment = []
        for f in agent_files:
            text = f.read_text()
            if "Agent(" in text and "system_prompt=" in text:
                agents_with_agent.append(f.name)
                if "get_system_prompt_fragment" in text:
                    agents_with_fragment.append(f.name)
        missing = set(agents_with_agent) - set(agents_with_fragment)
        report.results.append(
            SpecResult(
                spec_id="st-consumer-coverage-001",
                system="stimmung",
                tier="V1",
                passed=len(missing) == 0,
                details=f"{len(agents_with_fragment)}/{len(agents_with_agent)} agents use fragment"
                + (f" (missing: {missing})" if missing else ""),
            )
        )

    # st-modulation-001: stimmung modulates engine, visual, scheduler, correction
    agg_path = root / "agents" / "visual_layer_aggregator.py"
    state_path = root / "agents" / "visual_layer_state.py"
    ok1, _ = _check_file_contains(agg_path, ["stimmung_stance", "stimmung_collector"])
    ok2, _ = _check_file_contains(state_path, ["stimmung_stance"])
    ok = ok1 and ok2
    detail = (
        "aggregator + state machine both use stimmung_stance"
        if ok
        else "stimmung modulation incomplete"
    )
    report.results.append(
        SpecResult(
            spec_id="st-modulation-001",
            system="stimmung",
            tier="V1",
            passed=ok,
            details=detail,
        )
    )

    engine_path = root / "logos" / "engine" / "__init__.py"
    ok, detail = _check_file_contains(
        engine_path,
        [
            "Stance.DEGRADED",
            "Stance.CRITICAL",
            "a.phase == 0",
        ],
    )
    report.results.append(
        SpecResult(
            spec_id="st-modulation-001-engine",
            system="stimmung",
            tier="V1",
            passed=ok,
            details=f"engine phase gating: {detail}",
        )
    )

    # tp-protention-observation-001: protention.observe in poll_perception
    ok, detail = _check_file_contains(
        agg_path,
        [
            "_protention.observe(",
            "poll_perception",
        ],
    )
    report.results.append(
        SpecResult(
            spec_id="tp-protention-observation-001",
            system="temporal",
            tier="V1",
            passed=ok,
            details=detail,
        )
    )

    # tp-predictive-cache-001: cache match before, precompute after
    ok, detail = _check_file_contains(
        agg_path,
        [
            "_predictive_cache.match(",
            "_predictive_cache.precompute(",
        ],
    )
    report.results.append(
        SpecResult(
            spec_id="tp-predictive-cache-001",
            system="temporal",
            tier="V2",
            passed=ok,
            details=detail,
        )
    )

    # ex-episode-boundary-001: episode builder wired
    ok, detail = _check_file_contains(
        agg_path,
        [
            "_episode_builder.observe(",
            "_tick_experiential",
        ],
    )
    report.results.append(
        SpecResult(
            spec_id="ex-episode-boundary-001",
            system="experiential",
            tier="V1",
            passed=ok,
            details=detail,
        )
    )

    # ex-episode-flush-001: flush on close
    ok, detail = _check_file_contains(
        agg_path,
        [
            "_episode_builder.flush()",
        ],
    )
    report.results.append(
        SpecResult(
            spec_id="ex-episode-flush-001",
            system="experiential",
            tier="V2",
            passed=ok,
            details=detail,
        )
    )

    # ex-consolidation-trigger-001: reactive rule exists
    rules_path = root / "logos" / "engine" / "reactive_rules.py"
    ok, detail = _check_file_contains(
        rules_path,
        [
            "pattern-consolidation",
            "PATTERN_CONSOLIDATION_RULE",
            "cooldown_s=86400",
        ],
    )
    report.results.append(
        SpecResult(
            spec_id="ex-consolidation-trigger-001",
            system="experiential",
            tier="V2",
            passed=ok,
            details=detail,
        )
    )

    # tl-graceful-absence-001: telemetry never crashes
    tl_path = root / "shared" / "telemetry.py"
    ok, detail = _check_file_contains(
        tl_path,
        [
            "if client is None",
            "yield None",
            "except Exception",
        ],
    )
    report.results.append(
        SpecResult(
            spec_id="tl-graceful-absence-001",
            system="telemetry",
            tier="V0",
            passed=ok,
            details=detail,
        )
    )

    # emb-dimension-001: all stores use 768-dim
    dim_files = [
        root / "shared" / "correction_memory.py",
        root / "shared" / "episodic_memory.py",
        root / "shared" / "pattern_consolidation.py",
        root / "shared" / "profile_store.py",
        root / "shared" / "axiom_precedents.py",
    ]
    dim_ok = True
    dim_missing = []
    for f in dim_files:
        if f.exists():
            ok, _ = _check_file_contains(f, ["VECTOR_DIM = 768"])
            if not ok:
                # Also check for 768 as inline
                ok2, _ = _check_file_contains(f, ["768"])
                if not ok2:
                    dim_ok = False
                    dim_missing.append(f.name)
    report.results.append(
        SpecResult(
            spec_id="emb-dimension-001",
            system="embedding",
            tier="V0",
            passed=dim_ok,
            details="all stores use 768-dim" if dim_ok else f"missing 768-dim: {dim_missing}",
        )
    )

    # df-frontmatter-001: canonical parser used
    ok, detail = _check_file_contains(
        root / "shared" / "frontmatter.py",
        ["def parse_frontmatter"],
    )
    report.results.append(
        SpecResult(
            spec_id="df-frontmatter-001",
            system="data_formats",
            tier="V1",
            passed=ok,
            details=f"canonical frontmatter parser: {detail}",
        )
    )

    # inf-graceful-degradation-001: fetch_json catches errors
    ok, detail = _check_file_contains(agg_path, ["except Exception", "return None"])
    report.results.append(
        SpecResult(
            spec_id="inf-graceful-degradation-001",
            system="infrastructure",
            tier="V1",
            passed=ok,
            details=f"aggregator graceful degradation: {detail}",
        )
    )

    # re-phase-ordering-001: PhasedExecutor exists
    ok, detail = _check_file_contains(engine_path, ["PhasedExecutor", "gpu_concurrency"])
    report.results.append(
        SpecResult(
            spec_id="re-phase-ordering-001",
            system="reactive_engine",
            tier="V1",
            passed=ok,
            details=f"phased execution: {detail}",
        )
    )

    # tl-interaction-visibility-001: cross-system interaction logging
    ok, detail = _check_file_contains(
        agg_path,
        [
            "hapax_interaction(",
        ],
    )
    report.results.append(
        SpecResult(
            spec_id="tl-interaction-visibility-001",
            system="telemetry",
            tier="V2",
            passed=ok,
            details=detail,
        )
    )

    return report


# ── Runtime Checks ────────────────────────────────────────────────────────────


def audit_runtime() -> SpecReport:
    """Run runtime spec checks (requires live system state files)."""
    report = SpecReport(timestamp=time.time())

    # pc-heartbeat-001: perception ring has recent data
    perception_path = Path.home() / ".cache" / "hapax-voice" / "perception-state.json"
    try:
        data = json.loads(perception_path.read_text())
        ts = data.get("timestamp", 0)
        age = time.time() - ts
        report.results.append(
            SpecResult(
                spec_id="pc-heartbeat-001",
                system="perception",
                tier="V0",
                passed=age < 10.0,
                details=f"perception state age: {age:.1f}s" + (" (STALE)" if age >= 10 else ""),
            )
        )
    except (OSError, json.JSONDecodeError) as e:
        report.results.append(
            SpecResult(
                spec_id="pc-heartbeat-001",
                system="perception",
                tier="V0",
                passed=False,
                details=f"cannot read perception state: {e}",
            )
        )

    # st-heartbeat-001: stimmung file fresh
    stimmung_path = Path("/dev/shm/hapax-stimmung/state.json")
    try:
        data = json.loads(stimmung_path.read_text())
        ts = data.get("timestamp", 0)
        age = time.monotonic() - ts if ts > 0 else 999
        stance = data.get("overall_stance", "unknown")
        report.results.append(
            SpecResult(
                spec_id="st-heartbeat-001",
                system="stimmung",
                tier="V0",
                passed=age < 20.0,
                details=f"stimmung age: {age:.1f}s, stance: {stance}",
            )
        )
    except (OSError, json.JSONDecodeError) as e:
        report.results.append(
            SpecResult(
                spec_id="st-heartbeat-001",
                system="stimmung",
                tier="V0",
                passed=False,
                details=f"cannot read stimmung state: {e}",
            )
        )

    # st-dimension-coverage-001: all dimensions fresh
    try:
        data = json.loads(stimmung_path.read_text())
        stale_dims = []
        for dim in [
            "health",
            "resource_pressure",
            "error_rate",
            "processing_throughput",
            "perception_confidence",
            "llm_cost_pressure",
        ]:
            dim_data = data.get(dim, {})
            freshness = dim_data.get("freshness_s", 999)
            if freshness >= 120:
                stale_dims.append(f"{dim}({freshness:.0f}s)")
        report.results.append(
            SpecResult(
                spec_id="st-dimension-coverage-001",
                system="stimmung",
                tier="V1",
                passed=len(stale_dims) == 0,
                details=f"stale dimensions: {stale_dims}" if stale_dims else "all dimensions fresh",
            )
        )
    except (OSError, json.JSONDecodeError):
        report.results.append(
            SpecResult(
                spec_id="st-dimension-coverage-001",
                system="stimmung",
                tier="V1",
                passed=False,
                details="stimmung file not available",
            )
        )

    # vs-heartbeat-001: visual layer state fresh
    visual_path = Path("/dev/shm/hapax-compositor/visual-layer-state.json")
    try:
        mtime = visual_path.stat().st_mtime
        age = time.time() - mtime
        report.results.append(
            SpecResult(
                spec_id="vs-heartbeat-001",
                system="visual",
                tier="V0",
                passed=age < 6.0,
                details=f"visual state age: {age:.1f}s",
            )
        )
    except OSError as e:
        report.results.append(
            SpecResult(
                spec_id="vs-heartbeat-001",
                system="visual",
                tier="V0",
                passed=False,
                details=f"cannot read visual state: {e}",
            )
        )

    # tp-protention-learning-001: protention state exists
    protention_path = Path.home() / ".cache" / "hapax-voice" / "protention-state.json"
    try:
        data = json.loads(protention_path.read_text())
        chain_obs = sum(
            sum(v.values()) for v in data.get("activity_chain", {}).get("counts", {}).values()
        )
        report.results.append(
            SpecResult(
                spec_id="tp-protention-learning-001",
                system="temporal",
                tier="V1",
                passed=chain_obs > 0,
                details=f"protention has {chain_obs} activity observations",
            )
        )
    except (OSError, json.JSONDecodeError):
        report.results.append(
            SpecResult(
                spec_id="tp-protention-learning-001",
                system="temporal",
                tier="V1",
                passed=False,
                details="protention state not found (engine hasn't learned yet)",
            )
        )

    # inf-qdrant-001: Qdrant reachable with all collections
    try:
        from shared.config import get_qdrant

        client = get_qdrant()
        collections = [c.name for c in client.get_collections().collections]
        required = {
            "documents",
            "profile-facts",
            "axiom-precedents",
            "studio-moments",
            "operator-corrections",
            "operator-episodes",
            "operator-patterns",
        }
        missing = required - set(collections)
        report.results.append(
            SpecResult(
                spec_id="inf-qdrant-001",
                system="infrastructure",
                tier="V0",
                passed=len(missing) == 0,
                details=f"collections present: {len(required) - len(missing)}/{len(required)}"
                + (f" (missing: {missing})" if missing else ""),
            )
        )
    except Exception as e:
        report.results.append(
            SpecResult(
                spec_id="inf-qdrant-001",
                system="infrastructure",
                tier="V0",
                passed=False,
                details=f"Qdrant unreachable: {e}",
            )
        )

    # inf-ollama-001: Ollama reachable with embedding model
    try:
        import ollama

        client = ollama.Client(timeout=3)
        models = client.list()
        model_names = [m.get("name", m.get("model", "")) for m in models.get("models", [])]
        has_nomic = any("nomic" in n for n in model_names)
        report.results.append(
            SpecResult(
                spec_id="inf-ollama-001",
                system="infrastructure",
                tier="V0",
                passed=has_nomic,
                details=f"nomic model: {'found' if has_nomic else 'MISSING'} "
                f"(models: {len(model_names)})",
            )
        )
    except Exception as e:
        report.results.append(
            SpecResult(
                spec_id="inf-ollama-001",
                system="infrastructure",
                tier="V0",
                passed=False,
                details=f"Ollama unreachable: {e}",
            )
        )

    # tm-cycle-mode-001: cycle mode readable
    cycle_path = Path.home() / ".cache" / "hapax" / "cycle-mode"
    try:
        mode = cycle_path.read_text().strip()
        report.results.append(
            SpecResult(
                spec_id="tm-cycle-mode-001",
                system="timing",
                tier="V1",
                passed=mode in ("dev", "prod"),
                details=f"cycle mode: {mode}",
            )
        )
    except OSError:
        report.results.append(
            SpecResult(
                spec_id="tm-cycle-mode-001",
                system="timing",
                tier="V1",
                passed=False,
                details="cycle mode file not found (defaulting to prod)",
            )
        )

    return report


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    """Run spec audit and print report."""
    import sys

    print("=== Structural Audit ===")
    structural = audit_structural()
    print(structural.summary())
    print()

    print("=== Runtime Audit ===")
    runtime = audit_runtime()
    print(runtime.summary())
    print()

    total_passed = structural.passed + runtime.passed
    total = len(structural.results) + len(runtime.results)
    vital_fails = structural.vital_failures + runtime.vital_failures
    print(f"Total: {total_passed}/{total} specs passing")
    if vital_fails:
        print(f"VITAL FAILURES: {len(vital_fails)} — system operationally degraded")
        sys.exit(1)


if __name__ == "__main__":
    main()
