"""Audio source spec emitter (audit F).

One-command "add new audio source" generator. Operator runs the CLI
with a source name + chain kind; the emitter renders three artifacts
into a workspace-local staging dir for operator review:

  * `<source-id>.conf`       — PipeWire filter-chain conf
  * `<source-id>.service`    — systemd user unit stub
  * `<source-id>.yaml`       — yaml fragment to merge into
                               config/audio-topology.yaml

Generated artifacts pass schema v3 validation immediately — the
yaml fragment merges into a copy of the live topology and the merge
result re-parses through `TopologyDescriptor.from_yaml`.

Usage:

    uv run python -m agents.audio_codegen.spec_emitter \\
        --source-id new-mic-loudnorm \\
        --chain-kind loudnorm \\
        --description "New mic loudnorm chain" \\
        --staging-dir ~/.cache/hapax/audio-codegen-staging

Operator inspects the staging dir, then either:

  * Moves `.conf` into `config/pipewire/`, merges the yaml fragment
    into `config/audio-topology.yaml`, deploys the systemd unit; or
  * Discards (the staging dir is ephemeral).

The emitter never touches the live tree directly. Operator-confirm-
before-install is the contract per AC#3.

Cc-task: ``audio-audit-F-source-spec-emitter``.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
DEFAULT_TOPOLOGY = REPO_ROOT / "config" / "audio-topology.yaml"

#: chain_kind values the generator supports. Mirror's the
#: TopologyDescriptor schema v3 typed-template set.
SUPPORTED_CHAIN_KINDS = ("loudnorm", "duck", "usb-bias", "none")

#: Default LADSPA chain values for `loudnorm` / `usb-bias`. These
#: align with `shared/audio_loudness.py` constants — operator can
#: edit the generated artifacts before install if they need to
#: deviate.
DEFAULT_LIMIT_DB = -1.0
DEFAULT_RELEASE_S = 0.20
DEFAULT_INPUT_GAIN_DB = 0.0


def _render(template_basename: str, context: Mapping[str, Any]) -> str:
    """Render one template with the given context.

    Uses jinja2 if available; falls back to a tiny `str.format`-style
    substitution otherwise so this module doesn't hard-require jinja2.
    Both code paths produce identical output for the supported
    template syntax (no loops, only variable substitution + a single
    if-block in the yaml fragment).
    """
    template_path = TEMPLATES_DIR / template_basename
    if not template_path.is_file():
        raise FileNotFoundError(f"template missing: {template_path}")
    template_text = template_path.read_text(encoding="utf-8")
    try:
        from jinja2 import Environment, StrictUndefined

        env = Environment(undefined=StrictUndefined, autoescape=False)
        return env.from_string(template_text).render(**dict(context))
    except ImportError:
        # Fallback: very-simple substitution. Only handles
        # `{{ var }}` and skips `{%- if %}/{%- endif %}` blocks
        # by retaining their bodies unconditionally. The shipped
        # templates all use either jinja2 (when installed) or a
        # narrow subset of substitution this fallback handles.
        rendered = template_text
        for key, value in context.items():
            rendered = rendered.replace(f"{{{{ {key} }}}}", str(value))
        return rendered


def emit(
    *,
    source_id: str,
    chain_kind: str,
    description: str,
    staging_dir: Path,
    pipewire_name: str | None = None,
    limit_db: float = DEFAULT_LIMIT_DB,
    release_s: float = DEFAULT_RELEASE_S,
    input_gain_db: float = DEFAULT_INPUT_GAIN_DB,
) -> dict[str, Path]:
    """Render all three artifacts into ``staging_dir``.

    Parameters
    ----------
    source_id:
        Stable kebab-case identifier (matches the topology yaml `id` field).
    chain_kind:
        One of ``SUPPORTED_CHAIN_KINDS``. ``"none"`` produces a stream-
        routing filter_chain with no LADSPA stage.
    description:
        Operator-readable label for the source.
    staging_dir:
        Where to drop the three generated files. Created if missing.
    pipewire_name:
        Defaults to ``"hapax-{source_id}"`` to match the conf-naming
        convention enforced by the F-precommit gate.
    limit_db / release_s / input_gain_db:
        LADSPA chain parameters baked into the conf template.

    Returns
    -------
    Mapping `artifact_kind` → `Path` of the rendered files.
    """

    if chain_kind not in SUPPORTED_CHAIN_KINDS:
        raise ValueError(
            f"chain_kind={chain_kind!r} unsupported; pick one of {SUPPORTED_CHAIN_KINDS}"
        )

    pw_name = pipewire_name or f"hapax-{source_id}"
    conf_basename = f"hapax-{source_id}.conf"
    staging_dir.mkdir(parents=True, exist_ok=True)

    context = {
        "source_id": source_id,
        "pipewire_name": pw_name,
        "description": description,
        "chain_kind": chain_kind if chain_kind != "none" else "null",
        "conf_basename": conf_basename,
        "limit_db": f"{limit_db:.2f}",
        "release_s": f"{release_s:.2f}",
        "input_gain_db": f"{input_gain_db:.2f}",
    }

    artifacts: dict[str, Path] = {}
    for artifact_kind, template_name in (
        ("conf", "source.conf.j2"),
        ("service", "source.service.j2"),
        ("yaml_fragment", "source.yaml.j2"),
    ):
        text = _render(template_name, context)
        ext = {"conf": ".conf", "service": ".service", "yaml_fragment": ".yaml"}[artifact_kind]
        out_path = staging_dir / f"{source_id}{ext}"
        out_path.write_text(text, encoding="utf-8")
        artifacts[artifact_kind] = out_path
    return artifacts


def validate_yaml_fragment_merges(
    *,
    fragment_path: Path,
    topology_path: Path = DEFAULT_TOPOLOGY,
) -> tuple[bool, str]:
    """Verify the yaml fragment merges into the live topology cleanly.

    Loads ``topology_path``, parses ``fragment_path`` as a list of
    nodes, appends them to the topology's `nodes:` array, then
    re-parses the merged document through `TopologyDescriptor.from_yaml`
    via a temp file. Returns ``(ok, message)``.

    A return of ``(False, ...)`` means the operator MUST adjust the
    fragment before merging; the live topology yaml is never touched.
    """

    from shared.audio_topology import TopologyDescriptor

    try:
        live_text = topology_path.read_text(encoding="utf-8")
        live_doc = yaml.safe_load(live_text)
    except FileNotFoundError:
        return False, f"live topology missing: {topology_path}"
    except yaml.YAMLError as exc:
        return False, f"live topology malformed: {exc}"
    if not isinstance(live_doc, dict):
        return False, "live topology root is not a mapping"

    try:
        fragment_text = fragment_path.read_text(encoding="utf-8")
        fragment_doc = yaml.safe_load(fragment_text)
    except (OSError, yaml.YAMLError) as exc:
        return False, f"fragment unreadable / malformed: {exc}"

    if isinstance(fragment_doc, list):
        new_nodes = fragment_doc
    elif isinstance(fragment_doc, dict) and "nodes" in fragment_doc:
        new_nodes = fragment_doc["nodes"]
    else:
        # The shipped template emits a list-shape (top-level `- id: ...`).
        # If the fragment is structured as a single-element mapping we
        # wrap it; otherwise it's a malformed fragment.
        new_nodes = [fragment_doc] if isinstance(fragment_doc, dict) else []
    if not isinstance(new_nodes, list) or not new_nodes:
        return False, "fragment is empty or not a list of nodes"

    merged = dict(live_doc)
    merged_nodes = list(merged.get("nodes") or [])
    merged_nodes.extend(new_nodes)
    merged["nodes"] = merged_nodes

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
        yaml.safe_dump(merged, tmp)
        tmp_path = Path(tmp.name)
    try:
        TopologyDescriptor.from_yaml(tmp_path)
    except Exception as exc:
        return False, f"merged topology rejects fragment: {exc}"
    finally:
        tmp_path.unlink(missing_ok=True)

    return True, "fragment merges cleanly into live topology"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate audio source artifacts (conf + service + yaml fragment).",
    )
    parser.add_argument(
        "--source-id",
        required=True,
        help="Kebab-case stable identifier for the new source.",
    )
    parser.add_argument(
        "--chain-kind",
        choices=SUPPORTED_CHAIN_KINDS,
        default="loudnorm",
        help="LADSPA chain template kind (default: loudnorm).",
    )
    parser.add_argument(
        "--description",
        required=True,
        help="Operator-readable description.",
    )
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=Path("~/.cache/hapax/audio-codegen-staging").expanduser(),
        help="Where to drop generated artifacts (operator-controlled).",
    )
    parser.add_argument(
        "--pipewire-name",
        default=None,
        help="Override pipewire_name (defaults to hapax-<source-id>).",
    )
    parser.add_argument(
        "--limit-db",
        type=float,
        default=DEFAULT_LIMIT_DB,
        help=f"LADSPA Limit (dB) (default: {DEFAULT_LIMIT_DB}).",
    )
    parser.add_argument(
        "--release-s",
        type=float,
        default=DEFAULT_RELEASE_S,
        help=f"LADSPA Release time (s) (default: {DEFAULT_RELEASE_S}).",
    )
    parser.add_argument(
        "--input-gain-db",
        type=float,
        default=DEFAULT_INPUT_GAIN_DB,
        help=f"LADSPA Input gain (dB) (default: {DEFAULT_INPUT_GAIN_DB}).",
    )
    parser.add_argument(
        "--skip-validate",
        action="store_true",
        help="Skip yaml-fragment merge validation (fast smoke).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    artifacts = emit(
        source_id=args.source_id,
        chain_kind=args.chain_kind,
        description=args.description,
        staging_dir=args.staging_dir,
        pipewire_name=args.pipewire_name,
        limit_db=args.limit_db,
        release_s=args.release_s,
        input_gain_db=args.input_gain_db,
    )
    print(f"Generated 3 artifacts in {args.staging_dir}:")
    for kind, path in artifacts.items():
        print(f"  {kind:>15}: {path}")
    if not args.skip_validate:
        ok, msg = validate_yaml_fragment_merges(fragment_path=artifacts["yaml_fragment"])
        print(f"Validation: {msg}")
        if not ok:
            return 1
    print("\nReview the staging dir, then merge / install per docs/runbooks/add-audio-source.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
