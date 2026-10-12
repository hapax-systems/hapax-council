"""The scan-before-push hook refuses secret-shaped strings and home paths, passes clean pushes,
and honours only an explicit local exemption. Runs detect-secrets for real (via PATH or uvx)."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import runpy
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-prepush-secret-scan"
ZERO = "0" * 40


def _lock_fixture(name: str, *, opaque: str | None = None) -> str:
    digest = "sha512-" + base64.b64encode(hashlib.sha512(b"registry fixture").digest()).decode()
    if name.endswith("package-lock.json"):
        entry = {"version": "1.0.0", "integrity": digest}
        if opaque is not None:
            del entry["integrity"]
            entry["opaque"] = opaque
        return (
            json.dumps(
                {"lockfileVersion": 3, "packages": {"node_modules/example": entry}}, indent=2
            )
            + "\n"
        )
    text = (
        "lockfileVersion: '9.0'\npackages:\n  example@1.0.0:\n    resolution: {integrity: "
        + digest
        + "}\n"
    )
    if opaque is not None:
        text = (
            "lockfileVersion: '9.0'\npackages:\n  example@1.0.0:\n    opaque: \"" + opaque + '"\n'
        )
    return text


@pytest.mark.parametrize("name", ["hapax-logos/package-lock.json", "hapax-logos/pnpm-lock.yaml"])
def test_lockfile_non_digest_entropy_is_refused(tmp_path, name):
    """A real entropy finding without a vendor/keyword prefix must survive digest admission."""
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    opaque = base64.b64encode(
        hashlib.sha384(b"synthetic opaque credential fixture").digest()
    ).decode()
    tip = _commit(repo, name, _lock_fixture(name, opaque=opaque))
    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert result.returncode == 1, result.stderr
    assert "Base64 High Entropy String" in result.stderr
    assert opaque not in result.stdout + result.stderr


@pytest.mark.parametrize("name", ["hapax-logos/package-lock.json", "hapax-logos/pnpm-lock.yaml"])
def test_lockfile_registry_integrity_passes(tmp_path, name):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    tip = _commit(repo, name, _lock_fixture(name))
    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("name", ["package-lock.json", "pnpm-lock.yaml"])
@pytest.mark.parametrize(
    "case", ["keyword", "vendor", "home", "same-line-opaque", "same-value-other-field"]
)
def test_lockfile_integrity_does_not_hide_other_findings(tmp_path, name, case):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    text = _lock_fixture(name)
    opaque = base64.b64encode(
        hashlib.sha384(b"synthetic opaque credential fixture").digest()
    ).decode()
    key, value = "opaque", opaque
    expected = "Base64 High Entropy String"
    if case == "keyword":
        key, value, expected = "api_" + "key", "not-a-real-credential", "Secret Keyword"
    elif case == "vendor":
        value, expected = "sk-ant-" + "Q" * 40, "vendor-key-shaped"
    elif case == "home":
        value, expected = "/".join(("", "home", "example", "private")), "home path"
    elif case == "same-value-other-field":
        value = "sha512-" + base64.b64encode(hashlib.sha512(b"registry fixture").digest()).decode()
    if name.endswith("json"):
        data = json.loads(text)
        data["packages"]["node_modules/example"][key] = value
        text = json.dumps(data) + "\n"
    else:
        text = text.replace("}\n", ", " + key + ': "' + value + '"}\n')
    tip = _commit(repo, name, text)
    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert result.returncode == 1, result.stderr
    assert expected in result.stderr
    assert value not in result.stdout + result.stderr


@pytest.mark.parametrize("name", ["package-lock.json", "pnpm-lock.yaml"])
@pytest.mark.parametrize(
    "case",
    [
        "wrong-field",
        "wrong-root",
        "wrong-package",
        "wrong-version",
        "wrong-version-type",
        "array-value",
        "escaped-value",
        "non-lockfile",
        "lookalike-path",
        "wrong-length",
        "wrong-algorithm",
        "invalid-padding",
        "duplicate",
        "malformed",
    ],
)
def test_lockfile_integrity_requires_exact_structure(tmp_path, name, case):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    text = _lock_fixture(name)
    if case == "wrong-field":
        text = text.replace("integrity", "opaque")
    elif case == "wrong-root":
        text = text.replace("packages", "unrelated")
    elif case == "wrong-package":
        text = text.replace("node_modules/example", "example").replace("example@1.0.0", "example")
    elif case == "wrong-version":
        text = text.replace('"lockfileVersion": 3', '"lockfileVersion": 99').replace(
            "'9.0'", "'99.0'"
        )
    elif case == "wrong-version-type":
        text = text.replace('"lockfileVersion": 3', '"lockfileVersion": "3"').replace(
            "'9.0'", "9.0"
        )
    elif case == "array-value":
        digest = "sha512-" + base64.b64encode(hashlib.sha512(b"registry fixture").digest()).decode()
        text = (
            text.replace('"' + digest + '"', '["' + digest + '"]')
            if name.endswith("json")
            else text.replace(digest, '["' + digest + '"]')
        )
    elif case == "escaped-value":
        if name.endswith("json"):
            text = text.replace('"sha512-', '"' + chr(92) + "u0073ha512-")
        else:
            digest = (
                "sha512-" + base64.b64encode(hashlib.sha512(b"registry fixture").digest()).decode()
            )
            text = text.replace(digest, '"' + chr(92) + "x73" + digest[1:] + '"')
    elif case == "non-lockfile":
        name = "ordinary." + name.rsplit(".", 1)[-1]
    elif case == "lookalike-path":
        name = "other-" + name
    elif case == "wrong-length":
        text = text.replace("sha512-", "sha512-AAAA")
    elif case == "wrong-algorithm":
        text = text.replace("sha512-", "sha256-")
    elif case == "invalid-padding":
        # Canonical encoding of 64 bytes has four zero trailing bits.
        digest = base64.b64encode(hashlib.sha512(b"registry fixture").digest()).decode()
        text = text.replace(digest, digest[:-3] + "B==")
    elif case == "duplicate":
        if name.endswith("json"):
            text = text.replace('"version": "1.0.0",', '"version": "1.0.0", "version": "2.0.0",')
        else:
            text += "packages: {}\n"
    elif case == "malformed":
        text = text + ("}" if name.endswith("json") else "[bad\n")
    tip = _commit(repo, name, text)
    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    if case in {"duplicate", "malformed"}:
        assert result.returncode == 3, result.stderr
        assert "REFUSED [lockfile-structure]" in result.stderr
    else:
        assert result.returncode == 1, result.stderr
        assert "Base64 High Entropy String" in result.stderr


def test_lockfile_parser_unavailable_refuses(tmp_path, monkeypatch):
    """Losing structural observation must not turn into an entropy exemption."""
    import builtins

    scan = runpy.run_path(str(SCRIPT))
    original_import = builtins.__import__

    def without_yaml(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("fixture parser unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_yaml)
    with pytest.raises(SystemExit) as exc:
        scan["lockfile_detector_text"]("pnpm-lock.yaml", _lock_fixture("pnpm-lock.yaml"))
    assert exc.value.code == 3


def test_package_lock_requires_json_even_when_valid_yaml(tmp_path):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    digest = "sha512-" + base64.b64encode(hashlib.sha512(b"registry fixture").digest()).decode()
    text = "lockfileVersion: 3\npackages:\n  node_modules/example:\n    integrity: " + digest + "\n"
    tip = _commit(repo, "package-lock.json", text)
    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert result.returncode == 3, result.stderr
    assert "REFUSED [lockfile-structure]" in result.stderr


@pytest.mark.parametrize("name", ["package-lock.json", "pnpm-lock.yaml"])
def test_integrity_retains_nonentropy_detectors(tmp_path, name):
    """Even a canonical digest grants only an entropy exemption, not a vendor-key exemption."""
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    original = base64.b64encode(hashlib.sha512(b"registry fixture").digest()).decode()
    payload = base64.b64encode(hashlib.sha512(b"nonentropy fixture").digest()).decode()
    fake = "AKIA" + "Z" * 16
    payload = payload[:7] + "/" + fake + "/" + payload[29:]
    assert base64.b64encode(base64.b64decode(payload, validate=True)).decode() == payload
    tip = _commit(repo, name, _lock_fixture(name).replace(original, payload))
    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert result.returncode == 1, result.stderr
    assert "AWS Access Key" in result.stderr
    assert payload not in result.stdout + result.stderr


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_lockfile_refused(tmp_path, constant):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    text = _lock_fixture("package-lock.json").replace(
        '"lockfileVersion": 3', '"lockfileVersion": 3, "extra": ' + constant
    )
    tip = _commit(repo, "package-lock.json", text)
    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert result.returncode == 3, result.stderr


@pytest.mark.parametrize("name", ["package-lock.json", "pnpm-lock.yaml"])
def test_generated_prefix_cannot_exempt_lockfile(tmp_path, name):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    opaque = base64.b64encode(
        hashlib.sha384(b"synthetic opaque credential fixture").digest()
    ).decode()
    path = "docs/architecture/system-dynamics-map/" + name
    tip = _commit(repo, path, _lock_fixture(name, opaque=opaque))
    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert result.returncode == 1, result.stderr
    assert "Base64 High Entropy String" in result.stderr


@pytest.mark.parametrize("case", ["anchor", "alias", "custom-tag", "block-scalar"])
def test_pnpm_ambiguous_or_relocated_integrity_refused(tmp_path, case):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    name = "pnpm-lock.yaml"
    text = _lock_fixture(name)
    digest = "sha512-" + base64.b64encode(hashlib.sha512(b"registry fixture").digest()).decode()
    if case == "anchor":
        text = text.replace(digest, "&value " + digest)
    elif case == "alias":
        text = "saved: &value '" + digest + "'\n" + text.replace(digest, "*value")
    elif case == "custom-tag":
        text = text.replace(digest, "!opaque " + digest)
    else:
        text = text.replace("{integrity: " + digest + "}", 'integrity: |\n      "' + digest + '"')
        # Resolution must be a mapping; a string resembling its contents is not one.
        text = text.replace("resolution: integrity: |", "resolution: |")
    tip = _commit(repo, name, text)
    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert result.returncode == (1 if case == "block-scalar" else 3), result.stderr


@pytest.mark.parametrize("name", ["package-lock.json", "pnpm-lock.yaml"])
def test_lockfile_digest_copied_to_new_non_digest_field_is_refused(tmp_path, name):
    """Detector deduplication must not attribute the new opaque field to an old digest."""
    repo = _repo(tmp_path)
    original = _lock_fixture(name)
    base = _commit(repo, name, original)
    value = "sha512-" + base64.b64encode(hashlib.sha512(b"registry fixture").digest()).decode()
    if name.endswith("json"):
        data = json.loads(original)
        data["packages"]["node_modules/example"]["opaque"] = value
        changed = json.dumps(data, indent=2) + "\n"
    else:
        changed = original + '    opaque: "' + value + '"\n'
    tip = _commit(repo, name, changed)
    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert result.returncode == 1, result.stderr
    assert "Base64 High Entropy String" in result.stderr


@pytest.mark.parametrize("name", ["package-lock.json", "pnpm-lock.yaml"])
@pytest.mark.parametrize("separator", ["\n", "\r\n", "\r"])
def test_lockfile_digest_restoration_and_regeneration_pass(tmp_path, name, separator):
    repo = _repo(tmp_path)
    original = _lock_fixture(name)
    _commit(repo, name, original)
    base = _commit(repo, name, _lock_fixture(name, opaque="ordinary"))
    restored = _commit(repo, name, ("\n\n" + original).replace("\n", separator))
    result = _run(repo, "origin", f"refs/heads/main {restored} refs/heads/main {base}\n")
    assert result.returncode == 0, result.stderr
    digest = base64.b64encode(hashlib.sha512(b"registry fixture").digest()).decode()
    fresh = base64.b64encode(hashlib.sha512(b"regenerated registry fixture").digest()).decode()
    regenerated = _commit(repo, name, original.replace(digest, fresh).replace("\n", separator))
    result = _run(repo, "origin", f"refs/heads/main {regenerated} refs/heads/main {restored}\n")
    assert result.returncode == 0, result.stderr


pytestmark = pytest.mark.skipif(
    not (shutil.which("detect-secrets") or shutil.which("uvx")),
    reason="needs detect-secrets or uvx on PATH",
)


@pytest.fixture(autouse=True)
def isolated_git(tmp_path, monkeypatch):
    """Never inherit the operator's hooks, signing, Git directory, or config."""
    for key in tuple(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    template = tmp_path / "empty-template"
    template.mkdir()
    monkeypatch.setenv("GIT_TEMPLATE_DIR", str(template))


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("clean\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _commit(repo: Path, name: str, text: str) -> str:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"add {name}")
    return _git(repo, "rev-parse", "HEAD")


def _run(repo: Path, remote: str, refs: str) -> subprocess.CompletedProcess:
    try:
        destination = _git(repo, "remote", "get-url", "--push", remote)
    except subprocess.CalledProcessError:
        destination = (
            ""  # Direct protocol tests with no configured destination scan conservatively.
        )
    return subprocess.run(
        [sys.executable, str(SCRIPT), remote, destination],
        cwd=repo,
        input=refs,
        capture_output=True,
        text=True,
        timeout=900,
    )


def test_refuses_secret_and_home_path_and_names_types_only(tmp_path):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    key = "AKIA" + "ZZZZAAAAQQQQ1234"  # AWS access-key shape; not a real key
    home = "/".join(("", "home", "someone", ".cache", "x.log"))
    tip = _commit(repo, "cfg.py", f'AWS_KEY = "{key}"\nLOG = "{home}"\n')
    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert r.returncode == 1, r.stderr
    assert "secret-shaped: cfg.py" in r.stderr
    assert "home path in 1 added line(s): cfg.py" in r.stderr
    assert key not in r.stderr and key not in r.stdout  # types and counts only, never values
    assert "Remedy:" in r.stderr


def test_clean_companion_cannot_hide_css_aws_key(tmp_path):
    """The real CLI must give the same refusal with one file and two files."""
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    key = "AKIA" + "Z" * 16
    tip = _commit(repo, "probe.css", f'TOKEN = "{key}"\n')
    single = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert single.returncode == 1, single.stderr
    assert "AWS Access Key" in single.stderr

    (repo / "README.md").write_text("clean companion\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--amend", "--no-edit", "-q")
    tip = _git(repo, "rev-parse", "HEAD")
    multiple = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert multiple.returncode == 1, (multiple.returncode, multiple.stderr)
    assert "secret-shaped: probe.css" in multiple.stderr
    assert "AWS Access Key" in multiple.stderr
    for result in (single, multiple):
        assert key not in result.stdout and key not in result.stderr


def test_clean_push_passes(tmp_path):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    tip = _commit(repo, "notes.md", "nothing secret here; relative paths only: ~/.cache/x\n")
    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize(
    "filename", ["probe.yaml", "probe.yml", "probe.eyaml", "probe.ini", "probe.py"]
)
@pytest.mark.parametrize("companion", [False, True], ids=["single-file", "multiple-files"])
def test_real_detector_transformers_cannot_hide_comments(tmp_path, filename, companion):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    key = "AKIA" + "Z" * 16
    if companion:
        (repo / "README.md").write_text("clean companion\n")
    prefix = (
        "label: ordinary\n" if filename.endswith(("yaml", "yml")) else "[section]\nlabel=ordinary\n"
    )
    tip = _commit(repo, filename, prefix + f"# {key}\n")

    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert result.returncode == 1, (result.returncode, result.stderr)
    assert f"secret-shaped: {filename}" in result.stderr
    assert "AWS Access Key" in result.stderr
    assert key not in result.stdout and key not in result.stderr


@pytest.mark.parametrize(
    "case", ["key", "sequence", "duplicate-key", "block-scalar", "ini-section"]
)
def test_real_detector_transformers_preserve_all_added_content(tmp_path, case):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    key = "AKIA" + "Z" * 16
    content = {
        "key": f"label: ordinary\n{key}: ordinary\n",
        "sequence": f"label: ordinary\nitems:\n  - {key}\n",
        "duplicate-key": f"label: {key}\nlabel: ordinary\n",
        "block-scalar": f"label: |\n  ordinary\n  {key}\n",
        "ini-section": f"[{key}]\nlabel=ordinary\n",
    }[case]
    filename = "probe.ini" if case == "ini-section" else "probe.yaml"
    (repo / "README.md").write_text("clean companion\n")
    tip = _commit(repo, filename, content)

    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert result.returncode == 1, result.stderr
    assert f"secret-shaped: {filename}" in result.stderr
    assert "AWS Access Key" in result.stderr
    assert key not in result.stdout and key not in result.stderr


@pytest.mark.parametrize("filename", ["probe.yaml", "probe.ini"])
@pytest.mark.parametrize("policy", ["unchanged", "inline-pragma", "nextline-pragma"])
def test_raw_scan_preserves_added_line_and_pragma_policy(tmp_path, filename, policy):
    repo = _repo(tmp_path)
    key = "AKIA" + "Z" * 16
    prefix = "label: ordinary\n" if filename.endswith("yaml") else "[section]\nlabel=ordinary\n"
    secret_line = f"# {key}\n"
    if policy == "unchanged":
        _commit(repo, filename, prefix + secret_line)
    base = _git(repo, "rev-parse", "HEAD")
    if policy == "inline-pragma":
        secret_line = f"# {key}  # pragma: allowlist secret\n"
    elif policy == "nextline-pragma":
        secret_line = "# pragma: allowlist nextline secret\n" + secret_line
    (repo / "README.md").write_text("clean companion\n")
    tip = _commit(repo, filename, prefix + secret_line + "# ordinary added comment\n")

    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert result.returncode == 0, result.stderr
    assert key not in result.stdout and key not in result.stderr


def test_multifile_scan_reports_every_secret_file(tmp_path):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    key = "AKIA" + "Z" * 16
    files = ["00-probe.css", "nested/probe.svg", "probe.lock", ".hidden/probe.txt"]
    for filename in files:
        path = repo / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'TOKEN = "{key}"\n')
    tip = _commit(repo, "README.md", "clean companion\n")

    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert result.returncode == 1, result.stderr
    for filename in files:
        assert f"secret-shaped: {filename}" in result.stderr
    assert result.stderr.count("AWS Access Key") == len(files)
    assert key not in result.stdout and key not in result.stderr


def test_real_detector_scans_symlink_blob_with_companion(tmp_path):
    """A dangling symlink's committed bytes must be scanned as regular staged text."""
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    key = "AKIA" + "Z" * 16
    (repo / "probe.svg").symlink_to(key)
    tip = _commit(repo, "README.md", "clean companion\n")

    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert result.returncode == 1, result.stderr
    assert "secret-shaped: probe.svg" in result.stderr
    assert "AWS Access Key" in result.stderr
    assert key not in result.stdout and key not in result.stderr


@pytest.mark.parametrize(
    "failure", ["bad-version", "missing-version", "config-rejected", "invalid-json"]
)
@pytest.mark.parametrize("raw_view", [False, True], ids=["normal-view", "raw-view"])
def test_later_file_detector_failure_refuses_without_retry(
    tmp_path, monkeypatch, failure, raw_view
):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "README.md").write_text("clean companion\n")
    tip = _commit(repo, "last.css", "ordinary content\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "invocations.jsonl"
    payload = {"version": "1.5.0", "results": {}}
    if failure == "bad-version":
        payload["version"] = "1.6.0"
    elif failure == "missing-version":
        del payload["version"]
    output = "invalid-json" if failure == "invalid-json" else json.dumps(payload)
    _executable(
        bin_dir / "detect-secrets",
        f"#!{sys.executable}\n"
        "import json, pathlib, sys\n"
        "files = sorted(p for p in pathlib.Path('.').rglob('*') if p.is_file())\n"
        "raw = any(p.read_bytes().startswith(b'@hapax-prepush-raw@') for p in files)\n"
        f"with open({str(log)!r}, 'a') as log:\n"
        "    log.write(json.dumps([str(p) for p in files]) + '\\n')\n"
        f"if pathlib.Path('last.css') in files and raw == {raw_view!r}:\n"
        f"    print({output!r})\n"
        f"    sys.exit({2 if failure == 'config-rejected' else 0})\n"
        "print(json.dumps({'version': '1.5.0', 'results': {}}))\n",
    )
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])

    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert result.returncode == 3, result.stderr
    kind = (
        "detector-version"
        if "version" in failure
        else ("detector-failed" if failure == "config-rejected" else "detector-result")
    )
    assert f"REFUSED [{kind}]" in result.stderr
    assert "Remedy:" in result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert calls == [["README.md"], ["README.md"]] + [["last.css"]] * (2 if raw_view else 1)


