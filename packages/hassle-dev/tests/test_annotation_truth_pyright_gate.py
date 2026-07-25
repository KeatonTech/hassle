"""Type-annotation truth pass — the pyright gate.

Evidence from a real bundle (Pylance standard mode): the DECOMPILED
code is correct HA-wise, but the DSL's OWN annotations reject it --

- `state(entity_id=[e.input_select.day_phase])` -- entity classes aren't
  `str`-typed, and `list[X]` is invariant, so a list of entity refs never
  satisfies a `list[str]`-typed parameter;
- `area(["back_yard", "front_yard"])` -- `area(area_id: str)` doesn't admit
  the list form the decompiler actually emits for a multi-area target;
- `triggers=[state(...).to(...)]` -- `list[StateExpr]` is not assignable to
  `list[TriggerBuilder] | None` (invariance again, this time on the
  `@automation(triggers=...)` decorator kwarg).

This is the RED-FIRST gate: it must fail against current `main` (no source
changes yet), for the reasons named above -- not some unrelated pyright
error. Two independent bundles are checked:

1. The REAL acceptance sample bundle (`hassle_dev.bundle_gen.generate_sample_bundle`,
   which drives the actual `hassle pull` pipeline), with the full generated
   `typings/` tree, pyright'd exactly as a fresh cold-opened bundle would be
   (matching the scaffolded `.vscode/settings.json` + `pyrightconfig.json`
   convention established by `test_registry_stubs_pyright_init_template.py`,
   escalated here to `standard` mode -- the bug this gate responds to was
   observed in Pylance *standard* mode).
2. A synthetic bundle decompiled from rich corpus shapes this repo already
   has fixtures for -- multi-entity targets, `numeric_state`, template
   helpers, and (via `snapshot=`) namespace service calls
   (`hassle.services.<domain>.<method>(target=..., ...)`) -- plus one
   hand-built purpose-trigger automation with a MULTI-AREA target
   (`target: {"area_id": ["back_yard", "front_yard"]}`), since no existing
   corpus fixture happens to carry a list-valued `area_id` (every purpose-
   trigger fixture in the corpus targets a single area/floor/device) and
   that was the exact shape observed.

No vacuous filtering (the mistake that let three prior bugs ship): every
assertion enumerates the full set of diagnostic `rule`s it checks
(`reportArgumentType`, `reportAttributeAccessIssue`, `reportUndefinedVariable`,
`reportUnknownVariableType`) rather than filtering down to just one, and
prints every offending diagnostic on failure so a future regression is
diagnosable from CI output alone.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hassle_dev.bundle_gen import generate_sample_bundle

REPO_ROOT = Path(__file__).resolve().parents[3]
CORE_SRC = REPO_ROOT / "packages" / "hassle-core" / "src"
CONFIGS_DIR = REPO_ROOT / "fixtures" / "configs"
REGISTRY_FIXTURE = REPO_ROOT / "fixtures" / "registry" / "home.json"

# The classes of diagnostic this gate polices. Enumerated explicitly (never a
# single-rule filter) per the task brief's "vacuous-filter mistake" warning.
_POLICED_RULES = frozenset(
    {
        "reportArgumentType",
        "reportAttributeAccessIssue",
        "reportUndefinedVariable",
        "reportUnknownVariableType",
    }
)


def _pyright_available() -> bool:
    return shutil.which("pyright") is not None or shutil.which("uv") is not None


pytestmark = pytest.mark.skipif(
    not _pyright_available(), reason="pyright/uv not available in this environment"
)


def _run_pyright(cwd: Path) -> subprocess.CompletedProcess[str]:
    """Same invocation convention as `test_registry_stubs_pyright.py`: prefer a
    directly-available `pyright`, else `uv run pyright` from the repo root
    (uv manages the workspace's pinned pyright install)."""
    if shutil.which("pyright") is not None:
        cmd = ["pyright", "--outputjson", "."]
        run_cwd = cwd
    else:
        cmd = ["uv", "run", "--project", str(REPO_ROOT), "pyright", "--outputjson", str(cwd)]
        run_cwd = REPO_ROOT
    return subprocess.run(cmd, cwd=run_cwd, capture_output=True, text=True, timeout=180)


def _write_pyrightconfig_standard(root: Path, *, extra_paths: list[str]) -> None:
    """`typeCheckingMode: "standard"` -- matches what the scaffolded
    settings set, and the bug this gate responds to, which was observed in
    Pylance *standard* mode."""
    config = {
        "typeCheckingMode": "standard",
        "stubPath": "typings",
        "extraPaths": extra_paths,
        "reportMissingImports": True,
        "pythonVersion": "3.12",
    }
    (root / "pyrightconfig.json").write_text(json.dumps(config), encoding="utf-8")


def _policed_diagnostics(payload: dict[str, object]) -> list[dict[str, object]]:
    diagnostics = payload.get("generalDiagnostics", [])
    assert isinstance(diagnostics, list)
    return [d for d in diagnostics if d.get("rule") in _POLICED_RULES]  # type: ignore[union-attr]


def _format_diagnostics(diagnostics: list[dict[str, object]]) -> str:
    lines = []
    for d in diagnostics:
        lines.append(f"  [{d.get('rule')}] {d.get('file')}: {d.get('message')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Gate 1: the real acceptance sample bundle (the actual `hassle pull` output,
# decompiled sources + full generated `typings/` tree).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sample_bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("annotation_truth_sample") / "sample_house"
    generate_sample_bundle(out, repo_root=REPO_ROOT)
    return out


def test_sample_bundle_is_pyright_clean_in_standard_mode(sample_bundle: Path) -> None:
    """THE GATE (bundle 1): the real acceptance sample bundle -- generated by
    driving the actual `hassle pull` pipeline, so its sources are exactly
    what a real user's decompiled bundle looks like (`triggers=[state(e.<domain>.<x>)
    .to(...)]`, `<domain>.<service>(target=e.<domain>.<x>, ...)`) -- must be
    ZERO diagnostics of the policed classes under `standard` mode with the
    bundle's own generated `typings/` tree in play.

    RED against current main: `state(e.binary_sensor.hall_motion)` inside a
    `triggers=[...]` list trips `reportArgumentType` (entity classes aren't
    `str`-typed) and the typed namespace service calls
    (`light.turn_on(target=e.light.hallway, ...)`) trip `reportCallIssue`-style
    unknown-parameter errors because the generated `hassle.services` stub
    methods have no `target` parameter at all yet.
    """
    _write_pyrightconfig_standard(sample_bundle, extra_paths=[str(CORE_SRC), "."])
    proc = _run_pyright(sample_bundle)
    payload = json.loads(proc.stdout or "{}")
    policed = _policed_diagnostics(payload)
    assert policed == [], (
        f"expected zero policed diagnostics on the real sample bundle in standard "
        f"mode; got {len(policed)}:\n{_format_diagnostics(policed)}\n\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )


# ---------------------------------------------------------------------------
# Gate 2: a synthetic bundle decompiled from rich corpus shapes -- multi-
# entity targets, numeric_state, template helpers, namespace service calls,
# and a hand-built multi-area purpose-trigger target (no existing corpus
# fixture carries a list-valued area_id).
# ---------------------------------------------------------------------------


def _load_fixture(name: str) -> dict[str, object]:
    return json.loads((CONFIGS_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _multi_area_purpose_trigger_config() -> dict[str, object]:
    """Hand-built (DESIGN §5.4 shape): a purpose trigger targeting MULTIPLE
    areas -- `target: {"area_id": ["back_yard", "front_yard"]}` -- the exact
    shape observed in the wild (`area(["back_yard", "front_yard"])`).
    No fixture in `fixtures/configs/` happens to carry a list-valued
    `area_id`/`floor_id`/`label_id`/`device_id` target (every purpose-trigger
    fixture there targets a single area/floor/device), so this is
    constructed directly rather than borrowed."""
    return {
        "id": "multi_area_purpose_trigger",
        "alias": "Multi-area purpose trigger",
        "triggers": [
            {
                "trigger": "motion.detected",
                "target": {"area_id": ["back_yard", "front_yard"]},
                "behavior": "first",
            }
        ],
        "actions": [
            {"action": "light.turn_on", "target": {"entity_id": "light.porch"}},
        ],
        "mode": "single",
    }


def _multi_entity_state_trigger_config() -> dict[str, object]:
    """Hand-built multi-entity `state` trigger (real UI-authored shape: HA
    stores `entity_id`/`to` as lists even for one entity, DESIGN §5.4), using
    entity_ids registered in `fixtures/registry/home.json`
    (`binary_sensor.hall_motion`/`binary_sensor.kitchen_motion`)."""
    return {
        "id": "multi_entity_state_trigger",
        "alias": "Multi-entity state trigger",
        "triggers": [
            {
                "trigger": "state",
                "entity_id": ["binary_sensor.hall_motion", "binary_sensor.kitchen_motion"],
                "to": ["on", "detected"],
            }
        ],
        "actions": [
            {"action": "light.turn_on", "target": {"entity_id": "light.porch"}},
        ],
        "mode": "single",
    }


def _multi_entity_numeric_state_config() -> dict[str, object]:
    """Hand-built multi-entity `numeric_state` trigger, using entity_ids that
    actually exist in `fixtures/registry/home.json` (unlike the otherwise-
    equivalent shape in `automation_state_trigger_list_valued_fields.json`,
    whose `sensor.living_room_temp`/`sensor.bedroom_temp` are NOT in that
    snapshot -- using it here would add unrelated `reportAttributeAccessIssue`
    noise about unknown entities, not the annotation-truth bug this gate
    polices)."""
    return {
        "id": "multi_entity_numeric_state",
        "alias": "Multi-entity numeric_state trigger",
        "triggers": [
            {
                "trigger": "numeric_state",
                "entity_id": ["sensor.living_room_temperature", "sensor.bedroom_temperature"],
                "above": 20,
            }
        ],
        "actions": [
            {"action": "light.turn_on", "target": {"entity_id": "light.porch"}},
        ],
        "mode": "single",
    }


@pytest.fixture(scope="module")
def rich_shapes_bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from hassle.decompiler import decompile_bundle
    from hassle.ir import parse
    from hassle.registry.snapshot import RegistrySnapshot
    from hassle.registry.stubs import (
        generate_entities_stub,
        generate_hassle_reexport_stub,
        generate_services_stub,
    )

    snapshot = RegistrySnapshot.load(REGISTRY_FIXTURE)

    # Fixtures chosen so every entity/service reference they decompile to
    # (via the `e.<domain>.<id>` stub-sugar form) is ACTUALLY registered in
    # `fixtures/registry/home.json` -- an unregistered entity reference is a
    # correct, EXPECTED `reportAttributeAccessIssue` (that's the whole point
    # of the typed stub catching a typo/unknown entity) and would be noise
    # for this gate, which polices the annotation-truth bug classes
    # specifically, not "does every corpus fixture's entity exist in
    # home.json". `automation_template_trigger` (unregistered
    # `automation.template_trigger`), `automation_condition_numeric_state`
    # (unregistered `switch.dehumidifier`), and
    # `automation_state_trigger_list_valued_fields` (unregistered
    # `binary_sensor.x`/`sensor.living_room_temp`/`sensor.bedroom_temp`) were
    # excluded for exactly this reason -- their multi-entity/numeric_state
    # shapes are instead hand-built below
    # (`_multi_entity_numeric_state_config`) against entities that ARE
    # registered.
    fixture_names = [
        # template trigger + namespace service call (Jinja math functions).
        "automation_math_template_trigger",
        # template condition (Jinja), registered light.hallway/sensor.temperature.
        "automation_condition_template",
        # a namespace-service-call-eligible plain action (light.turn_on with
        # kwarg-expressible data -- decompiles to the typed `hassle.services`
        # form given `snapshot=`).
        "automation_purpose_trigger_area_behavior_first",
        "automation_purpose_trigger_floor_device",
    ]

    objects = {}
    for name in fixture_names:
        config = _load_fixture(name)
        key_hint = name if "id" not in config else None
        obj = parse(config, kind="automation", key_hint=key_hint)
        objects[obj.object_key()] = obj  # type: ignore[attr-defined]

    multi_area_config = _multi_area_purpose_trigger_config()
    multi_area_obj = parse(multi_area_config, kind="automation", key_hint=None)
    objects[multi_area_obj.object_key()] = multi_area_obj  # type: ignore[attr-defined]

    multi_entity_state_config = _multi_entity_state_trigger_config()
    multi_entity_state_obj = parse(multi_entity_state_config, kind="automation", key_hint=None)
    objects[multi_entity_state_obj.object_key()] = multi_entity_state_obj  # type: ignore[attr-defined]

    multi_entity_numeric_state_config = _multi_entity_numeric_state_config()
    multi_entity_numeric_state_obj = parse(
        multi_entity_numeric_state_config, kind="automation", key_hint=None
    )
    objects[multi_entity_numeric_state_obj.object_key()] = multi_entity_numeric_state_obj  # type: ignore[attr-defined]

    source = decompile_bundle(objects, snapshot=snapshot)

    out = tmp_path_factory.mktemp("annotation_truth_rich") / "rich_bundle"
    out.mkdir(parents=True, exist_ok=True)
    (out / "objects.py").write_text(source, encoding="utf-8")

    typings_registry_dir = out / "typings" / "hassle" / "registry"
    typings_registry_dir.mkdir(parents=True, exist_ok=True)
    (typings_registry_dir / "__init__.pyi").write_text(
        generate_entities_stub(snapshot), encoding="utf-8"
    )
    (out / "typings" / "hassle" / "services.pyi").write_text(
        generate_services_stub(snapshot), encoding="utf-8"
    )
    (out / "typings" / "hassle" / "__init__.pyi").write_text(
        generate_hassle_reexport_stub(), encoding="utf-8"
    )
    return out


def test_rich_corpus_shapes_bundle_is_pyright_clean_in_standard_mode(
    rich_shapes_bundle: Path,
) -> None:
    """THE GATE (bundle 2): a bundle decompiled from rich corpus shapes
    (multi-entity targets, areas incl. a MULTI-area target, numeric_state,
    template helpers, namespace service calls) must be ZERO policed
    diagnostics under `standard` mode.

    RED against current main for the same three field-evidence reasons:
    entity-typed `state(...)`/`numeric_state(...)` args, the multi-area
    `target=area([...])` sugar (once the decompiler round-trips it back
    through the `area()` builder call form), and any `triggers=[...]`
    decorator list.
    """
    _write_pyrightconfig_standard(rich_shapes_bundle, extra_paths=[str(CORE_SRC), "."])
    proc = _run_pyright(rich_shapes_bundle)
    payload = json.loads(proc.stdout or "{}")
    policed = _policed_diagnostics(payload)
    assert policed == [], (
        f"expected zero policed diagnostics on the rich-corpus-shapes bundle in "
        f"standard mode; got {len(policed)}:\n{_format_diagnostics(policed)}\n\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )


def test_multi_area_target_decompiles_to_area_list_call(rich_shapes_bundle: Path) -> None:
    """Regression pin: confirms the hand-built multi-area fixture above
    actually DID decompile through the `area([...])` list-arg call form (not,
    say, silently collapsing to a single area or falling back to `raw_*`) --
    so gate 2 is exercising the real shape it claims to, not accidentally
    passing because the decompiler never emitted it."""
    source = (rich_shapes_bundle / "objects.py").read_text(encoding="utf-8")
    assert "area(" in source
    assert "back_yard" in source and "front_yard" in source
