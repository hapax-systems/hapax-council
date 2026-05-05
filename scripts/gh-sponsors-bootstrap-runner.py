#!/usr/bin/env python3
"""Dry-run/default GitHub Sponsors profile + tier bootstrap recipe."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

LIVE_ENV = "HAPAX_GH_SPONSORS_LIVE_APPLY"
DEFAULT_CONFIG = Path.home() / ".config/hapax/gh-sponsors-tiers.toml"
DEFAULT_OUTPUT = Path.home() / ".local/state/hapax/gh-sponsors-bootstrap"
DEFAULT_PROFILE = Path(
    os.environ.get(
        "HAPAX_GH_SPONSORS_PLAYWRIGHT_PROFILE",
        str(Path.home() / ".cache/hapax/playwright/github-sponsors"),
    )
)
GITHUB_SPONSORS_URL = "https://github.com/sponsors"
TierKind = Literal["monthly", "one_time"]


@dataclass(frozen=True)
class SponsorTier:
    slug: str
    kind: TierKind
    amount_usd_cents: int
    title: str
    description: str
    sponsorware_threshold: str = ""


@dataclass(frozen=True)
class SponsorsProfile:
    account: str
    legal_name: str
    display_name: str
    description: str
    profile_url_pass_key: str = "github-sponsors/profile-url"
    tier_id_pass_key_prefix: str = "github-sponsors/tiers"

    @property
    def dashboard_url(self) -> str:
        return f"{GITHUB_SPONSORS_URL}/accounts/{self.account}/dashboard/profile"


@dataclass(frozen=True)
class SponsorsBootstrapConfig:
    schema_version: int
    profile: SponsorsProfile
    tiers: tuple[SponsorTier, ...]


class ConfigError(ValueError):
    """Raised when the Sponsors bootstrap TOML fails schema validation."""


def _table(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{key!r} must be a TOML table")
    return value


def _str(raw: dict[str, Any], key: str, *, default: str | None = None) -> str:
    value = raw.get(key, default)
    if value == "" and default == "":
        return ""
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key!r} must be a non-empty string")
    return value.strip()


def _int(raw: dict[str, Any], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key!r} must be an integer")
    return value


def _validate_slug(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}[a-z0-9]", value):
        raise ConfigError(f"tier slug {value!r} must be lowercase kebab-case")
    return value


def _profile_from(raw: dict[str, Any]) -> SponsorsProfile:
    return SponsorsProfile(
        account=_validate_slug(_str(raw, "account")),
        legal_name=_str(raw, "legal_name"),
        display_name=_str(raw, "display_name"),
        description=_str(raw, "description"),
        profile_url_pass_key=_str(
            raw, "profile_url_pass_key", default="github-sponsors/profile-url"
        ),
        tier_id_pass_key_prefix=_str(
            raw, "tier_id_pass_key_prefix", default="github-sponsors/tiers"
        ).rstrip("/"),
    )


def _tier_from(raw: Any) -> SponsorTier:
    if not isinstance(raw, dict):
        raise ConfigError("each [[tiers]] entry must be a TOML table")
    kind = _str(raw, "kind")
    if kind not in {"monthly", "one_time"}:
        raise ConfigError("'kind' must be monthly or one_time")
    cents = _int(raw, "amount_usd_cents")
    if cents <= 0:
        raise ConfigError("'amount_usd_cents' must be positive")
    return SponsorTier(
        slug=_validate_slug(_str(raw, "slug")),
        kind=kind,
        amount_usd_cents=cents,
        title=_str(raw, "title"),
        description=_str(raw, "description"),
        sponsorware_threshold=_str(raw, "sponsorware_threshold", default=""),
    )


def load_config(path: Path) -> SponsorsBootstrapConfig:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    version = _int(raw, "schema_version")
    if version != 1:
        raise ConfigError(f"unsupported schema_version {version}; expected 1")
    tiers_raw = raw.get("tiers")
    if not isinstance(tiers_raw, list) or not tiers_raw:
        raise ConfigError("at least one [[tiers]] entry is required")
    tiers = tuple(_tier_from(item) for item in tiers_raw)
    slugs = [tier.slug for tier in tiers]
    if len(slugs) != len(set(slugs)):
        raise ConfigError("tier slugs must be unique")
    return SponsorsBootstrapConfig(
        schema_version=version,
        profile=_profile_from(_table(raw, "profile")),
        tiers=tiers,
    )


def build_plan(config: SponsorsBootstrapConfig) -> dict[str, Any]:
    profile_url = f"{GITHUB_SPONSORS_URL}/{config.profile.account}"
    tier_rows = []
    for tier in config.tiers:
        tier_rows.append(
            {
                **asdict(tier),
                "amount_usd": f"{tier.amount_usd_cents / 100:.2f}",
                "pass_key": f"{config.profile.tier_id_pass_key_prefix}/{tier.slug}",
            }
        )
    return {
        "schema_version": config.schema_version,
        "dashboard_url": config.profile.dashboard_url,
        "profile_url": profile_url,
        "profile_pass_key": config.profile.profile_url_pass_key,
        "profile": asdict(config.profile),
        "tiers": tier_rows,
        "safety": {
            "dry_run_default": True,
            "live_gate_env": LIVE_ENV,
            "does_not_touch_repo_sponsorships": True,
            "does_not_write_funding_yml": True,
        },
    }


def build_cassette(config: SponsorsBootstrapConfig) -> dict[str, Any]:
    actions: list[dict[str, Any]] = [
        {
            "action": "goto",
            "url": config.profile.dashboard_url,
        },
        {
            "action": "fill_profile",
            "fields": ["legal_name", "display_name", "description"],
        },
    ]
    for tier in config.tiers:
        actions.append(
            {
                "action": "create_tier",
                "slug": tier.slug,
                "kind": tier.kind,
                "amount_usd_cents": tier.amount_usd_cents,
                "pass_key": f"{config.profile.tier_id_pass_key_prefix}/{tier.slug}",
            }
        )
    return {"schema_version": 1, "actions": actions}


def _fill_first(page: Any, labels: tuple[str, ...], value: str) -> None:
    for label in labels:
        try:
            page.get_by_label(label, exact=False).first.fill(value)
            return
        except Exception:
            pass
    raise RuntimeError(f"no fillable control found for labels {labels!r}")


def run_playwright(
    config: SponsorsBootstrapConfig, *, output_dir: Path, apply: bool
) -> dict[str, Any]:
    """Open the Sponsors portal and optionally submit configured fields.

    This path is intentionally untested in CI; tests inject a fake runner.
    The recipe uses broad label/role selectors because GitHub's portal copy
    changes. If a selector fails, the browser remains open for operator
    correction and the run fails before any pass-store write.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(DEFAULT_PROFILE), headless=False
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(20_000)
        page.goto(config.profile.dashboard_url, wait_until="domcontentloaded")
        _fill_first(page, ("Legal name", "Payout legal name"), config.profile.legal_name)
        _fill_first(page, ("Display name", "Profile name"), config.profile.display_name)
        _fill_first(
            page, ("Description", "Short bio", "Profile description"), config.profile.description
        )
        for tier in config.tiers:
            page.get_by_role(
                "button", name=re.compile("new tier|add tier|create tier", re.I)
            ).click()
            _fill_first(page, ("Tier name", "Name"), tier.title)
            _fill_first(
                page,
                ("Amount", "Monthly amount", "One-time amount"),
                str(tier.amount_usd_cents // 100),
            )
            _fill_first(page, ("Description", "Tier description"), tier.description)
            if tier.kind == "one_time":
                page.get_by_text(re.compile("one[- ]time", re.I)).click()
            if apply:
                page.get_by_role("button", name=re.compile("save|publish|create", re.I)).click()
                page.wait_for_load_state("networkidle")
        screenshot = output_dir / "sponsors-preview.png"
        page.screenshot(path=str(screenshot), full_page=True)
        profile_url = f"{GITHUB_SPONSORS_URL}/{config.profile.account}"
        tier_ids = extract_tier_ids(page, config)
        context.close()
    return {"profile_url": profile_url, "tier_ids": tier_ids, "screenshot_path": str(screenshot)}


def extract_tier_ids(page: Any, config: SponsorsBootstrapConfig) -> dict[str, str]:
    """Best-effort extraction from current portal links after live creation."""
    ids: dict[str, str] = {}
    anchors = page.locator("a[href*='tier']").all()
    for anchor in anchors:
        href = str(anchor.get_attribute("href") or "")
        text = str(anchor.inner_text() or "").lower()
        match = re.search(r"/tiers?/([A-Za-z0-9_-]+)", href)
        if not match:
            continue
        for tier in config.tiers:
            if tier.slug in ids:
                continue
            if tier.slug in href.lower() or tier.title.lower() in text:
                ids[tier.slug] = match.group(1)
    return ids


def pass_records(config: SponsorsBootstrapConfig, outcome: dict[str, Any]) -> dict[str, str]:
    records: dict[str, str] = {}
    profile_url = outcome.get("profile_url")
    if isinstance(profile_url, str) and profile_url:
        records[config.profile.profile_url_pass_key] = profile_url
    tier_ids = outcome.get("tier_ids", {})
    if not isinstance(tier_ids, dict):
        return records
    for tier in config.tiers:
        tier_id = tier_ids.get(tier.slug)
        if isinstance(tier_id, str) and tier_id:
            records[f"{config.profile.tier_id_pass_key_prefix}/{tier.slug}"] = json.dumps(
                {
                    "tier_id": tier_id,
                    "slug": tier.slug,
                    "kind": tier.kind,
                    "amount_usd_cents": tier.amount_usd_cents,
                },
                sort_keys=True,
            )
    return records


def write_pass_value(key: str, value: str) -> None:
    subprocess.run(
        ["pass", "insert", "-m", key],
        input=f"{value}\n",
        text=True,
        check=True,
    )


def write_pass_plan(path: Path, records: dict[str, str]) -> None:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "# Values are intentionally omitted; rerun with --apply --write-pass after live capture.",
    ]
    for key in sorted(records):
        lines.append(f"pass insert -m {key!r}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--write-pass", action="store_true")
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    portal_runner: Any = run_playwright,
    pass_writer: Any = write_pass_value,
    env: dict[str, str] | os._Environ[str] = os.environ,
) -> int:
    args = _args(argv)
    config = load_config(args.config)
    if args.apply and env.get(LIVE_ENV) != "1":
        print(f"refusing live apply: set {LIVE_ENV}=1 and pass --apply", file=sys.stderr)
        return 2

    output_dir = args.output_dir / datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    output_dir.mkdir(parents=True, exist_ok=True)
    plan = build_plan(config)
    (output_dir / "bootstrap-plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "dry-run-cassette.json").write_text(
        json.dumps(build_cassette(config), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    outcome: dict[str, Any] = {
        "profile_url": plan["profile_url"],
        "tier_ids": {},
        "screenshot_path": None,
    }
    if args.open_browser or args.apply:
        outcome = portal_runner(config, output_dir=output_dir, apply=args.apply)
    records = pass_records(config, outcome)
    if args.write_pass:
        if not args.apply:
            print(
                "--write-pass requires --apply so dry-runs cannot mutate pass-store",
                file=sys.stderr,
            )
            return 2
        for key, value in records.items():
            pass_writer(key, value)
    write_pass_plan(output_dir / "pass-store-plan.sh", records)
    summary = {
        "output_dir": str(output_dir),
        "profile_url": outcome.get("profile_url"),
        "tier_ids_captured": sorted(records),
        "applied": bool(args.apply),
    }
    (output_dir / "outcome.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