@pytest.mark.parametrize(
    "filename",
    [
        pytest.param(":(exclude)*", id="exclude-magic"),
        pytest.param(":!*.txt", id="exclude-shorthand"),
        pytest.param(":/probe.txt", id="top-magic"),
        pytest.param(":(glob)probe*.txt", id="glob-magic"),
        pytest.param("probe*.txt", id="asterisk"),
        pytest.param("probe?.txt", id="question-mark"),
        pytest.param("probe[ab].txt", id="brackets"),
        pytest.param("--probe.txt", id="leading-dash"),
    ],
)
def test_committed_pathspec_filenames_are_literal_and_refused(tmp_path, monkeypatch, filename):
    """Scan each committed filename exactly, including names that Git treats as patterns."""
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    # In the same commit, add clean files that magic/glob pathspecs could select.
    # Refusal alone would miss glob widening: it must not pollute this file's lines.
    for companion in ("probe.txt", "probea.txt"):
        (repo / companion).write_text("unrelated added content\n")
    key = "AKIA" + "Z" * 16
    vendor = "sk-ant-" + "a" * 32
    home = "/home/" + "synthetic-operator/private"
    lines = [f'TOKEN = "{key}"', f'provider = "{vendor}"', f'archive = "{home}"']
    tip = _commit(repo, filename, "\n".join(lines) + "\n")

    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert result.returncode == 1, result.stderr
    assert "REFUSED" in result.stderr
    assert f"secret-shaped: {filename}" in result.stderr
    assert "AWS Access Key" in result.stderr
    assert f"vendor-key-shaped in 1 added line(s): {filename}" in result.stderr
    assert f"home path in 1 added line(s): {filename}" in result.stderr
    for value in (key, vendor, home):
        assert value not in result.stdout and value not in result.stderr

    scanner = runpy.run_path(str(SCRIPT))
    monkeypatch.chdir(repo)
    assert scanner["added_lines"](base, tip, [filename]) == {filename: list(enumerate(lines, 1))}


