"""The one estate secret resolver: env -> FileStore -> hapax-secret. Never pass.

Operator ruling 2026-09-16: "Pass and gopass should never be used going forward to manage
secrets." This module is the Python half of that; `scripts/lib/secret.sh` is the shell half.

Every test here uses SYNTHETIC values under `REINS_SECRET_STORE=<tmpdir>`. No test reads a
real secret, and no assertion prints a value.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from shared.secrets import (
    SecretIntegrityFailed,
    SecretUnavailable,
    get_secret,
    has_secret,
    list_secret_names,
    put_instruction,
    put_secret,
    reins_api_path,
    secret_store_name,
)


def _install_local_name_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``secret_store_name`` work on CI, which has no reins API.

    Mapping and integrity tests must run against FileStore-local behaviour. They
    must not skip, and they must not fall through to the hapax-secret CLI. The
    live ``hapax_secret.name_of`` stays preferred so the one-implementation pin
    still compares against the real module when it is installed.
    """
    import shared.secrets as secrets

    secrets._name_of.cache_clear()
    if secrets.reins_api_path() is not None:
        return
    api = tmp_path / "reins-api-stub"
    api.mkdir()
    (api / "hapax_secret.py").write_text(
        "import re\n"
        "ALIASES = {\n"
        '    "litellm/master-key": "litellm-master-key",\n'
        '    "langfuse/public-key": "langfuse-public-key",\n'
        '    "langfuse/secret-key": "langfuse-secret-key",\n'
        "}\n"
        '_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")\n'
        "\n"
        "def name_of(raw: str) -> str:\n"
        '    text = raw.strip().lstrip("/")\n'
        "    if not text:\n"
        '        raise ValueError("secret name is empty")\n'
        '    mapped = ALIASES.get(text, text.replace("/", "-"))\n'
        "    if (\n"
        '        mapped in {".", ".."}\n'
        '        or "/" in mapped\n'
        "        or chr(92) in mapped\n"
        "        or _NAME_RE.fullmatch(mapped) is None\n"
        "    ):\n"
        '        raise ValueError("secret name must map to [A-Za-z0-9._-]+")\n'
        "    return mapped\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HAPAX_REINS_API", str(api))
    secrets._name_of.cache_clear()


@pytest.fixture
def local_name_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import shared.secrets as secrets

    installed_stub = secrets.reins_api_path() is None
    _install_local_name_mapping(tmp_path, monkeypatch)
    yield
    secrets._name_of.cache_clear()
    if installed_stub:
        sys.modules.pop("hapax_secret", None)


