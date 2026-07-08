"""M19 -- shared-script parameters are real template values.

MILESTONES M19 ("Write these tests first"):

1. Golden: a body written with `tag=tag` and a composed `concat(tag, ...)`
   compiles to the exact `"{{ tag }}"` / `"{{ tag ~ '...' }}"` IR the
   `param()` string form produces (byte-identical to the `param()` form).
2. Marker misuse: `range(times)` / `if tag:` in a body -> R6 error teaching
   the honest alternatives (owner amendment: the originally-planned
   `param_default()` escape hatch was REJECTED -- it would bake a stale
   compile-time value into the compiled sequence while the HA field still
   exists and still invites callers to pass other values, making the field a
   lie. The blessed alternatives are a runtime construct HA itself supports
   (`with repeat_count(times):`, which accepts the marker directly) for a
   genuinely runtime value, or a module constant / `@macro` argument for a
   genuinely compile-time one -- see `test_repeat_count_positive.py` for the
   blessed pattern's own golden case).
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

import hassle
from hassle.compiler import compile_bundle
from hassle.compiler.scripts import SharedScriptParamMisuseError, shared_script

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
# error teaching the honest alternatives (repeat_count(...) for a runtime
# value, a module constant/@macro argument for a compile-time one).
# ---------------------------------------------------------------------------


def test_range_on_bound_param_raises_shared_script_misuse_error() -> None:
    case = FIXTURES / "shared_script_param_range_misuse" / "bundle"
    with pytest.raises(SharedScriptParamMisuseError) as excinfo:
        compile_bundle(case)
    message = str(excinfo.value)
    assert "repeat_count(times)" in message
    assert "@macro" in message
    assert "times" in message
    assert "scripts.py" in message
    # The rejected escape hatch must NOT be named -- it doesn't exist.
    assert "param_default" not in message


def test_if_on_bound_param_raises_shared_script_misuse_error() -> None:
    case = FIXTURES / "shared_script_param_if_misuse" / "bundle"
    with pytest.raises(SharedScriptParamMisuseError) as excinfo:
        compile_bundle(case)
    message = str(excinfo.value)
    assert "repeat_count(tag)" in message
    assert "@macro" in message
    assert "tag" in message
    assert "scripts.py" in message
    assert "param_default" not in message


def test_param_default_is_gone() -> None:
    """Owner amendment (MILESTONES M19): `param_default` was rejected and
    removed entirely -- it bakes a stale compile-time value into the
    compiled sequence while the HA field still exists, making the field a
    lie. Neither the module-internal function nor its error class exist
    anymore."""
    import hassle.compiler.scripts as scripts_module

    assert not hasattr(scripts_module, "param_default")
    assert not hasattr(scripts_module, "NoDeclaredDefaultError")
    assert "param_default" not in hassle.__all__
    assert "NoDeclaredDefaultError" not in hassle.__all__


# ---------------------------------------------------------------------------
# Test 2 (reviewer finding, M19 PR review): container dunders. `param()`'s
# marker is a `str` subclass, so `for x in marker:` / `"a" in marker` /
# `len(marker)` / `marker[0]` would otherwise sail through SILENTLY WRONG
# (iterating/checking/measuring the literal `"{{ name }}"` Jinja text)
# instead of raising at all -- trapped the same way the numeric/boolean
# dunders are.
# ---------------------------------------------------------------------------


def _bound_marker(name: str, fields: frozenset[str]):
    from hassle.compiler.scripts import _ACTIVE_FIELDS, param

    token = _ACTIVE_FIELDS.set(fields)
    try:
        return param(name)
    finally:
        _ACTIVE_FIELDS.reset(token)


def test_iteration_on_bound_param_raises_shared_script_misuse_error() -> None:
    marker = _bound_marker("items", frozenset({"items"}))
    with pytest.raises(SharedScriptParamMisuseError) as excinfo:
        for _ in marker:
            pass
    message = str(excinfo.value)
    assert "repeat_for_each(items)" in message
    assert "items" in message


def test_membership_on_bound_param_raises_shared_script_misuse_error() -> None:
    marker = _bound_marker("area", frozenset({"area"}))
    with pytest.raises(SharedScriptParamMisuseError) as excinfo:
        assert "living" in marker
    message = str(excinfo.value)
    assert "runtime membership" in message
    assert "area" in message


def test_len_on_bound_param_raises_shared_script_misuse_error() -> None:
    marker = _bound_marker("tag", frozenset({"tag"}))
    with pytest.raises(SharedScriptParamMisuseError) as excinfo:
        len(marker)
    assert "tag" in str(excinfo.value)


def test_getitem_on_bound_param_raises_shared_script_misuse_error() -> None:
    marker = _bound_marker("tag", frozenset({"tag"}))
    with pytest.raises(SharedScriptParamMisuseError) as excinfo:
        marker[0]
    assert "tag" in str(excinfo.value)


def test_str_and_composition_unaffected_by_container_traps() -> None:
    """The container-dunder traps must NOT break the rendering/composition
    surface every internal consumer relies on: `str()`/f-string
    interpolation (`__str__`, untouched), `+`/`.eq()`/`concat(...)`
    (`_as_operand`-based composition, untouched), and JSON serialization
    (treats a `str` as an opaque leaf -- never iterates/indexes it)."""
    import json

    from hassle.compiler.math_expr import concat

    marker = _bound_marker("tag", frozenset({"tag"}))
    assert str(marker) == "{{ tag }}"
    assert f"{marker}" == "{{ tag }}"
    assert concat(marker, "_x") == "{{ tag ~ '_x' }}"
    assert marker.eq("x") == "{{ tag == 'x' }}"
    assert json.dumps({"k": marker}) == '{"k": "{{ tag }}"}'


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


# ---------------------------------------------------------------------------
# Typing investigation (MILESTONES M19, owner pre-merge design feedback):
# `@shared_script`'s signature now annotates every field `TemplateExpr`
# (body-true typing) with `field_default(...)`-typed defaults. The COMPILE-
# TIME net for a bad call-site kwarg is what actually protects a bundle
# author (pyright can't -- the caller wrapper is `(*args: Any, **kwargs:
# Any) -> None`, fully decoupled from the def's own annotations, verified
# empirically: neither a wrong kwarg NAME nor a wrong kwarg VALUE TYPE at a
# call site produces any pyright diagnostic under standard mode). Both
# reachable variants of that net are pinned here.
# ---------------------------------------------------------------------------


def test_unknown_kwarg_rejected_for_signature_derived_script(tmp_path: Path) -> None:
    """Signature-derived script (no explicit `fields=`): the net is Python's
    OWN `TypeError` from `inspect.Signature.bind_partial`, not
    `UnknownFieldError` (that error is reserved for the `fields=`-given case,
    see the next test) -- still a compile-time failure, never a silent
    pass-through, and never something pyright could have caught instead."""
    (tmp_path / "scripts.py").write_text(
        "from hassle import automation, service, shared_script, state, when\n\n\n"
        '@shared_script(id="flash_lights", alias="Flash lights")\n'
        "def flash_lights(times: int = 3):\n"
        '    service("light.toggle", entity_id="light.all")\n\n\n'
        '@automation(id="a1", alias="A1")\n'
        "def a1():\n"
        '    when(state("input_boolean.x").to("on"))\n'
        "    flash_lights(bogus_kwarg=5)\n",
        encoding="utf-8",
    )
    with pytest.raises(TypeError, match="bogus_kwarg"):
        compile_bundle(tmp_path)


def test_unknown_kwarg_rejected_for_explicit_fields_script() -> None:
    """Explicit `fields=` script: the net IS `UnknownFieldError` (`fields=`'s
    keys are the superset source of truth, `ux/shared-script-rich-fields`) --
    the pre-existing coverage this test module cross-references, confirmed
    still reachable post-M19/typing-amendment (the call-recording layer is
    untouched by either change)."""
    from hassle.compiler import UnknownFieldError

    with pytest.raises(UnknownFieldError, match="untracked"):
        compile_bundle(FIXTURES / "shared_script_rich_fields_unknown_call_kwarg" / "bundle")


def test_caller_wrapper_source_is_untyped_any_kwargs() -> None:
    """Structural proof (not just the docstring claim above) that pyright's
    STATIC view of a call site is fully decoupled from the decorated
    function's own annotations: `caller`'s own SOURCE (what pyright actually
    type-checks a call site against -- pyright does static analysis on the
    literal `def caller(...)` text, it does NOT follow `__wrapped__` the way
    `inspect.signature()` does at runtime, which is precisely why the
    empirical pyright probe found zero diagnostics for a wrong kwarg
    name/type at a call site) is declared `*args: Any, **kwargs: Any) ->
    None`, with no `ParamSpec` anywhere in this module to propagate the
    decorated function's parameter types through the decorator. Read directly
    off `inspect.getsource` rather than `inspect.signature` (which DOES
    unwrap via `__wrapped__` at runtime -- a real, useful runtime-
    introspection fact, but not what pyright's static analysis sees)."""
    import inspect

    source = inspect.getsource(shared_script)
    assert "def caller(\n" in source
    assert "*args: Any," in source
    assert "**kwargs: Any," in source
    assert ") -> None:" in source
