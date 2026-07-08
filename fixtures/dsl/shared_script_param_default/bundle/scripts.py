"""Golden case (M19 test 2): `param_default(name)` is the escape hatch for
deliberate compile-time metaprogramming on a shared-script parameter -- the
declared default (from the signature), a plain Python value, NOT a
TemplateExpr. Unrolls `for _ in range(param_default("times")):` into that
many literal actions at compile time (the classic pattern `param()`'s
runtime-marker binding can no longer support, MILESTONES M19).
"""

from hassle import delay, service, shared_script
from hassle.compiler.scripts import param_default


@shared_script(id="flash_lights_unrolled", alias="Flash lights (unrolled)")
def flash_lights_unrolled(times: int = 3):
    for _ in range(param_default("times")):
        service("light.toggle", entity_id="light.all_downstairs")
        delay(seconds=1)
