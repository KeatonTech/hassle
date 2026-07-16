"""Golden case: `shade_tracks_sun`.

Mirrors fixtures/configs/automation_math_shade_sun.json byte-for-byte in its
compiled `data.position` template -- this pins the math builder's exact
parenthesization and function-vs-filter choices (`state_attr`/`cos` as bare
function calls, `round_` as a `| round(0)` filter).
"""

from hassle import automation, numeric_state, only_if, service, time_pattern, when
from hassle.compiler.math_expr import PI, cos, round_
from hassle.registry import entities as e


@automation(id="shade_tracks_sun", alias="Shade Tracks Sun", mode="single")
def shade_tracks_sun():
    when(time_pattern(minutes="/5"))
    only_if(numeric_state(e.sun.sun, attribute="elevation", above=0))
    service(
        "cover.set_cover_position",
        target={"entity_id": "cover.living_room_shade"},
        position=round_(100 * cos(e.sun.sun.attr("elevation") * PI / 180), 0),
    )
