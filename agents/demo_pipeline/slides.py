"""Marp slide generation from DemoScript."""
from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from collections.abc import Callable

from agents.demo_models import DemoScript

log = logging.getLogger(__name__)

AUDIENCE_LABELS: dict[str, str] = {
    "family": "Family",
    "technical-peer": "Technical Peers",
    "leadership": "Leadership",
    "team-member": "Team Members",
}

THEME_PATH = Path(__file__).parent / "gruvbox-marp.css"


def generate_marp_markdown(
    script: DemoScript, screenshots: dict[str, Path]
) -> str:
    """Generate Marp-flavored markdown from a DemoScript."""
    lines: list[str] = []

    audience_label = AUDIENCE_LABELS.get(script.audience, script.audience.replace("-", " ").title())

    lines.append("---")
    lines.append("marp: true")
    lines.append("theme: gruvbox")
    lines.append("paginate: true")
    lines.append(f"footer: '{script.title} — for {audience_label}'")
    lines.append("---")
    lines.append("")

    lines.append("<!-- _class: lead -->")
    lines.append("")
    lines.append(f"# {script.title}")
    lines.append("")
    lines.append(f"*Prepared for: {audience_label}*")
    lines.append("")
    lines.append(f"<!-- {script.intro_narration} -->")
    lines.append("")

    for scene in script.scenes:
        lines.append("---")
        lines.append("")
        lines.append(f"## {scene.title}")
        lines.append("")

        img_path = screenshots.get(scene.title)
        if img_path:
            lines.append(f"![bg right:60% fit]({img_path})")
            lines.append("")

        if scene.key_points:
            for point in scene.key_points:
                lines.append(f"- {point}")
            lines.append("")

        lines.append("<!--")
        lines.append(scene.narration)
        lines.append("-->")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("<!-- _class: lead -->")
    lines.append("")
    lines.append("# Thank You")
    lines.append("")
    lines.append(f"<!-- {script.outro_narration} -->")
    lines.append("")

    return "\n".join(lines)


async def render_slides(
    script: DemoScript,
    screenshots: dict[str, Path],
    output_dir: Path,
    render_pdf: bool = True,
    on_progress: Callable[[str], None] | None = None,
) -> Path:
    """Generate Marp markdown and optionally render to PDF."""
    output_dir.mkdir(parents=True, exist_ok=True)

    slides_screenshot_dir = output_dir / "screenshots"
    slides_screenshot_dir.mkdir(exist_ok=True)
    relative_screenshots: dict[str, Path] = {}
    for title, src in screenshots.items():
        dest = slides_screenshot_dir / src.name
        if src.exists() and src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        relative_screenshots[title] = Path("screenshots") / src.name

    md = generate_marp_markdown(script, relative_screenshots)
    md_path = output_dir / "slides.md"
    md_path.write_text(md)

    if render_pdf:
        pdf_path = output_dir / "slides.pdf"
        theme_dest = output_dir / "gruvbox-marp.css"
        shutil.copy2(THEME_PATH, theme_dest)

        proc = await asyncio.create_subprocess_exec(
            "npx", "-y", "@marp-team/marp-cli@4",
            str(md_path),
            "--theme", str(theme_dest),
            "--html",
            "--allow-local-files",
            "-o", str(pdf_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(output_dir),
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            msg = f"WARNING: Marp PDF render failed: {stderr.decode()[:500]}"
            log.error(msg)
            if on_progress:
                on_progress(msg)
        else:
            log.info("Slides rendered to %s", pdf_path)

    return md_path
