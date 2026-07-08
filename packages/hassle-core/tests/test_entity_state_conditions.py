"""MILESTONES M20 -- entity-first conditions (`entity.state != ""`).

`EntityRef.state` is a defined property (wins over M18's service-method
`__getattr__`) returning a comparison accessor:
  - `==`/`!=`         -> native `state` condition (`is_`/`is_not` equivalents)
  - `>`/`>=`/`<`/`<=`  -> `numeric_state` above/below (HA has no inclusive
    form; `>=`/`<=` raise a clear R6 error naming the exclusive equivalent
    rather than silently emitting a wrong bound)
  - `.in_([...])`      -> `state` condition with a list value

Also covers the SCOPE EXPANSION items absorbed into this milestone:
  (a) `StateExpr.is_not(v)` (mirrors `.is_()` exactly, compiles to
      `not_(state(x).is_(v))`'s condition shape byte-identically);
  (b) real `__eq__`/`__ne__` on the `.state` accessor object (NOT on
      `StateExpr`/`EntityRef` themselves -- those stay plain string-subclass
      types with normal string equality, same rule `TemplateExpr` follows,
      see `hassle/compiler/templates.py`);
  (c) an R6 bool-guard in every condition-accepting entry point (`only_if`,
      `choose` branches, `if_then`, `repeat_while`/`repeat_until`) so a plain
      `bool` argument (the classic `==`/`!=` typo) raises a teaching error
      instead of a bare `AttributeError`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hassle.compiler.builders import state
from hassle.compiler.conditions import all_of, any_of, not_
from hassle.compiler.control_flow import choose, if_then, repeat_until, repeat_while
from hassle.compiler.errors import CompileError
from hassle.compiler.helpers import input_text
from hassle.compiler.recording import only_if, recording
from hassle.compiler.triggers import numeric_state
from hassle.registry import entities as e

SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "errors"


def _check_snapshot(name: str, actual: str) -> None:
    import os

    path = SNAP_DIR / f"{name}.txt"
    if os.environ.get("HASSLE_UPDATE_SNAPSHOTS"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual + "\n", encoding="utf-8")
    assert path.is_file(), f"missing snapshot {path}; set HASSLE_UPDATE_SNAPSHOTS=1 to write it"
    assert actual == path.read_text(encoding="utf-8").rstrip("\n")


def _normalize(msg: str) -> str:
    return re.sub(r"(/[^\s:]+/)([^/\s:]+\.py)", r"\2", msg)


# ---------------------------------------------------------------------------
# Test 1: IR equivalence goldens -- each operator form vs its builder-form
# twin, byte-identical.
# ---------------------------------------------------------------------------


def test_state_eq_condition_matches_builder_form_exactly() -> None:
    accessor_result = (e.input_select.day_phase.state == "Sleeping").to_condition()
    builder_result = state("input_select.day_phase").is_("Sleeping").to_condition()
    assert accessor_result == builder_result
    assert accessor_result == {
        "condition": "state",
        "entity_id": "input_select.day_phase",
        "state": "Sleeping",
    }


def test_state_ne_condition_matches_not_is_builder_form_exactly() -> None:
    accessor_result = (e.sensor.last_shown_notification.state != "").to_condition()
    builder_result = not_(state("sensor.last_shown_notification").is_("")).to_condition()
    assert accessor_result == builder_result
    assert accessor_result == {
        "condition": "not",
        "conditions": [
            {"condition": "state", "entity_id": "sensor.last_shown_notification", "state": ""}
        ],
    }


def test_state_is_not_method_matches_not_is_builder_form_exactly() -> None:
    """(a) `StateExpr.is_not(v)` mirrors `.is_()` exactly -- same combinator
    shape as `not_(state(x).is_(v))`, byte-identical."""
    via_is_not = state("sensor.x").is_not("home").to_condition()
    via_not_is = not_(state("sensor.x").is_("home")).to_condition()
    assert via_is_not == via_not_is
    assert via_is_not == {
        "condition": "not",
        "conditions": [{"condition": "state", "entity_id": "sensor.x", "state": "home"}],
    }


def test_state_gt_condition_matches_numeric_state_above_builder_form() -> None:
    accessor_result = (e.sensor.temp.state > 21.5).to_condition()
    builder_result = numeric_state("sensor.temp", above=21.5).to_condition()
    assert accessor_result == builder_result
    assert accessor_result == {
        "condition": "numeric_state",
        "entity_id": "sensor.temp",
        "above": 21.5,
    }


def test_state_lt_condition_matches_numeric_state_below_builder_form() -> None:
    accessor_result = (e.sensor.temp.state < 21.5).to_condition()
    builder_result = numeric_state("sensor.temp", below=21.5).to_condition()
    assert accessor_result == builder_result
    assert accessor_result == {
        "condition": "numeric_state",
        "entity_id": "sensor.temp",
        "below": 21.5,
    }


def test_state_in_condition_matches_state_is_list_builder_form() -> None:
    accessor_result = e.input_select.day_phase.state.in_(["Sleeping", "Waking"]).to_condition()
    builder_result = state("input_select.day_phase").is_(["Sleeping", "Waking"]).to_condition()
    assert accessor_result == builder_result
    assert accessor_result == {
        "condition": "state",
        "entity_id": "input_select.day_phase",
        "state": ["Sleeping", "Waking"],
    }


def test_state_accessor_also_works_on_helper_declaration_refs() -> None:
    """The owner's actual driving case: a helper-declaration handle (not an
    `e.`-registry ref) also gets the `.state` accessor -- one implementation,
    wherever `EntityRef` appears."""
    with recording(alias="x", id="x"):
        last_shown_notification = input_text(id="last_shown_notification")
    accessor_result = (last_shown_notification.state != "").to_condition()
    builder_result = not_(state("input_text.last_shown_notification").is_("")).to_condition()
    assert accessor_result == builder_result


# ---------------------------------------------------------------------------
# >=/<= mapping decision: HA's numeric_state above/below are EXCLUSIVE bounds
# (verified against the IR model, hassle/compiler/triggers.py::NumericStateExpr
# -- no inclusive form exists). Silently mapping `>=`/`<=` onto the exclusive
# fields would compile a WRONG condition (off-by-the-boundary-value), so both
# raise a clear R6 error naming the honest exclusive rewrite instead.
# ---------------------------------------------------------------------------


def test_state_ge_raises_r6_error_naming_exclusive_rewrite() -> None:
    with recording(alias="x", id="x"), pytest.raises(CompileError) as excinfo:
        _ = e.sensor.temp.state >= 21.5
    msg = str(excinfo.value)
    assert "Fix:" in msg
    assert ">" in msg  # names the exclusive equivalent as the suggested fix


def test_state_le_raises_r6_error_naming_exclusive_rewrite() -> None:
    with recording(alias="x", id="x"), pytest.raises(CompileError) as excinfo:
        _ = e.sensor.temp.state <= 21.5
    msg = str(excinfo.value)
    assert "Fix:" in msg
    assert "<" in msg


def test_state_ge_error_is_snapshot_tested() -> None:
    with recording(alias="x", id="x"), pytest.raises(CompileError) as excinfo:
        _ = e.sensor.temp.state >= 21.5
    _check_snapshot("state_accessor_ge_no_inclusive_bound", _normalize(str(excinfo.value)))


def test_state_le_error_is_snapshot_tested() -> None:
    with recording(alias="x", id="x"), pytest.raises(CompileError) as excinfo:
        _ = e.sensor.temp.state <= 21.5
    _check_snapshot("state_accessor_le_no_inclusive_bound", _normalize(str(excinfo.value)))


# ---------------------------------------------------------------------------
# Test 2: the `in`-operator trap -- `x.state in ["a"]` inside a condition
# context raises the R6 error naming `.in_()`; snapshot-tested.
# ---------------------------------------------------------------------------


def test_state_in_operator_trap_raises_naming_in_underscore() -> None:
    with recording(alias="x", id="x"), pytest.raises(CompileError) as excinfo:
        if e.input_select.day_phase.state in ["Sleeping", "Waking"]:
            pass
    msg = str(excinfo.value)
    assert ".in_(" in msg
    assert "Fix:" in msg


def test_state_in_operator_trap_is_snapshot_tested() -> None:
    with recording(alias="x", id="x"), pytest.raises(CompileError) as excinfo:
        if e.input_select.day_phase.state in ["Sleeping", "Waking"]:
            pass
    _check_snapshot("state_accessor_in_operator_trap", _normalize(str(excinfo.value)))


def test_bare_bool_of_state_accessor_also_traps() -> None:
    """The accessor itself (before any comparison) must never be usable as a
    bare Python truthy value either -- `if e.x.state:` is the same class of
    silent-compile-time-branch mistake DESIGN §5.5 already traps for
    `StateExpr`/`NumericStateExpr`."""
    with recording(alias="x", id="x"), pytest.raises(CompileError):
        if e.input_select.day_phase.state:
            pass


# ---------------------------------------------------------------------------
# Test 3: trigger/expression non-confusion -- `.state` accessor used where a
# TRIGGER is expected raises a clear error; `state_of()` (M16) remains the
# template-string read, `.state` is the native-condition read.
# ---------------------------------------------------------------------------


def test_state_accessor_result_has_no_to_trigger_method() -> None:
    """A `.state` comparison builds a CONDITION object only -- it has no
    `to_trigger`, so passing it to `when(...)` fails clearly (AttributeError
    on the missing method) rather than silently compiling as some other
    trigger shape."""
    result = e.input_select.day_phase.state == "Sleeping"
    assert not hasattr(result, "to_trigger")
    assert hasattr(result, "to_condition")


def test_state_accessor_used_as_when_trigger_raises_clear_error() -> None:
    from hassle.compiler.recording import when

    with recording(alias="x", id="x"), pytest.raises(AttributeError):
        when(e.input_select.day_phase.state == "Sleeping")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Test 5: pyright strict clean despite __eq__ overloads (the documented
# typing dance) -- exercised by the pyright gate itself (packages/hassle-core
# is --strict, see the report); this test pins the runtime hash-story finding
# (StateExpr/EntityRef stay hashable, unaffected by the accessor's __eq__).
# ---------------------------------------------------------------------------


def test_entity_ref_remains_hashable_and_dict_keyable() -> None:
    """`EntityRef` itself never gained an `__eq__` override (only the new
    `.state` ACCESSOR object did) -- so it stays usable as a dict key/in a
    set, exactly as any `str` is, unaffected by this milestone."""
    d = {e.sensor.temp: "ok"}
    assert d[e.sensor.temp] == "ok"
    assert e.sensor.temp in {e.sensor.temp, e.sensor.other}
    assert hash(e.sensor.temp) == hash(str(e.sensor.temp))


def test_state_accessor_result_is_not_hashed_but_has_explicit_dunder() -> None:
    """The accessor's __eq__-result (a condition-builder object) is not a
    dict-key type in practice, but must not silently inherit a broken
    identity-hash/equality mismatch either -- covered by an explicit
    `__hash__ = object.__hash__` on the accessor class (see
    `hassle.compiler.builders._StateAccessor`), so `hash()` never raises
    `TypeError` (Python's automatic "unhashable type" rule kicks in for any
    class defining `__eq__` without also defining `__hash__`)."""
    from hassle.compiler.builders import _StateAccessor  # pyright: ignore[reportPrivateUsage]

    accessor = e.sensor.temp.state
    assert isinstance(accessor, _StateAccessor)
    hash(accessor)  # must not raise TypeError


# ---------------------------------------------------------------------------
# (c) R6 bool-guard sweep: a plain `bool` argument to every condition-
# accepting entry point raises a teaching what/where/fix error (today: a raw
# `AttributeError: 'bool' object has no attribute 'to_condition'`).
# ---------------------------------------------------------------------------


def test_only_if_bare_bool_raises_r6_error() -> None:
    # The classic mistake this guards: comparing two plain Python values
    # (never touching `.state`/a builder at all) instead of building a real
    # condition -- collapses to a bare `bool` by the time it reaches
    # `only_if(...)`.
    with recording(alias="x", id="x"), pytest.raises(CompileError) as excinfo:
        only_if("Sleeping" == "Sleeping")  # type: ignore[arg-type]
    msg = str(excinfo.value)
    assert "Fix:" in msg
    assert ".is_(" in msg or ".is_not(" in msg or "==" in msg


def test_if_then_bare_bool_raises_r6_error() -> None:
    with (
        recording(alias="x", id="x"),
        pytest.raises(CompileError) as excinfo,
        if_then(True),  # type: ignore[arg-type]
    ):
        pass
    msg = str(excinfo.value)
    assert "Fix:" in msg


def test_choose_when_bare_bool_raises_r6_error() -> None:
    with (
        recording(alias="x", id="x"),
        pytest.raises(CompileError) as excinfo,
        choose() as c,
        c.when_(True),  # type: ignore[arg-type]
    ):
        pass
    msg = str(excinfo.value)
    assert "Fix:" in msg


def test_repeat_while_bare_bool_raises_r6_error() -> None:
    with (
        recording(alias="x", id="x"),
        pytest.raises(CompileError) as excinfo,
        repeat_while(False),  # type: ignore[arg-type]
    ):
        pass
    msg = str(excinfo.value)
    assert "Fix:" in msg


def test_repeat_until_bare_bool_raises_r6_error() -> None:
    with (
        recording(alias="x", id="x"),
        pytest.raises(CompileError) as excinfo,
        repeat_until(False),  # type: ignore[arg-type]
    ):
        pass
    msg = str(excinfo.value)
    assert "Fix:" in msg


def test_any_of_bare_bool_raises_r6_error() -> None:
    with recording(alias="x", id="x"), pytest.raises(CompileError) as excinfo:
        any_of(True, e.input_select.day_phase.state == "Sleeping").to_condition()  # type: ignore[arg-type]
    msg = str(excinfo.value)
    assert "Fix:" in msg


def test_all_of_bare_bool_raises_r6_error() -> None:
    with recording(alias="x", id="x"), pytest.raises(CompileError) as excinfo:
        all_of(False).to_condition()  # type: ignore[arg-type]
    msg = str(excinfo.value)
    assert "Fix:" in msg


def test_not__bare_bool_raises_r6_error() -> None:
    with recording(alias="x", id="x"), pytest.raises(CompileError) as excinfo:
        not_(True).to_condition()  # type: ignore[arg-type]
    msg = str(excinfo.value)
    assert "Fix:" in msg


def test_only_if_bool_guard_is_snapshot_tested() -> None:
    with recording(alias="x", id="x"), pytest.raises(CompileError) as excinfo:
        only_if(True)  # type: ignore[arg-type]
    _check_snapshot("bool_guard_only_if", _normalize(str(excinfo.value)))


def test_if_then_bool_guard_is_snapshot_tested() -> None:
    with (
        recording(alias="x", id="x"),
        pytest.raises(CompileError) as excinfo,
        if_then(False),  # type: ignore[arg-type]
    ):
        pass
    _check_snapshot("bool_guard_if_then", _normalize(str(excinfo.value)))


def test_choose_when_bool_guard_is_snapshot_tested() -> None:
    with (
        recording(alias="x", id="x"),
        pytest.raises(CompileError) as excinfo,
        choose() as c,
        c.when_(True),  # type: ignore[arg-type]
    ):
        pass
    _check_snapshot("bool_guard_choose_when", _normalize(str(excinfo.value)))


# ---------------------------------------------------------------------------
# Regression guards: a real (non-bool) condition builder still passes through
# every one of these entry points completely unaffected.
# ---------------------------------------------------------------------------


def test_only_if_real_condition_unaffected() -> None:
    with recording(alias="x", id="x") as rec:
        only_if(e.input_select.day_phase.state == "Sleeping")
    assert rec.conditions[0].body == {
        "condition": "state",
        "entity_id": "input_select.day_phase",
        "state": "Sleeping",
    }


def test_if_then_real_condition_unaffected() -> None:
    from hassle.compiler.actions import service

    with (
        recording(alias="x", id="x") as rec,
        if_then(e.input_select.day_phase.state == "Sleeping"),
    ):
        service("light.turn_on")
    assert rec.actions[0].body["if"] == [
        {"condition": "state", "entity_id": "input_select.day_phase", "state": "Sleeping"}
    ]


# ---------------------------------------------------------------------------
# Test 4: stubs -- generated entity classes type the `.state` accessor; the
# M28 decompiled-bundle pyright gate stays zero (exercised in full by
# packages/hassle-dev/tests/test_annotation_truth_pyright_gate.py, which
# already builds/pyrights a real decompiled bundle against these generated
# stubs). These pin the generator's own output shape.
# ---------------------------------------------------------------------------


def test_generated_entity_stub_types_state_accessor() -> None:
    from hassle.registry.snapshot import RegistrySnapshot
    from hassle.registry.stubs import generate_entities_stub

    repo_root = Path(__file__).resolve().parents[3]
    snapshot = RegistrySnapshot.load(repo_root / "fixtures" / "registry" / "home.json")
    stub = generate_entities_stub(snapshot)
    # Every entity class gets the accessor -- even a domain with no typed
    # services (which used to collapse to the one-line `class X(str): ...`
    # form; see test_registry_stubs.py::test_stub_entity_classes_inherit_str).
    assert "class BinarySensorEntity(str):" in stub
    assert "class BinarySensorEntity(str): ..." not in stub
    assert stub.count("def state(self) -> Any: ...") >= 1
    assert "    @property\n    def state(self) -> Any: ..." in stub


def test_generated_entity_stub_is_valid_python() -> None:
    import ast

    from hassle.registry.snapshot import RegistrySnapshot
    from hassle.registry.stubs import generate_entities_stub

    repo_root = Path(__file__).resolve().parents[3]
    snapshot = RegistrySnapshot.load(repo_root / "fixtures" / "registry" / "home.json")
    stub = generate_entities_stub(snapshot)
    ast.parse(stub)  # must not raise
