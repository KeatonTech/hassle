"""The agent-acceptance harness (MILESTONES M9 test 3, DESIGN §12: "a
scripted harness gives a fresh model session the pulled sample bundle +
AGENTS.md only, and 10 representative tasks ... >= 8/10 must produce changes
that pass `hassle validate && hassle test` without human help").

**This module builds the harness; it does not run any model session.**
Spawning fresh model sessions is the orchestrator's job (a capability this
module deliberately does not have and must not grow) -- everything here is
pure/offline: emitting the 10 task prompts for a given bundle, and
mechanically scoring the *result* of a session against that bundle by
running `hassle validate` and `hassle test` (as real subprocesses, exactly
what a human/agent would run) and reporting pass/fail.

## How the orchestrator runs this (one session per task)

For each of the 10 tasks `emit_tasks(bundle_dir)` returns:

1. Start a **fresh** model session (no memory of any other task in this
   run) with exactly two inputs: a clean copy of `bundle_dir` (freshly
   `hassle pull`ed, so it has an `AGENTS.md`/`docs/` of its own) and the
   task's `prompt` text. No other context, no hints beyond what `AGENTS.md`
   and `docs/` already say -- that is the whole point of the acceptance
   gate (DESIGN §12).
2. Let the session edit the bundle copy freely (it has real file access to
   that one directory) until it declares itself done, or a timeout elapses.
3. Call `score_task(bundle_copy)` (this module) on the resulting bundle
   directory. This is the **mechanical** half of the rubric: did the
   session leave the bundle in a state where `hassle validate` and
   `hassle test` both succeed? A session that produces syntactically valid,
   green-testing nonsense that doesn't actually satisfy the task's intent
   will still mechanically "pass" here -- the milestone's `>= 8/10` bar
   also requires a human (or a second, independent model pass) to spot-
   check that the diff actually does what the task asked; `score_task`
   narrows that review to "does this candidate even meet the floor", not a
   full grade.
4. Record `TaskResult` for the task; repeat for the remaining 9 (each from
   its own fresh copy of the ORIGINAL bundle_dir -- tasks must never see
   each other's edits).
5. Tally: `>= 8/10` mechanically-passing (`score_task(...).passed`) *and*
   human-approved-as-actually-correct is the DESIGN §12 acceptance bar.
   Keep the harness (this module + its task list) as a permanent regression
   suite -- re-run it whenever `AGENTS.md`/`docs/DSL.md`/`docs/COOKBOOK.md`
   generation changes, since the whole premise is "iterate docs until this
   goes green".

`hassle-dev acceptance-tasks --bundle DIR [--json]` is the CLI entry point
an orchestrator script shells out to for step 1's prompt text (see
`hassle_dev.cli`).
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AcceptanceTask:
    """One representative task: a stable id, a category (machine-readable,
    matches the milestone's example list), and the exact prompt text a
    fresh model session receives verbatim."""

    task_id: str
    category: str
    prompt: str


@dataclass(frozen=True)
class TaskResult:
    """The mechanical half of scoring one task's outcome (see module
    docstring step 3): whether `hassle validate`/`hassle test` succeeded
    against the bundle after a session's edits."""

    validate_passed: bool
    test_passed: bool
    validate_output: str
    test_output: str

    @property
    def passed(self) -> bool:
        return self.validate_passed and self.test_passed


def _bundle_display_name(bundle_dir: Path) -> str:
    return bundle_dir.name


