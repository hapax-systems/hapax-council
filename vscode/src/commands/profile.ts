import * as vscode from "vscode";
import * as fs from "fs/promises";
import * as path from "path";
import * as os from "os";

interface ProfileDigest {
  generated_at: string;
  dimensions: Record<string, { summary: string; fact_count: number }>;
}

/**
 * Display operator profile dimensions from the profiler digest.
 * Reads the digest JSON from the ai-agents profile directory
 * and presents it as a webview panel.
 */
export async function viewProfile(
  context: vscode.ExtensionContext
): Promise<void> {
  const panel = vscode.window.createWebviewPanel(
    "hapaxProfile",
    "Operator Profile",
    vscode.ViewColumn.One,
    { enableScripts: false }
  );

  try {
    const digestPath = path.join(
      os.homedir(),
      "projects",
      "ai-agents",
      "profiles",
      "operator-digest.json"
    );
    const raw = await fs.readFile(digestPath, "utf-8");
    const digest: ProfileDigest = JSON.parse(raw);

    panel.webview.html = buildProfileHtml(digest);
  } catch {
    panel.webview.html = buildErrorHtml();
  }
}

function buildProfileHtml(digest: ProfileDigest): string {
  const cards = Object.entries(digest.dimensions)
    .map(
      ([dimension, data]) => `
      <div class="card">
        <div class="card-header">
          <strong>${escapeHtml(dimension.replace(/_/g, " "))}</strong>
          <span class="fact-count">${data.fact_count} facts</span>
        </div>
        <p>${escapeHtml(data.summary || "No summary available")}</p>
      </div>`
    )
    .join("\n");

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Operator Profile</title>
  <style>
    body {
      font-family: var(--vscode-font-family, sans-serif);
      color: var(--vscode-foreground);
      background: var(--vscode-editor-background);
      padding: 16px;
      margin: 0;
    }
    h2 { margin-top: 0; }
    .timestamp {
      color: var(--vscode-descriptionForeground);
      font-size: 0.85em;
      margin-bottom: 16px;
      display: block;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
      gap: 12px;
    }
    .card {
      border: 1px solid var(--vscode-panel-border);
      border-radius: 4px;
      padding: 12px;
      background: var(--vscode-editorWidget-background);
    }
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 8px;
    }
    .card-header strong {
      text-transform: capitalize;
    }
    .fact-count {
      color: var(--vscode-descriptionForeground);
      font-size: 0.85em;
    }
    .card p {
      margin: 0;
      line-height: 1.4;
    }
  </style>
</head>
<body>
  <h2>Operator Profile</h2>
  <span class="timestamp">Generated: ${escapeHtml(digest.generated_at)}</span>
  <div class="grid">
    ${cards}
  </div>
</body>
</html>`;
}

function buildErrorHtml(): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Operator Profile</title>
  <style>
    body {
      font-family: var(--vscode-font-family, sans-serif);
      color: var(--vscode-foreground);
      background: var(--vscode-editor-background);
      padding: 16px;
      margin: 0;
    }
  </style>
</head>
<body>
  <h2>Operator Profile</h2>
  <p>Profile digest not found. Run: <code>cd ~/projects/ai-agents && uv run python -m agents.profiler --digest</code></p>
</body>
</html>`;
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
