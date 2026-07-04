"""Golden case: stop/variables/event/service_ext action primitives."""

from hassle import automation, event, service_ext, state, stop, variables, when


@automation(id="misc_primitives", alias="Misc action primitives")
def misc_primitives():
    when(state("binary_sensor.trigger").to("on"))
    variables(greeting="hello", count=3)
    event("hassle_custom_event", room="hallway", level=2)
    service_ext(
        "climate.get_forecast",
        target={"entity_id": "climate.living_room"},
        response_variable="forecast",
    )
    service_ext(
        "notify.mobile_app",
        message="done",
        continue_on_error=True,
    )
    stop(message="all done", error=False)
