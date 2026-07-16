"""MILESTONES M7 test 4: `test_conflict_ux_snapshot` -- 3-way DSL diff output golden."""

from __future__ import annotations

from pathlib import Path

from hassle_dev.snapshots import check_snapshot

SNAP_DIR = Path(__file__).resolve().parent / "snapshots"


def _check_snapshot(name: str, actual: str) -> None:
    check_snapshot(SNAP_DIR, name, actual)


def test_dsl_diff_list_literal_is_not_mangled_by_rich_markup() -> None:
    """Regression test (bug found while implementing `ux/triggers-in-decorator`):
    `render_plan`'s conflict diff printed `dsl_diff`'s output through
    `console.print(diff_text, style="")` with Rich markup parsing left on.
    `diff_text` is arbitrary decompiled DSL source, not a markup string -- a
    literal `[...]` list in it (e.g. `triggers=[...]`, or a list-valued
    `target={"entity_id": [...]}`) was silently stripped by Rich's `[tag]`
    markup parser, corrupting the printed diff (`triggers=[state(...)])`
    rendered as `triggers=)`). Pinned directly against `render_plan`, which is
    the actual code path with the fix (`markup=False`), rather than only via
    the full CLI conflict-flow snapshot above (belt-and-suspenders: this one
    fails immediately at the rendering layer if the fix regresses, independent
    of any future change to the surrounding conflict scenario/snapshot)."""
    import io
    from dataclasses import dataclass
    from unittest.mock import patch

    from rich.console import Console

    from hassle.sync import PlanAction
    from hassle_cli import plan_render

    @dataclass
    class _FakeConflict:
        local: dict[str, object]
        remote: dict[str, object]

    @dataclass
    class _FakeEntry:
        object_key: str
        kind: str
        action: PlanAction
        local: dict[str, object] | None
        remote: dict[str, object] | None
        conflict: _FakeConflict | None

    @dataclass
    class _FakePlan:
        entries: list[_FakeEntry]

    local = {
        "id": "a",
        "alias": "A",
        "triggers": [{"trigger": "state", "entity_id": "binary_sensor.hall_motion", "to": "on"}],
        "conditions": [],
        "actions": [],
    }
    remote = {**local, "alias": "A (remote edit)"}
    entry = _FakeEntry(
        object_key="automation:a",
        kind="automation",
        action=PlanAction.CONFLICT,
        local=local,
        remote=remote,
        conflict=_FakeConflict(local=local, remote=remote),
    )

    buf = io.StringIO()
    console = Console(file=buf, no_color=True, force_terminal=False, width=100)
    with patch.object(plan_render, "is_modernization_only_diff", return_value=False):
        plan_render.render_plan(console, _FakePlan(entries=[entry]))
    output = buf.getvalue()

    # The list literal must survive intact -- not stripped to `triggers=)`.
    assert "triggers=[state(e.binary_sensor.hall_motion).to(" in output
    assert "triggers=)" not in output


