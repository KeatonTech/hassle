"""Golden case (M19, owner-blessed pattern): a runtime repeat count on a
shared-script parameter belongs in `repeat_count(...)`, HA's own native
runtime repeat -- not compile-time metaprogramming (`range(...)`, rejected as
an anti-pattern, see `shared_script_param_range_misuse`'s error case).

`repeat_count` never coerces its argument (`hassle.compiler.control_flow`'s
`_repeat_cm` stores it verbatim as `{"repeat": {"count": value, ...}}`), so
the bound `times` marker -- a `TemplateExpr`/`str` subclass -- passes through
untouched and renders as HA's own template-count spelling,
`{"count": "{{ times }}"}`, honoring whatever the caller actually passes at
runtime (unlike the rejected `param_default()` escape hatch, which would have
baked the DECLARED default in once, forever, regardless of the caller).
"""

from hassle import delay, repeat_count, service, shared_script


@shared_script(id="flash_lights_repeat", alias="Flash lights (repeat)")
def flash_lights_repeat(times: int = 3):
    with repeat_count(times):
        service("light.toggle", entity_id="light.all_downstairs")
        delay(seconds=1)
