"""`scripts/lib/secret.sh` — the shell half of the estate secret resolver. Never pass.

Driven through a real bash process with a fake `hapax-secret` on PATH, so these pin the
script as it will actually run, not a Python re-description of it. Synthetic values only.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "scripts" / "lib" / "secret.sh"
_BASH = shutil.which("bash") or "/usr/bin/bash"


@pytest.fixture(scope="module", autouse=True)
def _empty_bin(tmp_path_factory):
    """A directory with nothing in it, used as the PATH for the no-CLI case."""
    global _EMPTY_BIN
    _EMPTY_BIN = tmp_path_factory.mktemp("empty-bin")
    return _EMPTY_BIN


_EMPTY_BIN = Path("/nonexistent-bin")


def _fake_cli(tmp_path: Path, mapping: dict[str, str], *, exit_code: int = 1) -> Path:
    """A `hapax-secret` that answers for `mapping` and fails for everything else."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    cases = "\n".join(
        f'  {name!r}) printf {value!r}"\\n" ;;'.replace("'", '"') for name, value in mapping.items()
    )
    (bin_dir / "hapax-secret").write_text(
        '#!/usr/bin/env bash\ncase "$1" in\n' + cases + f"\n  *) exit {exit_code} ;;\nesac\n",
        encoding="utf-8",
    )
    (bin_dir / "hapax-secret").chmod(0o755)
    return bin_dir


def _run(script: str, *, bin_dir: Path | None, env: dict[str, str] | None = None):
    environment = dict(os.environ)
    if bin_dir is not None:
        environment["PATH"] = f"{bin_dir}{os.pathsep}{environment['PATH']}"
    else:
        # A PATH with no `hapax-secret` on it. It must still contain the standard bin dirs or
        # the test hides `bash` from itself rather than hiding the CLI from the helper.
        environment["PATH"] = str(_EMPTY_BIN)
    environment.update(env or {})
    return subprocess.run(
        [_BASH, "-c", f'set -euo pipefail\n. "{HELPER}"\n{script}'],
        capture_output=True,
        text=True,
        env=environment,
    )


class TestGet:
    def test_a_stored_value_is_printed_without_its_newline(self, tmp_path) -> None:
        bin_dir = _fake_cli(tmp_path, {"demo/alpha": "alpha-value"})
        result = _run("hapax_secret_get demo/alpha", bin_dir=bin_dir)
        assert result.returncode == 0, result.stderr
        assert result.stdout == "alpha-value"

    def test_a_missing_secret_is_quiet_and_non_zero(self, tmp_path) -> None:
        """It composes inside `||` chains, so it must not print on the miss."""
        bin_dir = _fake_cli(tmp_path, {})
        result = _run("hapax_secret_get demo/absent || echo MISS", bin_dir=bin_dir)
        assert "MISS" in result.stdout
        assert result.stderr == ""

    def test_a_failing_cli_is_not_reported_as_success(self, tmp_path) -> None:
        bin_dir = _fake_cli(tmp_path, {}, exit_code=3)
        result = _run(
            "if hapax_secret_get demo/absent; then echo WRONG; else echo OK; fi", bin_dir=bin_dir
        )
        assert "OK" in result.stdout and "WRONG" not in result.stdout

    def test_a_failing_cli_that_still_prints_is_not_reported_as_success(self, tmp_path) -> None:
        """The status check, isolated.

        `local value=$(cmd)` swallows the command's exit status into `local`'s own, so every
        failed read reports success; the assignment in the helper is deliberately split. The
        non-printing failure case above does NOT pin this — the empty-value guard catches it
        either way, so that mutation stayed green. Only a CLI that fails WHILE printing
        separates the two guards, and a partial write on a dying process is exactly the shape
        that produces a truncated credential.
        """
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        (bin_dir / "hapax-secret").write_text(
            "#!/usr/bin/env bash\nprintf 'truncated-val'\nexit 3\n", encoding="utf-8"
        )
        (bin_dir / "hapax-secret").chmod(0o755)
        result = _run(
            "if hapax_secret_get demo/x; then echo WRONG; else echo OK; fi", bin_dir=bin_dir
        )
        assert "OK" in result.stdout, result.stdout
        assert "truncated-val" not in result.stdout

    def test_an_empty_stored_value_does_not_count(self, tmp_path) -> None:
        bin_dir = _fake_cli(tmp_path, {"demo/empty": ""})
        result = _run(
            "if hapax_secret_get demo/empty; then echo WRONG; else echo OK; fi", bin_dir=bin_dir
        )
        assert "OK" in result.stdout


