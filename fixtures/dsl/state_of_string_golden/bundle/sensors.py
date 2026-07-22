"""Golden case: `state_of(...)` string-state vocabulary (DESIGN §5.4
extension). Exercises: bare string read, `.eq()`/`.ne()` string comparisons,
`.in_([...])` membership, boolean composition (`&`/`|`/`~`), and both
accepted argument shapes -- a plain entity id string and an `e.`-registry
ref (mirroring `expr()`'s own argument handling).
"""

from hassle import automation, expr, service, state, state_of, when
from hassle.registry import entities as e


@automation(id="string_state_demo", alias="String state expression demo")
def string_state_demo():
    when(state("binary_sensor.motion").to("on"))
    service(
        "notify.mobile_app",
        # bare string read
        raw_state=state_of("sensor.time_of_day"),
        # string equality, plain entity id arg
        is_daytime=state_of("sensor.time_of_day").eq("day"),
        # string inequality
        is_not_night=state_of("sensor.time_of_day").ne("night"),
        # membership
        is_transition=state_of("sensor.time_of_day").in_(["dawn", "dusk"]),
        # e.-registry ref argument (mirrors expr()'s accepted shapes)
        is_daytime_via_ref=state_of(e.sensor.time_of_day).eq("day"),
        # boolean and/or/not composition
        day_and_hot=state_of("sensor.time_of_day").eq("day") & (expr("sensor.outdoor_temp") > 25),
        dawn_or_dusk=state_of("sensor.time_of_day").eq("dawn")
        | state_of("sensor.time_of_day").eq("dusk"),
        not_night=~state_of("sensor.time_of_day").eq("night"),
    )
