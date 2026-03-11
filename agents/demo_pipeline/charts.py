"""Gruvbox-themed data visualization for demos."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import numpy as np

log = logging.getLogger(__name__)

MPLSTYLE_PATH = Path(__file__).resolve().parent.parent.parent / "profiles" / "gruvbox.mplstyle"

# Gruvbox colors for manual use
COLORS = {
    "orange": "#fe8019",
    "yellow": "#fabd2f",
    "green": "#b8bb26",
    "blue": "#83a598",
    "purple": "#d3869b",
    "aqua": "#8ec07c",
    "red": "#fb4934",
    "fg": "#ebdbb2",
    "bg": "#282828",
    "bg1": "#3c3836",
}


def _normalize_chart_spec(spec: dict) -> dict:
    """Normalize Chart.js-style specs to our Matplotlib-style format.

    The LLM sometimes generates Chart.js format with 'datasets' and 'options'
    instead of our expected format with 'labels' and 'values'.
    """
    data = spec.get("data", {})

    # Chart.js format: data.labels + data.datasets[0].data
    # Preserve datasets array for multi-series charts (stacked-bar, stacked-line, multi-line)
    chart_type = spec.get("type", "bar")
    multi_series_types = ("stacked-bar", "stacked-line")
    if "datasets" in data and "labels" in data and chart_type not in multi_series_types:
        datasets = data["datasets"]
        if datasets and isinstance(datasets, list):
            first = datasets[0]
            values = first.get("data", first.get("values", []))
            labels = data["labels"]
            spec["data"] = {"labels": labels, "values": values}
            if first.get("label"):
                spec["data"]["label"] = first["label"]
            # Inherit colors from dataset backgroundColor if present
            bg_colors = first.get("backgroundColor")
            if bg_colors:
                spec["data"]["colors"] = bg_colors if isinstance(bg_colors, list) else [bg_colors] * len(labels)
            log.info("Normalized Chart.js format to Matplotlib format")

    # Chart.js wraps config in data.datasets for line charts too
    # Also handle: options.scales → xlabel/ylabel
    options = spec.pop("options", None)
    if options and isinstance(options, dict):
        scales = options.get("scales", {})
        x_axis = scales.get("x", {})
        y_axis = scales.get("y", {})
        if x_axis.get("title", {}).get("text") and not spec.get("xlabel"):
            spec["xlabel"] = x_axis["title"]["text"]
        if y_axis.get("title", {}).get("text") and not spec.get("ylabel"):
            spec["ylabel"] = y_axis["title"]["text"]

    return spec


def render_chart(chart_spec: str, output_path: Path, size: tuple[int, int] = (1920, 1080)) -> Path:
    """Render a chart from a JSON specification string.

    chart_spec JSON format:
    {
        "type": "bar" | "horizontal-bar" | "line" | "area" | "pie" | "gauge",
        "title": str,
        "data": {...},  # type-specific
        "xlabel": str,  # optional
        "ylabel": str,  # optional
    }
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        spec = json.loads(chart_spec)
    except (json.JSONDecodeError, TypeError) as e:
        log.warning("Chart spec is not valid JSON, generating fallback: %s", e)
        spec = {"title": "Data Visualization"}
        _render_fallback(spec, output_path, (size[0] / 150, size[1] / 150), 150)
        return output_path

    spec = _normalize_chart_spec(spec)
    chart_type = spec.get("type", "bar")

    # Load Gruvbox style
    if MPLSTYLE_PATH.exists():
        plt.style.use(str(MPLSTYLE_PATH))

    dpi = 150
    fig_w = size[0] / dpi
    fig_h = size[1] / dpi

    renderers = {
        "bar": _render_bar,
        "horizontal-bar": _render_horizontal_bar,
        "stacked-bar": _render_stacked_bar,
        "line": _render_line,
        "area": _render_area,
        "pie": _render_pie,
        "gauge": _render_gauge,
        "network": _render_network,
        "graph": _render_network,
        "grouped-bar": _render_bar,
        "donut": _render_pie,
        "stacked-line": _render_multi_line,
        "multi-line": _render_multi_line,
        "timeline": _render_timeline,
        "schedule": _render_timeline,
        "sankey": _render_network,  # LLMs hallucinate sankey; closest is network
        "flow": _render_network,
        "funnel": _render_bar,  # funnel → horizontal bar approximation
        "heatmap": _render_bar,  # fallback
        "treemap": _render_pie,  # treemap → pie approximation
        "radar": _render_bar,  # fallback
        # Underscore variants (LLMs sometimes use underscores instead of hyphens)
        "stacked_bar": _render_stacked_bar,
        "horizontal_bar": _render_horizontal_bar,
        "stacked_line": _render_multi_line,
        "multi_line": _render_multi_line,
        # Compound hallucinations
        "gauge_with_history": _render_gauge,
        "bar_chart": _render_bar,
        "pie_chart": _render_pie,
        "line_chart": _render_line,
    }

    try:
        renderer = renderers.get(chart_type)
        if not renderer:
            # Try to extract a known base type from compound names like "service-overview"
            base_types = ["timeline", "bar", "line", "pie", "gauge", "area", "network"]
            for base in base_types:
                if base in chart_type:
                    renderer = renderers[base]
                    log.info("Mapped unknown chart type '%s' to '%s'", chart_type, base)
                    break
        if renderer:
            renderer(spec, output_path, (fig_w, fig_h), dpi)
        else:
            log.warning("Unknown chart type '%s', rendering as bar", chart_type)
            # Try bar if data has labels/values, otherwise fallback
            data = spec.get("data", {})
            if "labels" in data and "values" in data:
                _render_bar(spec, output_path, (fig_w, fig_h), dpi)
            else:
                _render_fallback(spec, output_path, (fig_w, fig_h), dpi)
    except Exception as e:
        log.warning("Chart render failed (%s), generating fallback: %s", chart_type, e)
        _render_fallback(spec, output_path, (fig_w, fig_h), dpi)

    return output_path


