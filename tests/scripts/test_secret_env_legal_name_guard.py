"""The legal-name guard's binding reaches the publish orchestrator and nothing that renders.

``HAPAX_OPERATOR_NAME`` arms the legal-name guards (the hardening gate's legal_name child,
``omg_referent.safe_render`` and the publication allowlist), and the same variable is the
display name the livestream egress footer renders. The compositor loads the shared
``hapax-secrets.env``, so the name must never be written there. It is projected alone into
``hapax-publish-legal-name-guard.env``, and only the publish orchestrator loads that file; it
is required there, so the orchestrator never runs with the guard unarmed.

Driven through the real script in a subprocess against a synthetic FileStore, and verified by
effect: under the orchestrator's guard file the real gate child rejects a draft carrying the name
and does not report itself unconfigured, and under the compositor's environment the real footer
renders its default. The name below is synthetic; no real secret is read.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "secret_env_from_filestore.py"
UNITS_DIR = REPO_ROOT / "systemd" / "units"
GUARD_FILE = "hapax-publish-legal-name-guard.env"
GUARD_ENTRY = "hapax-operator-legal-name"  # `hapax-secret hapax/operator-legal-name` maps / to -
SYNTHETIC_NAME = "Synthetic Legalname Fixture"

REQUIRED_NAMES = (
    "litellm-master-key",
    "langfuse-public-key",
    "langfuse-secret-key",
    "api-huggingface",
    "api-mistral",
    "api-openai",
)


def _reins_api() -> Path | None:
    for candidate in (
        Path(os.environ.get("HAPAX_REINS_API", "") or "/nonexistent"),
        Path.home() / ".local/share/reins/current/api",
        Path.home() / "projects/reins/api",
    ):
        if (candidate / "k0" / "key_capture.py").is_file():
            return candidate
    return None


@pytest.fixture
def store(tmp_path, monkeypatch):
    api = _reins_api()
    if api is None:
        pytest.skip("reins API not present on this host")
    root = tmp_path / "secrets"
    monkeypatch.setenv("REINS_SECRET_STORE", str(root))
    if str(api) not in sys.path:
        sys.path.insert(0, str(api))
    from k0.key_capture import default_store

    store = default_store()
    for name in REQUIRED_NAMES:
        store.put(name, b"synthetic-value")
    return store


def _run(store, tmp_path: Path) -> subprocess.CompletedProcess:
    environment = dict(os.environ)
    environment["REINS_SECRET_STORE"] = str(store.root)
    environment["HAPAX_SECRETS_ENV_PATH"] = str(tmp_path / "hapax-secrets.env")
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        env=environment,
        cwd=REPO_ROOT,
    )


def test_the_name_is_projected_alone_into_the_guard_file(store, tmp_path) -> None:
    store.put(GUARD_ENTRY, SYNTHETIC_NAME.encode())

    proc = _run(store, tmp_path)

    assert proc.returncode == 0, proc.stderr
    guard = tmp_path / GUARD_FILE
    assert guard.read_text(encoding="utf-8") == f"HAPAX_OPERATOR_NAME={SYNTHETIC_NAME}\n"
    assert stat.S_IMODE(guard.stat().st_mode) == 0o600


def test_the_shared_env_never_carries_the_name(store, tmp_path) -> None:
    store.put(GUARD_ENTRY, SYNTHETIC_NAME.encode())

    proc = _run(store, tmp_path)

    assert proc.returncode == 0, proc.stderr
    shared = (tmp_path / "hapax-secrets.env").read_text(encoding="utf-8")
    assert SYNTHETIC_NAME not in shared
    assert not any(line.startswith("HAPAX_OPERATOR_NAME=") for line in shared.splitlines())


def test_an_absent_entry_removes_a_stale_guard_file(store, tmp_path) -> None:
    stale = tmp_path / GUARD_FILE
    stale.write_text("HAPAX_OPERATOR_NAME=stale\n", encoding="utf-8")

    proc = _run(store, tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert not stale.exists()


def test_an_empty_entry_refuses_and_keeps_both_files(store, tmp_path) -> None:
    store.put(GUARD_ENTRY, b"   \n")
    shared = tmp_path / "hapax-secrets.env"
    guard = tmp_path / GUARD_FILE
    shared.write_text("PRIOR=1\n", encoding="utf-8")
    guard.write_text("HAPAX_OPERATOR_NAME=prior\n", encoding="utf-8")

    proc = _run(store, tmp_path)

    assert proc.returncode == 2
    assert "next action" in proc.stderr.lower()
    assert shared.read_text(encoding="utf-8") == "PRIOR=1\n"
    assert guard.read_text(encoding="utf-8") == "HAPAX_OPERATOR_NAME=prior\n"


@pytest.mark.parametrize("shape", ["symlink-loop", "directory", "dangling-symlink"])
def test_an_entry_not_shown_absent_refuses_and_keeps_every_file(store, tmp_path, shape) -> None:
    # has() is Path.is_file(), which is False for each shape without the entry being absent;
    # only FileNotFoundError on the entry's own path may remove the guard file.
    shared = tmp_path / "hapax-secrets.env"
    guard = tmp_path / GUARD_FILE
    shared.write_text("PRIOR=1\n", encoding="utf-8")
    guard.write_text("HAPAX_OPERATOR_NAME=prior\n", encoding="utf-8")
    blob = store.root / f"{GUARD_ENTRY}.bin"
    if shape == "symlink-loop":
        blob.symlink_to(blob.name)
    elif shape == "directory":
        blob.mkdir()
    else:
        blob.symlink_to("missing-target.bin")

    proc = _run(store, tmp_path)

    assert proc.returncode == 2
    assert f"FileStore entry {GUARD_ENTRY} could not be shown absent" in proc.stderr
    assert shared.read_text(encoding="utf-8") == "PRIOR=1\n"
    assert guard.read_text(encoding="utf-8") == "HAPAX_OPERATOR_NAME=prior\n"


def test_only_the_publish_orchestrator_loads_the_guard_file() -> None:
    loaders = sorted(
        path.name
        for path in UNITS_DIR.iterdir()
        if path.is_file() and GUARD_FILE in path.read_text(encoding="utf-8", errors="replace")
    )
    assert loaders == ["hapax-publish-orchestrator.service"]


def test_the_orchestrator_requires_the_guard_file_and_the_compositor_does_not_load_it() -> None:
    orchestrator = (UNITS_DIR / "hapax-publish-orchestrator.service").read_text(encoding="utf-8")
    # No "-": a missing guard file stops the unit instead of starting it with the guard unarmed.
    assert f"EnvironmentFile=/run/user/%U/{GUARD_FILE}" in orchestrator.splitlines()
    compositor = (UNITS_DIR / "studio-compositor.service").read_text(encoding="utf-8")
    assert GUARD_FILE not in compositor


def _env_from_files(*files: Path) -> dict[str, str]:
    """The variables systemd would load from these EnvironmentFiles (KEY=VALUE lines)."""
    env: dict[str, str] = {}
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key] = value
    return env


def _run_in(env_extra: dict[str, str], code: str, *args: str) -> str:
    """Run code under a clean environment plus env_extra; HAPAX_OPERATOR_NAME only if given."""
    environment = {k: v for k, v in os.environ.items() if k != "HAPAX_OPERATOR_NAME"}
    environment.update(env_extra)
    proc = subprocess.run(
        [sys.executable, "-c", code, *args],
        capture_output=True,
        text=True,
        env=environment,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


# The real gate child on a draft (argv[1]) and on a clean draft; prints decisions and findings.
GATE_PROBE = """
import json, sys
from shared.publication_hardening.gate import PublicationHardeningGate
gate = PublicationHardeningGate()
out = {}
for key, text in (("draft", sys.argv[1]), ("clean", "A clean draft.")):
    result = gate._legal_name_child(text)
    out[key] = {"decision": result.decision.value, "findings": [str(f) for f in result.findings]}
