"""Task #30 (`ux/capture-notify-recipe`): the cookbook actionable-notification
recipe's compiled IR shape, plus the round-trip honesty contract for BOTH new
constructs the recipe is built on:

- `capture_actions()`/`emit_actions(...)` (the public capture seam,
  `hassle.compiler.recording`) -- proven by `fixtures/dsl/capture_emit_actions/`.
- the cookbook `notify_mobile`/`action` recipe itself
  (`fixtures/cookbook/bundle/lib/notify_actions.py`) -- proven directly here.

Both are AUTHORING-ONLY sugar (like `@macro`, DESIGN §5.6): the compiled IR is
always a plain `wait_for_trigger`/`choose` (for the recipe) or whatever
container the caller built (for the capture seam) -- there is no dedicated IR
node for either, so the decompiler needs (and gets) ZERO changes. This test
proves that directly: `decompile_object` on the compiled automation produces
ordinary `wait_for`/`choose`/`service` source (no `notify_mobile`/`action`/
`capture_actions`/`emit_actions` names anywhere in it), and re-compiling that
decompiled source reproduces the identical IR (I3).

Sim-test findings (docs/ha-api-notes.md §36.2, STOP per this task's explicit
instruction): the simulator cannot yet resume a pending `wait_for_trigger` on
an event, nor does it populate the `wait.trigger` template variable a
satisfied wait's later conditions read -- so branch DISPATCH is untestable
against the current simulator. This file is the IR-shape-level test the STOP
instruction says may still land; `fixtures/cookbook/bundle/tests/
test_recipes.py::test_notify_with_actions_sends_actionable_notification_on_unlock`
covers the always-true part (the notification itself firing) via the real
simulator.
"""

from __future__ import annotations

from pathlib import Path

from hassle.compiler.bundle import compile_bundle
from hassle.decompiler.codegen import decompile_bundle, decompile_object
from hassle.ir import canonical_json

_COOKBOOK_BUNDLE = Path(__file__).resolve().parents[3] / "fixtures" / "cookbook" / "bundle"
_CAPTURE_DSL_BUNDLE = (
    Path(__file__).resolve().parents[3] / "fixtures" / "dsl" / "capture_emit_actions" / "bundle"
)


def _recompile_source(source: str, *, tmp_path: Path, module_name: str) -> dict[str, object]:
    """Write ``source`` as a standalone one-file bundle and compile it."""
    bundle_dir = tmp_path / module_name
    bundle_dir.mkdir()
    (bundle_dir / f"{module_name}.py").write_text(source, encoding="utf-8")
    result = compile_bundle(bundle_dir)
    return {key: obj.to_ha() for key, obj in result.objects.items()}


# ---------------------------------------------------------------------------
# The cookbook recipe: notify_mobile/action.
# ---------------------------------------------------------------------------


def test_notify_with_actions_compiles_to_wait_for_trigger_and_choose() -> None:
    result = compile_bundle(_COOKBOOK_BUNDLE)
    key = "automation:cookbook_notify_with_actions"
    obj = result.objects[key]
    actions = obj.actions  # type: ignore[attr-defined]

    assert actions[0]["action"] == "notify.mobile_app_keaton"
    assert actions[0]["data"]["actions"] == [
        {"action": "OPEN_BLINDS", "title": "Open Blinds", "icon": "mdi:blinds-open"},
        {"action": "CLOSE_BLINDS", "title": "Close Blinds"},
    ]

    assert "wait_for_trigger" in actions[1]
    assert actions[1]["wait_for_trigger"] == [
        {"trigger": "event", "event_type": "mobile_app_notification_action"}
    ]
    assert actions[1]["timeout"] == "00:05:00"

    assert "choose" in actions[2]
    branches = actions[2]["choose"]
    assert len(branches) == 2
    assert branches[0]["conditions"] == [
        {
            "condition": "template",
            "value_template": ("{{ wait.trigger['event']['data']['action'] == 'OPEN_BLINDS' }}"),
        }
    ]
    assert branches[0]["sequence"] == [
        {
            "action": "cover.open_cover",
            "target": {"entity_id": ["cover.bedroom_blinds", "cover.office_blinds"]},
        }
    ]
    assert branches[1]["conditions"] == [
        {
            "condition": "template",
            "value_template": ("{{ wait.trigger['event']['data']['action'] == 'CLOSE_BLINDS' }}"),
        }
    ]
    assert branches[1]["sequence"] == [
        {
            "action": "cover.close_cover",
            "target": {"entity_id": ["cover.bedroom_blinds", "cover.office_blinds"]},
        }
    ]


