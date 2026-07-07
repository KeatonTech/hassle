import * as assert from "assert";
import {
  MalformedValidateJsonError,
  formatValidateFailureMessage,
  parseValidateJson,
} from "../../findingsSchema";

// Canned --json output, matching the shape
// packages/hassle-cli/tests/test_cli_commands.py::test_validate_json_reports_findings_with_stable_schema
// asserts on the Python side -- this is the shared-contract snapshot test's
// TypeScript half (MILESTONES M8 test 3).
const CANNED_FINDING_JSON = JSON.stringify({
  findings: [
    {
      code: "unknown-entity",
      severity: "error",
      file: "a.py",
      line: 6,
      message: "unknown entity light.halway",
      fix: "did you mean light.hallway?",
    },
  ],
});

describe("findingsSchema: parseValidateJson", () => {
  it("parses a clean-bundle payload (empty findings array)", () => {
    const payload = parseValidateJson(JSON.stringify({ findings: [] }));
    assert.deepStrictEqual(payload, { findings: [] });
  });

  it("parses the canned multi-field finding exactly (field-for-field)", () => {
    const payload = parseValidateJson(CANNED_FINDING_JSON);
    assert.strictEqual(payload.findings.length, 1);
    assert.deepStrictEqual(payload.findings[0], {
      code: "unknown-entity",
      severity: "error",
      file: "a.py",
      line: 6,
      message: "unknown entity light.halway",
      fix: "did you mean light.hallway?",
    });
  });

  it("accepts a finding with null file/line (no source location)", () => {
    const payload = parseValidateJson(
      JSON.stringify({
        findings: [
          { code: "x", severity: "warning", file: null, line: null, message: "m", fix: "f" },
        ],
      })
    );
    assert.strictEqual(payload.findings[0].file, null);
    assert.strictEqual(payload.findings[0].line, null);
  });

  it("throws MalformedValidateJsonError on invalid JSON", () => {
    assert.throws(() => parseValidateJson("not json"), MalformedValidateJsonError);
  });

  it("throws MalformedValidateJsonError when the top-level findings key is missing", () => {
    assert.throws(() => parseValidateJson(JSON.stringify({ oops: [] })), MalformedValidateJsonError);
  });

  it("throws MalformedValidateJsonError when a finding is missing a required field", () => {
    assert.throws(
      () =>
        parseValidateJson(
          JSON.stringify({ findings: [{ code: "x", severity: "error", message: "m", fix: "f" }] })
        ),
      MalformedValidateJsonError
    );
  });
});

describe("findingsSchema: formatValidateFailureMessage (M8 polish-batch item 1)", () => {
  it("keeps the original 'check the CLI version' message for genuinely unparseable NON-empty stdout", () => {
    const msg = formatValidateFailureMessage("not json at all", new Error("Unexpected token"));
    assert.ok(msg.includes("could not parse"));
    assert.ok(msg.includes("check the Hassle CLI version"));
  });

  it("lists every command tried, with its error, when stdout is empty and attempts are provided", () => {
    const msg = formatValidateFailureMessage("", new Error("Unexpected end of JSON input"), [
      { label: "uv run hassle", command: "uv", args: ["run", "hassle"], error: "spawn uv ENOENT" },
      { label: "hassle (PATH)", command: "hassle", args: [], error: "spawn hassle ENOENT" },
    ]);
    assert.ok(!msg.includes("check the Hassle CLI version"), "must not use the misleading version-mismatch wording");
    assert.ok(msg.includes("uv run hassle"));
    assert.ok(msg.includes("spawn uv ENOENT"));
    assert.ok(msg.includes("hassle (PATH)"));
    assert.ok(msg.includes("spawn hassle ENOENT"));
  });

  it("falls back to a generic empty-output message when stdout is empty but no attempts are known", () => {
    const msg = formatValidateFailureMessage("", new Error("Unexpected end of JSON input"));
    assert.ok(!msg.includes("check the Hassle CLI version"));
    assert.ok(msg.includes("produced no output"));
  });

  it("treats whitespace-only stdout the same as empty", () => {
    const msg = formatValidateFailureMessage("   \n  ", new Error("boom"), [
      { label: "hassle (PATH)", command: "hassle", args: [], error: "spawn hassle ENOENT" },
    ]);
    assert.ok(msg.includes("hassle (PATH)"));
  });
});
