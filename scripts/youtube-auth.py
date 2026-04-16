#!/usr/bin/env python3
"""Re-authorize Google OAuth with YouTube write scope.

The existing google/token in pass only has calendar.readonly.
This triggers re-consent to add youtube.force-ssl scope.

Usage:
    cd hapax-council && uv run python scripts/youtube-auth.py
"""

import sys

sys.path.insert(0, ".")
from shared.google_auth import get_google_credentials  # noqa: E402

creds = get_google_credentials(["https://www.googleapis.com/auth/youtube.force-ssl"])
print(f"Authorized. Scopes: {creds.scopes}")
print("The youtube-player daemon will pick up the new token on next restart.")
