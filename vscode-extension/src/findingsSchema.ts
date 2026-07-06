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
