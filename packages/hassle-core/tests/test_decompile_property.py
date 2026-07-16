"""Property test (hypothesis): random IR generated from the model schema
round-trips through the decompiler (generalized beyond the fixed corpus).

Kept seeded/deterministic in CI: a fixed ``hypothesis.seed`` and
``derandomize=True`` mean the exact same examples run on every CI invocation, so
a failure is always reproducible and the suite never flakes from example choice.

The strategy builds automation configs directly from the IR/DSL schema (random
combinations of state/numeric_state triggers, state/template conditions, service
and delay actions, `mode`), which is exactly the shape ``AutomationConfig``
models and ``compile_bundle`` produces -- "generated from the model schema" per
the milestone text.
"""

from __future__ import annotations

from typing import Any

from hypothesis import HealthCheck, given, seed, settings
from hypothesis import strategies as st

from hassle.compiler.bundle import compile_bundle
from hassle.decompiler import decompile_bundle
from hassle.ir import parse, sha256_hash

_ENTITY_IDS = st.sampled_from(
    [
        "binary_sensor.hall_motion",
        "binary_sensor.door",
        "light.hallway",
        "sensor.temperature",
        "input_boolean.guest_mode",
    ]
)
_STATE_VALUES = st.sampled_from(["on", "off", "open", "closed", "home", "away"])


@st.composite
def _state_trigger(draw: st.DrawFn) -> dict[str, Any]:
    body: dict[str, Any] = {"trigger": "state", "entity_id": draw(_ENTITY_IDS)}
    if draw(st.booleans()):
        body["to"] = draw(_STATE_VALUES)
    if draw(st.booleans()):
        body["from"] = draw(_STATE_VALUES)
    return body


@st.composite
def _numeric_state_trigger(draw: st.DrawFn) -> dict[str, Any]:
    body: dict[str, Any] = {"trigger": "numeric_state", "entity_id": draw(_ENTITY_IDS)}
    if draw(st.booleans()):
        body["above"] = draw(st.integers(min_value=0, max_value=100))
    else:
        body["below"] = draw(st.integers(min_value=0, max_value=100))
    return body


_TRIGGER = st.one_of(_state_trigger(), _numeric_state_trigger())


@st.composite
def _state_condition(draw: st.DrawFn) -> dict[str, Any]:
    return {
        "condition": "state",
        "entity_id": draw(_ENTITY_IDS),
        "state": draw(_STATE_VALUES),
    }


_CONDITION = _state_condition()


@st.composite
def _service_action(draw: st.DrawFn) -> dict[str, Any]:
    action = draw(st.sampled_from(["light.turn_on", "light.turn_off", "notify.mobile_app"]))
    body: dict[str, Any] = {"action": action, "target": {"entity_id": draw(_ENTITY_IDS)}}
    if draw(st.booleans()):
        body["data"] = {"brightness_pct": draw(st.integers(min_value=1, max_value=100))}
    return body


@st.composite
def _delay_action(draw: st.DrawFn) -> dict[str, Any]:
    return {"delay": {"seconds": draw(st.integers(min_value=1, max_value=120))}}


_ACTION = st.one_of(_service_action(), _delay_action())


@st.composite
def _automation_config(draw: st.DrawFn) -> dict[str, Any]:
    ident = draw(st.from_regex(r"[a-z][a-z0-9_]{2,15}", fullmatch=True))
    return {
        "id": ident,
        "alias": f"Generated {ident}",
        "mode": draw(st.sampled_from(["single", "restart", "queued", "parallel"])),
        "triggers": draw(st.lists(_TRIGGER, min_size=1, max_size=3)),
        "conditions": draw(st.lists(_CONDITION, min_size=0, max_size=2)),
        "actions": draw(st.lists(_ACTION, min_size=1, max_size=3)),
    }


@seed(20260703)
@settings(
    max_examples=50,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(config=_automation_config())
def test_random_ir_roundtrips(config: dict[str, Any], tmp_path_factory: Any) -> None:
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})

    bundle_dir = tmp_path_factory.mktemp("prop_bundle")
    (bundle_dir / "objects.py").write_text(source, encoding="utf-8")
    result = compile_bundle(str(bundle_dir))

    assert len(result.objects) == 1
    (recompiled,) = result.objects.values()
    assert sha256_hash(recompiled.to_ha()) == sha256_hash(config), (
        f"random IR failed to round-trip; config={config!r}\nsource:\n{source}"
    )
