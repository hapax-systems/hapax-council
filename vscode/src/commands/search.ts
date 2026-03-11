import * as vscode from "vscode";
import { getSettings } from "../settings";
import { QdrantClient } from "../qdrant-client";
import type { QdrantSearchResult } from "../types";

interface SearchResult {
  title: string;
  score: number;
  source: string;
  snippet: string;
  vaultPath: string | null;
  collection?: string;
}

const SEARCH_COLLECTIONS = ["documents", "profile-facts", "axiom-precedents"];

/**
 * Knowledge Base Search command.
 *
 * Opens a quick pick input, takes a text query, embeds it via Ollama,
 * searches multiple Qdrant collections, and displays results
 * with links to vault notes where applicable.
 */
export async function openKnowledgeSearch(
  _context: vscode.ExtensionContext
): Promise<void> {
  const query = await vscode.window.showInputBox({
    prompt: "Search knowledge base...",
    placeHolder: "Enter search query (min 3 characters)",
  });

  if (!query || query.length < 3) {
    return;
  }

  const settings = getSettings();
  const qdrant = new QdrantClient(settings);

  // Show progress while searching
  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: "Searching knowledge base...",
      cancellable: false,
    },
    async () => {
      let results: SearchResult[];
      try {
        const multiResults = await qdrant.searchMulti(
          query,
          SEARCH_COLLECTIONS,
          5
        );
        results = multiResults.map((r) => mapResult(r, r.collection));
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        const isLocalhost =
          settings.qdrantUrl.includes("localhost") ||
          settings.qdrantUrl.includes("127.0.0.1");
        if (
          isLocalhost &&
          (err instanceof TypeError ||
            msg.includes("fetch") ||
            msg.includes("ECONNREFUSED"))
        ) {
          vscode.window.showWarningMessage(
            "Knowledge search requires the home network (Qdrant + Ollama)."
          );
        } else {
          vscode.window.showErrorMessage(`Search failed: ${msg}`);
        }
        return;
      }

      if (results.length === 0) {
        vscode.window.showInformationMessage("No results found.");
        return;
      }

      // Show results in a quick pick
      const items = results.map((r) => ({
        label: r.title,
        description: `${(r.score * 100).toFixed(0)}%`,
        detail: r.snippet.slice(0, 200) + (r.snippet.length > 200 ? "..." : ""),
        result: r,
      }));

      const selected = await vscode.window.showQuickPick(items, {
        placeHolder: `${results.length} results for "${query}"`,
        matchOnDescription: true,
        matchOnDetail: true,
      });

      if (!selected) return;

      const result = selected.result;

      if (result.vaultPath) {
        // Open the file in the vault
        try {
          const uri = vscode.Uri.joinPath(
            vscode.workspace.workspaceFolders![0].uri,
            result.vaultPath
          );
          const doc = await vscode.workspace.openTextDocument(uri);
          await vscode.window.showTextDocument(doc);
          return;
        } catch {
          // Fall through to clipboard
        }
      }

      // If no vault path, copy the snippet to clipboard
      await vscode.env.clipboard.writeText(result.snippet);
      vscode.window.showInformationMessage("Snippet copied to clipboard.");
    }
  );
}

function mapResult(
  r: QdrantSearchResult & { collection?: string },
  collection?: string
): SearchResult {
  const payload = r.payload || {};
  const text =
    (payload["text"] as string) || (payload["content"] as string) || "";
  const source =
    (payload["source"] as string) || (payload["file_path"] as string) || "";
  const title =
    (payload["title"] as string) || extractTitle(source, text);

  const vaultPath = resolveVaultPath(source);

  return {
    title,
    score: r.score,
    source: collection ? `[${collection}] ${source}` : source,
    snippet: text,
    vaultPath,
    collection,
  };
}

function extractTitle(source: string, text: string): string {
  if (source) {
    const parts = source.split("/");
    const filename = parts[parts.length - 1];
    return filename.replace(/\.\w+$/, "").replace(/-/g, " ");
  }
  const firstLine = text.split("\n")[0] || "Untitled";
  return firstLine.slice(0, 80);
}

function resolveVaultPath(source: string): string | null {
  if (!source) return null;

  // If source looks like a vault-relative path ending in .md, return it
  if (source.endsWith(".md") && !source.startsWith("/") && !source.startsWith("http")) {
    return source;
  }

  // Try to extract filename and construct a plausible path
  const parts = source.split("/");
  const filename = parts[parts.length - 1];
  if (filename && filename.endsWith(".md")) {
    return source;
  }

  return null;
}