def _code_only(text: str) -> str:
    """`text` with docstrings and comments removed, so a string gate reads code not prose."""
    import ast
    import io
    import tokenize

    tree = ast.parse(text)
    doc_spans = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                doc_spans.add((body[0].lineno, body[0].end_lineno))
    keep = []
    for index, line in enumerate(text.splitlines(), start=1):
        if any(start <= index <= end for start, end in doc_spans):
            continue
        keep.append(line)
    stripped = "\n".join(keep)
    out = []
    for token in tokenize.generate_tokens(io.StringIO(stripped).readline):
        if token.type == tokenize.COMMENT:
            continue
        out.append(token.string)
    return "\n".join(out)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A real FileStore rooted in tmp_path, seeded through the shipped put path."""
    monkeypatch.setenv("REINS_SECRET_STORE", str(tmp_path / "secrets"))
    api = reins_api_path()
    # A mapping-only HAPAX_REINS_API stub (CI) is not the FileStore module.
    if api is None or not (api / "k0" / "key_capture.py").is_file():
        pytest.skip("reins API not present on this host")
    if str(api) not in sys.path:
        sys.path.insert(0, str(api))
    from k0.key_capture import default_store

    def put(name: str, value: bytes) -> None:
        default_store().put(secret_store_name(name), value)

    return put


class TestResolutionOrder:
    def test_env_wins_over_the_store(self, store, monkeypatch) -> None:
        store("demo/alpha", b"from-store")
        monkeypatch.setenv("DEMO_ALPHA", "from-env")
        assert get_secret("demo/alpha", env="DEMO_ALPHA") == "from-env"

    def test_an_empty_env_var_is_not_a_value(self, store, monkeypatch) -> None:
        """An exported-but-empty variable is the classic silent-empty-credential bug."""
        store("demo/alpha", b"from-store")
        monkeypatch.setenv("DEMO_ALPHA", "")
        assert get_secret("demo/alpha", env="DEMO_ALPHA") == "from-store"

    def test_the_store_is_read_when_no_env_is_named(self, store) -> None:
        store("demo/beta", b"stored-value")
        assert get_secret("demo/beta") == "stored-value"

    def test_a_trailing_newline_is_stripped(self, store) -> None:
        """Consumers interpolate these into headers and argv; `hapax-secret ... | tr -d` is
        the shell idiom and the Python resolver must not be laxer."""
        store("demo/gamma", b"value-with-newline\n")
        assert get_secret("demo/gamma") == "value-with-newline"

    def test_interior_whitespace_survives(self, store) -> None:
        store("demo/delta", b"a b\tc\n")
        assert get_secret("demo/delta") == "a b\tc"


@pytest.mark.usefixtures("local_name_mapping")
class TestNameMapping:
    def test_slashes_become_dashes(self) -> None:
        assert secret_store_name("hapax-reviewer/org") == "hapax-reviewer-org"

    def test_the_three_aliases_are_honoured(self) -> None:
        assert secret_store_name("litellm/master-key") == "litellm-master-key"
        assert secret_store_name("langfuse/public-key") == "langfuse-public-key"
        assert secret_store_name("langfuse/secret-key") == "langfuse-secret-key"

    def test_the_mapping_is_not_a_second_copy(self) -> None:
        """`hapax_secret.name_of` is the one implementation. A private reimplementation would
        be the duplicated exec-auth host derivation again: two copies that drift, and one
        operator-facing name resolving to two different blobs depending which path ran.

        Asserted as behaviour plus absence-of-a-copy rather than function identity, because a
        thin delegating wrapper is fine and `is` would forbid it.
        """
        # Ignore HAPAX_REINS_API (the CI mapping stub). This pin is about the live
        # module; a stub compared to itself would not catch a private copy here.
        live = next(
            (
                candidate
                for candidate in (
                    Path.home() / ".local" / "share" / "reins" / "current" / "api",
                    Path.home() / "projects" / "reins" / "api",
                )
                if (candidate / "hapax_secret.py").is_file()
            ),
            None,
        )
        if live is None:
            pytest.skip("reins API not present on this host")
        if str(live) not in sys.path:
            sys.path.insert(0, str(live))
        import hapax_secret

        for raw in (
            "a/b/c",
            "hapax-reviewer/org",
            "litellm/master-key",
            "langfuse/public-key",
            "langfuse/secret-key",
            "x//y",
            "plain",
        ):
            assert secret_store_name(raw) == hapax_secret.name_of(raw), raw

        source = (Path(__file__).resolve().parents[2] / "shared" / "secrets.py").read_text(
            encoding="utf-8"
        )
        assert 'replace("/", "-")' not in source, "the mapping must be imported, not restated"
        assert "ALIASES" not in source, "the alias table must not be copied here"

    def test_a_traversal_name_cannot_escape_the_store(self) -> None:
        """The safety property is CONTAINMENT, not refusal: `../escape` is neutralised to a
        single safe segment rather than rejected, which is what keeps a blob name from ever
        being a path. Only genuinely unmappable names raise."""
        assert secret_store_name("../escape") == "..-escape"
        assert "/" not in secret_store_name("../escape")
        for hostile in ("..", "", "   ", "a\\b"):
            with pytest.raises(ValueError):
                secret_store_name(hostile)


class TestMissingSecret:
    def test_missing_raises_typed_with_a_next_action(self, store) -> None:
        with pytest.raises(SecretUnavailable) as excinfo:
            get_secret("demo/absent")
        error = excinfo.value
        assert error.name == "demo/absent"
        assert error.legal_next
        assert "hapax-secret" in error.legal_next

    def test_not_required_returns_none(self, store) -> None:
        assert get_secret("demo/absent", required=False) is None

    def test_the_message_never_carries_a_value(self, store) -> None:
        store("demo/secretish", b"SUPER-SECRET-VALUE")
        with pytest.raises(SecretUnavailable) as excinfo:
            get_secret("demo/other-absent")
        assert "SUPER-SECRET-VALUE" not in str(excinfo.value)


class TestNoPassPath:
    def test_the_module_contains_no_pass_invocation(self) -> None:
        """The whole point of the row. A resolver with a pass fallback keeps pass installed.

        Asserted on INVOCATIONS, not on the string `pass` appearing anywhere: this module's
        own docstring quotes the operator ruling that names pass and gopass, and a gate that
        cannot tell a reference-as-the-point from a call would force that quote to be deleted.
        Comments and docstrings are stripped before the check so the assertion is about code.
        """
        source = Path(__file__).resolve().parents[2] / "shared" / "secrets.py"
        code = _code_only(source.read_text(encoding="utf-8"))
        for forbidden in (
            "pass show",
            "pass ls",
            "pass insert",
            "gopass",
            "PassStore",
            "password-store",
            "PASSWORD_STORE_DIR",
        ):
            assert forbidden not in code, forbidden

    def test_a_non_file_backend_refuses_rather_than_falling_back(self, store, monkeypatch) -> None:
        """If `default_store()` ever returns PassStore, this resolver must REFUSE, not use it.
        A fallback that reaches further than the primary is the shape that keeps pass alive."""
        import shared.secrets as secrets

        class _PassLike:
            backend_id = "pass"

            def get(self, name):  # pragma: no cover - must never be called
                raise AssertionError("the resolver must not read a pass backend")

        monkeypatch.setattr(secrets, "_file_store", lambda: _PassLike())
        with pytest.raises(SecretUnavailable) as excinfo:
            get_secret("demo/alpha")
        assert "file" in str(excinfo.value)


class TestSubprocessFallback:
    def test_a_host_without_the_module_shells_out_to_hapax_secret(
        self, tmp_path, monkeypatch
    ) -> None:
        """Hosts without the reins API still resolve, through the CLI that does its own
        name mapping -- so there is still exactly one `name_of` on each path."""
        import shared.secrets as secrets

        fake = tmp_path / "hapax-secret"
        fake.write_text(
            "#!/usr/bin/env bash\n"
            'if [ "$1" = "demo/cli" ]; then printf "cli-value\\n"; exit 0; fi\n'
            "exit 1\n",
            encoding="utf-8",
        )
        fake.chmod(0o755)
        monkeypatch.setattr(secrets, "_file_store", lambda: None)
        monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
        assert get_secret("demo/cli") == "cli-value"

    def test_a_failing_cli_is_a_typed_unavailable_not_a_crash(self, tmp_path, monkeypatch) -> None:
        import shared.secrets as secrets

        fake = tmp_path / "hapax-secret"
        fake.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
        fake.chmod(0o755)
        monkeypatch.setattr(secrets, "_file_store", lambda: None)
        monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
        with pytest.raises(SecretUnavailable):
            get_secret("demo/cli")


@pytest.mark.usefixtures("local_name_mapping")
class TestIntegrityFailureIsNotAbsence:
    """reins PR 44 makes `FileStore.get` RAISE `SecretIntegrityError` where it used to return
    `None`. A corrupt or tampered blob is not a missing secret, and the difference is
    load-bearing: resolution must STOP, not continue to another path.

    A fallback that reaches further than the primary is unsound by construction — a tampered
    blob would be silently replaced by whatever the next path returned, which is the exact
    substitution an attacker wants. Failure handling does less, not more.
    """

    @staticmethod
    def _integrity_store(monkeypatch, error_type):
        import shared.secrets as secrets

        class _Corrupt:
            backend_id = "file"

            def get(self, name):
                raise error_type("integrity check failed")

        monkeypatch.setattr(secrets, "_file_store", lambda: _Corrupt())
        monkeypatch.setattr(secrets, "_integrity_error_types", lambda: (error_type,))
        monkeypatch.setattr(
            secrets,
            "_from_cli",
            lambda name: (_ for _ in ()).throw(
                AssertionError("integrity failure must not fall through to the CLI")
            ),
        )
        return secrets

    def test_a_corrupt_blob_raises_typed_and_names_the_audit(self, monkeypatch) -> None:
        error_type = type("SecretIntegrityError", (Exception,), {})
        self._integrity_store(monkeypatch, error_type)
        with pytest.raises(SecretIntegrityFailed) as excinfo:
            get_secret("demo/corrupt")
        assert excinfo.value.name == "demo/corrupt"
        assert "--audit" in excinfo.value.legal_next

    def test_integrity_failure_does_not_fall_through_to_the_cli(
        self, tmp_path, monkeypatch
    ) -> None:
        """The heart of it. A CLI that would happily answer must never be consulted after an
        integrity failure, or a tampered blob is silently swapped for another path's answer."""
        error_type = type("SecretIntegrityError", (Exception,), {})
        secrets = self._integrity_store(monkeypatch, error_type)
        called: list[str] = []

        def _must_not_run(name: str):
            called.append(name)
            return "cli-value"

        monkeypatch.setattr(secrets, "_from_cli", _must_not_run)
        with pytest.raises(SecretIntegrityFailed):
            get_secret("demo/corrupt")
        assert called == [], "resolution must stop at an integrity failure"

    def test_integrity_failure_raises_even_when_not_required(self, monkeypatch) -> None:
        """`required=False` means "absence is acceptable". Tampering is not absence, and
        returning None for it would present a compromised store as an empty one."""
        error_type = type("SecretIntegrityError", (Exception,), {})
        self._integrity_store(monkeypatch, error_type)
        with pytest.raises(SecretIntegrityFailed):
            get_secret("demo/corrupt", required=False)

    def test_integrity_failure_is_catchable_as_secret_unavailable(self, monkeypatch) -> None:
        """Existing `except SecretUnavailable` handlers keep working; the subclass exists so a
        caller that wants to escalate tampering separately can."""
        error_type = type("SecretIntegrityError", (Exception,), {})
        self._integrity_store(monkeypatch, error_type)
        with pytest.raises(SecretUnavailable):
            get_secret("demo/corrupt")

    def test_the_message_never_carries_the_value(self, monkeypatch) -> None:
        error_type = type("SecretIntegrityError", (Exception,), {})
        self._integrity_store(monkeypatch, error_type)
        with pytest.raises(SecretIntegrityFailed) as excinfo:
            get_secret("demo/corrupt")
        assert "integrity check failed" not in str(excinfo.value), (
            "the backend's own message may quote blob bytes; only the name is safe to echo"
        )

    def test_a_reins_without_the_typed_error_still_resolves(self, store) -> None:
        """Resolved dynamically, so this module works against a reins that predates PR 44 and
        one that has it, with no version check to go stale."""
        import shared.secrets as secrets

        store("demo/normal", b"ok")
        assert get_secret("demo/normal") == "ok"
        assert isinstance(secrets._integrity_error_types(), tuple)


