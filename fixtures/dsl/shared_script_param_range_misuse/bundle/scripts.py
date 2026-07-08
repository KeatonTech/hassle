"""Error case (M19 test 2): `range(times)` on a bound shared-script parameter.

Since M19, `times` inside the body IS the runtime `param("times")` marker
(bound from the signature regardless of its declared default), not the
Python default -- `range(times)` can't honestly work at compile time. This
must fail loudly with an R6 what/where/fix error naming the `param_default()`
escape hatch, not a bare `TypeError` from deep inside `range()`.
"""

from hassle import delay, service, shared_script


@shared_script(id="flash_lights_range_misuse", alias="Flash lights (range misuse)")
def flash_lights_range_misuse(times: int = 3):
    for _ in range(times):
        service("light.toggle", entity_id="light.all_downstairs")
        delay(seconds=1)