@pytest.mark.parametrize(
    "filename",
    [
        pytest.param("probe.css", id="is_non_text_file-css"),
        pytest.param("probe.svg", id="is_non_text_file-svg"),
        pytest.param("probe.lock", id="is_non_text_file-lock"),
        pytest.param("probe.png", id="is_non_text_file-utf8-png"),
        pytest.param("package-lock.json", id="is_lock_file-package"),
        pytest.param("nested/Cartfile.resolved", id="is_lock_file-cartfile"),
        pytest.param("swagger-ui.html", id="is_swagger_file-name"),
        pytest.param("swagger/config.txt", id="is_swagger_file-directory"),
    ],
)
@pytest.mark.parametrize("content", ["aws", "keyword", "clean", "pragma"])
@pytest.mark.parametrize("companions", [0, 1, 4], ids=["single-file", "two-files", "five-files"])
def test_real_detector_filename_filters_cannot_exempt_text(tmp_path, filename, content, companions):
    """File format guesses are not permission to omit committed UTF-8 text."""
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    if content in {"aws", "pragma"}:
        fake = "AKIA" + "Z" * 16
        line = f'TOKEN = "{fake}"'
        kind = "AWS Access Key"
    else:
        fake = "quartz-mango-bicycle"
        line = f'password = "{fake}"' if content == "keyword" else "ordinary text"
        kind = "Secret Keyword"
    if content == "pragma":
        line += "  # pragma: allowlist secret"
    if filename == "package-lock.json":
        # The lockfile has to be valid JSON before its structure can be observed.
        fields = {
            "password" if content == "keyword" else "opaque": fake
            if content != "clean"
            else "ordinary"
        }
        if content == "pragma":
            fields["_comment"] = "pragma: allowlist secret"
        line = json.dumps(fields)
    for index in range(companions):
        (repo / f"companion-{index}.md").write_text("clean companion\n")
    tip = _commit(repo, filename, line + "\n")

    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    # JSON has no comment pragma; an arbitrary _comment property grants nothing.
    dirty = content not in {"clean", "pragma"} or (
        filename == "package-lock.json" and content == "pragma"
    )
    assert result.returncode == (1 if dirty else 0), result.stderr
    if dirty:
        assert f"secret-shaped: {filename}" in result.stderr
        assert kind in result.stderr
        assert "REFUSED" in result.stderr
    assert fake not in result.stdout and fake not in result.stderr


