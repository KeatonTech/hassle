"""Golden case: deep nesting — if inside repeat inside choose.

Exercises the recording-context stack to three levels deep: `choose()`'s
`when_` branch contains a `repeat_count`, which itself contains an `if_then`.
Also the case pinned by test_span_depth_empirical.py for span depth=2 at
every nesting level.
"""

from hassle import automation, choose, if_then, repeat_count, service, state, when


@automation(id="deep_nesting", alias="Deep nesting")
def deep_nesting():
    when(state("binary_sensor.trigger").to("on"))
    with choose() as c:  # noqa: SIM117 - deliberately deep for the golden case
        with c.when_(state("input_boolean.armed").is_("on")):
            with repeat_count(2):
                with if_then(state("sensor.temperature").is_("above_25")):
                    service("light.turn_on", target={"entity_id": "light.hallway"})
