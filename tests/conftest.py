"""Root conftest — skip tests that depend on unavailable optional packages
or local-only files not present in CI.

Hardware packages (audio extra): pipecat, pyaudio, torch, cv2, pvporcupine
Sync packages (sync-pipeline extra): googleapiclient
Local files: profiles/operator.json, profiles/demo-personas.yaml, hapaxromana paths
"""

from __future__ import annotations

import importlib
import json
import os
import pwd
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared import frame_verdicts as fv


@pytest.fixture(autouse=True)
def _isolate_gate_log(tmp_path, monkeypatch):
    """Keep routing-gate events and their durable mirror out of the operator's ledger.

    shared.gate_log resolves its canonical path at call time from HAPAX_GATE_LOG, so
    every test (and every child process it spawns) appends under tmp_path; the durable
    sink root follows the same rule through HAPAX_DURABLE_SINK_ROOT.
    """
    monkeypatch.setenv("HAPAX_GATE_LOG", str(tmp_path / "gate-events.jsonl"))


@pytest.fixture(autouse=True)
def _isolate_durable_sink(tmp_path, monkeypatch):
    """Keep the call-time durable root valid, including chronicle and gate mirrors."""
    sink_root = tmp_path / "durable-sink"
    sink_root.mkdir()
    monkeypatch.setenv("HAPAX_DURABLE_SINK_ROOT", str(sink_root))


@pytest.fixture(autouse=True)
def _isolate_egress_audit(tmp_path, monkeypatch):
    """Replace the cached writer and the constructor's per-call fallback."""
    from shared.governance import monetization_egress_audit as audit

    path = tmp_path / "egress-audit.jsonl"
    monkeypatch.setattr(audit, "DEFAULT_AUDIT_PATH", path)
    monkeypatch.setattr(audit, "_DEFAULT_WRITER", audit.MonetizationEgressAudit(path))


@pytest.fixture(autouse=True)
def _isolate_flagged_store(tmp_path, monkeypatch):
    """Cover both the cached gate store and subsequent default construction."""
    from agents.monetization_review import flagged_store
    from shared.governance import monetization_safety

    root = tmp_path / "flagged-payloads"
    monkeypatch.setattr(flagged_store, "DEFAULT_FLAGGED_DIR", root)
    monkeypatch.setattr(monetization_safety, "_FLAGGED_STORE", flagged_store.FlaggedStore(root))


@pytest.fixture(autouse=True)
def _isolate_dispatch_trace(tmp_path, monkeypatch):
    """The enabled writer looks up this module attribute on every append."""
    monkeypatch.setattr(
        "shared.affordance_pipeline.DISPATCH_TRACE_FILE", tmp_path / "dispatch.jsonl"
    )


@pytest.fixture(autouse=True)
def _isolate_recruitment_log(tmp_path, monkeypatch):
    """Redirect the per-write module attribute without changing enablement."""
    monkeypatch.setattr(
        "shared.affordance_pipeline.RECRUITMENT_LOG_FILE", tmp_path / "recruitment.jsonl"
    )


@pytest.fixture(autouse=True)
def _isolate_embed_cache(tmp_path, monkeypatch):
    """The pipeline explicitly passes this attribute to the captured-default cache."""
    monkeypatch.setattr(
        "shared.affordance_pipeline._DISK_CACHE_PATH", tmp_path / "embed-cache.json"
    )


@pytest.fixture(autouse=True)
def _isolate_chronicle(tmp_path, monkeypatch):
    """Keep default-path equality, so Stage0 events still require their durable mirror."""
    monkeypatch.setattr("shared.chronicle.CHRONICLE_FILE", tmp_path / "chronicle.jsonl")


@pytest.fixture(autouse=True)
def _isolate_tavily_locks(tmp_path, monkeypatch):
    """Client construction looks up this fallback when no lock directory is supplied."""
    monkeypatch.setattr("shared.tavily_client.DEFAULT_LOCK_DIR", tmp_path / "tavily-locks")


@pytest.fixture(autouse=True)
def _isolate_correction_question(tmp_path, monkeypatch):
    """Both the atomic writer and reader look up QUESTION_FILE per call."""
    monkeypatch.setattr("shared.active_correction.QUESTION_FILE", tmp_path / "correction.json")


