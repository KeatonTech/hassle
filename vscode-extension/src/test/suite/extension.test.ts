import * as assert from "assert";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";
import { CliRunner, ProcessRunner } from "../../cliRunner";
import { DiagnosticsManager } from "../../diagnosticsManager";
import { setProcessRunnerForTesting } from "../../extension";

/**
 * MILESTONES M8 test 2: `@vscode/test-electron` integration suite.
 *
 *   - each command invokes the CLI with correct args (CLI mocked: a fake
 *     `ProcessRunner` is injected via `setProcessRunnerForTesting`, so no
 *     real `uv`/`hassle` process ever runs -- Node's built-in
 *     `child_process` module is non-configurable inside the real Extension
 *     Host, so module-level mocking doesn't work here the way it can in the
 *     plain-Node unit suite);
 *   - validate findings appear as diagnostics with correct ranges;
 *   - explain panel renders for the automation under the cursor.
 *
 * Runs inside a real VS Code Extension Host against
 * `src/test/suite/fixtureWorkspace` (a minimal bundle with `hassle.toml`
 * AND a `pyproject.toml` -- polish-batch item 1's fallback chain only takes
 * the `uv run hassle` branch when one is present, so the fixture workspace
 * carries one to pin that branch for the arg-shape assertions below; the
 * no-pyproject bare-`hassle` fallback is exercised separately, against an
 * isolated temp directory, in its own suite further down) launched by
 * `src/test/runTest.ts`.
 */

const EXTENSION_ID = "REPLACE_WITH_YOUR_PUBLISHER_ID.hassle-vscode";

interface Canned {
  stdout?: string;
  stderr?: string;
  exitCode?: number;
}

/** A fake `ProcessRunner` that records every invocation and replies with a
 * canned result -- the extension-host-safe equivalent of stubbing `child_process.spawn`. */
class FakeProcessRunner implements ProcessRunner {
  calls: { command: string; args: string[]; cwd: string }[] = [];
  constructor(private readonly canned: Canned) {}
  async run(command: string, args: string[], cwd: string) {
    this.calls.push({ command, args, cwd });
    return {
      exitCode: this.canned.exitCode ?? 0,
      stdout: this.canned.stdout ?? "",
      stderr: this.canned.stderr ?? "",
    };
  }
}

async function ensureActivated(): Promise<void> {
  const ext = vscode.extensions.getExtension(EXTENSION_ID);
  assert.ok(ext, `extension ${EXTENSION_ID} should be discoverable`);
  if (!ext!.isActive) {
    await ext!.activate();
  }
}

suite("Hassle extension: activation", () => {
  test("activates in a workspace containing hassle.toml", async () => {
    await ensureActivated();
    const ext = vscode.extensions.getExtension(EXTENSION_ID);
    assert.strictEqual(ext!.isActive, true);
  });

  test("registers the full M8 command inventory", async () => {
    const commands = await vscode.commands.getCommands(true);
    for (const cmd of [
      "hassle.pull",
      "hassle.plan",
      "hassle.push",
      "hassle.validate",
      "hassle.test",
      "hassle.run",
      "hassle.showCompiledYaml",
    ]) {
      assert.ok(commands.includes(cmd), `expected command ${cmd} to be registered`);
    }
  });
});

suite("Hassle extension: commands shell to the CLI with correct args", () => {
  teardown(() => {
    setProcessRunnerForTesting(undefined);
  });

  test("hassle.plan invokes `uv run hassle --plain plan`", async () => {
    await ensureActivated();
    const fake = new FakeProcessRunner({ stdout: "no changes", exitCode: 0 });
    setProcessRunnerForTesting(fake);

    await vscode.commands.executeCommand("hassle.plan");
    await new Promise((resolve) => setTimeout(resolve, 100));

    assert.strictEqual(fake.calls.length, 1);
    assert.strictEqual(fake.calls[0].command, "uv");
    assert.deepStrictEqual(fake.calls[0].args, ["run", "hassle", "--plain", "plan"]);
  });

  test("hassle.validate invokes plain validate for output plus validate --json for diagnostics", async () => {
    await ensureActivated();
    const fake = new FakeProcessRunner({ stdout: JSON.stringify({ findings: [] }), exitCode: 0 });
    setProcessRunnerForTesting(fake);

    await vscode.commands.executeCommand("hassle.validate");
    await new Promise((resolve) => setTimeout(resolve, 100));

    // args are ["run", "hassle", "--plain", "validate", ...]; drop the first
    // three tokens to compare just the hassle-subcommand-and-onward part.
    const subcommands = fake.calls.map((c) => c.args.slice(3));
    assert.ok(
      subcommands.some((args) => args[0] === "validate" && !args.includes("--json")),
      `expected a plain "validate" invocation among: ${JSON.stringify(subcommands)}`
    );
    assert.ok(
      subcommands.some((args) => args[0] === "validate" && args.includes("--json")),
      `expected a "validate --json" invocation among: ${JSON.stringify(subcommands)}`
    );
  });
});

