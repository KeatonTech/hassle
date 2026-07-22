"""Integration smoke golden: >=15 distinct DSL constructs in one bundle.

Exercises the constructs the corpus needs, across three areas:

triggers/conditions:  purpose trigger on(...) with area target + behavior + for_,
                      numeric_state trigger, state() trigger with options,
                      all_of / not_ combinators, template condition
control-flow:         if_then / else_then, choose + default else_then, nested
                      repeat_count, parallel, wait_template
actions:              service (with response_variable), raw_action, fire_event,
                      variables, stop, shared-script call
templates/objects:    template expression (state(x).value > n), macro call,
                      helper declaration + reference, @shared_script

This is the core integration test: if the surfaces compose, it compiles.
"""

from hassle import (
    all_of,
    area,
    automation,
    choose,
    else_then,
    fire_event,
    if_then,
    input_boolean,
    input_number,
    macro,
    not_,
    numeric_state,
    on,
    only_if,
    parallel,
    param,
    raw_action,
    repeat_count,
    service,
    shared_script,
    state,
    stop,
    template,
    variables,
    wait_template,
    when,
)

# --- helper declarations (top-level objects) + references ------------------
GUEST_MODE = input_boolean(id="guest_mode", name="Guest Mode")
BRIGHTNESS = input_number(id="target_brightness", name="Target Brightness", min=0, max=255)


# --- a macro: compile-time inlined into the caller's action list -----------
@macro
def announce(message: str) -> None:
    service("notify.mobile_app", message=message)
    fire_event("hassle_announced", text=message)


# --- a shared script: emits a script object + a call verb ------------------
@shared_script(id="flash_lights", alias="Flash Lights")
def flash_lights(count: int = 3):
    service("light.toggle", target={"entity_id": "light.hallway"}, data={"count": param("count")})
    service("light.toggle", target={"entity_id": "light.hallway"})


@automation(id="kitchen_sink", alias="Kitchen sink integration", mode="restart")
def kitchen_sink():
    # multiple triggers: purpose + classic + state-with-options
    when(
        on("motion.detected", target=area("living_room"), behavior="first", for_={"minutes": 1}),
        numeric_state("sensor.temperature", above=25),
        state(GUEST_MODE).to("on", id="guest_on"),
    )
    # combinator + template condition
    only_if(
        all_of(
            not_(state("input_boolean.away").is_("on")),
            template("{{ now().hour >= 6 and now().hour < 23 }}"),
        )
    )

    variables(brightness_expr=state(BRIGHTNESS).value)

    # nested control flow: if/else with a template expression
    with if_then(state("sensor.temperature").value > 30):
        announce("It is hot")
        with repeat_count(2):
            service("fan.turn_on", target={"entity_id": "fan.living_room"})
    with else_then():
        flash_lights(count=2)

    # choose with when_ branches + a default
    with choose() as c:
        with c.when_(state("input_select.house_mode").is_("night")):
            service("light.turn_off", target={"entity_id": "light.all"})
        with c.default():
            service(
                "climate.get_forecast",
                target={"entity_id": "climate.living_room"},
                response_variable="forecast",
            )

    # parallel + wait + raw passthrough
    with parallel():
        service("switch.turn_on", target={"entity_id": "switch.porch"})
        wait_template("{{ is_state('binary_sensor.door', 'off') }}")
    raw_action({"delay": {"seconds": 5}})

    stop(message="done")
