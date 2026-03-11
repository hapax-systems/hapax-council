import * as vscode from "vscode";
import { readVaultFile, listVaultFiles, parseFrontmatter, vaultRoot } from "../vault";
import { getSettings } from "../settings";
import { QdrantClient } from "../qdrant-client";
import type { QdrantSearchResult } from "../types";
import type { ChatViewProvider } from "../chat-view";

/**
 * Prepare 1:1 command.
 *
 * Reads the current person-type note, searches Qdrant for related context,
 * reads the last 5 meeting files for this person from the vault,
 * finds coaching hypothesis notes, then sends all to the LLM for synthesis.
 * Output is streamed in the chat sidebar via ChatViewProvider.
 */
export async function prepare1on1(
  context: vscode.ExtensionContext,
  chat: ChatViewProvider,
): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showWarningMessage(
      "No active file. Open a person note first."
    );
    return;
  }

  const fileUri = editor.document.uri;
  const root = vaultRoot();
  const relativePath = vscode.workspace.asRelativePath(fileUri, false);

  // Read and check frontmatter
  const raw = await readVaultFile(relativePath);
  const { data: frontmatter } = parseFrontmatter(raw);
  if (frontmatter["type"] !== "person") {
    vscode.window.showWarningMessage(
      "Current note is not a person note (missing 'type: person' in frontmatter)."
    );
    return;
  }

  // Extract person name from filename (e.g., "john-doe.md" -> "john doe")
  const basename = relativePath.split("/").pop()?.replace(/\.md$/, "") || "";
  const personName = basename.replace(/-/g, " ");
  vscode.window.showInformationMessage(`Preparing 1:1 for ${personName}...`);

  const settings = getSettings();
  const qdrant = new QdrantClient(settings);

  // Step 1: Search Qdrant for related context about this person
  let qdrantResults: QdrantSearchResult[] = [];
  try {
    qdrantResults = await qdrant.search(
      `${personName} work performance feedback coaching`,
      settings.qdrantCollection,
      10
    );
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    console.warn(
      "Qdrant search failed, continuing without RAG context:",
      msg
    );
  }

  // Step 2: Find meeting files for this person
  const meetingFiles = await findMeetingFiles(personName);
  const meetingContents: string[] = [];
  for (const uri of meetingFiles.slice(0, 5)) {
    try {
      const path = vscode.workspace.asRelativePath(uri, false);
      const content = await readVaultFile(path);
      const name = path.split("/").pop()?.replace(/\.md$/, "") || path;
      meetingContents.push(`## Meeting: ${name}\n\n${content}`);
    } catch (err: unknown) {
      console.warn(`Hapax: skipping unreadable file ${uri.fsPath}:`, err);
    }
  }

  // Step 3: Find coaching hypothesis notes
  const coachingFiles = await findCoachingNotes(personName);
  const coachingContents: string[] = [];
  for (const uri of coachingFiles.slice(0, 3)) {
    try {
      const path = vscode.workspace.asRelativePath(uri, false);
      const content = await readVaultFile(path);
      const name = path.split("/").pop()?.replace(/\.md$/, "") || path;
      coachingContents.push(`## Coaching Note: ${name}\n\n${content}`);
    } catch (err: unknown) {
      console.warn(`Hapax: skipping unreadable file ${uri.fsPath}:`, err);
    }
  }

  // Step 4: Build the synthesis prompt
  const qdrantContext = qdrantResults
    .map((r, i) => {
      const text =
        (r.payload?.["text"] as string) ||
        (r.payload?.["content"] as string) ||
        JSON.stringify(r.payload);
      const source = (r.payload?.["source"] as string) || "unknown";
      return `[${i + 1}] (score: ${r.score.toFixed(3)}, source: ${source})\n${text}`;
    })
    .join("\n\n");

  const prompt = buildSynthesisPrompt(
    personName,
    raw,
    qdrantContext,
    meetingContents,
    coachingContents
  );

  // Step 5: Send to chat sidebar for LLM synthesis
  vscode.commands.executeCommand("hapax.chatView.focus");
  chat.injectMessage(`Preparing 1:1 for ${personName}...`, prompt);
}