@pytest.mark.parametrize(
    "line,kind",
    [
        pytest.param(
            'token = fetch("' + "AKIA" + "Z" * 16 + '")',
            "AWS Access Key",
            id="is_indirect_reference",
        ),
        pytest.param(
            'password = "abcdefghijklmnop"',  # pragma: allowlist secret
            "Secret Keyword",
            id="is_sequential_string",
        ),
        pytest.param(
            'password = "7d3812ce-894b-467f-afe2-038914fed9ab"',  # pragma: allowlist secret
            "Secret Keyword",
            id="is_potential_uuid",
        ),
        pytest.param(
            'id = "zxCBVnmlk09876poiuyTREWQ43215asdfg"',  # pragma: allowlist secret
            "Base64 High Entropy String",
            id="is_likely_id_string",
        ),
        pytest.param(
            'url = "https://probe:{quartz-mango-bicycle}@example.invalid"',  # pragma: allowlist secret
            "Basic Auth Credentials",
            id="is_templated_secret",
        ),
        pytest.param(
            'password = "937102648509"',  # pragma: allowlist secret
            "Secret Keyword",
            id="is_not_alphanumeric_string",
        ),
    ],
)
@pytest.mark.parametrize("companion", [False, True], ids=["single-file", "multiple-files"])
def test_real_detector_content_filters_cannot_exempt_findings(tmp_path, line, kind, companion):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    if companion:
        (repo / "README.md").write_text("clean companion\n")
    # A known source extension avoids the eager INI transformer, which quotes
    # apparent function calls in unknown file types and masks the reference filter.
    tip = _commit(repo, "probe.py", line + "\n")

    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert result.returncode == 1, result.stderr
    assert "REFUSED" in result.stderr
    assert "secret-shaped: probe.py" in result.stderr
    assert kind in result.stderr
    assert line not in result.stdout and line not in result.stderr


@pytest.mark.parametrize(
    "fake",
    ["fixture-candidate", "$fixture-candidate"],
    ids=["is_ignored_due_to_verification_policies", "is_prefixed_with_dollar_sign"],
)
@pytest.mark.parametrize("companion", [False, True], ids=["single-file", "multiple-files"])
def test_real_detector_filters_cannot_discard_plugin_findings(
    tmp_path, monkeypatch, fake, companion
):
    """Exercise the real CLI's filter pipeline with an offline verification result.

    The extension supplies a dollar-prefixed candidate because 1.5.0's bundled
    regexes do not emit that shape. No scanner or filter output is mocked.
    """
    plugin = tmp_path / "fixture_detector.py"
    plugin.write_text(
        "import re\n"
        "from detect_secrets.plugins.base import RegexBasedDetector\n"
        "from detect_secrets.constants import VerifiedResult\n"
        "class FixtureDetector(RegexBasedDetector):\n"
        "    secret_type = 'Fixture Credential'\n"  # pragma: allowlist secret
        "    denylist = [re.compile(r'\\$?fixture-candidate')]\n"
        "    def verify(self, secret):\n"
        "        return VerifiedResult.VERIFIED_FALSE\n"
    )
    detector = shutil.which("detect-secrets")
    command = [detector] if detector else ["uvx", "detect-secrets"]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    wrapper = bin_dir / "detect-secrets"
    wrapper.write_text(
        "#!/bin/sh\nexec "
        + shlex.join(command)
        + ' "$@" --plugin '
        + shlex.quote(str(plugin))
        + "\n"
    )
    wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    if companion:
        (repo / "README.md").write_text("clean companion\n")
    tip = _commit(repo, "probe.txt", fake + "\n")

    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert result.returncode == 1, result.stderr
    assert "REFUSED" in result.stderr
    assert "Fixture Credential" in result.stderr
    assert fake not in result.stdout and fake not in result.stderr


def test_intermediate_commit_finding_is_scanned_even_when_tip_removes_it(tmp_path):
    """Every commit transferred by the push is scanned, not only the base-to-tip diff."""
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    fake = "AKIA" + "QWERASDFZXCV1234"  # AWS access-key shape; obviously not a real key
    _commit(repo, "transient.txt", f"AWS_ACCESS_KEY_ID={fake}\n")
    tip = _commit(repo, "transient.txt", "redacted before branch tip\n")

    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert r.returncode == 1, r.stderr
    assert "secret-shaped: transient.txt" in r.stderr
    assert fake not in r.stderr and fake not in r.stdout


def test_detect_secrets_scans_a_filename_containing_whitespace(tmp_path):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    fake = "AKIA" + "MNBVCXZLKJHG1234"  # AWS access-key shape; obviously not a real key
    tip = _commit(repo, "leak file.txt", f"AWS_ACCESS_KEY_ID={fake}\n")

    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert r.returncode == 1, r.stderr
    assert "secret-shaped: leak file.txt" in r.stderr
    assert fake not in r.stderr and fake not in r.stdout


def test_single_backslash_filename_is_refused_before_detector_can_skip_it(tmp_path):
    """One changed file reaches detect-secrets' special single-file scan branch."""
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    filename = r"probe\name.txt"
    key = "AKIA" + "Z" * 16
    tip = _commit(repo, filename, f'TOKEN = "{key}"\n')

    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert result.returncode == 3, result.stderr
    assert "REFUSED [unsupported-filename]" in result.stderr
    assert f"unscanned content: {ascii(filename)}" in result.stderr
    assert "Remedy: rename" in result.stderr
    assert "amend/rebase" in result.stderr
    assert key not in result.stdout and key not in result.stderr