@pytest.fixture(autouse=True)
def _isolate_segment_log(tmp_path, monkeypatch):
    """SegmentRecorder and direct appends resolve the environment per write."""
    monkeypatch.setenv("HAPAX_SEGMENTS_LOG", str(tmp_path / "segments.jsonl"))


@pytest.fixture(autouse=True)
def _isolate_workspace_snapshot(tmp_path, monkeypatch):
    """WorkspaceMonitor recomputes Path.home() inside _persist_analysis."""
    home = tmp_path / "fixture-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))


_AFFORDANCE_REACHING_MODULES = (
    "tests/test_affordance_pipeline.py",
    "tests/test_affordance_migration.py",
    "tests/test_affordance_retrieval.py",
    "tests/test_perception_impingement.py",
    "tests/shared/test_affordance_conative_prior.py",
    "tests/shared/test_camera_salience_production_wiring.py",
)
_MONETIZATION_REACHING_MODULES = (
    "tests/governance/test_monetization_safety.py",
    "tests/governance/test_monetization_safety_ring2_integration.py",
    "tests/governance/test_demonet_metrics.py",
    "tests/governance/test_quiet_frame_subscriber.py",
    "tests/monetization_review/test_whitelist.py",
    "tests/shared/test_programme_monetization_opt_ins.py",
    "tests/test_affordance_pipeline_d26_programme_plumb.py",
    "tests/test_preset_bias_monetization_gate.py",
)
_NARRATION_REACHING_MODULES = (
    "tests/shared/test_narration_triad.py",
    "tests/hapax_daimonion/autonomous_narrative/test_state_readers.py",
    "tests/hapax_daimonion/test_narration_triad_dispatch.py",
    "tests/hapax_daimonion/autonomous_narrative/test_narration_recruitment.py",
)

# Each pin runs every established reaching module for that family. The final
# tuple is the default-shaped parent relative to HOME or a private SHM mount.
_SINK_PINS = {
    "egress": (
        _MONETIZATION_REACHING_MODULES
        + _AFFORDANCE_REACHING_MODULES
        + (
            "tests/test_affordance_dispatch_trace.py",
            "tests/test_affordance_pipeline_u8_preset_family_bias.py",
        ),
        "home",
        ("hapax-state",),
    ),
    "dispatch": (
        _AFFORDANCE_REACHING_MODULES,
        "home",
        ("hapax-state", "affordance"),
    ),
    "recruitment": (
        _AFFORDANCE_REACHING_MODULES[-2:],
        "home",
        ("hapax-state", "affordance"),
    ),
    "embed": (
        _AFFORDANCE_REACHING_MODULES[:1],
        "home",
        (".cache", "hapax"),
    ),
    "durable": (
        _NARRATION_REACHING_MODULES,
        "home",
        (".cache", "hapax", "stage0-durable-sink"),
    ),
    "chronicle": (_NARRATION_REACHING_MODULES, "shm", ("hapax-chronicle",)),
    "tavily": (
        ("tests/shared/test_tavily_client.py",),
        "home",
        (".cache", "hapax", "tavily"),
    ),
    "workspace": (
        ("tests/hapax_daimonion/test_cross_component_integration.py",),
        "home",
        (".local", "share", "hapax-daimonion"),
    ),
    "correction": (("tests/test_active_correction.py",), "shm", ("hapax-compositor",)),
    "flagged": (
        ("tests/governance/test_monetization_safety_ring2_integration.py",),
        "home",
        ("hapax-state", "monetization-flagged"),
    ),
    "segment": (
        ("tests/hapax_daimonion/test_response_dispatch.py",),
        "home",
        ("hapax-state", "segments"),
    ),
}


