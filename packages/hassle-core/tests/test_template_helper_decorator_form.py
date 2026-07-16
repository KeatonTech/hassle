"""Template-helper DECORATOR form.

Golden DSL<->IR pair: `fixtures/dsl/template_helper_decorator_form/`
covers all four template domains in decorator form; `test_dsl_golden_pairs.py`
already exercises it as an ordinary golden case (it is discovered generically
from `fixtures/dsl/`). This file adds the byte-identical-IR-to-the-equivalent-
call-form assertion, plus the
decorator's own contract (zero-arg body, `TemplateExpr`/`str` return only --
DESIGN §5.4/§5.7 extension).

Bad decorator body -> compile error stating what/where/fix, snapshot-tested:
`TemplateHelperDecoratorBodyError` for the three ways a decorated function can
misbehave -- declared parameters, a recording-verb call (naturally surfaces as
`NoRecordingContextError`, itself already snapshot-tested elsewhere), and a
non-`TemplateExpr`/`str` return value.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle import expr, service, template_number, template_sensor
from hassle.compiler import NoRecordingContextError, TemplateHelperDecoratorBodyError
from hassle.compiler.bundle import compile_bundle
from hassle.compiler.template_helpers import reset_declared_template_helpers
from hassle.registry import entities as e
from hassle_dev.snapshots import check_snapshot, normalize_error

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "dsl"
    / "template_helper_decorator_form"
    / "bundle"
)
CALL_FORM_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "dsl"
    / "template_helper_declarations"
    / "bundle"
)


SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "errors"


def _check_snapshot(name: str, actual: str) -> None:
    check_snapshot(SNAP_DIR, name, actual)


def _normalize(msg: str) -> str:
    return normalize_error(msg, mask_lines_for=Path(__file__).name)


@pytest.fixture(autouse=True)
def _reset():
    reset_declared_template_helpers()
    yield
    reset_declared_template_helpers()


# ---------------------------------------------------------------------------
# Test 1: decorator form compiles to the identical IR as the equivalent call
# form (byte-identical bodies) -- all four template domains.
# ---------------------------------------------------------------------------


def test_decorator_form_golden_case_is_present_and_covers_all_four_domains() -> None:
    result = compile_bundle(FIXTURE)
    assert set(result.objects) == {
        "template_number:active_hvac_zones",
        "template_sensor:average_temp",
        "template_binary_sensor:any_door_open",
        "template_select:house_scene",
    }


def test_decorator_form_state_is_rendered_jinja_not_a_bare_repr() -> None:
    """The `state=` body key must be the RENDERED Jinja text (`TemplateExpr.
    __str__`), exactly like the call form's `_render_state` does for an
    Expr-builder value -- never the Python repr of the returned object."""
    result = compile_bundle(FIXTURE)
    obj = result.objects["template_sensor:average_temp"]
    state = obj.to_ha()["state"]
    assert state == "{{ (states('sensor.a') | float + states('sensor.b') | float) / 2 }}"


def test_decorator_form_identity_is_still_slug_of_name() -> None:
    """Identity remains `slug(name)` (§26.6) regardless of the cosmetic
    function name -- exercise a case where the function name and the name's
    slug intentionally differ, to prove identity comes from `name=`, not
    from `func.__name__`."""

    @template_sensor(name="Weirdly Named Sensor!!")
    def totally_different_function_name():
        return expr(e.sensor.a)

    from hassle.compiler.registry import current_registry

    prebuilt = current_registry().prebuilt
    keys = [p.obj.object_key() for p in prebuilt]
    assert "template_sensor:weirdly_named_sensor" in keys


def test_decorator_form_matches_hand_written_call_form_ir_shape() -> None:
    """Golden-pair equivalence (milestone text): the decorator fixture's
    `template_sensor:average_temp` IR has the exact same KEYS (and non-state
    values) as the call-form fixture's own `template_sensor:average_temp` --
    only `state=`'s Jinja text differs (a different, but equivalent,
    expression was used on each side to also prove the state text is
    computed from the DECORATOR fixture's own body, not copy-pasted)."""
    decorator_result = compile_bundle(FIXTURE)
    call_result = compile_bundle(CALL_FORM_FIXTURE)
    decorator_ir = decorator_result.objects["template_sensor:average_temp"].to_ha()
    call_ir = call_result.objects["template_sensor:average_temp"].to_ha()
    assert set(decorator_ir) == set(call_ir)
    assert decorator_ir["name"] == call_ir["name"]
    assert decorator_ir["unit_of_measurement"] == call_ir["unit_of_measurement"]
    assert decorator_ir["device_class"] == call_ir["device_class"]
    assert decorator_ir["state"].startswith("{{") and decorator_ir["state"].endswith("}}")


