import * as vscode from "vscode";
import { CliRunner } from "./cliRunner";
import { groupDiagnosticsByFile } from "./diagnostics";
import { parseValidateJson } from "./findingsSchema";

/** Runs `hassle validate --json` and republishes the result into a
 * `vscode.DiagnosticCollection` (the Problems pane) -- DESIGN §11 layer 2.
 *
 * Requests are sequenced with a monotonic counter: `activate()` fires one
 * refresh immediately on startup and commands (`hassle.validate`, and any
 * future file-save watcher) can fire another before the first one's CLI
 * subprocess has returned -- without the guard below, a slow/stale response
 * landing AFTER a newer one would clobber the Problems pane with outdated
 * (or, on a subprocess failure, forcibly cleared) results. Only the response
 * to the most-recently-*started* request is ever applied. */
export class DiagnosticsManager {
  private readonly collection: vscode.DiagnosticCollection;
  private latestRequestId = 0;

  constructor(
    private readonly cliRunner: CliRunner,
    collectionName = "hassle"
  ) {
    this.collection = vscode.languages.createDiagnosticCollection(collectionName);
  }

  async refresh(workspaceRoot: string): Promise<void> {
    const requestId = ++this.latestRequestId;
    const result = await this.cliRunner.run("validate", ["--json"], workspaceRoot);
    if (requestId !== this.latestRequestId) {
      return; // superseded by a newer refresh() call while this one was in flight
    }

    // `hassle validate` exits 1 when findings exist (packages/hassle-cli/src/hassle_cli/cli.py) --
    // that is a NORMAL, expected outcome here, not a tool failure. Only stdout
    // that fails to parse as the documented schema is treated as an error.
    let payload;
    try {
      payload = parseValidateJson(result.stdout);
    } catch (err) {
      this.collection.clear();
      vscode.window.showErrorMessage(
        `Hassle: could not parse \`hassle validate --json\` output (${(err as Error).message}). ` +
          "Fix: check the Hassle CLI version matches this extension's expected schema."
      );
      return;
    }
    this.collection.clear();
    const byFile = groupDiagnosticsByFile(payload.findings, workspaceRoot);
    for (const [absolutePath, diagnostics] of byFile) {
      this.collection.set(vscode.Uri.file(absolutePath), diagnostics);
    }
  }

  dispose(): void {
    this.collection.dispose();
  }
}
