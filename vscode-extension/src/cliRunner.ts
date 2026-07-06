/**
 * Resolves and shells out to the Hassle CLI (packages/hassle-cli, cli.py).
 *
 * CLI path resolution (per the M8 work-item brief):
 *   1. `hassle.executablePath` workspace setting, if non-empty -- used as the
 *      literal command (split on whitespace, first token is the executable).
 *   2. Default: `uv run hassle`, invoked with `cwd` set to the workspace
 *      root -- matches how a bundle's own `.github/workflows/hassle.yml`
 *      (see `hassle_cli.init_cmd.CI_WORKFLOW`) and the DESIGN §8.4 daily loop
 *      both invoke it: no global install assumed, `uv` resolves the pinned
 *      version from the bundle's own lockfile/environment.
 *
 * Every invocation gets `--plain` appended right after the executable/`run`
 * tokens (before the subcommand) -- the CLI's global `--plain` flag strips
 * rich/ANSI formatting (`hassle_cli/cli.py`'s `main` group), which this
 * extension needs since it parses stdout as plain text or JSON, never ANSI.
 */

export interface CliInvocation {
  /** The executable (argv[0]) actually spawned, e.g. "uv" or "/usr/local/bin/hassle". */
  command: string;
  /** Arguments passed to `command`, in order -- includes leading `run hassle` etc. when applicable. */
  args: string[];
}

export interface CliResult {
  exitCode: number;
  stdout: string;
  stderr: string;
}

export interface ProcessRunner {
  run(command: string, args: string[], cwd: string): Promise<CliResult>;
}

const DEFAULT_COMMAND = "uv";
const DEFAULT_BASE_ARGS = ["run", "hassle"];

/** Splits a user-provided `hassle.executablePath` setting into argv0 + leading args
 * (so a setting like "uv run --project /path hassle" also works). Empty/whitespace-only
 * input means "use the default". */
export function resolveBaseInvocation(executablePathSetting: string | undefined): {
  command: string;
  baseArgs: string[];
} {
  const trimmed = (executablePathSetting ?? "").trim();
  if (trimmed === "") {
    return { command: DEFAULT_COMMAND, baseArgs: [...DEFAULT_BASE_ARGS] };
  }
  const tokens = trimmed.split(/\s+/);
  return { command: tokens[0], baseArgs: tokens.slice(1) };
}

/** Builds the full argv for one CLI subcommand invocation, e.g.
 * `buildInvocation("validate", ["--json"], undefined)` with the default
 * executable setting produces `{command: "uv", args: ["run", "hassle", "--plain", "validate", "--json"]}`. */
export function buildInvocation(
  subcommand: string,
  subcommandArgs: string[],
  executablePathSetting: string | undefined
): CliInvocation {
  const { command, baseArgs } = resolveBaseInvocation(executablePathSetting);
  return {
    command,
    args: [...baseArgs, "--plain", subcommand, ...subcommandArgs],
  };
}

export class NodeProcessRunner implements ProcessRunner {
  run(command: string, args: string[], cwd: string): Promise<CliResult> {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { spawn } = require("child_process") as typeof import("child_process");
    return new Promise((resolve, reject) => {
      const child = spawn(command, args, { cwd });
      let stdout = "";
      let stderr = "";
      child.stdout?.on("data", (chunk: Buffer) => {
        stdout += chunk.toString("utf8");
      });
      child.stderr?.on("data", (chunk: Buffer) => {
        stderr += chunk.toString("utf8");
      });
      child.on("error", (err: Error) => reject(err));
      child.on("close", (code: number | null) => {
        resolve({ exitCode: code ?? -1, stdout, stderr });
      });
    });
  }
}

export class CliRunner {
  private readonly getProcessRunner: () => ProcessRunner;

  constructor(
    private readonly getExecutablePathSetting: () => string | undefined,
    processRunner: ProcessRunner | (() => ProcessRunner) = new NodeProcessRunner()
  ) {
    // Accept either a fixed instance (the common case, e.g. plain-Node unit
    // tests constructing a `FakeProcessRunner` up front) or a getter that is
    // re-evaluated on every `.run()` call -- the latter is what lets the
    // `@vscode/test-electron` suite swap in a fake AFTER `activate()` has
    // already constructed this `CliRunner` (see `setProcessRunnerForTesting`
    // in extension.ts; Node's built-in `child_process` module can't be
    // module-mocked inside the real Extension Host process).
    this.getProcessRunner = typeof processRunner === "function" ? processRunner : () => processRunner;
  }

  async run(subcommand: string, subcommandArgs: string[], cwd: string): Promise<CliResult> {
    const invocation = buildInvocation(subcommand, subcommandArgs, this.getExecutablePathSetting());
    return this.getProcessRunner().run(invocation.command, invocation.args, cwd);
  }
}