def test_decorator_form_reuses_write_target_validation() -> None:
    """`template_number`/`template_select`'s required-write-target check
    (`MissingTemplateHelperWriteTargetError`) still fires in decorator form --
    the decorator kwargs are the SAME kwargs dict the call form validates."""
    from hassle.compiler import MissingTemplateHelperWriteTargetError

    with pytest.raises(MissingTemplateHelperWriteTargetError):

        @template_number(name="No Write Target")
        def _no_write_target():
            return expr(e.sensor.a)


# ---------------------------------------------------------------------------
# Bad decorator body -> compile error stating what/where/fix, snapshot-tested.
# ---------------------------------------------------------------------------


def test_decorator_with_parameters_raises_decorator_body_error() -> None:
    with pytest.raises(TemplateHelperDecoratorBodyError) as excinfo:

        @template_sensor(name="Bad Sensor")
        def _bad_sensor(some_arg):
            return expr(e.sensor.a)

    msg = str(excinfo.value)
    assert "test_template_helper_decorator_form.py" in msg
    assert "some_arg" in msg
    assert "zero" in msg or "no parameters" in msg


def test_decorator_with_parameters_message_snapshot() -> None:
    with pytest.raises(TemplateHelperDecoratorBodyError) as excinfo:

        @template_sensor(name="Bad Sensor")
        def _bad_sensor(some_arg):
            return expr(e.sensor.a)

    _check_snapshot("template_helper_decorator_has_parameters", _normalize(str(excinfo.value)))


def test_decorator_returning_non_template_expr_raises_decorator_body_error() -> None:
    with pytest.raises(TemplateHelperDecoratorBodyError) as excinfo:

        @template_sensor(name="Bad Return Sensor")
        def _bad_return_sensor():
            return 42

    msg = str(excinfo.value)
    assert "test_template_helper_decorator_form.py" in msg
    assert "42" in msg
    assert "TemplateExpr" in msg


def test_decorator_returning_non_template_expr_message_snapshot() -> None:
    with pytest.raises(TemplateHelperDecoratorBodyError) as excinfo:

        @template_sensor(name="Bad Return Sensor")
        def _bad_return_sensor():
            return 42

    _check_snapshot("template_helper_decorator_bad_return", _normalize(str(excinfo.value)))


def test_decorator_calling_a_recording_verb_raises_no_recording_context_error() -> None:
    """A `service(...)` call inside a decorator body has nowhere to record
    into (the decorator form calls the function directly, no active
    recorder) -- this is `NoRecordingContextError`, not a NEW error class;
    already snapshot-tested (`test_no_recording_context...`), asserted
    here as belt-and-suspenders that the decorator form actually reaches that
    same trap rather than silently swallowing the call."""
    with pytest.raises(NoRecordingContextError):

        @template_sensor(name="Side Effecting Sensor")
        def _side_effecting_sensor():
            service("notify.mobile_app", message="hi")
            return expr(e.sensor.a)


def test_decorator_body_user_exception_is_chained_under_decorator_body_error() -> None:
    """A plain (non-CompileError) exception raised
    inside the decorated function -- e.g. a `ZeroDivisionError` from a bug in
    the user's expression math -- is chained under
    `TemplateHelperDecoratorBodyError` so the helper's `@template_sensor(...)`
    file:line is visible, with the original exception/traceback preserved via
    `raise ... from exc`."""
    with pytest.raises(TemplateHelperDecoratorBodyError) as excinfo:

        @template_sensor(name="Buggy Sensor")
        def _buggy_sensor():
            return 1 / 0  # deliberate user bug under test

    msg = str(excinfo.value)
    assert "test_template_helper_decorator_form.py" in msg
    assert "ZeroDivisionError" in msg
    assert isinstance(excinfo.value.__cause__, ZeroDivisionError)


def test_decorator_returning_plain_jinja_string_is_accepted() -> None:
    """A plain `str` return (raw Jinja, not built via the Expr surface) is
    also accepted -- `state=` always took either shape in the call form
    (module docstring's `_render_state`), and the decorator form must accept
    both too."""

    @template_sensor(name="Raw String Sensor")
    def _raw_string_sensor():
        return "{{ states('sensor.a') }}"

    from hassle.compiler.registry import current_registry

    prebuilt = current_registry().prebuilt
    obj = next(p.obj for p in prebuilt if p.obj.object_key() == "template_sensor:raw_string_sensor")
    assert obj.to_ha()["state"] == "{{ states('sensor.a') }}"
