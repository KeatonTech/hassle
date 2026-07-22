"""Golden case: `param()` is a composable Expr.

`param("sun_angle") / 360 * 2 * PI` inside a `@shared_script` body composes
exactly like any other TemplateExpr leaf.
"""

from hassle import service, shared_script
from hassle.compiler.math_expr import PI
from hassle.compiler.scripts import param


@shared_script(id="angle_calc", alias="Angle calc")
def angle_calc(sun_angle: float = 0):
    service(
        "input_number.set_value",
        entity_id="input_number.angle_radians",
        degrees=param("sun_angle") / 360 * 2 * PI,
    )
