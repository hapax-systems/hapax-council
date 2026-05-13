"""Aesthetic asset generator for the POSSE architecture.

Generates SVG assets adhering to the mIRC-16/Gruvbox palette tokens defined in
docs/logos-design-language.md.
"""

PALETTE = {
    "bg": "#1d2021",
    "fg": "#ebdbb2",
    "dim": "#a89984",
    "accent": "#d3869b",
    "border": "#3c3836",
}


def generate_github_banner(
    stimmung_mood: str = "nominal", metrics: dict[str, str] | None = None
) -> str:
    """Generate an SVG banner for the GitHub profile README."""
    metrics_str = ""
    if metrics:
        metrics_str = " | ".join(f"{k}: {v}" for k, v in metrics.items())

    # Use accent color or default based on stimmung
    color = PALETTE["accent"] if stimmung_mood != "nominal" else PALETTE["fg"]

    svg = f"""<svg width="800" height="200" xmlns="http://www.w3.org/2000/svg">
    <rect width="100%" height="100%" fill="{PALETTE["bg"]}" />
    <rect width="100%" height="100%" fill="none" stroke="{PALETTE["border"]}" stroke-width="4" />
    <text x="400" y="100" font-family="monospace" font-size="32" fill="{color}" text-anchor="middle" dominant-baseline="middle">hapax-council</text>
    <text x="400" y="140" font-family="monospace" font-size="16" fill="{PALETTE["dim"]}" text-anchor="middle" dominant-baseline="middle">stimmung: {stimmung_mood}</text>
    <text x="400" y="170" font-family="monospace" font-size="12" fill="{PALETTE["dim"]}" text-anchor="middle" dominant-baseline="middle">{metrics_str}</text>
</svg>"""
    return svg


def generate_mastodon_header(stimmung_mood: str = "nominal") -> str:
    """Generate an SVG header for Mastodon/Bluesky profiles."""
    color = PALETTE["accent"] if stimmung_mood != "nominal" else PALETTE["fg"]
    svg = f"""<svg width="1500" height="500" xmlns="http://www.w3.org/2000/svg">
    <rect width="100%" height="100%" fill="{PALETTE["bg"]}" />
    <text x="750" y="250" font-family="monospace" font-size="64" fill="{color}" text-anchor="middle" dominant-baseline="middle">Hapax Systems</text>
    <text x="750" y="320" font-family="monospace" font-size="24" fill="{PALETTE["dim"]}" text-anchor="middle" dominant-baseline="middle">Aesthetic Unity Enforced</text>
</svg>"""
    return svg


def publish_assets(dry_run: bool = False) -> None:
    """Orchestrate the generation and publication of aesthetic assets."""
    github_banner = generate_github_banner()
    mastodon_header = generate_mastodon_header()

    if dry_run:
        print(
            f"Dry run: Assets generated. Github banner length: {len(github_banner)}. Mastodon header length: {len(mastodon_header)}."
        )
        return

    # In a real implementation, this would save the SVGs to a directory or
    # call the respective publishers to upload them via API.
    # For now, we simulate the output.
    pass


if __name__ == "__main__":
    publish_assets(dry_run=True)
