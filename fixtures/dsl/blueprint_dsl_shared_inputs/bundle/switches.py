"""Golden case: blueprint_dsl_shared_inputs (blueprints-design §8.2, §8.11).

The sibling of `blueprint_dsl_authored`, which pins the single-blueprint,
inputs-declared-in-the-body shape. This one pins everything that shape could
not express, and it is the determinism gate for all of it:

- **A module-scope declaration shared by two blueprints.** `room_light` is
  declared once and used by both documents. HA's `!input` namespace is
  per-document, so each emitted YAML carries its own full entry with the shared
  metadata — sharing is a source-level convenience, never a cross-document
  reference. Read the two documents' `room_light` entries against each other.
- **Membership by use.** Neither document mentions the other's paddle or step
  size: each `input:` block contains exactly what its own triggers and actions
  reach, out of the five declared here.
- **Order by declaration, not by first use.** Every declaration order here is
  deliberately the REVERSE of first-use order. `tap_up_brighter` mentions
  `button_up` first (in its decorator trigger), then `room_light`, then
  `step_up_pct` — and emits them in exactly the opposite arrangement, because
  the emitted block follows the module's declaration sequence. Sorting by use
  would mean moving a service call reorders the form Home Assistant renders for
  every user of the blueprint.
- **Decorator triggers (§8.11).** Both bodies are pure action sequences: the
  subscription lives in `triggers=`, evaluated at decoration time, and names
  module-scope inputs freely — which is the whole reason module-scope
  declarations exist.
- **The sugar that retired `raw_trigger` here.** `not_from`/`not_to` on the
  state trigger (an event entity's state is the timestamp of its last press, so
  a real press is "any change except the platform's own restart shuffle"), and
  `for_` on the template trigger.
"""

from hassle import blueprint, bp_input, minutes, service, state, template

# Declaration ORDER is the whole point of this fixture: it, and nothing else,
# orders each emitted `input:` block. Read the two documents in expected_ir.json
# against this list, not against the bodies below.
ROOM_LIGHT = bp_input(
    "room_light",
    selector={"entity": {"filter": [{"domain": "light"}]}},
    description="The light this switch owns.",
)
STEP_UP_PCT = bp_input(
    "step_up_pct",
    selector={"number": {"min": 1, "max": 100}},
    default=10,
    description="How far one tap of the upper paddle brightens.",
)
STEP_DOWN_PCT = bp_input(
    "step_down_pct",
    selector={"number": {"min": -100, "max": -1}},
    default=-10,
    description="How far one tap of the lower paddle dims.",
)
BUTTON_UP = bp_input(
    "button_up",
    selector={"entity": {"filter": [{"domain": "event"}]}},
    description="The switch's upper paddle.",
)
BUTTON_DOWN = bp_input(
    "button_down",
    selector={"entity": {"filter": [{"domain": "event"}]}},
    description="The switch's lower paddle.",
)

#: Reject only what the platform generates by itself: an `unavailable` origin,
#: an unknown/unavailable destination. `unknown -> timestamp` IS a real press
#: (the first one after a reconnect), so it must not be filtered out.
NOT_A_PRESS_FROM = ["unavailable"]
NOT_A_PRESS_TO = ["unknown", "unavailable"]


@blueprint(
    domain="automation",
    path="local/tap-up-brighter.yaml",
    name="Tap up: brighter",
    description="One tap of the upper paddle steps this room's light up.",
    mode="restart",
    triggers=[
        state(BUTTON_UP).with_options(not_from=NOT_A_PRESS_FROM, not_to=NOT_A_PRESS_TO),
    ],
)
def tap_up_brighter():
    service(
        "light.turn_on",
        target={"entity_id": ROOM_LIGHT},
        brightness_step_pct=STEP_UP_PCT,
    )


@blueprint(
    domain="automation",
    path="local/tap-down-dimmer.yaml",
    name="Tap down: dimmer",
    description="One tap of the lower paddle steps this room's light down.",
    mode="restart",
    triggers=[
        state(BUTTON_DOWN).with_options(not_from=NOT_A_PRESS_FROM, not_to=NOT_A_PRESS_TO),
        # A second trigger of a different shape, here to pin the template
        # trigger's own `for_` in a golden: the lux sensor has read unavailable
        # for two minutes, so dim rather than trust it.
        template("{{ states('sensor.room_lux') | float(-1) < 0 }}", for_=minutes(2)),
    ],
)
def tap_down_dimmer():
    service(
        "light.turn_on",
        target={"entity_id": ROOM_LIGHT},
        brightness_step_pct=STEP_DOWN_PCT,
    )
