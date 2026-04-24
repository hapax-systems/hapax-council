"""Daemon entry point — ``python -m agents.quota_observability``."""

from agents.quota_observability.exporter import main

if __name__ == "__main__":
    main()