class TestOrFail:
    def test_env_wins_and_the_store_is_not_read(self, tmp_path) -> None:
        bin_dir = _fake_cli(tmp_path, {"demo/alpha": "from-store"})
        result = _run(
            "hapax_secret_or_fail demo/alpha DEMO_ALPHA",
            bin_dir=bin_dir,
            env={"DEMO_ALPHA": "from-env"},
        )
        assert result.stdout == "from-env"

    def test_an_empty_env_var_is_not_a_value(self, tmp_path) -> None:
        bin_dir = _fake_cli(tmp_path, {"demo/alpha": "from-store"})
        result = _run(
            "hapax_secret_or_fail demo/alpha DEMO_ALPHA", bin_dir=bin_dir, env={"DEMO_ALPHA": ""}
        )
        assert result.stdout == "from-store"

    def test_a_miss_exits_two_with_a_next_action_and_no_value(self, tmp_path) -> None:
        bin_dir = _fake_cli(tmp_path, {"demo/other": "SUPER-SECRET"})
        result = _run("hapax_secret_or_fail demo/absent DEMO_ABSENT", bin_dir=bin_dir)
        assert result.returncode == 2
        assert "demo/absent" in result.stderr
        assert "Next action" in result.stderr
        assert "hapax-secret" in result.stderr
        assert "SUPER-SECRET" not in result.stderr

    def test_a_host_without_the_cli_says_so(self, tmp_path) -> None:
        result = _run("hapax_secret_or_fail demo/alpha", bin_dir=None)
        assert result.returncode == 2
        assert "hapax-secret is not on PATH" in result.stderr


class TestInto:
    def test_the_first_resolvable_name_wins(self, tmp_path) -> None:
        bin_dir = _fake_cli(tmp_path, {"github/personal-access-token": "pat-value"})
        result = _run(
            "hapax_secret_into GH_TOKEN github/absent github/personal-access-token; "
            'printf "%s" "${GH_TOKEN:-}"',
            bin_dir=bin_dir,
        )
        assert result.stdout == "pat-value"

    def test_an_already_set_variable_short_circuits(self, tmp_path) -> None:
        bin_dir = _fake_cli(tmp_path, {"demo/alpha": "from-store"})
        result = _run(
            'hapax_secret_into GH_TOKEN demo/alpha; printf "%s" "$GH_TOKEN"',
            bin_dir=bin_dir,
            env={"GH_TOKEN": "already"},
        )
        assert result.stdout == "already"

    def test_nothing_resolvable_returns_non_zero_so_chains_still_work(self, tmp_path) -> None:
        """This replaces `load_first_available_pass_secret` exactly, minus pass — callers
        keep their `|| other_source || exit` chains."""
        bin_dir = _fake_cli(tmp_path, {})
        result = _run("hapax_secret_into GH_TOKEN a/b c/d || echo FELL_THROUGH", bin_dir=bin_dir)
        assert "FELL_THROUGH" in result.stdout


class TestNoPassPath:
    def test_the_helper_invokes_no_pass(self) -> None:
        """Comments are stripped first: this file's header quotes the operator ruling that
        names pass, and a gate that cannot tell a reference-as-the-point from a call would
        force that quote out."""
        code = "\n".join(
            line
            for line in HELPER.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )
        for forbidden in ("pass show", "pass ls", "pass insert", "gopass", "PASSWORD_STORE_DIR"):
            assert forbidden not in code, forbidden


class TestReadVersusGet:
    """`hapax_secret_read` tells EMPTY from ABSENT; `hapax_secret_get` does not, on purpose.

    Two operator actions: look for a secret that was never put, versus re-put one that was
    put wrong. Wiring `hapax-glmcp-claude` to `hapax_secret_get` collapsed its exit 5 and 6
    into 5 — a real regression the exit-code test caught, which is why the two levels exist.
    """

    def test_read_returns_an_empty_value_successfully(self, tmp_path) -> None:
        bin_dir = _fake_cli(tmp_path, {"demo/empty": ""})
        result = _run(
            'if value="$(hapax_secret_read demo/empty)"; then '
            'printf "OK:[%s]" "$value"; else printf "MISS"; fi',
            bin_dir=bin_dir,
        )
        assert result.stdout == "OK:[]", result.stdout

    def test_read_fails_only_when_the_secret_cannot_be_read(self, tmp_path) -> None:
        bin_dir = _fake_cli(tmp_path, {})
        result = _run(
            "if hapax_secret_read demo/absent >/dev/null; then echo OK; else echo MISS; fi",
            bin_dir=bin_dir,
        )
        assert "MISS" in result.stdout

    def test_get_treats_empty_and_absent_alike(self, tmp_path) -> None:
        """The convenience level: most callers only ever want a USABLE value."""
        for mapping in ({"demo/x": ""}, {}):
            bin_dir = _fake_cli(tmp_path, mapping)
            result = _run(
                "if hapax_secret_get demo/x >/dev/null; then echo OK; else echo MISS; fi",
                bin_dir=bin_dir,
            )
            assert "MISS" in result.stdout, mapping

    def test_get_is_built_on_read_not_a_second_implementation(self) -> None:
        code = "\n".join(
            line
            for line in HELPER.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )
        body = code.split("hapax_secret_get() {", 1)[1].split("\n}", 1)[0]
        assert "hapax_secret_read" in body, "get must delegate, not re-derive"
        assert "hapax-secret " not in body, "get must not call the CLI directly"
