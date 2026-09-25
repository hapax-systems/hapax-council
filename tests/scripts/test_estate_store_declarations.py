from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check-estate-store-declarations.py"
SPEC = importlib.util.spec_from_file_location("check_estate_store_declarations", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_missing_declaration_is_a_nonblocking_finding(tmp_path: Path) -> None:
    unit = tmp_path / "new.service"
    unit.write_text("[Service]\nExecStart=/usr/bin/true\n", encoding="utf-8")

    findings = module.check_services([unit], {"known-store"})
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--unit", str(unit), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert [finding.kind for finding in findings] == ["missing-store-declaration"]
    assert result.returncode == 0
    assert '"blocking": false' in result.stdout
    assert '"finding_count": 1' in result.stdout


def test_registered_store_and_explicit_none_are_clean(tmp_path: Path) -> None:
    writer = tmp_path / "writer.service"
    writer.write_text(
        "[Unit]\nX-Hapax-Store=estate-registration-runtime\n[Service]\nExecStart=/usr/bin/true\n",
        encoding="utf-8",
    )
    no_store = tmp_path / "reader.service"
    no_store.write_text(
        "[Unit]\nX-Hapax-Store=None\n[Service]\nExecStart=/usr/bin/true\n",
        encoding="utf-8",
    )

    assert module.check_services([writer, no_store], {"estate-registration-runtime"}) == []


def test_unknown_store_id_is_reported(tmp_path: Path) -> None:
    unit = tmp_path / "new.service"
    unit.write_text(
        "[Unit]\nX-Hapax-Store=made-up\n[Service]\nExecStart=/usr/bin/true\n",
        encoding="utf-8",
    )

    findings = module.check_services([unit], {"known-store"})

    assert [finding.kind for finding in findings] == ["unregistered-store-id"]


def test_checker_refuses_to_guess_comparison_base() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "pass --base-ref" in result.stderr


def test_shipped_units_are_inert_and_declare_outputs() -> None:
    unit_dir = REPO_ROOT / "systemd" / "units"
    services = [
        unit_dir / "hapax-estate-canary.service",
        unit_dir / "hapax-estate-canary-peer-check.service",
        unit_dir / "hapax-estate-drift-sweep.service",
    ]
    timers = [path.with_suffix(".timer") for path in services]

    assert module.check_services(services, {"estate-registration-runtime"}) == []
    assert " originate" in services[0].read_text(encoding="utf-8")
    assert " check-peer" in services[1].read_text(encoding="utf-8")
    assert " sweep-peer" in services[2].read_text(encoding="utf-8")
    for timer in timers:
        text = timer.read_text(encoding="utf-8")
        assert "WantedBy=timers.target" in text
        assert "Unit=hapax-estate" in text
    preset_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / "systemd" / "user-preset.d").glob("*")
        if path.is_file()
    )
    assert "hapax-estate-canary" not in preset_text
    assert "hapax-estate-drift-sweep" not in preset_text


def test_report_checker_is_not_wired_as_a_hook_or_deploy_blocker() -> None:
    searched = [
        *(REPO_ROOT / "hooks").rglob("*"),
        REPO_ROOT / "scripts" / "hapax-root-required-deploy-audit",
        REPO_ROOT / "scripts" / "hapax-post-merge-deploy",
    ]
    references = []
    for path in searched:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "check-estate-store-declarations" in text:
            references.append(str(path.relative_to(REPO_ROOT)))

    assert references == []
