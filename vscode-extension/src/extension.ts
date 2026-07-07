import * as vscode from "vscode";
import { CliInvocationError, CliRunner, NodeProcessRunner, ProcessRunner } from "./cliRunner";
import { DiagnosticsManager } from "./diagnosticsManager";
import { ExplainPanel } from "./explainPanel";
import { HassleStatusBar } from "./statusBar";

/**
 * Hassle VS Code extension activation (DESIGN §11 layer 2).
 *
 * Command inventory (also declared in package.json's `contributes.commands`):
 *   hassle.pull, hassle.plan, hassle.push, hassle.validate, hassle.test,
 *   hassle.run, hassle.showCompiledYaml
 *
 * Every command shells to the CLI via `CliRunner` (src/cliRunner.ts) and
 * prints raw stdout/stderr to a shared Output channel -- this extension does
 * not re-render the CLI's own plain-text output, it just surfaces it
 * (the CLI is the single source of truth for what happened, DESIGN §8.4).
 */

let output: vscode.OutputChannel;

// Test-only seam (mirrors `hassle_cli.backend_factory`'s `fake://` registration
// pattern on the Python side): `@vscode/test-electron` runs the real Extension
// Host, which cannot mock `child_process.spawn` at the module level (Node's
// built-in module properties are non-configurable there) -- so tests inject a
// fake `ProcessRunner` here instead, never touching the real subprocess layer.
// Never set by production code paths.
let processRunnerOverrideForTesting: ProcessRunner | undefined;

export function setProcessRunnerForTesting(runner: ProcessRunner | undefined): void {
  processRunnerOverrideForTesting = runner;
}

function workspaceRoot(): string | undefined {
  return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
}

function getExecutablePathSetting(): string | undefined {
  return vscode.workspace.getConfiguration("hassle").get<string>("executablePath");
}

async function runAndShowOutput(
  cliRunner: CliRunner,
  subcommand: string,
  args: string[],
  label: string
): Promise<void> {
  const root = workspaceRoot();
  if (!root) {
    vscode.window.showErrorMessage("Hassle: open a folder containing hassle.toml first.");
    return;
  }
  output.appendLine(`$ hassle --plain ${subcommand} ${args.join(" ")}`);
  let result;
  try {
    result = await cliRunner.run(subcommand, args, root);
  } catch (err) {
    // Every fallback candidate failed to spawn (CliInvocationError lists each
    // command tried, with its error -- see cliRunner.ts).
    const message = err instanceof CliInvocationError ? err.message : (err as Error).message;
    output.appendLine(message);
    output.show(true);
    vscode.window.showErrorMessage(`Hassle: ${label} could not run. See Output panel.`);
    return;
  }
  output.appendLine(result.stdout);
  if (result.stderr) {
    output.appendLine(result.stderr);
  }
  output.show(true);
  if (result.exitCode !== 0) {
    vscode.window.showErrorMessage(`Hassle: ${label} failed (exit ${result.exitCode}). See Output panel.`);
  } else {
    vscode.window.showInformationMessage(`Hassle: ${label} complete.`);
  }
}

export function activate(context: vscode.ExtensionContext): void {
  output = vscode.window.createOutputChannel("Hassle");
  const defaultProcessRunner = new NodeProcessRunner();
  const cliRunner = new CliRunner(
    getExecutablePathSetting,
    () => processRunnerOverrideForTesting ?? defaultProcessRunner
  );
  const diagnostics = new DiagnosticsManager(cliRunner);
  const statusBar = new HassleStatusBar();

  const refreshDiagnostics = async () => {
    const root = workspaceRoot();
    if (root) {
      await diagnostics.refresh(root);
    }
  };

  context.subscriptions.push(
    output,
    diagnostics,
    statusBar,
    vscode.commands.registerCommand("hassle.pull", () =>
      runAndShowOutput(cliRunner, "pull", [], "pull")
    ),
    vscode.commands.registerCommand("hassle.plan", () =>
      runAndShowOutput(cliRunner, "plan", [], "plan")
    ),
    vscode.commands.registerCommand("hassle.push", () =>
      runAndShowOutput(cliRunner, "push", [], "push")
    ),
    vscode.commands.registerCommand("hassle.validate", async () => {
      await runAndShowOutput(cliRunner, "validate", [], "validate");
      await refreshDiagnostics();
    }),
    vscode.commands.registerCommand("hassle.test", () =>
      runAndShowOutput(cliRunner, "test", [], "test")
    ),
    vscode.commands.registerCommand("hassle.run", async () => {
      const target = await vscode.window.showInputBox({
        prompt: "Automation to run on the simulator (e.g. hallway.py::hall_light_on_motion)",
      });
      if (!target) {
        return;
      }
      await runAndShowOutput(cliRunner, "run", [target], "run");
    }),
    vscode.commands.registerCommand("hassle.showCompiledYaml", async () => {
      const root = workspaceRoot();
      if (!root) {
        vscode.window.showErrorMessage("Hassle: open a folder containing hassle.toml first.");
        return;
      }
      await ExplainPanel.showForCursor(cliRunner, root);
    })
  );

  void refreshDiagnostics();
}

export function deactivate(): void {
  // No explicit teardown beyond `context.subscriptions` disposables above.
}
