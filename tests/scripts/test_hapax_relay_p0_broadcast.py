"""Tests for the relay P0 broadcast fan-out script."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "hapax-relay-p0-broadcast.sh"


def test_p0_broadcast_only_mutates_live_peer_yamls(tmp_path: Path) -> None:
    relay = tmp_path / ".cache" / "hapax" / "relay"
    relay.mkdir(parents=True)
    body = tmp_path / "body.md"
    body.write_text("incident body\n")

    originals = {
        "alpha": "session: alpha\n",
        "beta": "session: beta\n",
        "cx-red": "session: cx-red\n",
        "audit-old": "kind: audit\n",
        "peer-status-delta": "kind: peer-status\n",
        "queue-state-alpha": "kind: queue\n",
        "working-mode": "mode: rnd\n",
    }
    for name, text in originals.items():
        (relay / f"{name}.yaml").write_text(text)

    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["HAPAX_AGENT_NAME"] = "alpha"

    result = subprocess.run(
        ["bash", str(SCRIPT), "P0", str(body)],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "appended to 2 peer yamls" in result.stdout
    assert (relay / "alpha.yaml").read_text() == originals["alpha"]
    for live_peer in ("beta", "cx-red"):
        text = (relay / f"{live_peer}.yaml").read_text()
        assert "p0_broadcast_inbox_" in text
        assert "wakeup_reason: P0_BROADCAST" in text
    for metadata_peer in ("audit-old", "peer-status-delta", "queue-state-alpha", "working-mode"):
        assert (relay / f"{metadata_peer}.yaml").read_text() == originals[metadata_peer]
