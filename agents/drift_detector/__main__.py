"""Allow running as: python -m agents.drift_detector"""

import asyncio

from .cli import main

asyncio.run(main())
