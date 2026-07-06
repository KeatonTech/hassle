import * as os from "os";
import * as path from "path";
import { runTests } from "@vscode/test-electron";

/**
 * MILESTONES M8 test 2: a real `@vscode/test-electron` run -- downloads (or
 * reuses a cached) VS Code build and launches the actual Extension Host
 * against `src/test/suite/fixtureWorkspace`, running `suite/index.ts`'s
 * Mocha suite inside it. This is the ONE run in the matrix that must execute
 * headless in CI (see `.github/workflows/node.yml`), matching the M8 note
 * "at least one @vscode/test-electron run must execute headless in CI".
 */
async function main(): Promise<void> {
  const extensionDevelopmentPath = path.resolve(__dirname, "../../");
  const extensionTestsPath = path.resolve(__dirname, "./suite/index");
  // The fixture workspace is plain data (not `.ts`), so `tsc` never copies it
  // into `out/` -- read it from `src/` regardless of where this compiled
  // file itself ends up running from.
  const fixtureWorkspace = path.resolve(
    extensionDevelopmentPath,
    "src/test/suite/fixtureWorkspace"
  );

  // VS Code's `--user-data-dir` opens a Unix domain socket under it whose
  // path must stay under ~103 chars (OS limit) -- this repo lives under a
  // long per-agent worktree path (`.claude/worktrees/agent-<hash>/...`),
  // which overflows that limit if VS Code's default (inside this repo's own
  // `.vscode-test/`) is used. Route both dirs through the OS temp dir instead
  // (always short, e.g. `/tmp/...`), keyed so parallel runs don't collide.
  const shortTmpRoot = path.join(os.tmpdir(), `hassle-vscode-test-${process.pid}`);

  await runTests({
    extensionDevelopmentPath,
    extensionTestsPath,
    launchArgs: [
      fixtureWorkspace,
      "--disable-extensions",
      `--user-data-dir=${path.join(shortTmpRoot, "user-data")}`,
      `--extensions-dir=${path.join(shortTmpRoot, "extensions")}`,
    ],
  });
}

main().catch((err) => {
  // eslint-disable-next-line no-console
  console.error("Failed to run integration tests:", err);
  process.exit(1);
});
