"""Root conftest — skip tests that depend on unavailable optional packages
or local-only files not present in CI.

Hardware packages (audio extra): pipecat, pyaudio, torch, cv2, pvporcupine
Sync packages (sync-pipeline extra): googleapiclient
Local files: profiles/operator.json, profiles/demo-personas.yaml, hapaxromana paths
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Money-rail resource receipts resolve their ledger at call time from this env
# var (agents/payment_processors/resource_receipts.default_receipt_log_path),
# falling back to the live /dev/shm production ledger only when it is unset. The
# env value therefore wins over any module-constant monkeypatch. Isolation must
# be universal: a session-private quarantine protects collection/between-test
# emissions, and a per-test override binds every test to its own tmp ledger. See
# the root safety-boundary exception documented for
# cc-task-money-rails-resource-receipt-ledger-20260630.
_RESOURCE_RECEIPT_LOG_ENV = "HAPAX_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH"
_RESOURCE_RECEIPT_QUARANTINE_DIR_ATTR = "_hapax_resource_receipt_quarantine_dir"
_RESOURCE_RECEIPT_PRIOR_ENV_ATTR = "_hapax_resource_receipt_prior_env"


def pytest_configure(config: pytest.Config) -> None:
    """Establish a session-private resource-receipt quarantine before collection.

    pytest imports test modules (and evaluates any module/collection-time code)
    after this hook runs. Redirecting the ledger env to a session-private
    quarantine here means that even a hostile inherited value cannot steer a
    collection-time emission at the live /dev/shm ledger. The prior process value
    is captured so it can be restored verbatim at unconfigure.
    """

    setattr(config, _RESOURCE_RECEIPT_PRIOR_ENV_ATTR, os.environ.get(_RESOURCE_RECEIPT_LOG_ENV))
    quarantine_dir = Path(tempfile.mkdtemp(prefix="hapax-resource-receipt-quarantine-"))
    setattr(config, _RESOURCE_RECEIPT_QUARANTINE_DIR_ATTR, quarantine_dir)
    os.environ[_RESOURCE_RECEIPT_LOG_ENV] = str(quarantine_dir / "resource-receipts.jsonl")


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config: pytest.Config) -> None:
    """Remove the quarantine, then restore inherited process state.

    Ordered fail-closed. ``trylast=True`` runs this after every other
    ``pytest_unconfigure`` hook, so no later teardown can emit at the live ledger
    behind our back. The session quarantine directory is removed *strictly*
    (errors propagate, never swallowed) while
    ``HAPAX_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH`` still points inside it, so any
    stray teardown emission lands in quarantine rather than the production
    ledger. Only after the quarantine has been removed successfully is the
    inherited environment value restored; if removal fails the error propagates
    (fail-visible) and the safe env stays in place (fail-closed).
    """

    quarantine_dir = getattr(config, _RESOURCE_RECEIPT_QUARANTINE_DIR_ATTR, None)
    if quarantine_dir is not None:
        shutil.rmtree(quarantine_dir)
    prior = getattr(config, _RESOURCE_RECEIPT_PRIOR_ENV_ATTR, None)
    if prior is None:
        os.environ.pop(_RESOURCE_RECEIPT_LOG_ENV, None)
    else:
        os.environ[_RESOURCE_RECEIPT_LOG_ENV] = prior


@pytest.fixture(autouse=True)
def _isolate_resource_receipt_ledger(tmp_path, monkeypatch):
    """Bind every test to its own money-rail resource-receipt ledger.

    ``default_receipt_log_path`` reads ``HAPAX_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH``
    at call time, so setting it here isolates every default-path emission —
    including call-time late imports and ordinary child processes that inherit
    the environment — inside the per-test ``tmp_path``. ``monkeypatch.setenv``
    restores the value captured before the test, which is the session quarantine
    established by ``pytest_configure`` (never the live default), so teardown
    returns to quarantine rather than the production ledger.
    """

    monkeypatch.setenv(
        _RESOURCE_RECEIPT_LOG_ENV,
        str(tmp_path / "resource-receipts.jsonl"),
    )


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
