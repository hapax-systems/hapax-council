"""Root conftest — skip tests that depend on unavailable optional packages
or local-only files not present in CI.

Hardware packages (audio extra): pipecat, pyaudio, torch, cv2, pvporcupine
Sync packages (sync-pipeline extra): googleapiclient
Local files: profiles/operator.json, profiles/demo-personas.yaml, hapaxromana paths
"""

from __future__ import annotations

import importlib
from pathlib import Path

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

# Prefixes for hapax_voice test files at top level
_HAPAX_VOICE_PREFIX = "test_hapax_voice_"
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
    collect_ignore_glob.extend(
        [
            "hapax_voice/*",
            _HAPAX_VOICE_PREFIX + "*",
        ]
    )
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