@pytest.fixture
def sink_subprocess(tmp_path):
    """Fresh imports and execution, with physical containment for captured SHM defaults.

    Bubblewrap supplies an empty private mount before Python starts; it does not
    redirect a writer to the fixture's expected output or suppress a write. A
    removed fixture therefore leaves its default-shaped file visible to the pin.
    Persistent tmp_path storage is required by the real durable-root validator.
    """

    def run(family):
        modules, storage, relative = _SINK_PINS[family]
        root = tmp_path / "sink-child"
        home = root / "home"
        shm = home / "private-shm"
        shm.mkdir(parents=True)
        base = root / "pytest"
        # Production requires this fallback to exist. Seed it so accidental
        # durable appends cannot disappear behind a swallowed missing-root error.
        home.joinpath(".cache", "hapax", "stage0-durable-sink").mkdir(parents=True)
        env = os.environ.copy()
        for key in (
            "HAPAX_GATE_LOG",
            "HAPAX_DURABLE_SINK_ROOT",
            "HAPAX_SEGMENTS_LOG",
            "HAPAX_REFUSALS_LOG_PATH",
            "HAPAX_PUBLICATION_LOG_PATH",
            "HAPAX_FRAME_PROCEDURE_ROOT",
            "HAPAX_DISPATCH_TRACE",
            "HAPAX_RECRUITMENT_LOG",
            "HAPAX_DEMONET_AUDIT",
        ):
            env.pop(key, None)
        env["HOME"] = str(home)
        env["TMPDIR"] = str(root)
        command = [
            "unshare",
            "--user",
            "--map-current-user",
            "--mount",
            "--net",
            "bwrap",
            "--bind",
            "/",
            "/",
        ]
        command += ["--dev-bind", "/dev", "/dev", "--bind", str(shm), "/dev/shm"]
        # Some unrelated readers still contain absolute operator paths. Hide
        # those parents as well, without reading their contents.
        operator_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        for index, parts in enumerate((("hapax-state",), (".cache", "hapax"), (".local", "share"))):
            empty = root / f"absolute-parent-{index}"
            empty.mkdir()
            command += ["--bind", str(empty), str(operator_home.joinpath(*parts))]
        command += [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--confcutdir=tests",
            f"--basetemp={base}",
            "-k",
            "not root_sink_subprocess_pin",
            *modules,
        ]
        result = subprocess.run(
            command, cwd=_PROJECT_ROOT, env=env, text=True, capture_output=True, timeout=240
        )
        parents = [shm.joinpath(*relative)] if storage == "shm" else [home.joinpath(*relative)]
        # A call-time HOME resolver must not be masked by the workspace fixture.
        # Workspace snapshots themselves deliberately belong in fixture HOME.
        if storage == "home" and family != "workspace":
            parents += [p.joinpath(*relative) for p in base.glob("*/fixture-home")]
        leaks = []
        for parent in parents:
            if parent.is_file():
                leaks.append(parent)
            elif parent.is_dir():
                leaks.extend(p for p in parent.rglob("*") if p.is_file())
        output = result.stdout + result.stderr
        assert not leaks, f"{family} escaped its fixture: {leaks}\n{output}"
        assert result.returncode == 0, output
        assert " passed" in result.stdout, output

    return run


@pytest.fixture(autouse=True)
def _isolate_turn_timing_witness(tmp_path, monkeypatch):
    """Keep TurnBudget.emit() receipts out of the production /dev/shm witness.

    Voice pipeline/runner paths exercised in tests emit TIMING receipts via
    turn_budget.record_turn_timing, which defaults to the live
    voice-output-witness.json. Redirect the default path to tmp; tests that
    pass an explicit path (or patch the seam themselves) are unaffected.
    No-op unless the module is already imported by the test's module.
    """
    if sys.modules.get("agents.hapax_daimonion.turn_budget") is None:
        return
    from agents.hapax_daimonion import voice_output_witness as _vw

    def _redirected(**kwargs):
        kwargs.setdefault("path", tmp_path / "voice-output-witness.json")
        return _vw.record_turn_timing(**kwargs)

    monkeypatch.setattr("agents.hapax_daimonion.turn_budget.record_turn_timing", _redirected)


