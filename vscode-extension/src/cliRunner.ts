/**
 * Resolves and shells out to the Hassle CLI (packages/hassle-cli, cli.py).
 *
 * CLI invocation fallback chain (supersedes the
 * original single-shot "always `uv run hassle`" design):
 *   1. `hassle.executablePath` workspace setting, if non-empty -- used as the
 *      literal command (split on whitespace, first token is the executable).
 *      An explicit setting wins outright: no fallback is attempted if it
 *      fails, since the user pinned it deliberately.
 *   2. `uv run hassle`, invoked with `cwd` set to the workspace root --
 *      ONLY tried when the workspace root contains a `pyproject.toml` (a bare
 *      non-bundle folder, or a bundle laid out without its own uv project --
 *      see `hassle-cli`'s bundle-as-uv-project scaffolding -- has no `uv` project to run against,
 *      and shelling `uv run` there either fails confusingly or resolves the
 *      wrong environment).
 *   3. Bare `hassle` resolved from PATH -- the fallback when `uv run hassle`
 *      isn't applicable/available, e.g. a `uv tool install`ed CLI with no
 *      per-bundle uv project.
 *
 * Every invocation gets `--plain` appended right after the executable/`run`
 * tokens (before the subcommand) -- the CLI's global `--plain` flag strips
 * rich/ANSI formatting (`hassle_cli/cli.py`'s `main` group), which this
 * extension needs since it parses stdout as plain text or JSON, never ANSI.
 *
 * On total failure (every candidate's process failed to even spawn -- e.g.
 * neither `uv` nor `hassle` exist on PATH), `CliRunner.run` throws a
 * `CliInvocationError` that lists EACH command tried, with its captured
 * spawn error, so the user sees exactly what was attempted instead of a
 * single misleading "could not parse JSON" message.
 */

export interface CliInvocation {
  /** The executable (argv[0]) actually spawned, e.g. "uv" or "/usr/local/bin/hassle". */
  command: string;
  /** Arguments passed to `command`, in order -- includes leading `run hassle` etc. when applicable. */
  args: string[];
}

/** One candidate in the fallback chain: a base command/args pair (before
 * `--plain <subcommand> ...` is appended) plus a human-readable label for
 * error reporting. */
export interface CliCandidate {
  command: string;
  args: string[];
  /** Human-readable description of this candidate, e.g. "uv run hassle" or "hassle (PATH)". */
  label: string;
}

export interface CliResult {
  exitCode: number;
  stdout: string;
  stderr: string;
}

export interface ProcessRunner {
  run(command: string, args: string[], cwd: string): Promise<CliResult>;
}

/** One attempt made while working through the fallback chain: either it
 * produced a `result` (the process spawned, regardless of exit code) or it
 * `error`ed (the process failed to spawn at all, e.g. ENOENT). */
export interface CliAttempt {
  candidate: CliCandidate;
  result?: CliResult;
  error?: string;
}

/** Thrown by `CliRunner.run` when every candidate in the fallback chain
 * failed to spawn. Lists each command tried with its captured error so
 * callers can render a precise message instead of guessing. */
export class CliInvocationError extends Error {
  constructor(public readonly attempts: CliAttempt[]) {
    super(CliInvocationError.formatMessage(attempts));
    this.name = "CliInvocationError";
  }

  private static formatMessage(attempts: CliAttempt[]): string {
    const lines = attempts.map((a) => {
      const argv = [a.candidate.command, ...a.candidate.args].join(" ");
      return `  - ${a.candidate.label} (\`${argv}\`): ${a.error ?? "unknown error"}`;
    });
    return (
      `Hassle: could not run the Hassle CLI -- every command tried failed to start:\n` +
      lines.join("\n") +
      `\nFix: install the CLI (\`uv tool install -e <repo>/packages/hassle-cli\`) or set ` +
      `"hassle.executablePath" in your workspace settings.`
    );
  }
}

const DEFAULT_COMMAND = "uv";
const DEFAULT_BASE_ARGS = ["run", "hassle"];
const BARE_COMMAND = "hassle";

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

/** Builds the ordered list of candidates to try for one invocation, per the
 * fallback chain documented at the top of this file:
 *   - explicit `executablePathSetting` -> that one candidate only;
 *   - else, `hasPyprojectToml` -> [`uv run hassle`, bare `hassle`];
 *   - else -> [bare `hassle`] only (no `uv run` attempt without a project). */
