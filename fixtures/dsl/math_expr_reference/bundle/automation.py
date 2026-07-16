"""Golden case: `math_expr_reference`.

`shade_tracks_sun` already goldens `cos`/`round_`/`PI`; this fixture exists
purely so **every remaining** `hassle.compiler.math_expr` builder has a real
DSL<->compiled-YAML golden pair backing its docs/DSL.md section (the docs
build fails if any `hassle.__all__` name lacks a documented pair) --
`sin`/`tan`/`asin`/`acos`/`atan`/`atan2`/`sqrt`/`log`/
`abs_`/`min_`/`max_`, the `E_`/`TAU` constants, the datetime helpers
(`as_datetime`/`as_timestamp`/`today_at`/`timedelta_`), `var`, and `concat`.
One `variables` action is the natural place to exercise a batch of
independent template expressions at once (DESIGN §5.4's math-expression
extension; docs/dsl-extensions.md "Runtime-math expression surface").
"""

from hassle import (
    E_,
    TAU,
    abs_,
    acos,
    as_datetime,
    as_timestamp,
    asin,
    atan,
    atan2,
    automation,
    concat,
    log,
    max_,
    min_,
    sin,
    sqrt,
    tan,
    time_pattern,
    timedelta_,
    today_at,
    var,
    variables,
    when,
)


@automation(id="math_expr_reference", alias="Math expr reference", mode="single")
def math_expr_reference():
    when(time_pattern(minutes="/5"))
    variables(
        trig=sin(var("angle")) + tan(var("angle")),
        inverse_trig=asin(var("ratio")) + acos(var("ratio")) + atan(var("ratio")),
        angle_from_slopes=atan2(var("dy"), var("dx")),
        magnitude=sqrt(var("x") * var("x") + var("y") * var("y")),
        log_value=log(var("x")),
        abs_value=abs_(var("delta")),
        smallest=min_(var("a"), var("b"), var("c")),
        largest=max_(var("a"), var("b"), var("c")),
        eulers_number=E_,
        full_turn=TAU,
        parsed_time=as_datetime(var("wakeup_time")),
        epoch_seconds=as_timestamp(var("event_time")),
        six_thirty=today_at("06:30:00"),
        half_hour=timedelta_(minutes=30),
        wakeup_plus_offset=today_at("06:30:00") + timedelta_(minutes=30),
        joined_label=concat("Room ", var("room_name"), " is ready"),
    )
