import * as vscode from "vscode";
export { parseFrontmatter, serializeFrontmatter } from "./frontmatter";

/** Check if the vault is a work vault (contains 10-work/ directory). */
export async function isWorkVault(): Promise<boolean> {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders?.length) return false;
  const workDir = vscode.Uri.joinPath(folders[0].uri, "10-work");
  try {
    const stat = await vscode.workspace.fs.stat(workDir);
    return stat.type === vscode.FileType.Directory;
  } catch {
    return false;
  }
}

/** Get the vault root URI. Throws if no workspace folder is open. */
export function vaultRoot(): vscode.Uri {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders?.length) throw new Error("No workspace folder open");
  return folders[0].uri;
}

/** Read a vault file as UTF-8 string. */
export async function readVaultFile(relativePath: string): Promise<string> {
  const uri = vscode.Uri.joinPath(vaultRoot(), relativePath);
  const bytes = await vscode.workspace.fs.readFile(uri);
  return Buffer.from(bytes).toString("utf-8");
}

/** Write a UTF-8 string to a vault file (creates parent dirs automatically). */
export async function writeVaultFile(
  relativePath: string,
  content: string,
): Promise<void> {
  const uri = vscode.Uri.joinPath(vaultRoot(), relativePath);
  await vscode.workspace.fs.writeFile(uri, Buffer.from(content, "utf-8"));
}

/** List files in a vault directory matching optional glob. */
export async function listVaultFiles(
  relativeDir: string,
  glob?: string,
): Promise<vscode.Uri[]> {
  const pattern = new vscode.RelativePattern(
    vaultRoot(),
    `${relativeDir}/${glob || "**/*"}`,
  );
  return vscode.workspace.findFiles(pattern);
}