class TestPresenceWriteAndListing:
    """`has_secret`, `put_secret`, `list_secret_names`, `put_instruction` — the verbs the
    consumers need beyond reading: presence probes, bootstrap/consent writes, inventories,
    and the one operator instruction that replaced every `pass insert <name>` string."""

    def test_has_secret_is_presence_without_a_read(self, store) -> None:
        assert has_secret("demo/present") is False
        store("demo/present", b"synthetic")
        assert has_secret("demo/present") is True

    def test_put_secret_round_trips_through_the_one_mapping(self, store) -> None:
        put_secret("demo/written", b"synthetic-value")
        assert get_secret("demo/written") == "synthetic-value"
        assert secret_store_name("demo/written") in list_secret_names()

    def test_put_secret_takes_bytes_only(self, store) -> None:
        with pytest.raises(TypeError):
            put_secret("demo/typed", "not-bytes")  # type: ignore[arg-type]

    def test_put_secret_refuses_a_non_file_backend(self, store, monkeypatch) -> None:
        import shared.secrets as secrets

        class _PassLike:
            backend_id = "pass"

            def put(self, name, value):  # pragma: no cover - must never be called
                raise AssertionError("the resolver must not write a pass backend")

        monkeypatch.setattr(secrets, "_file_store", lambda: _PassLike())
        with pytest.raises(SecretUnavailable):
            put_secret("demo/alpha", b"synthetic")

    def test_put_secret_has_no_cli_leg(self, tmp_path, monkeypatch) -> None:
        """Without the module a put REFUSES. It never pipes a value into a subprocess — the
        CLI's put is an operator TTY dialogue, and a fallback that reaches further than the
        primary is the shape this module exists to forbid."""
        import shared.secrets as secrets

        marker = tmp_path / "cli-was-invoked"
        fake = tmp_path / "hapax-secret"
        fake.write_text(f"#!/usr/bin/env bash\ntouch '{marker}'\nexit 0\n", encoding="utf-8")
        fake.chmod(0o755)
        monkeypatch.setattr(secrets, "_file_store", lambda: None)
        monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
        with pytest.raises(SecretUnavailable):
            put_secret("demo/alpha", b"synthetic")
        assert not marker.exists()

    def test_has_secret_shells_out_where_the_module_is_absent(self, tmp_path, monkeypatch) -> None:
        import shared.secrets as secrets

        fake = tmp_path / "hapax-secret"
        fake.write_text(
            '#!/usr/bin/env bash\n[ "$1" = "--where" ] && [ "$2" = "demo/x" ] && exit 0\nexit 1\n',
            encoding="utf-8",
        )
        fake.chmod(0o755)
        monkeypatch.setattr(secrets, "_file_store", lambda: None)
        monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
        assert has_secret("demo/x") is True
        assert has_secret("demo/y") is False

    def test_put_secret_on_a_read_only_store_is_a_typed_refusal(self, store, tmp_path) -> None:
        """A container mounts the FileStore read-only (the sync pipeline): a put there must refuse
        with the name and the host-side next action, not escape as an OSError."""
        import os

        if os.geteuid() == 0:  # pragma: no cover - root ignores mode bits
            pytest.skip("root can write a mode-500 directory")
        store("demo/present", b"synthetic")  # materialises the root
        root = tmp_path / "secrets"
        root.chmod(0o500)
        try:
            with pytest.raises(SecretUnavailable) as excinfo:
                put_secret("demo/written", b"synthetic")
        finally:
            root.chmod(0o700)
        assert "not writable" in str(excinfo.value)
        assert "synthetic" not in str(excinfo.value)

    def test_list_secret_names_is_names_only_and_sorted(self, store) -> None:
        store("demo/b", b"VALUE-SENTINEL-B")
        store("demo/a", b"VALUE-SENTINEL-A")
        names = list_secret_names()
        assert names == tuple(sorted(names))
        assert "demo-a" in names
        assert "demo-b" in names
        assert not any("SENTINEL" in name for name in names)

    def test_list_secret_names_over_an_explicit_root_needs_no_module(
        self, tmp_path, monkeypatch
    ) -> None:
        import shared.secrets as secrets

        root = tmp_path / "store"
        root.mkdir()
        (root / "demo-b.bin").write_bytes(b"VALUE-SENTINEL")
        (root / "demo-a.bin").write_bytes(b"VALUE-SENTINEL")
        (root / "not-a-blob.txt").write_bytes(b"x")
        (root / "nested").mkdir()
        (root / "nested" / "demo-c.bin").write_bytes(b"x")
        monkeypatch.setattr(secrets, "_file_store", lambda: None)
        assert list_secret_names(root) == ("demo-a", "demo-b")
        assert list_secret_names(tmp_path / "absent") == ()

    def test_list_secret_names_degrades_to_empty_not_a_crash(self, tmp_path, monkeypatch) -> None:
        import shared.secrets as secrets

        monkeypatch.setattr(secrets, "_file_store", lambda: None)
        monkeypatch.setenv("PATH", str(tmp_path))  # no hapax-secret anywhere on PATH
        assert list_secret_names() == ()

    def test_put_instruction_names_the_cli_and_the_name_never_pass(self, monkeypatch) -> None:
        import shared.secrets as secrets

        # Must render on a host with no reins module at all (CI): no name mapping is consulted.
        monkeypatch.setattr(secrets, "reins_api_path", lambda: None)
        text = put_instruction("demo/alpha")
        assert text.startswith("hapax-secret")
        assert "demo/alpha" in text
        assert "pass insert" not in text
        assert "gopass" not in text
