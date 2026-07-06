import * as vscode from "vscode";
import { JsonFinding } from "./findingsSchema";

/**
 * Maps `hassle validate --json` Findings to `vscode.Diagnostic`s in the
 * Problems pane (DESIGN §11 layer 2).
 *
 * Range mapping: a Finding's `line` is 1-based (matches every other file:line
 * the CLI prints, e.g. compiler error snapshots) while `vscode.Position` is
 * 0-based -- subtract 1. Findings carry no column information, so each
 * diagnostic spans the whole line (column 0 to end-of-line is approximated
 * as a very wide range; VS Code clamps it to the actual line length when
 * rendering the squiggle).
 *
 * A Finding with `file: null` (no source location) is not attributable to any
 * document and is dropped from the per-file diagnostics map -- there is
 * nowhere in the Problems pane to anchor it; command output (the Output
 * channel) still shows it via the plain-text `hassle validate` fallback.
 */

const LINE_END_APPROXIMATION = 100000;

export function severityToDiagnosticSeverity(severity: string): vscode.DiagnosticSeverity {
  switch (severity.toLowerCase()) {
    case "error":
      return vscode.DiagnosticSeverity.Error;
    case "warning":
      return vscode.DiagnosticSeverity.Warning;
    case "info":
    case "information":
      return vscode.DiagnosticSeverity.Information;
    case "hint":
      return vscode.DiagnosticSeverity.Hint;
    default:
      // Unknown severities still render (never silently dropped) -- default
      // to Warning rather than Error, since we can't distinguish an unfamiliar
      // future severity string from an intentionally soft one.
      return vscode.DiagnosticSeverity.Warning;
  }
}

export function findingToDiagnostic(finding: JsonFinding): vscode.Diagnostic {
  const line = finding.line !== null && finding.line > 0 ? finding.line - 1 : 0;
  const range = new vscode.Range(
    new vscode.Position(line, 0),
    new vscode.Position(line, LINE_END_APPROXIMATION)
  );
  const message = `${finding.message} Fix: ${finding.fix}`;
  const diagnostic = new vscode.Diagnostic(range, message, severityToDiagnosticSeverity(finding.severity));
  diagnostic.code = finding.code;
  diagnostic.source = "hassle";
  return diagnostic;
}

/** Groups findings by their (workspace-root-relative) `file` and returns a map
 * from absolute file path to its diagnostics -- ready to hand one-by-one to a
 * `vscode.DiagnosticCollection.set(uri, diagnostics)` call. */
export function groupDiagnosticsByFile(
  findings: JsonFinding[],
  workspaceRoot: string
): Map<string, vscode.Diagnostic[]> {
  const path = require("path") as typeof import("path");
  const byFile = new Map<string, vscode.Diagnostic[]>();
  for (const finding of findings) {
    if (finding.file === null) {
      continue;
    }
    const absolute = path.isAbsolute(finding.file) ? finding.file : path.join(workspaceRoot, finding.file);
    const diagnostic = findingToDiagnostic(finding);
    const existing = byFile.get(absolute);
    if (existing) {
      existing.push(diagnostic);
    } else {
      byFile.set(absolute, [diagnostic]);
    }
  }
  return byFile;
}