def _render_fallback(spec: dict, output_path: Path, figsize: tuple, dpi: int) -> None:
    """Render a simple text-only fallback when chart spec can't be parsed."""
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    title = spec.get("title", "Data Visualization")
    ax.text(0.5, 0.5, title, ha="center", va="center", fontsize=32,
            color=COLORS["fg"], transform=ax.transAxes)
    ax.set_axis_off()
    fig.savefig(output_path)
    plt.close(fig)


def _render_bar(spec: dict, output_path: Path, figsize: tuple, dpi: int) -> None:
    data = spec["data"]
    labels = data["labels"]
    values = data["values"]
    colors = data.get("colors") or [COLORS["orange"]] * len(labels)

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    ax.bar(labels, values, color=colors)
    ax.set_title(spec.get("title", ""))
    if spec.get("xlabel"):
        ax.set_xlabel(spec["xlabel"])
    if spec.get("ylabel"):
        ax.set_ylabel(spec["ylabel"])
    fig.savefig(output_path)
    plt.close(fig)


def _render_horizontal_bar(spec: dict, output_path: Path, figsize: tuple, dpi: int) -> None:
    data = spec["data"]
    labels = data["labels"]
    values = data["values"]
    colors = data.get("colors") or [COLORS["orange"]] * len(labels)

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    ax.barh(labels, values, color=colors)
    ax.set_title(spec.get("title", ""))
    if spec.get("xlabel"):
        ax.set_xlabel(spec["xlabel"])
    if spec.get("ylabel"):
        ax.set_ylabel(spec["ylabel"])
    ax.invert_yaxis()  # Top-to-bottom reading order
    fig.savefig(output_path)
    plt.close(fig)


