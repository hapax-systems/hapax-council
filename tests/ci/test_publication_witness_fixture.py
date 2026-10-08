"""Exercise the real fixture and writer without optional publisher dependencies."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("import_when", ["never", "collection", "test"])
def test_publication_fixture_import_and_isolation_boundary(tmp_path: Path, import_when: str):
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "conftest.py").write_bytes((REPO_ROOT / "tests/conftest.py").read_bytes())
    probes = suite / "probes"
    probes.mkdir()
    witness_path = REPO_ROOT / "agents/publication_bus/witness_log.py"
    child_code = (
        f"import runpy; m = runpy.run_path({str(witness_path)!r}); "
        "assert m['append_publication_witness']("
        "surface='fixture-child', target='child-target', result='ok')"
    )
    # Use the actual stdlib writer. Loading its file avoids the parent package's
    # optional dependencies while exercising the canonical module identity.
    (suite / "writer.py").write_text(
        textwrap.dedent(f"""\
        import importlib.util
        import sys
        from pathlib import Path

        NAME = "agents.publication_bus.witness_log"
        def load():
            if NAME not in sys.modules:
                spec = importlib.util.spec_from_file_location(NAME, {str(witness_path)!r})
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.DEFAULT_PUBLICATION_LOG_PATH = Path({str(tmp_path / "default.jsonl")!r})
                sys.modules[NAME] = module
            return sys.modules[NAME]
        """),
        encoding="utf-8",
    )
    (probes / "conftest.py").write_text(
        textwrap.dedent("""\
        import sys
        from pathlib import Path
        import pytest
        import writer

        @pytest.hookimpl(hookwrapper=True)
        def pytest_runtest_teardown(item, nextitem):
            yield
            module = sys.modules.get(writer.NAME)
            if module is not None:
                # After fixture teardown, the same event must be writable again.
                assert module.append_publication_witness(
                    surface="fixture-probe", target="same-target", result="ok",
                    log_path=Path("teardown.jsonl"),
                )
        """),
        encoding="utf-8",
    )
    (probes / "test_probe.py").write_text(
        textwrap.dedent(f"""\
        import json
        import os
        import subprocess
        import sys
        from pathlib import Path
        import pytest
        import writer

        WHEN = {import_when!r}
        if WHEN == "collection":
            assert writer.load().append_publication_witness(
                surface="fixture-probe", target="same-target", result="ok",
                log_path=Path("collection.jsonl"),
            )

        @pytest.mark.parametrize("iteration", [1, 2])
        def test_write(iteration, tmp_path):
            # The fixture must never load the parent publication package.
            assert "agents.publication_bus" not in sys.modules
            path = Path(os.environ["HAPAX_PUBLICATION_LOG_PATH"])
            assert path == tmp_path / "publication-log.jsonl"
            if WHEN == "never":
                assert writer.NAME not in sys.modules
                return
            module = writer.load()
            assert module.PUBLICATION_LOG_PATH_ENV == "HAPAX_PUBLICATION_LOG_PATH"
            assert module.append_publication_witness(
                surface="fixture-probe", target="same-target", result="ok",
            )
            assert not module.append_publication_witness(
                surface="fixture-probe", target="same-target", result="ok",
            )
            subprocess.run(
                [sys.executable, "-c", {child_code!r}],
                check=True, capture_output=True, text=True,
            )
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            assert [row["surface"] for row in rows] == ["fixture-probe", "fixture-child"]
        """),
        encoding="utf-8",
    )
    env = {**os.environ, "PYTHONPATH": str(suite), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    env.pop("HAPAX_PUBLICATION_LOG_PATH", None)
    env.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--confcutdir=.", "-q", "-p", "no:cacheprovider"],
        cwd=suite,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout
    assert not (tmp_path / "default.jsonl").exists()
