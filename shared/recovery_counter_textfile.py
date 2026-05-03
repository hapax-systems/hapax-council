"""Recovery counter / gauge writer for node_exporter textfile collector.

Writes Prometheus exposition-format `.prom` files under
`/var/lib/node_exporter/textfile_collector/`. node_exporter scrapes
the directory and exposes everything as part of its own `/metrics`
output, so a small recovery script (xHCI / BT firmware watchdog) or
per-tick health evaluator can publish counters and gauges without
running its own HTTP server or pidfile.

Two write modes are supported because the textfile collector reads
the file as-is (no aggregation across writes):

  * **Counter** — read current per-label value, add `delta`, write
    back. The script's own state survives across watchdog restarts
    because the textfile is the source of truth.
  * **Gauge** — write a single per-label value verbatim, replacing
    whatever was there.

Both writes are atomic on POSIX: write to a sibling `.tmp` file in
the same directory, then `os.replace` over the target. node_exporter
will never read a half-written file.

Threadsafe within one process (file operations don't share state);
multi-process callers must serialise externally if they share the
same metric name (none currently do — each watchdog owns its own
metric file).

Spec:
  * `audio-audit-H3-prometheus-recovery-counters` cc-task ACs.
  * Pattern reference: `agents/novelty_emitter/_emitter.py`
    (textfile collector for `hapax_novelty_shift_*`).

Cc-task: `audio-audit-H3-prometheus-recovery-counters`
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping
from pathlib import Path

log = logging.getLogger(__name__)

#: Default node_exporter textfile collector directory. Override per
#: file when running under a different collector path.
DEFAULT_COLLECTOR_DIR = Path("/var/lib/node_exporter/textfile_collector")

#: Match a Prometheus exposition-format counter / gauge line:
#: `metric_name{label="val",...} numeric_value`
#: We only care about lines that match the metric name + label-set
#: we're updating; comments + other metrics pass through.
_METRIC_LINE_RE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)"
    r"(?P<labels>\{[^}]*\})?"
    r"\s+(?P<value>[+-]?[\d.]+(?:[eE][+-]?\d+)?)"
    r"\s*$"
)


def _format_labels(labels: Mapping[str, str]) -> str:
    """Render a label dict as a Prometheus exposition label-set fragment.

    Empty labels render as the empty string (no curly braces) so
    `metric_name 1.0` is a valid output. Sorted keys for stable
    diffs across writes.
    """
    if not labels:
        return ""
    parts = []
    for key in sorted(labels):
        # Escape backslash, double-quote, newline per Prometheus spec.
        v = str(labels[key]).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        parts.append(f'{key}="{v}"')
    return "{" + ",".join(parts) + "}"


def _atomic_write(path: Path, content: str) -> None:
    """Write `content` to `path` atomically (tmp + replace).

    Creates parent directory if missing — the watchdogs may run
    before any prior textfile-collector emission, so a fresh
    `/var/lib/node_exporter/textfile_collector/` is plausible.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def increment_counter(
    *,
    metric_name: str,
    labels: Mapping[str, str],
    help_text: str,
    delta: float = 1.0,
    collector_dir: Path = DEFAULT_COLLECTOR_DIR,
    file_basename: str | None = None,
) -> float:
    """Atomically read+increment a textfile-collector counter.

    Parameters
    ----------
    metric_name:
        Bare metric name, e.g. ``hapax_xhci_recovery_total``.
    labels:
        Per-emission label set, e.g. ``{"controller": "0000:71:00.0"}``.
        Empty mapping renders an unlabelled metric.
    help_text:
        ``# HELP`` line text. Mandatory so the metric is documented in
        the exposition.
    delta:
        Increment amount (default 1.0). Must be >= 0; counters never
        decrement.
    collector_dir:
        Override the default ``/var/lib/...`` location for tests.
    file_basename:
        Override the textfile basename. Defaults to
        ``{metric_name}.prom``; pass a custom name when one file
        carries several related metrics (e.g.
        ``hapax_audio_recovery.prom`` for the H3 trio).

    Returns
    -------
    The post-increment cumulative value for the matching label-set
    (caller can log it for journal traceability).

    Raises
    ------
    ValueError if ``delta < 0``.
    """
    if delta < 0:
        raise ValueError(f"counter delta must be >= 0, got {delta}")

    file_path = collector_dir / (file_basename or f"{metric_name}.prom")
    label_str = _format_labels(labels)
    target_line_prefix = f"{metric_name}{label_str}"

    new_value = delta
    other_lines: list[str] = []
    help_seen = False
    type_seen = False

    if file_path.exists():
        try:
            existing = file_path.read_text(encoding="utf-8")
        except OSError:
            log.warning("textfile %s exists but unreadable; rewriting", file_path)
            existing = ""
        for line in existing.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(f"# HELP {metric_name} "):
                help_seen = True
                other_lines.append(line)
                continue
            if stripped.startswith(f"# TYPE {metric_name} "):
                type_seen = True
                other_lines.append(line)
                continue
            if stripped.startswith("#"):
                other_lines.append(line)
                continue
            m = _METRIC_LINE_RE.match(stripped)
            if m and m.group("name") == metric_name:
                # Same metric name; check whether labels match exactly.
                existing_label_str = m.group("labels") or ""
                if existing_label_str == label_str:
                    try:
                        new_value = float(m.group("value")) + delta
                    except ValueError:
                        log.warning(
                            "textfile %s had non-numeric value for %s; resetting to delta",
                            file_path,
                            target_line_prefix,
                        )
                        new_value = delta
                    continue
                # Different label-set for the same metric — keep it.
                other_lines.append(line)
                continue
            # Different metric on the same file — preserve.
            other_lines.append(line)

    out_lines: list[str] = []
    if not help_seen:
        out_lines.append(f"# HELP {metric_name} {help_text}")
    if not type_seen:
        out_lines.append(f"# TYPE {metric_name} counter")
    out_lines.extend(other_lines)
    out_lines.append(f"{target_line_prefix} {new_value:g}")
    _atomic_write(file_path, "\n".join(out_lines) + "\n")
    return new_value


