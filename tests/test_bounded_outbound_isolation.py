"""Bounded-outbound isolation guard — receive-only rails cannot reach outbound.

Per cc-task ``20260628-mdlccore-phase6-receive-only-rails-unchanged-test``
(REQ-20260628-mdlc-core-freeze-and-bounded-outbound-executor, objective 6):
the bounded-outbound envelope (``shared/outbound_executor.py`` +
``shared/outbound_lane_pattern.py``) is a NEW separately-governed authority
surface, NOT a relaxation of the receive-only rails.

The refusal direction — the executor refuses every receive-only provider by
name — is enforced by ``tests/shared/test_outbound_executor.py``. This guard
enforces the reachability direction: no receive-only surface may import, or
transitively pull in, the bounded-outbound modules, so a receive-only reader
can never acquire a path to outbound execution.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

BOUNDED_OUTBOUND_MODULES: Final[frozenset[str]] = frozenset(
    {
        "shared.outbound_executor",
        "shared.outbound_lane_pattern",
    }
)

RECEIVE_ONLY_SURFACES: Final[tuple[str, ...]] = (
    "agents/payment_processors",
    "agents/publication_bus",
    "logos/api/routes/payment_rails.py",
    "logos/api/routes/_payment_rails_helpers.py",
)
"""Receive-only code surfaces that must never reach bounded-outbound.

The ``shared/*_receive_only_rail.py`` modules are appended by glob in
:func:`_receive_only_files` so newly wired rails are guarded automatically.
"""


def _receive_only_files(repo_root: Path = REPO_ROOT) -> list[Path]:
    files: list[Path] = []
    for surface in RECEIVE_ONLY_SURFACES:
        path = repo_root / surface
        if path.is_dir():
            files.extend(p for p in sorted(path.rglob("*.py")) if "__pycache__" not in p.parts)
        elif path.is_file():
            files.append(path)
    files.extend(sorted((repo_root / "shared").glob("*_receive_only_rail.py")))
    return files


def _imported_modules(file: Path) -> set[str]:
    tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _bounded_outbound_imports(files: list[Path]) -> list[tuple[Path, str]]:
    findings: list[tuple[Path, str]] = []
    for file in files:
        for module in sorted(_imported_modules(file)):
            if module in BOUNDED_OUTBOUND_MODULES or any(
                module.startswith(f"{name}.") for name in BOUNDED_OUTBOUND_MODULES
            ):
                findings.append((file, module))
    return findings


def test_receive_only_surface_inventory_is_nonempty() -> None:
    """The scan must never pass vacuously because the surfaces moved."""
    files = _receive_only_files()
    names = {p.name for p in files}
    assert "payment_rails.py" in names
    assert any(name.endswith("_receive_only_rail.py") for name in names)
    assert len(files) >= 10, (
        f"receive-only surface inventory collapsed to {len(files)} files; "
        "update RECEIVE_ONLY_SURFACES if the packages were relocated"
    )


def test_no_receive_only_surface_imports_bounded_outbound() -> None:
    """No receive-only module may import the bounded-outbound modules."""
    findings = _bounded_outbound_imports(_receive_only_files())
    assert findings == [], (
        "Receive-only surfaces import bounded-outbound modules:\n"
        + "\n".join(f"  {path}: {module}" for path, module in findings)
        + "\n\nThe bounded-outbound envelope is a separately-governed authority "
        "surface (REQ-20260628-mdlc-core-freeze-and-bounded-outbound-executor "
        "objective 6); receive-only rails must stay structurally incapable of "
        "reaching it."
    )


def test_scanner_detects_from_import(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad_rail.py"
    bad_file.write_text("from shared.outbound_executor import OutboundExecutor\n")
    assert _bounded_outbound_imports([bad_file]) == [(bad_file, "shared.outbound_executor")]


def test_scanner_detects_plain_import(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad_rail.py"
    bad_file.write_text("import shared.outbound_lane_pattern\n")
    assert _bounded_outbound_imports([bad_file]) == [(bad_file, "shared.outbound_lane_pattern")]


def test_scanner_detects_submodule_from_import(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad_rail.py"
    bad_file.write_text("from shared.outbound_executor import receipts\n")
    findings = _bounded_outbound_imports([bad_file])
    assert findings == [(bad_file, "shared.outbound_executor")]


def test_receive_only_import_closure_excludes_bounded_outbound() -> None:
    """Transitive proof: a clean interpreter importing every receive-only
    entrypoint must not pull the bounded-outbound modules into sys.modules."""
    probe = (
        "import sys\n"
        "import agents.payment_processors\n"
        "import agents.publication_bus\n"
        "import logos.api.routes.payment_rails\n"
        "guarded = {'shared.outbound_executor', 'shared.outbound_lane_pattern'}\n"
        "leaked = sorted(m for m in sys.modules if m in guarded)\n"
        "print('PROBE_RAN leaked=' + (','.join(leaked) or 'none'))\n"
        "sys.exit(1 if leaked else 0)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert "PROBE_RAN" in result.stdout, (
        f"import-closure probe did not run to completion:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert result.returncode == 0, (
        "bounded-outbound modules are reachable from the receive-only import "
        f"closure: {result.stdout.strip()}\nstderr: {result.stderr}"
    )