def test_plan_renders_conflict_with_3way_dsl_diff(
    git_repo: Path, cli, fake_backend, tmp_path: Path, toml_writer, output_normalizer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0

    # Edit remotely (simulating a UI edit) ...
    remote = backend.list_remote("automation")["hall_light_on_motion"]
    remote_edited = {**remote, "alias": "Hallway light on motion (UI edit)"}
    backend.update("automation", "hall_light_on_motion", remote_edited)

    # ... and locally, to a *different* value -> both_edited conflict.
    (git_repo / "hallway.py").write_text(
        """
from hassle import automation, service, state, when

@automation(id="hall_light_on_motion", alias="Hallway light on motion (local edit)")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
        encoding="utf-8",
    )

    result = cli(["plan"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "conflict" in result.output.lower()
    assert "local" in result.output.lower()
    assert "remote" in result.output.lower()
    _check_snapshot("conflict_3way_diff", output_normalizer(result.output, tmp_path))


def test_push_aborts_on_unresolved_conflict(git_repo: Path, cli, fake_backend, toml_writer) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0

    remote = backend.list_remote("automation")["hall_light_on_motion"]
    backend.update("automation", "hall_light_on_motion", {**remote, "alias": "UI edit"})
    (git_repo / "hallway.py").write_text(
        """
from hassle import automation, service, state, when

@automation(id="hall_light_on_motion", alias="Local edit")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
        encoding="utf-8",
    )

    result = cli(["push", "--yes"], cwd=git_repo)
    assert result.exit_code != 0
    assert "conflict" in result.output.lower()
    assert "--accept-local" in result.output
    assert "--accept-remote" in result.output


def test_push_accept_local_resolves_conflict(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0

    remote = backend.list_remote("automation")["hall_light_on_motion"]
    backend.update("automation", "hall_light_on_motion", {**remote, "alias": "UI edit"})
    (git_repo / "hallway.py").write_text(
        """
from hassle import automation, service, state, when

@automation(id="hall_light_on_motion", alias="Local edit")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
        encoding="utf-8",
    )

    result = cli(
        ["push", "--yes", "--accept-local", "automation:hall_light_on_motion"], cwd=git_repo
    )
    assert result.exit_code == 0, result.output
    assert backend.list_remote("automation")["hall_light_on_motion"]["alias"] == "Local edit"


def test_push_accept_remote_records_base_so_replan_is_refresh(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    """The non-interactive `--accept-remote` flag path records the same base
    the interactive [r] prompt does (field report, BrandtCamp 2026-07-14:
    an accept-remote that records nothing re-surfaces the IDENTICAL conflict
    on every subsequent plan, training the owner to ignore prompts -- I6).
    Base advances to the LOCAL side: next plan reads `refresh`, and push
    leaves the kept remote untouched."""
    from hassle.sync.models import PlanAction
    from hassle_cli.cli import _build_plan

    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0

    remote = backend.list_remote("automation")["hall_light_on_motion"]
    backend.update("automation", "hall_light_on_motion", {**remote, "alias": "UI edit"})
    (git_repo / "hallway.py").write_text(
        """
from hassle import automation, service, state, when

@automation(id="hall_light_on_motion", alias="Local edit")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
        encoding="utf-8",
    )

    result = cli(
        ["push", "--yes", "--accept-remote", "automation:hall_light_on_motion"], cwd=git_repo
    )
    assert result.exit_code == 0, result.output
    # The kept remote was not clobbered by the push...
    assert backend.list_remote("automation")["hall_light_on_motion"]["alias"] == "UI edit"
    # ...and the next plan is a refresh (pull-side), never the same conflict again.
    plan = _build_plan(git_repo)
    actions = {e.object_key: e.action for e in plan.entries}
    assert actions.get("automation:hall_light_on_motion") is PlanAction.REFRESH, actions
    # A --yes push right now must not push the rejected local version over the
    # kept remote (I6: the accepted UI edit is never silently lost).
    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0
    assert backend.list_remote("automation")["hall_light_on_motion"]["alias"] == "UI edit"


def test_push_accept_remote_of_locally_deleted_object_replans_as_adopt(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    """accept-remote on a deleted-locally/edited-remotely conflict: the bundle
    no longer declares the object and the user chose to keep HA's version, so
    the manifest entry is dropped -- the next plan reads `adopt` (unmanaged
    until pulled back in), never the same conflict again."""
    from hassle.sync.models import PlanAction
    from hassle_cli.cli import _build_plan

    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0

    remote = backend.list_remote("automation")["hall_light_on_motion"]
    backend.update("automation", "hall_light_on_motion", {**remote, "alias": "UI edit"})
    (git_repo / "hallway.py").unlink()

    # deleted locally + edited remotely = conflict; unresolved push refuses.
    assert cli(["push", "--yes"], cwd=git_repo).exit_code != 0

    result = cli(
        ["push", "--yes", "--accept-remote", "automation:hall_light_on_motion"], cwd=git_repo
    )
    assert result.exit_code == 0, result.output
    assert backend.list_remote("automation")["hall_light_on_motion"]["alias"] == "UI edit"
    plan = _build_plan(git_repo)
    actions = {e.object_key: e.action for e in plan.entries}
    assert actions.get("automation:hall_light_on_motion") is PlanAction.ADOPT, actions
