"""Run only source/synthetic checks; retain C10 runtime tests as explicitly skipped.

Use from the repository root: uv run python tests/capability_envelope/run_source_checks.py.
The root conftest probes a production port during collection; these pure tests need
no root fixtures. Bubblewrap is simulated unavailable so even collection cannot launch it.
This is not the required CI containment job, which continues to run the actual C10 tests.
"""

import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main() -> int:
    original = shutil.which
    with patch(
        "shutil.which",
        side_effect=lambda name, *args, **kwargs: (
            None if name == "bwrap" else original(name, *args, **kwargs)
        ),
    ):
        return pytest.main(
            ["--confcutdir=tests/capability_envelope"]
            + (sys.argv[1:] or ["tests/capability_envelope", "-q", "-rs"])
        )


if __name__ == "__main__":
    raise SystemExit(main())
