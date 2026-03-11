import * as vscode from "vscode";
import { readVaultFile, listVaultFiles, parseFrontmatter } from "../vault";
import { getSettings } from "../settings";
import { QdrantClient } from "../qdrant-client";
import type { QdrantSearchResult } from "../types";
import type { ChatViewProvider } from "../chat-view";

/**
 * Team Snapshot command.
 *
 * Reads all person notes from 10-work/people/, queries Qdrant for team context,
 * and sends to the LLM for synthesis. Output streamed in the chat sidebar.
 */
export async function teamSnapshot(
  context: vscode.ExtensionContext,
  chat: ChatViewProvider,
): Promise<void> {
  vscode.window.showInformationMessage("Generating team snapshot...");

  const settings = getSettings();

  // Step 1: Find all person notes in 10-work/people/
  const personFiles = await findPersonNotes();
  if (personFiles.length === 0) {
    vscode.window.showWarningMessage(
      "No person notes found in 10-work/people/."
    );
    return;
  }

  // Step 2: Read all person notes
  const personSummaries: string[] = [];
  for (const uri of personFiles) {
    try {
      const path = vscode.workspace.asRelativePath(uri, false);
      const content = await readVaultFile(path);
      const name =
        path.split("/").pop()?.replace(/\.md$/, "")?.replace(/-/g, " ") || path;
      personSummaries.push(`## ${name}\n\n${content}`);
    } catch {
      // Skip unreadable files
    }
  }

  // Step 3: Search Qdrant for team-level context
  const qdrant = new QdrantClient(settings);
  let qdrantResults: QdrantSearchResult[] = [];
  try {
    qdrantResults = await qdrant.search(
      "team health performance workload capacity risks blockers",
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

  // Step 4: Build prompt
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

  const prompt = buildTeamPrompt(personSummaries, qdrantContext);

  // Step 5: Send to chat sidebar for LLM synthesis
  vscode.commands.executeCommand("hapax.chatView.focus");
  chat.injectMessage("Generating team snapshot...", prompt);
}

function buildTeamPrompt(
  personSummaries: string[],
  qdrantContext: string
): string {
  let prompt = `Generate a team snapshot. Synthesize the following person notes into a concise team-level view. Include:

- **Capacity overview**: Who has bandwidth, who is stretched. Reference cognitive-load ratings where available
- **Larson state assessment**: Based on aggregate signals, classify team state (falling-behind / treading-water / repaying-debt / innovating). Cite specific evidence
- **Topology alignment**: Note team-type and interaction-mode fields. Flag mismatches between declared type and observed behavior
- **Skill/will distribution**: Summarize skill levels and will signals across team members
- **Risk signals**: Blockers, disengagement indicators, stale 1:1s, overdue coaching
- **Growth patterns**: Who is progressing, who needs attention. Reference career goals where set
- **Action items**: Concrete next steps for the manager

Do NOT speculate on sentiment or emotions. Stick to observable signals from the data.

---

## Team Members (${personSummaries.length})

${personSummaries.join("\n\n---\n\n")}

---
`;

  if (qdrantContext) {
    prompt += `\n## Additional Context (from knowledge base)\n\n${qdrantContext}\n\n---\n`;
  }

  return prompt;
}

/**
 * Find all person-type notes in the 10-work/people/ directory.
 */
async function findPersonNotes(): Promise<vscode.Uri[]> {
  const files = await listVaultFiles("10-work/people", "*.md");
  const personFiles: { uri: vscode.Uri; name: string }[] = [];

  for (const uri of files) {
    try {
      const path = vscode.workspace.asRelativePath(uri, false);
      const raw = await readVaultFile(path);
      const { data: fm } = parseFrontmatter(raw);
      if (fm["type"] === "person") {
        const name = path.split("/").pop()?.replace(/\.md$/, "") || "";
        personFiles.push({ uri, name });
      }
    } catch {
      // skip unreadable
    }
  }

  // Sort alphabetically by name
  personFiles.sort((a, b) => a.name.localeCompare(b.name));
  return personFiles.map((f) => f.uri);
}
