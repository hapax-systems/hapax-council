"""Daemon entry point: ``python -m agents.youtube_chat_reader``."""

from __future__ import annotations

import logging
import os

from prometheus_client import start_http_server

from agents.youtube_chat_reader.reader import ChatReader

DEFAULT_METRICS_PORT = 9499


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("HAPAX_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    metrics_port = int(os.environ.get("HAPAX_YT_CHAT_METRICS_PORT", str(DEFAULT_METRICS_PORT)))
    start_http_server(metrics_port, addr="127.0.0.1")
    reader = ChatReader()
    # Wire reverse-channel registry so the chat-poster lane
    # (cc-task chat-response-verbal-and-text) can resolve the
    # liveChatId for liveChatMessages.insert without coupling.
    from agents.youtube_chat_reader import register_reader

    register_reader(reader)
    reader.run_forever()


if __name__ == "__main__":
    main()
