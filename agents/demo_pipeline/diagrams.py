"""D2 architecture diagram generation with Gruvbox theme."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw

log = logging.getLogger(__name__)

# Valid D2 shapes — anything else gets stripped
VALID_D2_SHAPES = frozenset(
    {
        "rectangle",
        "square",
        "circle",
        "oval",
        "diamond",
        "cylinder",
        "cloud",
        "person",
        "page",
        "hexagon",
        "package",
        "queue",
        "step",
        "callout",
        "stored_data",
        "document",
        "parallelogram",
        "text",
        "code",
        "class",
        "sql_table",
        "image",
        "sequence_diagram",
    }
)

# Gruvbox theme preamble for D2.
# Theme 200 (dark) provides acceptable dark backgrounds. We set canvas colors
# explicitly. Individual node colors come from theme 200's dark palette which
# is close enough to Gruvbox (dark gray nodes, muted borders).
GRUVBOX_D2_THEME = """
vars: {
  d2-config: {
    theme-id: 200
    dark-theme-id: 200
    layout-engine: elk
    pad: 50
  }
}

style: {
  fill: "#282828"
  stroke: "#504945"
  font-color: "#ebdbb2"
}

classes: {
  service: {
    style: {
      fill: "#3c3836"
      stroke: "#fe8019"
      font-color: "#ebdbb2"
      border-radius: 8
    }
  }
  highlight: {
    style: {
      fill: "#3c3836"
      stroke: "#fabd2f"
      font-color: "#fabd2f"
      border-radius: 8
    }
  }
}
"""


def _convert_bracket_shapes(d2_source: str) -> str:
    """Convert bracket-shape syntax to valid D2.

    LLMs sometimes generate: ``node_id [shape: circle]: My Label``
    This is not valid D2. Convert to: ``node_id: "My Label" { shape: circle }``
    """
    lines = d2_source.split("\n")
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Match: id [shape: X]: Label
        m = re.match(r"^(\s*)([\w-]+)\s*\[shape:\s*(\w+)\]\s*:\s*(.+)$", stripped)
        if m:
            indent, node_id, shape, label = (
                m.group(1),
                m.group(2),
                m.group(3).lower(),
                m.group(4).strip(),
            )
            if shape not in VALID_D2_SHAPES:
                shape = "rectangle"
            result.append(f'{indent}{node_id}: "{label}" {{')
            result.append(f"{indent}  shape: {shape}")
            result.append(f"{indent}}}")
            continue
        # Match: id [shape: X] (no label)
        m2 = re.match(r"^(\s*)([\w-]+)\s*\[shape:\s*(\w+)\]\s*$", stripped)
        if m2:
            indent, node_id, shape = m2.group(1), m2.group(2), m2.group(3).lower()
            if shape not in VALID_D2_SHAPES:
                shape = "rectangle"
            result.append(f"{indent}{node_id}: {{")
            result.append(f"{indent}  shape: {shape}")
            result.append(f"{indent}}}")
            continue
        result.append(line)
    return "\n".join(result)


def _convert_inline_chain(d2_source: str) -> str:
    """Convert single-line pseudo-D2 chain format to valid multi-line D2.

    LLMs sometimes generate: ``Title: A [shape] -> B [shape] -> C [shape]``
    This is NOT valid D2. Convert to proper node definitions + edges.
    """
    # Detect the pattern: contains -> and [shape] on a single line (or very few lines)
    lines = [l.strip() for l in d2_source.strip().split("\n") if l.strip()]

    # Only apply if the source looks like a single-line chain
    # (≤3 non-empty lines, contains ->, contains [...])
    if len(lines) > 3:
        return d2_source
    full = " ".join(lines)
    if "->" not in full or "[" not in full:
        return d2_source

    # Strip leading title (e.g. "Title: A -> B -> C")
    title_match = re.match(r"^(.+?):\s*(.+?->.+)$", full)
    chain_text = title_match.group(2) if title_match else full

    # Parse nodes with optional [shape] annotations
    # Pattern: "Node Name [shape]" or just "Node Name"
    parts = re.split(r"\s*->\s*", chain_text)
    nodes: list[tuple[str, str]] = []  # (id, label, shape)

    for part in parts:
        part = part.strip()
        shape_match = re.match(r"^(.+?)\s*\[(\w+)\]\s*$", part)
        if shape_match:
            label = shape_match.group(1).strip()
            shape = shape_match.group(2).lower()
            if shape not in VALID_D2_SHAPES:
                shape = "rectangle"
        else:
            label = part
            shape = "rectangle"

        # Create a clean node ID
        node_id = re.sub(r"[^a-zA-Z0-9]", "_", label.lower()).strip("_")[:30]
        nodes.append((node_id, label, shape))

    if len(nodes) < 2:
        return d2_source

    # Generate valid D2
    d2_lines = ["direction: right", ""]
    for node_id, label, shape in nodes:
        d2_lines.append(f'{node_id}: "{label}" {{')
        d2_lines.append(f"  shape: {shape}")
        d2_lines.append("}")
        d2_lines.append("")

    # Add edges
    for i in range(len(nodes) - 1):
        d2_lines.append(f"{nodes[i][0]} -> {nodes[i + 1][0]}")

    log.info("Converted inline chain (%d nodes) to valid D2", len(nodes))
    return "\n".join(d2_lines)


def _expand_semicolons(d2_source: str) -> str:
    """Expand semicolon-separated D2 properties into multi-line format.

    LLMs generate: ``name: Label {shape: person; style: {fill: #abc}}``
    D2 expects properties on separate lines inside braces.
    """
    result_lines: list[str] = []
    for line in d2_source.split("\n"):
        stripped = line.strip()
        # Only process lines with semicolons inside braces
        if ";" not in stripped or "{" not in stripped:
            result_lines.append(line)
            continue

        # Match: prefix { prop1; prop2; ... }
        m = re.match(r"^(\s*)(.*?)\{\s*(.+?)\s*\}\s*$", line)
        if m:
            indent, prefix, inner = m.groups()
            # Split properties by semicolons
            props = [p.strip() for p in inner.split(";") if p.strip()]
            result_lines.append(f"{indent}{prefix}{{")
            for prop in props:
                # Handle nested braces: style: {fill: #abc}
                if re.match(r"\w+:\s*\{.+\}", prop):
                    # Expand nested: style: {fill: #abc} -> style block
                    nm = re.match(r"(\w+):\s*\{(.+)\}", prop)
                    if nm:
                        result_lines.append(f"{indent}  {nm.group(1)}: {{")
                        for sub in nm.group(2).split(";"):
                            sub = sub.strip()
                            if sub:
                                result_lines.append(f"{indent}    {sub}")
                        result_lines.append(f"{indent}  }}")
                else:
                    result_lines.append(f"{indent}  {prop}")
            result_lines.append(f"{indent}}}")
        else:
            result_lines.append(line)

    return "\n".join(result_lines)


def _strip_style_blocks(d2_source: str) -> str:
    """Strip inline style blocks from D2 source.

    LLMs generate per-node ``style: { fill: #abc; stroke: red }`` blocks.
    The Gruvbox theme preamble handles all styling, so these are noise that
    often cause D2 parse errors. We strip them entirely.

    Also strips standalone style property lines (style.fill, etc.).
    """
    lines = d2_source.split("\n")
    result: list[str] = []
    depth = 0
    in_style_block = False

    for line in lines:
        stripped = line.strip()

        # Track style block entry
        if re.match(r"^\s*style\s*:\s*\{", stripped) or re.match(r"^\s*style\s*\{", stripped):
            in_style_block = True
            depth = 1
            # Check if it's a single-line style: { ... }
            if "}" in stripped:
                in_style_block = False
            continue

        if in_style_block:
            depth += stripped.count("{") - stripped.count("}")
            if depth <= 0:
                in_style_block = False
            continue

        # Strip inline style.X properties
        if re.match(
            r"^\s*style\.(fill|stroke|font-color|stroke-dash|border-radius|opacity|font-size|bold|italic|underline|text-transform|3d|multiple|double-border|shadow|animated|font):",
            stripped,
        ):
            continue

        result.append(line)

    return "\n".join(result)


def sanitize_d2_source(d2_source: str) -> str:
    """Sanitize LLM-generated D2 source to fix common issues.

    - Converts single-line chain format (A [shape] -> B [shape]) to valid D2
    - Expands semicolon-separated properties to multi-line
    - Strips all style blocks and style.X properties (Gruvbox theme handles colors)
    - Removes invalid shape declarations (eye, mic, phone, server, etc.)
    - Quotes unquoted labels containing special characters (colons, parens, etc.)
    - Strips markdown fences that LLMs sometimes wrap D2 in
    """
    # Strip markdown code fences
    d2_source = re.sub(r"^```(?:d2)?\s*\n?", "", d2_source.strip())
    d2_source = re.sub(r"\n?```\s*$", "", d2_source.strip())

    # Pre-pass: convert bracket-shape syntax BEFORE chain detection
    # "id [shape: X]: Label" → "id: Label { shape: X }" (valid D2)
    d2_source = _convert_bracket_shapes(d2_source)

    # Convert inline chain format if detected
    d2_source = _convert_inline_chain(d2_source)

    # Expand semicolons to multi-line (before style stripping)
    d2_source = _expand_semicolons(d2_source)

    # Strip all style blocks and inline style properties
    d2_source = _strip_style_blocks(d2_source)

    lines = d2_source.split("\n")
    cleaned: list[str] = []

    for line in lines:
        stripped = line.strip()

        # Skip empty lines from style stripping
        if not stripped:
            cleaned.append(line)
            continue

        # Remove invalid shape declarations
        shape_match = re.match(r"^\s*shape:\s*(\w+)", stripped)
        if shape_match:
            shape = shape_match.group(1).lower()
            if shape not in VALID_D2_SHAPES:
                log.info("Stripping invalid D2 shape: %s", shape)
                continue  # Skip the line entirely

        # Strip "near:" referencing other objects (ELK doesn't support dynamic near)
        near_match = re.match(r"^\s*near:\s*(.+)", stripped)
        if near_match:
            val = near_match.group(1).strip()
            # Only constant values like "top-center" are valid in ELK
            if val not in (
                "top-left",
                "top-center",
                "top-right",
                "center-left",
                "center-right",
                "bottom-left",
                "bottom-center",
                "bottom-right",
            ):
                log.info("Stripping unsupported D2 'near' reference: %s", val)
                continue

        # Strip incomplete connections: "X ->" or "-> Y" (missing source or destination)
        if re.match(r"^.*->\s*$", stripped) or re.match(r"^\s*->", stripped):
            log.info("Stripping incomplete D2 connection: %s", stripped[:60])
            continue

        # Strip "map value without key" — standalone colons or values without parent
        if re.match(r"^\s*:\s", stripped):
            log.info("Stripping keyless map value: %s", stripped[:60])
            continue

        # Strip lines that are just free-text inside braces (LLM prose / routing tables)
        # e.g. "'fast' → Claude Haiku" or "Handles all model routing"
        if re.match(r"^\s*['\"]", stripped) or re.match(r"^\s*→", stripped):
            log.info("Stripping free-text line: %s", stripped[:60])
            continue

        # Fix dot-notation in edge references: "Node.property -> Target" → strip the .property
        # D2 interprets dots as attribute access which causes "substitutions must begin on {"
        dot_edge = re.match(r"^(\s*)(.*?)\.([\w-]+)\s*(->)\s*(.+)$", line)
        if dot_edge:
            indent = dot_edge.group(1)
            src = dot_edge.group(2).strip()
            arrow = dot_edge.group(4)
            rest = dot_edge.group(5).strip()
            line = f"{indent}{src} {arrow} {rest}"
            log.info("Stripped dot-notation from edge: %s.%s", src, dot_edge.group(3))

        # Escape $ in edge labels — D2 interprets $ as substitution variables
        # e.g. "A -> B: $37.47/day" → "A -> B: 37.47/day"
        if "->" in stripped and "$" in stripped:
            line = line.replace("$", "")

        # Quote unquoted inline labels that contain special chars
        # Pattern: `NodeId: Some Label With Special Chars` (not followed by { and not a keyword)
        label_match = re.match(r"^(\s*)([\w-]+)\s*:\s*(.+)$", line)
        if label_match:
            indent, name, value = label_match.groups()
            value = value.rstrip()
            d2_keywords = (
                "shape",
                "style",
                "label",
                "direction",
                "vars",
                "classes",
                "d2-config",
                "theme-id",
                "dark-theme-id",
                "layout-engine",
                "pad",
                "fill",
                "stroke",
                "font-color",
                "border-radius",
                "opacity",
                "near",
                "icon",
                "width",
                "height",
                "tooltip",
                "link",
                "constraint",
                "source-arrowhead",
                "target-arrowhead",
            )
            if name.lower() not in d2_keywords and not value.startswith(('"', "'", "{")):
                # Handle block-opening labels: `name: Label With:Colon {`
                block_match = re.match(r"^(.+?)\s*(\{)\s*$", value)
                if block_match:
                    label_part = block_match.group(1)
                    if re.search(
                        r"[:()\[\]@#$%^&*+=|<>!?,;/]", label_part
                    ) and not label_part.startswith('"'):
                        line = f'{indent}{name}: "{label_part}" {{'
                elif not value.endswith(("{", "}")):
                    # Regular label (no block opening)
                    if re.search(r"[:()\[\]@#$%^&*+=|<>!?,;/]", value):
                        line = f'{indent}{name}: "{value}"'

        cleaned.append(line)

    return "\n".join(cleaned)


def is_d2_available() -> bool:
    """Check if D2 CLI is installed."""
    return shutil.which("d2") is not None


def _try_d2_render(d2_source: str, output_path: Path) -> bool:
    """Try to render D2 source. Returns True on success."""
    with tempfile.NamedTemporaryFile(suffix=".d2", mode="w", delete=False) as f:
        f.write(d2_source)
        d2_file = Path(f.name)

    try:
        result = subprocess.run(
            ["d2", "--theme", "200", "--pad", "50", str(d2_file), str(output_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            log.warning("D2 render failed: %s", result.stderr[:200])
            return False
        return True
    finally:
        d2_file.unlink(missing_ok=True)


def _simplify_d2(d2_source: str) -> str:
    """Extract just nodes and edges from D2 source, dropping all nested blocks."""
    nodes: dict[str, str] = {}  # id -> label
    edges: list[str] = []

    for line in d2_source.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Match edges: A -> B or "Multi Word" -> "Other" (with optional label)
        edge_match = re.match(r"^(.+?)\s*->\s*(.+?)(?:\s*[:{].*)?$", stripped)
        if edge_match:
            src = edge_match.group(1).strip().strip('"')
            tgt = edge_match.group(2).strip().strip('"')
            # Add nodes if not already known
            src_id = re.sub(r"[^a-zA-Z0-9]", "_", src.lower()).strip("_")
            tgt_id = re.sub(r"[^a-zA-Z0-9]", "_", tgt.lower()).strip("_")
            if src_id not in nodes:
                nodes[src_id] = src
            if tgt_id not in nodes:
                nodes[tgt_id] = tgt
            edges.append(f"{src_id} -> {tgt_id}")
            continue

        # Match node with inline label: name: "Label Text" or name: Label Text {
        inline_label_match = re.match(r'^([\w-]+)\s*:\s*["\'](.+?)["\']', stripped)
        if inline_label_match:
            name = inline_label_match.group(1)
            if name not in ("style", "vars", "classes", "direction", "shape", "label"):
                nodes[name] = inline_label_match.group(2)
            continue

        # Match node definitions: name: { or "Multi Word Name": { or Multi Word Name {
        node_match = re.match(r"^([\w][\w\s]*?)\s*(?::\s*)?\{", stripped)
        if node_match:
            name = node_match.group(1).strip()
            name_id = re.sub(r"[^a-zA-Z0-9]", "_", name.lower()).strip("_")
            if name_id not in ("style", "vars", "classes", "direction"):
                nodes[name_id] = name.replace("-", " ").replace("_", " ")
            continue

        # Match labels inside blocks: label: "text"
        label_match = re.match(r'^\s*label:\s*["\']?(.+?)["\']?\s*$', stripped)
        if label_match and nodes:
            last_key = list(nodes.keys())[-1]
            nodes[last_key] = label_match.group(1)

        # Match nested node with inline label: Name: {label: "text"}
        nested_match = re.match(r'^\s*([\w-]+)\s*:\s*\{label:\s*["\'](.+?)["\']\}', stripped)
        if nested_match:
            name = nested_match.group(1)
            if name not in ("style", "vars", "classes"):
                nodes[name] = nested_match.group(2)

        # Match direction
        dir_match = re.match(r"^direction:\s*(\w+)", stripped)
        if dir_match:
            edges.insert(0, f"direction: {dir_match.group(1)}")

    lines = []
    for nid, label in nodes.items():
        lines.append(f'{nid}: "{label}"')
    lines.extend(edges)

    return "\n".join(lines)


def render_d2(d2_source: str, output_path: Path, size: tuple[int, int] = (1920, 1080)) -> Path:
    """Render D2 source to PNG. Falls back to simplified D2, then Pillow."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not is_d2_available():
        log.warning("D2 not installed — generating fallback image")
        return _fallback_diagram(d2_source, output_path, size)

    # Sanitize LLM-generated source before rendering
    sanitized = sanitize_d2_source(d2_source)

    # Try 1: Full sanitized source with Gruvbox theme
    themed_source = GRUVBOX_D2_THEME + "\n" + sanitized
    if _try_d2_render(themed_source, output_path):
        return output_path

    # Try 2: Simplified source (just nodes + edges)
    log.info("Retrying with simplified D2 source")
    simplified = _simplify_d2(d2_source)
    if simplified.strip():
        themed_simple = GRUVBOX_D2_THEME + "\n" + simplified
        if _try_d2_render(themed_simple, output_path):
            return output_path

    # Try 3: Pillow fallback with visual node layout
    log.info("Using Pillow fallback for diagram")
    return _fallback_diagram(d2_source, output_path, size)


def _extract_nodes_and_edges(d2_source: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Extract node labels and edges from D2 source for fallback rendering."""
    nodes: list[str] = []
    edges: list[tuple[str, str]] = []

    for line in d2_source.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("direction"):
            continue

        # Match edges: A -> B or A -> B: label
        edge_match = re.match(r"^(\w[\w\s]*?)\s*->\s*(\w[\w\s]*?)(?:\s*[:{]|$)", stripped)
        if edge_match:
            edges.append((edge_match.group(1).strip(), edge_match.group(2).strip()))
            continue

        # Match node definitions: name: { or name: "label" or label: "text"
        label_match = re.match(r"^(\w[\w\s]*?):\s*\{", stripped)
        if label_match:
            name = label_match.group(1).strip()
            if name not in ("style", "vars", "classes", "shape"):
                nodes.append(name)
            continue

        # Match inline label
        inline_match = re.match(r'^\s*label:\s*["\']?(.+?)["\']?\s*$', stripped)
        if inline_match and nodes:
            # Replace last node name with its label
            nodes[-1] = inline_match.group(1)

    return nodes, edges


def _fallback_diagram(d2_source: str, output_path: Path, size: tuple[int, int]) -> Path:
    """Generate a Pillow diagram showing nodes and connections from D2 source."""
    from agents.demo_pipeline.title_cards import _get_font

    BG = (40, 40, 40)  # #282828
    FG = (235, 219, 178)  # #ebdbb2
    ACCENT = (250, 189, 47)  # #fabd2f
    ORANGE = (254, 128, 25)  # #fe8019
    SUBTLE = (168, 153, 132)  # #a89984

    img = Image.new("RGB", size, BG)
    draw = ImageDraw.Draw(img)

    nodes, edges = _extract_nodes_and_edges(d2_source)

    font_title = _get_font(32)
    font_node = _get_font(22)
    font_small = _get_font(16)

    if not nodes:
        # Truly empty — show generic diagram placeholder
        draw.text(
            (size[0] // 2, size[1] // 2),
            "Architecture Diagram",
            fill=ACCENT,
            font=font_title,
            anchor="mm",
        )
        img.save(output_path)
        return output_path

    # Layout: horizontal flow of boxes with arrows
    margin = 80
    usable_w = size[0] - 2 * margin
    size[1] - 2 * margin

    # Limit to 8 nodes for readability
    display_nodes = nodes[:8]
    n = len(display_nodes)

    if n <= 4:
        # Single row layout
        box_w = min(280, usable_w // n - 40)
        box_h = 80
        spacing = usable_w // n
        y_center = size[1] // 2

        positions: list[tuple[int, int]] = []
        for i in range(n):
            x = margin + spacing * i + spacing // 2
            positions.append((x, y_center))

        for i, (x, y) in enumerate(positions):
            # Draw rounded box
            x1, y1 = x - box_w // 2, y - box_h // 2
            x2, y2 = x + box_w // 2, y + box_h // 2
            draw.rounded_rectangle(
                [x1, y1, x2, y2], radius=12, fill=(60, 56, 54), outline=ORANGE, width=2
            )
            label = textwrap.shorten(display_nodes[i], width=20, placeholder="...")
            draw.text((x, y), label, fill=FG, font=font_node, anchor="mm")

            # Draw arrow to next
            if i < n - 1:
                next_x = positions[i + 1][0]
                arrow_start = x2 + 8
                arrow_end = next_x - box_w // 2 - 8
                if arrow_end > arrow_start:
                    draw.line([(arrow_start, y), (arrow_end, y)], fill=SUBTLE, width=2)
                    draw.polygon(
                        [(arrow_end, y), (arrow_end - 10, y - 6), (arrow_end - 10, y + 6)],
                        fill=SUBTLE,
                    )
    else:
        # Two-row layout
        top_n = (n + 1) // 2
        bot_n = n - top_n
        box_w = min(250, usable_w // max(top_n, bot_n) - 40)
        box_h = 70
        y_top = size[1] // 2 - 80
        y_bot = size[1] // 2 + 80

        positions = []
        for i in range(top_n):
            spacing = usable_w // top_n
            x = margin + spacing * i + spacing // 2
            positions.append((x, y_top))
        for i in range(bot_n):
            spacing = usable_w // bot_n
            x = margin + spacing * i + spacing // 2
            positions.append((x, y_bot))

        for i, (x, y) in enumerate(positions):
            x1, y1 = x - box_w // 2, y - box_h // 2
            x2, y2 = x + box_w // 2, y + box_h // 2
            draw.rounded_rectangle(
                [x1, y1, x2, y2], radius=12, fill=(60, 56, 54), outline=ORANGE, width=2
            )
            label = textwrap.shorten(display_nodes[i], width=18, placeholder="...")
            draw.text((x, y), label, fill=FG, font=font_node, anchor="mm")

    # Subtitle
    draw.text(
        (size[0] // 2, size[1] - 40),
        "System Architecture",
        fill=SUBTLE,
        font=font_small,
        anchor="mm",
    )

    img.save(output_path)
    return output_path
