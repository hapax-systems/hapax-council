"""`secret_env_from_filestore` must refuse a corrupt blob, not traceback and not skip it.

reins PR 44 makes `FileStore.get` RAISE `SecretIntegrityError` where it used to return
`None`. This script treats `None` as "missing" (fatal for REQUIRED, skipped for OPTIONAL), so
without handling it would either crash with a traceback at boot or — worse for an OPTIONAL
name — sail past a tampered secret as though it were simply absent.

Driven through the real script in a subprocess against a synthetic FileStore with a byte
flipped in the blob. No real secret is read and no value is asserted on.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "secret_env_from_filestore.py"

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
def store_root(tmp_path, monkeypatch):
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
    store.put("orcid-orcid", b"synthetic-optional")
    return root


def _run(store_root: Path, tmp_path: Path, env: dict[str, str] | None = None):
    environment = dict(os.environ)
    environment["REINS_SECRET_STORE"] = str(store_root)
    environment["HAPAX_SECRETS_ENV_PATH"] = str(tmp_path / "hapax-secrets.env")
    environment.update(env or {})
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        env=environment,
        cwd=REPO_ROOT,
    )


def _corrupt(store_root: Path, name: str) -> None:
    """Flip one byte inside the stored blob, leaving the file present and readable."""
    blob = store_root / f"{name}.bin"
    raw = bytearray(blob.read_bytes())
    raw[-1] ^= 0xFF
    blob.write_bytes(bytes(raw))


class TestHappyPath:
    def test_a_clean_store_writes_the_env_file(self, store_root, tmp_path) -> None:
        result = _run(store_root, tmp_path)
        assert result.returncode == 0, result.stderr[-1500:]
        written = tmp_path / "hapax-secrets.env"
        assert written.is_file()
        assert written.stat().st_mode & 0o777 == 0o600


class TestCorruptRequiredSecret:
    def test_it_refuses_instead_of_tracebacking(self, store_root, tmp_path) -> None:
        _corrupt(store_root, "api-openai")
        result = _run(store_root, tmp_path)
        assert result.returncode != 0
        assert "Traceback" not in result.stderr, result.stderr[-1500:]
        assert "integrity_failed" in result.stderr
        assert "api-openai" in result.stderr
        assert "--audit" in result.stderr

    def test_the_last_valid_env_file_survives(self, store_root, tmp_path) -> None:
        """A boot-time unit that empties the environment on a bad blob turns one corrupt
        secret into a whole-stack outage. temp+replace already guarantees this; the point is
        that the integrity path does not bypass it."""
        first = _run(store_root, tmp_path)
        assert first.returncode == 0, first.stderr[-1000:]
        written = tmp_path / "hapax-secrets.env"
        before = written.read_bytes()

        _corrupt(store_root, "api-openai")
        second = _run(store_root, tmp_path)
        assert second.returncode != 0
        assert written.read_bytes() == before, "the previous environment must be untouched"
        assert not list(tmp_path.glob(".*tmp")), "no temp file left behind"


class TestCorruptOptionalSecret:
    def test_a_tampered_optional_secret_is_not_treated_as_absent(
        self, store_root, tmp_path
    ) -> None:
        """The judgement call, and it goes the same way as the Python resolver: absence is
        acceptable for an OPTIONAL name, tampering is not. Skipping a corrupt blob because
        its slot is optional would let a tampered store boot silently — the one outcome an
        integrity check exists to prevent."""
        _corrupt(store_root, "orcid-orcid")
        result = _run(store_root, tmp_path)
        assert result.returncode != 0, result.stdout
        assert "integrity_failed" in result.stderr
        assert "orcid-orcid" in result.stderr


class TestMissingIsStillMissing:
    def test_an_absent_required_secret_still_reports_missing_not_integrity(
        self, store_root, tmp_path
    ) -> None:
        """Absent and tampered need different operator actions: put it, versus audit it."""
        (store_root / "api-openai.bin").unlink()
        result = _run(store_root, tmp_path)
        assert result.returncode != 0
        assert "missing" in result.stderr
        assert "integrity_failed" not in result.stderr

    def test_an_absent_optional_secret_is_still_skipped(self, store_root, tmp_path) -> None:
        (store_root / "orcid-orcid.bin").unlink()
        result = _run(store_root, tmp_path)
        assert result.returncode == 0, result.stderr[-1000:]


class TestTypedErrorPath:
    """The PR 44 path, exercised without needing PR 44 installed.

    The installed reins returns `None` for a corrupt blob, so the `has() and get() is None`
    branch is what fires on this host today. Once PR 44 lands, `get` RAISES instead — a
    different branch, and one that would otherwise ship untested until the day it matters.
    A stub `k0.key_capture` carrying the typed error drives it now.
    """

    def test_a_raised_integrity_error_is_caught_and_named(self, store_root, tmp_path) -> None:
        shim = tmp_path / "shim"
        (shim / "k0").mkdir(parents=True)
        (shim / "k0" / "__init__.py").write_text("", encoding="utf-8")
        (shim / "k0" / "key_capture.py").write_text(
            "from pathlib import Path\n"
            "import os\n"
            "\n"
            "class SecretIntegrityError(Exception):\n"
            "    pass\n"
            "\n"
            "class _Store:\n"
            "    backend_id = 'file'\n"
            "\n"
            "    @property\n"
            "    def root(self):\n"
            "        return Path(os.environ['REINS_SECRET_STORE'])\n"
            "\n"
            "    def has(self, name):\n"
            "        return (self.root / f'{name}.bin').is_file()\n"
            "\n"
            "    def get(self, name):\n"
            "        if name == 'api-openai':\n"
            "            raise SecretIntegrityError('blob failed to verify')\n"
            "        return b'synthetic-value' if self.has(name) else None\n"
            "\n"
            "def default_store():\n"
            "    return _Store()\n",
            encoding="utf-8",
        )
        result = _run(store_root, tmp_path, env={"HAPAX_REINS_API": str(shim)})
        assert result.returncode == 3, (result.returncode, result.stderr[-1200:])
        assert "Traceback" not in result.stderr, result.stderr[-1200:]
        assert "integrity_failed: api-openai" in result.stderr
        assert "--audit" in result.stderr

    def test_the_exit_code_separates_tampering_from_a_missing_secret(
        self, store_root, tmp_path
    ) -> None:
        """3 = audit this store, 2 = put this secret. Same remedy for both would send an
        operator to re-put over a blob whose history nobody has looked at yet."""
        _corrupt(store_root, "api-openai")
        tampered = _run(store_root, tmp_path).returncode

        (store_root / "api-mistral.bin").unlink()
        # restore the corrupt one so only the absent name is at fault
        api = _reins_api()
        if api is None:  # pragma: no cover - fixture already skipped
            pytest.skip("reins API not present")
        from k0.key_capture import default_store

        default_store().put("api-openai", b"synthetic-value")
        absent = _run(store_root, tmp_path).returncode

        assert tampered == 3 and absent == 2, (tampered, absent)
