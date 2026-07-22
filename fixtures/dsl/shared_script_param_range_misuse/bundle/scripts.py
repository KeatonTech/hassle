"""Error case: `range(times)` on a bound shared-script parameter.

`times` inside the body IS the runtime `param("times")` marker
(bound from the signature regardless of its declared default), not the
Python default -- `range(times)` can't honestly work at compile time. This
must fail loudly with a what/where/fix error teaching the honest
alternatives (a `param_default()` escape hatch was considered and rejected
for baking a stale compile-time value into the compiled
sequence while the field still exists): `with repeat_count(times):` for a
genuinely runtime count (see `shared_script_repeat_count_marker` for that
blessed pattern's own golden case), or a module constant / `@macro` argument
for a genuinely compile-time one.
"""

from hassle import delay, service, shared_script


@shared_script(id="flash_lights_range_misuse", alias="Flash lights (range misuse)")
def flash_lights_range_misuse(times: int = 3):
    for _ in range(times):
        service("light.toggle", entity_id="light.all_downstairs")
        delay(seconds=1)
