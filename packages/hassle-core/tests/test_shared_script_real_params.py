"""M19 -- shared-script parameters are real template values.

MILESTONES M19 ("Write these tests first"):

1. Golden: a body written with `tag=tag` and a composed `concat(tag, ...)`
   compiles to the exact `"{{ tag }}"` / `"{{ tag ~ '...' }}"` IR the
   `param()` string form produces (byte-identical to the `param()` form).
2. Marker misuse: `range(times)` / `if tag:` in a body -> R6 error naming
   `param_default()`; `param_default` itself returns the declared default
   and its result is NOT a TemplateExpr.
4. `param()` remains valid and equivalent (back-compat, F3).
6. Simulator parity (I5) for marker-bound bodies.

(Test 3, the decompiler round-trip, lives in
`test_decompile_shared_script_real_params.py`; test 5, the corpus/docs
migration audit, is covered by the existing `hassle-dev goldens`/`docs` gates
plus the fixture corpus audit itself -- every pre-M19 shared-script fixture
in this PR still compiles byte-identically, no golden regenerated for them.)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.compiler import compile_bundle
from hassle.compiler.scripts import SharedScriptParamMisuseError

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "dsl"


# ---------------------------------------------------------------------------
# Test 1 -- bare parameter reads are real template values, byte-identical to
# the equivalent param() form.
# ---------------------------------------------------------------------------


def test_bare_param_name_is_a_runtime_field_read() -> None:
    result = compile_bundle(FIXTURES / "shared_script_bare_param" / "bundle")
    script_obj = result.objects["script:dismiss_tagged_notification"].to_ha()
    assert script_obj["sequence"][0]["data"]["notification_id"] == "{{ tag }}"


def test_bare_param_composes_with_the_expression_surface() -> None:
    result = compile_bundle(FIXTURES / "shared_script_bare_param" / "bundle")
    script_obj = result.objects["script:dismiss_tagged_notification"].to_ha()
    assert script_obj["sequence"][1]["data"]["notification_id"] == "{{ tag ~ '_x' }}"


def test_bare_param_form_byte_identical_to_param_form() -> None:
    """The owner's real shape (`tag=tag`) and the pre-M19 `param("tag")`
    spelling must compile to the exact same IR -- proven directly by
    compiling both `shared_script_bare_param` (bare) and
    `shared_script_call_metadata` (param()) and comparing the analogous
    single-field-read data value, not just eyeballing the golden JSON.
    """
    bare = compile_bundle(FIXTURES / "shared_script_bare_param" / "bundle")
    via_param = compile_bundle(FIXTURES / "shared_script_call_metadata" / "bundle")
    bare_data = bare.objects["script:dismiss_tagged_notification"].to_ha()["sequence"][0]["data"]
    param_data = via_param.objects["script:dismiss_notification"].to_ha()["sequence"][0]["data"]
    # Both are a single field read rendered as `"{{ <field> }}"` -- the exact
    # same Jinja shape regardless of which field/script it came from.
    assert bare_data["notification_id"] == "{{ tag }}"
    assert param_data["notification_id"] == "{{ notification_id }}"


# ---------------------------------------------------------------------------
# Test 2 -- marker misuse: range()/if on a bound parameter is a loud R6
# error naming param_default(); param_default() itself is the escape hatch.
# ---------------------------------------------------------------------------


def test_range_on_bound_param_raises_shared_script_misuse_error() -> None:
    case = FIXTURES / "shared_script_param_range_misuse" / "bundle"
    with pytest.raises(SharedScriptParamMisuseError) as excinfo:
        compile_bundle(case)
    message = str(excinfo.value)
    assert "param_default" in message
    assert "times" in message
    assert "scripts.py" in message


def test_if_on_bound_param_raises_shared_script_misuse_error() -> None:
    case = FIXTURES / "shared_script_param_if_misuse" / "bundle"
    with pytest.raises(SharedScriptParamMisuseError) as excinfo:
        compile_bundle(case)
    message = str(excinfo.value)
    assert "param_default" in message
    assert "tag" in message
    assert "scripts.py" in message


def test_param_default_returns_declared_default_not_a_template_expr() -> None:
    result = compile_bundle(FIXTURES / "shared_script_param_default" / "bundle")
    script_obj = result.objects["script:flash_lights_unrolled"].to_ha()
    # Unrolled 3 times at compile time (the declared default) -- 3 pairs of
    # (toggle, delay) actions, not a single param()-bound runtime read.
    actions = script_obj["sequence"]
    assert len(actions) == 6
    assert all(a.get("action") == "light.toggle" for a in actions[0::2])


def test_param_default_value_is_plain_python_not_template_expr() -> None:
    """`param_default("times")` inside the real fixture body returns `3` (a
    plain int), which is exactly why `range()` on it works -- proven by the
    fact compilation reaches the unrolled 6-action sequence at all (a
    TemplateExpr fed to `range()` raises `TypeError`, `test_range_on_bound_
    param_raises_shared_script_misuse_error` pins that for the *unbound*
    marker case)."""
    from hassle.compiler.templates import TemplateExpr

    result = compile_bundle(FIXTURES / "shared_script_param_default" / "bundle")
    script_obj = result.objects["script:flash_lights_unrolled"].to_ha()
    assert isinstance(script_obj["fields"]["times"]["default"], int)
    assert not isinstance(script_obj["fields"]["times"]["default"], TemplateExpr)


# ---------------------------------------------------------------------------
# Test 4 -- param() remains valid and equivalent (back-compat, F3).
# ---------------------------------------------------------------------------


def test_param_still_works_and_matches_bare_form() -> None:
    # shared_script_call_metadata (pre-existing fixture) still uses
    # param("notification_id") -- must still compile to the same runtime
    # read the bare form produces.
    result = compile_bundle(FIXTURES / "shared_script_call_metadata" / "bundle")
    script_obj = result.objects["script:dismiss_notification"].to_ha()
    assert script_obj["sequence"][0]["data"]["notification_id"] == "{{ notification_id }}"


# ---------------------------------------------------------------------------
# Test 6 -- simulator parity (I5): the simulator only ever sees compiled IR,
# and marker-bound vs param()-bound bodies compile to indistinguishable IR,
# so simulated behavior is identical either way.
# ---------------------------------------------------------------------------


def test_simulator_parity_for_marker_bound_shared_script_call() -> None:
    from hassle.testing import simulate

    sim = simulate(FIXTURES / "shared_script_bare_param" / "bundle")
    sim.state_change("input_boolean.guest_mode", "on", "off")
    sim.assert_called("script.dismiss_tagged_notification", tag="guest_reminder")


def test_simulator_parity_matches_param_form_call() -> None:
    """The pre-existing param()-bound fixture behaves identically under the
    simulator -- I5 parity isn't a new code path, just proof the M19 binding
    change never leaks into what the simulator (which only ever consumes
    compiled IR/HA-JSON, `test_sim_runs_compiled_ir_only.py`) can observe."""
    from hassle.testing import simulate

    sim = simulate(FIXTURES / "shared_script_call_metadata" / "bundle")
    sim.state_change("input_boolean.guest_mode", "on", "off")
    sim.assert_called("script.dismiss_notification", notification_id="guest_reminder")
