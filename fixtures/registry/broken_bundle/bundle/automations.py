"""M3 done-gate fixture: a purpose-built bundle with >= 25 DISTINCT seeded
mistakes, one per numbered comment below, covering every Finding type the M3
validator implements. Positions are varied deliberately: some in when(), some
in only_if(), some in service() calls, some inside template(...) strings, some
inside raw_trigger/raw_condition/raw_action.

This bundle must still COMPILE (the compiler doesn't know about the registry);
only `hassle.registry.validate.validate_bundle` flags these.
"""

from hassle import (
    area,
    automation,
    choose,
    device_id,
    else_then,
    floor,
    if_then,
    label,
    met,
    on,
    only_if,
    parallel,
    raw_action,
    raw_condition,
    raw_trigger,
    repeat_count,
    service,
    state,
    template,
    wait_for,
    when,
)

# --- automation 1: unknown entities in trigger / condition / action --------


@automation(id="broken_unknown_refs", alias="Broken: unknown refs")
def broken_unknown_refs():
    when(state("binary_sensor.does_not_exist_1").to("on"))  # 1: unknown entity in trigger
    only_if(state("input_boolean.does_not_exist_2").is_("on"))  # 2: unknown entity in condition
    service(
        "light.turn_on", target={"entity_id": "light.does_not_exist_3"}
    )  # 3: unknown entity in action target


# --- automation 2: did-you-mean-able typos ----------------------------------


@automation(id="broken_typos", alias="Broken: typos")
def broken_typos():
    when(state("binary_sensor.hal_motion").to("on"))  # 4: did-you-mean hall_motion
    service("light.turn_on", target={"entity_id": "light.halway"})  # 5: did-you-mean hallway


# --- automation 3: unknown entity inside a Jinja template string ------------


@automation(id="broken_template_refs", alias="Broken: template refs")
def broken_template_refs():
    when(
        template("{{ states('sensor.does_not_exist_4') | float > 10 }}")
    )  # 6: unknown entity inside template (states())
    only_if(
        template("{{ is_state('binary_sensor.does_not_exist_5', 'on') }}")
    )  # 7: unknown entity inside template (is_state())
    service(
        "notify.notify",
        target={"entity_id": "notify.phone"},
        message=template(
            "{{ state_attr('light.does_not_exist_6', 'brightness') }}"
        ),  # 8: unknown entity inside template (state_attr())
    )


# --- automation 4: unknown entity/device inside raw_* blocks ---------------


@automation(id="broken_raw_refs", alias="Broken: raw refs")
def broken_raw_refs():
    raw_trigger(
        {"trigger": "state", "entity_id": "binary_sensor.does_not_exist_7", "to": "on"}
    )  # 9: unknown entity inside raw_trigger
    raw_condition(
        {"condition": "state", "entity_id": "input_boolean.does_not_exist_8", "state": "on"}
    )  # 10: unknown entity inside raw_condition
    raw_action(
        {"action": "light.turn_on", "entity_id": "light.does_not_exist_9"}
    )  # 11: unknown entity inside raw_action
    raw_action(
        {
            "action": "light.turn_on",
            "target": {"entity_id": ["light.hallway", "light.does_not_exist_10"]},
        }
    )  # 12: unknown entity inside a raw target entity_id LIST form


# --- automation 5: purpose-vocabulary validation ----------------------------


@automation(id="broken_purpose_vocab", alias="Broken: purpose vocabulary")
def broken_purpose_vocab():
    when(on("nonsense.made_up_type_11"))  # 13: unknown purpose trigger type
    only_if(met("also_nonsense.made_up_12"))  # 14: unknown purpose condition type
    service("light.turn_on", target={"entity_id": "light.hallway"})


@automation(id="broken_renamed_purpose_key", alias="Broken: renamed purpose key")
def broken_renamed_purpose_key():
    when(
        on("battery.low", target="sensor.wireless_device_battery")
    )  # 15: renamed pre-2026.7 purpose key (battery.low -> battery.became_low)
    service("notify.mobile_app_kai", message="battery low")


# --- automation 6: unknown area / floor / label / device in purpose target --


@automation(id="broken_purpose_targets", alias="Broken: purpose targets")
def broken_purpose_targets():
    when(on("motion.detected", target=area("not_a_real_area_13")))  # 16: unknown area
    only_if(
        met("climate.is_target_temperature", target=floor("not_a_real_floor_14"))
    )  # 17: unknown floor
    service("light.turn_on", target={"entity_id": "light.hallway"})


@automation(id="broken_purpose_label_device", alias="Broken: purpose label + device")
def broken_purpose_label_device():
    when(on("motion.detected", target=label("not_a_real_label_15")))  # 18: unknown label
    only_if(state("input_boolean.armed").is_("on"))
    service(
        "notify.mobile_app_kai",
        message="event",
        # 19: unknown device target (purpose condition device target)
    )


@automation(id="broken_purpose_device_target", alias="Broken: purpose device target")
def broken_purpose_device_target():
    when(
        on("motion.detected", target=device_id("not_a_real_device_16"))
    )  # 19: unknown device_id in purpose target
    service("light.turn_on", target={"entity_id": "light.hallway"})


# --- automation 7: undeclared helper reference ------------------------------


@automation(id="broken_undeclared_helper", alias="Broken: undeclared helper")
def broken_undeclared_helper():
    when(
        state("input_boolean.totally_undeclared_17").to("on")
    )  # 20: undeclared helper reference (not in bundle, not in registry)
    service("light.turn_on", target={"entity_id": "light.hallway"})


# --- automation 8: service-call parameter validation ------------------------


