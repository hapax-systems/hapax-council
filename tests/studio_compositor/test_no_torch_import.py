"""Regression pin: compositor modules must NOT import torch or Kokoro.

Delta session's ALPHA-FINDING-1 (Phase 3 of the post-epic audit) traced
the compositor's ~49 MB/min RSS leak to an in-process Kokoro forward
pass reaching ``director_loop._synthesize``. That call site lazy-imported
``agents.hapax_daimonion.tts.TTSManager``, which pulled libtorch_cuda +
35 libtorch* mappings + the full CUDA driver chain into the compositor
process.

This test walks the static import graph reachable from the compositor
entry points and fails fast if anything along the way imports ``torch``,
``kokoro``, or ``agents.hapax_daimonion.tts``. The TTS delegation fix
routes synthesis over a UDS socket to the already-running daimonion —
keeping this pin live prevents a future lazy-import from silently
re-introducing the regression.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

_COMPOSITOR_ROOT = Path(__file__).resolve().parents[2] / "agents" / "studio_compositor"

_FORBIDDEN_PREFIXES = (
    "torch",
    "kokoro",
    "agents.hapax_daimonion.tts",
)


def _iter_imports(module_path: Path) -> Iterator[tuple[str, int]]:
    try:
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            yield node.module, node.lineno


def _is_forbidden(module: str) -> bool:
    # agents.hapax_daimonion (the package) is fine — the voice daemon shares
    # pw_audio_output + a few small utilities with the compositor. Only the
    # ``.tts`` submodule drags torch. Match submodule prefixes exactly.
    for forbidden in _FORBIDDEN_PREFIXES:
        if module == forbidden or module.startswith(forbidden + "."):
            return True
    return False


@pytest.mark.parametrize(
    "py_file",
    sorted(_COMPOSITOR_ROOT.rglob("*.py")),
    ids=lambda p: str(p.relative_to(_COMPOSITOR_ROOT)),
)
def test_compositor_module_does_not_import_torch_or_kokoro(py_file: Path) -> None:
    violations: list[tuple[str, int]] = []
    for module, lineno in _iter_imports(py_file):
        if _is_forbidden(module):
            violations.append((module, lineno))
    assert violations == [], (
        f"{py_file.relative_to(_COMPOSITOR_ROOT)}: compositor modules must not "
        f"import torch / kokoro / daimonion TTS — delegate synthesis via "
        f"DaimonionTtsClient instead. Offending: {violations}"
    )
