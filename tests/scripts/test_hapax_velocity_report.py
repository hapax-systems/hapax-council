"""Tests for hapax-velocity-report script and systemd units."""

import json
import os
import pathlib
import subprocess

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-velocity-report"
SERVICE = REPO_ROOT / "systemd" / "units" / "hapax-velocity-report.service"
TIMER = REPO_ROOT / "systemd" / "units" / "hapax-velocity-report.timer"


def _parse_unit(path):
    sections = {}
    current = None
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, {})
        elif "=" in line and current is not None:
            key, _, val = line.partition("=")
            sections[current].setdefault(key.strip(), []).append(val.strip())
    return sections


class TestVelocityScript:
    def test_script_exists_and_executable(self):
        assert SCRIPT.exists()
        assert SCRIPT.stat().st_mode & 0o111

    def test_strict_mode(self):
        assert "set -euo pipefail" in SCRIPT.read_text()

    def test_uses_pass_for_token(self):
        text = SCRIPT.read_text()
        assert "pass show" in text

    def test_writes_json_output(self):
        text = SCRIPT.read_text()
        assert "velocity.json" in text.lower() or "REPORT_JSON" in text

    def test_writes_markdown_output(self):
        text = SCRIPT.read_text()
        assert "velocity.md" in text.lower() or "REPORT_MD" in text

    def test_collects_pr_metrics(self):
        text = SCRIPT.read_text()
        assert "prs_merged" in text or "pr_count" in text

    def test_collects_dora_metrics(self):
        text = SCRIPT.read_text()
        assert "dora" in text.lower()

    def test_bash_syntax_valid(self):
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"


class TestOpenPrCountIsTheWholePopulation:
    """The open-PR figure is measured by running the script, not by reading its source.

    Every other test in this file asserts on `SCRIPT.read_text()`. That is why the previous
    implementation — `per_page=1` with `--jq length`, which returns 1 for any repository with
    at least one open PR — survived: no test ever ran it. Measured 2026-08-23, the report said
    `Open PRs: 1` against a true 52.

    The stub emits 150 PR numbers when `--paginate` is passed and 100 without it, so the three
    implementations are distinguishable by their answer alone:
      old (`per_page=1`, length) -> 1 ;  single page of 100 -> 100 ;  correct -> 150.
    """

    def _run(self, tmp_path):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(
            "#!/usr/bin/env bash\n"
            'args="$*"\n'
            'if [[ "$args" == *"/pulls?state=open"* ]]; then\n'
            "  n=100\n"
            '  [[ "$args" == *"--paginate"* ]] && n=150\n'
            "  for ((i=1;i<=n;i++)); do echo $i; done\n"
            "  exit 0\n"
            "fi\n"
            'if [[ "$args" == *"/pulls?state=closed"* ]]; then echo "[]"; exit 0; fi\n'
            'if [[ "$args" == *"actions/runs"* ]]; then echo 0; exit 0; fi\n'
            'echo ""\n',
            encoding="utf-8",
        )
        gh.chmod(0o755)
        # `pass` must not be consulted: no secret value may be read in a test.
        (bin_dir / "pass").write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
        (bin_dir / "pass").chmod(0o755)

        out = tmp_path / "observatory"
        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["HAPAX_OBSERVATORY_DIR"] = str(out)
        env["GITHUB_TOKEN"] = "stub-not-a-secret"
        result = subprocess.run(
            ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, result.stderr
        written = sorted(out.glob("*-velocity.json"))
        assert written, f"no JSON report written; stderr={result.stderr}"
        return json.loads(written[0].read_text())

    def test_open_pr_count_is_every_open_pr_not_the_page_size(self, tmp_path):
        report = self._run(tmp_path)
        assert report["quality"]["open_prs"] == 150, (
            "the report must count every open PR. 1 means the page size is being measured; "
            "100 means a single unpaginated page is being counted and the figure will cap "
            "silently once the queue passes 100."
        )


class TestVelocitySystemdUnits:
    def test_service_is_oneshot(self):
        assert _parse_unit(SERVICE)["Service"]["Type"] == ["oneshot"]

    def test_service_has_memory_limit(self):
        assert "MemoryMax" in _parse_unit(SERVICE)["Service"]

    def test_service_has_on_failure(self):
        assert "OnFailure" in _parse_unit(SERVICE)["Unit"]

    def test_timer_fires_at_end_of_day(self):
        unit = _parse_unit(TIMER)
        cal = unit["Timer"]["OnCalendar"][0]
        hour = int(cal.split()[-1].split(":")[0])
        assert hour >= 23, f"Timer fires at {hour}:00, should be near end of day"

    def test_timer_is_persistent(self):
        assert _parse_unit(TIMER)["Timer"]["Persistent"] == ["true"]

    def test_timer_has_install(self):
        assert "Install" in _parse_unit(TIMER)