def test_notify_with_actions_decompiles_to_plain_wait_for_and_choose() -> None:
    """Round-trip honesty (I3): `notify_mobile`/`action` are authoring-only
    sugar, like `@macro` -- the decompiler reconstructs the compiled shape as
    ordinary `wait_for(...)`/`choose(...)`/`service(...)` calls, never a
    `notify_mobile`/`action` call (those names are `lib/`-local to the
    cookbook bundle; the decompiler has no knowledge of them and needs none)."""
    result = compile_bundle(_COOKBOOK_BUNDLE)
    key = "automation:cookbook_notify_with_actions"
    obj = result.objects[key]
    source = decompile_object(key, obj)

    for sugar_name in ("notify_mobile", "action(", "capture_actions", "emit_actions"):
        assert sugar_name not in source, f"{sugar_name!r} leaked into decompiled source:\n{source}"

    assert "wait_for(" in source
    assert "choose(" in source
    assert "service(" in source


def test_notify_with_actions_compile_decompile_recompile_reproduces_ir(
    tmp_path: Path,
) -> None:
    """I3: `compile(decompile(x)) == x` for the recipe's compiled shape."""
    first = compile_bundle(_COOKBOOK_BUNDLE)
    key = "automation:cookbook_notify_with_actions"
    obj = first.objects[key]
    original_ha = obj.to_ha()

    # `decompile_bundle` (not `decompile_object`) here: it emits the needed
    # `from hassle import ...` imports too, so the decompiled source is a
    # real, standalone, importable module (`decompile_object` alone returns
    # just the `def`/decorator body, by design -- the caller controls
    # import assembly, e.g. for the splice codemod).
    source = decompile_bundle({key: obj})
    recompiled = _recompile_source(source, tmp_path=tmp_path, module_name="notify_recompiled")

    assert len(recompiled) == 1
    (recompiled_ha,) = recompiled.values()
    assert canonical_json(recompiled_ha) == canonical_json(original_ha)


# ---------------------------------------------------------------------------
# The public capture seam itself, via its own golden fixture.
# ---------------------------------------------------------------------------


def test_capture_emit_actions_decompiles_with_no_capture_sugar_leaking() -> None:
    result = compile_bundle(_CAPTURE_DSL_BUNDLE)
    key = "automation:doors_porch_light"
    obj = result.objects[key]
    source = decompile_object(key, obj)

    for sugar_name in ("capture_actions", "emit_actions", "porch_off_on_either_door"):
        assert sugar_name not in source, f"{sugar_name!r} leaked into decompiled source:\n{source}"
    assert "choose(" in source


def test_capture_emit_actions_compile_decompile_recompile_reproduces_ir(
    tmp_path: Path,
) -> None:
    first = compile_bundle(_CAPTURE_DSL_BUNDLE)
    key = "automation:doors_porch_light"
    obj = first.objects[key]
    original_ha = obj.to_ha()

    source = decompile_bundle({key: obj})
    recompiled = _recompile_source(source, tmp_path=tmp_path, module_name="capture_recompiled")

    assert len(recompiled) == 1
    (recompiled_ha,) = recompiled.values()
    assert canonical_json(recompiled_ha) == canonical_json(original_ha)
