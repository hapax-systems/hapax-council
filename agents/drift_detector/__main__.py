"""Allow running as: python -m agents.drift_detector"""

import asyncio

from .agent import main

asyncio.run(main())