function buildSynthesisPrompt(
  personName: string,
  personNote: string,
  qdrantContext: string,
  meetingContents: string[],
  coachingContents: string[]
): string {
  let prompt = `Prepare a 1:1 meeting brief for **${personName}**. Synthesize all available context into actionable talking points. Focus on:
- Recent work and accomplishments
- Open items and blockers from previous meetings
- Growth areas and coaching experiment status
- Career trajectory context (3-year goal, current gaps, last career conversation date)
- Skill/will assessment signals (skill level, will indicators)
- Team topology context (team type, interaction mode) if relevant
- Questions to ask (not advice to give)

Do NOT draft feedback language or coaching hypotheses directly. Instead, aggregate signals and surface patterns.

---

## Person Note

${personNote}

---
`;

  if (meetingContents.length > 0) {
    prompt += `\n## Recent Meetings (last ${meetingContents.length})\n\n${meetingContents.join("\n\n---\n\n")}\n\n---\n`;
  } else {
    prompt += "\n## Recent Meetings\n\nNo recent meeting notes found.\n\n---\n";
  }

  if (coachingContents.length > 0) {
    prompt += `\n## Coaching Notes\n\n${coachingContents.join("\n\n---\n\n")}\n\n---\n`;
  }

  if (qdrantContext) {
    prompt += `\n## Related Context (from knowledge base)\n\n${qdrantContext}\n\n---\n`;
  }

  return prompt;
}

/**
 * Convert a person name to kebab-case for matching filenames.
 */
function nameToKebab(name: string): string {
  return name
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-");
}

/**
 * Find meeting files that mention this person, sorted by modification time (newest first).
 */
async function findMeetingFiles(personName: string): Promise<vscode.Uri[]> {
  const allMdFiles = await listVaultFiles("", "**/*.md");
  const results: { uri: vscode.Uri; mtime: number }[] = [];

  const nameLower = personName.toLowerCase();
  const nameKebab = nameToKebab(personName);

  for (const uri of allMdFiles) {
    const path = vscode.workspace.asRelativePath(uri, false).toLowerCase();
    if (!path.includes("meeting")) continue;

    const basename = path.split("/").pop()?.replace(/\.md$/, "") || "";

    // Check filename match
    if (basename.includes(nameLower) || basename.includes(nameKebab)) {
      const stat = await vscode.workspace.fs.stat(uri);
      results.push({ uri, mtime: stat.mtime });
      continue;
    }

    // Check frontmatter for attendees
    try {
      const raw = await readVaultFile(
        vscode.workspace.asRelativePath(uri, false)
      );
      const { data: fm } = parseFrontmatter(raw);
      const attendees = fm["attendees"];
      if (Array.isArray(attendees)) {
        const found = attendees.some(
          (a: unknown) =>
            typeof a === "string" &&
            (a.toLowerCase().includes(nameLower) ||
              a.toLowerCase().includes(nameKebab))
        );
        if (found) {
          const stat = await vscode.workspace.fs.stat(uri);
          results.push({ uri, mtime: stat.mtime });
        }
      }
    } catch {
      // skip unreadable
    }
  }

  results.sort((a, b) => b.mtime - a.mtime);
  return results.map((r) => r.uri);
}

/**
 * Find coaching hypothesis notes related to this person.
 */
async function findCoachingNotes(personName: string): Promise<vscode.Uri[]> {
  const allMdFiles = await listVaultFiles("", "**/*.md");
  const results: { uri: vscode.Uri; mtime: number }[] = [];

  const nameLower = personName.toLowerCase();
  const nameKebab = nameToKebab(personName);

  for (const uri of allMdFiles) {
    const path = vscode.workspace.asRelativePath(uri, false).toLowerCase();

    const isCoachingRelated =
      path.includes("coaching") || path.includes("hypothesis");
    if (!isCoachingRelated) continue;

    const basename = path.split("/").pop()?.replace(/\.md$/, "") || "";

    if (basename.includes(nameLower) || basename.includes(nameKebab)) {
      const stat = await vscode.workspace.fs.stat(uri);
      results.push({ uri, mtime: stat.mtime });
      continue;
    }

    // Check frontmatter
    try {
      const raw = await readVaultFile(
        vscode.workspace.asRelativePath(uri, false)
      );
      const { data: fm } = parseFrontmatter(raw);
      const person = fm["person"] || fm["subject"];
      if (
        typeof person === "string" &&
        (person.toLowerCase().includes(nameLower) ||
          person.toLowerCase().includes(nameKebab))
      ) {
        const stat = await vscode.workspace.fs.stat(uri);
        results.push({ uri, mtime: stat.mtime });
      }
    } catch {
      // skip unreadable
    }
  }

  results.sort((a, b) => b.mtime - a.mtime);
  return results.map((r) => r.uri);
}

