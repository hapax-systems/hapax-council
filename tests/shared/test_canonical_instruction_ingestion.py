"""The review admission reads the chosen release and the deployed home together."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from shared.canonical_instruction_ingestion import (
    InstructionIngestionError,
    read_canonical_instructions,
)


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "release"
    source = root / "config/agent-instructions/AGENTS.md"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"# Canonical shared policy\nDo the governed thing.\n")
    home = tmp_path / "operator"
    shared = home / ".config/hapax/agent-instructions/AGENTS.md"
    native = home / ".gemini/GEMINI.md"
    shared.parent.mkdir(parents=True)
    native.parent.mkdir(parents=True)
    shared.write_bytes(source.read_bytes())
    native.write_bytes(b"generated header\n" + source.read_bytes())
    receipt = shared.parent / "current.json"
    receipt.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "binding": "shared",
                        "path": str(shared),
                        "sha256": hashlib.sha256(shared.read_bytes()).hexdigest(),
                    },
                    {
                        "binding": "agy",
                        "path": str(native),
                        "sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return root, home, native, receipt


def test_exact_current_body_and_native_binding_are_returned(tmp_path: Path) -> None:
    root, home, native, _ = _fixture(tmp_path)
    observed = read_canonical_instructions(
        source_root=root, operator_home=home, native_binding=("agy", ".gemini/GEMINI.md")
    )
    assert observed.body == (root / "config/agent-instructions/AGENTS.md").read_bytes()
    assert observed.sha256 == hashlib.sha256(observed.body).hexdigest()
    assert observed.native_body == native.read_bytes()


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "stale",
        "stale-neutral",
        "wrong-home",
        "symlink-home",
        "wrong-source",
        "missing-body",
    ],
)
def test_invalid_native_or_source_refuses(tmp_path: Path, failure: str) -> None:
    root, home, native, receipt = _fixture(tmp_path)
    if failure == "missing":
        native.unlink()
    elif failure == "stale":
        native.write_bytes(b"changed native")
    elif failure == "stale-neutral":
        neutral = home / ".config/hapax/agent-instructions/AGENTS.md"
        neutral.write_bytes(b"old shared policy")
        payload = json.loads(receipt.read_text())
        payload["files"][0]["sha256"] = hashlib.sha256(neutral.read_bytes()).hexdigest()
        receipt.write_text(json.dumps(payload))
    elif failure == "wrong-home":
        payload = json.loads(receipt.read_text())
        payload["files"][1]["path"] = str(tmp_path / "other-home/.gemini/GEMINI.md")
        receipt.write_text(json.dumps(payload))
    elif failure == "symlink-home":
        outside = tmp_path / "other-home/GEMINI.md"
        outside.parent.mkdir()
        outside.write_bytes(native.read_bytes())
        native.unlink()
        native.symlink_to(outside)
    elif failure == "wrong-source":
        (root / "config/agent-instructions/AGENTS.md").write_bytes(b"new release policy")
    else:
        native.write_bytes(b"generated header without body")
        payload = json.loads(receipt.read_text())
        payload["files"][1]["sha256"] = hashlib.sha256(native.read_bytes()).hexdigest()
        receipt.write_text(json.dumps(payload))
    with pytest.raises(InstructionIngestionError):
        read_canonical_instructions(
            source_root=root, operator_home=home, native_binding=("agy", ".gemini/GEMINI.md")
        )
