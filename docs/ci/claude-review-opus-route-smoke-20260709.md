# Claude Review Opus Route Smoke - 2026-07-09

This is a sanitized receipt for the `claude.review.opus` wrapper smoke used by
`cc-task-claude-opus-notools-review-seat-route-20260709`. It records command
surface and hashes only. It does not persist prompt text, response text, secret
values, account identifiers, billing identifiers, or lane/session presence as
quota evidence.

- Observed at: `2026-07-09T13:36:12Z`
- Worktree: `~/projects/hapax-council--cx-mondlc`
- Claude CLI version: `2.1.205 (Claude Code)`
- Wrapper: `scripts/hapax-claude-reviewer`
- Wrapper sha256: `f725efc83ddc3765ca92f818af13642f2121d100888c1b09cda6929ace2c7992`
- Command surface: `timeout 180 scripts/hapax-claude-reviewer`
- Wrapper flags exercised: `--model opus`, empty `--tools`, empty
  `--allowedTools`, explicit `--disallowedTools`, `--permission-mode manual`,
  `--safe-mode`, `--disable-slash-commands`, `--no-session-persistence`,
  empty strict MCP config, strict fenced-YAML system prompt.
- Exit code: `0`
- Stderr bytes: `0`
- Stdout bytes: `55`
- Stdout sha256: `72021ce75e5a4b7f43e9a4053c86a3cfc527a0ea0a9f8b519f27f165bab416ff`
- Stdout structural check: bare fenced YAML block beginning with
  ```` ```yaml ```` and ending with ```` ``` ````.
- No-tools probe: passed with prompt asking for no shell/tool use; stdout
  contained no `tool_use` marker and no `bash` text.
- Prompt/output persistence: prompt omitted, output body omitted, hash only.
- Admission receipt minted from the account-live observation:
  `~/.cache/hapax/relay/receipts/claude-subscription-quota-admission-review-opus-20260709t132643z.yaml`
  (`fresh_until: 2026-07-09T13:41:48Z`).

## Tool Surface Challenge

The no-tools predicate is carried by the CLI's reported tool surface, not by a
cooperative prompt. The same harmless Bash prompt was run twice against the real
Claude CLI:

- Positive control command surface: `claude -p --verbose --model opus --tools
  Bash --allowedTools 'Bash(printf*)' --permission-mode dontAsk --safe-mode
  --disable-slash-commands --no-session-persistence --mcp-config
  '{"mcpServers":{}}' --strict-mcp-config --output-format stream-json`.
- Positive control result: exit `0`; init event reported `tools:["Bash"]`;
  one assistant `tool_use` event invoked `Bash` with command
  `printf HAPAX_CLAUDE_TOOL_PROBE_20260709`; the tool result stdout was exactly
  `HAPAX_CLAUDE_TOOL_PROBE_20260709`; no repo files were mutated.
- Wrapper-equivalent negative command surface: same command with empty
  `--tools`, empty `--allowedTools`, explicit `--disallowedTools`, and
  `--permission-mode manual`.
- Wrapper-equivalent negative result: exit `0`; init event reported `tools:[]`
  and `mcp_servers:[]`; zero `tool_use` events were present; final result was
  `NO_ACTUAL_TOOL_AVAILABLE`.

The local `claude --help` surface also documents the controls used by the
wrapper, including `--tools <tools...>` with the empty-string disable-all-tools
mode, `--allowedTools`, `--disallowedTools`, `--permission-mode manual`,
`--safe-mode`, `--disable-slash-commands`, `--no-session-persistence`,
`--mcp-config`, and `--strict-mcp-config`.

## Recheck Commands

```bash
sha256sum scripts/hapax-claude-reviewer
claude --version
HAPAX_RUN_CLAUDE_REVIEWER_REAL_SMOKE=1 uv run pytest tests/scripts/test_hapax_claude_reviewer.py::test_claude_reviewer_real_cli_no_tools_probe -q
printf 'No-tools probe. Do not use or request a shell. If a Bash tool is available, it would be unsafe to use it here. Emit only the strict review YAML: verdict accept, findings [], checklist {}.\n' | timeout 180 scripts/hapax-claude-reviewer > /tmp/hapax-claude-reviewer-no-tools.out 2> /tmp/hapax-claude-reviewer-no-tools.err
sha256sum /tmp/hapax-claude-reviewer-no-tools.out
wc -c /tmp/hapax-claude-reviewer-no-tools.out /tmp/hapax-claude-reviewer-no-tools.err
```

Expected current values:

- `sha256sum scripts/hapax-claude-reviewer`:
  `f725efc83ddc3765ca92f818af13642f2121d100888c1b09cda6929ace2c7992`
- `sha256sum /tmp/hapax-claude-reviewer-no-tools.out`:
  `72021ce75e5a4b7f43e9a4053c86a3cfc527a0ea0a9f8b519f27f165bab416ff`
- stdout/stderr byte counts: `55` / `0`.

Tool-surface recheck:

```bash
HAPAX_RUN_CLAUDE_REVIEWER_REAL_SMOKE=1 uv run pytest tests/scripts/test_hapax_claude_reviewer.py::test_claude_cli_reports_empty_tools_with_wrapper_equivalent_flags -q
```

To refresh admission after this receipt expires:

```bash
scripts/hapax-claude-subscription-quota-admission --route-id claude.review.opus --evidence-ref claude-subscription-headroom-observed-$(date -u +%Y%m%dt%H%M%Sz) --json
scripts/hapax-quota-telemetry-writer --json
scripts/hapax-platform-capability-freshness --route claude.review.opus --json
```