def emit_tasks(bundle_dir: Path) -> list[AcceptanceTask]:
    """Build the 10 representative task prompts for ``bundle_dir``
    (MILESTONES M9 test 3's example list, made concrete against this
    specific bundle's own files/entities so a session has something real to
    act on -- not a generic placeholder)."""
    name = _bundle_display_name(bundle_dir)
    return [
        AcceptanceTask(
            task_id="entity_swap",
            category="entity_swap",
            prompt=(
                f"In this {name} bundle, the hallway motion automation currently controls "
                "`light.hallway`. Change it to control `light.living_room` instead (same "
                "brightness/behavior otherwise). Run `hassle validate` and `hassle test` "
                "and make sure both pass before you're done."
            ),
        ),
        AcceptanceTask(
            task_id="add_helper_and_use_it",
            category="add_helper_and_use_it",
            prompt=(
                "Add a new `input_boolean` helper called `night_mode` (give it a sensible "
                "name/icon), and change the hallway motion automation so it only turns the "
                "light on when `night_mode` is on. Run `hassle validate` and `hassle test` "
                "and make sure both pass before you're done."
            ),
        ),
        AcceptanceTask(
            task_id="add_condition",
            category="add_condition",
            prompt=(
                "The hallway motion automation currently has no guest-mode check. Add a "
                "condition so it only turns the light on when `input_boolean.guest_mode` is "
                "off. Write or update a simulator test proving the light does NOT turn on "
                "when guest mode is on. Run `hassle validate` and `hassle test` and make "
                "sure both pass before you're done."
            ),
        ),
        AcceptanceTask(
            task_id="write_sim_test",
            category="write_sim_test",
            prompt=(
                "Write a new simulator test (in `tests/`) for the existing hallway motion "
                "automation that proves: motion during the day (well before sunset) does "
                "NOT turn the light on. Use the `hassle.testing.Simulator`/`sim` fixture "
                "conventions already used elsewhere in this bundle. Run `hassle validate` "
                "and `hassle test` and make sure both pass before you're done."
            ),
        ),
        AcceptanceTask(
            task_id="diagnose_failing_test",
            category="diagnose_failing_test",
            prompt=(
                "One of the tests in `tests/` is failing. Find out why, and fix the "
                "underlying automation logic (not the test) so the test passes for the "
                "right reason. Run `hassle validate` and `hassle test` and make sure both "
                "pass before you're done."
            ),
        ),
        AcceptanceTask(
            task_id="add_automation_purpose_trigger",
            category="add_automation_purpose_trigger",
            prompt=(
                'Add a new automation using a purpose-specific trigger (`on("motion.'
                'detected", target=...)`, DESIGN §5.4) that turns on a light when motion '
                "is detected in a target of your choice, and write a simulator test for it "
                "(purpose triggers are exercised via `sim.fire(...)`, not a state change -- "
                "see AGENTS.md/docs/DSL.md). Run `hassle validate` and `hassle test` and "
                "make sure both pass before you're done."
            ),
        ),
        AcceptanceTask(
            task_id="refactor_into_macro",
            category="refactor_into_macro",
            prompt=(
                "If this bundle has more than one automation that sends the same kind of "
                "notification, extract that into a `@macro` under `lib/` and use it from "
                "both call sites (see `lib/README.md`). If there's only one automation, "
                "add a second one first, then do the extraction. Run `hassle validate` and "
                "`hassle test` and make sure both pass before you're done."
            ),
        ),
        AcceptanceTask(
            task_id="ignore_glob_addition",
            category="ignore_glob_addition",
            prompt=(
                "Add an `ignore` glob to this bundle's `hassle.toml` so Hassle never "
                "manages any `input_boolean` whose id starts with `material_you_` (a "
                "pattern from HA's own generated helpers). Confirm `hassle validate` still "
                "passes afterward."
            ),
        ),
        AcceptanceTask(
            task_id="explain_plan_diff",
            category="explain_plan_diff",
            prompt=(
                "Explain, in a short comment or note, what `hassle plan` would show if the "
                "hallway automation's `brightness_pct` were changed locally from 60 to 80 "
                "with no corresponding change in HA -- name which row of the plan-semantics "
                "table (DESIGN §8.2 / docs/DSL.md) applies and why. No code change is "
                "required for this task; just the written explanation."
            ),
        ),
        AcceptanceTask(
            task_id="fix_validation_finding",
            category="fix_validation_finding",
            prompt=(
                "Introduce a typo in an entity id somewhere in this bundle (e.g. "
                "`light.hallwya` instead of `light.hallway`), run `hassle validate`, read "
                "the Finding it produces, and then fix the typo so validation is clean "
                "again. Show the Finding text you saw before fixing it."
            ),
        ),
    ]


def _run(cmd: list[str], cwd: Path) -> tuple[bool, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return proc.returncode == 0, proc.stdout + proc.stderr


def score_task(bundle_dir: Path) -> TaskResult:
    """Run the mechanical half of the rubric against ``bundle_dir`` after a
    session's edits: `hassle validate` and `hassle test`, as real
    subprocesses (matching exactly what AGENTS.md tells the session to run
    itself). Never inspects the diff's semantic correctness -- see the
    module docstring's step 3 caveat."""
    validate_passed, validate_output = _run(
        [sys.executable, "-m", "hassle_cli", "validate"], bundle_dir
    )
    test_passed, test_output = _run([sys.executable, "-m", "hassle_cli", "test"], bundle_dir)
    return TaskResult(
        validate_passed=validate_passed,
        test_passed=test_passed,
        validate_output=validate_output,
        test_output=test_output,
    )
