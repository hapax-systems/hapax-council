import YAML = require("yaml");

export function parseFrontmatter(raw: string): {
  data: Record<string, unknown>;
  content: string;
} {
  const match = /^---\r?\n(?:([\s\S]*?)\r?\n)?---\r?\n?/.exec(raw);
  if (!match) {
    return { data: {}, content: raw };
  }
  const parsed = YAML.parse(match[1] ?? "");
  return {
    data:
      parsed && typeof parsed === "object" && !Array.isArray(parsed)
        ? (parsed as Record<string, unknown>)
        : {},
    content: raw.slice(match[0].length),
  };
}

export function serializeFrontmatter(
  data: Record<string, unknown>,
  content: string,
): string {
  return `---\n${YAML.stringify(data).trimEnd()}\n---\n${content}`;
}