def _render_stacked_bar(spec: dict, output_path: Path, figsize: tuple, dpi: int) -> None:
    """Render stacked bar chart. Expects datasets with multiple value series."""
    data = spec["data"]
    labels = data.get("labels", [])
    palette = [COLORS["orange"], COLORS["yellow"], COLORS["green"],
               COLORS["blue"], COLORS["purple"], COLORS["aqua"], COLORS["red"]]

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)

    # Handle datasets format: [{label, data}, ...]
    datasets = data.get("datasets", [])
    if datasets:
        x = np.arange(len(labels))
        bottom = np.zeros(len(labels))
        for i, ds in enumerate(datasets):
            values = ds.get("data", ds.get("values", []))
            color = palette[i % len(palette)]
            ax.bar(x, values, bottom=bottom, label=ds.get("label", f"Series {i+1}"), color=color)
            bottom += np.array(values, dtype=float)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha="right")
        ax.legend()
    else:
        # Fallback to regular bar if no datasets
        values = data.get("values", [])
        ax.bar(labels, values, color=COLORS["orange"])

    ax.set_title(spec.get("title", ""))
    if spec.get("xlabel"):
        ax.set_xlabel(spec["xlabel"])
    if spec.get("ylabel"):
        ax.set_ylabel(spec["ylabel"])
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)


def _render_line(spec: dict, output_path: Path, figsize: tuple, dpi: int) -> None:
    data = spec["data"]

    # Handle multiple data formats the LLM might generate
    if "x" in data and "y" in data:
        x = data["x"]
        y = data["y"]
    elif "labels" in data and "values" in data:
        # Bar-style format used for line chart
        x = data["labels"]
        y = data["values"]
    elif "datasets" in data:
        # Chart.js line format
        ds = data["datasets"][0]
        y = ds.get("data", [])
        x = data.get("labels", list(range(len(y))))
    else:
        # Fallback: just use values as y with sequential x
        y = list(data.values())[0] if data else [0]
        x = list(range(len(y)))

    label = data.get("label", "")

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    ax.plot(x, y, label=label, color=COLORS["orange"])
    ax.set_title(spec.get("title", ""))
    if label:
        ax.legend()
    if spec.get("xlabel"):
        ax.set_xlabel(spec["xlabel"])
    if spec.get("ylabel"):
        ax.set_ylabel(spec["ylabel"])
    fig.savefig(output_path)
    plt.close(fig)


def _render_area(spec: dict, output_path: Path, figsize: tuple, dpi: int) -> None:
    data = spec["data"]

    if "x" in data and "y" in data:
        x = data["x"]
        y = data["y"]
    elif "labels" in data and "values" in data:
        x = data["labels"]
        y = data["values"]
    else:
        y = list(data.values())[0] if data else [0]
        x = list(range(len(y)))

    label = data.get("label", "")

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    ax.fill_between(range(len(y)), y, alpha=0.3, color=COLORS["orange"])
    ax.plot(range(len(y)), y, color=COLORS["orange"], label=label)
    ax.set_xticks(range(len(x)))
    ax.set_xticklabels(x)
    ax.set_title(spec.get("title", ""))
    if label:
        ax.legend()
    if spec.get("xlabel"):
        ax.set_xlabel(spec["xlabel"])
    if spec.get("ylabel"):
        ax.set_ylabel(spec["ylabel"])
    fig.savefig(output_path)
    plt.close(fig)


def _render_pie(spec: dict, output_path: Path, figsize: tuple, dpi: int) -> None:
    data = spec["data"]
    labels = data["labels"]
    values = data["values"]
    palette = [COLORS["orange"], COLORS["yellow"], COLORS["green"],
               COLORS["blue"], COLORS["purple"], COLORS["aqua"], COLORS["red"]]
    colors = data.get("colors") or [palette[i % len(palette)] for i in range(len(labels))]

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    wedges, texts, autotexts = ax.pie(
        values, labels=labels, colors=colors, autopct="%1.0f%%",
        textprops={"color": COLORS["fg"]},
    )
    for t in autotexts:
        t.set_color(COLORS["bg"])
        t.set_fontweight("bold")
    ax.set_title(spec.get("title", ""))
    fig.savefig(output_path)
    plt.close(fig)


