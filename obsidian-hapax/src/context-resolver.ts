import type { NoteContext } from "./types";
import { NoteKind } from "./types";

export function resolveNoteContext(
  path: string,
  frontmatter: Record<string, unknown> | null,
  metadataTags: string[],
): NoteContext {
  const fm = frontmatter ?? {};
  const id = typeof fm["id"] === "string" ? fm["id"] : undefined;
  const model = typeof fm["model"] === "string" ? fm["model"] : undefined;

  // Collect tags from frontmatter + metadata cache
  const fmTags = normalizeTags(fm["tags"]);
  const allTags = Array.from(new Set([...fmTags, ...metadataTags]));

  // 1. Measure: path contains sprint/measures/ + id matches d+.d+
  if (path.includes("sprint/measures/") && id && /^\d+\.\d+$/.test(id)) {
    return { kind: NoteKind.Measure, id, model, tags: allTags };
  }

  // 2. Gate: path contains sprint/gates/ + id matches G\d+
  if (path.includes("sprint/gates/") && id && /^G\d+$/.test(id)) {
    return { kind: NoteKind.Gate, id, model, tags: allTags };
  }

  // 3. SprintSummary: path contains sprint/sprints/
  if (path.includes("sprint/sprints/")) {
    return { kind: NoteKind.SprintSummary, id, model, tags: allTags };
  }

  // 4. PosteriorTracker: path ends with _posterior-tracker.md
  if (path.endsWith("_posterior-tracker.md")) {
    return { kind: NoteKind.PosteriorTracker, id, model, tags: allTags };
  }

  // 5. Goal: type: goal frontmatter
  if (fm["type"] === "goal") {
    return { kind: NoteKind.Goal, id, model, tags: allTags };
  }

  // 6. Daily: calendar/daily/ path or type: daily
  if (path.includes("40-calendar/daily/") || fm["type"] === "daily") {
    return { kind: NoteKind.Daily, id, model, tags: allTags };
  }

  // 7. Management: people/ path or type: person (non-historical)
  if (path.includes("/people/") || (fm["type"] === "person" && fm["role"] !== "historical")) {
    return { kind: NoteKind.Management, id, model, tags: allTags };
  }

  // 8. Studio: studio or music tags
  if (allTags.includes("studio") || allTags.includes("music")) {
    return { kind: NoteKind.Studio, id, model, tags: allTags };
  }

  // 9. Briefing: path contains briefings/
  if (path.includes("briefings/")) {
    return { kind: NoteKind.Briefing, id, model, tags: allTags };
  }

  // 10. Nudges: path ends with nudges.md
  if (path.endsWith("nudges.md")) {
    return { kind: NoteKind.Nudges, id, model, tags: allTags };
  }

  // 11. Research: path contains hapax-research/
  if (path.includes("hapax-research/")) {
    return { kind: NoteKind.Research, id, model, tags: allTags };
  }

  // 12. Concept: path contains permanent-notes/
  if (path.includes("permanent-notes/") && allTags.includes("type/concept")) {
    return { kind: NoteKind.Concept, id, model, tags: allTags };
  }

  // 13. Unknown
  return { kind: NoteKind.Unknown, id, model, tags: allTags };
}

function normalizeTags(raw: unknown): string[] {
  if (Array.isArray(raw)) {
    return raw.filter((t) => typeof t === "string");
  }
  if (typeof raw === "string") {
    return raw.split(/[,\s]+/).filter(Boolean);
  }
  return [];
}
