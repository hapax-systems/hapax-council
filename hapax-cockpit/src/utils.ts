/** Format React Query's dataUpdatedAt timestamp as a relative age string. */
export function formatAge(dataUpdatedAt: number): string {
  if (!dataUpdatedAt) return "";
  const seconds = Math.floor((Date.now() - dataUpdatedAt) / 1000);
  if (seconds < 10) return "now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ago`;
}

/**
 * Parse a command string like "uv run python -m agents.health_monitor --fix --hours 24"
 * into { agent, flags } for pre-filling the agent config modal.
 * Returns null if command doesn't match the agents.<name> pattern.
 */
export function parseAgentCommand(
  cmd: string,
): { agent: string; flags: Record<string, string> } | null {
  const match = cmd.match(/agents\.(\w+)/);
  if (!match) return null;

  const agent = match[1];
  const flags: Record<string, string> = {};

  const afterAgent = cmd.slice(cmd.indexOf(match[0]) + match[0].length).trim();
  const tokens = afterAgent.split(/\s+/).filter(Boolean);

  let i = 0;
  while (i < tokens.length) {
    const token = tokens[i];
    if (token.startsWith("--")) {
      if (i + 1 < tokens.length && !tokens[i + 1].startsWith("--")) {
        flags[token] = tokens[i + 1];
        i += 2;
      } else {
        flags[token] = "";
        i += 1;
      }
    } else {
      i += 1;
    }
  }

  return { agent, flags };
}