def _render_gauge(spec: dict, output_path: Path, figsize: tuple, dpi: int) -> None:
    data = spec["data"]
    value = data["value"]
    max_val = data["max"]
    label = data.get("label", "")

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi, subplot_kw={"projection": "polar"})

    # Semicircle gauge
    ratio = value / max_val
    theta = np.linspace(np.pi, 0, 100)

    # Background arc
    ax.plot(theta, [1] * 100, color=COLORS["bg1"], linewidth=20, solid_capstyle="round")

    # Value arc
    fill_theta = np.linspace(np.pi, np.pi - (np.pi * ratio), int(100 * ratio))
    color = COLORS["green"] if ratio > 0.8 else COLORS["yellow"] if ratio > 0.5 else COLORS["red"]
    if len(fill_theta) > 1:
        ax.plot(fill_theta, [1] * len(fill_theta), color=color, linewidth=20, solid_capstyle="round")

    ax.set_ylim(0, 1.5)
    ax.set_axis_off()
    ax.text(0, 0.3, f"{value}/{max_val}", ha="center", va="center", fontsize=48, color=COLORS["fg"])
    ax.text(0, -0.1, label, ha="center", va="center", fontsize=24, color=COLORS["fg"])
    ax.set_title(spec.get("title", ""), pad=20)

    fig.savefig(output_path)
    plt.close(fig)


def _render_multi_line(spec: dict, output_path: Path, figsize: tuple, dpi: int) -> None:
    """Render multiple line series on a single chart (stacked-line, multi-line)."""
    data = spec["data"]
    labels = data.get("labels", [])
    datasets = data.get("datasets", [])
    palette = [COLORS["orange"], COLORS["yellow"], COLORS["green"],
               COLORS["blue"], COLORS["purple"], COLORS["aqua"], COLORS["red"]]

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)

    if datasets:
        x = list(range(len(labels)))
        for i, ds in enumerate(datasets):
            values = ds.get("data", ds.get("values", []))
            color = palette[i % len(palette)]
            ax.plot(x, values, label=ds.get("label", f"Series {i+1}"),
                    color=color, linewidth=2, marker="o", markersize=4)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha="right")
        ax.legend()
    else:
        # Fallback to single line
        _render_line(spec, output_path, figsize, dpi)
        return

    ax.set_title(spec.get("title", ""))
    if spec.get("xlabel"):
        ax.set_xlabel(spec["xlabel"])
    if spec.get("ylabel"):
        ax.set_ylabel(spec["ylabel"])
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)


def _render_timeline(spec: dict, output_path: Path, figsize: tuple, dpi: int) -> None:
    """Render a timeline of events as a horizontal schedule."""
    data = spec["data"]
    events = data.get("events", [])
    palette = [COLORS["orange"], COLORS["yellow"], COLORS["green"],
               COLORS["blue"], COLORS["purple"], COLORS["aqua"], COLORS["red"]]

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)

    if not events:
        # Fallback: try labels/values as time/event pairs
        labels = data.get("labels", [])
        values = data.get("values", [])
        events = [{"time": str(l), "event": str(v)} for l, v in zip(labels, values)]

    if events:
        y_positions = list(range(len(events)))
        times = [e.get("time", str(i)) for i, e in enumerate(events)]
        event_names = [e.get("event", e.get("label", "")) for e in events]

        # Horizontal timeline with dots and labels
        for i, (t, name) in enumerate(zip(times, event_names)):
            color = palette[i % len(palette)]
            ax.scatter(i, 0, s=200, color=color, zorder=3)
            ax.annotate(
                f"{t}\n{name}",
                (i, 0),
                textcoords="offset points",
                xytext=(0, 20 if i % 2 == 0 else -30),
                ha="center", va="bottom" if i % 2 == 0 else "top",
                fontsize=9, color=COLORS["fg"],
                arrowprops=dict(arrowstyle="-", color=COLORS["fg"], alpha=0.3),
            )

        # Draw connecting line
        ax.plot(range(len(events)), [0] * len(events),
                color=COLORS["fg"], alpha=0.3, linewidth=2)
        ax.set_xlim(-0.5, len(events) - 0.5)
        ax.set_ylim(-1, 1)
    else:
        ax.text(0.5, 0.5, spec.get("title", "Timeline"),
                ha="center", va="center", fontsize=32,
                color=COLORS["fg"], transform=ax.transAxes)

    ax.set_axis_off()
    ax.set_title(spec.get("title", ""))
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)


