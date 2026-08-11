"""Golden case: blueprint_dsl_authored (docs/internals/blueprints-design.md §8).

A blueprint AUTHORED IN THE DSL. Stage 1's golden (`blueprint_managed_object`)
pins a hand-written blueprint FILE becoming a managed object; this one pins the
stage-2 inversion — there is no file, and `BlueprintConfig.source` in
`expected_ir.json` is the emitted YAML, byte for byte.

That makes this fixture the determinism gate (§8.6): declaration order for the
inputs, the fixed metadata and section order, the `!input` tags in plain style,
and the header naming the Python source. Any drift in the emitter shows up here
as a golden diff rather than as a surprise in somebody's Home Assistant.
"""

from hassle import blueprint, bp_input, service, state, when


@blueprint(
    domain="automation",
    path="local/room-switch-controls.yaml",
    name="Room switch controls",
    description="Tap a wall switch to drive a room's light.",
    mode="restart",
)
def room_switch_controls():
    switch_entity = bp_input(
        "switch_entity",
        selector={"entity": {"filter": [{"domain": "sensor"}]}},
        description="The wall switch that drives this room.",
    )
    room_light = bp_input(
        "room_light",
        selector={"entity": {"filter": [{"domain": "light"}]}},
    )
    dim_step_pct = bp_input(
        "dim_step_pct",
        selector={"number": {"min": 1, "max": 100}},
        default=10,
    )
    when(state(switch_entity).to("on"))
    service(
        "light.turn_on",
        target={"entity_id": room_light},
        brightness_step_pct=dim_step_pct,
    )
