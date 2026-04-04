"""Convert markdown and ANSI text to Pango markup for overlay rendering."""

from __future__ import annotations

import re

ANSI_COLORS: dict[int, str] = {
    30: "#282828",
    31: "#cc241d",
    32: "#98971a",
    33: "#d79921",
    34: "#458588",
    35: "#b16286",
    36: "#689d6a",
    37: "#a89984",
    90: "#928374",
    91: "#fb4934",
    92: "#b8bb26",
    93: "#fabd2f",
    94: "#83a598",
    95: "#d3869b",
    96: "#8ec07c",
    97: "#ebdbb2",
}


def markdown_to_pango(text: str) -> str:
    text = re.sub(r"\A---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL)
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = re.sub(r"^## (.+)$", r'<span size="large"><b>\1</b></span>', text, flags=re.MULTILINE)
    text = re.sub(r"^# (.+)$", r'<span size="x-large"><b>\1</b></span>', text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
    text = re.sub(r"`(.+?)`", r"<tt>\1</tt>", text)
    return text.strip()


def ansi_to_pango(text: str) -> str:
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    result: list[str] = []
    current_fg: str | None = None
    i = 0
    while i < len(text):
        m = re.match(r"\x1b\[([0-9;]*)m", text[i:])
        if m:
            codes = m.group(1).split(";") if m.group(1) else ["0"]
            for code_str in codes:
                code = int(code_str) if code_str.isdigit() else 0
                if code == 0:
                    if current_fg:
                        result.append("</span>")
                        current_fg = None
                elif code in ANSI_COLORS:
                    if current_fg:
                        result.append("</span>")
                    current_fg = ANSI_COLORS[code]
                    result.append(f'<span foreground="{current_fg}">')
            i += m.end()
        else:
            result.append(text[i])
            i += 1
    if current_fg:
        result.append("</span>")
    return "".join(result)


def parse_overlay_content(text: str, is_ansi: bool = False) -> str:
    if is_ansi:
        return ansi_to_pango(text)
    return markdown_to_pango(text)
