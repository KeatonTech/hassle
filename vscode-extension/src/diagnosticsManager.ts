import * as vscode from "vscode";
import { CliInvocationError, CliRunner } from "./cliRunner";
import { groupDiagnosticsByFile } from "./diagnostics";
import { formatValidateFailureMessage, parseValidateJson } from "./findingsSchema";

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

    let result;
    let invocationAttempts: { label: string; command: string; args: string[]; error?: string }[] | undefined;
    try {
      result = await this.cliRunner.run("validate", ["--json"], workspaceRoot);
    } catch (err) {
      if (requestId !== this.latestRequestId) {
        return;
      }
      // Every fallback candidate failed to spawn (CliInvocationError, see
      // cliRunner.ts) -- there is no stdout at all. Route through
      // formatValidateFailureMessage with the empty-stdout branch so the
      // user sees each command tried, not the parse-failure wording.
      this.collection.clear();
      if (err instanceof CliInvocationError) {
        invocationAttempts = err.attempts.map((a) => ({
          label: a.candidate.label,
          command: a.candidate.command,
          args: a.candidate.args,
          error: a.error,
        }));
        vscode.window.showErrorMessage(formatValidateFailureMessage("", err, invocationAttempts));
      } else {
        vscode.window.showErrorMessage(formatValidateFailureMessage("", err as Error));
      }
      return;
    }
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
      vscode.window.showErrorMessage(formatValidateFailureMessage(result.stdout, err as Error));
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
