"""Shared launch environment: host bindings in, freshly authored identity out.

The shell command emits names to unset, never values (including credentials).
Run it before resolving identity and again in a tmux runner, whose parent is
the server. Provider credentials are resolved after this boundary via FileStore.
"""

from __future__ import annotations

import argparse
import os
import resource
import shlex
import sys
from collections.abc import Mapping
from pathlib import Path

# Explicit host/configuration bindings, not prefixes. In particular no parent
# session, task, native-harness state, provider credential or messaging channel.
INHERITED_BINDINGS = frozenset(
    [
        "HOME",
        "USER",
        "LOGNAME",
        "PATH",
        "SHELL",
        "TERM",
        "COLORTERM",
        "LANG",
        "LANGUAGE",
        "LC_ALL",
        "LC_CTYPE",
        "LC_MESSAGES",
        "TZ",
        "TMPDIR",
        "PWD",
        "SHLVL",
        "_",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
        "XDG_RUNTIME_DIR",
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "XAUTHORITY",
        "DBUS_SESSION_BUS_ADDRESS",
        "TMUX",
        "TMUX_PANE",
        "TMUX_TMPDIR",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "NO_COLOR",
        "NPM_CONFIG_PREFIX",
        "KIMI_BIN",
        "HAPAX_COUNCIL_DIR",
        "HAPAX_SOURCE_ACTIVATE_WORKTREE",
        "HAPAX_PLATFORM_CAPABILITY_REGISTRY",
        "HAPAX_IDLE_UPDATE_SECONDS",
        "HAPAX_RELAY_DIR",
        "HAPAX_CC_TASK_ROOT",
        "HAPAX_SESSION_PROTECTION_FILE",
        "HAPAX_CODEX_BIN_PATH",
        "HAPAX_CODEX_BRANCH_PREFIX",
        "HAPAX_CODEX_CREATE_WORKTREE",
        "HAPAX_CODEX_EXEC_AUTH_TIMEOUT_SECONDS",
        "HAPAX_CODEX_FOOT_WORKSPACE",
        "HAPAX_CODEX_OPERATOR_DOSSIER",
        "HAPAX_METHODOLOGY_EMERGENCY",
        "HAPAX_CODEX_PRIMARY_SESSION",
        "HAPAX_CODEX_PROTECTED_SESSION_OVERRIDE",
        "HAPAX_CODEX_TERMINAL",
        "HAPAX_CODEX_WORKTREE_BASE",
        "HAPAX_CODEX_WORKTREE_ROOT",
        "HAPAX_CODEX_HEADLESS_ALLOW",
        "HAPAX_CODEX_HEADLESS_DISABLE_FILE",
        "HAPAX_CODEX_HEADLESS_ENABLE_FILE",
        "HAPAX_CODEX_HEADLESS_PID_DIR",
        "HAPAX_CODEX_HEADLESS_WORKDIR",
        "HAPAX_CLAUDE_EFFORT",
        "HAPAX_CLAUDE_MODEL",
        "HAPAX_CLAUDE_SKIP_PERMS",
        "HAPAX_CLAUDE_TERMINAL",
        "HAPAX_CLAUDE_WORKTREE_ROOT",
        "HAPAX_CLAUDE_HEADLESS_WORKDIR",
        "HAPAX_CLAUDE_HEADLESS_ALLOW",
        "HAPAX_CLAUDE_HEADLESS_DISABLE_FILE",
        "HAPAX_CLAUDE_HEADLESS_ENABLE_FILE",
        "HAPAX_CLAUDE_READY_TIMEOUT",
        "HAPAX_GLMCP_MODEL",
        "HAPAX_GLMCP_WORKDIR",
        "HAPAX_GLMCP_OPENAI_BASE_URL",
        "HAPAX_GLMCP_HAIKU_MODEL",
        "HAPAX_GLMCP_SECRET_ENTRY",
        "HAPAX_GLMCP_ANTHROPIC_BASE_URL",
        "HAPAX_GLMCP_ALLOW_NON_CODING_PLAN_MODEL",
        "HAPAX_GLMCP_ALLOW_SECRET_ENTRY_OVERRIDE",
        "HAPAX_GLMCP_ALLOW_BASE_URL_OVERRIDE",
        "HAPAX_DISPATCH_HOST",
        "HAPAX_DISPATCH_HOST_FALLBACK",
        "HAPAX_DISPATCH_LOGOS_URL",
        "HAPAX_DISPATCH_PROOF_DIR",
        "HAPAX_SDLC_SLICE_ATTACHED",
        "LOGOS_BASE_URL",
        "COCKPIT_BASE_URL",
    ]
)


def clean_environment(source: Mapping[str, str]) -> dict[str, str]:
    return {name: value for name, value in source.items() if name in INHERITED_BINDINGS}


def raise_nofile() -> None:
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    target = 65536 if hard == resource.RLIM_INFINITY else min(hard, 65536)
    if soft != resource.RLIM_INFINITY and soft < target:
        resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))


# Executed in the lane's shell, not a subprocess whose raised limit would die
# with it. Keep the existing Claude behavior: cap by hard, never lower soft.
NOFILE_SHELL = """nofile_target=65536
nofile_hard="$(ulimit -Hn)"
if [ "$nofile_hard" != unlimited ] && [ "$nofile_hard" -lt "$nofile_target" ]; then
  nofile_target="$nofile_hard"
fi
nofile_soft="$(ulimit -Sn)"
if [ "$nofile_soft" != unlimited ] && [ "$nofile_soft" -lt "$nofile_target" ]; then
  ulimit -Sn "$nofile_target"
fi"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("shell", "session-id"))
    parser.add_argument("session_id", nargs="?", default="")
    args = parser.parse_args()
    if args.command == "shell":
        for name in sorted(os.environ.keys() - INHERITED_BINDINGS):
            if name.startswith("BASH_FUNC_") and name.endswith("%%"):
                print(f"unset -f -- {shlex.quote(name[10:-2])}")
            else:
                print(f"unset -v -- {shlex.quote(name)}")
        print(NOFILE_SHELL)
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from shared.session_identity import is_claim_keyable_session_id, mint_session_id

        if args.session_id and not is_claim_keyable_session_id(args.session_id):
            parser.error("unsafe --session-id; pass a path-safe, claim-keyable session id")
        print(args.session_id or mint_session_id())


if __name__ == "__main__":
    main()