@pytest.mark.parametrize(
    "filename",
    [
        pytest.param(r"\probe.txt", id="leading-backslash"),
        pytest.param(r"dir\name/probe.txt", id="directory-backslash"),
        pytest.param("probe\\\nname.txt", id="backslash-newline"),
    ],
)
@pytest.mark.parametrize("companion", [False, True], ids=["single-file", "multiple-files"])
def test_backslash_names_are_refused_even_for_clean_content(tmp_path, filename, companion):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    if companion:
        (repo / "companion.txt").write_text("ordinary companion content\n")
    tip = _commit(repo, filename, "ordinary content\n")

    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert result.returncode == 3, result.stderr
    assert "REFUSED [unsupported-filename]" in result.stderr
    assert f"unscanned content: {ascii(filename)}" in result.stderr
    assert "Remedy: rename" in result.stderr
    assert "amend/rebase" in result.stderr
    assert len(result.stderr.splitlines()) == 3  # Control characters stay escaped.


@pytest.mark.parametrize(
    "filename",
    ["./probe.txt", "dir//probe.txt", "../probe.txt", "/probe.txt", "dir/../probe.txt"],
    ids=["dot-component", "empty-component", "parent-component", "absolute", "internal-parent"],
)
def test_unmappable_staging_paths_are_refused_before_reading_content(monkeypatch, capsys, filename):
    scanner = runpy.run_path(str(SCRIPT))

    def unexpected_read(*args, **kwargs):
        pytest.fail("unsupported staging paths must be refused before reading content")

    monkeypatch.setattr(subprocess, "run", unexpected_read)
    with pytest.raises(SystemExit) as error:
        scanner["scan_with_detector"]("unused-tip", [filename], {filename: [(1, "ordinary")]})
    assert error.value.code == 3
    diagnostic = capsys.readouterr().err
    assert "REFUSED [unsupported-filename]" in diagnostic
    assert f"unscanned content: {ascii(filename)}" in diagnostic
    assert "Remedy: rename" in diagnostic


@pytest.mark.parametrize(
    "filename",
    [
        pytest.param("-probe.txt", id="leading-dash"),
        pytest.param("--probe.txt", id="double-dash"),
        pytest.param("probe\nname.txt", id="newline"),
        pytest.param("probe\rname.txt", id="carriage-return"),
        pytest.param("probe\r\nname.txt", id="crlf"),
        pytest.param("probe\tname.txt", id="tab"),
        pytest.param("probe\vname.txt", id="vertical-tab"),
        pytest.param("probe\fname.txt", id="form-feed"),
        pytest.param("probe\x1cname.txt", id="file-separator"),
        pytest.param("probe\x1dname.txt", id="group-separator"),
        pytest.param("probe\x1ename.txt", id="record-separator"),
        pytest.param("probe\x85name.txt", id="next-line"),
        pytest.param("probe\u2028name.txt", id="line-separator"),
        pytest.param("probe\u2029name.txt", id="paragraph-separator"),
        pytest.param("dir/name.txt", id="forward-slash"),
        pytest.param("probe\u2215name.txt", id="division-slash"),
        pytest.param("probe\uff0fname.txt", id="fullwidth-slash"),
        pytest.param("probe\uff3cname.txt", id="fullwidth-backslash"),
        pytest.param(".probe.txt", id="dotfile"),
        pytest.param("probe.txt ", id="trailing-space"),
        pytest.param(os.fsdecode(b"probe\xffname.txt"), id="non-utf8-filename"),
    ],
)
@pytest.mark.parametrize("companion", [False, True], ids=["single-file", "multiple-files"])
def test_real_detector_scans_supported_filename_separators(tmp_path, filename, companion):
    """An AWS-only finding must survive literal staging with either file count."""
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    if companion:
        (repo / "README.md").write_text("clean companion\n")
    key = "AKIA" + "Z" * 16
    tip = _commit(repo, filename, f'TOKEN = "{key}"\n')

    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert result.returncode == 1, result.stderr
    assert "REFUSED" in result.stderr
    assert "AWS Access Key" in result.stderr
    assert key not in result.stdout and key not in result.stderr


def test_detect_secrets_staging_preserves_distinct_repository_paths(tmp_path):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    fake = "AKIA" + "POIUYTREWQLK1234"  # AWS access-key shape; obviously not a real key
    (repo / "a").mkdir()
    (repo / "a" / "b").write_text(f"AWS_ACCESS_KEY_ID={fake}\n")
    (repo / "a__b").write_text("benign content that must not overwrite a/b\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add collision pair")
    tip = _git(repo, "rev-parse", "HEAD")

    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert r.returncode == 1, r.stderr
    assert "secret-shaped: a/b" in r.stderr
    assert fake not in r.stderr and fake not in r.stdout


@pytest.mark.parametrize("separator", ["\r", "\r\n", "\r\n\r"], ids=["cr", "crlf", "mixed"])
def test_real_detector_maps_carriage_returns_to_added_git_lines(tmp_path, separator):
    repo = _repo(tmp_path)
    base = _commit(repo, "carriage.txt", f"prefix{separator}")
    key = "AKIA" + "ZXCVBNMASDFG1234"  # pragma: allowlist secret
    content = f"prefix{separator}AWS_ACCESS_KEY_ID={key}\r\n"
    tip = _commit(repo, "carriage.txt", content)
    expected_deletions = int(separator != "\r\n")
    assert _git(repo, "diff", "--numstat", base, tip) == f"1\t{expected_deletions}\tcarriage.txt"

    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert result.returncode == 1, result.stderr
    assert "secret-shaped: carriage.txt" in result.stderr
    assert "AWS Access Key" in result.stderr
    assert "Remedy: remove or redact" in result.stderr
    assert key not in result.stdout and key not in result.stderr


@pytest.mark.parametrize("separator", ["\r", "\r\n"], ids=["cr", "crlf"])
def test_real_detector_carriage_returns_do_not_flag_unchanged_git_lines(tmp_path, separator):
    repo = _repo(tmp_path)
    key = "AKIA" + "ZXCVBNMASDFG1234"  # pragma: allowlist secret
    existing = f"prefix{separator}AWS_ACCESS_KEY_ID={key}\r\n"
    base = _commit(repo, "existing.txt", existing)
    tip = _commit(repo, "existing.txt", existing + "ordinary added line\r\n")

    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert result.returncode == 0, result.stderr
    assert key not in result.stdout and key not in result.stderr


@pytest.mark.parametrize("existing_accent", [False, True], ids=["new-file", "existing-accent"])
def test_real_detector_refuses_non_utf8_text(tmp_path, existing_accent):
    repo = _repo(tmp_path)
    path = repo / "latin1.txt"
    accent = b"caf\xe9\n"
    if existing_accent:
        path.write_bytes(accent)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "existing Latin-1 text")
    base = _git(repo, "rev-parse", "HEAD")
    key = "AKIA" + "ZXCVBNMASDFG1234"  # pragma: allowlist secret
    path.write_bytes(accent + f"AWS_ACCESS_KEY_ID={key}\n".encode())
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add synthetic credential to Latin-1 text")
    tip = _git(repo, "rev-parse", "HEAD")
    assert _git(repo, "diff", "--numstat", base, tip) == (
        f"{1 if existing_accent else 2}\t0\tlatin1.txt"
    )

    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert result.returncode == 3, result.stderr
    assert "committed content is not valid UTF-8" in result.stderr
    assert "unscanned content: latin1.txt" in result.stderr
    assert "Remedy: convert the file to UTF-8 or remove it" in result.stderr
    assert "amend/rebase" in result.stderr
    assert key not in result.stdout and key not in result.stderr
    assert "caf" not in result.stderr