export function buildCandidates(
  executablePathSetting: string | undefined,
  hasPyprojectToml: boolean
): CliCandidate[] {
  const trimmed = (executablePathSetting ?? "").trim();
  if (trimmed !== "") {
    const tokens = trimmed.split(/\s+/);
    return [{ command: tokens[0], args: tokens.slice(1), label: "configured hassle.executablePath" }];
  }
  const candidates: CliCandidate[] = [];
  if (hasPyprojectToml) {
    candidates.push({ command: DEFAULT_COMMAND, args: [...DEFAULT_BASE_ARGS], label: "uv run hassle" });
  }
  candidates.push({ command: BARE_COMMAND, args: [], label: "hassle (PATH)" });
  return candidates;
}

/** Builds the full argv for one CLI subcommand invocation using the FIRST
 * candidate in the fallback chain (i.e. what would be tried first), e.g.
 * `buildInvocation("validate", ["--json"], undefined, true)` produces
 * `{command: "uv", args: ["run", "hassle", "--plain", "validate", "--json"]}`.
 * Kept for callers that only need the primary invocation shape (tests,
 * logging); `CliRunner.run` itself walks the full candidate list. */
export function buildInvocation(
  subcommand: string,
  subcommandArgs: string[],
  executablePathSetting: string | undefined,
  hasPyprojectToml: boolean
): CliInvocation {
  const [primary] = buildCandidates(executablePathSetting, hasPyprojectToml);
  return {
    command: primary.command,
    args: [...primary.args, "--plain", subcommand, ...subcommandArgs],
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

/** Default `hasPyprojectToml` check: looks for `pyproject.toml` directly in
 * the workspace root. Lazily requires `fs`/`path` so this module stays
 * side-effect-free to import in the plain-Node unit test runner. */
function defaultHasPyprojectToml(cwd: string): boolean {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const fs = require("fs") as typeof import("fs");
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const path = require("path") as typeof import("path");
  try {
    return fs.existsSync(path.join(cwd, "pyproject.toml"));
  } catch {
    return false;
  }
}

export class CliRunner {
  private readonly getProcessRunner: () => ProcessRunner;
  private readonly hasPyprojectToml: (cwd: string) => boolean;

  constructor(
    private readonly getExecutablePathSetting: () => string | undefined,
    processRunner: ProcessRunner | (() => ProcessRunner) = new NodeProcessRunner(),
    hasPyprojectToml: (cwd: string) => boolean = defaultHasPyprojectToml
  ) {
    // Accept either a fixed instance (the common case, e.g. plain-Node unit
    // tests constructing a `FakeProcessRunner` up front) or a getter that is
    // re-evaluated on every `.run()` call -- the latter is what lets the
    // `@vscode/test-electron` suite swap in a fake AFTER `activate()` has
    // already constructed this `CliRunner` (see `setProcessRunnerForTesting`
    // in extension.ts; Node's built-in `child_process` module can't be
    // module-mocked inside the real Extension Host process).
    this.getProcessRunner = typeof processRunner === "function" ? processRunner : () => processRunner;
    this.hasPyprojectToml = hasPyprojectToml;
  }

  /** Runs one CLI subcommand, walking the fallback chain (see module docs)
   * until a candidate's process spawns successfully. A candidate that spawns
   * but exits non-zero (a genuine CLI-side error, e.g. validation findings or
   * a bundle error) is NOT a spawn failure -- its result is returned as-is,
   * with no further candidates tried. Only candidates whose process fails to
   * start at all (ENOENT etc.) are skipped in favor of the next candidate.
   * Throws `CliInvocationError` if every candidate fails to spawn. */
  async run(subcommand: string, subcommandArgs: string[], cwd: string): Promise<CliResult> {
    const candidates = buildCandidates(this.getExecutablePathSetting(), this.hasPyprojectToml(cwd));
    const attempts: CliAttempt[] = [];
    for (const candidate of candidates) {
      const args = [...candidate.args, "--plain", subcommand, ...subcommandArgs];
      try {
        const result = await this.getProcessRunner().run(candidate.command, args, cwd);
        return result;
      } catch (err) {
        attempts.push({ candidate, error: (err as Error).message });
      }
    }
    throw new CliInvocationError(attempts);
  }
}
