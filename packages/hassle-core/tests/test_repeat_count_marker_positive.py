"""M19 owner-blessed pattern: `repeat_count(times)` with a bound shared-script
parameter marker -- HA's native runtime repeat, honoring whatever the caller
actually passes (the honest alternative to the rejected `param_default()`
escape hatch, see `test_shared_script_real_params.py`).

`repeat_count`/`_repeat_cm` never coerces its argument (stores it verbatim as
``{"repeat": {"count": value, ...}}``), so the marker -- a `TemplateExpr`/
`str` subclass -- passes through untouched and renders as HA's own
template-count spelling.
"""

from __future__ import annotations

from pathlib import Path

from hassle.compiler import compile_bundle
from hassle.decompiler import decompile_bundle
from hassle.ir import sha256_hash

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "dsl"


def test_repeat_count_accepts_bound_marker_and_renders_template_count() -> None:
    result = compile_bundle(FIXTURES / "shared_script_repeat_count_marker" / "bundle")
    script_obj = result.objects["script:flash_lights_repeat"].to_ha()
    assert script_obj["sequence"][0]["repeat"]["count"] == "{{ times }}"


def test_repeat_count_marker_call_honors_caller_value() -> None:
    """A caller passing a DIFFERENT value than the field's declared default
    must see that value at runtime -- proof the marker-based `repeat_count`
    pattern (unlike the rejected `param_default()` escape hatch) never bakes
    in a stale compile-time default."""
    from hassle.testing import simulate

    sim = simulate(FIXTURES / "shared_script_call" / "bundle")
    # flash_lights's own default is times=3, but guest_arrived calls it with
    # times=5 -- the call's recorded data must carry the CALLER's value, not
    # the field's declared default (this is the general shared-script call
    # mechanism the repeat_count-with-marker pattern relies on: the count
    # only ever resolves inside HA at runtime, using whatever data the call
    # actually sent).
    sim.state_change("binary_sensor.guest_sensor", "off", "on")
    calls = sim.calls("script.flash_lights")
    assert len(calls) == 1
    assert calls[0].data["times"] == 5


def test_repeat_count_marker_decompiles_and_recompiles_byte_identical() -> None:
    obj = result_obj = compile_bundle(
        FIXTURES / "shared_script_repeat_count_marker" / "bundle"
    ).objects["script:flash_lights_repeat"]
    source = decompile_bundle({obj.object_key(): obj})
    assert "with repeat_count(times):" in source

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "scripts.py").write_text(source, encoding="utf-8")
        recompiled = compile_bundle(tmp)
    (recompiled_obj,) = recompiled.objects.values()
    assert sha256_hash(recompiled_obj.to_ha()) == sha256_hash(result_obj.to_ha())
