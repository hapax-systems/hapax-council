"""Drop-in config truth — no theater in the daimonion systemd surface.

The 2026-06-10 voice foundation audit found env knobs in the (then
unversioned) drop-in directory that no code read — "where repairs go to
die". This pin enforces, for the versioned unit + drop-ins:

1. every ``HAPAX_*`` env var has a reader in ``agents/`` or ``shared/``;
2. every non-``HAPAX_*`` env var is an allowlisted external knob
   (consumed by a library or the runtime, not hapax code);
3. the configured ``HAPAX_TTS_BACKEND`` value is one the selector accepts.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
UNIT = REPO / "systemd" / "units" / "hapax-daimonion.service"
DROPIN_DIR = REPO / "systemd" / "units" / "hapax-daimonion.service.d"

# Consumed by libraries or the runtime itself — a reader in hapax code is
# not expected.
_EXTERNAL_PREFIXES = (
    "PATH",
    "PYTHONPATH",
    "HOME",
    "XDG_",
    "OMP_",
    "MKL_",
    "OPENBLAS_",
    "ONNXRUNTIME_",
    "OTEL_",
    "PYTORCH_",
    "CUDA_",
)


def _env_assignments() -> list[tuple[str, str, str]]:
    """(file, var, value) for every Environment= line in unit + drop-ins."""
    out: list[tuple[str, str, str]] = []
    for conf in [UNIT, *sorted(DROPIN_DIR.glob("*.conf"))]:
        for line in conf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line.startswith("Environment="):
                continue
            assignment = line.removeprefix("Environment=").strip().strip('"')
            name, _, value = assignment.partition("=")
            out.append((conf.name, name, value))
    return out


@lru_cache(maxsize=1)
def _source_corpus() -> str:
    chunks: list[str] = []
    for root in (REPO / "agents", REPO / "shared"):
        for py in root.rglob("*.py"):
            try:
                chunks.append(py.read_text(encoding="utf-8"))
            except OSError:
                continue
    return "\n".join(chunks)


def test_env_assignments_found() -> None:
    names = {name for _, name, _ in _env_assignments()}
    # Sanity floor — the surface this pin guards actually parsed.
    assert "HAPAX_TTS_BACKEND" in names
    assert "HAPAX_AUDIO_INPUT_TARGET" in names


def test_every_hapax_env_var_has_a_reader() -> None:
    corpus = _source_corpus()
    unread = [
        (conf, name)
        for conf, name, _ in _env_assignments()
        if name.startswith("HAPAX_") and name not in corpus
    ]
    assert not unread, (
        f"config theater: {unread} set env vars no code under agents/ or "
        "shared/ reads — kill the knob or honor it"
    )


def test_non_hapax_env_vars_are_allowlisted_external_knobs() -> None:
    unknown = [
        (conf, name)
        for conf, name, _ in _env_assignments()
        if not name.startswith("HAPAX_") and not name.startswith(_EXTERNAL_PREFIXES)
    ]
    assert not unknown, (
        f"unrecognized env vars {unknown} in the daimonion systemd surface — "
        "add a reader (HAPAX_*) or extend _EXTERNAL_PREFIXES with a comment"
    )


def test_configured_tts_backend_is_valid_and_honored() -> None:
    from agents.hapax_daimonion.tts import (
        TTS_BACKEND_ENV,
        VALID_TTS_BACKENDS,
        resolve_backend_from_env,
    )

    configured = {name: value for _, name, value in _env_assignments() if name == TTS_BACKEND_ENV}
    assert configured, f"{TTS_BACKEND_ENV} not set in any versioned drop-in"
    (value,) = set(configured.values())
    assert value in VALID_TTS_BACKENDS
    with patch.dict(os.environ, {TTS_BACKEND_ENV: value}):
        assert resolve_backend_from_env() == value
