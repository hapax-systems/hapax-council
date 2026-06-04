from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-audio-reconciler"


def test_reconciler_only_mutates_missing_or_forbidden_present_links(tmp_path: Path) -> None:
    graph = tmp_path / "graph.txt"
    calls = tmp_path / "calls.txt"
    link_map = tmp_path / "audio-link-map.conf"
    forbidden = tmp_path / "audio-forbidden-links.conf"
    log = tmp_path / "reconciler.log"
    fake_pw_link = tmp_path / "pw-link"

    graph.write_text(
        "\n".join(
            [
                "present-source:out",
                "  |-> present-target:in",
                "missing-source:out",
                "missing-target:in",
                "forbidden-source:out",
                "  |-> forbidden-target:in",
                "",
            ]
        ),
        encoding="utf-8",
    )
    link_map.write_text(
        "\n".join(
            [
                "present-source:out|present-target:in",
                "missing-source:out|missing-target:in",
                "absent-source:out|absent-target:in",
                "",
            ]
        ),
        encoding="utf-8",
    )
    forbidden.write_text(
        "\n".join(
            [
                "forbidden-source:out|forbidden-target:in",
                "absent-forbidden-source:out|absent-forbidden-target:in",
                "",
            ]
        ),
        encoding="utf-8",
    )
    fake_pw_link.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "-l" ]; then cat "$PW_LINK_GRAPH"; exit 0; fi\n'
        'if [ "$1" = "-o" ]; then cat "$PW_LINK_OUTPUTS"; exit 0; fi\n'
        'if [ "$1" = "-i" ]; then cat "$PW_LINK_INPUTS"; exit 0; fi\n'
        'if [ "$1" = "-d" ]; then printf \'disconnect %s %s\\n\' "$2" "$3" >> "$PW_LINK_CALLS"; exit 0; fi\n'
        'printf \'connect %s %s\\n\' "$1" "$2" >> "$PW_LINK_CALLS"\n',
        encoding="utf-8",
    )
    fake_pw_link.chmod(0o755)

    env = {
        **os.environ,
        "HAPAX_RECONCILER_ONCE": "1",
        "HAPAX_RECONCILER_INTERVAL_S": "0",
        "HAPAX_RECONCILER_LINK_MAP": str(link_map),
        "HAPAX_RECONCILER_FORBIDDEN_LINKS": str(forbidden),
        "HAPAX_RECONCILER_LOG": str(log),
        "HAPAX_RECONCILER_PW_LINK": str(fake_pw_link),
        "PW_LINK_GRAPH": str(graph),
        "PW_LINK_OUTPUTS": str(graph),
        "PW_LINK_INPUTS": str(graph),
        "PW_LINK_CALLS": str(calls),
    }

    result = subprocess.run(
        [str(SCRIPT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "connect missing-source:out missing-target:in",
        "disconnect forbidden-source:out forbidden-target:in",
    ]


def test_reconciler_sees_unlinked_ports_from_port_inventory(tmp_path: Path) -> None:
    graph = tmp_path / "graph.txt"
    outputs = tmp_path / "outputs.txt"
    inputs = tmp_path / "inputs.txt"
    calls = tmp_path / "calls.txt"
    link_map = tmp_path / "audio-link-map.conf"
    forbidden = tmp_path / "audio-forbidden-links.conf"
    log = tmp_path / "reconciler.log"
    fake_pw_link = tmp_path / "pw-link"

    graph.write_text(
        "\n".join(
            [
                "present-source:out",
                "  |-> present-target:in",
                "",
            ]
        ),
        encoding="utf-8",
    )
    outputs.write_text(
        "\n".join(
            [
                "present-source:out",
                "unlinked-source:out",
                "",
            ]
        ),
        encoding="utf-8",
    )
    inputs.write_text(
        "\n".join(
            [
                "present-target:in",
                "unlinked-target:in",
                "",
            ]
        ),
        encoding="utf-8",
    )
    link_map.write_text(
        "\n".join(
            [
                "present-source:out|present-target:in",
                "unlinked-source:out|unlinked-target:in",
                "",
            ]
        ),
        encoding="utf-8",
    )
    forbidden.write_text("", encoding="utf-8")
    fake_pw_link.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "-l" ]; then cat "$PW_LINK_GRAPH"; exit 0; fi\n'
        'if [ "$1" = "-o" ]; then cat "$PW_LINK_OUTPUTS"; exit 0; fi\n'
        'if [ "$1" = "-i" ]; then cat "$PW_LINK_INPUTS"; exit 0; fi\n'
        'printf \'connect %s %s\\n\' "$1" "$2" >> "$PW_LINK_CALLS"\n',
        encoding="utf-8",
    )
    fake_pw_link.chmod(0o755)

    env = {
        **os.environ,
        "HAPAX_RECONCILER_ONCE": "1",
        "HAPAX_RECONCILER_INTERVAL_S": "0",
        "HAPAX_RECONCILER_LINK_MAP": str(link_map),
        "HAPAX_RECONCILER_FORBIDDEN_LINKS": str(forbidden),
        "HAPAX_RECONCILER_LOG": str(log),
        "HAPAX_RECONCILER_PW_LINK": str(fake_pw_link),
        "PW_LINK_GRAPH": str(graph),
        "PW_LINK_OUTPUTS": str(outputs),
        "PW_LINK_INPUTS": str(inputs),
        "PW_LINK_CALLS": str(calls),
    }

    result = subprocess.run(
        [str(SCRIPT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "connect unlinked-source:out unlinked-target:in",
    ]
