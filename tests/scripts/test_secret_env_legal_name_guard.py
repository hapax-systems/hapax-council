"""The legal-name guard's binding reaches the publish orchestrator and nothing that renders.

``HAPAX_OPERATOR_NAME`` arms the legal-name guards (the hardening gate's legal_name child,
``omg_referent.safe_render`` and the publication allowlist), and the same variable is the
display name the livestream egress footer renders. The compositor loads the shared
``hapax-secrets.env``, so the name must never be written there. It is projected alone into
``hapax-publish-legal-name-guard.env``, and only the publish orchestrator loads that file.

Driven through the real script in a subprocess against a synthetic FileStore. The name below is
synthetic; no real secret is read.
"""

from __future__ import annotations

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


def test_only_the_publishers_load_the_guard_file() -> None:
    # Publishers scan for the name; nothing that renders a display name may load it.
    loaders = sorted(
        path.name
        for path in UNITS_DIR.iterdir()
        if path.is_file() and GUARD_FILE in path.read_text(encoding="utf-8", errors="replace")
    )
    assert loaders == [
        "hapax-bluesky-post.service",
        "hapax-mastodon-post.service",
        "hapax-publish-orchestrator.service",
    ]


def test_the_orchestrator_loads_the_guard_file_and_the_compositor_does_not() -> None:
    orchestrator = (UNITS_DIR / "hapax-publish-orchestrator.service").read_text(encoding="utf-8")
    assert f"EnvironmentFile=-/run/user/%U/{GUARD_FILE}" in orchestrator.splitlines()
    compositor = (UNITS_DIR / "studio-compositor.service").read_text(encoding="utf-8")
    assert GUARD_FILE not in compositor
