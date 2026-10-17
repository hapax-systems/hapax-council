"""Module entry point: python -m agents.discourse_sensing."""

import sys

from agents.discourse_sensing.run import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
