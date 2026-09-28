"""Real CLI request-route canary; invoked ONLY inside an unshared network namespace.

Synthetic credentials, loopback-only HTTP, no provider access and no retained output.
"""

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def main():
    cli, guard = sys.argv[1:]
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True, capture_output=True)
    hits = []

    class Canary(BaseHTTPRequestHandler):
        def do_POST(self):
            # Never record headers, tokens, request bodies or CLI output.
            if self.path.startswith("/v1/messages"):
                hits.append(True)
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "type": "error",
                        "error": {
                            "type": "authentication_error",
                            "message": "synthetic canary refusal",
                        },
                    }
                ).encode()
            )

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Canary)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    config = Path(os.environ["CLAUDE_CONFIG_DIR"])
    settings = config / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "ANTHROPIC_AUTH_TOKEN": "synthetic-gateway-token",
                    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                    "API_TIMEOUT_MS": "3000",
                    "CLAUDE_CODE_MAX_RETRIES": "0",
                }
            }
        )
    )
    before = settings.read_bytes()
    args = [
        cli,
        "-p",
        "ok",
        "--model",
        "claude-opus-4-8",
        "--output-format",
        "json",
        "--tools",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--no-session-persistence",
    ]
    result = {}
    try:
        for name, command in [
            ("unguarded", args),
            ("guarded", [sys.executable, guard, "--exec-interactive-subscription", *args]),
        ]:
            hits.clear()
            try:
                proc = subprocess.run(command, capture_output=True, text=True, timeout=40)
                result[name] = {
                    "returncode": proc.returncode,
                    "timed_out": False,
                    "connection_failure": any(
                        s in (proc.stdout + proc.stderr).lower()
                        for s in (
                            "unable to connect",
                            "connection error",
                            "fetch failed",
                            "enotfound",
                            "request timed out",
                            "econnrefused",
                            "enetunreach",
                        )
                    ),
                }
            except subprocess.TimeoutExpired:
                result[name] = {"timed_out": True}
            result[name]["gateway_requests"] = len(hits)
        result["settings_unchanged"] = settings.read_bytes() == before
    finally:
        server.shutdown()
    print(json.dumps(result))


if __name__ == "__main__":
    main()
