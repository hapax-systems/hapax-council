"""Behavioral coverage for scripts/experiment-check (bash port of the fish original).

The script is a manual pre-SCED validator; nothing invokes it in CI. These tests
pin the port's behavior so the fish-to-bash conversion can't silently rot:
pass/fail counting, exit codes, and the exact report structure.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "experiment-check"


def _stub_dir(tmp_path: Path, *, succeed: bool) -> Path:
    """Stub every command the script calls, answering per-argument."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    def stub(name: str, body: str) -> None:
        target = bin_dir / name
        target.write_text(body, encoding="utf-8")
        target.chmod(0o755)

    gpu_clock = "1800" if succeed else "0"
    gpu_power = "350.00" if succeed else "0"
    quantum = "128" if succeed else "0"
    dirty = "134217728" if succeed else "0"
    dirty_bg = "33554432" if succeed else "0"
    redis_policy = "noeviction" if succeed else "wrong"
    qdrant_state = "healthy" if succeed else "unhealthy"

    stub(
        "nvidia-smi",
        f'#!/usr/bin/env bash\ncase "$*" in\n  *clocks.gr*) echo "{gpu_clock}" ;;\n  *power.limit*) echo "{gpu_power}" ;;\nesac\n',
    )
    stub("pw-cli", f"#!/usr/bin/env bash\necho 'default.clock.quantum = \"{quantum}\"'\n")
    stub(
        "sysctl",
        f'#!/usr/bin/env bash\ncase "$*" in\n  *dirty_background*) echo "{dirty_bg}" ;;\n  *dirty_bytes*) echo "{dirty}" ;;\nesac\n',
    )
    stub(
        "docker",
        f'#!/usr/bin/env bash\ncase "$*" in\n  *inspect*Args*) printf -- "--requirepass\nfallbackpw\n" ;;\n  *redis-cli*) echo "{redis_policy}" ;;\n  *inspect*) echo "{qdrant_state}" ;;\nesac\n',
    )
    stub("uv", '#!/usr/bin/env bash\nif [ "$1" = "run" ]; then shift; exec "$@"; fi\n')
    stub("python", "#!/usr/bin/env bash\necho ok\n")
    stub(
        "systemctl",
        '#!/usr/bin/env bash\ncase "$2" in\n  ollama) echo "Environment=OLLAMA_NUM_PARALLEL=1 OLLAMA_KEEP_ALIVE=24h OLLAMA_CONTEXT_LENGTH=4096" ;;\n  irqbalance) echo "Environment=IRQBALANCE_BANNED_CPUS=0000c000" ;;\n  *) exit 0 ;;\nesac\n',
    )
    return bin_dir


def _run(tmp_path: Path, *, succeed: bool) -> subprocess.CompletedProcess:
    bin_dir = _stub_dir(tmp_path, succeed=succeed)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}"
    return subprocess.run(
        [str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_all_pass_exits_zero_with_full_report(tmp_path):
    result = _run(tmp_path, succeed=True)
    assert "=== Results: 12 passed, 0 failed ===" in result.stdout
    assert "Workstation ready" in result.stdout
    assert result.returncode == 0


def test_failures_exit_one_and_name_the_check(tmp_path):
    result = _run(tmp_path, succeed=False)
    assert result.returncode == 1
    assert "[FAIL]" in result.stdout
    assert "EXPERIMENT NOT READY" in result.stdout
