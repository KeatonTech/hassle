# Agent-acceptance run log (MILESTONES M9 test 3)

The M9 "real gate": fresh model sessions receive a generated sample bundle
(`hassle-dev acceptance-bundle`) plus one task prompt from
`hassle-dev acceptance-tasks`, with AGENTS.md and the bundle's `docs/` as their
only guidance. Each session's result is scored mechanically
(`hassle_dev.acceptance.score_task`: `hassle validate` + `hassle test` both
green) and spot-checked for intent. Bar: ≥ 8/10.

Re-run this whenever AGENTS.md / docs generation changes — the premise is
"iterate docs until green", and this log is the regression record.

## Run 1 — 2026-07-06 — **10/10 PASS**

- Toolchain: main @ `436a4fe` (post M10 + M11 + acceptance-bundle generator).
- Sessions: 10 fresh generic agents (one per task), each on an isolated copy of
  the generated sample bundle, orchestrated per the harness module docstring.
- Mechanical score: 10/10 validate+test green (bar ≥ 8).
- Intent spot-check: 10/10 — every diff did what the task asked. Highlights:
  - `diagnose_failing_test`: root-caused the seeded inverted holiday-mode
    condition, fixed the automation (not the test), removed the strict-xfail
    marker per its docstring, and added a suppression-direction test.
  - `write_sim_test`: asserted past the automation's 5-minute delay window to
    prove the whole action body was skipped, not just the first call.
  - `explain_plan_diff`: named the correct §8.2 row (local changed / remote
    unchanged → update) with correct manifest-base three-way reasoning and
    accurate references to I1/I2/I6.
  - `fix_validation_finding`: exercised the M3 `unknown-entity` Finding
    end-to-end, including the "Did you mean `light.hallway`?" suggestion.
- Common session behaviors worth keeping (signals the docs are doing their
  job): every session left `id=` untouched, treated the seeded xfail as
  out-of-scope by reading its docstring, verified entities against
  `.hassle/registry.json` before using them, and followed the
  edit → validate → test loop from AGENTS.md without prompting.
- Zero documentation-gap failures; no docs iteration needed this run.
