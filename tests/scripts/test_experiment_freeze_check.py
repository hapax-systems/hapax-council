from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "experiment-freeze-check"
MANIFEST = REPO_ROOT / "experiment-freeze-manifest.txt"

LIVE_RULER_PATHS = {
    "agents/deliberative_council/rubrics.py",
    "agents/hapax_daimonion/daily_segment_prep.py",
    "agents/hapax_daimonion/segment_composability_gate.py",
    "shared/segment_prep_a0_runner.py",
    "shared/segment_prep_consultation.py",
    "shared/segment_prep_contract.py",
    "shared/segment_prep_dv_reader.py",
    "shared/segment_prep_pause.py",
    "shared/segment_prep_phase_controller.py",
}

RETIRED_CYCLE2_DYAD_PATHS = {
    "agents/hapax_daimonion/grounding_ledger.py",
    "agents/hapax_daimonion/grounding_evaluator.py",
    "agents/hapax_daimonion/stats.py",
    "agents/hapax_daimonion/experiment_runner.py",
    "agents/hapax_daimonion/eval_grounding.py",
    "agents/hapax_daimonion/conversation_pipeline.py",
    "agents/hapax_daimonion/persona.py",
    "agents/hapax_daimonion/conversational_policy.py",
}


def _manifest_paths() -> set[str]:
    return {
        line.strip()
        for line in MANIFEST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _write(repo: Path, relative: str, body: str = "baseline\n") -> None:
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def _repo_with_active_freeze(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "freeze-check-test@example.test")
    _git(repo, "config", "user.name", "Freeze Check Test")
    _write(repo, "experiment-phase.json", '{"phase": "a0-sced"}\n')
    _write(repo, "experiment-freeze-manifest.txt", MANIFEST.read_text(encoding="utf-8"))
    for relative in LIVE_RULER_PATHS | {"agents/hapax_daimonion/proofs/RESEARCH-STATE.md"}:
        _write(repo, relative)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")
    return repo


def _run_freeze_check(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT)],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )


def test_manifest_tracks_live_segment_ruler_not_retired_dyad() -> None:
    paths = _manifest_paths()

    assert paths >= LIVE_RULER_PATHS
    assert {
        "agents/hapax_daimonion/proofs/",
        "experiment-phase.json",
        "experiment-freeze-manifest.txt",
    } <= paths
    assert paths.isdisjoint(RETIRED_CYCLE2_DYAD_PATHS)


@pytest.mark.parametrize("frozen_path", sorted(LIVE_RULER_PATHS))
def test_active_phase_blocks_staged_live_ruler_change(
    tmp_path: Path,
    frozen_path: str,
) -> None:
    repo = _repo_with_active_freeze(tmp_path)
    _write(repo, frozen_path, "changed\n")
    _git(repo, "add", frozen_path)

    result = _run_freeze_check(repo)

    assert result.returncode == 1
    output = result.stdout + result.stderr
    assert "EXPERIMENT FREEZE" in output
    assert frozen_path in output


def test_active_phase_allows_staged_live_ruler_change_with_deviation(
    tmp_path: Path,
) -> None:
    repo = _repo_with_active_freeze(tmp_path)
    frozen_path = "agents/hapax_daimonion/daily_segment_prep.py"
    deviation_path = "research/protocols/deviations/DEVIATION-999.md"
    _write(repo, frozen_path, "changed\n")
    _write(repo, deviation_path, "# Deviation\n")
    _git(repo, "add", frozen_path, deviation_path)

    result = _run_freeze_check(repo)

    assert result.returncode == 0, result.stderr
    output = result.stdout + result.stderr
    assert "frozen path(s) modified with deviation record" in output
    assert frozen_path in output
