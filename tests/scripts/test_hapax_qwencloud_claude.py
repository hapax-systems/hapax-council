"""scripts/hapax-qwencloud-claude — Claude Code as the plan's listed client, key never on disk or argv."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parents[2] / "scripts" / "hapax-qwencloud-claude"
OFFICIAL = "https://token-plan.ap-southeast-1.maas.aliyuncs.com/apps/anthropic"


@pytest.fixture
def bench(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A PATH with a fake `claude` that records its argv and environment, and a fake `hapax-secret`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "claude-seen.json"
    (bin_dir / "claude").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"json.dump({{'argv': sys.argv[1:], 'env': dict(os.environ)}}, open({str(record)!r}, 'w'))\n"
        "print(json.dumps({'result': 'OK', 'modelUsage': {os.environ.get('ANTHROPIC_MODEL', '?'): {}}}))\n",
        encoding="utf-8",
    )
    (bin_dir / "claude").chmod(0o755)
    (bin_dir / "hapax-secret").write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "--where" ]; then echo filestore; exit 0; fi\n'
        'if [ "$1" = "qwencloud/apikey" ]; then echo "fixture-plan-key-0000"; exit 0; fi\n'
        "exit 1\n",
        encoding="utf-8",
    )
    (bin_dir / "hapax-secret").chmod(0o755)
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path / "real-home"),
        "TMPDIR": str(tmp_path / "tmp"),
    }
    (tmp_path / "real-home").mkdir()
    (tmp_path / "tmp").mkdir()
    return record, env


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(WRAPPER), *args], env=env, capture_output=True, text=True, check=False, timeout=60
    )


def test_the_client_runs_isolated_with_the_key_only_in_its_environment(bench) -> None:
    record, env = bench

    proc = _run(env, "-p", "Reply with exactly: OK", "--output-format", "json")

    assert proc.returncode == 0, proc.stderr
    seen = json.loads(record.read_text())
    assert seen["argv"] == ["-p", "Reply with exactly: OK", "--output-format", "json"]
    assert seen["env"]["ANTHROPIC_BASE_URL"] == OFFICIAL
    assert seen["env"]["ANTHROPIC_AUTH_TOKEN"] == "fixture-plan-key-0000"
    assert seen["env"]["ANTHROPIC_MODEL"] == "qwen3.7-plus"
    assert seen["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "qwen3.7-plus"
    assert seen["env"]["HOME"] != env["HOME"], "the client must not see the real HOME"
    assert not Path(seen["env"]["HOME"]).exists(), "the isolated HOME is removed after the run"
    assert "fixture-plan-key" not in " ".join(seen["argv"])
    assert "fixture-plan-key" not in proc.stderr
    assert "TMPDIR" not in seen["env"] or seen["env"].get("TMPDIR") != env["TMPDIR"]
    assert json.loads(proc.stdout)["result"] == "OK"


def test_check_reports_without_reading_the_key(bench) -> None:
    record, env = bench

    proc = _run(env, "--check")

    assert proc.returncode == 0, proc.stderr
    assert "endpoint " + OFFICIAL in proc.stdout and "qwen3.7-plus" in proc.stdout
    if record.exists():  # the version probe is the only client call --check may make
        seen = json.loads(record.read_text())
        assert seen["argv"] == ["--version"]
        assert "ANTHROPIC_AUTH_TOKEN" not in seen["env"] and "ANTHROPIC_BASE_URL" not in seen["env"]


def test_base_url_and_model_overrides_are_refused_unless_reviewed(bench) -> None:
    record, env = bench

    proc = _run(
        {**env, "HAPAX_QWENCLOUD_ANTHROPIC_BASE_URL": "https://evil.example/anthropic"}, "-p", "x"
    )
    assert proc.returncode == 2 and "refusing base URL" in proc.stderr
    assert not record.exists()

    proc = _run({**env, "HAPAX_QWENCLOUD_MODEL": "gpt-oss-120b"}, "-p", "x")
    assert proc.returncode == 2 and "not in the plan's documented catalogue" in proc.stderr
    assert not record.exists()

    proc = _run({**env, "HAPAX_QWENCLOUD_MODEL": "qwen3-coder-plus"}, "-p", "x")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(record.read_text())["env"]["ANTHROPIC_MODEL"] == "qwen3-coder-plus"


def test_missing_secret_or_client_names_the_remedy(bench, tmp_path: Path) -> None:
    record, env = bench
    (tmp_path / "bin" / "hapax-secret").write_text(
        "#!/usr/bin/env bash\nexit 1\n", encoding="utf-8"
    )

    proc = _run(env, "-p", "x")

    assert proc.returncode == 4 and "store the plan's sk-sp- key" in proc.stderr
    assert not record.exists()
