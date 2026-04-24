"""Publisher configuration — env-overridable, Pydantic-validated."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COUNCIL_ASSETS_DEFAULT = _REPO_ROOT / "assets" / "aesthetic-library"
_CHECKOUT_DEFAULT = Path.home() / ".cache" / "hapax" / "hapax-assets-checkout"
_RATE_STATE_DEFAULT = Path.home() / ".cache" / "hapax" / "hapax-assets-publisher" / "rate-state"


class PublisherConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    source_dir: Path = _COUNCIL_ASSETS_DEFAULT
    checkout_dir: Path = _CHECKOUT_DEFAULT
    remote_url: str = "git@github.com:ryanklee/hapax-assets.git"
    branch: str = "main"
    min_push_interval_sec: int = 30
    rate_state_file: Path = _RATE_STATE_DEFAULT

    @classmethod
    def from_env(cls) -> PublisherConfig:
        return cls(
            source_dir=Path(
                os.environ.get("HAPAX_ASSETS_SOURCE_DIR", str(_COUNCIL_ASSETS_DEFAULT))
            ),
            checkout_dir=Path(os.environ.get("HAPAX_ASSETS_CHECKOUT_DIR", str(_CHECKOUT_DEFAULT))),
            remote_url=os.environ.get(
                "HAPAX_ASSETS_REMOTE_URL",
                "git@github.com:ryanklee/hapax-assets.git",
            ),
            branch=os.environ.get("HAPAX_ASSETS_BRANCH", "main"),
            min_push_interval_sec=int(os.environ.get("HAPAX_ASSETS_MIN_PUSH_INTERVAL_SEC", "30")),
            rate_state_file=Path(
                os.environ.get("HAPAX_ASSETS_RATE_STATE_FILE", str(_RATE_STATE_DEFAULT))
            ),
        )
