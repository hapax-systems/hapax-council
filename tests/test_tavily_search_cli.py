"""The Tavily route's --check must not report a credential it does not have.

`load_tavily_api_key()` returns "" when nothing is found rather than raising, and
`TavilyClient` accepts the empty string, deferring the failure to request time. A check
written to catch exceptions therefore printed "secret=available" on a host holding no
credential at all -- the same false-green shape as a conformance checker that skips its
artifact checks and still says conformant.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "hapax-tavily-search"


def load_cli():
    # An explicit SourceFileLoader is required: spec_from_file_location infers the loader from
    # the suffix and returns None for an extensionless file. The estate keeps 146 Python
    # entrypoints with no extension, so this is the general shape for importing any of them.
    loader = importlib.machinery.SourceFileLoader("hapax_tavily_search", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


def _run(args: list[str], env_extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
    import os

    env = dict(os.environ)
    env.pop("TAVILY_API_KEY", None)
    env.update(env_extra)
    # PATH is emptied so the `pass` fallback cannot find a real credential on a developer
    # host; the point of the test is the no-credential branch.
    env["PATH"] = "/nonexistent"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


def test_check_refuses_when_no_credential_is_reachable() -> None:
    result = _run(["--check"], {})

    assert result.returncode == 2, f"must fail closed, got {result.returncode}: {result.stdout}"
    assert "secret=available" not in result.stdout, (
        "an absent credential must never be reported as available"
    )
    assert "no credential on this host" in result.stderr
    assert "Next:" in result.stderr, "executive_function: the error must carry a next action"


def test_check_does_not_advise_copying_the_credential() -> None:
    """B1 custody: the remedy is a remote seat, never replication.

    Copying a credential from podium to appendix is the workaround this estate has already
    been warned about; the error text must not send the next reader down that path.
    """
    result = _run(["--check"], {})

    assert "Do NOT copy" in result.stderr
    assert "remote seat" in result.stderr


def test_a_present_credential_is_reported_available() -> None:
    result = _run(["--check"], {"TAVILY_API_KEY": "probe-value-not-a-real-key"})

    assert result.returncode == 0, result.stderr
    assert "secret=available" in result.stdout


def test_exit_codes_are_distinct() -> None:
    """Config, refusal and upstream failure must be distinguishable by exit code alone.

    A caller that cannot tell 'no credential here' from 'budget exhausted' from 'upstream
    down' cannot route around any of them.
    """
    cli = load_cli()

    codes = {cli.EXIT_CONFIG, cli.EXIT_REFUSED, cli.EXIT_UPSTREAM}
    assert len(codes) == 3, "each failure class needs its own exit code"
    assert 0 not in codes, "no failure class may share the success code"
