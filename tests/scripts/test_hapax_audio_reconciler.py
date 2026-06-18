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
        "HAPAX_RECONCILER_VOLUME_NODES": "",
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
        "HAPAX_RECONCILER_VOLUME_NODES": "",
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


def test_reconciler_sets_unity_volume_for_present_configured_nodes(tmp_path: Path) -> None:
    graph = tmp_path / "graph.txt"
    calls = tmp_path / "calls.txt"
    wpctl_calls = tmp_path / "wpctl-calls.txt"
    wpctl_status = tmp_path / "wpctl-status.txt"
    link_map = tmp_path / "audio-link-map.conf"
    forbidden = tmp_path / "audio-forbidden-links.conf"
    log = tmp_path / "reconciler.log"
    fake_pw_link = tmp_path / "pw-link"
    fake_wpctl = tmp_path / "wpctl"

    graph.write_text("", encoding="utf-8")
    link_map.write_text("", encoding="utf-8")
    forbidden.write_text("", encoding="utf-8")
    wpctl_status.write_text(
        "\n".join(
            [
                "Audio",
                " ├─ Sinks:",
                " ├─ Filters:",
                " │      80. hapax-broadcast-master              [Audio/Source]",
                " │     104. hapax-music-loudnorm                [Audio/Sink]",
                " │  *  107. hapax-obs-broadcast-remap           [Audio/Source]",
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
        'printf \'connect %s %s\\n\' "$1" "$2" >> "$PW_LINK_CALLS"\n',
        encoding="utf-8",
    )
    fake_pw_link.chmod(0o755)
    fake_wpctl.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "status" ] && [ "$2" = "--name" ]; then cat "$WPCTL_STATUS"; exit 0; fi\n'
        'if [ "$1" = "get-volume" ] && [ "$2" = "80" ]; then printf \'Volume: 0.00\\n\'; exit 0; fi\n'
        'if [ "$1" = "get-volume" ] && [ "$2" = "107" ]; then printf \'Volume: 1.00\\n\'; exit 0; fi\n'
        'if [ "$1" = "set-volume" ]; then printf \'set-volume %s %s\\n\' "$2" "$3" >> "$WPCTL_CALLS"; exit 0; fi\n'
        "exit 2\n",
        encoding="utf-8",
    )
    fake_wpctl.chmod(0o755)

    env = {
        **os.environ,
        "HAPAX_RECONCILER_ONCE": "1",
        "HAPAX_RECONCILER_INTERVAL_S": "0",
        "HAPAX_RECONCILER_LINK_MAP": str(link_map),
        "HAPAX_RECONCILER_FORBIDDEN_LINKS": str(forbidden),
        "HAPAX_RECONCILER_LOG": str(log),
        "HAPAX_RECONCILER_PW_LINK": str(fake_pw_link),
        "HAPAX_RECONCILER_WPCTL": str(fake_wpctl),
        "HAPAX_RECONCILER_VOLUME_NODES": (
            "hapax-livestream-tap hapax-broadcast-master hapax-broadcast-normalized "
            "hapax-music-loudnorm hapax-obs-broadcast-remap"
        ),
        "PW_LINK_GRAPH": str(graph),
        "PW_LINK_OUTPUTS": str(graph),
        "PW_LINK_INPUTS": str(graph),
        "PW_LINK_CALLS": str(calls),
        "WPCTL_STATUS": str(wpctl_status),
        "WPCTL_CALLS": str(wpctl_calls),
    }

    result = subprocess.run(
        [str(SCRIPT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert not calls.exists()
    assert wpctl_calls.read_text(encoding="utf-8").splitlines() == [
        "set-volume 80 1.0",
    ]
    log_text = log.read_text(encoding="utf-8")
    assert "rejected 2 disallowed zero-volume target(s)" in log_text
    assert "hapax-music-loudnorm" not in wpctl_calls.read_text(encoding="utf-8")


def test_reconciler_volume_guard_degrades_when_wpctl_status_unavailable(
    tmp_path: Path,
) -> None:
    graph = tmp_path / "graph.txt"
    calls = tmp_path / "calls.txt"
    link_map = tmp_path / "audio-link-map.conf"
    forbidden = tmp_path / "audio-forbidden-links.conf"
    log = tmp_path / "reconciler.log"
    fake_pw_link = tmp_path / "pw-link"
    fake_wpctl = tmp_path / "wpctl"

    graph.write_text("", encoding="utf-8")
    link_map.write_text("", encoding="utf-8")
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
    fake_wpctl.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    fake_wpctl.chmod(0o755)

    env = {
        **os.environ,
        "HAPAX_RECONCILER_ONCE": "1",
        "HAPAX_RECONCILER_INTERVAL_S": "0",
        "HAPAX_RECONCILER_LINK_MAP": str(link_map),
        "HAPAX_RECONCILER_FORBIDDEN_LINKS": str(forbidden),
        "HAPAX_RECONCILER_LOG": str(log),
        "HAPAX_RECONCILER_PW_LINK": str(fake_pw_link),
        "HAPAX_RECONCILER_WPCTL": str(fake_wpctl),
        "HAPAX_RECONCILER_VOLUME_NODES": "hapax-broadcast-master",
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
    assert not calls.exists()


def test_reconciler_volume_guard_skips_muted_zero_volume_nodes(tmp_path: Path) -> None:
    graph = tmp_path / "graph.txt"
    calls = tmp_path / "calls.txt"
    wpctl_status = tmp_path / "wpctl-status.txt"
    link_map = tmp_path / "audio-link-map.conf"
    forbidden = tmp_path / "audio-forbidden-links.conf"
    log = tmp_path / "reconciler.log"
    fake_pw_link = tmp_path / "pw-link"
    fake_wpctl = tmp_path / "wpctl"

    graph.write_text("", encoding="utf-8")
    link_map.write_text("", encoding="utf-8")
    forbidden.write_text("", encoding="utf-8")
    wpctl_status.write_text(
        " │      80. hapax-broadcast-master              [Audio/Source]\n",
        encoding="utf-8",
    )
    fake_pw_link.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "-l" ]; then cat "$PW_LINK_GRAPH"; exit 0; fi\n'
        'if [ "$1" = "-o" ]; then cat "$PW_LINK_OUTPUTS"; exit 0; fi\n'
        'if [ "$1" = "-i" ]; then cat "$PW_LINK_INPUTS"; exit 0; fi\n'
        'printf \'connect %s %s\\n\' "$1" "$2" >> "$PW_LINK_CALLS"\n',
        encoding="utf-8",
    )
    fake_pw_link.chmod(0o755)
    fake_wpctl.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "status" ] && [ "$2" = "--name" ]; then cat "$WPCTL_STATUS"; exit 0; fi\n'
        'if [ "$1" = "get-volume" ]; then printf \'Volume: 0.00 [MUTED]\\n\'; exit 0; fi\n'
        'if [ "$1" = "set-volume" ]; then printf \'set-volume %s %s\\n\' "$2" "$3" >> "$WPCTL_CALLS"; exit 0; fi\n'
        "exit 2\n",
        encoding="utf-8",
    )
    fake_wpctl.chmod(0o755)

    env = {
        **os.environ,
        "HAPAX_RECONCILER_ONCE": "1",
        "HAPAX_RECONCILER_INTERVAL_S": "0",
        "HAPAX_RECONCILER_LINK_MAP": str(link_map),
        "HAPAX_RECONCILER_FORBIDDEN_LINKS": str(forbidden),
        "HAPAX_RECONCILER_LOG": str(log),
        "HAPAX_RECONCILER_PW_LINK": str(fake_pw_link),
        "HAPAX_RECONCILER_WPCTL": str(fake_wpctl),
        "HAPAX_RECONCILER_VOLUME_NODES": "hapax-broadcast-master",
        "PW_LINK_GRAPH": str(graph),
        "PW_LINK_OUTPUTS": str(graph),
        "PW_LINK_INPUTS": str(graph),
        "PW_LINK_CALLS": str(calls),
        "WPCTL_STATUS": str(wpctl_status),
        "WPCTL_CALLS": str(tmp_path / "wpctl-calls.txt"),
    }

    result = subprocess.run(
        [str(SCRIPT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert not Path(env["WPCTL_CALLS"]).exists()


def test_reconciler_volume_guard_degrades_when_get_volume_fails(
    tmp_path: Path,
) -> None:
    graph = tmp_path / "graph.txt"
    calls = tmp_path / "calls.txt"
    wpctl_status = tmp_path / "wpctl-status.txt"
    link_map = tmp_path / "audio-link-map.conf"
    forbidden = tmp_path / "audio-forbidden-links.conf"
    log = tmp_path / "reconciler.log"
    fake_pw_link = tmp_path / "pw-link"
    fake_wpctl = tmp_path / "wpctl"

    graph.write_text("", encoding="utf-8")
    link_map.write_text("", encoding="utf-8")
    forbidden.write_text("", encoding="utf-8")
    wpctl_status.write_text(
        " │      80. hapax-broadcast-master              [Audio/Source]\n",
        encoding="utf-8",
    )
    fake_pw_link.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "-l" ]; then cat "$PW_LINK_GRAPH"; exit 0; fi\n'
        'if [ "$1" = "-o" ]; then cat "$PW_LINK_OUTPUTS"; exit 0; fi\n'
        'if [ "$1" = "-i" ]; then cat "$PW_LINK_INPUTS"; exit 0; fi\n'
        'printf \'connect %s %s\\n\' "$1" "$2" >> "$PW_LINK_CALLS"\n',
        encoding="utf-8",
    )
    fake_pw_link.chmod(0o755)
    fake_wpctl.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "status" ] && [ "$2" = "--name" ]; then cat "$WPCTL_STATUS"; exit 0; fi\n'
        'if [ "$1" = "get-volume" ]; then exit 8; fi\n'
        'if [ "$1" = "set-volume" ]; then printf \'set-volume %s %s\\n\' "$2" "$3" >> "$WPCTL_CALLS"; exit 0; fi\n'
        "exit 2\n",
        encoding="utf-8",
    )
    fake_wpctl.chmod(0o755)

    env = {
        **os.environ,
        "HAPAX_RECONCILER_ONCE": "1",
        "HAPAX_RECONCILER_INTERVAL_S": "0",
        "HAPAX_RECONCILER_LINK_MAP": str(link_map),
        "HAPAX_RECONCILER_FORBIDDEN_LINKS": str(forbidden),
        "HAPAX_RECONCILER_LOG": str(log),
        "HAPAX_RECONCILER_PW_LINK": str(fake_pw_link),
        "HAPAX_RECONCILER_WPCTL": str(fake_wpctl),
        "HAPAX_RECONCILER_VOLUME_NODES": "hapax-broadcast-master",
        "PW_LINK_GRAPH": str(graph),
        "PW_LINK_OUTPUTS": str(graph),
        "PW_LINK_INPUTS": str(graph),
        "PW_LINK_CALLS": str(calls),
        "WPCTL_STATUS": str(wpctl_status),
        "WPCTL_CALLS": str(tmp_path / "wpctl-calls.txt"),
    }

    result = subprocess.run(
        [str(SCRIPT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert not Path(env["WPCTL_CALLS"]).exists()
    log_text = log.read_text(encoding="utf-8")
    assert "zero-volume target(s) could not be evaluated or repaired" in log_text
    assert "wpctl get-volume <id>" in log_text


def test_reconciler_volume_guard_degrades_when_set_volume_fails(tmp_path: Path) -> None:
    graph = tmp_path / "graph.txt"
    calls = tmp_path / "calls.txt"
    wpctl_status = tmp_path / "wpctl-status.txt"
    link_map = tmp_path / "audio-link-map.conf"
    forbidden = tmp_path / "audio-forbidden-links.conf"
    log = tmp_path / "reconciler.log"
    fake_pw_link = tmp_path / "pw-link"
    fake_wpctl = tmp_path / "wpctl"

    graph.write_text("", encoding="utf-8")
    link_map.write_text("", encoding="utf-8")
    forbidden.write_text("", encoding="utf-8")
    wpctl_status.write_text(
        " │      80. hapax-broadcast-master              [Audio/Source]\n",
        encoding="utf-8",
    )
    fake_pw_link.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "-l" ]; then cat "$PW_LINK_GRAPH"; exit 0; fi\n'
        'if [ "$1" = "-o" ]; then cat "$PW_LINK_OUTPUTS"; exit 0; fi\n'
        'if [ "$1" = "-i" ]; then cat "$PW_LINK_INPUTS"; exit 0; fi\n'
        'printf \'connect %s %s\\n\' "$1" "$2" >> "$PW_LINK_CALLS"\n',
        encoding="utf-8",
    )
    fake_pw_link.chmod(0o755)
    fake_wpctl.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "status" ] && [ "$2" = "--name" ]; then cat "$WPCTL_STATUS"; exit 0; fi\n'
        'if [ "$1" = "get-volume" ]; then printf \'Volume: 0.00\\n\'; exit 0; fi\n'
        'if [ "$1" = "set-volume" ]; then exit 9; fi\n'
        "exit 2\n",
        encoding="utf-8",
    )
    fake_wpctl.chmod(0o755)

    env = {
        **os.environ,
        "HAPAX_RECONCILER_ONCE": "1",
        "HAPAX_RECONCILER_INTERVAL_S": "0",
        "HAPAX_RECONCILER_LINK_MAP": str(link_map),
        "HAPAX_RECONCILER_FORBIDDEN_LINKS": str(forbidden),
        "HAPAX_RECONCILER_LOG": str(log),
        "HAPAX_RECONCILER_PW_LINK": str(fake_pw_link),
        "HAPAX_RECONCILER_WPCTL": str(fake_wpctl),
        "HAPAX_RECONCILER_VOLUME_NODES": "hapax-broadcast-master",
        "PW_LINK_GRAPH": str(graph),
        "PW_LINK_OUTPUTS": str(graph),
        "PW_LINK_INPUTS": str(graph),
        "PW_LINK_CALLS": str(calls),
        "WPCTL_STATUS": str(wpctl_status),
    }

    result = subprocess.run(
        [str(SCRIPT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    log_text = log.read_text(encoding="utf-8")
    assert "zero-volume target(s) could not be evaluated or repaired" in log_text
    assert "Next action:" in log_text


def test_reconciler_volume_guard_does_not_restart_pipewire() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "restart pipewire" not in text.lower()
    assert "systemctl --user restart" not in text


def test_reconciler_default_volume_targets_stay_on_aggregate_nodes() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    default_line = next(
        line for line in text.splitlines() if line.startswith("DEFAULT_VOLUME_NODES=")
    )

    assert "hapax-broadcast-master" in default_line
    assert "hapax-broadcast-normalized" in default_line
    assert "hapax-obs-broadcast-remap" in default_line
    assert "hapax-livestream-tap" not in default_line
    assert "hapax-music-loudnorm" not in default_line
    assert "hapax-yt-loudnorm" not in default_line
    assert "hapax-mic-rode-playback" not in default_line
    assert "hapax-voice-wet-playback" not in default_line
    assert "HAPAX_RECONCILER_VOLUME_LEVEL" not in text