def test_git_binary_classification_refuses_and_names_unscannable_file(tmp_path, monkeypatch):
    """A binary diff has no added-line hunks, so the hook must refuse it explicitly."""
    fake_bin = tmp_path / "detector-bin"
    fake_bin.mkdir()
    fake_detector = fake_bin / "detect-secrets"
    fake_detector.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' \'{"version": "1.5.0", "results": {}}\'\n'
    )
    fake_detector.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")

    repo = _repo(tmp_path)
    base = _commit(repo, ".gitattributes", "*.bin binary\n")
    payload = (  # pragma: allowlist secret
        "path " + "/".join(("", "home", "someone", "private"))
    ).encode() + b"\0"
    (repo / "payload.bin").write_bytes(payload)
    _git(repo, "add", "payload.bin")
    _git(repo, "commit", "-q", "-m", "add binary-classified payload")
    tip = _git(repo, "rev-parse", "HEAD")

    assert _git(repo, "diff", "--numstat", base, tip) == "-\t-\tpayload.bin"
    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert r.returncode == 1, r.stderr
    assert "unscannable binary content: payload.bin" in r.stderr
    assert payload.decode(errors="ignore") not in r.stderr


def test_vendor_key_prefix_honours_installed_inline_pragma(tmp_path, monkeypatch):
    """The independent vendor predicate still refuses keys detect-secrets does not flag."""
    fake_bin = tmp_path / "detector-bin"
    fake_bin.mkdir()
    fake_detector = fake_bin / "detect-secrets"
    fake_detector.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' \'{"version": "1.5.0", "results": {}}\'\n'
    )
    fake_detector.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")

    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    fake = "sk-ant-" + "api03-" + "Q" * 40  # shape only; not a key
    tip = _commit(repo, "env.txt", f"ANTHROPIC_API_KEY={fake}\n")
    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert r.returncode == 1, r.stderr
    assert "vendor-key-shaped in 1 added line(s): env.txt" in r.stderr
    assert fake not in r.stderr
    # Preserve the installed hook's explicit false-positive pragma policy.
    tip2 = _commit(repo, "env.txt", f"EXAMPLE={fake}  # pragma: allowlist secret\n")
    r2 = _run(repo, "origin", f"refs/heads/main {tip2} refs/heads/main {tip}\n")
    assert r2.returncode == 0, r2.stderr
    assert fake not in r2.stderr and fake not in r2.stdout


def test_detector_nonzero_exit_with_valid_json_refuses_push(tmp_path, monkeypatch):
    """A parseable detector payload is not a completed scan when the process failed."""
    fake_bin = tmp_path / "detector-bin"
    fake_bin.mkdir()
    fake_detector = fake_bin / "detect-secrets"
    fake_detector.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' \'{"version": "1.5.0", "results": {}}\'\nexit 9\n'
    )
    fake_detector.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")

    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    tip = _commit(repo, "scan-me.txt", "ordinary content\n")

    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert r.returncode == 3, r.stderr
    assert "detect-secrets failed with exit status 9" in r.stderr


def test_detector_json_without_results_refuses_push(tmp_path, monkeypatch):
    """A successful process must still return the documented results object."""
    fake_bin = tmp_path / "detector-bin"
    fake_bin.mkdir()
    fake_detector = fake_bin / "detect-secrets"
    fake_detector.write_text("#!/bin/sh\nprintf '%s\\n' '{}'\n")
    fake_detector.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")

    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    tip = _commit(repo, "scan-me.txt", "ordinary content\n")

    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert r.returncode == 3, r.stderr
    assert "detect-secrets response has no results object" in r.stderr


def test_new_branch_scans_everything_not_nothing(tmp_path):
    """Remote sha all-zero and no remote default branch known → base is the empty tree."""
    repo = _repo(tmp_path)
    tip = _commit(
        repo, "leak.txt", "path " + "/".join(("", "home", "other", "secret-store")) + "\n"
    )
    r = _run(repo, "origin", f"refs/heads/feature {tip} refs/heads/feature {ZERO}\n")
    assert r.returncode == 1, r.stderr
    assert "home path" in r.stderr


def test_new_branch_to_foreign_remote_does_not_inherit_origin_base(tmp_path, monkeypatch):
    """A target with no known base must not borrow an unrelated remote's branch tip."""
    fake_bin = tmp_path / "detector-bin"
    fake_bin.mkdir()
    fake_detector = fake_bin / "detect-secrets"
    fake_detector.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' \'{"version": "1.5.0", "results": {}}\'\n'
    )
    fake_detector.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")

    repo = _repo(tmp_path)
    line = "path " + "/".join(("", "home", "someone", "secret-store")) + "\n"
    tip = _commit(repo, "leak.txt", line)
    _git(repo, "update-ref", "refs/remotes/origin/main", tip)

    r = _run(repo, "mirror", f"refs/heads/feature {tip} refs/heads/feature {ZERO}\n")

    assert r.returncode == 1, r.stderr
    assert "home path" in r.stderr


def test_exemption_only_by_explicit_local_config(tmp_path):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    tip = _commit(
        repo, "leak.txt", "path " + "/".join(("", "home", "other", "secret-store")) + "\n"
    )
    refs = f"refs/heads/main {tip} refs/heads/main {base}\n"
    assert _run(repo, "mirror", refs).returncode == 1
    _git(repo, "config", "--add", "hapax.prepushScan.skipRemote", "mirror")
    assert _run(repo, "mirror", refs).returncode == 0
    assert _run(repo, "origin", refs).returncode == 1  # exemption is per remote name, not global


def test_pre_existing_finding_in_a_changed_file_is_not_new_exposure(tmp_path):
    """A keyword-shaped line the remote already has must not make an unrelated edit unpushable;
    a NEW keyword-shaped line in the same file must. Measured 2026-09-02: the first real push
    through this hook was refused for a test fixture that has been on main for weeks."""
    repo = _repo(tmp_path)
    # The keyword names are assembled at runtime so THIS file carries no keyword-shaped line
    # (the hook scans its own pull request's diff; the fixture must exist only inside tmp_path).
    keyword_a = "OPENAI_" + "API_" + "KEY"
    keyword_b = "CODEX_" + "API_" + "KEY"
    fixture = f'env["{keyword_a}"] = "test-key-value-not-real"\n'
    base = _commit(repo, "fixture.py", fixture + "x = 1\n")
    # Unrelated edit below the pre-existing line: passes.
    tip = _commit(repo, "fixture.py", fixture + "x = 2\n")
    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert r.returncode == 0, r.stderr
    # A second keyword-shaped line ADDED: refused, and the file is named.
    tip2 = _commit(
        repo, "fixture.py", fixture + "x = 2\n" + f'env["{keyword_b}"] = "another-test-value"\n'
    )
    r2 = _run(repo, "origin", f"refs/heads/main {tip2} refs/heads/main {tip}\n")
    assert r2.returncode == 1, r2.stderr
    assert "secret-shaped: fixture.py" in r2.stderr


