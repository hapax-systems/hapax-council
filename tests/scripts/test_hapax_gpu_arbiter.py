"""Tests for scripts/hapax-gpu-arbiter — podium-5090 tenant control plane (signals/state/toggle).

The arbiter decides which workload owns the podium 5090: livestream COMPOSITING (production) or the
Ornith-35B coding workhorse (idle). Production has ABSOLUTE priority — an actively-public livestream is
never pre-empted, even by a manual override. This is the control plane only; no GPU actuation here.
"""

from __future__ import annotations

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-gpu-arbiter"


def _load():
    loader = SourceFileLoader("hapax_gpu_arbiter", str(_SCRIPT))
    spec = importlib.util.spec_from_loader("hapax_gpu_arbiter", loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules["hapax_gpu_arbiter"] = module  # so the script's @dataclass can resolve __module__
    loader.exec_module(module)
    return module


arb = _load()


def _paths(tmp_path: Path, **over):
    """An ArbiterPaths pointing at tmp files; callers seed only what a test needs."""
    return arb.ArbiterPaths(
        stream_mode=over.get("stream_mode", tmp_path / "stream-mode"),
        livestream_dev=over.get("livestream_dev", tmp_path / "livestream-surface-dev"),
        override=over.get("override", tmp_path / "gpu-arbiter-override"),
        tasks=over.get("tasks", tmp_path / "tasks"),
        prom=over.get("prom", tmp_path / "arbiter.prom"),
    )


def _seed(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# --- decide(): the truth table -------------------------------------------------


def test_idle_private_no_dev_is_ornith(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _seed(paths.stream_mode, "private\n")
    d = arb.decide(paths)
    assert d["mode"] == "ORNITH"
    assert d["tenant_5090"] == "ornith-35b"


def test_unset_stream_mode_is_not_live(tmp_path: Path) -> None:
    # No stream-mode file at all -> not livestreaming (errs only by the explicit public flag).
    d = arb.decide(_paths(tmp_path))
    assert d["mode"] == "ORNITH"
    assert d["livestreaming"] is False


def test_public_stream_is_production(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _seed(paths.stream_mode, "public\n")
    d = arb.decide(paths)
    assert d["mode"] == "PRODUCTION"
    assert d["tenant_5090"] == "compositing"
    assert d["livestreaming"] is True


def test_livestreaming_is_absolute_even_against_override_ornith(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _seed(paths.stream_mode, "public\n")
    _seed(paths.override, "ornith\n")
    d = arb.decide(paths)
    assert d["mode"] == "PRODUCTION"  # production has ABSOLUTE priority
    assert "refused" in d["why"].lower()


def test_livestream_dev_flag_forces_production(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _seed(paths.stream_mode, "private\n")
    _seed(paths.livestream_dev, "on\n")
    d = arb.decide(paths)
    assert d["mode"] == "PRODUCTION"
    assert d["livestream_dev"] is True


def test_override_production_reserves_when_idle(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _seed(paths.stream_mode, "private\n")
    _seed(paths.override, "production\n")
    d = arb.decide(paths)
    assert d["mode"] == "PRODUCTION"
    assert "override=production" in d["why"]


def test_override_ornith_beats_dev_heuristic_when_not_live(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _seed(paths.stream_mode, "private\n")
    _seed(paths.livestream_dev, "on\n")  # heuristic would say PRODUCTION
    _seed(paths.override, "ornith\n")  # operator forces ornith (not live -> allowed)
    d = arb.decide(paths)
    assert d["mode"] == "ORNITH"


def test_livestream_dev_via_cctask_heuristic(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _seed(paths.stream_mode, "private\n")
    tasks = paths.tasks
    _seed(
        tasks / "cc-task-compositor-fix.md",
        "---\nstatus: in_progress\n---\nwork on the darkplaces compositor\n",
    )
    d = arb.decide(paths)
    assert d["mode"] == "PRODUCTION"
    assert "cc-task" in d["livestream_dev_why"]


def test_falsey_dev_flag_is_off(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _seed(paths.stream_mode, "private\n")
    _seed(paths.livestream_dev, "off\n")  # present but falsey -> not dev
    d = arb.decide(paths)
    assert d["livestream_dev"] is False
    assert d["mode"] == "ORNITH"


# --- degradation: unreadable signal files must not crash -----------------------


def test_missing_files_degrade_to_idle(tmp_path: Path) -> None:
    # Nothing seeded; every reader degrades to its safe default -> ORNITH, no exception.
    d = arb.decide(_paths(tmp_path))
    assert d["mode"] == "ORNITH"


def test_invalid_override_falls_back_to_auto(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _seed(paths.stream_mode, "private\n")
    _seed(paths.override, "garbage\n")
    d = arb.decide(paths)
    assert d["override"] == "auto"
    assert d["mode"] == "ORNITH"


# --- prom output ---------------------------------------------------------------


def test_prom_shape(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _seed(paths.stream_mode, "public\n")
    arb.write_prom(arb.decide(paths), paths)
    text = paths.prom.read_text(encoding="utf-8")
    assert 'hapax_gpu_arbiter_mode{mode="production"} 1' in text
    assert 'hapax_gpu_arbiter_mode{mode="ornith"} 0' in text
    assert 'hapax_gpu_arbiter_signal{signal="livestreaming"} 1' in text


# --- toggles -------------------------------------------------------------------


def test_set_override_roundtrip(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    arb.set_override("ornith", paths)
    assert arb.get_override(paths.override) == "ornith"


def test_set_livestream_dev_on_off(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    arb.set_livestream_dev(True, paths)
    assert arb.livestream_dev_active(paths)[0] is True
    arb.set_livestream_dev(False, paths)
    assert arb.livestream_dev_active(paths)[0] is False
