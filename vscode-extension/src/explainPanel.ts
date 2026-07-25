import * as vscode from "vscode";
import { CliRunner } from "./cliRunner";

/**
 * "Show compiled YAML" side panel (DESIGN §11 layer 2): runs
 * `hassle explain <object_key> --yaml` for the automation/script/helper under
 * the cursor and renders the result in a read-only webview.
 *
 * Object-key detection is intentionally simple: it looks for the nearest
 * preceding `@automation(id="...")` / `@script(id="...")` / `@shared_script(id="...")`
 * decorator above the cursor's line and combines its `kind` with the `id=`
 * value into `kind:id` -- the same `object_key` shape `hassle explain` takes
 * (`hassle_cli/cli.py`'s `explain` command; `kind:object_id`, DESIGN §6).
 * A full DSL-aware "automation under cursor" resolution is LSP-shaped
 * (layer 3, out of scope for this extension for now) -- this regex
 * approach covers the common case (one decorated function per screenful)
 * without a real parser.
 */

const DECORATOR_RE = /@(automation|script|shared_script)\s*\(\s*id\s*=\s*["']([^"']+)["']/;

export function findObjectKeyAtCursor(documentText: string, cursorLine: number): string | null {
  const lines = documentText.split(/\r?\n/);
  for (let i = Math.min(cursorLine, lines.length - 1); i >= 0; i--) {
    const match = DECORATOR_RE.exec(lines[i]);
    if (match) {
      const kind = match[1] === "shared_script" ? "script" : match[1];
      return `${kind}:${match[2]}`;
    }
  }
  return null;
}

export class ExplainPanel {
  private static panel: vscode.WebviewPanel | undefined;

  static async showForCursor(cliRunner: CliRunner, workspaceRoot: string): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
      vscode.window.showWarningMessage("Hassle: open a bundle file first to show its compiled YAML.");
      return;
    }
    const objectKey = findObjectKeyAtCursor(editor.document.getText(), editor.selection.active.line);
    if (objectKey === null) {
      vscode.window.showWarningMessage(
        "Hassle: place the cursor inside (or below) an @automation/@script/@shared_script " +
          "definition to show its compiled YAML."
      );
      return;
    }
    await this.showForObjectKey(cliRunner, workspaceRoot, objectKey);
  }

  static async showForObjectKey(
    cliRunner: CliRunner,
    workspaceRoot: string,
    objectKey: string
  ): Promise<void> {
    const result = await cliRunner.run("explain", [objectKey, "--yaml"], workspaceRoot);
    const body =
      result.exitCode === 0
        ? `<pre>${escapeHtml(result.stdout)}</pre>`
        : `<pre class="error">${escapeHtml(result.stderr || result.stdout)}</pre>`;

    if (!this.panel) {
      this.panel = vscode.window.createWebviewPanel(
        "hassleExplain",
        "Hassle: Compiled YAML",
        vscode.ViewColumn.Beside,
        { enableScripts: false }
      );
      this.panel.onDidDispose(() => {
        this.panel = undefined;
      });
    }
    this.panel.title = `Hassle: ${objectKey}`;
    this.panel.webview.html = renderHtml(objectKey, body);
    this.panel.reveal(vscode.ViewColumn.Beside, true);
  }
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function renderHtml(objectKey: string, body: string): string {
  return `<!DOCTYPE html>
<html>
<head><meta charset="UTF-8" /></head>
<body>
<h2>${escapeHtml(objectKey)}</h2>
${body}
</body>
</html>`;
}
