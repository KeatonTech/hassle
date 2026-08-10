"""CLI wiring for the blueprint kind (blueprints-design §3/§4/§5).

Everything core does only works if the CLI actually hands it the two things a
`Plan` cannot carry on its own — the substitute-compare verdict (§3, needs a
backend round trip) and the blueprint→instances map (§4, needs the compiled
bundle, since an unchanged instance is a `noop` row with no body) — and if
placement and rendering know the kind exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rich.console import Console

from hassle.blueprints import blueprint_body, blueprint_metadata, blueprint_remote_body
from hassle.ir import BLUEPRINT_KIND
from hassle.sync.models import Conflict, ConflictKind, Plan, PlanAction, PlanEntry
from hassle_cli import bundle_ops
from hassle_cli.plan_render import plan_summary, render_plan

SOURCE = """\
blueprint:
  name: Room Switch Controls
  domain: automation
  input:
    switch_entity:
mode: restart
triggers:
  - trigger: state
    entity_id: !input switch_entity
actions: []
"""

PATH = "local/room-switch-controls.yaml"
KEY = f"blueprint:automation/{PATH}"


# --- placement -------------------------------------------------------------


def test_a_blueprints_source_path_is_its_own_yaml_file() -> None:
    """Not `misc.py`: a blueprint's source of truth IS the YAML file at
    `blueprints/<domain>/<path>`, and pull must never be pointed at a .py."""
    assert bundle_ops.default_source_path(KEY) == f"blueprints/automation/{PATH}"


def test_placement_keeps_the_path_verbatim() -> None:
    assert bundle_ops.default_source_path("blueprint:script/a/b/c.yml") == (
        "blueprints/script/a/b/c.yml"
    )


def test_a_registry_snapshot_never_redirects_a_blueprint() -> None:
    """Blueprints have no HA category scope; a category file would be the
    wrong place for a YAML document regardless."""
    from hassle.registry.snapshot import RegistrySnapshot

    assert bundle_ops.default_source_path(KEY, registry=RegistrySnapshot()) == (
        f"blueprints/automation/{PATH}"
    )


# --- build_source_paths over a real bundle ---------------------------------


def _bundle(tmp_path: Path) -> Path:
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "misc.py").write_text(
        "from hassle import blueprint_automation\n"
        "blueprint_automation(\n"
        '    id="office_switch",\n'
        f'    use_blueprint="{PATH}",\n'
        '    inputs={"switch_entity": "event.office"},\n'
        ")\n",
        encoding="utf-8",
    )
    target = root / "blueprints" / "automation" / PATH
    target.parent.mkdir(parents=True)
    target.write_text(SOURCE, encoding="utf-8")
    return root


def test_build_source_paths_points_a_blueprint_at_its_yaml(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    _objects, result = bundle_ops.compile_local_objects(root)
    paths = bundle_ops.build_source_paths(root, result, [KEY, "automation:office_switch"])
    assert paths[KEY] == f"blueprints/automation/{PATH}"


def test_compile_local_objects_includes_the_blueprint(tmp_path: Path) -> None:
    objects, _result = bundle_ops.compile_local_objects(_bundle(tmp_path))
    assert objects[KEY][0] == BLUEPRINT_KIND
    assert objects[KEY][1]["source"] == SOURCE


# --- the instance map the CLI must build -----------------------------------


def test_blueprint_instances_are_derived_from_the_compiled_bundle(tmp_path: Path) -> None:
    objects, _result = bundle_ops.compile_local_objects(_bundle(tmp_path))
    assert bundle_ops.blueprint_instances_for(objects) == {KEY: ["automation:office_switch"]}


def test_the_instance_map_is_empty_without_blueprints(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()
    (root / "misc.py").write_text(
        "from hassle import automation\n\n\n@automation(id='a')\ndef a() -> None:\n    pass\n",
        encoding="utf-8",
    )
    objects, _result = bundle_ops.compile_local_objects(root)
    assert bundle_ops.blueprint_instances_for(objects) == {}


# --- rendering -------------------------------------------------------------


def _render(entry: PlanEntry) -> str:
    console = Console(record=True, width=200, force_terminal=False)
    render_plan(console, Plan(entries=[entry]))
    return console.export_text()


def test_an_unmanageable_adopt_renders_as_a_warning() -> None:
    """§3: a warning row only. Printing a bare `adopt` would read as "Hassle
    is about to adopt this", which is exactly what it cannot do."""
    entry = PlanEntry(
        object_key=KEY,
        kind=BLUEPRINT_KIND,
        action=PlanAction.ADOPT,
        remote=blueprint_remote_body("automation", PATH, blueprint_metadata(SOURCE)),
        warning=True,
        message="Home Assistant has a blueprint at ... place the file by hand.",
    )
    output = _render(entry)
    assert "warning" in output
    assert "place the file by hand" in output


def test_a_blueprint_conflict_prints_its_message_not_a_dsl_diff() -> None:
    """There is no DSL for a blueprint (it is authored YAML) and no remote
    source to diff against -- `dsl_diff` would raise. The message IS the
    explanation for this kind."""
    remote = blueprint_remote_body("automation", PATH, blueprint_metadata(SOURCE))
    entry = PlanEntry(
        object_key=KEY,
        kind=BLUEPRINT_KIND,
        action=PlanAction.CONFLICT,
        local=blueprint_body(domain="automation", path=PATH, source=SOURCE),
        remote=remote,
        conflict=Conflict(
            object_key=KEY,
            kind=ConflictKind.BOTH_EDITED,
            base=None,
            local=None,
            remote=remote,
        ),
        message="The blueprint was edited in place in Home Assistant.",
    )
    output = _render(entry)
    assert "edited in place" in output
    assert "conflict" in output


@pytest.mark.parametrize("action", [PlanAction.CREATE, PlanAction.UPDATE, PlanAction.DELETE])
def test_ordinary_blueprint_rows_render_without_decompiling(action: PlanAction) -> None:
    """Every blueprint row must survive rendering: the decompiler has no
    handler for the kind, so a row that reached it would crash `hassle plan`."""
    entry = PlanEntry(
        object_key=KEY,
        kind=BLUEPRINT_KIND,
        action=action,
        local=blueprint_body(domain="automation", path=PATH, source=SOURCE),
        remote=blueprint_remote_body("automation", PATH, blueprint_metadata(SOURCE)),
    )
    assert KEY in _render(entry)


def test_a_warning_row_is_not_counted_as_a_change() -> None:
    """`plan_summary` drives "N to apply" messaging and the confirm prompt; a
    row nothing will ever act on must not inflate it."""
    entry = PlanEntry(
        object_key=KEY,
        kind=BLUEPRINT_KIND,
        action=PlanAction.ADOPT,
        warning=True,
        message="...",
    )
    assert plan_summary(Plan(entries=[entry])) == {}
