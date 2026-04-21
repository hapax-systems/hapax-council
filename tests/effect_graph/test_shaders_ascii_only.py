"""Pin: GLSL ES fragment shaders must be ASCII-only.

ESSL 1.00 §3.1: "Characters used in source files for GLSL ES are limited
to ASCII." NVIDIA's GLSL ES parser enforces this even inside comments —
non-ASCII bytes (em-dashes, smart quotes, accented characters) trigger
``error C0000: syntax error, unexpected $undefined`` recovery and the
whole shader fails to compile.

Live regression seen 2026-04-21: the studio compositor logged
``Shader recompile FAILED`` every few minutes whenever a `postprocess`
shader (which had em-dashes in line-comments at lines 21 + 23) was
re-set into a glfeedback slot. After this fix, the entire .frag
catalogue is ASCII-clean.

This test is the regression pin — any future contributor adding a
non-ASCII char (intentional smart quote, em-dash, accent) will fail
the build before it lands on stream.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SHADER_DIR = Path(__file__).resolve().parents[2] / "agents" / "shaders" / "nodes"


def _all_frag_files() -> list[Path]:
    return sorted(SHADER_DIR.glob("*.frag"))


def test_shader_directory_exists() -> None:
    assert SHADER_DIR.exists(), f"shader dir missing: {SHADER_DIR}"


def test_at_least_one_frag_present() -> None:
    files = _all_frag_files()
    assert files, "no .frag files found — registry pipeline likely broken"


@pytest.mark.parametrize("frag_path", _all_frag_files(), ids=lambda p: p.name)
def test_frag_is_ascii_only(frag_path: Path) -> None:
    """Every byte in every .frag must be 7-bit ASCII (0x00-0x7F)."""
    raw = frag_path.read_bytes()
    bad: list[tuple[int, int]] = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
    if bad:
        # Surface the first few offending bytes with line context.
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        bad_lines: list[str] = []
        for offset, byte in bad[:5]:
            line_no = raw[: offset + 1].count(b"\n") + 1
            line = lines[line_no - 1] if line_no <= len(lines) else "<EOF>"
            bad_lines.append(f"  line {line_no} (byte 0x{byte:02X}): {line}")
        joined = "\n".join(bad_lines)
        pytest.fail(
            f"{frag_path.name}: {len(bad)} non-ASCII byte(s); ESSL 1.00 §3.1 "
            f"forbids non-ASCII even in comments. NVIDIA's parser fails the "
            f'whole shader. Replace em-dashes with --, smart quotes with ", '
            f"etc.\n{joined}"
        )