suite("Hassle extension: no-pyproject.toml falls back to bare `hassle` (polish-batch item 1)", () => {
  // Exercised directly against `CliRunner` (not through a registered
  // `hassle.*` command) so it doesn't need a SECOND VS Code workspace with
  // no pyproject.toml -- `fixtureWorkspace` itself now carries one (see the
  // suite above), so this test targets an isolated, freshly created temp
  // directory instead, mirroring the "regression: a slow, stale refresh()"
  // test's own direct-`CliRunner` pattern further down this file.
  test("invokes bare `hassle` (never `uv run hassle`) when the target directory has no pyproject.toml", async () => {
    const noProjectDir = fs.mkdtempSync(path.join(os.tmpdir(), "hassle-vscode-no-pyproject-"));
    try {
      const fake = new FakeProcessRunner({ stdout: "no changes", exitCode: 0 });
      const cliRunner = new CliRunner(() => undefined, fake);

      const result = await cliRunner.run("plan", [], noProjectDir);

      assert.strictEqual(result.stdout, "no changes");
      assert.strictEqual(fake.calls.length, 1);
      assert.strictEqual(fake.calls[0].command, "hassle");
      assert.deepStrictEqual(fake.calls[0].args, ["--plain", "plan"]);
      assert.strictEqual(fake.calls[0].cwd, noProjectDir);
    } finally {
      fs.rmSync(noProjectDir, { recursive: true, force: true });
    }
  });
});

