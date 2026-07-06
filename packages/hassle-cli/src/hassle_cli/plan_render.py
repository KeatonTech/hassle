"""Renders a `hassle.sync.Plan` (DESIGN §8.2: "renders the table with colors +
DSL-level diffs").

- `UPDATE` entries that are modernization-only (MILESTONES M7 test 4b) are
  labeled "modernization (one-time)" instead of a plain "update", so users
  aren't alarmed by a diff they didn't cause.
- `CONFLICT` entries get the 3-way DSL diff (`hassle_cli.diffing.dsl_diff`)
  plus the `--accept-local`/`--accept-remote` hint (DESIGN §8.2).
"""

from __future__ import annotations

from rich.console import Console

from hassle.sync import Plan, PlanAction
from hassle_cli.diffing import dsl_diff, is_modernization_only_diff

_ACTION_STYLES: dict[PlanAction, str] = {
    PlanAction.NOOP: "dim",
    PlanAction.UPDATE: "yellow",
    PlanAction.DELETE: "red",
    PlanAction.REFRESH: "cyan",
    PlanAction.CONFLICT: "bold red",
    PlanAction.DROP: "red",
    PlanAction.CREATE: "green",
    PlanAction.ADOPT: "green",
}


def _label_for(entry: object, action: PlanAction, modernization: bool) -> str:
    if action is PlanAction.UPDATE and modernization:
        return "modernization (one-time)"
    return action.value


def render_plan(console: Console, plan: Plan, *, show_noop: bool = False) -> None:
    any_shown = False
    for entry in plan.entries:
        if entry.action is PlanAction.NOOP and not show_noop:
            continue
        any_shown = True
        modernization = entry.action is PlanAction.UPDATE and is_modernization_only_diff(
            entry.object_key, entry.kind, entry.local, entry.remote
        )
        label = _label_for(entry, entry.action, modernization)
        style = _ACTION_STYLES.get(entry.action, "")
        console.print(f"[{style}]{label:>24}[/{style}]  {entry.object_key}")

        if entry.action is PlanAction.CONFLICT:
            conflict = entry.conflict
            local = conflict.local if conflict else entry.local
            remote = conflict.remote if conflict else entry.remote
            diff_text = dsl_diff(entry.object_key, entry.kind, local, remote)
            if diff_text:
                # markup=False (bug fix, regression-tested): `diff_text` is
                # arbitrary decompiled DSL source, not a Rich markup string --
                # a literal `[...]` in it (a list literal, e.g. `triggers=[...]`
                # or `target={"entity_id": [...]}`) was being parsed as a Rich
                # style tag and silently stripped, corrupting the printed diff.
                # soft_wrap=True: a unified diff's `-`/`+`-prefixed lines are
                # meaningful as literal lines (like `git diff`'s own output,
                # never word-wrapped) -- Rich's default wrapping at the
                # console width would otherwise split a long decompiled line
                # (e.g. a multi-kwarg `@automation(...)`) across several
                # visual lines with no `-`/`+` prefix on the continuation,
                # making the diff ambiguous to read.
                console.print(diff_text, style="", markup=False, soft_wrap=True)
            else:
                console.print("  (local)")
                console.print(f"  {local}")
                console.print("  (remote)")
                console.print(f"  {remote}")
            console.print(
                f"  resolve with: hassle push --accept-local {entry.object_key}"
                f"  |  --accept-remote {entry.object_key}"
            )
        elif modernization:
            console.print(
                "  (schema-only: Hassle compiles the modern form; HA stores whatever "
                "it's given verbatim, so this diff appears once and never again)"
            )

    if not any_shown:
        console.print("[dim]no changes[/dim]")


def plan_summary(plan: Plan) -> dict[str, int]:
    summary: dict[str, int] = {}
    for entry in plan.entries:
        if entry.action is PlanAction.NOOP:
            continue
        summary[entry.action.value] = summary.get(entry.action.value, 0) + 1
    return summary
