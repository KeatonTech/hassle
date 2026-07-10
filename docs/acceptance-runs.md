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

## Run 2 — 2026-07-09 — **10/10 PASS**

- Toolchain: main @ `184f564` (post M13–M20: decorator-form template helpers,
  category-first layout, string-state expressions, typed service namespaces,
  marker-bound shared-script params, entity-first conditions; docs/DSL.md and
  AGENTS.md regenerated many times since run 1 — this run validates the docs
  kept pace).
- Sample bundle: regenerated in the NEW canonical forms (root-level `misc.py`
  layout, `from hassle.services import ...` namespace calls, typed shared-script
  signatures) — sessions faced materially different code than run 1.
- Mechanical score: 10/10 validate+test green (bar ≥ 8).
- Intent spot-check: 10/10. Consistent with run 1's quality bar: `id=` never
  touched, seeded xfail respected via its docstring, entities verified against
  the registry snapshot, edit → validate → test loop followed unprompted, and
  one session explicitly avoided piping gate commands (the AGENTS.md exit-code
  guidance landing). `explain_plan_diff` correctly reasoned the three-way
  manifest-base semantics and even flagged that it could not quote DESIGN §8.2's
  exact row label without leaving its bundle fence — honest boundary-keeping.
- Zero documentation-gap failures; no docs iteration needed this run.