def write_gauge(
    *,
    metric_name: str,
    labels: Mapping[str, str],
    help_text: str,
    value: float,
    collector_dir: Path = DEFAULT_COLLECTOR_DIR,
    file_basename: str | None = None,
) -> None:
    """Atomically write a textfile-collector gauge (replace prior value).

    Same shape as :func:`increment_counter` but for gauges: the file's
    prior value for the matching label-set is replaced verbatim, not
    accumulated.
    """
    file_path = collector_dir / (file_basename or f"{metric_name}.prom")
    label_str = _format_labels(labels)
    target_line_prefix = f"{metric_name}{label_str}"

    other_lines: list[str] = []
    help_seen = False
    type_seen = False

    if file_path.exists():
        try:
            existing = file_path.read_text(encoding="utf-8")
        except OSError:
            log.warning("textfile %s exists but unreadable; rewriting", file_path)
            existing = ""
        for line in existing.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(f"# HELP {metric_name} "):
                help_seen = True
                other_lines.append(line)
                continue
            if stripped.startswith(f"# TYPE {metric_name} "):
                type_seen = True
                other_lines.append(line)
                continue
            if stripped.startswith("#"):
                other_lines.append(line)
                continue
            m = _METRIC_LINE_RE.match(stripped)
            if m and m.group("name") == metric_name:
                existing_label_str = m.group("labels") or ""
                if existing_label_str == label_str:
                    # Drop the prior matching line; we'll write the new value below.
                    continue
                other_lines.append(line)
                continue
            other_lines.append(line)

    out_lines: list[str] = []
    if not help_seen:
        out_lines.append(f"# HELP {metric_name} {help_text}")
    if not type_seen:
        out_lines.append(f"# TYPE {metric_name} gauge")
    out_lines.extend(other_lines)
    out_lines.append(f"{target_line_prefix} {value:g}")
    _atomic_write(file_path, "\n".join(out_lines) + "\n")


__all__ = [
    "DEFAULT_COLLECTOR_DIR",
    "increment_counter",
    "write_gauge",
]
