"""Golden case: stop/variables/fire_event/service action primitives.

``fire_event`` is the fire-event *action* (distinct from the ``event`` trigger
builder); ``response_variable``/``continue_on_error`` are folded into ``service``
(there is no separate ``service_ext``).
"""

from hassle import automation, fire_event, service, state, stop, variables, when


@automation(id="misc_primitives", alias="Misc action primitives")
def misc_primitives():
    when(state("binary_sensor.trigger").to("on"))
    variables(greeting="hello", count=3)
    fire_event("hassle_custom_event", room="hallway", level=2)
    service(
        "climate.get_forecast",
        target={"entity_id": "climate.living_room"},
        response_variable="forecast",
    )
    service(
        "notify.mobile_app",
        message="done",
        continue_on_error=True,
    )
    # response_variable= (ux/script-responses): the named run variable's
    # value becomes the script/automation response (HA script responses).
    stop(message="all done", error=False, response_variable="greeting")
