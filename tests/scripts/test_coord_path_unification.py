"""Coord event-log path unification (reform fix, CASE-CROSS-RUNTIME-COMMS-001).

The canonical coordination SSOT is the single user-writable tree
``~/.cache/hapax/coord`` (``coord_base_dir()``), NOT the former root-owned
``/var/lib/hapax/coord`` that uid 1000 could never ``mkdir`` into. Every coord
script must resolve its paths through the ``shared.coord_event_log`` resolvers so
one log lives outside every worktree and no dead default fires in production.

These pins guard against a coord script re-introducing a hardcoded ``/var/lib``
literal (which previously HARD-BLOCKED the dispatch-launch coord write) and prove
``coord_event_log_from_env()`` falls back to ``coord_base_dir()`` when unset.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCRIPTS_DIR = REPO_ROOT / "scripts"
DISPATCH_SCRIPT = SCRIPTS_DIR / "hapax-methodology-dispatch"

# Every env var that can redirect coord path resolution; cleared so the test
# exercises the bare default (which must be the user-writable cache base).
_COORD_ENV_VARS = (
    "HAPAX_COORD_DIR",
    "HAPAX_COORD_LEDGER_DB",
    "HAPAX_COORD_JSONL_MIRROR",
    "HAPAX_COORD_SPOOL_DIR",
    "HAPAX_COORD_GRANT_DIR",
    "HAPAX_COORD_GRANT_KEY",
    "XDG_CACHE_HOME",
)


def _load_script_module(name: str, path: Path) -> ModuleType:
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)
    return module


def test_no_var_lib_coord_literal_in_scripts() -> None:
    offenders: list[str] = []
    for path in sorted(SCRIPTS_DIR.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "/var/lib/hapax/coord" in text:
            offenders.append(str(path.relative_to(SCRIPTS_DIR)))
    assert not offenders, (
        "coord scripts must not hardcode the dead root-owned /var/lib/hapax/coord "
        f"default — resolve via shared.coord_event_log instead: {offenders}"
    )


def test_coord_event_log_from_env_unset_resolves_to_cache_base(tmp_path: Path) -> None:
    module = _load_script_module("hapax_methodology_dispatch_pathtest", DISPATCH_SCRIPT)
    home = tmp_path / "home"
    with mock.patch.dict(os.environ, {"HOME": str(home)}):
        for var in _COORD_ENV_VARS:
            os.environ.pop(var, None)
        log = module.coord_event_log_from_env()
    base = home / ".cache" / "hapax" / "coord"
    assert log.db_path == base / "ledger.db"
    assert log.jsonl_path == base / "ledger.jsonl"
    assert log.spool_dir == base / "spool"
    assert "/var/lib" not in str(log.db_path)