def _render_network(spec: dict, output_path: Path, figsize: tuple, dpi: int) -> None:
    """Render a network/graph chart showing nodes and connections."""
    import networkx as nx

    data = spec["data"]
    palette = [COLORS["orange"], COLORS["yellow"], COLORS["green"],
               COLORS["blue"], COLORS["purple"], COLORS["aqua"], COLORS["red"]]

    G = nx.Graph()

    # Support multiple data formats the LLM might generate
    nodes = data.get("nodes", [])
    edges = data.get("edges", data.get("links", data.get("connections", [])))

    if nodes and isinstance(nodes[0], str):
        for n in nodes:
            G.add_node(n)
    elif nodes and isinstance(nodes[0], dict):
        for n in nodes:
            node_id = n.get("id", n.get("label", n.get("name", str(n))))
            G.add_node(node_id, label=n.get("label", n.get("name", str(node_id))))

    if edges:
        for e in edges:
            if isinstance(e, dict):
                src = e.get("source", e.get("from", ""))
                tgt = e.get("target", e.get("to", ""))
                if src and tgt:
                    G.add_edge(src, tgt, label=e.get("label", ""))
            elif isinstance(e, (list, tuple)) and len(e) >= 2:
                G.add_edge(e[0], e[1])

    # Fallback: if no edges parsed, create a simple chain from nodes
    if G.number_of_edges() == 0 and G.number_of_nodes() > 1:
        node_list = list(G.nodes())
        for i in range(len(node_list) - 1):
            G.add_edge(node_list[i], node_list[i + 1])

    # Fallback: if still empty, create from labels/values as a star graph
    if G.number_of_nodes() == 0:
        labels = data.get("labels", [])
        center = spec.get("title", "Center")
        G.add_node(center)
        for lbl in labels:
            G.add_node(lbl)
            G.add_edge(center, lbl)

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)

    if G.number_of_nodes() == 0:
        ax.text(0.5, 0.5, spec.get("title", "Network"), ha="center", va="center",
                fontsize=32, color=COLORS["fg"], transform=ax.transAxes)
        ax.set_axis_off()
    else:
        pos = nx.spring_layout(G, seed=42, k=2.0 / max(1, G.number_of_nodes() ** 0.5))
        node_colors = [palette[i % len(palette)] for i in range(G.number_of_nodes())]

        labels = {}
        for n in G.nodes():
            labels[n] = G.nodes[n].get("label", str(n))

        nx.draw_networkx_nodes(G, pos, ax=ax, node_color=node_colors,
                               node_size=2000, edgecolors=COLORS["bg1"], linewidths=2)
        nx.draw_networkx_edges(G, pos, ax=ax, edge_color=COLORS["fg"],
                               width=2, alpha=0.6)
        nx.draw_networkx_labels(G, pos, labels=labels, ax=ax,
                                font_size=10, font_color=COLORS["fg"], font_weight="bold")

        edge_labels = {(u, v): d.get("label", "") for u, v, d in G.edges(data=True) if d.get("label")}
        if edge_labels:
            nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, ax=ax,
                                         font_size=8, font_color=COLORS["yellow"])

        ax.set_axis_off()

    ax.set_title(spec.get("title", ""))
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
