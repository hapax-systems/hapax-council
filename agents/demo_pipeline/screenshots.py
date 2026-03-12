"""Re-export from hapax-demo package for backwards compatibility."""
from demo.pipeline.screenshots import *  # noqa: F401, F403
from demo.pipeline.screenshots import (  # noqa: F401
    capture_screenshots, fix_localhost_url, validate_screenshot_specs,
    _resolve_selector, _preflight_check, _clear_chat_session, _chat_variant_index,
)