@pytest.fixture(autouse=True, scope="session")
def _frame_verdicts_default_root(tmp_path_factory: pytest.TempPathFactory):
    """Every governed-dispatch validation consults the frame's verdicts (shared/frame_verdicts.py)
    and refuses when they are absent or stale. Tests run without the vault, so the session gets a
    fresh verdict set in which nothing is decayed; a test that wants a decayed member or a stale
    epoch sets HAPAX_FRAME_PROCEDURE_ROOT itself (a function-scoped monkeypatch wins)."""
    root = tmp_path_factory.mktemp("frame-procedure")
    epoch = root / "_runs" / "epochs" / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-00000000"
    epoch.mkdir(parents=True)
    member = {"id": "nothing", "location": {"path": str(root / "nothing")}}
    (epoch / "elements.json").write_text(
        json.dumps(
            [
                {
                    "id": "frame:relevance-report",
                    "kind": "relevance_report",
                    "payload": {
                        "verdicts": [
                            {
                                "subject": {"member_id": "nothing"},
                                "relation": relation,
                                "verdict": "FALSE" if relation == "scope_exited" else "UNKNOWN",
                                "projection": "frame-reduction",
                            }
                            for relation in sorted(fv.ALL_RELATIONS)
                        ]
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    (root / "declaration").mkdir()
    (root / "declaration" / "mass.yaml").write_text(
        json.dumps({"projection": "frame-reduction", "members": [member]}), encoding="utf-8"
    )
    (epoch / "coverage.json").write_text(
        json.dumps(
            [
                {
                    "member_id": "nothing",
                    "member_declaration_identity": fv._member_declaration_identity(member, []),
                }
            ]
        ),
        encoding="utf-8",
    )
    (epoch / "publish.json").write_text(
        json.dumps({"epoch": epoch.name, "swapped": True, "reason": "test fixture"}),
        encoding="utf-8",
    )
    (root / "_runs" / "current").symlink_to(Path("epochs") / epoch.name)
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("HAPAX_FRAME_PROCEDURE_ROOT", str(root))
        yield


# Packages that require optional extras
_HARDWARE_PACKAGES = ["pipecat", "pyaudio", "torch", "cv2", "pvporcupine"]
_SYNC_PACKAGES = ["googleapiclient"]

# Top-level test files that transitively import hardware-only modules
_AUDIO_DEP_FILES = {
    "test_audio_processor.py",
    "test_frame_gate.py",
    "test_perception.py",
    "test_perception_integration.py",
    "test_voice.py",
    "test_voice_checks.py",
}

# Prefixes for hapax_daimonion test files at top level
_HAPAX_VOICE_PREFIX = "test_hapax_daimonion_"
_OTHER_VOICE_PREFIXES = ("test_governor", "test_dimensions")

# Test files that depend on local-only profile files (gitignored)
_PROFILE_DEP_FILES = {
    "test_demo_agent.py",
    "test_demo_audiences.py",
    "test_demo_custom_persona.py",
    "test_demo_dossier.py",
    "test_demo_integration.py",
    "test_demo_models.py",
    "test_demo_quality_integration.py",
    "test_demo_sufficiency.py",
    "test_context_tools.py",
}

# Test files that depend on operator.json (gitignored)
_OPERATOR_DEP_FILES = {
    "test_operator.py",
}

# Test files that depend on external repo paths or local filesystem state
_LOCAL_ENV_FILES = {
    "test_knowledge_sufficiency.py",
    "test_profiler.py",
    "test_sufficiency_probes.py",
}

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _is_available(pkg: str) -> bool:
    try:
        importlib.import_module(pkg)
        return True
    except ImportError:
        return False


_has_audio = all(_is_available(p) for p in _HARDWARE_PACKAGES)
_has_sync = all(_is_available(p) for p in _SYNC_PACKAGES)
_has_personas = (_PROJECT_ROOT / "profiles" / "demo-personas.yaml").is_file()
_has_operator = (_PROJECT_ROOT / "profiles" / "operator.json").is_file()

collect_ignore_glob: list[str] = []

if not _has_audio:
    # NOTE: hapax_daimonion/ is NOT ignored here — it has its own conftest.py
    # that stubs pipecat/pyaudio/torch/openwakeword before imports.
    collect_ignore_glob.append(_HAPAX_VOICE_PREFIX + "*")
    for f in _AUDIO_DEP_FILES:
        collect_ignore_glob.append(f)
    for prefix in _OTHER_VOICE_PREFIXES:
        collect_ignore_glob.append(prefix + "*")

if not _has_personas:
    for f in _PROFILE_DEP_FILES:
        collect_ignore_glob.append(f)

if not _has_operator:
    for f in _OPERATOR_DEP_FILES:
        collect_ignore_glob.append(f)

# Tests that depend on external repos or local filesystem layout
# (hapaxromana, obsidian-hapax, Claude Code transcripts, etc.)
if not Path.home().joinpath("projects", "hapaxromana").is_dir():
    for f in _LOCAL_ENV_FILES:
        collect_ignore_glob.append(f)
