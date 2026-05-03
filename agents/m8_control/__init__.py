"""M8 remote button control — write-only serial daemon + UDS server.

cc-task ``m8-remote-button-control-daemon``. Stands up a small daemon
that holds the write fd to the M8's CDC serial port (``/dev/hapax-m8-serial``)
and exposes a UDS socket (``/run/hapax/m8-control.sock``) for command
submission. Translates JSON commands into the M8's documented host→M8
serial protocol (``'C'`` button bitmask, ``'K'`` keyjazz, ``'R'`` display
reset, ``'S'`` theme color).

Architectural separation: m8c-hapax owns the read fd on the same TTY;
this daemon holds the write fd. Concurrent open of independent fds for
read/write is supported by Linux serial drivers. Isolating the writer in
a tiny daemon prevents future m8c-hapax rebases from breaking the
capability.
"""

from agents.m8_control.daemon import (
    M8ButtonRequest,
    M8ControlDaemon,
    M8KeyjazzRequest,
    M8ResetRequest,
    M8ThemeRequest,
    encode_button,
    encode_keyjazz,
    encode_reset,
    encode_theme,
    parse_request,
)

__all__ = [
    "M8ButtonRequest",
    "M8ControlDaemon",
    "M8KeyjazzRequest",
    "M8ResetRequest",
    "M8ThemeRequest",
    "encode_button",
    "encode_keyjazz",
    "encode_reset",
    "encode_theme",
    "parse_request",
]