@pytest.mark.parametrize(
    "generated",
    [
        "docs/architecture/system-dynamics-map.lock.json",
        "config/capability-inventory-baseline.json",
    ],
)
def test_generated_hash_bearing_artifacts_are_exempt_from_entropy_only_findings(
    tmp_path, generated
):
    """A re-materialized architecture map adds fresh hex digests; those are not secrets. The same
    digest in any other path is still refused, and a keyword on the generated path still is."""
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    # Computed, not literal: this file's own push must not carry a high-entropy hex line.
    digest = hashlib.sha256(b"content digest, not a secret").hexdigest()
    line = f'{{"digest": "{digest}"}}\n'
    tip = _commit(repo, generated, line)
    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert r.returncode == 0, r.stderr

    tip2 = _commit(repo, "notes/digest.json", line)  # same content, ordinary path: refused
    r2 = _run(repo, "origin", f"refs/heads/main {tip2} refs/heads/main {tip}\n")
    assert r2.returncode == 1, r2.stderr
    assert "secret-shaped: notes/digest.json" in r2.stderr

    keyword = "OPENAI_" + "API_" + "KEY"
    tip3 = _commit(repo, generated, line + f'{{"{keyword}": "not-a-real-value-either"}}\n')
    r3 = _run(repo, "origin", f"refs/heads/main {tip3} refs/heads/main {tip2}\n")
    assert r3.returncode == 1, r3.stderr  # the exemption is entropy-only; keywords still count


def test_systemd_unit_files_preserve_installed_home_path_exemption(tmp_path):
    """Reconcile the installed systemd-only exception, leaving ordinary files guarded."""
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    # Built at runtime so this fixture line is not itself a home path in an added line.
    line = (
        "ExecStart=" + "/".join(("", "home", "someone", "projects", "x", "scripts", "job")) + "\n"
    )
    tip = _commit(repo, "systemd/units/job.service", "[Service]\n" + line)
    r = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert r.returncode == 0, r.stderr
    tip2 = _commit(repo, "config/job.service", "[Service]\n" + line)
    r2 = _run(repo, "origin", f"refs/heads/main {tip2} refs/heads/main {tip}\n")
    assert r2.returncode == 1, r2.stderr
    assert "home path in 1 added line(s): config/job.service" in r2.stderr


def test_deletion_pushes_nothing_and_passes(tmp_path):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    r = _run(repo, "origin", f"(delete) {ZERO} refs/heads/old {base}\n")
    assert r.returncode == 0, r.stderr


def _executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


@pytest.fixture
def clean_detector(tmp_path, monkeypatch):
    bin_dir = tmp_path / "clean-detector"
    bin_dir.mkdir()
    _executable(
        bin_dir / "detect-secrets",
        '#!/bin/sh\nprintf \'%s\\n\' \'{"version": "1.5.0", "results": {}}\'\n',
    )
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    return bin_dir


def _publish_base(repo: Path, tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", "-q", "-b", "main", str(remote))
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "-u", "origin", "main")
    assert _git(repo, "rev-parse", "refs/remotes/origin/main") == _git(remote, "rev-parse", "main")
    return remote


def _published_feature(tmp_path: Path) -> tuple[Path, Path, str]:
    repo = _repo(tmp_path)
    remote = _publish_base(repo, tmp_path)
    _git(repo, "checkout", "-q", "-b", "feature")
    base = _commit(repo, "feature.txt", "published feature\n")
    _git(repo, "push", "-q", "origin", "feature")
    return repo, remote, base


def _feature_scan(repo: Path, base: str) -> subprocess.CompletedProcess:
    tip = _git(repo, "rev-parse", "HEAD")
    return _run(repo, "origin", f"refs/heads/feature {tip} refs/heads/feature {base}\n")


@pytest.mark.parametrize("remote_branch", ["main", "other-published", "published-tag"])
def test_existing_branch_merges_remote_fixtures(tmp_path, remote_branch):
    """(a) Previously published content on any destination ref adds no exposure."""
    repo, _remote, base = _published_feature(tmp_path)
    _git(repo, "checkout", "-q", "main")
    if remote_branch != "main":
        _git(repo, "checkout", "-q", "-b", remote_branch)
    fake = "AKIA" + "ZXCVBNMASDFG1234"  # Synthetic shape only.
    home = "/".join(("", "home", "example", "fixture"))
    _commit(repo, "fixture.txt", f"{fake}\n{home}\n")
    if remote_branch == "published-tag":
        _git(repo, "tag", "-a", "remote-fixture", "-m", "published fixtures")
        _git(repo, "push", "-q", "origin", "refs/tags/remote-fixture")
    else:
        _git(repo, "push", "-q", "origin", remote_branch)
    _git(repo, "checkout", "-q", "feature")
    _git(repo, "merge", "--no-ff", "-q", "-m", "merge published fixtures", remote_branch)
    assert _git(repo, "diff", remote_branch, "HEAD", "--", "fixture.txt") == ""

    result = _feature_scan(repo, base)

    assert result.returncode == 0, result.stderr
    assert fake not in result.stdout + result.stderr


def test_merge_conflict_resolution_secret_is_refused(tmp_path):
    """(b) A new line in the merge itself is absent from both published parents."""
    repo, remote, _base = _published_feature(tmp_path)
    base = _commit(repo, "README.md", "feature resolution candidate\n")
    _git(repo, "push", "-q", "origin", "feature")
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "README.md", "main resolution candidate\n")
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "checkout", "-q", "feature")
    merge = subprocess.run(
        ["git", "merge", "--no-ff", "main"], cwd=repo, capture_output=True, text=True
    )
    assert merge.returncode == 1
    fake = "AKIA" + "ZXCVBNMASDFG1234"  # Synthetic shape only.
    _commit(repo, "README.md", f"{fake}\n")
    assert len(_git(repo, "rev-list", "--parents", "-n", "1", "HEAD").split()) == 3
    for branch in ("feature", "main"):
        assert fake not in _git(remote, "show", f"{branch}:README.md")

    result = _feature_scan(repo, base)

    assert result.returncode == 1, result.stderr
    assert "secret-shaped: README.md" in result.stderr
    assert fake not in result.stdout + result.stderr


def test_existing_ref_new_secret_is_refused(tmp_path):
    """(c) Ordinary new commits remain in the scan even on an existing remote ref."""
    repo, _remote, base = _published_feature(tmp_path)
    fake = "AKIA" + "ZXCVBNMASDFG1234"  # Synthetic shape only.
    _commit(repo, "new-secret.txt", f"{fake}\n")

    result = _feature_scan(repo, base)

    assert result.returncode == 1, result.stderr
    assert "secret-shaped: new-secret.txt" in result.stderr
    assert fake not in result.stdout + result.stderr


@pytest.mark.parametrize("published_default", [False, True], ids=["empty", "known-default"])
@pytest.mark.parametrize("dirty", [False, True], ids=["clean", "secret"])
def test_new_ref_zero_sha_preserves_scanning(tmp_path, published_default, dirty):
    """(d) New refs still allow clean content and refuse new secrets, with or without a base."""
    repo = _repo(tmp_path)
    fake = "AKIA" + "ZXCVBNMASDFG1234"  # Synthetic shape only.
    if published_default:
        _commit(repo, "published-fixture.txt", f"{fake}\n")
        _publish_base(repo, tmp_path)
    else:
        remote = tmp_path / "empty.git"
        _git(tmp_path, "init", "--bare", "-q", str(remote))
        _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit(repo, "new-content.txt", f"{fake}\n" if dirty else "ordinary content\n")

    result = _feature_scan(repo, ZERO)

    assert result.returncode == (1 if dirty else 0), result.stderr
    assert ("secret-shaped: new-content.txt" in result.stderr) == dirty
    assert fake not in result.stdout + result.stderr