@automation(id="broken_service_unknown_param", alias="Broken: unknown service param")
def broken_service_unknown_param():
    when(state("binary_sensor.hall_motion").to("on"))
    service(
        "light.turn_on",
        target={"entity_id": "light.hallway"},
        not_a_real_param_18=1,
    )  # 21: unknown service param


@automation(id="broken_service_wrong_type", alias="Broken: wrong service param type")
def broken_service_wrong_type():
    when(state("binary_sensor.hall_motion").to("on"))
    service(
        "light.turn_on",
        target={"entity_id": "light.hallway"},
        brightness_pct="not_a_number_19",
    )  # 22: wrong service param type (string instead of integer)


@automation(id="broken_service_missing_required", alias="Broken: missing required param")
def broken_service_missing_required():
    when(state("binary_sensor.hall_motion").to("on"))
    service(
        "notify.notify", target={"entity_id": "notify.phone"}, title="no message field"
    )  # 23: missing required service param (message)


@automation(id="broken_service_wrong_type_bool", alias="Broken: wrong bool param type")
def broken_service_wrong_type_bool():
    when(state("binary_sensor.hall_motion").to("on"))
    service(
        "automation.trigger",
        target={"entity_id": "automation.morning_lights"},
        skip_condition="not_a_bool_20",
    )  # 24: wrong service param type (string instead of boolean)


@automation(id="broken_service_wrong_type_float", alias="Broken: wrong float param type")
def broken_service_wrong_type_float():
    when(state("binary_sensor.hall_motion").to("on"))
    service(
        "climate.set_temperature",
        target={"entity_id": "climate.living_room"},
        temperature="not_a_float_21",
    )  # 25: wrong service param type (string instead of float)


# --- automation 9: more unknown-entity variety (mixed positions) -----------


@automation(id="broken_mixed_positions", alias="Broken: mixed positions")
def broken_mixed_positions():
    when(
        state("binary_sensor.hall_motion").to("on"),
        state("sensor.does_not_exist_22").to("changed"),
    )  # 26: unknown entity as the SECOND trigger in a multi-trigger when()
    only_if(
        state("input_boolean.armed").is_("on"),
        state("binary_sensor.does_not_exist_23").is_("off"),
    )  # 27: unknown entity as the SECOND condition in a multi-condition only_if()
    service("light.turn_on", target={"entity_id": "light.hallway"})
    raw_action(
        {
            "action": "light.turn_on",
            "target": {"area_id": "not_a_real_area_24"},
        }
    )  # 28: unknown area_id inside a raw action target
    raw_trigger(
        {
            "trigger": "motion.detected",
            "target": {"label_id": ["security", "not_a_real_label_25"]},
        }
    )  # 29: unknown label_id inside a raw trigger target LIST form


# --- automation 10: unknown entities nested inside control-flow containers -
# (reviewer B1) extraction/validation must recurse into if/choose/repeat/
# parallel/wait_for_trigger bodies, not just the top-level trigger/condition/
# action lists -- these seeds pin that blind spot shut for good.


@automation(id="broken_nested_if_then_else", alias="Broken: nested if/then/else")
def broken_nested_if_then_else():
    when(state("binary_sensor.hall_motion").to("on"))
    with if_then(state("sensor.temperature").is_("hot")):
        service(
            "light.turn_on", target={"entity_id": "light.does_not_exist_26"}
        )  # 30: unknown entity inside an if_then body
    with else_then():
        service(
            "light.turn_on", target={"entity_id": "light.does_not_exist_27"}
        )  # 31: unknown entity inside an else_then body


@automation(id="broken_nested_choose", alias="Broken: nested choose branch + default")
def broken_nested_choose():
    when(state("binary_sensor.hall_motion").to("on"))
    with choose() as c:
        with c.when_(state("input_select.house_mode").is_("night")):
            service(
                "light.turn_on", target={"entity_id": "light.does_not_exist_28"}
            )  # 32: unknown entity inside a choose() branch
        with c.default():
            service(
                "light.turn_on", target={"entity_id": "light.does_not_exist_29"}
            )  # 33: unknown entity inside a choose() default


@automation(id="broken_nested_repeat", alias="Broken: nested repeat body")
def broken_nested_repeat():
    when(state("binary_sensor.hall_motion").to("on"))
    with repeat_count(2):
        service(
            "light.turn_on", target={"entity_id": "light.does_not_exist_30"}
        )  # 34: unknown entity inside a repeat_count body


@automation(id="broken_nested_parallel", alias="Broken: nested parallel body")
def broken_nested_parallel():
    when(state("binary_sensor.hall_motion").to("on"))
    with parallel():
        service(
            "light.turn_on", target={"entity_id": "light.does_not_exist_31"}
        )  # 35: unknown entity inside a parallel() body


@automation(id="broken_nested_repeat_inside_choose", alias="Broken: repeat nested inside choose")
def broken_nested_repeat_inside_choose():
    when(state("binary_sensor.hall_motion").to("on"))
    with choose() as c:  # noqa: SIM117 - deliberately deep (repeat nested inside choose)
        with c.when_(state("input_boolean.armed").is_("on")):
            with repeat_count(2):
                service(
                    "light.turn_on", target={"entity_id": "light.does_not_exist_32"}
                )  # 36: unknown entity two levels deep (repeat inside choose)


@automation(id="broken_nested_wait_for_trigger", alias="Broken: wait_for_trigger inner trigger")
def broken_nested_wait_for_trigger():
    when(state("binary_sensor.hall_motion").to("on"))
    wait_for(
        state("binary_sensor.does_not_exist_33").to("off")
    )  # 37: unknown entity inside wait_for_trigger's inner trigger block
    service("light.turn_on", target={"entity_id": "light.hallway"})
