"""The staged scanner is an explicit test input, never an implicit hook candidate."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STAGED = ROOT / "tests" / "fixtures" / "prepush_secret_scan.py"


@pytest.mark.parametrize("complete_location", ["primary", "activation"])
def test_unchanged_hook_selects_complete_scanner_not_staged_source(tmp_path, complete_location):
    hook_dir = tmp_path / "activation" / "scripts"
    hook_dir.mkdir(parents=True)
    common = tmp_path / "primary" / ".git"
    common.mkdir(parents=True)
    primary_scripts = common.parent / "scripts"
    primary_scripts.mkdir()
    complete = (hook_dir if complete_location == "activation" else primary_scripts) / (
        "hapax-prepush-secret-scan"
    )
    # Selection sentinel only: never invoked as a scanner or installed anywhere.
    complete.write_text("existing scanner selection sentinel\n")
    assert STAGED.is_file()
    wrapper = (ROOT / "scripts" / "pre-push").read_text()
    resolver = wrapper[wrapper.index("resolve() {") : wrapper.index("\nname_scan=")]
    result = subprocess.run(
        [
            "bash",
            "-c",
            'root="$1"; common="$2"; hook_dir="$3"\n'
            + resolver
            + "\nresolve scripts/hapax-prepush-secret-scan\n",
            "selection-test",
            str(ROOT),
            str(common),
            str(hook_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()).resolve() == complete.resolve()
    assert STAGED.read_bytes() != complete.read_bytes()


def test_staged_source_does_not_fill_missing_operational_scanner(tmp_path):
    hook_dir = tmp_path / "activation" / "scripts"
    hook_dir.mkdir(parents=True)
    common = tmp_path / "primary" / ".git"
    common.mkdir(parents=True)
    wrapper = (ROOT / "scripts" / "pre-push").read_text()
    resolver = wrapper[wrapper.index("resolve() {") : wrapper.index("\nname_scan=")]
    assert STAGED.is_file()
    result = subprocess.run(
        [
            "bash",
            "-c",
            'root="$1"; common="$2"; hook_dir="$3"\n'
            + resolver
            + "\nresolve scripts/hapax-prepush-secret-scan\n",
            "selection-test",
            str(ROOT),
            str(common),
            str(hook_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert not result.stdout