def test_existing_ref_new_home_path_is_refused(tmp_path):
    """(e) Home paths newly introduced on a published branch remain guarded."""
    repo, _remote, base = _published_feature(tmp_path)
    home = "/".join(("", "home", "example", "private"))
    _commit(repo, "new-path.txt", f"path {home}\n")

    result = _feature_scan(repo, base)

    assert result.returncode == 1, result.stderr
    assert "home path in 1 added line(s): new-path.txt" in result.stderr
    assert home not in result.stdout + result.stderr


@pytest.mark.parametrize("retarget", ["url", "pushurl"])
def test_cached_refs_from_other_destination_cannot_hide_secret(tmp_path, retarget):
    repo = _repo(tmp_path)
    fake = "AKIA" + "ZXCVBNMASDFG1234"  # Synthetic shape only.
    _commit(repo, "secret.txt", f"{fake}\n")
    _publish_base(repo, tmp_path)
    empty = tmp_path / "other.git"
    _git(tmp_path, "init", "--bare", "-q", str(empty))
    _git(repo, "config", f"remote.origin.{retarget}", str(empty))

    result = _feature_scan(repo, ZERO)

    assert result.returncode == 1, result.stderr
    assert "secret-shaped: secret.txt" in result.stderr


def test_unpublished_second_parent_secret_is_scanned(tmp_path):
    repo, _remote, base = _published_feature(tmp_path)
    _git(repo, "checkout", "-q", "-b", "unpublished", "main")
    fake = "AKIA" + "ZXCVBNMASDFG1234"  # Synthetic shape only.
    _commit(repo, "side-secret.txt", f"{fake}\n")
    _git(repo, "checkout", "-q", "feature")
    _git(repo, "merge", "--no-ff", "-q", "-m", "merge unpublished branch", "unpublished")

    result = _feature_scan(repo, base)

    assert result.returncode == 1, result.stderr
    assert "secret-shaped: side-secret.txt" in result.stderr


def test_unavailable_destination_cannot_trust_cached_refs(tmp_path):
    repo = _repo(tmp_path)
    fake = "AKIA" + "ZXCVBNMASDFG1234"  # Synthetic shape only.
    _commit(repo, "secret.txt", f"{fake}\n")
    _publish_base(repo, tmp_path)
    _git(repo, "remote", "set-url", "origin", str(tmp_path / "missing.git"))

    result = _feature_scan(repo, ZERO)

    assert result.returncode == 1, result.stderr
    assert "could not verify destination refs" in result.stderr
    assert "secret-shaped: secret.txt" in result.stderr
    assert fake not in result.stdout + result.stderr


def test_missing_protocol_history_refuses_with_fetch_guidance(tmp_path):
    repo = _repo(tmp_path)
    missing = "1" * 40

    result = _feature_scan(repo, missing)

    assert result.returncode == 3, result.stderr
    assert "could not resolve pushed history" in result.stderr
    assert "fetch the destination's missing history" in result.stderr
    assert "Traceback" not in result.stderr


def test_textconv_cannot_hide_added_secret(tmp_path):
    repo, _remote, base = _published_feature(tmp_path)
    _commit(repo, ".gitattributes", "*.txt diff=hidden\n")
    _git(repo, "config", "diff.hidden.textconv", "true")
    fake = "AKIA" + "ZXCVBNMASDFG1234"  # Synthetic shape only.
    _commit(repo, "hidden.txt", f"{fake}\n")

    result = _feature_scan(repo, base)

    assert result.returncode == 1, result.stderr
    assert "secret-shaped: hidden.txt" in result.stderr


@pytest.mark.parametrize("binary", [False, True], ids=["text", "binary"])
def test_symlink_type_change_is_scanned(tmp_path, clean_detector, binary):
    repo = _repo(tmp_path)
    path = repo / "replacement.txt"
    path.symlink_to("README.md")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "remote symlink")
    _publish_base(repo, tmp_path)
    base = _git(repo, "rev-parse", "refs/remotes/origin/main")
    home = "/".join(("", "home", "example", "private"))
    key = "sk-ant-" + "Q" * 40
    path.unlink()
    path.write_bytes(f"{home}\n{key}\n".encode() + (b"\0" if binary else b""))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "replace symlink")
    tip = _git(repo, "rev-parse", "HEAD")
    assert _git(repo, "diff", "--name-status", base, tip) == "T\treplacement.txt"

    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert result.returncode == 1, result.stderr
    if binary:
        assert "unscannable binary content: replacement.txt" in result.stderr
    else:
        assert "home path in 1 added line(s): replacement.txt" in result.stderr
        assert "vendor-key-shaped in 1 added line(s): replacement.txt" in result.stderr
    assert "Remedy:" in result.stderr
    assert home not in result.stderr and key not in result.stderr


SEPARATORS = ["\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029", "\r"]
SEPARATOR_IDS = ["vt", "ff", "fs", "gs", "rs", "nel", "ls", "ps", "cr"]


@pytest.mark.parametrize("separator", SEPARATORS, ids=SEPARATOR_IDS)
def test_git_line_boundaries_preserve_findings(tmp_path, clean_detector, monkeypatch, separator):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    home = "/".join(("", "home", "example", "private"))
    key = "sk-ant-" + "Q" * 40
    lines = [f"prefix{separator}{home}", f"prefix{separator}{key}", "last\r"]
    tip = _commit(repo, "controls.txt", "\n".join(lines) + "\n")
    scanner = runpy.run_path(str(SCRIPT))
    monkeypatch.chdir(repo)

    added = scanner["added_lines"](base, tip, ["controls.txt"])

    assert added == {"controls.txt": list(enumerate(lines, 1))}
    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert result.returncode == 1, result.stderr
    assert "home path in 1 added line(s): controls.txt" in result.stderr
    assert "vendor-key-shaped in 1 added line(s): controls.txt" in result.stderr
    assert home not in result.stderr and key not in result.stderr


@pytest.mark.parametrize("separator", SEPARATORS[5:8], ids=SEPARATOR_IDS[5:8])
def test_unicode_separators_in_ref_and_remote_names(tmp_path, clean_detector, separator):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    branch = f"feature{separator}name"
    _git(repo, "switch", "-c", branch)
    home = "/".join(("", "home", "example", "private"))
    tip = _commit(repo, "ref-content.txt", f"{home}\n")
    # This is one config value, not an exemption for a remote named origin.
    _git(repo, "config", "--add", "hapax.prepushScan.skipRemote", f"origin{separator}other")
    refs = f"refs/heads/{branch} {tip} refs/heads/{branch} {base}\n"

    result = _run(repo, "origin", refs)

    assert result.returncode == 1, result.stderr
    assert "home path in 1 added line(s): ref-content.txt" in result.stderr
    assert _run(repo, f"origin{separator}other", refs).returncode == 0


@pytest.mark.parametrize("operation", ["delete", "copy", "rename"])
def test_content_status_selection(tmp_path, clean_detector, operation):
    repo = _repo(tmp_path)
    home = "/".join(("", "home", "example", "private"))
    base = _commit(repo, "source.txt", f"{home}\n")
    _publish_base(repo, tmp_path)
    _git(repo, "config", "diff.renames", "copies")
    source = repo / "source.txt"
    if operation == "delete":
        source.unlink()
    elif operation == "copy":
        shutil.copy2(source, repo / "destination.txt")
    else:
        source.rename(repo / "destination.txt")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", operation)
    tip = _git(repo, "rev-parse", "HEAD")
    status = _git(repo, "diff", "--name-status", "-C", "--find-copies-harder", base, tip)
    assert status.startswith({"delete": "D\t", "copy": "C100\t", "rename": "R100\t"}[operation])

    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")

    assert result.returncode == (0 if operation == "delete" else 1), result.stderr
    if operation != "delete":
        assert "home path in 1 added line(s): destination.txt" in result.stderr