suite("Hassle extension: validate diagnostics", () => {
  teardown(() => {
    setProcessRunnerForTesting(undefined);
  });

  test("a validate --json finding becomes a Problems-pane diagnostic with the right range", async () => {
    await ensureActivated();
    const workspaceRoot = vscode.workspace.workspaceFolders![0].uri.fsPath;
    const findingFile = path.join(workspaceRoot, "automations", "hallway.py");
    const fake = new FakeProcessRunner({
      stdout: JSON.stringify({
        findings: [
          {
            code: "unknown-entity",
            severity: "error",
            file: "automations/hallway.py",
            line: 6,
            message: "unknown entity light.halway",
            fix: "did you mean light.hallway?",
          },
        ],
      }),
      exitCode: 1,
    });
    setProcessRunnerForTesting(fake);

    await vscode.commands.executeCommand("hassle.validate");
    await new Promise((resolve) => setTimeout(resolve, 300));

    const targetUri = vscode.Uri.file(findingFile).toString();
    const [, diags] =
      vscode.languages.getDiagnostics().find(([uri]) => uri.toString() === targetUri) ?? [];
    assert.ok(diags, `expected a diagnostics entry for ${targetUri}`);
    assert.strictEqual(diags!.length, 1, `expected exactly one diagnostic, got ${diags?.length ?? 0}`);
    const diag = diags![0];
    assert.strictEqual(diag.range.start.line, 5); // 0-based, Finding.line is 1-based (6)
    assert.strictEqual(diag.severity, vscode.DiagnosticSeverity.Error);
    assert.ok(diag.message.includes("light.halway"));
    assert.ok(diag.message.includes("Fix:"));
    assert.strictEqual(diag.code, "unknown-entity");
    assert.strictEqual(diag.source, "hassle");
  });

  test("regression: a slow, stale refresh() cannot clobber a newer one's results", async () => {
    // Bug found while writing the test above: `DiagnosticsManager.refresh()`
    // had no request sequencing -- a slow-to-resolve call (e.g. the
    // activation-time refresh racing a `hassle.validate` command's own
    // refresh) that resolved AFTER a newer call would blindly `.clear()` and
    // overwrite the Problems pane with its own (older, possibly empty)
    // results. Fixed with a monotonic `latestRequestId` guard in
    // `diagnosticsManager.ts`; this test pins that behavior directly against
    // `DiagnosticsManager`, independent of the extension's own activation
    // timing (which is what originally surfaced it, non-deterministically).
    const workspaceRoot = vscode.workspace.workspaceFolders![0].uri.fsPath;

    // A file distinct from every other test's `automations/hallway.py` --
    // `vscode.languages.getDiagnostics()` merges entries from every
    // registered `DiagnosticCollection` for a given URI (collections are not
    // singletons by name: two `createDiagnosticCollection("hassle")` calls
    // return two independent collections), so reusing `hallway.py` here could
    // pick up a leftover finding this suite's earlier test left on it.
    const regressionTargetRelativePath = "automations/regression_target.py";

    class DelayedThenFakeProcessRunner implements ProcessRunner {
      private callIndex = 0;
      async run(_command: string, _args: string[], _cwd: string) {
        const index = this.callIndex++;
        if (index === 0) {
          // First call: slow, and resolves to "no findings" -- simulates the
          // stale activation-time refresh.
          await new Promise((resolve) => setTimeout(resolve, 150));
          return { exitCode: 0, stdout: JSON.stringify({ findings: [] }), stderr: "" };
        }
        // Second call: fast, and resolves to one real finding -- simulates a
        // newer, user-triggered refresh that should win.
        return {
          exitCode: 1,
          stdout: JSON.stringify({
            findings: [
              {
                code: "unknown-entity",
                severity: "error",
                file: regressionTargetRelativePath,
                line: 6,
                message: "unknown entity light.halway",
                fix: "did you mean light.hallway?",
              },
            ],
          }),
          stderr: "",
        };
      }
    }

    const cliRunner = new CliRunner(() => undefined, new DelayedThenFakeProcessRunner());
    const manager = new DiagnosticsManager(cliRunner, "hassle-test-regression");
    try {
      const stalePromise = manager.refresh(workspaceRoot); // starts first, resolves last
      await manager.refresh(workspaceRoot); // starts second, resolves first
      await stalePromise; // let the stale one land too -- it must be a no-op

      const targetUri = vscode.Uri.file(path.join(workspaceRoot, regressionTargetRelativePath)).toString();
      const [, diags] =
        vscode.languages.getDiagnostics().find(([uri]) => uri.toString() === targetUri) ?? [];
      assert.ok(diags, "expected the newer refresh's finding to still be present");
      assert.strictEqual(diags!.length, 1, `expected exactly one diagnostic, got ${diags?.length ?? 0}`);
    } finally {
      manager.dispose();
    }
  });
});

suite("Hassle extension: explain panel", () => {
  teardown(() => {
    setProcessRunnerForTesting(undefined);
  });

  test("renders compiled YAML for the automation under the cursor", async () => {
    await ensureActivated();
    const workspaceRoot = vscode.workspace.workspaceFolders![0].uri.fsPath;
    const filePath = path.join(workspaceRoot, "automations", "hallway.py");
    const document = await vscode.workspace.openTextDocument(filePath);
    const editor = await vscode.window.showTextDocument(document);
    editor.selection = new vscode.Selection(new vscode.Position(5, 0), new vscode.Position(5, 0));

    const fake = new FakeProcessRunner({
      stdout: "alias: Hallway light on motion\nid: hall_light_on_motion\n",
      exitCode: 0,
    });
    setProcessRunnerForTesting(fake);

    await vscode.commands.executeCommand("hassle.showCompiledYaml");
    await new Promise((resolve) => setTimeout(resolve, 200));

    const explainCall = fake.calls.find((c) => c.args.includes("explain"));
    assert.ok(explainCall, "expected an `explain` invocation");
    assert.ok(explainCall!.args.includes("automation:hall_light_on_motion"));
    assert.ok(explainCall!.args.includes("--yaml"));
  });
});
