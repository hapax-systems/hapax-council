/**
 * Vault writer for interview-extracted data (VS Code port).
 *
 * Creates or updates vault notes via the VS Code workspace API.
 * Three output types: person_note, reference_doc, frontmatter_update.
 *
 * Respects mg-boundary-001/002 — writes factual data only,
 * never generates management advice or feedback language.
 */
import * as vscode from "vscode";
import {
  readVaultFile,
  writeVaultFile,
  parseFrontmatter,
  serializeFrontmatter,
  vaultRoot,
} from "../vault";

/**
 * Normalize a person name to kebab-case for vault filenames.
 * Transliterates common accented characters before stripping.
 */
export function nameToKebab(name: string): string {
  return name
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-");
}

export interface PersonData {
  name: string;
  role?: string;
  team?: string;
  status?: string;
  cadence?: string;
  [key: string]: string | number | boolean | undefined;
}

export interface ReferenceDocData {
  id: string;
  title: string;
  content: string;
}

/**
 * Check if a file exists in the vault.
 */
async function fileExists(relativePath: string): Promise<boolean> {
  try {
    const uri = vscode.Uri.joinPath(vaultRoot(), relativePath);
    await vscode.workspace.fs.stat(uri);
    return true;
  } catch {
    return false;
  }
}

/**
 * Create a person note in 10-work/people/{name}.md
 */
export async function createPersonNote(
  data: PersonData,
): Promise<string | null> {
  const kebabName = nameToKebab(data.name);
  const path = `10-work/people/${kebabName}.md`;

  // Don't overwrite existing notes
  if (await fileExists(path)) {
    vscode.window.showInformationMessage(`Person note already exists: ${path}`);
    return path;
  }

  const frontmatter = [
    "---",
    "type: person",
    `status: ${data.status || "active"}`,
    `role: ${data.role || "direct-report"}`,
    `team: ${data.team || ""}`,
    `cadence: ${data.cadence || ""}`,
    `cognitive-load: `,
    `growth-vector: `,
    `feedback-style: `,
    `coaching-active: false`,
    `skill-level: `,
    `will-signal: `,
    `career-goal-3y: `,
    `current-gaps: `,
    `current-focus: `,
    `last-career-convo: `,
    `team-type: `,
    `interaction-mode: `,
    "---",
  ].join("\n");

  const body = `\n# ${data.name}\n\n## Contact\n\n## Status\n\n## Notes\n`;
  const content = frontmatter + body;

  try {
    await writeVaultFile(path, content);
    vscode.window.showInformationMessage(`Created person note: ${data.name}`);
    return path;
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    vscode.window.showErrorMessage(`Failed to create person note: ${msg}`);
    return null;
  }
}

/**
 * Create a reference document in 10-work/references/{id}.md
 */
export async function createReferenceDoc(
  data: ReferenceDocData,
): Promise<string | null> {
  const path = `10-work/references/${data.id}.md`;

  // Don't overwrite existing
  if (await fileExists(path)) {
    vscode.window.showInformationMessage(
      `Reference doc already exists: ${path}`,
    );
    return path;
  }

  const content = [
    "---",
    "type: reference",
    `date: ${new Date().toISOString().split("T")[0]}`,
    "---",
    "",
    `# ${data.title}`,
    "",
    data.content,
    "",
  ].join("\n");

  try {
    await writeVaultFile(path, content);
    vscode.window.showInformationMessage(
      `Created reference doc: ${data.title}`,
    );
    return path;
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    vscode.window.showErrorMessage(`Failed to create reference doc: ${msg}`);
    return null;
  }
}

/**
 * Update frontmatter fields on an existing person note.
 */
export async function updateFrontmatter(
  personName: string,
  fields: Record<string, string | number | boolean>,
): Promise<boolean> {
  const kebabName = nameToKebab(personName);
  const path = `10-work/people/${kebabName}.md`;

  if (!(await fileExists(path))) {
    vscode.window.showWarningMessage(`Person note not found: ${personName}`);
    return false;
  }

  try {
    const raw = await readVaultFile(path);
    const { data, content } = parseFrontmatter(raw);
    for (const [key, value] of Object.entries(fields)) {
      data[key] = value;
    }
    const updated = serializeFrontmatter(data, content);
    await writeVaultFile(path, updated);
    vscode.window.showInformationMessage(
      `Updated ${personName}: ${Object.keys(fields).join(", ")}`,
    );
    return true;
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    vscode.window.showErrorMessage(`Failed to update frontmatter: ${msg}`);
    return false;
  }
}
