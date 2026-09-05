"""Root conftest — skip tests that depend on unavailable optional packages
or local-only files not present in CI.

Hardware packages (audio extra): pipecat, pyaudio, torch, cv2, pvporcupine
Sync packages (sync-pipeline extra): googleapiclient
Local files: profiles/operator.json, profiles/demo-personas.yaml, hapaxromana paths
"""

from __future__ import annotations

import importlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared import frame_verdicts as fv


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
