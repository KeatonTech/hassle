/**
 * The shared JSON contract with `hassle validate --json`
 * (packages/hassle-cli/src/hassle_cli/cli.py, backed by `hassle.registry.finding.Finding` --
 * packages/hassle-core/src/hassle/registry/finding.py).
 *
 * MILESTONES M8 test 3: this schema is snapshot-tested on BOTH sides --
 * `packages/hassle-cli/tests/test_cli_commands.py::test_validate_json_reports_findings_with_stable_schema`
 * on the Python side, `src/test/unit/findingsSchema.test.ts` here.
 *
 * Shape (one JSON object on stdout, regardless of exit code):
 *   { "findings": [ { code, severity, file, line, message, fix }, ... ] }
 *
 * `file`/`line` are `null` when a Finding has no source location (mirrors
 * `Finding.file`/`Finding.line` being `str | None` / `int | None` in Python).
 */

export interface JsonFinding {
  code: string;
  severity: string;
  file: string | null;
  line: number | null;
  message: string;
  fix: string;
}

export interface ValidateJsonPayload {
  findings: JsonFinding[];
}

export class MalformedValidateJsonError extends Error {}

/** Builds the error message shown when `hassle validate --json`'s output
 * can't be turned into diagnostics (M8 polish-batch item 1).
 *
 * Two distinct situations share this call site but need different messages:
 *   - stdout was non-empty and genuinely failed to parse as the documented
 *     schema (a real schema mismatch, e.g. an extension/CLI version skew) --
 *     keep the original "check the CLI version" message; it is still
 *     accurate there.
 *   - stdout was EMPTY (nothing ran -- most often because the CLI process
 *     itself never produced output, e.g. every fallback candidate failed to
 *     spawn) -- that "check the CLI version" wording is actively misleading,
 *     since no CLI output was ever produced to have a version mismatch in.
 *     When a `CliInvocationError`-shaped list of attempts is available, list
 *     each command tried with its captured error instead.
 */
export function formatValidateFailureMessage(
  stdout: string,
  parseError: Error,
  attempts?: { label: string; command: string; args: string[]; error?: string }[]
): string {
  const stdoutIsEmpty = stdout.trim() === "";
  if (stdoutIsEmpty && attempts && attempts.length > 0) {
    const lines = attempts.map((a) => {
      const argv = [a.command, ...a.args].join(" ");
      return `  - ${a.label} (\`${argv}\`): ${a.error ?? "produced no output"}`;
    });
    return (
      `Hassle: could not run \`hassle validate --json\` -- every command tried produced no output:\n` +
      lines.join("\n") +
      `\nFix: install the CLI (\`uv tool install -e <repo>/packages/hassle-cli\`) or set ` +
      `"hassle.executablePath" in your workspace settings.`
    );
  }
  if (stdoutIsEmpty) {
    return (
      "Hassle: `hassle validate --json` produced no output. " +
      "Fix: confirm the Hassle CLI is installed and runnable (set \"hassle.executablePath\" if needed)."
    );
  }
  return (
    `Hassle: could not parse \`hassle validate --json\` output (${parseError.message}). ` +
    "Fix: check the Hassle CLI version matches this extension's expected schema."
  );
}

/** Parses and structurally validates one `hassle validate --json` stdout blob.
 * Throws `MalformedValidateJsonError` (never a bare parse exception) so callers
 * can surface a clean "what/where/fix"-style message instead of a raw stack trace. */
export function parseValidateJson(stdout: string): ValidateJsonPayload {
  let raw: unknown;
  try {
    raw = JSON.parse(stdout);
  } catch (err) {
    throw new MalformedValidateJsonError(
      `hassle validate --json produced output that is not valid JSON: ${(err as Error).message}`
    );
  }
  if (typeof raw !== "object" || raw === null || !("findings" in raw)) {
    throw new MalformedValidateJsonError(
      'hassle validate --json output is missing the top-level "findings" array'
    );
  }
  const findings = (raw as { findings: unknown }).findings;
  if (!Array.isArray(findings)) {
    throw new MalformedValidateJsonError('"findings" must be an array');
  }
  for (const f of findings) {
    if (
      typeof f !== "object" ||
      f === null ||
      typeof (f as JsonFinding).code !== "string" ||
      typeof (f as JsonFinding).severity !== "string" ||
      typeof (f as JsonFinding).message !== "string" ||
      typeof (f as JsonFinding).fix !== "string" ||
      !("file" in f) ||
      !("line" in f)
    ) {
      throw new MalformedValidateJsonError(
        `a finding is missing one of code/severity/file/line/message/fix: ${JSON.stringify(f)}`
      );
    }
  }
  return { findings: findings as JsonFinding[] };
}