print(json.dumps(out))
"""


def test_the_orchestrator_environment_rejects_a_draft_carrying_the_name(store, tmp_path) -> None:
    """By effect: projection, then the orchestrator's guard file, then the real gate child."""
    store.put(GUARD_ENTRY, SYNTHETIC_NAME.encode())
    assert _run(store, tmp_path).returncode == 0
    before = sorted(p.name for p in tmp_path.iterdir())
    env = _env_from_files(tmp_path / GUARD_FILE)

    out = json.loads(_run_in(env, GATE_PROBE, f"Drafted by {SYNTHETIC_NAME}."))

    assert out["draft"]["decision"] == "reject"
    assert out["clean"]["decision"] == "pass"
    for case in out.values():
        assert not any("legal_name_guard_unconfigured" in f for f in case["findings"])
    assert sorted(p.name for p in tmp_path.iterdir()) == before  # nothing durable written


def test_without_the_guard_file_the_gate_reports_itself_unarmed() -> None:
    out = json.loads(_run_in({}, GATE_PROBE, f"Drafted by {SYNTHETIC_NAME}."))

    assert out["draft"]["decision"] == "pass"  # unarmed: the leak goes through, hence the file
    assert any("legal_name_guard_unconfigured" in f for f in out["clean"]["findings"])


def test_the_compositor_environment_renders_the_default_footer(store, tmp_path) -> None:
    """By effect: the compositor's only EnvironmentFile is the shared env, which lacks the name."""
    store.put(GUARD_ENTRY, SYNTHETIC_NAME.encode())
    assert _run(store, tmp_path).returncode == 0
    env = _env_from_files(tmp_path / "hapax-secrets.env")

    footer = _run_in(
        env,
        "from shared.governance.egress_footer import render_footer_text\n"
        "print(render_footer_text())",
    )

    assert SYNTHETIC_NAME not in footer
    assert "the operator" in footer
