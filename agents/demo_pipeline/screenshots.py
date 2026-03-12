"""Re-export from hapax-demo package for backwards compatibility."""

from demo.pipeline.screenshots import *  # noqa: F401, F403
from demo.pipeline.screenshots import (  # noqa: F401
    _chat_variant_index,
    _clear_chat_session,
    _preflight_check,
    _resolve_selector,
    capture_screenshots,
    fix_localhost_url,
    validate_screenshot_specs,
)
