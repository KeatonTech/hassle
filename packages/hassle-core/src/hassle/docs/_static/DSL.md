# docs/DSL.md — Hassle DSL reference

**Generated** by `hassle.docs.dsl_reference.generate_dsl_reference` from the golden
fixtures under `fixtures/dsl/` — every section below is sourced directly from a real,
compiler-verified DSL<->compiled-YAML pair, so this file can never drift from what
`hassle` actually does. Do not hand-edit; regenerate via `hassle-dev docs --update`
(golden files are regenerated, never hand-edited — same discipline as `hassle-dev
goldens --update`).

Agents and humans alike: pattern-match on the pair (DESIGN §12) — the Python on top,
the exact compiled shape HA stores underneath.

## Validator coverage boundaries

Two `hassle validate` checks are deliberately permissive rather than strict (from
`hassle.registry.validate`'s own docstring, verbatim intent — kept in sync here so
it can't drift):

- A service whose schema has an empty `fields: {}` is never checked for
  unknown/wrong-type params (an incomplete schema capture looks identical to "this
  service genuinely takes no parameters").
- A bare `entity_id=` kwarg to `service(...)` is never flagged as an "unknown
  service param" (HA's own legacy target shorthand and an intentional data field
  merge into the same `data` dict with no residual marker of which one it started
  as).

Everything else is strict: an unrecognized entity/area/floor/label/device id,
purpose-vocabulary type, or (non-empty-schema) service param always produces a
Finding.

## One-way expression sugar

The template expression builder (`expr`/math builders/operators) is **one-way
sugar**: the decompiler always reconstructs a compiled Jinja string as a raw
`template("...")` string. It never re-derives the operator/builder call chain
(`cos(...)`, `.attr(...)`, comparisons, ...) that produced it. This is a deliberate
simplification (dsl-extensions.md), not a bug — round-tripping still holds
(compile(decompile(x)) == x) because
`template(...)` is itself a first-class, fully-supported DSL construct.

## Scripts-as-functions: when a call rewrites vs. stays `service(...)`

Calling a `@shared_script`-decorated function elsewhere in the bundle records a
`script.<id>`-style call action (DESIGN §5.6), not a re-run of the script's body.
On decompile, the reverse rewrite (a stored `script.<id>` action becomes a real
Python call to the generated wrapper function) only applies when the call site's
`metadata`/`alias`/`enabled`/field kwargs can be represented by that wrapper's
accepted keywords; anything the wrapper doesn't understand falls back to a plain
`service("script.<id>", ...)` action instead of a rewritten call, so no data is
ever silently dropped.

## Category-first file placement

The decompiler only decides file placement for an object it has never seen before:
its default is one **root-level, mixed-kind** file per HA UI category —
`<slug(category)>.py`, from the object's OWN entity-registry category (automations
and scripts each have their own category-registry scope; every helper kind shares
one scope, `"helpers"` — a category named "HVAC" puts the HVAC automation, the
HVAC script, and the HVAC helpers all in the SAME `hvac.py`) — else the single
shared `misc.py` for every uncategorized object of every kind. After that first
placement, **file organization is entirely user-controlled** — an object always
stays in whatever file the user puts it in (tracked by the manifest), never
auto-moved.

An optional module-level `CATEGORY: str = "Automatic HVAC"` in a category-shaped
file supplies the *exact* display name Hassle uses if it ever has to create that
category fresh in HA (an acronym or punctuation choice a slug can't recover, e.g.
`"HVAC"` from `automatic_hvac.py`) — `slugify(CATEGORY)` must equal the file's own
stem, or `hassle validate` flags it and `hassle push` ignores the global (falling
back to a slug-derived guess) rather than guessing which side is right. It is
consulted ONLY when push has to CREATE a brand-new category; matching an existing
HA category is always slug-based, and an existing category is never renamed by
push (the HA UI owns renames). `hassle pull` writes this line itself whenever it
creates a new category file, so display names round-trip through source; refreshing
an already-existing file never duplicates or moves the line.

### A category can be a package, not just a file

A category's source may be a **Python package** instead of a single file: a
root-level directory holding an `__init__.py`. Every module inside it
(recursively) is attributed to ONE category — the package's own name — exactly
as if every object had been declared in a single root-level `<slug>.py`:

```
automatic_hvac/          <- the category is `automatic_hvac`
    __init__.py
    climate.py           <- objects here...
    prompts.py           <- ...and here...
    holds.py             <- ...all tag as `automatic_hvac`
lib/                     <- no __init__.py: ordinary support code, uncategorized
    helpers.py
```

This is for splitting one large area across several files without inventing a
category per file. Splitting is a pure reorganization: the same objects compile
to byte-identical IR either way.

`__init__.py` is the opt-in marker and the only discriminator, so `lib/`,
`tests/`, `docs/` and dot-directories keep behaving exactly as before — an
existing bundle cannot change behaviour until someone adds one deliberately. A
`CATEGORY` global inside a package module is anchored to the PACKAGE's name
(`slugify(CATEGORY)` must equal the package's own name). A package and a
same-named root-level file (`automatic_hvac/` and `automatic_hvac.py`) both
claiming one category is a compile-time error rather than a silent coin flip.

## Upgrade / plan-labeling note

`hassle push`ing a legacy-form remote object (inner `platform:`, scalar `delay:`,
...) that was previously adopted produces a ONE-TIME "modernization" diff: Hassle
compiles the modern plural/dict form, and HA stores it verbatim thereafter, so the
very next plan is clean. The plan renderer labels this diff class
`modernization (one-time)` specifically so it doesn't read as an unexpected,
recurring drift.

## Trap / error surface

Every compile-time trap below is an exception class in `hassle.__all__`, assertable
by bundles and tests. These don't compile to an HA YAML shape — the error text
*is* the documentation.


### `Mode`

Golden case: `fixtures/dsl/mode_enum_parity/`.

```python
"""Golden case: `Mode`/`MaxExceeded` StrEnum form --
`StrEnum` IS a `str` subclass, so passing a member compiles byte-identical to the
equivalent plain string. Paired with `mode_str_parity/`'s plain-string form to
prove compile parity.
"""

from hassle import MaxExceeded, Mode, automation, service, state, when


@automation(
    id="hall_light_on_motion",
    alias="Hallway: light on motion",
    mode=Mode.RESTART,
    max_exceeded=MaxExceeded.SILENT,
)
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", entity_id="light.hallway")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:hall_light_on_motion": {
    "actions": [
      {
        "action": "light.turn_on",
        "data": {
          "entity_id": "light.hallway"
        }
      }
    ],
    "alias": "Hallway: light on motion",
    "conditions": [],
    "id": "hall_light_on_motion",
    "max_exceeded": "silent",
    "mode": "restart",
    "triggers": [
      {
        "entity_id": "binary_sensor.hall_motion",
        "to": "on",
        "trigger": "state"
      }
    ]
  }
}
```

### `MaxExceeded`

Golden case: `fixtures/dsl/mode_enum_parity/`.

```python
"""Golden case: `Mode`/`MaxExceeded` StrEnum form --
`StrEnum` IS a `str` subclass, so passing a member compiles byte-identical to the
equivalent plain string. Paired with `mode_str_parity/`'s plain-string form to
prove compile parity.
"""

from hassle import MaxExceeded, Mode, automation, service, state, when


@automation(
    id="hall_light_on_motion",
    alias="Hallway: light on motion",
    mode=Mode.RESTART,
    max_exceeded=MaxExceeded.SILENT,
)
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", entity_id="light.hallway")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:hall_light_on_motion": {
    "actions": [
      {
        "action": "light.turn_on",
        "data": {
          "entity_id": "light.hallway"
        }
      }
    ],
    "alias": "Hallway: light on motion",
    "conditions": [],
    "id": "hall_light_on_motion",
    "max_exceeded": "silent",
    "mode": "restart",
    "triggers": [
      {
        "entity_id": "binary_sensor.hall_motion",
        "to": "on",
        "trigger": "state"
      }
    ]
  }
}
```

### `PI`

Golden case: `fixtures/dsl/shade_tracks_sun/`.

```python
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
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:shade_tracks_sun": {
    "actions": [
      {
        "action": "cover.set_cover_position",
        "data": {
          "position": "{{ (100 * cos(state_attr('sun.sun', 'elevation') * pi / 180)) | round(0) }}"
        },
        "target": {
          "entity_id": "cover.living_room_shade"
        }
      }
    ],
    "alias": "Shade Tracks Sun",
    "conditions": [
      {
        "above": 0,
        "attribute": "elevation",
        "condition": "numeric_state",
        "entity_id": "sun.sun"
      }
    ],
    "id": "shade_tracks_sun",
    "mode": "single",
    "triggers": [
      {
        "minutes": "/5",
        "trigger": "time_pattern"
      }
    ]
  }
}
```

See also: `fixtures/dsl/math_expr_reference/`

### `E_`

Golden case: `fixtures/dsl/math_expr_reference/`.

```python
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
extension; docs/internals/dsl-extensions.md "Runtime-math expression surface").
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
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:math_expr_reference": {
    "actions": [
      {
        "variables": {
          "abs_value": "{{ delta | abs }}",
          "angle_from_slopes": "{{ atan2(dy, dx) }}",
          "epoch_seconds": "{{ as_timestamp(event_time) }}",
          "eulers_number": "{{ e }}",
          "full_turn": "{{ tau }}",
          "half_hour": "{{ timedelta(minutes=30) }}",
          "inverse_trig": "{{ asin(ratio) + acos(ratio) + atan(ratio) }}",
          "joined_label": "{{ 'Room ' ~ room_name ~ ' is ready' }}",
          "largest": "{{ [a, b, c] | max }}",
          "log_value": "{{ log(x) }}",
          "magnitude": "{{ sqrt(x * x + y * y) }}",
          "parsed_time": "{{ as_datetime(wakeup_time) }}",
          "six_thirty": "{{ today_at('06:30:00') }}",
          "smallest": "{{ [a, b, c] | min }}",
          "trig": "{{ sin(angle) + tan(angle) }}",
          "wakeup_plus_offset": "{{ today_at('06:30:00') + timedelta(minutes=30) }}"
        }
      }
    ],
    "alias": "Math expr reference",
    "conditions": [],
    "id": "math_expr_reference",
    "mode": "single",
    "triggers": [
      {
        "minutes": "/5",
        "trigger": "time_pattern"
      }
    ]
  }
}
```

### `TAU`

Golden case: `fixtures/dsl/math_expr_reference/`.

```python
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
extension; docs/internals/dsl-extensions.md "Runtime-math expression surface").
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
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:math_expr_reference": {
    "actions": [
      {
        "variables": {
          "abs_value": "{{ delta | abs }}",
          "angle_from_slopes": "{{ atan2(dy, dx) }}",
          "epoch_seconds": "{{ as_timestamp(event_time) }}",
          "eulers_number": "{{ e }}",
          "full_turn": "{{ tau }}",
          "half_hour": "{{ timedelta(minutes=30) }}",
          "inverse_trig": "{{ asin(ratio) + acos(ratio) + atan(ratio) }}",
          "joined_label": "{{ 'Room ' ~ room_name ~ ' is ready' }}",
          "largest": "{{ [a, b, c] | max }}",
          "log_value": "{{ log(x) }}",
          "magnitude": "{{ sqrt(x * x + y * y) }}",
          "parsed_time": "{{ as_datetime(wakeup_time) }}",
          "six_thirty": "{{ today_at('06:30:00') }}",
          "smallest": "{{ [a, b, c] | min }}",
          "trig": "{{ sin(angle) + tan(angle) }}",
          "wakeup_plus_offset": "{{ today_at('06:30:00') + timedelta(minutes=30) }}"
        }
      }
    ],
    "alias": "Math expr reference",
    "conditions": [],
    "id": "math_expr_reference",
    "mode": "single",
    "triggers": [
      {
        "minutes": "/5",
        "trigger": "time_pattern"
      }
    ]
  }
}
```

### `automation`

Golden case: `fixtures/dsl/state_delay_service/`.

```python
"""Golden case: state trigger + delay + service call.

Exercises the one end-to-end trigger builder (`state(...).to(...)`), the first
action primitive (`delay`), and a service-call action with kwargs.
"""

from hassle import automation, delay, service, state, when


@automation(id="hall_light_on_motion", alias="Hallway: light on motion", mode="restart")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", entity_id="light.hallway", brightness_pct=60)
    delay(minutes=5)
    service("light.turn_off", entity_id="light.hallway")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:hall_light_on_motion": {
    "actions": [
      {
        "action": "light.turn_on",
        "data": {
          "brightness_pct": 60,
          "entity_id": "light.hallway"
        }
      },
      {
        "delay": {
          "minutes": 5
        }
      },
      {
        "action": "light.turn_off",
        "data": {
          "entity_id": "light.hallway"
        }
      }
    ],
    "alias": "Hallway: light on motion",
    "conditions": [],
    "id": "hall_light_on_motion",
    "mode": "restart",
    "triggers": [
      {
        "entity_id": "binary_sensor.hall_motion",
        "to": "on",
        "trigger": "state"
      }
    ]
  }
}
```

See also: `fixtures/dsl/kitchen_sink_full/`

### `script`

Golden case: `fixtures/dsl/standalone_scripts/`.

```python
"""Golden case: standalone @script objects (DESIGN §5.7).

Covers the three script_*.json corpus shapes:
- a basic script (bare sequence),
- a script with mode=queued + max,
- a script with a full `fields` mapping carrying name/description/example/
  default metadata (authored explicitly via fields=, since a plain @script's
  fields are not derived from a signature — that's @shared_script's job).
"""

from hassle import delay, script, service


@script(id="basic_greet", alias="Basic Greet")
def basic_greet():
    service("notify.mobile_app", message="hello")


@script(id="queued_worker", alias="Queued Worker", mode="queued", max=10)
def queued_worker():
    service("switch.turn_on", target={"entity_id": "switch.pump"})
    delay(seconds=5)
    service("switch.turn_off", target={"entity_id": "switch.pump"})


@script(
    id="script_with_fields",
    alias="Script With Fields",
    description="A script with input fields for parameters",
    fields={
        "light_entity": {
            "name": "Light Entity",
            "description": "The light to control",
            "example": "light.bedroom",
        },
        "brightness": {
            "name": "Brightness",
            "description": "Brightness level 0-255",
            "example": 200,
            "default": 255,
        },
    },
)
def script_with_fields():
    service(
        "light.turn_on",
        target={"entity_id": "{{ light_entity }}"},
        data={"brightness": "{{ brightness }}"},
    )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "script:basic_greet": {
    "alias": "Basic Greet",
    "sequence": [
      {
        "action": "notify.mobile_app",
        "data": {
          "message": "hello"
        }
      }
    ]
  },
  "script:queued_worker": {
    "alias": "Queued Worker",
    "max": 10,
    "mode": "queued",
    "sequence": [
      {
        "action": "switch.turn_on",
        "target": {
          "entity_id": "switch.pump"
        }
      },
      {
        "delay": {
          "seconds": 5
        }
      },
      {
        "action": "switch.turn_off",
        "target": {
          "entity_id": "switch.pump"
        }
      }
    ]
  },
  "script:script_with_fields": {
    "alias": "Script With Fields",
    "description": "A script with input fields for parameters",
    "fields": {
      "brightness": {
        "default": 255,
        "description": "Brightness level 0-255",
        "example": 200,
        "name": "Brightness"
      },
      "light_entity": {
        "description": "The light to control",
        "example": "light.bedroom",
        "name": "Light Entity"
      }
    },
    "sequence": [
      {
        "action": "light.turn_on",
        "data": {
          "brightness": "{{ brightness }}"
        },
        "target": {
          "entity_id": "{{ light_entity }}"
        }
      }
    ]
  }
}
```

### `shared_script`

Golden case: `fixtures/dsl/shared_script_call/`.

```python
"""Golden case: @shared_script compiles to a script object AND a call action
(DESIGN §5.6).

`flash_lights` becomes a real HA script (fields derived from the signature,
defaults -> field defaults) whose sequence references `param("times")` and
`param("brightness")` as runtime template reads. The caller automation's
action list gets a `script.turn_on`-style call action (matching the corpus
script-call shape), never a re-run of the body.
"""

from hassle import automation, param, service, shared_script, state, when


@shared_script(id="flash_lights", alias="Flash lights", icon="mdi:alarm-light")
def flash_lights(times: int = 3, brightness: int = 255):
    service(
        "light.turn_on",
        entity_id="light.all_downstairs",
        brightness=param("brightness"),
    )
    service("light.turn_off", entity_id="light.all_downstairs")


@automation(id="guest_arrived", alias="Guest arrived")
def guest_arrived():
    when(state("binary_sensor.guest_sensor").to("on"))
    flash_lights(times=5, brightness=128)
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:guest_arrived": {
    "actions": [
      {
        "action": "script.flash_lights",
        "data": {
          "brightness": 128,
          "times": 5
        }
      }
    ],
    "alias": "Guest arrived",
    "conditions": [],
    "id": "guest_arrived",
    "triggers": [
      {
        "entity_id": "binary_sensor.guest_sensor",
        "to": "on",
        "trigger": "state"
      }
    ]
  },
  "script:flash_lights": {
    "alias": "Flash lights",
    "fields": {
      "brightness": {
        "default": 255
      },
      "times": {
        "default": 3
      }
    },
    "icon": "mdi:alarm-light",
    "sequence": [
      {
        "action": "light.turn_on",
        "data": {
          "brightness": "{{ brightness }}",
          "entity_id": "light.all_downstairs"
        }
      },
      {
        "action": "light.turn_off",
        "data": {
          "entity_id": "light.all_downstairs"
        }
      }
    ]
  }
}
```

### `macro`

Golden case: `fixtures/dsl/macro_two_callers/`.

```python
"""Golden case: one macro used by two automations.

Both automations' action lists must contain the macro's expansion.
"""

from notify import notify_adults

from hassle import automation, service, state, when


@automation(id="front_door", alias="Front door opened")
def front_door():
    when(state("binary_sensor.front_door").to("open"))
    notify_adults("Front door opened")


@automation(id="back_door", alias="Back door opened")
def back_door():
    when(state("binary_sensor.back_door").to("open"))
    notify_adults("Back door opened")
    service("light.turn_on", entity_id="light.porch")


"""Shared macro library: notify_adults (DESIGN §5.6)."""

from hassle import macro, service


@macro
def notify_adults(message: str):
    service("notify.mobile_app_kai", message=message)
    service("notify.mobile_app_spouse", message=message)
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:back_door": {
    "actions": [
      {
        "action": "notify.mobile_app_kai",
        "data": {
          "message": "Back door opened"
        }
      },
      {
        "action": "notify.mobile_app_spouse",
        "data": {
          "message": "Back door opened"
        }
      },
      {
        "action": "light.turn_on",
        "data": {
          "entity_id": "light.porch"
        }
      }
    ],
    "alias": "Back door opened",
    "conditions": [],
    "id": "back_door",
    "triggers": [
      {
        "entity_id": "binary_sensor.back_door",
        "to": "open",
        "trigger": "state"
      }
    ]
  },
  "automation:front_door": {
    "actions": [
      {
        "action": "notify.mobile_app_kai",
        "data": {
          "message": "Front door opened"
        }
      },
      {
        "action": "notify.mobile_app_spouse",
        "data": {
          "message": "Front door opened"
        }
      }
    ],
    "alias": "Front door opened",
    "conditions": [],
    "id": "front_door",
    "triggers": [
      {
        "entity_id": "binary_sensor.front_door",
        "to": "open",
        "trigger": "state"
      }
    ]
  }
}
```

See also: `fixtures/dsl/macro_with_args/`

### `raw_automation`

Golden case: `fixtures/dsl/raw_automation_legacy/`.

```python
"""Golden case: raw_automation authored with legacy singular keys.

Proves normalize_ha runs on the raw body: the bundle writes the pre-2024.10
singular schema (trigger/condition/action + service:), and the compiler stores
the canonical plural form (triggers/conditions/actions + action:), exactly as
HA normalizes on storage (docs/internals/ha-api-notes.md §10.1).
"""

from hassle import raw_automation


@raw_automation(id="legacy_device_automation")
def legacy_device_automation():
    return {
        "alias": "Legacy Device Automation",
        "trigger": [{"platform": "state", "entity_id": "binary_sensor.motion", "to": "on"}],
        "condition": [
            {"condition": "state", "entity_id": "input_boolean.guest_mode", "state": "on"}
        ],
        "action": [
            {"service": "light.turn_on", "target": {"entity_id": "light.hallway"}},
        ],
        "mode": "single",
    }
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:legacy_device_automation": {
    "actions": [
      {
        "action": "light.turn_on",
        "target": {
          "entity_id": "light.hallway"
        }
      }
    ],
    "alias": "Legacy Device Automation",
    "conditions": [
      {
        "condition": "state",
        "entity_id": "input_boolean.guest_mode",
        "state": "on"
      }
    ],
    "id": "legacy_device_automation",
    "mode": "single",
    "triggers": [
      {
        "entity_id": "binary_sensor.motion",
        "platform": "state",
        "to": "on"
      }
    ]
  }
}
```

### `blueprint_automation`

Golden case: `fixtures/dsl/blueprint_automation/`.

```python
"""Golden case: blueprint_automation (DESIGN §5.8 / ha-api-notes §10.5).

The ergonomic DSL ``inputs=`` maps to the stored ``use_blueprint.input``
(singular) with an author-qualified blueprint path. A blueprint automation
carries only ``use_blueprint`` — no triggers/conditions/actions.
"""

from hassle import blueprint_automation

blueprint_automation(
    id="hall_motion_blueprint",
    use_blueprint="hassle/motion_light.yaml",
    inputs={
        "motion_entity": "binary_sensor.hall_motion",
        "light_target": "light.hallway",
        "no_motion_wait": 90,
    },
)
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:hall_motion_blueprint": {
    "id": "hall_motion_blueprint",
    "use_blueprint": {
      "input": {
        "light_target": "light.hallway",
        "motion_entity": "binary_sensor.hall_motion",
        "no_motion_wait": 90
      },
      "path": "hassle/motion_light.yaml"
    }
  }
}
```

### `blueprint`

Golden case: `fixtures/dsl/blueprint_dsl_authored/`.

```python
"""Golden case: blueprint_dsl_authored (docs/internals/blueprints-design.md §8).

A blueprint AUTHORED IN THE DSL. Stage 1's golden (`blueprint_managed_object`)
pins a hand-written blueprint FILE becoming a managed object; this one pins the
stage-2 inversion — there is no file, and `BlueprintConfig.source` in
`expected_ir.json` is the emitted YAML, byte for byte.

That makes this fixture the determinism gate (§8.6): declaration order for the
inputs, the fixed metadata and section order, the `!input` tags in plain style,
and the header naming the Python source. Any drift in the emitter shows up here
as a golden diff rather than as a surprise in somebody's Home Assistant.
"""

from hassle import blueprint, bp_input, service, state, when


@blueprint(
    domain="automation",
    path="local/room-switch-controls.yaml",
    name="Room switch controls",
    description="Tap a wall switch to drive a room's light.",
    mode="restart",
)
def room_switch_controls():
    switch_entity = bp_input(
        "switch_entity",
        selector={"entity": {"filter": [{"domain": "sensor"}]}},
        description="The wall switch that drives this room.",
    )
    room_light = bp_input(
        "room_light",
        selector={"entity": {"filter": [{"domain": "light"}]}},
    )
    dim_step_pct = bp_input(
        "dim_step_pct",
        selector={"number": {"min": 1, "max": 100}},
        default=10,
    )
    when(state(switch_entity).to("on"))
    service(
        "light.turn_on",
        target={"entity_id": room_light},
        brightness_step_pct=dim_step_pct,
    )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "blueprint:automation/local/room-switch-controls.yaml": {
    "domain": "automation",
    "inputs": {
      "dim_step_pct": {
        "default": 10,
        "selector": {
          "number": {
            "max": 100,
            "min": 1
          }
        }
      },
      "room_light": {
        "selector": {
          "entity": {
            "filter": [
              {
                "domain": "light"
              }
            ]
          }
        }
      },
      "switch_entity": {
        "description": "The wall switch that drives this room.",
        "selector": {
          "entity": {
            "filter": [
              {
                "domain": "sensor"
              }
            ]
          }
        }
      }
    },
    "path": "local/room-switch-controls.yaml",
    "source": "# Compiled from Python by Hassle. Do not edit -- edit the source and recompile.\n# Source: switches.py\nblueprint:\n  name: Room switch controls\n  description: Tap a wall switch to drive a room's light.\n  domain: automation\n  input:\n    switch_entity:\n      description: The wall switch that drives this room.\n      selector:\n        entity:\n          filter:\n            - domain: sensor\n    room_light:\n      selector:\n        entity:\n          filter:\n            - domain: light\n    dim_step_pct:\n      selector:\n        number:\n          min: 1\n          max: 100\n      default: 10\ntriggers:\n  - trigger: state\n    entity_id: !input switch_entity\n    to: 'on'\nactions:\n  - action: light.turn_on\n    target:\n      entity_id: !input room_light\n    data:\n      brightness_step_pct: !input dim_step_pct\nmode: restart\n"
  }
}
```

### `bp_input`

Golden case: `fixtures/dsl/blueprint_dsl_authored/`.

```python
"""Golden case: blueprint_dsl_authored (docs/internals/blueprints-design.md §8).

A blueprint AUTHORED IN THE DSL. Stage 1's golden (`blueprint_managed_object`)
pins a hand-written blueprint FILE becoming a managed object; this one pins the
stage-2 inversion — there is no file, and `BlueprintConfig.source` in
`expected_ir.json` is the emitted YAML, byte for byte.

That makes this fixture the determinism gate (§8.6): declaration order for the
inputs, the fixed metadata and section order, the `!input` tags in plain style,
and the header naming the Python source. Any drift in the emitter shows up here
as a golden diff rather than as a surprise in somebody's Home Assistant.
"""

from hassle import blueprint, bp_input, service, state, when


@blueprint(
    domain="automation",
    path="local/room-switch-controls.yaml",
    name="Room switch controls",
    description="Tap a wall switch to drive a room's light.",
    mode="restart",
)
def room_switch_controls():
    switch_entity = bp_input(
        "switch_entity",
        selector={"entity": {"filter": [{"domain": "sensor"}]}},
        description="The wall switch that drives this room.",
    )
    room_light = bp_input(
        "room_light",
        selector={"entity": {"filter": [{"domain": "light"}]}},
    )
    dim_step_pct = bp_input(
        "dim_step_pct",
        selector={"number": {"min": 1, "max": 100}},
        default=10,
    )
    when(state(switch_entity).to("on"))
    service(
        "light.turn_on",
        target={"entity_id": room_light},
        brightness_step_pct=dim_step_pct,
    )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "blueprint:automation/local/room-switch-controls.yaml": {
    "domain": "automation",
    "inputs": {
      "dim_step_pct": {
        "default": 10,
        "selector": {
          "number": {
            "max": 100,
            "min": 1
          }
        }
      },
      "room_light": {
        "selector": {
          "entity": {
            "filter": [
              {
                "domain": "light"
              }
            ]
          }
        }
      },
      "switch_entity": {
        "description": "The wall switch that drives this room.",
        "selector": {
          "entity": {
            "filter": [
              {
                "domain": "sensor"
              }
            ]
          }
        }
      }
    },
    "path": "local/room-switch-controls.yaml",
    "source": "# Compiled from Python by Hassle. Do not edit -- edit the source and recompile.\n# Source: switches.py\nblueprint:\n  name: Room switch controls\n  description: Tap a wall switch to drive a room's light.\n  domain: automation\n  input:\n    switch_entity:\n      description: The wall switch that drives this room.\n      selector:\n        entity:\n          filter:\n            - domain: sensor\n    room_light:\n      selector:\n        entity:\n          filter:\n            - domain: light\n    dim_step_pct:\n      selector:\n        number:\n          min: 1\n          max: 100\n      default: 10\ntriggers:\n  - trigger: state\n    entity_id: !input switch_entity\n    to: 'on'\nactions:\n  - action: light.turn_on\n    target:\n      entity_id: !input room_light\n    data:\n      brightness_step_pct: !input dim_step_pct\nmode: restart\n"
  }
}
```

### `input_boolean`

Golden case: `fixtures/dsl/helper_declarations/`.

```python
"""Golden case: helper declarations for all nine storage-collection domains.

Each declaration is a whole top-level object (DESIGN §5.7); the compiler must
land every one in CompileResult.objects under "<domain>:<id>". Declaring them
also returns an EntityRef usable elsewhere in the bundle.
"""

from hassle import (
    counter,
    input_boolean,
    input_button,
    input_datetime,
    input_number,
    input_select,
    input_text,
    schedule,
    timer,
)

input_boolean(id="guest_mode", name="Guest Mode", icon="mdi:account")
input_number(id="target_temp", name="Target Temp", min=10, max=30, step=0.5, mode="slider")
input_select(id="house_mode", name="House Mode", options=["home", "away", "night"])
input_text(id="last_message", name="Last Message", max=255)
input_datetime(id="wake_time", name="Wake Time", has_date=False, has_time=True)
input_button(id="run_scene", name="Run Scene")
counter(id="door_opens", name="Door Opens", initial=0, step=1)
timer(id="cooldown", name="Cooldown", duration="00:05:00")
schedule(id="heating_schedule", name="Heating Schedule")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "counter:door_opens": {
    "id": "door_opens",
    "initial": 0,
    "name": "Door Opens",
    "step": 1
  },
  "input_boolean:guest_mode": {
    "icon": "mdi:account",
    "id": "guest_mode",
    "name": "Guest Mode"
  },
  "input_button:run_scene": {
    "id": "run_scene",
    "name": "Run Scene"
  },
  "input_datetime:wake_time": {
    "has_date": false,
    "has_time": true,
    "id": "wake_time",
    "name": "Wake Time"
  },
  "input_number:target_temp": {
    "id": "target_temp",
    "max": 30,
    "min": 10,
    "mode": "slider",
    "name": "Target Temp",
    "step": 0.5
  },
  "input_select:house_mode": {
    "id": "house_mode",
    "name": "House Mode",
    "options": [
      "home",
      "away",
      "night"
    ]
  },
  "input_text:last_message": {
    "id": "last_message",
    "max": 255,
    "name": "Last Message"
  },
  "schedule:heating_schedule": {
    "id": "heating_schedule",
    "name": "Heating Schedule"
  },
  "timer:cooldown": {
    "duration": "00:05:00",
    "id": "cooldown",
    "name": "Cooldown"
  }
}
```

### `input_number`

Golden case: `fixtures/dsl/helper_declarations/`.

```python
"""Golden case: helper declarations for all nine storage-collection domains.

Each declaration is a whole top-level object (DESIGN §5.7); the compiler must
land every one in CompileResult.objects under "<domain>:<id>". Declaring them
also returns an EntityRef usable elsewhere in the bundle.
"""

from hassle import (
    counter,
    input_boolean,
    input_button,
    input_datetime,
    input_number,
    input_select,
    input_text,
    schedule,
    timer,
)

input_boolean(id="guest_mode", name="Guest Mode", icon="mdi:account")
input_number(id="target_temp", name="Target Temp", min=10, max=30, step=0.5, mode="slider")
input_select(id="house_mode", name="House Mode", options=["home", "away", "night"])
input_text(id="last_message", name="Last Message", max=255)
input_datetime(id="wake_time", name="Wake Time", has_date=False, has_time=True)
input_button(id="run_scene", name="Run Scene")
counter(id="door_opens", name="Door Opens", initial=0, step=1)
timer(id="cooldown", name="Cooldown", duration="00:05:00")
schedule(id="heating_schedule", name="Heating Schedule")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "counter:door_opens": {
    "id": "door_opens",
    "initial": 0,
    "name": "Door Opens",
    "step": 1
  },
  "input_boolean:guest_mode": {
    "icon": "mdi:account",
    "id": "guest_mode",
    "name": "Guest Mode"
  },
  "input_button:run_scene": {
    "id": "run_scene",
    "name": "Run Scene"
  },
  "input_datetime:wake_time": {
    "has_date": false,
    "has_time": true,
    "id": "wake_time",
    "name": "Wake Time"
  },
  "input_number:target_temp": {
    "id": "target_temp",
    "max": 30,
    "min": 10,
    "mode": "slider",
    "name": "Target Temp",
    "step": 0.5
  },
  "input_select:house_mode": {
    "id": "house_mode",
    "name": "House Mode",
    "options": [
      "home",
      "away",
      "night"
    ]
  },
  "input_text:last_message": {
    "id": "last_message",
    "max": 255,
    "name": "Last Message"
  },
  "schedule:heating_schedule": {
    "id": "heating_schedule",
    "name": "Heating Schedule"
  },
  "timer:cooldown": {
    "duration": "00:05:00",
    "id": "cooldown",
    "name": "Cooldown"
  }
}
```

### `input_select`

Golden case: `fixtures/dsl/helper_declarations/`.

```python
"""Golden case: helper declarations for all nine storage-collection domains.

Each declaration is a whole top-level object (DESIGN §5.7); the compiler must
land every one in CompileResult.objects under "<domain>:<id>". Declaring them
also returns an EntityRef usable elsewhere in the bundle.
"""

from hassle import (
    counter,
    input_boolean,
    input_button,
    input_datetime,
    input_number,
    input_select,
    input_text,
    schedule,
    timer,
)

input_boolean(id="guest_mode", name="Guest Mode", icon="mdi:account")
input_number(id="target_temp", name="Target Temp", min=10, max=30, step=0.5, mode="slider")
input_select(id="house_mode", name="House Mode", options=["home", "away", "night"])
input_text(id="last_message", name="Last Message", max=255)
input_datetime(id="wake_time", name="Wake Time", has_date=False, has_time=True)
input_button(id="run_scene", name="Run Scene")
counter(id="door_opens", name="Door Opens", initial=0, step=1)
timer(id="cooldown", name="Cooldown", duration="00:05:00")
schedule(id="heating_schedule", name="Heating Schedule")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "counter:door_opens": {
    "id": "door_opens",
    "initial": 0,
    "name": "Door Opens",
    "step": 1
  },
  "input_boolean:guest_mode": {
    "icon": "mdi:account",
    "id": "guest_mode",
    "name": "Guest Mode"
  },
  "input_button:run_scene": {
    "id": "run_scene",
    "name": "Run Scene"
  },
  "input_datetime:wake_time": {
    "has_date": false,
    "has_time": true,
    "id": "wake_time",
    "name": "Wake Time"
  },
  "input_number:target_temp": {
    "id": "target_temp",
    "max": 30,
    "min": 10,
    "mode": "slider",
    "name": "Target Temp",
    "step": 0.5
  },
  "input_select:house_mode": {
    "id": "house_mode",
    "name": "House Mode",
    "options": [
      "home",
      "away",
      "night"
    ]
  },
  "input_text:last_message": {
    "id": "last_message",
    "max": 255,
    "name": "Last Message"
  },
  "schedule:heating_schedule": {
    "id": "heating_schedule",
    "name": "Heating Schedule"
  },
  "timer:cooldown": {
    "duration": "00:05:00",
    "id": "cooldown",
    "name": "Cooldown"
  }
}
```

### `input_text`

Golden case: `fixtures/dsl/helper_declarations/`.

```python
"""Golden case: helper declarations for all nine storage-collection domains.

Each declaration is a whole top-level object (DESIGN §5.7); the compiler must
land every one in CompileResult.objects under "<domain>:<id>". Declaring them
also returns an EntityRef usable elsewhere in the bundle.
"""

from hassle import (
    counter,
    input_boolean,
    input_button,
    input_datetime,
    input_number,
    input_select,
    input_text,
    schedule,
    timer,
)

input_boolean(id="guest_mode", name="Guest Mode", icon="mdi:account")
input_number(id="target_temp", name="Target Temp", min=10, max=30, step=0.5, mode="slider")
input_select(id="house_mode", name="House Mode", options=["home", "away", "night"])
input_text(id="last_message", name="Last Message", max=255)
input_datetime(id="wake_time", name="Wake Time", has_date=False, has_time=True)
input_button(id="run_scene", name="Run Scene")
counter(id="door_opens", name="Door Opens", initial=0, step=1)
timer(id="cooldown", name="Cooldown", duration="00:05:00")
schedule(id="heating_schedule", name="Heating Schedule")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "counter:door_opens": {
    "id": "door_opens",
    "initial": 0,
    "name": "Door Opens",
    "step": 1
  },
  "input_boolean:guest_mode": {
    "icon": "mdi:account",
    "id": "guest_mode",
    "name": "Guest Mode"
  },
  "input_button:run_scene": {
    "id": "run_scene",
    "name": "Run Scene"
  },
  "input_datetime:wake_time": {
    "has_date": false,
    "has_time": true,
    "id": "wake_time",
    "name": "Wake Time"
  },
  "input_number:target_temp": {
    "id": "target_temp",
    "max": 30,
    "min": 10,
    "mode": "slider",
    "name": "Target Temp",
    "step": 0.5
  },
  "input_select:house_mode": {
    "id": "house_mode",
    "name": "House Mode",
    "options": [
      "home",
      "away",
      "night"
    ]
  },
  "input_text:last_message": {
    "id": "last_message",
    "max": 255,
    "name": "Last Message"
  },
  "schedule:heating_schedule": {
    "id": "heating_schedule",
    "name": "Heating Schedule"
  },
  "timer:cooldown": {
    "duration": "00:05:00",
    "id": "cooldown",
    "name": "Cooldown"
  }
}
```

### `input_datetime`

Golden case: `fixtures/dsl/helper_declarations/`.

```python
"""Golden case: helper declarations for all nine storage-collection domains.

Each declaration is a whole top-level object (DESIGN §5.7); the compiler must
land every one in CompileResult.objects under "<domain>:<id>". Declaring them
also returns an EntityRef usable elsewhere in the bundle.
"""

from hassle import (
    counter,
    input_boolean,
    input_button,
    input_datetime,
    input_number,
    input_select,
    input_text,
    schedule,
    timer,
)

input_boolean(id="guest_mode", name="Guest Mode", icon="mdi:account")
input_number(id="target_temp", name="Target Temp", min=10, max=30, step=0.5, mode="slider")
input_select(id="house_mode", name="House Mode", options=["home", "away", "night"])
input_text(id="last_message", name="Last Message", max=255)
input_datetime(id="wake_time", name="Wake Time", has_date=False, has_time=True)
input_button(id="run_scene", name="Run Scene")
counter(id="door_opens", name="Door Opens", initial=0, step=1)
timer(id="cooldown", name="Cooldown", duration="00:05:00")
schedule(id="heating_schedule", name="Heating Schedule")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "counter:door_opens": {
    "id": "door_opens",
    "initial": 0,
    "name": "Door Opens",
    "step": 1
  },
  "input_boolean:guest_mode": {
    "icon": "mdi:account",
    "id": "guest_mode",
    "name": "Guest Mode"
  },
  "input_button:run_scene": {
    "id": "run_scene",
    "name": "Run Scene"
  },
  "input_datetime:wake_time": {
    "has_date": false,
    "has_time": true,
    "id": "wake_time",
    "name": "Wake Time"
  },
  "input_number:target_temp": {
    "id": "target_temp",
    "max": 30,
    "min": 10,
    "mode": "slider",
    "name": "Target Temp",
    "step": 0.5
  },
  "input_select:house_mode": {
    "id": "house_mode",
    "name": "House Mode",
    "options": [
      "home",
      "away",
      "night"
    ]
  },
  "input_text:last_message": {
    "id": "last_message",
    "max": 255,
    "name": "Last Message"
  },
  "schedule:heating_schedule": {
    "id": "heating_schedule",
    "name": "Heating Schedule"
  },
  "timer:cooldown": {
    "duration": "00:05:00",
    "id": "cooldown",
    "name": "Cooldown"
  }
}
```

### `input_button`

Golden case: `fixtures/dsl/helper_declarations/`.

```python
"""Golden case: helper declarations for all nine storage-collection domains.

Each declaration is a whole top-level object (DESIGN §5.7); the compiler must
land every one in CompileResult.objects under "<domain>:<id>". Declaring them
also returns an EntityRef usable elsewhere in the bundle.
"""

from hassle import (
    counter,
    input_boolean,
    input_button,
    input_datetime,
    input_number,
    input_select,
    input_text,
    schedule,
    timer,
)

input_boolean(id="guest_mode", name="Guest Mode", icon="mdi:account")
input_number(id="target_temp", name="Target Temp", min=10, max=30, step=0.5, mode="slider")
input_select(id="house_mode", name="House Mode", options=["home", "away", "night"])
input_text(id="last_message", name="Last Message", max=255)
input_datetime(id="wake_time", name="Wake Time", has_date=False, has_time=True)
input_button(id="run_scene", name="Run Scene")
counter(id="door_opens", name="Door Opens", initial=0, step=1)
timer(id="cooldown", name="Cooldown", duration="00:05:00")
schedule(id="heating_schedule", name="Heating Schedule")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "counter:door_opens": {
    "id": "door_opens",
    "initial": 0,
    "name": "Door Opens",
    "step": 1
  },
  "input_boolean:guest_mode": {
    "icon": "mdi:account",
    "id": "guest_mode",
    "name": "Guest Mode"
  },
  "input_button:run_scene": {
    "id": "run_scene",
    "name": "Run Scene"
  },
  "input_datetime:wake_time": {
    "has_date": false,
    "has_time": true,
    "id": "wake_time",
    "name": "Wake Time"
  },
  "input_number:target_temp": {
    "id": "target_temp",
    "max": 30,
    "min": 10,
    "mode": "slider",
    "name": "Target Temp",
    "step": 0.5
  },
  "input_select:house_mode": {
    "id": "house_mode",
    "name": "House Mode",
    "options": [
      "home",
      "away",
      "night"
    ]
  },
  "input_text:last_message": {
    "id": "last_message",
    "max": 255,
    "name": "Last Message"
  },
  "schedule:heating_schedule": {
    "id": "heating_schedule",
    "name": "Heating Schedule"
  },
  "timer:cooldown": {
    "duration": "00:05:00",
    "id": "cooldown",
    "name": "Cooldown"
  }
}
```

### `counter`

Golden case: `fixtures/dsl/helper_declarations/`.

```python
"""Golden case: helper declarations for all nine storage-collection domains.

Each declaration is a whole top-level object (DESIGN §5.7); the compiler must
land every one in CompileResult.objects under "<domain>:<id>". Declaring them
also returns an EntityRef usable elsewhere in the bundle.
"""

from hassle import (
    counter,
    input_boolean,
    input_button,
    input_datetime,
    input_number,
    input_select,
    input_text,
    schedule,
    timer,
)

input_boolean(id="guest_mode", name="Guest Mode", icon="mdi:account")
input_number(id="target_temp", name="Target Temp", min=10, max=30, step=0.5, mode="slider")
input_select(id="house_mode", name="House Mode", options=["home", "away", "night"])
input_text(id="last_message", name="Last Message", max=255)
input_datetime(id="wake_time", name="Wake Time", has_date=False, has_time=True)
input_button(id="run_scene", name="Run Scene")
counter(id="door_opens", name="Door Opens", initial=0, step=1)
timer(id="cooldown", name="Cooldown", duration="00:05:00")
schedule(id="heating_schedule", name="Heating Schedule")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "counter:door_opens": {
    "id": "door_opens",
    "initial": 0,
    "name": "Door Opens",
    "step": 1
  },
  "input_boolean:guest_mode": {
    "icon": "mdi:account",
    "id": "guest_mode",
    "name": "Guest Mode"
  },
  "input_button:run_scene": {
    "id": "run_scene",
    "name": "Run Scene"
  },
  "input_datetime:wake_time": {
    "has_date": false,
    "has_time": true,
    "id": "wake_time",
    "name": "Wake Time"
  },
  "input_number:target_temp": {
    "id": "target_temp",
    "max": 30,
    "min": 10,
    "mode": "slider",
    "name": "Target Temp",
    "step": 0.5
  },
  "input_select:house_mode": {
    "id": "house_mode",
    "name": "House Mode",
    "options": [
      "home",
      "away",
      "night"
    ]
  },
  "input_text:last_message": {
    "id": "last_message",
    "max": 255,
    "name": "Last Message"
  },
  "schedule:heating_schedule": {
    "id": "heating_schedule",
    "name": "Heating Schedule"
  },
  "timer:cooldown": {
    "duration": "00:05:00",
    "id": "cooldown",
    "name": "Cooldown"
  }
}
```

### `timer`

Golden case: `fixtures/dsl/helper_declarations/`.

```python
"""Golden case: helper declarations for all nine storage-collection domains.

Each declaration is a whole top-level object (DESIGN §5.7); the compiler must
land every one in CompileResult.objects under "<domain>:<id>". Declaring them
also returns an EntityRef usable elsewhere in the bundle.
"""

from hassle import (
    counter,
    input_boolean,
    input_button,
    input_datetime,
    input_number,
    input_select,
    input_text,
    schedule,
    timer,
)

input_boolean(id="guest_mode", name="Guest Mode", icon="mdi:account")
input_number(id="target_temp", name="Target Temp", min=10, max=30, step=0.5, mode="slider")
input_select(id="house_mode", name="House Mode", options=["home", "away", "night"])
input_text(id="last_message", name="Last Message", max=255)
input_datetime(id="wake_time", name="Wake Time", has_date=False, has_time=True)
input_button(id="run_scene", name="Run Scene")
counter(id="door_opens", name="Door Opens", initial=0, step=1)
timer(id="cooldown", name="Cooldown", duration="00:05:00")
schedule(id="heating_schedule", name="Heating Schedule")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "counter:door_opens": {
    "id": "door_opens",
    "initial": 0,
    "name": "Door Opens",
    "step": 1
  },
  "input_boolean:guest_mode": {
    "icon": "mdi:account",
    "id": "guest_mode",
    "name": "Guest Mode"
  },
  "input_button:run_scene": {
    "id": "run_scene",
    "name": "Run Scene"
  },
  "input_datetime:wake_time": {
    "has_date": false,
    "has_time": true,
    "id": "wake_time",
    "name": "Wake Time"
  },
  "input_number:target_temp": {
    "id": "target_temp",
    "max": 30,
    "min": 10,
    "mode": "slider",
    "name": "Target Temp",
    "step": 0.5
  },
  "input_select:house_mode": {
    "id": "house_mode",
    "name": "House Mode",
    "options": [
      "home",
      "away",
      "night"
    ]
  },
  "input_text:last_message": {
    "id": "last_message",
    "max": 255,
    "name": "Last Message"
  },
  "schedule:heating_schedule": {
    "id": "heating_schedule",
    "name": "Heating Schedule"
  },
  "timer:cooldown": {
    "duration": "00:05:00",
    "id": "cooldown",
    "name": "Cooldown"
  }
}
```

### `schedule`

Golden case: `fixtures/dsl/helper_declarations/`.

```python
"""Golden case: helper declarations for all nine storage-collection domains.

Each declaration is a whole top-level object (DESIGN §5.7); the compiler must
land every one in CompileResult.objects under "<domain>:<id>". Declaring them
also returns an EntityRef usable elsewhere in the bundle.
"""

from hassle import (
    counter,
    input_boolean,
    input_button,
    input_datetime,
    input_number,
    input_select,
    input_text,
    schedule,
    timer,
)

input_boolean(id="guest_mode", name="Guest Mode", icon="mdi:account")
input_number(id="target_temp", name="Target Temp", min=10, max=30, step=0.5, mode="slider")
input_select(id="house_mode", name="House Mode", options=["home", "away", "night"])
input_text(id="last_message", name="Last Message", max=255)
input_datetime(id="wake_time", name="Wake Time", has_date=False, has_time=True)
input_button(id="run_scene", name="Run Scene")
counter(id="door_opens", name="Door Opens", initial=0, step=1)
timer(id="cooldown", name="Cooldown", duration="00:05:00")
schedule(id="heating_schedule", name="Heating Schedule")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "counter:door_opens": {
    "id": "door_opens",
    "initial": 0,
    "name": "Door Opens",
    "step": 1
  },
  "input_boolean:guest_mode": {
    "icon": "mdi:account",
    "id": "guest_mode",
    "name": "Guest Mode"
  },
  "input_button:run_scene": {
    "id": "run_scene",
    "name": "Run Scene"
  },
  "input_datetime:wake_time": {
    "has_date": false,
    "has_time": true,
    "id": "wake_time",
    "name": "Wake Time"
  },
  "input_number:target_temp": {
    "id": "target_temp",
    "max": 30,
    "min": 10,
    "mode": "slider",
    "name": "Target Temp",
    "step": 0.5
  },
  "input_select:house_mode": {
    "id": "house_mode",
    "name": "House Mode",
    "options": [
      "home",
      "away",
      "night"
    ]
  },
  "input_text:last_message": {
    "id": "last_message",
    "max": 255,
    "name": "Last Message"
  },
  "schedule:heating_schedule": {
    "id": "heating_schedule",
    "name": "Heating Schedule"
  },
  "timer:cooldown": {
    "duration": "00:05:00",
    "id": "cooldown",
    "name": "Cooldown"
  }
}
```

### `template_number`

Golden case: `fixtures/dsl/template_helper_declarations/`.

```python
"""Golden case: template-helper declarations for all four template
domains. The driving case is `template_number` (e.g.
`number.active_hvac_zones`).

Identity (docs/internals/ha-api-notes.md §26.6): there is no `id=`/`unique_id=` kwarg --
real HA's config flow rejects an unrecognized `unique_id` key outright.
Identity is derived from `name` (slugified): "Active HVAC Zones" ->
`template_number:active_hvac_zones`.

`template_number`/`template_select` require a write-target action sequence
(`set_value=`/`select_option=`) -- HA's form schema rejects the submission
without one (a number/select needs somewhere to send a written value; a
sensor/binary_sensor is read-only and needs only `state=`).
"""

from hassle import (
    template_binary_sensor,
    template_number,
    template_select,
    template_sensor,
)

template_number(
    name="Active HVAC Zones",
    state="{{ states.climate | selectattr('state', 'ne', 'off') | list | count }}",
    set_value={
        "action": "input_number.set_value",
        "target": {"entity_id": "input_number.hvac_zone_override"},
        "data": {"value": "{{ value }}"},
    },
    min=0,
    max=8,
    step=1,
    unit_of_measurement="zones",
)
template_sensor(
    name="Average Temp",
    state="{{ (states('sensor.a') | float + states('sensor.b') | float) / 2 }}",
    unit_of_measurement="°C",
    device_class="temperature",
)
template_binary_sensor(
    name="Any Door Open",
    state="{{ is_state('binary_sensor.front_door', 'on') }}",
    device_class="door",
)
template_select(
    name="House Scene",
    state="{{ states('input_select.house_mode') }}",
    options="{{ ['home', 'away', 'night'] }}",
    select_option={
        "action": "input_select.select_option",
        "target": {"entity_id": "input_select.house_mode"},
        "data": {"option": "{{ option }}"},
    },
)
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "template_binary_sensor:any_door_open": {
    "device_class": "door",
    "name": "Any Door Open",
    "state": "{{ is_state('binary_sensor.front_door', 'on') }}"
  },
  "template_number:active_hvac_zones": {
    "max": 8.0,
    "min": 0.0,
    "name": "Active HVAC Zones",
    "set_value": {
      "action": "input_number.set_value",
      "data": {
        "value": "{{ value }}"
      },
      "target": {
        "entity_id": "input_number.hvac_zone_override"
      }
    },
    "state": "{{ states.climate | selectattr('state', 'ne', 'off') | list | count }}",
    "step": 1.0,
    "unit_of_measurement": "zones"
  },
  "template_select:house_scene": {
    "name": "House Scene",
    "options": "{{ ['home', 'away', 'night'] }}",
    "select_option": {
      "action": "input_select.select_option",
      "data": {
        "option": "{{ option }}"
      },
      "target": {
        "entity_id": "input_select.house_mode"
      }
    },
    "state": "{{ states('input_select.house_mode') }}"
  },
  "template_sensor:average_temp": {
    "device_class": "temperature",
    "name": "Average Temp",
    "state": "{{ (states('sensor.a') | float + states('sensor.b') | float) / 2 }}",
    "unit_of_measurement": "°C"
  }
}
```

### `template_sensor`

Golden case: `fixtures/dsl/template_helper_declarations/`.

```python
"""Golden case: template-helper declarations for all four template
domains. The driving case is `template_number` (e.g.
`number.active_hvac_zones`).

Identity (docs/internals/ha-api-notes.md §26.6): there is no `id=`/`unique_id=` kwarg --
real HA's config flow rejects an unrecognized `unique_id` key outright.
Identity is derived from `name` (slugified): "Active HVAC Zones" ->
`template_number:active_hvac_zones`.

`template_number`/`template_select` require a write-target action sequence
(`set_value=`/`select_option=`) -- HA's form schema rejects the submission
without one (a number/select needs somewhere to send a written value; a
sensor/binary_sensor is read-only and needs only `state=`).
"""

from hassle import (
    template_binary_sensor,
    template_number,
    template_select,
    template_sensor,
)

template_number(
    name="Active HVAC Zones",
    state="{{ states.climate | selectattr('state', 'ne', 'off') | list | count }}",
    set_value={
        "action": "input_number.set_value",
        "target": {"entity_id": "input_number.hvac_zone_override"},
        "data": {"value": "{{ value }}"},
    },
    min=0,
    max=8,
    step=1,
    unit_of_measurement="zones",
)
template_sensor(
    name="Average Temp",
    state="{{ (states('sensor.a') | float + states('sensor.b') | float) / 2 }}",
    unit_of_measurement="°C",
    device_class="temperature",
)
template_binary_sensor(
    name="Any Door Open",
    state="{{ is_state('binary_sensor.front_door', 'on') }}",
    device_class="door",
)
template_select(
    name="House Scene",
    state="{{ states('input_select.house_mode') }}",
    options="{{ ['home', 'away', 'night'] }}",
    select_option={
        "action": "input_select.select_option",
        "target": {"entity_id": "input_select.house_mode"},
        "data": {"option": "{{ option }}"},
    },
)
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "template_binary_sensor:any_door_open": {
    "device_class": "door",
    "name": "Any Door Open",
    "state": "{{ is_state('binary_sensor.front_door', 'on') }}"
  },
  "template_number:active_hvac_zones": {
    "max": 8.0,
    "min": 0.0,
    "name": "Active HVAC Zones",
    "set_value": {
      "action": "input_number.set_value",
      "data": {
        "value": "{{ value }}"
      },
      "target": {
        "entity_id": "input_number.hvac_zone_override"
      }
    },
    "state": "{{ states.climate | selectattr('state', 'ne', 'off') | list | count }}",
    "step": 1.0,
    "unit_of_measurement": "zones"
  },
  "template_select:house_scene": {
    "name": "House Scene",
    "options": "{{ ['home', 'away', 'night'] }}",
    "select_option": {
      "action": "input_select.select_option",
      "data": {
        "option": "{{ option }}"
      },
      "target": {
        "entity_id": "input_select.house_mode"
      }
    },
    "state": "{{ states('input_select.house_mode') }}"
  },
  "template_sensor:average_temp": {
    "device_class": "temperature",
    "name": "Average Temp",
    "state": "{{ (states('sensor.a') | float + states('sensor.b') | float) / 2 }}",
    "unit_of_measurement": "°C"
  }
}
```

### `template_binary_sensor`

Golden case: `fixtures/dsl/template_helper_declarations/`.

```python
"""Golden case: template-helper declarations for all four template
domains. The driving case is `template_number` (e.g.
`number.active_hvac_zones`).

Identity (docs/internals/ha-api-notes.md §26.6): there is no `id=`/`unique_id=` kwarg --
real HA's config flow rejects an unrecognized `unique_id` key outright.
Identity is derived from `name` (slugified): "Active HVAC Zones" ->
`template_number:active_hvac_zones`.

`template_number`/`template_select` require a write-target action sequence
(`set_value=`/`select_option=`) -- HA's form schema rejects the submission
without one (a number/select needs somewhere to send a written value; a
sensor/binary_sensor is read-only and needs only `state=`).
"""

from hassle import (
    template_binary_sensor,
    template_number,
    template_select,
    template_sensor,
)

template_number(
    name="Active HVAC Zones",
    state="{{ states.climate | selectattr('state', 'ne', 'off') | list | count }}",
    set_value={
        "action": "input_number.set_value",
        "target": {"entity_id": "input_number.hvac_zone_override"},
        "data": {"value": "{{ value }}"},
    },
    min=0,
    max=8,
    step=1,
    unit_of_measurement="zones",
)
template_sensor(
    name="Average Temp",
    state="{{ (states('sensor.a') | float + states('sensor.b') | float) / 2 }}",
    unit_of_measurement="°C",
    device_class="temperature",
)
template_binary_sensor(
    name="Any Door Open",
    state="{{ is_state('binary_sensor.front_door', 'on') }}",
    device_class="door",
)
template_select(
    name="House Scene",
    state="{{ states('input_select.house_mode') }}",
    options="{{ ['home', 'away', 'night'] }}",
    select_option={
        "action": "input_select.select_option",
        "target": {"entity_id": "input_select.house_mode"},
        "data": {"option": "{{ option }}"},
    },
)
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "template_binary_sensor:any_door_open": {
    "device_class": "door",
    "name": "Any Door Open",
    "state": "{{ is_state('binary_sensor.front_door', 'on') }}"
  },
  "template_number:active_hvac_zones": {
    "max": 8.0,
    "min": 0.0,
    "name": "Active HVAC Zones",
    "set_value": {
      "action": "input_number.set_value",
      "data": {
        "value": "{{ value }}"
      },
      "target": {
        "entity_id": "input_number.hvac_zone_override"
      }
    },
    "state": "{{ states.climate | selectattr('state', 'ne', 'off') | list | count }}",
    "step": 1.0,
    "unit_of_measurement": "zones"
  },
  "template_select:house_scene": {
    "name": "House Scene",
    "options": "{{ ['home', 'away', 'night'] }}",
    "select_option": {
      "action": "input_select.select_option",
      "data": {
        "option": "{{ option }}"
      },
      "target": {
        "entity_id": "input_select.house_mode"
      }
    },
    "state": "{{ states('input_select.house_mode') }}"
  },
  "template_sensor:average_temp": {
    "device_class": "temperature",
    "name": "Average Temp",
    "state": "{{ (states('sensor.a') | float + states('sensor.b') | float) / 2 }}",
    "unit_of_measurement": "°C"
  }
}
```

### `template_select`

Golden case: `fixtures/dsl/template_helper_declarations/`.

```python
"""Golden case: template-helper declarations for all four template
domains. The driving case is `template_number` (e.g.
`number.active_hvac_zones`).

Identity (docs/internals/ha-api-notes.md §26.6): there is no `id=`/`unique_id=` kwarg --
real HA's config flow rejects an unrecognized `unique_id` key outright.
Identity is derived from `name` (slugified): "Active HVAC Zones" ->
`template_number:active_hvac_zones`.

`template_number`/`template_select` require a write-target action sequence
(`set_value=`/`select_option=`) -- HA's form schema rejects the submission
without one (a number/select needs somewhere to send a written value; a
sensor/binary_sensor is read-only and needs only `state=`).
"""

from hassle import (
    template_binary_sensor,
    template_number,
    template_select,
    template_sensor,
)

template_number(
    name="Active HVAC Zones",
    state="{{ states.climate | selectattr('state', 'ne', 'off') | list | count }}",
    set_value={
        "action": "input_number.set_value",
        "target": {"entity_id": "input_number.hvac_zone_override"},
        "data": {"value": "{{ value }}"},
    },
    min=0,
    max=8,
    step=1,
    unit_of_measurement="zones",
)
template_sensor(
    name="Average Temp",
    state="{{ (states('sensor.a') | float + states('sensor.b') | float) / 2 }}",
    unit_of_measurement="°C",
    device_class="temperature",
)
template_binary_sensor(
    name="Any Door Open",
    state="{{ is_state('binary_sensor.front_door', 'on') }}",
    device_class="door",
)
template_select(
    name="House Scene",
    state="{{ states('input_select.house_mode') }}",
    options="{{ ['home', 'away', 'night'] }}",
    select_option={
        "action": "input_select.select_option",
        "target": {"entity_id": "input_select.house_mode"},
        "data": {"option": "{{ option }}"},
    },
)
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "template_binary_sensor:any_door_open": {
    "device_class": "door",
    "name": "Any Door Open",
    "state": "{{ is_state('binary_sensor.front_door', 'on') }}"
  },
  "template_number:active_hvac_zones": {
    "max": 8.0,
    "min": 0.0,
    "name": "Active HVAC Zones",
    "set_value": {
      "action": "input_number.set_value",
      "data": {
        "value": "{{ value }}"
      },
      "target": {
        "entity_id": "input_number.hvac_zone_override"
      }
    },
    "state": "{{ states.climate | selectattr('state', 'ne', 'off') | list | count }}",
    "step": 1.0,
    "unit_of_measurement": "zones"
  },
  "template_select:house_scene": {
    "name": "House Scene",
    "options": "{{ ['home', 'away', 'night'] }}",
    "select_option": {
      "action": "input_select.select_option",
      "data": {
        "option": "{{ option }}"
      },
      "target": {
        "entity_id": "input_select.house_mode"
      }
    },
    "state": "{{ states('input_select.house_mode') }}"
  },
  "template_sensor:average_temp": {
    "device_class": "temperature",
    "name": "Average Temp",
    "state": "{{ (states('sensor.a') | float + states('sensor.b') | float) / 2 }}",
    "unit_of_measurement": "°C"
  }
}
```

### `group_binary_sensor`

Golden case: `fixtures/dsl/group_helper_declarations/`.

```python
"""Golden case: group-helper declarations for all twelve group flavors,
covering the three schema shapes (docs/internals/ha-api-notes.md §38.1) -- base (name/
entities/hide_members), +all (binary_sensor/light/switch), +type (sensor).

Identity: there is no `id=`/`unique_id=` kwarg, mirroring template helpers
(docs/internals/ha-api-notes.md §38.1) -- real HA's `group` config flow rejects an
unrecognized `unique_id` key outright. Identity is derived from `name`
(slugified): "Entryway Top" -> `group_cover:entryway_top`.

`hide_members`/`all` are always materialized explicitly in the compiled
options body (one canonical form, §38.1) -- never omitted just because they
equal their default.

Every `entities=` member below is a REAL entity id from
`fixtures/registry/home.json` (except `cover.bay_window_top`, which is this
bundle's OWN nested group's entity -- a real-world live example, §38.1:
a `cover.entryway_top` group containing `cover.bay_window_top`,
itself a group), so this fixture is also exercised by
`test_registry_validate.py::test_no_false_positives_on_golden_corpus`
(validation-clean, no `_DELIBERATELY_NOT_CLEAN` escape hatch needed).
"""

from hassle import (
    group_binary_sensor,
    group_button,
    group_cover,
    group_event,
    group_fan,
    group_light,
    group_lock,
    group_media_player,
    group_notify,
    group_sensor,
    group_switch,
    group_valve,
)

# Nested: "Bay Window Top" is declared first so "Entryway Top" can reference
# its produced entity (`cover.bay_window_top`) as a member -- a group whose
# members are themselves a group, a real-world live example (§38.1).
group_cover(
    name="Bay Window Top",
    entities=["cover.bedroom_blinds", "cover.living_room_blinds"],
)
group_cover(
    name="Entryway Top",
    entities=["cover.bay_window_top", "cover.garage_door"],
)
group_light(
    name="Downstairs Lights",
    entities=["light.hallway", "light.living_room", "light.kitchen"],
    all=True,
)
group_switch(
    name="Outdoor Switches",
    entities=["switch.garage_door_opener", "switch.office_monitor"],
    hide_members=True,
)
group_binary_sensor(
    name="Any Door Open",
    entities=["binary_sensor.door", "binary_sensor.back_door"],
)
group_sensor(
    name="Average Temp",
    entities=["sensor.living_room_temperature", "sensor.bedroom_temperature"],
    type="mean",
)
group_button(name="All Doorbells", entities=["button.restart"])
group_event(name="All Doorbell Events", entities=["event.doorbell"])
group_fan(name="All Fans", entities=["fan.bedroom", "fan.living_room"])
group_lock(name="All Locks", entities=["lock.front_door", "lock.back_door"])
group_media_player(
    name="Whole House Audio",
    entities=["media_player.living_room_speaker", "media_player.kitchen_speaker"],
)
group_notify(name="All Phones", entities=["notify.mobile_app_kai", "notify.mobile_app_spouse"])
# No `valve` entities exist in fixtures/registry/home.json at all (its
# registry snapshot has no valve domain coverage) -- validation only checks
# that a referenced entity id EXISTS, not that its domain matches the
# group's own flavor, so a real (if domain-mismatched) registry entity keeps
# this fixture validation-clean without needing to touch the shared registry
# fixture just for this one domain.
group_valve(name="Irrigation Zone A", entities=["cover.garage_door"])
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "group_binary_sensor:any_door_open": {
    "all": false,
    "entities": [
      "binary_sensor.door",
      "binary_sensor.back_door"
    ],
    "hide_members": false,
    "name": "Any Door Open"
  },
  "group_button:all_doorbells": {
    "entities": [
      "button.restart"
    ],
    "hide_members": false,
    "name": "All Doorbells"
  },
  "group_cover:bay_window_top": {
    "entities": [
      "cover.bedroom_blinds",
      "cover.living_room_blinds"
    ],
    "hide_members": false,
    "name": "Bay Window Top"
  },
  "group_cover:entryway_top": {
    "entities": [
      "cover.bay_window_top",
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Entryway Top"
  },
  "group_event:all_doorbell_events": {
    "entities": [
      "event.doorbell"
    ],
    "hide_members": false,
    "name": "All Doorbell Events"
  },
  "group_fan:all_fans": {
    "entities": [
      "fan.bedroom",
      "fan.living_room"
    ],
    "hide_members": false,
    "name": "All Fans"
  },
  "group_light:downstairs_lights": {
    "all": true,
    "entities": [
      "light.hallway",
      "light.living_room",
      "light.kitchen"
    ],
    "hide_members": false,
    "name": "Downstairs Lights"
  },
  "group_lock:all_locks": {
    "entities": [
      "lock.front_door",
      "lock.back_door"
    ],
    "hide_members": false,
    "name": "All Locks"
  },
  "group_media_player:whole_house_audio": {
    "entities": [
      "media_player.living_room_speaker",
      "media_player.kitchen_speaker"
    ],
    "hide_members": false,
    "name": "Whole House Audio"
  },
  "group_notify:all_phones": {
    "entities": [
      "notify.mobile_app_kai",
      "notify.mobile_app_spouse"
    ],
    "hide_members": false,
    "name": "All Phones"
  },
  "group_sensor:average_temp": {
    "entities": [
      "sensor.living_room_temperature",
      "sensor.bedroom_temperature"
    ],
    "hide_members": false,
    "name": "Average Temp",
    "type": "mean"
  },
  "group_switch:outdoor_switches": {
    "all": false,
    "entities": [
      "switch.garage_door_opener",
      "switch.office_monitor"
    ],
    "hide_members": true,
    "name": "Outdoor Switches"
  },
  "group_valve:irrigation_zone_a": {
    "entities": [
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Irrigation Zone A"
  }
}
```

### `group_button`

Golden case: `fixtures/dsl/group_helper_declarations/`.

```python
"""Golden case: group-helper declarations for all twelve group flavors,
covering the three schema shapes (docs/internals/ha-api-notes.md §38.1) -- base (name/
entities/hide_members), +all (binary_sensor/light/switch), +type (sensor).

Identity: there is no `id=`/`unique_id=` kwarg, mirroring template helpers
(docs/internals/ha-api-notes.md §38.1) -- real HA's `group` config flow rejects an
unrecognized `unique_id` key outright. Identity is derived from `name`
(slugified): "Entryway Top" -> `group_cover:entryway_top`.

`hide_members`/`all` are always materialized explicitly in the compiled
options body (one canonical form, §38.1) -- never omitted just because they
equal their default.

Every `entities=` member below is a REAL entity id from
`fixtures/registry/home.json` (except `cover.bay_window_top`, which is this
bundle's OWN nested group's entity -- a real-world live example, §38.1:
a `cover.entryway_top` group containing `cover.bay_window_top`,
itself a group), so this fixture is also exercised by
`test_registry_validate.py::test_no_false_positives_on_golden_corpus`
(validation-clean, no `_DELIBERATELY_NOT_CLEAN` escape hatch needed).
"""

from hassle import (
    group_binary_sensor,
    group_button,
    group_cover,
    group_event,
    group_fan,
    group_light,
    group_lock,
    group_media_player,
    group_notify,
    group_sensor,
    group_switch,
    group_valve,
)

# Nested: "Bay Window Top" is declared first so "Entryway Top" can reference
# its produced entity (`cover.bay_window_top`) as a member -- a group whose
# members are themselves a group, a real-world live example (§38.1).
group_cover(
    name="Bay Window Top",
    entities=["cover.bedroom_blinds", "cover.living_room_blinds"],
)
group_cover(
    name="Entryway Top",
    entities=["cover.bay_window_top", "cover.garage_door"],
)
group_light(
    name="Downstairs Lights",
    entities=["light.hallway", "light.living_room", "light.kitchen"],
    all=True,
)
group_switch(
    name="Outdoor Switches",
    entities=["switch.garage_door_opener", "switch.office_monitor"],
    hide_members=True,
)
group_binary_sensor(
    name="Any Door Open",
    entities=["binary_sensor.door", "binary_sensor.back_door"],
)
group_sensor(
    name="Average Temp",
    entities=["sensor.living_room_temperature", "sensor.bedroom_temperature"],
    type="mean",
)
group_button(name="All Doorbells", entities=["button.restart"])
group_event(name="All Doorbell Events", entities=["event.doorbell"])
group_fan(name="All Fans", entities=["fan.bedroom", "fan.living_room"])
group_lock(name="All Locks", entities=["lock.front_door", "lock.back_door"])
group_media_player(
    name="Whole House Audio",
    entities=["media_player.living_room_speaker", "media_player.kitchen_speaker"],
)
group_notify(name="All Phones", entities=["notify.mobile_app_kai", "notify.mobile_app_spouse"])
# No `valve` entities exist in fixtures/registry/home.json at all (its
# registry snapshot has no valve domain coverage) -- validation only checks
# that a referenced entity id EXISTS, not that its domain matches the
# group's own flavor, so a real (if domain-mismatched) registry entity keeps
# this fixture validation-clean without needing to touch the shared registry
# fixture just for this one domain.
group_valve(name="Irrigation Zone A", entities=["cover.garage_door"])
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "group_binary_sensor:any_door_open": {
    "all": false,
    "entities": [
      "binary_sensor.door",
      "binary_sensor.back_door"
    ],
    "hide_members": false,
    "name": "Any Door Open"
  },
  "group_button:all_doorbells": {
    "entities": [
      "button.restart"
    ],
    "hide_members": false,
    "name": "All Doorbells"
  },
  "group_cover:bay_window_top": {
    "entities": [
      "cover.bedroom_blinds",
      "cover.living_room_blinds"
    ],
    "hide_members": false,
    "name": "Bay Window Top"
  },
  "group_cover:entryway_top": {
    "entities": [
      "cover.bay_window_top",
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Entryway Top"
  },
  "group_event:all_doorbell_events": {
    "entities": [
      "event.doorbell"
    ],
    "hide_members": false,
    "name": "All Doorbell Events"
  },
  "group_fan:all_fans": {
    "entities": [
      "fan.bedroom",
      "fan.living_room"
    ],
    "hide_members": false,
    "name": "All Fans"
  },
  "group_light:downstairs_lights": {
    "all": true,
    "entities": [
      "light.hallway",
      "light.living_room",
      "light.kitchen"
    ],
    "hide_members": false,
    "name": "Downstairs Lights"
  },
  "group_lock:all_locks": {
    "entities": [
      "lock.front_door",
      "lock.back_door"
    ],
    "hide_members": false,
    "name": "All Locks"
  },
  "group_media_player:whole_house_audio": {
    "entities": [
      "media_player.living_room_speaker",
      "media_player.kitchen_speaker"
    ],
    "hide_members": false,
    "name": "Whole House Audio"
  },
  "group_notify:all_phones": {
    "entities": [
      "notify.mobile_app_kai",
      "notify.mobile_app_spouse"
    ],
    "hide_members": false,
    "name": "All Phones"
  },
  "group_sensor:average_temp": {
    "entities": [
      "sensor.living_room_temperature",
      "sensor.bedroom_temperature"
    ],
    "hide_members": false,
    "name": "Average Temp",
    "type": "mean"
  },
  "group_switch:outdoor_switches": {
    "all": false,
    "entities": [
      "switch.garage_door_opener",
      "switch.office_monitor"
    ],
    "hide_members": true,
    "name": "Outdoor Switches"
  },
  "group_valve:irrigation_zone_a": {
    "entities": [
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Irrigation Zone A"
  }
}
```

### `group_cover`

Golden case: `fixtures/dsl/group_helper_declarations/`.

```python
"""Golden case: group-helper declarations for all twelve group flavors,
covering the three schema shapes (docs/internals/ha-api-notes.md §38.1) -- base (name/
entities/hide_members), +all (binary_sensor/light/switch), +type (sensor).

Identity: there is no `id=`/`unique_id=` kwarg, mirroring template helpers
(docs/internals/ha-api-notes.md §38.1) -- real HA's `group` config flow rejects an
unrecognized `unique_id` key outright. Identity is derived from `name`
(slugified): "Entryway Top" -> `group_cover:entryway_top`.

`hide_members`/`all` are always materialized explicitly in the compiled
options body (one canonical form, §38.1) -- never omitted just because they
equal their default.

Every `entities=` member below is a REAL entity id from
`fixtures/registry/home.json` (except `cover.bay_window_top`, which is this
bundle's OWN nested group's entity -- a real-world live example, §38.1:
a `cover.entryway_top` group containing `cover.bay_window_top`,
itself a group), so this fixture is also exercised by
`test_registry_validate.py::test_no_false_positives_on_golden_corpus`
(validation-clean, no `_DELIBERATELY_NOT_CLEAN` escape hatch needed).
"""

from hassle import (
    group_binary_sensor,
    group_button,
    group_cover,
    group_event,
    group_fan,
    group_light,
    group_lock,
    group_media_player,
    group_notify,
    group_sensor,
    group_switch,
    group_valve,
)

# Nested: "Bay Window Top" is declared first so "Entryway Top" can reference
# its produced entity (`cover.bay_window_top`) as a member -- a group whose
# members are themselves a group, a real-world live example (§38.1).
group_cover(
    name="Bay Window Top",
    entities=["cover.bedroom_blinds", "cover.living_room_blinds"],
)
group_cover(
    name="Entryway Top",
    entities=["cover.bay_window_top", "cover.garage_door"],
)
group_light(
    name="Downstairs Lights",
    entities=["light.hallway", "light.living_room", "light.kitchen"],
    all=True,
)
group_switch(
    name="Outdoor Switches",
    entities=["switch.garage_door_opener", "switch.office_monitor"],
    hide_members=True,
)
group_binary_sensor(
    name="Any Door Open",
    entities=["binary_sensor.door", "binary_sensor.back_door"],
)
group_sensor(
    name="Average Temp",
    entities=["sensor.living_room_temperature", "sensor.bedroom_temperature"],
    type="mean",
)
group_button(name="All Doorbells", entities=["button.restart"])
group_event(name="All Doorbell Events", entities=["event.doorbell"])
group_fan(name="All Fans", entities=["fan.bedroom", "fan.living_room"])
group_lock(name="All Locks", entities=["lock.front_door", "lock.back_door"])
group_media_player(
    name="Whole House Audio",
    entities=["media_player.living_room_speaker", "media_player.kitchen_speaker"],
)
group_notify(name="All Phones", entities=["notify.mobile_app_kai", "notify.mobile_app_spouse"])
# No `valve` entities exist in fixtures/registry/home.json at all (its
# registry snapshot has no valve domain coverage) -- validation only checks
# that a referenced entity id EXISTS, not that its domain matches the
# group's own flavor, so a real (if domain-mismatched) registry entity keeps
# this fixture validation-clean without needing to touch the shared registry
# fixture just for this one domain.
group_valve(name="Irrigation Zone A", entities=["cover.garage_door"])
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "group_binary_sensor:any_door_open": {
    "all": false,
    "entities": [
      "binary_sensor.door",
      "binary_sensor.back_door"
    ],
    "hide_members": false,
    "name": "Any Door Open"
  },
  "group_button:all_doorbells": {
    "entities": [
      "button.restart"
    ],
    "hide_members": false,
    "name": "All Doorbells"
  },
  "group_cover:bay_window_top": {
    "entities": [
      "cover.bedroom_blinds",
      "cover.living_room_blinds"
    ],
    "hide_members": false,
    "name": "Bay Window Top"
  },
  "group_cover:entryway_top": {
    "entities": [
      "cover.bay_window_top",
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Entryway Top"
  },
  "group_event:all_doorbell_events": {
    "entities": [
      "event.doorbell"
    ],
    "hide_members": false,
    "name": "All Doorbell Events"
  },
  "group_fan:all_fans": {
    "entities": [
      "fan.bedroom",
      "fan.living_room"
    ],
    "hide_members": false,
    "name": "All Fans"
  },
  "group_light:downstairs_lights": {
    "all": true,
    "entities": [
      "light.hallway",
      "light.living_room",
      "light.kitchen"
    ],
    "hide_members": false,
    "name": "Downstairs Lights"
  },
  "group_lock:all_locks": {
    "entities": [
      "lock.front_door",
      "lock.back_door"
    ],
    "hide_members": false,
    "name": "All Locks"
  },
  "group_media_player:whole_house_audio": {
    "entities": [
      "media_player.living_room_speaker",
      "media_player.kitchen_speaker"
    ],
    "hide_members": false,
    "name": "Whole House Audio"
  },
  "group_notify:all_phones": {
    "entities": [
      "notify.mobile_app_kai",
      "notify.mobile_app_spouse"
    ],
    "hide_members": false,
    "name": "All Phones"
  },
  "group_sensor:average_temp": {
    "entities": [
      "sensor.living_room_temperature",
      "sensor.bedroom_temperature"
    ],
    "hide_members": false,
    "name": "Average Temp",
    "type": "mean"
  },
  "group_switch:outdoor_switches": {
    "all": false,
    "entities": [
      "switch.garage_door_opener",
      "switch.office_monitor"
    ],
    "hide_members": true,
    "name": "Outdoor Switches"
  },
  "group_valve:irrigation_zone_a": {
    "entities": [
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Irrigation Zone A"
  }
}
```

### `group_event`

Golden case: `fixtures/dsl/group_helper_declarations/`.

```python
"""Golden case: group-helper declarations for all twelve group flavors,
covering the three schema shapes (docs/internals/ha-api-notes.md §38.1) -- base (name/
entities/hide_members), +all (binary_sensor/light/switch), +type (sensor).

Identity: there is no `id=`/`unique_id=` kwarg, mirroring template helpers
(docs/internals/ha-api-notes.md §38.1) -- real HA's `group` config flow rejects an
unrecognized `unique_id` key outright. Identity is derived from `name`
(slugified): "Entryway Top" -> `group_cover:entryway_top`.

`hide_members`/`all` are always materialized explicitly in the compiled
options body (one canonical form, §38.1) -- never omitted just because they
equal their default.

Every `entities=` member below is a REAL entity id from
`fixtures/registry/home.json` (except `cover.bay_window_top`, which is this
bundle's OWN nested group's entity -- a real-world live example, §38.1:
a `cover.entryway_top` group containing `cover.bay_window_top`,
itself a group), so this fixture is also exercised by
`test_registry_validate.py::test_no_false_positives_on_golden_corpus`
(validation-clean, no `_DELIBERATELY_NOT_CLEAN` escape hatch needed).
"""

from hassle import (
    group_binary_sensor,
    group_button,
    group_cover,
    group_event,
    group_fan,
    group_light,
    group_lock,
    group_media_player,
    group_notify,
    group_sensor,
    group_switch,
    group_valve,
)

# Nested: "Bay Window Top" is declared first so "Entryway Top" can reference
# its produced entity (`cover.bay_window_top`) as a member -- a group whose
# members are themselves a group, a real-world live example (§38.1).
group_cover(
    name="Bay Window Top",
    entities=["cover.bedroom_blinds", "cover.living_room_blinds"],
)
group_cover(
    name="Entryway Top",
    entities=["cover.bay_window_top", "cover.garage_door"],
)
group_light(
    name="Downstairs Lights",
    entities=["light.hallway", "light.living_room", "light.kitchen"],
    all=True,
)
group_switch(
    name="Outdoor Switches",
    entities=["switch.garage_door_opener", "switch.office_monitor"],
    hide_members=True,
)
group_binary_sensor(
    name="Any Door Open",
    entities=["binary_sensor.door", "binary_sensor.back_door"],
)
group_sensor(
    name="Average Temp",
    entities=["sensor.living_room_temperature", "sensor.bedroom_temperature"],
    type="mean",
)
group_button(name="All Doorbells", entities=["button.restart"])
group_event(name="All Doorbell Events", entities=["event.doorbell"])
group_fan(name="All Fans", entities=["fan.bedroom", "fan.living_room"])
group_lock(name="All Locks", entities=["lock.front_door", "lock.back_door"])
group_media_player(
    name="Whole House Audio",
    entities=["media_player.living_room_speaker", "media_player.kitchen_speaker"],
)
group_notify(name="All Phones", entities=["notify.mobile_app_kai", "notify.mobile_app_spouse"])
# No `valve` entities exist in fixtures/registry/home.json at all (its
# registry snapshot has no valve domain coverage) -- validation only checks
# that a referenced entity id EXISTS, not that its domain matches the
# group's own flavor, so a real (if domain-mismatched) registry entity keeps
# this fixture validation-clean without needing to touch the shared registry
# fixture just for this one domain.
group_valve(name="Irrigation Zone A", entities=["cover.garage_door"])
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "group_binary_sensor:any_door_open": {
    "all": false,
    "entities": [
      "binary_sensor.door",
      "binary_sensor.back_door"
    ],
    "hide_members": false,
    "name": "Any Door Open"
  },
  "group_button:all_doorbells": {
    "entities": [
      "button.restart"
    ],
    "hide_members": false,
    "name": "All Doorbells"
  },
  "group_cover:bay_window_top": {
    "entities": [
      "cover.bedroom_blinds",
      "cover.living_room_blinds"
    ],
    "hide_members": false,
    "name": "Bay Window Top"
  },
  "group_cover:entryway_top": {
    "entities": [
      "cover.bay_window_top",
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Entryway Top"
  },
  "group_event:all_doorbell_events": {
    "entities": [
      "event.doorbell"
    ],
    "hide_members": false,
    "name": "All Doorbell Events"
  },
  "group_fan:all_fans": {
    "entities": [
      "fan.bedroom",
      "fan.living_room"
    ],
    "hide_members": false,
    "name": "All Fans"
  },
  "group_light:downstairs_lights": {
    "all": true,
    "entities": [
      "light.hallway",
      "light.living_room",
      "light.kitchen"
    ],
    "hide_members": false,
    "name": "Downstairs Lights"
  },
  "group_lock:all_locks": {
    "entities": [
      "lock.front_door",
      "lock.back_door"
    ],
    "hide_members": false,
    "name": "All Locks"
  },
  "group_media_player:whole_house_audio": {
    "entities": [
      "media_player.living_room_speaker",
      "media_player.kitchen_speaker"
    ],
    "hide_members": false,
    "name": "Whole House Audio"
  },
  "group_notify:all_phones": {
    "entities": [
      "notify.mobile_app_kai",
      "notify.mobile_app_spouse"
    ],
    "hide_members": false,
    "name": "All Phones"
  },
  "group_sensor:average_temp": {
    "entities": [
      "sensor.living_room_temperature",
      "sensor.bedroom_temperature"
    ],
    "hide_members": false,
    "name": "Average Temp",
    "type": "mean"
  },
  "group_switch:outdoor_switches": {
    "all": false,
    "entities": [
      "switch.garage_door_opener",
      "switch.office_monitor"
    ],
    "hide_members": true,
    "name": "Outdoor Switches"
  },
  "group_valve:irrigation_zone_a": {
    "entities": [
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Irrigation Zone A"
  }
}
```

### `group_fan`

Golden case: `fixtures/dsl/group_helper_declarations/`.

```python
"""Golden case: group-helper declarations for all twelve group flavors,
covering the three schema shapes (docs/internals/ha-api-notes.md §38.1) -- base (name/
entities/hide_members), +all (binary_sensor/light/switch), +type (sensor).

Identity: there is no `id=`/`unique_id=` kwarg, mirroring template helpers
(docs/internals/ha-api-notes.md §38.1) -- real HA's `group` config flow rejects an
unrecognized `unique_id` key outright. Identity is derived from `name`
(slugified): "Entryway Top" -> `group_cover:entryway_top`.

`hide_members`/`all` are always materialized explicitly in the compiled
options body (one canonical form, §38.1) -- never omitted just because they
equal their default.

Every `entities=` member below is a REAL entity id from
`fixtures/registry/home.json` (except `cover.bay_window_top`, which is this
bundle's OWN nested group's entity -- a real-world live example, §38.1:
a `cover.entryway_top` group containing `cover.bay_window_top`,
itself a group), so this fixture is also exercised by
`test_registry_validate.py::test_no_false_positives_on_golden_corpus`
(validation-clean, no `_DELIBERATELY_NOT_CLEAN` escape hatch needed).
"""

from hassle import (
    group_binary_sensor,
    group_button,
    group_cover,
    group_event,
    group_fan,
    group_light,
    group_lock,
    group_media_player,
    group_notify,
    group_sensor,
    group_switch,
    group_valve,
)

# Nested: "Bay Window Top" is declared first so "Entryway Top" can reference
# its produced entity (`cover.bay_window_top`) as a member -- a group whose
# members are themselves a group, a real-world live example (§38.1).
group_cover(
    name="Bay Window Top",
    entities=["cover.bedroom_blinds", "cover.living_room_blinds"],
)
group_cover(
    name="Entryway Top",
    entities=["cover.bay_window_top", "cover.garage_door"],
)
group_light(
    name="Downstairs Lights",
    entities=["light.hallway", "light.living_room", "light.kitchen"],
    all=True,
)
group_switch(
    name="Outdoor Switches",
    entities=["switch.garage_door_opener", "switch.office_monitor"],
    hide_members=True,
)
group_binary_sensor(
    name="Any Door Open",
    entities=["binary_sensor.door", "binary_sensor.back_door"],
)
group_sensor(
    name="Average Temp",
    entities=["sensor.living_room_temperature", "sensor.bedroom_temperature"],
    type="mean",
)
group_button(name="All Doorbells", entities=["button.restart"])
group_event(name="All Doorbell Events", entities=["event.doorbell"])
group_fan(name="All Fans", entities=["fan.bedroom", "fan.living_room"])
group_lock(name="All Locks", entities=["lock.front_door", "lock.back_door"])
group_media_player(
    name="Whole House Audio",
    entities=["media_player.living_room_speaker", "media_player.kitchen_speaker"],
)
group_notify(name="All Phones", entities=["notify.mobile_app_kai", "notify.mobile_app_spouse"])
# No `valve` entities exist in fixtures/registry/home.json at all (its
# registry snapshot has no valve domain coverage) -- validation only checks
# that a referenced entity id EXISTS, not that its domain matches the
# group's own flavor, so a real (if domain-mismatched) registry entity keeps
# this fixture validation-clean without needing to touch the shared registry
# fixture just for this one domain.
group_valve(name="Irrigation Zone A", entities=["cover.garage_door"])
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "group_binary_sensor:any_door_open": {
    "all": false,
    "entities": [
      "binary_sensor.door",
      "binary_sensor.back_door"
    ],
    "hide_members": false,
    "name": "Any Door Open"
  },
  "group_button:all_doorbells": {
    "entities": [
      "button.restart"
    ],
    "hide_members": false,
    "name": "All Doorbells"
  },
  "group_cover:bay_window_top": {
    "entities": [
      "cover.bedroom_blinds",
      "cover.living_room_blinds"
    ],
    "hide_members": false,
    "name": "Bay Window Top"
  },
  "group_cover:entryway_top": {
    "entities": [
      "cover.bay_window_top",
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Entryway Top"
  },
  "group_event:all_doorbell_events": {
    "entities": [
      "event.doorbell"
    ],
    "hide_members": false,
    "name": "All Doorbell Events"
  },
  "group_fan:all_fans": {
    "entities": [
      "fan.bedroom",
      "fan.living_room"
    ],
    "hide_members": false,
    "name": "All Fans"
  },
  "group_light:downstairs_lights": {
    "all": true,
    "entities": [
      "light.hallway",
      "light.living_room",
      "light.kitchen"
    ],
    "hide_members": false,
    "name": "Downstairs Lights"
  },
  "group_lock:all_locks": {
    "entities": [
      "lock.front_door",
      "lock.back_door"
    ],
    "hide_members": false,
    "name": "All Locks"
  },
  "group_media_player:whole_house_audio": {
    "entities": [
      "media_player.living_room_speaker",
      "media_player.kitchen_speaker"
    ],
    "hide_members": false,
    "name": "Whole House Audio"
  },
  "group_notify:all_phones": {
    "entities": [
      "notify.mobile_app_kai",
      "notify.mobile_app_spouse"
    ],
    "hide_members": false,
    "name": "All Phones"
  },
  "group_sensor:average_temp": {
    "entities": [
      "sensor.living_room_temperature",
      "sensor.bedroom_temperature"
    ],
    "hide_members": false,
    "name": "Average Temp",
    "type": "mean"
  },
  "group_switch:outdoor_switches": {
    "all": false,
    "entities": [
      "switch.garage_door_opener",
      "switch.office_monitor"
    ],
    "hide_members": true,
    "name": "Outdoor Switches"
  },
  "group_valve:irrigation_zone_a": {
    "entities": [
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Irrigation Zone A"
  }
}
```

### `group_light`

Golden case: `fixtures/dsl/group_helper_declarations/`.

```python
"""Golden case: group-helper declarations for all twelve group flavors,
covering the three schema shapes (docs/internals/ha-api-notes.md §38.1) -- base (name/
entities/hide_members), +all (binary_sensor/light/switch), +type (sensor).

Identity: there is no `id=`/`unique_id=` kwarg, mirroring template helpers
(docs/internals/ha-api-notes.md §38.1) -- real HA's `group` config flow rejects an
unrecognized `unique_id` key outright. Identity is derived from `name`
(slugified): "Entryway Top" -> `group_cover:entryway_top`.

`hide_members`/`all` are always materialized explicitly in the compiled
options body (one canonical form, §38.1) -- never omitted just because they
equal their default.

Every `entities=` member below is a REAL entity id from
`fixtures/registry/home.json` (except `cover.bay_window_top`, which is this
bundle's OWN nested group's entity -- a real-world live example, §38.1:
a `cover.entryway_top` group containing `cover.bay_window_top`,
itself a group), so this fixture is also exercised by
`test_registry_validate.py::test_no_false_positives_on_golden_corpus`
(validation-clean, no `_DELIBERATELY_NOT_CLEAN` escape hatch needed).
"""

from hassle import (
    group_binary_sensor,
    group_button,
    group_cover,
    group_event,
    group_fan,
    group_light,
    group_lock,
    group_media_player,
    group_notify,
    group_sensor,
    group_switch,
    group_valve,
)

# Nested: "Bay Window Top" is declared first so "Entryway Top" can reference
# its produced entity (`cover.bay_window_top`) as a member -- a group whose
# members are themselves a group, a real-world live example (§38.1).
group_cover(
    name="Bay Window Top",
    entities=["cover.bedroom_blinds", "cover.living_room_blinds"],
)
group_cover(
    name="Entryway Top",
    entities=["cover.bay_window_top", "cover.garage_door"],
)
group_light(
    name="Downstairs Lights",
    entities=["light.hallway", "light.living_room", "light.kitchen"],
    all=True,
)
group_switch(
    name="Outdoor Switches",
    entities=["switch.garage_door_opener", "switch.office_monitor"],
    hide_members=True,
)
group_binary_sensor(
    name="Any Door Open",
    entities=["binary_sensor.door", "binary_sensor.back_door"],
)
group_sensor(
    name="Average Temp",
    entities=["sensor.living_room_temperature", "sensor.bedroom_temperature"],
    type="mean",
)
group_button(name="All Doorbells", entities=["button.restart"])
group_event(name="All Doorbell Events", entities=["event.doorbell"])
group_fan(name="All Fans", entities=["fan.bedroom", "fan.living_room"])
group_lock(name="All Locks", entities=["lock.front_door", "lock.back_door"])
group_media_player(
    name="Whole House Audio",
    entities=["media_player.living_room_speaker", "media_player.kitchen_speaker"],
)
group_notify(name="All Phones", entities=["notify.mobile_app_kai", "notify.mobile_app_spouse"])
# No `valve` entities exist in fixtures/registry/home.json at all (its
# registry snapshot has no valve domain coverage) -- validation only checks
# that a referenced entity id EXISTS, not that its domain matches the
# group's own flavor, so a real (if domain-mismatched) registry entity keeps
# this fixture validation-clean without needing to touch the shared registry
# fixture just for this one domain.
group_valve(name="Irrigation Zone A", entities=["cover.garage_door"])
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "group_binary_sensor:any_door_open": {
    "all": false,
    "entities": [
      "binary_sensor.door",
      "binary_sensor.back_door"
    ],
    "hide_members": false,
    "name": "Any Door Open"
  },
  "group_button:all_doorbells": {
    "entities": [
      "button.restart"
    ],
    "hide_members": false,
    "name": "All Doorbells"
  },
  "group_cover:bay_window_top": {
    "entities": [
      "cover.bedroom_blinds",
      "cover.living_room_blinds"
    ],
    "hide_members": false,
    "name": "Bay Window Top"
  },
  "group_cover:entryway_top": {
    "entities": [
      "cover.bay_window_top",
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Entryway Top"
  },
  "group_event:all_doorbell_events": {
    "entities": [
      "event.doorbell"
    ],
    "hide_members": false,
    "name": "All Doorbell Events"
  },
  "group_fan:all_fans": {
    "entities": [
      "fan.bedroom",
      "fan.living_room"
    ],
    "hide_members": false,
    "name": "All Fans"
  },
  "group_light:downstairs_lights": {
    "all": true,
    "entities": [
      "light.hallway",
      "light.living_room",
      "light.kitchen"
    ],
    "hide_members": false,
    "name": "Downstairs Lights"
  },
  "group_lock:all_locks": {
    "entities": [
      "lock.front_door",
      "lock.back_door"
    ],
    "hide_members": false,
    "name": "All Locks"
  },
  "group_media_player:whole_house_audio": {
    "entities": [
      "media_player.living_room_speaker",
      "media_player.kitchen_speaker"
    ],
    "hide_members": false,
    "name": "Whole House Audio"
  },
  "group_notify:all_phones": {
    "entities": [
      "notify.mobile_app_kai",
      "notify.mobile_app_spouse"
    ],
    "hide_members": false,
    "name": "All Phones"
  },
  "group_sensor:average_temp": {
    "entities": [
      "sensor.living_room_temperature",
      "sensor.bedroom_temperature"
    ],
    "hide_members": false,
    "name": "Average Temp",
    "type": "mean"
  },
  "group_switch:outdoor_switches": {
    "all": false,
    "entities": [
      "switch.garage_door_opener",
      "switch.office_monitor"
    ],
    "hide_members": true,
    "name": "Outdoor Switches"
  },
  "group_valve:irrigation_zone_a": {
    "entities": [
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Irrigation Zone A"
  }
}
```

### `group_lock`

Golden case: `fixtures/dsl/group_helper_declarations/`.

```python
"""Golden case: group-helper declarations for all twelve group flavors,
covering the three schema shapes (docs/internals/ha-api-notes.md §38.1) -- base (name/
entities/hide_members), +all (binary_sensor/light/switch), +type (sensor).

Identity: there is no `id=`/`unique_id=` kwarg, mirroring template helpers
(docs/internals/ha-api-notes.md §38.1) -- real HA's `group` config flow rejects an
unrecognized `unique_id` key outright. Identity is derived from `name`
(slugified): "Entryway Top" -> `group_cover:entryway_top`.

`hide_members`/`all` are always materialized explicitly in the compiled
options body (one canonical form, §38.1) -- never omitted just because they
equal their default.

Every `entities=` member below is a REAL entity id from
`fixtures/registry/home.json` (except `cover.bay_window_top`, which is this
bundle's OWN nested group's entity -- a real-world live example, §38.1:
a `cover.entryway_top` group containing `cover.bay_window_top`,
itself a group), so this fixture is also exercised by
`test_registry_validate.py::test_no_false_positives_on_golden_corpus`
(validation-clean, no `_DELIBERATELY_NOT_CLEAN` escape hatch needed).
"""

from hassle import (
    group_binary_sensor,
    group_button,
    group_cover,
    group_event,
    group_fan,
    group_light,
    group_lock,
    group_media_player,
    group_notify,
    group_sensor,
    group_switch,
    group_valve,
)

# Nested: "Bay Window Top" is declared first so "Entryway Top" can reference
# its produced entity (`cover.bay_window_top`) as a member -- a group whose
# members are themselves a group, a real-world live example (§38.1).
group_cover(
    name="Bay Window Top",
    entities=["cover.bedroom_blinds", "cover.living_room_blinds"],
)
group_cover(
    name="Entryway Top",
    entities=["cover.bay_window_top", "cover.garage_door"],
)
group_light(
    name="Downstairs Lights",
    entities=["light.hallway", "light.living_room", "light.kitchen"],
    all=True,
)
group_switch(
    name="Outdoor Switches",
    entities=["switch.garage_door_opener", "switch.office_monitor"],
    hide_members=True,
)
group_binary_sensor(
    name="Any Door Open",
    entities=["binary_sensor.door", "binary_sensor.back_door"],
)
group_sensor(
    name="Average Temp",
    entities=["sensor.living_room_temperature", "sensor.bedroom_temperature"],
    type="mean",
)
group_button(name="All Doorbells", entities=["button.restart"])
group_event(name="All Doorbell Events", entities=["event.doorbell"])
group_fan(name="All Fans", entities=["fan.bedroom", "fan.living_room"])
group_lock(name="All Locks", entities=["lock.front_door", "lock.back_door"])
group_media_player(
    name="Whole House Audio",
    entities=["media_player.living_room_speaker", "media_player.kitchen_speaker"],
)
group_notify(name="All Phones", entities=["notify.mobile_app_kai", "notify.mobile_app_spouse"])
# No `valve` entities exist in fixtures/registry/home.json at all (its
# registry snapshot has no valve domain coverage) -- validation only checks
# that a referenced entity id EXISTS, not that its domain matches the
# group's own flavor, so a real (if domain-mismatched) registry entity keeps
# this fixture validation-clean without needing to touch the shared registry
# fixture just for this one domain.
group_valve(name="Irrigation Zone A", entities=["cover.garage_door"])
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "group_binary_sensor:any_door_open": {
    "all": false,
    "entities": [
      "binary_sensor.door",
      "binary_sensor.back_door"
    ],
    "hide_members": false,
    "name": "Any Door Open"
  },
  "group_button:all_doorbells": {
    "entities": [
      "button.restart"
    ],
    "hide_members": false,
    "name": "All Doorbells"
  },
  "group_cover:bay_window_top": {
    "entities": [
      "cover.bedroom_blinds",
      "cover.living_room_blinds"
    ],
    "hide_members": false,
    "name": "Bay Window Top"
  },
  "group_cover:entryway_top": {
    "entities": [
      "cover.bay_window_top",
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Entryway Top"
  },
  "group_event:all_doorbell_events": {
    "entities": [
      "event.doorbell"
    ],
    "hide_members": false,
    "name": "All Doorbell Events"
  },
  "group_fan:all_fans": {
    "entities": [
      "fan.bedroom",
      "fan.living_room"
    ],
    "hide_members": false,
    "name": "All Fans"
  },
  "group_light:downstairs_lights": {
    "all": true,
    "entities": [
      "light.hallway",
      "light.living_room",
      "light.kitchen"
    ],
    "hide_members": false,
    "name": "Downstairs Lights"
  },
  "group_lock:all_locks": {
    "entities": [
      "lock.front_door",
      "lock.back_door"
    ],
    "hide_members": false,
    "name": "All Locks"
  },
  "group_media_player:whole_house_audio": {
    "entities": [
      "media_player.living_room_speaker",
      "media_player.kitchen_speaker"
    ],
    "hide_members": false,
    "name": "Whole House Audio"
  },
  "group_notify:all_phones": {
    "entities": [
      "notify.mobile_app_kai",
      "notify.mobile_app_spouse"
    ],
    "hide_members": false,
    "name": "All Phones"
  },
  "group_sensor:average_temp": {
    "entities": [
      "sensor.living_room_temperature",
      "sensor.bedroom_temperature"
    ],
    "hide_members": false,
    "name": "Average Temp",
    "type": "mean"
  },
  "group_switch:outdoor_switches": {
    "all": false,
    "entities": [
      "switch.garage_door_opener",
      "switch.office_monitor"
    ],
    "hide_members": true,
    "name": "Outdoor Switches"
  },
  "group_valve:irrigation_zone_a": {
    "entities": [
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Irrigation Zone A"
  }
}
```

### `group_media_player`

Golden case: `fixtures/dsl/group_helper_declarations/`.

```python
"""Golden case: group-helper declarations for all twelve group flavors,
covering the three schema shapes (docs/internals/ha-api-notes.md §38.1) -- base (name/
entities/hide_members), +all (binary_sensor/light/switch), +type (sensor).

Identity: there is no `id=`/`unique_id=` kwarg, mirroring template helpers
(docs/internals/ha-api-notes.md §38.1) -- real HA's `group` config flow rejects an
unrecognized `unique_id` key outright. Identity is derived from `name`
(slugified): "Entryway Top" -> `group_cover:entryway_top`.

`hide_members`/`all` are always materialized explicitly in the compiled
options body (one canonical form, §38.1) -- never omitted just because they
equal their default.

Every `entities=` member below is a REAL entity id from
`fixtures/registry/home.json` (except `cover.bay_window_top`, which is this
bundle's OWN nested group's entity -- a real-world live example, §38.1:
a `cover.entryway_top` group containing `cover.bay_window_top`,
itself a group), so this fixture is also exercised by
`test_registry_validate.py::test_no_false_positives_on_golden_corpus`
(validation-clean, no `_DELIBERATELY_NOT_CLEAN` escape hatch needed).
"""

from hassle import (
    group_binary_sensor,
    group_button,
    group_cover,
    group_event,
    group_fan,
    group_light,
    group_lock,
    group_media_player,
    group_notify,
    group_sensor,
    group_switch,
    group_valve,
)

# Nested: "Bay Window Top" is declared first so "Entryway Top" can reference
# its produced entity (`cover.bay_window_top`) as a member -- a group whose
# members are themselves a group, a real-world live example (§38.1).
group_cover(
    name="Bay Window Top",
    entities=["cover.bedroom_blinds", "cover.living_room_blinds"],
)
group_cover(
    name="Entryway Top",
    entities=["cover.bay_window_top", "cover.garage_door"],
)
group_light(
    name="Downstairs Lights",
    entities=["light.hallway", "light.living_room", "light.kitchen"],
    all=True,
)
group_switch(
    name="Outdoor Switches",
    entities=["switch.garage_door_opener", "switch.office_monitor"],
    hide_members=True,
)
group_binary_sensor(
    name="Any Door Open",
    entities=["binary_sensor.door", "binary_sensor.back_door"],
)
group_sensor(
    name="Average Temp",
    entities=["sensor.living_room_temperature", "sensor.bedroom_temperature"],
    type="mean",
)
group_button(name="All Doorbells", entities=["button.restart"])
group_event(name="All Doorbell Events", entities=["event.doorbell"])
group_fan(name="All Fans", entities=["fan.bedroom", "fan.living_room"])
group_lock(name="All Locks", entities=["lock.front_door", "lock.back_door"])
group_media_player(
    name="Whole House Audio",
    entities=["media_player.living_room_speaker", "media_player.kitchen_speaker"],
)
group_notify(name="All Phones", entities=["notify.mobile_app_kai", "notify.mobile_app_spouse"])
# No `valve` entities exist in fixtures/registry/home.json at all (its
# registry snapshot has no valve domain coverage) -- validation only checks
# that a referenced entity id EXISTS, not that its domain matches the
# group's own flavor, so a real (if domain-mismatched) registry entity keeps
# this fixture validation-clean without needing to touch the shared registry
# fixture just for this one domain.
group_valve(name="Irrigation Zone A", entities=["cover.garage_door"])
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "group_binary_sensor:any_door_open": {
    "all": false,
    "entities": [
      "binary_sensor.door",
      "binary_sensor.back_door"
    ],
    "hide_members": false,
    "name": "Any Door Open"
  },
  "group_button:all_doorbells": {
    "entities": [
      "button.restart"
    ],
    "hide_members": false,
    "name": "All Doorbells"
  },
  "group_cover:bay_window_top": {
    "entities": [
      "cover.bedroom_blinds",
      "cover.living_room_blinds"
    ],
    "hide_members": false,
    "name": "Bay Window Top"
  },
  "group_cover:entryway_top": {
    "entities": [
      "cover.bay_window_top",
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Entryway Top"
  },
  "group_event:all_doorbell_events": {
    "entities": [
      "event.doorbell"
    ],
    "hide_members": false,
    "name": "All Doorbell Events"
  },
  "group_fan:all_fans": {
    "entities": [
      "fan.bedroom",
      "fan.living_room"
    ],
    "hide_members": false,
    "name": "All Fans"
  },
  "group_light:downstairs_lights": {
    "all": true,
    "entities": [
      "light.hallway",
      "light.living_room",
      "light.kitchen"
    ],
    "hide_members": false,
    "name": "Downstairs Lights"
  },
  "group_lock:all_locks": {
    "entities": [
      "lock.front_door",
      "lock.back_door"
    ],
    "hide_members": false,
    "name": "All Locks"
  },
  "group_media_player:whole_house_audio": {
    "entities": [
      "media_player.living_room_speaker",
      "media_player.kitchen_speaker"
    ],
    "hide_members": false,
    "name": "Whole House Audio"
  },
  "group_notify:all_phones": {
    "entities": [
      "notify.mobile_app_kai",
      "notify.mobile_app_spouse"
    ],
    "hide_members": false,
    "name": "All Phones"
  },
  "group_sensor:average_temp": {
    "entities": [
      "sensor.living_room_temperature",
      "sensor.bedroom_temperature"
    ],
    "hide_members": false,
    "name": "Average Temp",
    "type": "mean"
  },
  "group_switch:outdoor_switches": {
    "all": false,
    "entities": [
      "switch.garage_door_opener",
      "switch.office_monitor"
    ],
    "hide_members": true,
    "name": "Outdoor Switches"
  },
  "group_valve:irrigation_zone_a": {
    "entities": [
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Irrigation Zone A"
  }
}
```

### `group_notify`

Golden case: `fixtures/dsl/group_helper_declarations/`.

```python
"""Golden case: group-helper declarations for all twelve group flavors,
covering the three schema shapes (docs/internals/ha-api-notes.md §38.1) -- base (name/
entities/hide_members), +all (binary_sensor/light/switch), +type (sensor).

Identity: there is no `id=`/`unique_id=` kwarg, mirroring template helpers
(docs/internals/ha-api-notes.md §38.1) -- real HA's `group` config flow rejects an
unrecognized `unique_id` key outright. Identity is derived from `name`
(slugified): "Entryway Top" -> `group_cover:entryway_top`.

`hide_members`/`all` are always materialized explicitly in the compiled
options body (one canonical form, §38.1) -- never omitted just because they
equal their default.

Every `entities=` member below is a REAL entity id from
`fixtures/registry/home.json` (except `cover.bay_window_top`, which is this
bundle's OWN nested group's entity -- a real-world live example, §38.1:
a `cover.entryway_top` group containing `cover.bay_window_top`,
itself a group), so this fixture is also exercised by
`test_registry_validate.py::test_no_false_positives_on_golden_corpus`
(validation-clean, no `_DELIBERATELY_NOT_CLEAN` escape hatch needed).
"""

from hassle import (
    group_binary_sensor,
    group_button,
    group_cover,
    group_event,
    group_fan,
    group_light,
    group_lock,
    group_media_player,
    group_notify,
    group_sensor,
    group_switch,
    group_valve,
)

# Nested: "Bay Window Top" is declared first so "Entryway Top" can reference
# its produced entity (`cover.bay_window_top`) as a member -- a group whose
# members are themselves a group, a real-world live example (§38.1).
group_cover(
    name="Bay Window Top",
    entities=["cover.bedroom_blinds", "cover.living_room_blinds"],
)
group_cover(
    name="Entryway Top",
    entities=["cover.bay_window_top", "cover.garage_door"],
)
group_light(
    name="Downstairs Lights",
    entities=["light.hallway", "light.living_room", "light.kitchen"],
    all=True,
)
group_switch(
    name="Outdoor Switches",
    entities=["switch.garage_door_opener", "switch.office_monitor"],
    hide_members=True,
)
group_binary_sensor(
    name="Any Door Open",
    entities=["binary_sensor.door", "binary_sensor.back_door"],
)
group_sensor(
    name="Average Temp",
    entities=["sensor.living_room_temperature", "sensor.bedroom_temperature"],
    type="mean",
)
group_button(name="All Doorbells", entities=["button.restart"])
group_event(name="All Doorbell Events", entities=["event.doorbell"])
group_fan(name="All Fans", entities=["fan.bedroom", "fan.living_room"])
group_lock(name="All Locks", entities=["lock.front_door", "lock.back_door"])
group_media_player(
    name="Whole House Audio",
    entities=["media_player.living_room_speaker", "media_player.kitchen_speaker"],
)
group_notify(name="All Phones", entities=["notify.mobile_app_kai", "notify.mobile_app_spouse"])
# No `valve` entities exist in fixtures/registry/home.json at all (its
# registry snapshot has no valve domain coverage) -- validation only checks
# that a referenced entity id EXISTS, not that its domain matches the
# group's own flavor, so a real (if domain-mismatched) registry entity keeps
# this fixture validation-clean without needing to touch the shared registry
# fixture just for this one domain.
group_valve(name="Irrigation Zone A", entities=["cover.garage_door"])
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "group_binary_sensor:any_door_open": {
    "all": false,
    "entities": [
      "binary_sensor.door",
      "binary_sensor.back_door"
    ],
    "hide_members": false,
    "name": "Any Door Open"
  },
  "group_button:all_doorbells": {
    "entities": [
      "button.restart"
    ],
    "hide_members": false,
    "name": "All Doorbells"
  },
  "group_cover:bay_window_top": {
    "entities": [
      "cover.bedroom_blinds",
      "cover.living_room_blinds"
    ],
    "hide_members": false,
    "name": "Bay Window Top"
  },
  "group_cover:entryway_top": {
    "entities": [
      "cover.bay_window_top",
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Entryway Top"
  },
  "group_event:all_doorbell_events": {
    "entities": [
      "event.doorbell"
    ],
    "hide_members": false,
    "name": "All Doorbell Events"
  },
  "group_fan:all_fans": {
    "entities": [
      "fan.bedroom",
      "fan.living_room"
    ],
    "hide_members": false,
    "name": "All Fans"
  },
  "group_light:downstairs_lights": {
    "all": true,
    "entities": [
      "light.hallway",
      "light.living_room",
      "light.kitchen"
    ],
    "hide_members": false,
    "name": "Downstairs Lights"
  },
  "group_lock:all_locks": {
    "entities": [
      "lock.front_door",
      "lock.back_door"
    ],
    "hide_members": false,
    "name": "All Locks"
  },
  "group_media_player:whole_house_audio": {
    "entities": [
      "media_player.living_room_speaker",
      "media_player.kitchen_speaker"
    ],
    "hide_members": false,
    "name": "Whole House Audio"
  },
  "group_notify:all_phones": {
    "entities": [
      "notify.mobile_app_kai",
      "notify.mobile_app_spouse"
    ],
    "hide_members": false,
    "name": "All Phones"
  },
  "group_sensor:average_temp": {
    "entities": [
      "sensor.living_room_temperature",
      "sensor.bedroom_temperature"
    ],
    "hide_members": false,
    "name": "Average Temp",
    "type": "mean"
  },
  "group_switch:outdoor_switches": {
    "all": false,
    "entities": [
      "switch.garage_door_opener",
      "switch.office_monitor"
    ],
    "hide_members": true,
    "name": "Outdoor Switches"
  },
  "group_valve:irrigation_zone_a": {
    "entities": [
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Irrigation Zone A"
  }
}
```

### `group_sensor`

Golden case: `fixtures/dsl/group_helper_declarations/`.

```python
"""Golden case: group-helper declarations for all twelve group flavors,
covering the three schema shapes (docs/internals/ha-api-notes.md §38.1) -- base (name/
entities/hide_members), +all (binary_sensor/light/switch), +type (sensor).

Identity: there is no `id=`/`unique_id=` kwarg, mirroring template helpers
(docs/internals/ha-api-notes.md §38.1) -- real HA's `group` config flow rejects an
unrecognized `unique_id` key outright. Identity is derived from `name`
(slugified): "Entryway Top" -> `group_cover:entryway_top`.

`hide_members`/`all` are always materialized explicitly in the compiled
options body (one canonical form, §38.1) -- never omitted just because they
equal their default.

Every `entities=` member below is a REAL entity id from
`fixtures/registry/home.json` (except `cover.bay_window_top`, which is this
bundle's OWN nested group's entity -- a real-world live example, §38.1:
a `cover.entryway_top` group containing `cover.bay_window_top`,
itself a group), so this fixture is also exercised by
`test_registry_validate.py::test_no_false_positives_on_golden_corpus`
(validation-clean, no `_DELIBERATELY_NOT_CLEAN` escape hatch needed).
"""

from hassle import (
    group_binary_sensor,
    group_button,
    group_cover,
    group_event,
    group_fan,
    group_light,
    group_lock,
    group_media_player,
    group_notify,
    group_sensor,
    group_switch,
    group_valve,
)

# Nested: "Bay Window Top" is declared first so "Entryway Top" can reference
# its produced entity (`cover.bay_window_top`) as a member -- a group whose
# members are themselves a group, a real-world live example (§38.1).
group_cover(
    name="Bay Window Top",
    entities=["cover.bedroom_blinds", "cover.living_room_blinds"],
)
group_cover(
    name="Entryway Top",
    entities=["cover.bay_window_top", "cover.garage_door"],
)
group_light(
    name="Downstairs Lights",
    entities=["light.hallway", "light.living_room", "light.kitchen"],
    all=True,
)
group_switch(
    name="Outdoor Switches",
    entities=["switch.garage_door_opener", "switch.office_monitor"],
    hide_members=True,
)
group_binary_sensor(
    name="Any Door Open",
    entities=["binary_sensor.door", "binary_sensor.back_door"],
)
group_sensor(
    name="Average Temp",
    entities=["sensor.living_room_temperature", "sensor.bedroom_temperature"],
    type="mean",
)
group_button(name="All Doorbells", entities=["button.restart"])
group_event(name="All Doorbell Events", entities=["event.doorbell"])
group_fan(name="All Fans", entities=["fan.bedroom", "fan.living_room"])
group_lock(name="All Locks", entities=["lock.front_door", "lock.back_door"])
group_media_player(
    name="Whole House Audio",
    entities=["media_player.living_room_speaker", "media_player.kitchen_speaker"],
)
group_notify(name="All Phones", entities=["notify.mobile_app_kai", "notify.mobile_app_spouse"])
# No `valve` entities exist in fixtures/registry/home.json at all (its
# registry snapshot has no valve domain coverage) -- validation only checks
# that a referenced entity id EXISTS, not that its domain matches the
# group's own flavor, so a real (if domain-mismatched) registry entity keeps
# this fixture validation-clean without needing to touch the shared registry
# fixture just for this one domain.
group_valve(name="Irrigation Zone A", entities=["cover.garage_door"])
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "group_binary_sensor:any_door_open": {
    "all": false,
    "entities": [
      "binary_sensor.door",
      "binary_sensor.back_door"
    ],
    "hide_members": false,
    "name": "Any Door Open"
  },
  "group_button:all_doorbells": {
    "entities": [
      "button.restart"
    ],
    "hide_members": false,
    "name": "All Doorbells"
  },
  "group_cover:bay_window_top": {
    "entities": [
      "cover.bedroom_blinds",
      "cover.living_room_blinds"
    ],
    "hide_members": false,
    "name": "Bay Window Top"
  },
  "group_cover:entryway_top": {
    "entities": [
      "cover.bay_window_top",
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Entryway Top"
  },
  "group_event:all_doorbell_events": {
    "entities": [
      "event.doorbell"
    ],
    "hide_members": false,
    "name": "All Doorbell Events"
  },
  "group_fan:all_fans": {
    "entities": [
      "fan.bedroom",
      "fan.living_room"
    ],
    "hide_members": false,
    "name": "All Fans"
  },
  "group_light:downstairs_lights": {
    "all": true,
    "entities": [
      "light.hallway",
      "light.living_room",
      "light.kitchen"
    ],
    "hide_members": false,
    "name": "Downstairs Lights"
  },
  "group_lock:all_locks": {
    "entities": [
      "lock.front_door",
      "lock.back_door"
    ],
    "hide_members": false,
    "name": "All Locks"
  },
  "group_media_player:whole_house_audio": {
    "entities": [
      "media_player.living_room_speaker",
      "media_player.kitchen_speaker"
    ],
    "hide_members": false,
    "name": "Whole House Audio"
  },
  "group_notify:all_phones": {
    "entities": [
      "notify.mobile_app_kai",
      "notify.mobile_app_spouse"
    ],
    "hide_members": false,
    "name": "All Phones"
  },
  "group_sensor:average_temp": {
    "entities": [
      "sensor.living_room_temperature",
      "sensor.bedroom_temperature"
    ],
    "hide_members": false,
    "name": "Average Temp",
    "type": "mean"
  },
  "group_switch:outdoor_switches": {
    "all": false,
    "entities": [
      "switch.garage_door_opener",
      "switch.office_monitor"
    ],
    "hide_members": true,
    "name": "Outdoor Switches"
  },
  "group_valve:irrigation_zone_a": {
    "entities": [
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Irrigation Zone A"
  }
}
```

### `group_switch`

Golden case: `fixtures/dsl/group_helper_declarations/`.

```python
"""Golden case: group-helper declarations for all twelve group flavors,
covering the three schema shapes (docs/internals/ha-api-notes.md §38.1) -- base (name/
entities/hide_members), +all (binary_sensor/light/switch), +type (sensor).

Identity: there is no `id=`/`unique_id=` kwarg, mirroring template helpers
(docs/internals/ha-api-notes.md §38.1) -- real HA's `group` config flow rejects an
unrecognized `unique_id` key outright. Identity is derived from `name`
(slugified): "Entryway Top" -> `group_cover:entryway_top`.

`hide_members`/`all` are always materialized explicitly in the compiled
options body (one canonical form, §38.1) -- never omitted just because they
equal their default.

Every `entities=` member below is a REAL entity id from
`fixtures/registry/home.json` (except `cover.bay_window_top`, which is this
bundle's OWN nested group's entity -- a real-world live example, §38.1:
a `cover.entryway_top` group containing `cover.bay_window_top`,
itself a group), so this fixture is also exercised by
`test_registry_validate.py::test_no_false_positives_on_golden_corpus`
(validation-clean, no `_DELIBERATELY_NOT_CLEAN` escape hatch needed).
"""

from hassle import (
    group_binary_sensor,
    group_button,
    group_cover,
    group_event,
    group_fan,
    group_light,
    group_lock,
    group_media_player,
    group_notify,
    group_sensor,
    group_switch,
    group_valve,
)

# Nested: "Bay Window Top" is declared first so "Entryway Top" can reference
# its produced entity (`cover.bay_window_top`) as a member -- a group whose
# members are themselves a group, a real-world live example (§38.1).
group_cover(
    name="Bay Window Top",
    entities=["cover.bedroom_blinds", "cover.living_room_blinds"],
)
group_cover(
    name="Entryway Top",
    entities=["cover.bay_window_top", "cover.garage_door"],
)
group_light(
    name="Downstairs Lights",
    entities=["light.hallway", "light.living_room", "light.kitchen"],
    all=True,
)
group_switch(
    name="Outdoor Switches",
    entities=["switch.garage_door_opener", "switch.office_monitor"],
    hide_members=True,
)
group_binary_sensor(
    name="Any Door Open",
    entities=["binary_sensor.door", "binary_sensor.back_door"],
)
group_sensor(
    name="Average Temp",
    entities=["sensor.living_room_temperature", "sensor.bedroom_temperature"],
    type="mean",
)
group_button(name="All Doorbells", entities=["button.restart"])
group_event(name="All Doorbell Events", entities=["event.doorbell"])
group_fan(name="All Fans", entities=["fan.bedroom", "fan.living_room"])
group_lock(name="All Locks", entities=["lock.front_door", "lock.back_door"])
group_media_player(
    name="Whole House Audio",
    entities=["media_player.living_room_speaker", "media_player.kitchen_speaker"],
)
group_notify(name="All Phones", entities=["notify.mobile_app_kai", "notify.mobile_app_spouse"])
# No `valve` entities exist in fixtures/registry/home.json at all (its
# registry snapshot has no valve domain coverage) -- validation only checks
# that a referenced entity id EXISTS, not that its domain matches the
# group's own flavor, so a real (if domain-mismatched) registry entity keeps
# this fixture validation-clean without needing to touch the shared registry
# fixture just for this one domain.
group_valve(name="Irrigation Zone A", entities=["cover.garage_door"])
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "group_binary_sensor:any_door_open": {
    "all": false,
    "entities": [
      "binary_sensor.door",
      "binary_sensor.back_door"
    ],
    "hide_members": false,
    "name": "Any Door Open"
  },
  "group_button:all_doorbells": {
    "entities": [
      "button.restart"
    ],
    "hide_members": false,
    "name": "All Doorbells"
  },
  "group_cover:bay_window_top": {
    "entities": [
      "cover.bedroom_blinds",
      "cover.living_room_blinds"
    ],
    "hide_members": false,
    "name": "Bay Window Top"
  },
  "group_cover:entryway_top": {
    "entities": [
      "cover.bay_window_top",
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Entryway Top"
  },
  "group_event:all_doorbell_events": {
    "entities": [
      "event.doorbell"
    ],
    "hide_members": false,
    "name": "All Doorbell Events"
  },
  "group_fan:all_fans": {
    "entities": [
      "fan.bedroom",
      "fan.living_room"
    ],
    "hide_members": false,
    "name": "All Fans"
  },
  "group_light:downstairs_lights": {
    "all": true,
    "entities": [
      "light.hallway",
      "light.living_room",
      "light.kitchen"
    ],
    "hide_members": false,
    "name": "Downstairs Lights"
  },
  "group_lock:all_locks": {
    "entities": [
      "lock.front_door",
      "lock.back_door"
    ],
    "hide_members": false,
    "name": "All Locks"
  },
  "group_media_player:whole_house_audio": {
    "entities": [
      "media_player.living_room_speaker",
      "media_player.kitchen_speaker"
    ],
    "hide_members": false,
    "name": "Whole House Audio"
  },
  "group_notify:all_phones": {
    "entities": [
      "notify.mobile_app_kai",
      "notify.mobile_app_spouse"
    ],
    "hide_members": false,
    "name": "All Phones"
  },
  "group_sensor:average_temp": {
    "entities": [
      "sensor.living_room_temperature",
      "sensor.bedroom_temperature"
    ],
    "hide_members": false,
    "name": "Average Temp",
    "type": "mean"
  },
  "group_switch:outdoor_switches": {
    "all": false,
    "entities": [
      "switch.garage_door_opener",
      "switch.office_monitor"
    ],
    "hide_members": true,
    "name": "Outdoor Switches"
  },
  "group_valve:irrigation_zone_a": {
    "entities": [
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Irrigation Zone A"
  }
}
```

### `group_valve`

Golden case: `fixtures/dsl/group_helper_declarations/`.

```python
"""Golden case: group-helper declarations for all twelve group flavors,
covering the three schema shapes (docs/internals/ha-api-notes.md §38.1) -- base (name/
entities/hide_members), +all (binary_sensor/light/switch), +type (sensor).

Identity: there is no `id=`/`unique_id=` kwarg, mirroring template helpers
(docs/internals/ha-api-notes.md §38.1) -- real HA's `group` config flow rejects an
unrecognized `unique_id` key outright. Identity is derived from `name`
(slugified): "Entryway Top" -> `group_cover:entryway_top`.

`hide_members`/`all` are always materialized explicitly in the compiled
options body (one canonical form, §38.1) -- never omitted just because they
equal their default.

Every `entities=` member below is a REAL entity id from
`fixtures/registry/home.json` (except `cover.bay_window_top`, which is this
bundle's OWN nested group's entity -- a real-world live example, §38.1:
a `cover.entryway_top` group containing `cover.bay_window_top`,
itself a group), so this fixture is also exercised by
`test_registry_validate.py::test_no_false_positives_on_golden_corpus`
(validation-clean, no `_DELIBERATELY_NOT_CLEAN` escape hatch needed).
"""

from hassle import (
    group_binary_sensor,
    group_button,
    group_cover,
    group_event,
    group_fan,
    group_light,
    group_lock,
    group_media_player,
    group_notify,
    group_sensor,
    group_switch,
    group_valve,
)

# Nested: "Bay Window Top" is declared first so "Entryway Top" can reference
# its produced entity (`cover.bay_window_top`) as a member -- a group whose
# members are themselves a group, a real-world live example (§38.1).
group_cover(
    name="Bay Window Top",
    entities=["cover.bedroom_blinds", "cover.living_room_blinds"],
)
group_cover(
    name="Entryway Top",
    entities=["cover.bay_window_top", "cover.garage_door"],
)
group_light(
    name="Downstairs Lights",
    entities=["light.hallway", "light.living_room", "light.kitchen"],
    all=True,
)
group_switch(
    name="Outdoor Switches",
    entities=["switch.garage_door_opener", "switch.office_monitor"],
    hide_members=True,
)
group_binary_sensor(
    name="Any Door Open",
    entities=["binary_sensor.door", "binary_sensor.back_door"],
)
group_sensor(
    name="Average Temp",
    entities=["sensor.living_room_temperature", "sensor.bedroom_temperature"],
    type="mean",
)
group_button(name="All Doorbells", entities=["button.restart"])
group_event(name="All Doorbell Events", entities=["event.doorbell"])
group_fan(name="All Fans", entities=["fan.bedroom", "fan.living_room"])
group_lock(name="All Locks", entities=["lock.front_door", "lock.back_door"])
group_media_player(
    name="Whole House Audio",
    entities=["media_player.living_room_speaker", "media_player.kitchen_speaker"],
)
group_notify(name="All Phones", entities=["notify.mobile_app_kai", "notify.mobile_app_spouse"])
# No `valve` entities exist in fixtures/registry/home.json at all (its
# registry snapshot has no valve domain coverage) -- validation only checks
# that a referenced entity id EXISTS, not that its domain matches the
# group's own flavor, so a real (if domain-mismatched) registry entity keeps
# this fixture validation-clean without needing to touch the shared registry
# fixture just for this one domain.
group_valve(name="Irrigation Zone A", entities=["cover.garage_door"])
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "group_binary_sensor:any_door_open": {
    "all": false,
    "entities": [
      "binary_sensor.door",
      "binary_sensor.back_door"
    ],
    "hide_members": false,
    "name": "Any Door Open"
  },
  "group_button:all_doorbells": {
    "entities": [
      "button.restart"
    ],
    "hide_members": false,
    "name": "All Doorbells"
  },
  "group_cover:bay_window_top": {
    "entities": [
      "cover.bedroom_blinds",
      "cover.living_room_blinds"
    ],
    "hide_members": false,
    "name": "Bay Window Top"
  },
  "group_cover:entryway_top": {
    "entities": [
      "cover.bay_window_top",
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Entryway Top"
  },
  "group_event:all_doorbell_events": {
    "entities": [
      "event.doorbell"
    ],
    "hide_members": false,
    "name": "All Doorbell Events"
  },
  "group_fan:all_fans": {
    "entities": [
      "fan.bedroom",
      "fan.living_room"
    ],
    "hide_members": false,
    "name": "All Fans"
  },
  "group_light:downstairs_lights": {
    "all": true,
    "entities": [
      "light.hallway",
      "light.living_room",
      "light.kitchen"
    ],
    "hide_members": false,
    "name": "Downstairs Lights"
  },
  "group_lock:all_locks": {
    "entities": [
      "lock.front_door",
      "lock.back_door"
    ],
    "hide_members": false,
    "name": "All Locks"
  },
  "group_media_player:whole_house_audio": {
    "entities": [
      "media_player.living_room_speaker",
      "media_player.kitchen_speaker"
    ],
    "hide_members": false,
    "name": "Whole House Audio"
  },
  "group_notify:all_phones": {
    "entities": [
      "notify.mobile_app_kai",
      "notify.mobile_app_spouse"
    ],
    "hide_members": false,
    "name": "All Phones"
  },
  "group_sensor:average_temp": {
    "entities": [
      "sensor.living_room_temperature",
      "sensor.bedroom_temperature"
    ],
    "hide_members": false,
    "name": "Average Temp",
    "type": "mean"
  },
  "group_switch:outdoor_switches": {
    "all": false,
    "entities": [
      "switch.garage_door_opener",
      "switch.office_monitor"
    ],
    "hide_members": true,
    "name": "Outdoor Switches"
  },
  "group_valve:irrigation_zone_a": {
    "entities": [
      "cover.garage_door"
    ],
    "hide_members": false,
    "name": "Irrigation Zone A"
  }
}
```

### `when`

Golden case: `fixtures/dsl/state_delay_service/`.

```python
"""Golden case: state trigger + delay + service call.

Exercises the one end-to-end trigger builder (`state(...).to(...)`), the first
action primitive (`delay`), and a service-call action with kwargs.
"""

from hassle import automation, delay, service, state, when


@automation(id="hall_light_on_motion", alias="Hallway: light on motion", mode="restart")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", entity_id="light.hallway", brightness_pct=60)
    delay(minutes=5)
    service("light.turn_off", entity_id="light.hallway")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:hall_light_on_motion": {
    "actions": [
      {
        "action": "light.turn_on",
        "data": {
          "brightness_pct": 60,
          "entity_id": "light.hallway"
        }
      },
      {
        "delay": {
          "minutes": 5
        }
      },
      {
        "action": "light.turn_off",
        "data": {
          "entity_id": "light.hallway"
        }
      }
    ],
    "alias": "Hallway: light on motion",
    "conditions": [],
    "id": "hall_light_on_motion",
    "mode": "restart",
    "triggers": [
      {
        "entity_id": "binary_sensor.hall_motion",
        "to": "on",
        "trigger": "state"
      }
    ]
  }
}
```

### `only_if`

Golden case: `fixtures/dsl/classic_conditions/`.

```python
"""Golden case: every classic condition builder in one automation.

Exercises state/numeric_state/sun/time/zone/template conditions plus the
`condition: trigger` block referencing a trigger id= (DESIGN §5.4). Field
shapes mirror fixtures/configs/automation_condition_*.json.
"""

from hassle import (
    automation,
    numeric_state,
    only_if,
    service,
    state,
    sun,
    template,
    time,
    trigger_condition,
    when,
    zone,
)


@automation(id="classic_conditions", alias="Classic Conditions")
def classic_conditions():
    when(numeric_state("sensor.humidity", above=0).with_options(id="motion"))
    only_if(
        state("input_boolean.enable_automation").is_("on"),
        numeric_state("sensor.humidity", above=60),
        sun(after="sunset", after_offset="-01:00:00"),
        time(after="22:00:00", before="06:00:00", weekday=["mon", "tue", "wed", "thu", "fri"]),
        zone("device_tracker.john", zone="zone.work"),
        template("{{ now().hour >= 6 and now().hour < 22 }}"),
        trigger_condition("motion"),
    )
    service("light.turn_on", target={"entity_id": "light.hallway"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:classic_conditions": {
    "actions": [
      {
        "action": "light.turn_on",
        "target": {
          "entity_id": "light.hallway"
        }
      }
    ],
    "alias": "Classic Conditions",
    "conditions": [
      {
        "condition": "state",
        "entity_id": "input_boolean.enable_automation",
        "state": "on"
      },
      {
        "above": 60,
        "condition": "numeric_state",
        "entity_id": "sensor.humidity"
      },
      {
        "after": "sunset",
        "after_offset": "-01:00:00",
        "condition": "sun"
      },
      {
        "after": "22:00:00",
        "before": "06:00:00",
        "condition": "time",
        "weekday": [
          "mon",
          "tue",
          "wed",
          "thu",
          "fri"
        ]
      },
      {
        "condition": "zone",
        "entity_id": "device_tracker.john",
        "zone": "zone.work"
      },
      {
        "condition": "template",
        "value_template": "{{ now().hour >= 6 and now().hour < 22 }}"
      },
      {
        "condition": "trigger",
        "id": "motion"
      }
    ],
    "id": "classic_conditions",
    "triggers": [
      {
        "above": 0,
        "entity_id": "sensor.humidity",
        "id": "motion",
        "trigger": "numeric_state"
      }
    ]
  }
}
```

### `capture_actions`

Golden case: `fixtures/dsl/capture_emit_actions/`.

```python
"""Golden case: `capture_actions()`/`emit_actions(...)` (the public
capture seam) -- one captured action list spliced into two `choose()`
branches inside a single automation.
"""

from shared_actions import porch_off_on_either_door

from hassle import automation, state, when


@automation(id="doors_porch_light", alias="Doors: porch light off")
def doors_porch_light():
    when(state("binary_sensor.front_door").to("open"))
    porch_off_on_either_door()


"""Shared capture/emit helper library (DESIGN §5.6-style `lib/` pattern).

Demonstrates the public capture seam: a `lib/` builder captures one block
of actions once with `capture_actions()`
and splices the SAME captured bodies into more than one place with
`emit_actions(...)` -- here, a single "turn off the porch light" action
reused across two `choose()` branches keyed on which door opened.
"""

from hassle import capture_actions, choose, emit_actions, service, state


def porch_off_on_either_door():
    with capture_actions() as porch_off:
        service("light.turn_off", entity_id="light.porch")

    with choose() as c:
        with c.when_(state("binary_sensor.front_door").is_("open")):
            emit_actions(porch_off)
        with c.when_(state("binary_sensor.back_door").is_("open")):
            emit_actions(porch_off)
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:doors_porch_light": {
    "actions": [
      {
        "choose": [
          {
            "conditions": [
              {
                "condition": "state",
                "entity_id": "binary_sensor.front_door",
                "state": "open"
              }
            ],
            "sequence": [
              {
                "action": "light.turn_off",
                "data": {
                  "entity_id": "light.porch"
                }
              }
            ]
          },
          {
            "conditions": [
              {
                "condition": "state",
                "entity_id": "binary_sensor.back_door",
                "state": "open"
              }
            ],
            "sequence": [
              {
                "action": "light.turn_off",
                "data": {
                  "entity_id": "light.porch"
                }
              }
            ]
          }
        ]
      }
    ],
    "alias": "Doors: porch light off",
    "conditions": [],
    "id": "doors_porch_light",
    "triggers": [
      {
        "entity_id": "binary_sensor.front_door",
        "to": "open",
        "trigger": "state"
      }
    ]
  }
}
```

### `emit_actions`

Golden case: `fixtures/dsl/capture_emit_actions/`.

```python
"""Golden case: `capture_actions()`/`emit_actions(...)` (the public
capture seam) -- one captured action list spliced into two `choose()`
branches inside a single automation.
"""

from shared_actions import porch_off_on_either_door

from hassle import automation, state, when


@automation(id="doors_porch_light", alias="Doors: porch light off")
def doors_porch_light():
    when(state("binary_sensor.front_door").to("open"))
    porch_off_on_either_door()


"""Shared capture/emit helper library (DESIGN §5.6-style `lib/` pattern).

Demonstrates the public capture seam: a `lib/` builder captures one block
of actions once with `capture_actions()`
and splices the SAME captured bodies into more than one place with
`emit_actions(...)` -- here, a single "turn off the porch light" action
reused across two `choose()` branches keyed on which door opened.
"""

from hassle import capture_actions, choose, emit_actions, service, state


def porch_off_on_either_door():
    with capture_actions() as porch_off:
        service("light.turn_off", entity_id="light.porch")

    with choose() as c:
        with c.when_(state("binary_sensor.front_door").is_("open")):
            emit_actions(porch_off)
        with c.when_(state("binary_sensor.back_door").is_("open")):
            emit_actions(porch_off)
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:doors_porch_light": {
    "actions": [
      {
        "choose": [
          {
            "conditions": [
              {
                "condition": "state",
                "entity_id": "binary_sensor.front_door",
                "state": "open"
              }
            ],
            "sequence": [
              {
                "action": "light.turn_off",
                "data": {
                  "entity_id": "light.porch"
                }
              }
            ]
          },
          {
            "conditions": [
              {
                "condition": "state",
                "entity_id": "binary_sensor.back_door",
                "state": "open"
              }
            ],
            "sequence": [
              {
                "action": "light.turn_off",
                "data": {
                  "entity_id": "light.porch"
                }
              }
            ]
          }
        ]
      }
    ],
    "alias": "Doors: porch light off",
    "conditions": [],
    "id": "doors_porch_light",
    "triggers": [
      {
        "entity_id": "binary_sensor.front_door",
        "to": "open",
        "trigger": "state"
      }
    ]
  }
}
```

### `service`

Golden case: `fixtures/dsl/state_delay_service/`.

```python
"""Golden case: state trigger + delay + service call.

Exercises the one end-to-end trigger builder (`state(...).to(...)`), the first
action primitive (`delay`), and a service-call action with kwargs.
"""

from hassle import automation, delay, service, state, when


@automation(id="hall_light_on_motion", alias="Hallway: light on motion", mode="restart")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", entity_id="light.hallway", brightness_pct=60)
    delay(minutes=5)
    service("light.turn_off", entity_id="light.hallway")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:hall_light_on_motion": {
    "actions": [
      {
        "action": "light.turn_on",
        "data": {
          "brightness_pct": 60,
          "entity_id": "light.hallway"
        }
      },
      {
        "delay": {
          "minutes": 5
        }
      },
      {
        "action": "light.turn_off",
        "data": {
          "entity_id": "light.hallway"
        }
      }
    ],
    "alias": "Hallway: light on motion",
    "conditions": [],
    "id": "hall_light_on_motion",
    "mode": "restart",
    "triggers": [
      {
        "entity_id": "binary_sensor.hall_motion",
        "to": "on",
        "trigger": "state"
      }
    ]
  }
}
```

### `delay`

Golden case: `fixtures/dsl/state_delay_service/`.

```python
"""Golden case: state trigger + delay + service call.

Exercises the one end-to-end trigger builder (`state(...).to(...)`), the first
action primitive (`delay`), and a service-call action with kwargs.
"""

from hassle import automation, delay, service, state, when


@automation(id="hall_light_on_motion", alias="Hallway: light on motion", mode="restart")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", entity_id="light.hallway", brightness_pct=60)
    delay(minutes=5)
    service("light.turn_off", entity_id="light.hallway")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:hall_light_on_motion": {
    "actions": [
      {
        "action": "light.turn_on",
        "data": {
          "brightness_pct": 60,
          "entity_id": "light.hallway"
        }
      },
      {
        "delay": {
          "minutes": 5
        }
      },
      {
        "action": "light.turn_off",
        "data": {
          "entity_id": "light.hallway"
        }
      }
    ],
    "alias": "Hallway: light on motion",
    "conditions": [],
    "id": "hall_light_on_motion",
    "mode": "restart",
    "triggers": [
      {
        "entity_id": "binary_sensor.hall_motion",
        "to": "on",
        "trigger": "state"
      }
    ]
  }
}
```

### `variables`

Golden case: `fixtures/dsl/action_primitives/`.

```python
"""Golden case: stop/variables/fire_event/service action primitives.

``fire_event`` is the fire-event *action* (distinct from the ``event`` trigger
builder); ``response_variable``/``continue_on_error`` are folded into ``service``
(there is no separate ``service_ext``).
"""

from hassle import automation, fire_event, service, state, stop, variables, when


@automation(id="misc_primitives", alias="Misc action primitives")
def misc_primitives():
    when(state("binary_sensor.trigger").to("on"))
    variables(greeting="hello", count=3)
    fire_event("hassle_custom_event", room="hallway", level=2)
    service(
        "climate.get_forecast",
        target={"entity_id": "climate.living_room"},
        response_variable="forecast",
    )
    service(
        "notify.mobile_app",
        message="done",
        continue_on_error=True,
    )
    # response_variable= (ux/script-responses): the named run variable's
    # value becomes the script/automation response (HA script responses).
    stop(message="all done", error=False, response_variable="greeting")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:misc_primitives": {
    "actions": [
      {
        "variables": {
          "count": 3,
          "greeting": "hello"
        }
      },
      {
        "event": "hassle_custom_event",
        "event_data": {
          "level": 2,
          "room": "hallway"
        }
      },
      {
        "action": "climate.get_forecast",
        "response_variable": "forecast",
        "target": {
          "entity_id": "climate.living_room"
        }
      },
      {
        "action": "notify.mobile_app",
        "continue_on_error": true,
        "data": {
          "message": "done"
        }
      },
      {
        "error": false,
        "response_variable": "greeting",
        "stop": "all done"
      }
    ],
    "alias": "Misc action primitives",
    "conditions": [],
    "id": "misc_primitives",
    "triggers": [
      {
        "entity_id": "binary_sensor.trigger",
        "to": "on",
        "trigger": "state"
      }
    ]
  }
}
```

See also: `fixtures/dsl/math_expr_reference/`

### `stop`

Golden case: `fixtures/dsl/action_primitives/`.

```python
"""Golden case: stop/variables/fire_event/service action primitives.

``fire_event`` is the fire-event *action* (distinct from the ``event`` trigger
builder); ``response_variable``/``continue_on_error`` are folded into ``service``
(there is no separate ``service_ext``).
"""

from hassle import automation, fire_event, service, state, stop, variables, when


@automation(id="misc_primitives", alias="Misc action primitives")
def misc_primitives():
    when(state("binary_sensor.trigger").to("on"))
    variables(greeting="hello", count=3)
    fire_event("hassle_custom_event", room="hallway", level=2)
    service(
        "climate.get_forecast",
        target={"entity_id": "climate.living_room"},
        response_variable="forecast",
    )
    service(
        "notify.mobile_app",
        message="done",
        continue_on_error=True,
    )
    # response_variable= (ux/script-responses): the named run variable's
    # value becomes the script/automation response (HA script responses).
    stop(message="all done", error=False, response_variable="greeting")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:misc_primitives": {
    "actions": [
      {
        "variables": {
          "count": 3,
          "greeting": "hello"
        }
      },
      {
        "event": "hassle_custom_event",
        "event_data": {
          "level": 2,
          "room": "hallway"
        }
      },
      {
        "action": "climate.get_forecast",
        "response_variable": "forecast",
        "target": {
          "entity_id": "climate.living_room"
        }
      },
      {
        "action": "notify.mobile_app",
        "continue_on_error": true,
        "data": {
          "message": "done"
        }
      },
      {
        "error": false,
        "response_variable": "greeting",
        "stop": "all done"
      }
    ],
    "alias": "Misc action primitives",
    "conditions": [],
    "id": "misc_primitives",
    "triggers": [
      {
        "entity_id": "binary_sensor.trigger",
        "to": "on",
        "trigger": "state"
      }
    ]
  }
}
```

### `fire_event`

Golden case: `fixtures/dsl/action_primitives/`.

```python
"""Golden case: stop/variables/fire_event/service action primitives.

``fire_event`` is the fire-event *action* (distinct from the ``event`` trigger
builder); ``response_variable``/``continue_on_error`` are folded into ``service``
(there is no separate ``service_ext``).
"""

from hassle import automation, fire_event, service, state, stop, variables, when


@automation(id="misc_primitives", alias="Misc action primitives")
def misc_primitives():
    when(state("binary_sensor.trigger").to("on"))
    variables(greeting="hello", count=3)
    fire_event("hassle_custom_event", room="hallway", level=2)
    service(
        "climate.get_forecast",
        target={"entity_id": "climate.living_room"},
        response_variable="forecast",
    )
    service(
        "notify.mobile_app",
        message="done",
        continue_on_error=True,
    )
    # response_variable= (ux/script-responses): the named run variable's
    # value becomes the script/automation response (HA script responses).
    stop(message="all done", error=False, response_variable="greeting")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:misc_primitives": {
    "actions": [
      {
        "variables": {
          "count": 3,
          "greeting": "hello"
        }
      },
      {
        "event": "hassle_custom_event",
        "event_data": {
          "level": 2,
          "room": "hallway"
        }
      },
      {
        "action": "climate.get_forecast",
        "response_variable": "forecast",
        "target": {
          "entity_id": "climate.living_room"
        }
      },
      {
        "action": "notify.mobile_app",
        "continue_on_error": true,
        "data": {
          "message": "done"
        }
      },
      {
        "error": false,
        "response_variable": "greeting",
        "stop": "all done"
      }
    ],
    "alias": "Misc action primitives",
    "conditions": [],
    "id": "misc_primitives",
    "triggers": [
      {
        "entity_id": "binary_sensor.trigger",
        "to": "on",
        "trigger": "state"
      }
    ]
  }
}
```

### `state`

Golden case: `fixtures/dsl/state_delay_service/`.

```python
"""Golden case: state trigger + delay + service call.

Exercises the one end-to-end trigger builder (`state(...).to(...)`), the first
action primitive (`delay`), and a service-call action with kwargs.
"""

from hassle import automation, delay, service, state, when


@automation(id="hall_light_on_motion", alias="Hallway: light on motion", mode="restart")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", entity_id="light.hallway", brightness_pct=60)
    delay(minutes=5)
    service("light.turn_off", entity_id="light.hallway")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:hall_light_on_motion": {
    "actions": [
      {
        "action": "light.turn_on",
        "data": {
          "brightness_pct": 60,
          "entity_id": "light.hallway"
        }
      },
      {
        "delay": {
          "minutes": 5
        }
      },
      {
        "action": "light.turn_off",
        "data": {
          "entity_id": "light.hallway"
        }
      }
    ],
    "alias": "Hallway: light on motion",
    "conditions": [],
    "id": "hall_light_on_motion",
    "mode": "restart",
    "triggers": [
      {
        "entity_id": "binary_sensor.hall_motion",
        "to": "on",
        "trigger": "state"
      }
    ]
  }
}
```

### `numeric_state`

Golden case: `fixtures/dsl/numeric_state_trigger/`.

```python
"""Golden case: `numeric_state` trigger builder.

Mirrors fixtures/configs/automation_numeric_state_trigger.json.
"""

from hassle import automation, numeric_state, service, when


@automation(id="numeric_state_trigger", alias="Numeric State Trigger")
def numeric_state_trigger():
    when(numeric_state("sensor.outdoor_temperature", above=25))
    service(
        "climate.set_temperature",
        target={"entity_id": "climate.living_room"},
        temperature=20,
    )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:numeric_state_trigger": {
    "actions": [
      {
        "action": "climate.set_temperature",
        "data": {
          "temperature": 20
        },
        "target": {
          "entity_id": "climate.living_room"
        }
      }
    ],
    "alias": "Numeric State Trigger",
    "conditions": [],
    "id": "numeric_state_trigger",
    "triggers": [
      {
        "above": 25,
        "entity_id": "sensor.outdoor_temperature",
        "trigger": "numeric_state"
      }
    ]
  }
}
```

### `time`

Golden case: `fixtures/dsl/time_trigger/`.

```python
"""Golden case: `time` trigger builder.

Mirrors fixtures/configs/automation_time_trigger.json.
"""

from hassle import automation, service, time, when


@automation(id="time_trigger", alias="Time Trigger")
def time_trigger():
    when(time(at="07:00:00"))
    service("light.turn_on", target={"entity_id": "light.bedroom"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:time_trigger": {
    "actions": [
      {
        "action": "light.turn_on",
        "target": {
          "entity_id": "light.bedroom"
        }
      }
    ],
    "alias": "Time Trigger",
    "conditions": [],
    "id": "time_trigger",
    "triggers": [
      {
        "at": "07:00:00",
        "trigger": "time"
      }
    ]
  }
}
```

### `time_pattern`

Golden case: `fixtures/dsl/time_pattern_trigger/`.

```python
"""Golden case: `time_pattern` trigger builder.

Mirrors fixtures/configs/automation_time_pattern_trigger.json.
"""

from hassle import automation, service, time_pattern, when


@automation(id="time_pattern_trigger", alias="Time Pattern Trigger")
def time_pattern_trigger():
    when(time_pattern(hours="/1", minutes="0"))
    service("homeassistant.update_entity", target={"entity_id": "sensor.uptime"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:time_pattern_trigger": {
    "actions": [
      {
        "action": "homeassistant.update_entity",
        "target": {
          "entity_id": "sensor.uptime"
        }
      }
    ],
    "alias": "Time Pattern Trigger",
    "conditions": [],
    "id": "time_pattern_trigger",
    "triggers": [
      {
        "hours": "/1",
        "minutes": "0",
        "trigger": "time_pattern"
      }
    ]
  }
}
```

### `sun`

Golden case: `fixtures/dsl/sun_trigger/`.

```python
"""Golden case: `sun` trigger builder.

Mirrors fixtures/configs/automation_sun_trigger.json.
"""

from hassle import automation, service, sun, when


@automation(id="sun_trigger", alias="Sun Trigger")
def sun_trigger():
    when(sun(event="sunset", offset="-00:30:00"))
    service("light.turn_on", target={"entity_id": "light.porch"}, brightness_pct=75)
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:sun_trigger": {
    "actions": [
      {
        "action": "light.turn_on",
        "data": {
          "brightness_pct": 75
        },
        "target": {
          "entity_id": "light.porch"
        }
      }
    ],
    "alias": "Sun Trigger",
    "conditions": [],
    "id": "sun_trigger",
    "triggers": [
      {
        "event": "sunset",
        "offset": "-00:30:00",
        "trigger": "sun"
      }
    ]
  }
}
```

### `event`

Golden case: `fixtures/dsl/event_trigger/`.

```python
"""Golden case: `event` trigger builder.

Mirrors fixtures/configs/automation_event_trigger.json.
"""

from hassle import automation, event, service, when


@automation(id="event_trigger", alias="Event Trigger")
def event_trigger():
    when(event("custom_event", event_data={"action": "test"}))
    service("notify.mobile_app", message="Custom event triggered")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:event_trigger": {
    "actions": [
      {
        "action": "notify.mobile_app",
        "data": {
          "message": "Custom event triggered"
        }
      }
    ],
    "alias": "Event Trigger",
    "conditions": [],
    "id": "event_trigger",
    "triggers": [
      {
        "event_data": {
          "action": "test"
        },
        "event_type": "custom_event",
        "trigger": "event"
      }
    ]
  }
}
```

### `zone`

Golden case: `fixtures/dsl/zone_trigger/`.

```python
"""Golden case: `zone` trigger builder.

Mirrors fixtures/configs/automation_zone_trigger.json.
"""

from hassle import automation, service, when, zone


@automation(id="zone_trigger", alias="Zone Trigger")
def zone_trigger():
    when(zone("device_tracker.john", zone="zone.work", event="enter"))
    service("light.turn_on", target={"entity_id": "light.office"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:zone_trigger": {
    "actions": [
      {
        "action": "light.turn_on",
        "target": {
          "entity_id": "light.office"
        }
      }
    ],
    "alias": "Zone Trigger",
    "conditions": [],
    "id": "zone_trigger",
    "triggers": [
      {
        "entity_id": "device_tracker.john",
        "event": "enter",
        "trigger": "zone",
        "zone": "zone.work"
      }
    ]
  }
}
```

### `template`

Golden case: `fixtures/dsl/template_trigger/`.

```python
"""Golden case: `template` trigger builder (raw Jinja string).

Mirrors fixtures/configs/automation_template_trigger.json.
"""

from hassle import automation, service, template, when


@automation(id="template_trigger", alias="Template Trigger")
def template_trigger():
    when(template("{{ state_attr('light.hallway', 'brightness') > 100 }}"))
    service("automation.turn_off", target={"entity_id": "automation.template_trigger"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:template_trigger": {
    "actions": [
      {
        "action": "automation.turn_off",
        "target": {
          "entity_id": "automation.template_trigger"
        }
      }
    ],
    "alias": "Template Trigger",
    "conditions": [],
    "id": "template_trigger",
    "triggers": [
      {
        "trigger": "template",
        "value_template": "{{ state_attr('light.hallway', 'brightness') > 100 }}"
      }
    ]
  }
}
```

See also: `fixtures/dsl/template_expr_golden/`

### `webhook`

Golden case: `fixtures/dsl/webhook_trigger/`.

```python
"""Golden case: `webhook` trigger builder.

Mirrors fixtures/configs/automation_webhook_trigger.json.
"""

from hassle import automation, service, webhook, when


@automation(id="webhook_trigger", alias="Webhook Trigger")
def webhook_trigger():
    when(webhook("abc123def456"))
    service("light.turn_on", target={"entity_id": "light.bedroom"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:webhook_trigger": {
    "actions": [
      {
        "action": "light.turn_on",
        "target": {
          "entity_id": "light.bedroom"
        }
      }
    ],
    "alias": "Webhook Trigger",
    "conditions": [],
    "id": "webhook_trigger",
    "triggers": [
      {
        "trigger": "webhook",
        "webhook_id": "abc123def456"
      }
    ]
  }
}
```

### `mqtt`

Golden case: `fixtures/dsl/mqtt_trigger/`.

```python
"""Golden case: `mqtt` trigger builder.

Mirrors fixtures/configs/automation_mqtt_trigger.json.
"""

from hassle import automation, mqtt, service, when


@automation(id="mqtt_trigger", alias="MQTT Trigger")
def mqtt_trigger():
    when(mqtt("home/bedroom/motion", payload="on"))
    service("switch.turn_on", target={"entity_id": "switch.bedroom_fan"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:mqtt_trigger": {
    "actions": [
      {
        "action": "switch.turn_on",
        "target": {
          "entity_id": "switch.bedroom_fan"
        }
      }
    ],
    "alias": "MQTT Trigger",
    "conditions": [],
    "id": "mqtt_trigger",
    "triggers": [
      {
        "payload": "on",
        "topic": "home/bedroom/motion",
        "trigger": "mqtt"
      }
    ]
  }
}
```

### `calendar`

Golden case: `fixtures/dsl/calendar_trigger/`.

```python
"""Golden case: `calendar` trigger builder.

Mirrors fixtures/configs/automation_calendar_trigger.json.
"""

from hassle import automation, calendar, service, when


@automation(id="calendar_trigger", alias="Calendar Trigger")
def calendar_trigger():
    when(calendar("calendar.holidays", event="start"))
    service("notify.mobile_app", message="Calendar event starting")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:calendar_trigger": {
    "actions": [
      {
        "action": "notify.mobile_app",
        "data": {
          "message": "Calendar event starting"
        }
      }
    ],
    "alias": "Calendar Trigger",
    "conditions": [],
    "id": "calendar_trigger",
    "triggers": [
      {
        "entity_id": "calendar.holidays",
        "event": "start",
        "trigger": "calendar"
      }
    ]
  }
}
```

### `persistent_notification`

Golden case: `fixtures/dsl/persistent_notification_trigger/`.

```python
"""Golden case: `persistent_notification` trigger builder.

Mirrors fixtures/configs/automation_persistent_notification_trigger.json.
"""

from hassle import automation, persistent_notification, service, when


@automation(id="persistent_notification_trigger", alias="Persistent Notification Trigger")
def persistent_notification_trigger():
    when(persistent_notification(notification_id="test_notification"))
    service("persistent_notification.dismiss", notification_id="test_notification")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:persistent_notification_trigger": {
    "actions": [
      {
        "action": "persistent_notification.dismiss",
        "data": {
          "notification_id": "test_notification"
        }
      }
    ],
    "alias": "Persistent Notification Trigger",
    "conditions": [],
    "id": "persistent_notification_trigger",
    "triggers": [
      {
        "notification_id": "test_notification",
        "trigger": "persistent_notification"
      }
    ]
  }
}
```

### `tag`

Golden case: `fixtures/dsl/tag_trigger/`.

```python
"""Golden case: `tag` trigger builder.

Mirrors fixtures/configs/automation_tag_trigger.json.
"""

from hassle import automation, service, tag, when


@automation(id="tag_trigger", alias="Tag Trigger")
def tag_trigger():
    when(tag("tag_abc123"))
    service("light.turn_on", target={"entity_id": "light.entryway"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:tag_trigger": {
    "actions": [
      {
        "action": "light.turn_on",
        "target": {
          "entity_id": "light.entryway"
        }
      }
    ],
    "alias": "Tag Trigger",
    "conditions": [],
    "id": "tag_trigger",
    "triggers": [
      {
        "tag_id": "tag_abc123",
        "trigger": "tag"
      }
    ]
  }
}
```

### `geo_location`

Golden case: `fixtures/dsl/geo_location_trigger/`.

```python
"""Golden case: `geo_location` trigger builder.

Mirrors fixtures/configs/automation_geo_location_trigger.json.
"""

from hassle import automation, geo_location, service, when


@automation(id="geo_location_trigger", alias="Geo Location Trigger")
def geo_location_trigger():
    when(geo_location(source="nsw_rural_fire_service_feed", zone="zone.home", event="enter"))
    service("notify.mobile_app", message="Geolocation event")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:geo_location_trigger": {
    "actions": [
      {
        "action": "notify.mobile_app",
        "data": {
          "message": "Geolocation event"
        }
      }
    ],
    "alias": "Geo Location Trigger",
    "conditions": [],
    "id": "geo_location_trigger",
    "triggers": [
      {
        "event": "enter",
        "source": "nsw_rural_fire_service_feed",
        "trigger": "geo_location",
        "zone": "zone.home"
      }
    ]
  }
}
```

### `homeassistant_start`

Golden case: `fixtures/dsl/homeassistant_start_trigger/`.

```python
"""Golden case: `homeassistant_start` trigger builder.

Mirrors fixtures/configs/automation_homeassistant_start_trigger.json.
"""

from hassle import automation, homeassistant_start, service, when


@automation(id="homeassistant_start_trigger", alias="HA Start Trigger")
def homeassistant_start_trigger():
    when(homeassistant_start())
    service("automation.reload")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:homeassistant_start_trigger": {
    "actions": [
      {
        "action": "automation.reload"
      }
    ],
    "alias": "HA Start Trigger",
    "conditions": [],
    "id": "homeassistant_start_trigger",
    "triggers": [
      {
        "event": "start",
        "trigger": "homeassistant"
      }
    ]
  }
}
```

### `homeassistant_shutdown`

Golden case: `fixtures/dsl/homeassistant_shutdown_trigger/`.

```python
"""Golden case: `homeassistant_shutdown` trigger builder.

Mirrors fixtures/configs/automation_homeassistant_shutdown_trigger.json.
"""

from hassle import automation, homeassistant_shutdown, service, when


@automation(id="homeassistant_shutdown_trigger", alias="HA Shutdown Trigger")
def homeassistant_shutdown_trigger():
    when(homeassistant_shutdown())
    service("light.turn_off", target={"entity_id": "light.all"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:homeassistant_shutdown_trigger": {
    "actions": [
      {
        "action": "light.turn_off",
        "target": {
          "entity_id": "light.all"
        }
      }
    ],
    "alias": "HA Shutdown Trigger",
    "conditions": [],
    "id": "homeassistant_shutdown_trigger",
    "triggers": [
      {
        "event": "shutdown",
        "trigger": "homeassistant"
      }
    ]
  }
}
```

### `device`

Golden case: `fixtures/dsl/device_trigger_raw/`.

```python
"""Golden case: `device` trigger builder (raw dict passthrough).

Mirrors fixtures/configs/automation_device_trigger.json.
"""

from hassle import automation, device, service, when


@automation(id="device_trigger_raw", alias="Device Trigger")
def device_trigger_raw():
    when(
        device(
            {
                "device_id": "1234567890abcdef",
                "domain": "zwave",
                "type": "scene_activation",
                "subtype": "scene_001",
            }
        )
    )
    service("scene.turn_on", target={"entity_id": "scene.evening"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:device_trigger_raw": {
    "actions": [
      {
        "action": "scene.turn_on",
        "target": {
          "entity_id": "scene.evening"
        }
      }
    ],
    "alias": "Device Trigger",
    "conditions": [],
    "id": "device_trigger_raw",
    "triggers": [
      {
        "device_id": "1234567890abcdef",
        "domain": "zwave",
        "subtype": "scene_001",
        "trigger": "device",
        "type": "scene_activation"
      }
    ]
  }
}
```

### `trigger_condition`

Golden case: `fixtures/dsl/classic_conditions/`.

```python
"""Golden case: every classic condition builder in one automation.

Exercises state/numeric_state/sun/time/zone/template conditions plus the
`condition: trigger` block referencing a trigger id= (DESIGN §5.4). Field
shapes mirror fixtures/configs/automation_condition_*.json.
"""

from hassle import (
    automation,
    numeric_state,
    only_if,
    service,
    state,
    sun,
    template,
    time,
    trigger_condition,
    when,
    zone,
)


@automation(id="classic_conditions", alias="Classic Conditions")
def classic_conditions():
    when(numeric_state("sensor.humidity", above=0).with_options(id="motion"))
    only_if(
        state("input_boolean.enable_automation").is_("on"),
        numeric_state("sensor.humidity", above=60),
        sun(after="sunset", after_offset="-01:00:00"),
        time(after="22:00:00", before="06:00:00", weekday=["mon", "tue", "wed", "thu", "fri"]),
        zone("device_tracker.john", zone="zone.work"),
        template("{{ now().hour >= 6 and now().hour < 22 }}"),
        trigger_condition("motion"),
    )
    service("light.turn_on", target={"entity_id": "light.hallway"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:classic_conditions": {
    "actions": [
      {
        "action": "light.turn_on",
        "target": {
          "entity_id": "light.hallway"
        }
      }
    ],
    "alias": "Classic Conditions",
    "conditions": [
      {
        "condition": "state",
        "entity_id": "input_boolean.enable_automation",
        "state": "on"
      },
      {
        "above": 60,
        "condition": "numeric_state",
        "entity_id": "sensor.humidity"
      },
      {
        "after": "sunset",
        "after_offset": "-01:00:00",
        "condition": "sun"
      },
      {
        "after": "22:00:00",
        "before": "06:00:00",
        "condition": "time",
        "weekday": [
          "mon",
          "tue",
          "wed",
          "thu",
          "fri"
        ]
      },
      {
        "condition": "zone",
        "entity_id": "device_tracker.john",
        "zone": "zone.work"
      },
      {
        "condition": "template",
        "value_template": "{{ now().hour >= 6 and now().hour < 22 }}"
      },
      {
        "condition": "trigger",
        "id": "motion"
      }
    ],
    "id": "classic_conditions",
    "triggers": [
      {
        "above": 0,
        "entity_id": "sensor.humidity",
        "id": "motion",
        "trigger": "numeric_state"
      }
    ]
  }
}
```

### `all_of`

Golden case: `fixtures/dsl/condition_combinators/`.

```python
"""Golden case: `any_of`/`all_of`/`not_` condition combinators.

Mirrors fixtures/configs/automation_condition_and_or_not.json (and/or/not
condition blocks).
"""

from hassle import all_of, any_of, automation, not_, only_if, service, state, when


@automation(id="condition_combinators", alias="Condition And Or Not")
def condition_combinators():
    when(state("binary_sensor.motion").to("on"))
    only_if(
        all_of(
            state("input_boolean.mode").is_("on"),
            any_of(
                state("light.bedroom").is_("on"),
                state("light.living_room").is_("on"),
            ),
            not_(state("input_boolean.away").is_("on")),
        )
    )
    service("light.turn_on", target={"entity_id": "light.hallway"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:condition_combinators": {
    "actions": [
      {
        "action": "light.turn_on",
        "target": {
          "entity_id": "light.hallway"
        }
      }
    ],
    "alias": "Condition And Or Not",
    "conditions": [
      {
        "condition": "and",
        "conditions": [
          {
            "condition": "state",
            "entity_id": "input_boolean.mode",
            "state": "on"
          },
          {
            "condition": "or",
            "conditions": [
              {
                "condition": "state",
                "entity_id": "light.bedroom",
                "state": "on"
              },
              {
                "condition": "state",
                "entity_id": "light.living_room",
                "state": "on"
              }
            ]
          },
          {
            "condition": "not",
            "conditions": [
              {
                "condition": "state",
                "entity_id": "input_boolean.away",
                "state": "on"
              }
            ]
          }
        ]
      }
    ],
    "id": "condition_combinators",
    "triggers": [
      {
        "entity_id": "binary_sensor.motion",
        "to": "on",
        "trigger": "state"
      }
    ]
  }
}
```

### `any_of`

Golden case: `fixtures/dsl/condition_combinators/`.

```python
"""Golden case: `any_of`/`all_of`/`not_` condition combinators.

Mirrors fixtures/configs/automation_condition_and_or_not.json (and/or/not
condition blocks).
"""

from hassle import all_of, any_of, automation, not_, only_if, service, state, when


@automation(id="condition_combinators", alias="Condition And Or Not")
def condition_combinators():
    when(state("binary_sensor.motion").to("on"))
    only_if(
        all_of(
            state("input_boolean.mode").is_("on"),
            any_of(
                state("light.bedroom").is_("on"),
                state("light.living_room").is_("on"),
            ),
            not_(state("input_boolean.away").is_("on")),
        )
    )
    service("light.turn_on", target={"entity_id": "light.hallway"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:condition_combinators": {
    "actions": [
      {
        "action": "light.turn_on",
        "target": {
          "entity_id": "light.hallway"
        }
      }
    ],
    "alias": "Condition And Or Not",
    "conditions": [
      {
        "condition": "and",
        "conditions": [
          {
            "condition": "state",
            "entity_id": "input_boolean.mode",
            "state": "on"
          },
          {
            "condition": "or",
            "conditions": [
              {
                "condition": "state",
                "entity_id": "light.bedroom",
                "state": "on"
              },
              {
                "condition": "state",
                "entity_id": "light.living_room",
                "state": "on"
              }
            ]
          },
          {
            "condition": "not",
            "conditions": [
              {
                "condition": "state",
                "entity_id": "input_boolean.away",
                "state": "on"
              }
            ]
          }
        ]
      }
    ],
    "id": "condition_combinators",
    "triggers": [
      {
        "entity_id": "binary_sensor.motion",
        "to": "on",
        "trigger": "state"
      }
    ]
  }
}
```

### `not_`

Golden case: `fixtures/dsl/condition_combinators/`.

```python
"""Golden case: `any_of`/`all_of`/`not_` condition combinators.

Mirrors fixtures/configs/automation_condition_and_or_not.json (and/or/not
condition blocks).
"""

from hassle import all_of, any_of, automation, not_, only_if, service, state, when


@automation(id="condition_combinators", alias="Condition And Or Not")
def condition_combinators():
    when(state("binary_sensor.motion").to("on"))
    only_if(
        all_of(
            state("input_boolean.mode").is_("on"),
            any_of(
                state("light.bedroom").is_("on"),
                state("light.living_room").is_("on"),
            ),
            not_(state("input_boolean.away").is_("on")),
        )
    )
    service("light.turn_on", target={"entity_id": "light.hallway"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:condition_combinators": {
    "actions": [
      {
        "action": "light.turn_on",
        "target": {
          "entity_id": "light.hallway"
        }
      }
    ],
    "alias": "Condition And Or Not",
    "conditions": [
      {
        "condition": "and",
        "conditions": [
          {
            "condition": "state",
            "entity_id": "input_boolean.mode",
            "state": "on"
          },
          {
            "condition": "or",
            "conditions": [
              {
                "condition": "state",
                "entity_id": "light.bedroom",
                "state": "on"
              },
              {
                "condition": "state",
                "entity_id": "light.living_room",
                "state": "on"
              }
            ]
          },
          {
            "condition": "not",
            "conditions": [
              {
                "condition": "state",
                "entity_id": "input_boolean.away",
                "state": "on"
              }
            ]
          }
        ]
      }
    ],
    "id": "condition_combinators",
    "triggers": [
      {
        "entity_id": "binary_sensor.motion",
        "to": "on",
        "trigger": "state"
      }
    ]
  }
}
```

### `on`

Golden case: `fixtures/dsl/purpose_trigger_area_first/`.

```python
"""Golden case: purpose-specific trigger, area target, behavior=first.

Mirrors fixtures/configs/automation_purpose_trigger_area_behavior_first.json.
"""

from hassle import area, automation, on, service, when


@automation(id="purpose_trigger_area_first", alias="Purpose Trigger Area Behavior First")
def purpose_trigger_area_first():
    when(on("motion.detected", target=area("office"), behavior="first"))
    service("light.turn_on", target={"entity_id": "light.office_ceiling"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:purpose_trigger_area_first": {
    "actions": [
      {
        "action": "light.turn_on",
        "target": {
          "entity_id": "light.office_ceiling"
        }
      }
    ],
    "alias": "Purpose Trigger Area Behavior First",
    "conditions": [],
    "id": "purpose_trigger_area_first",
    "triggers": [
      {
        "behavior": "first",
        "target": {
          "area_id": "office"
        },
        "trigger": "motion.detected"
      }
    ]
  }
}
```

### `met`

Golden case: `fixtures/dsl/purpose_condition/`.

```python
"""Golden case: classic state trigger + purpose-specific condition.

Mirrors fixtures/configs/automation_purpose_condition.json.
"""

from hassle import automation, met, only_if, service, state, when


@automation(id="purpose_condition", alias="Purpose-Specific Condition")
def purpose_condition():
    when(state("binary_sensor.living_room_motion").to("on"))
    only_if(met("climate.is_target_temperature", target="climate.living_room"))
    service("light.turn_on", target={"entity_id": "light.living_room"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:purpose_condition": {
    "actions": [
      {
        "action": "light.turn_on",
        "target": {
          "entity_id": "light.living_room"
        }
      }
    ],
    "alias": "Purpose-Specific Condition",
    "conditions": [
      {
        "condition": "climate.is_target_temperature",
        "target": {
          "entity_id": "climate.living_room"
        }
      }
    ],
    "id": "purpose_condition",
    "triggers": [
      {
        "entity_id": "binary_sensor.living_room_motion",
        "to": "on",
        "trigger": "state"
      }
    ]
  }
}
```

### `area`

Golden case: `fixtures/dsl/purpose_trigger_area_first/`.

```python
"""Golden case: purpose-specific trigger, area target, behavior=first.

Mirrors fixtures/configs/automation_purpose_trigger_area_behavior_first.json.
"""

from hassle import area, automation, on, service, when


@automation(id="purpose_trigger_area_first", alias="Purpose Trigger Area Behavior First")
def purpose_trigger_area_first():
    when(on("motion.detected", target=area("office"), behavior="first"))
    service("light.turn_on", target={"entity_id": "light.office_ceiling"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:purpose_trigger_area_first": {
    "actions": [
      {
        "action": "light.turn_on",
        "target": {
          "entity_id": "light.office_ceiling"
        }
      }
    ],
    "alias": "Purpose Trigger Area Behavior First",
    "conditions": [],
    "id": "purpose_trigger_area_first",
    "triggers": [
      {
        "behavior": "first",
        "target": {
          "area_id": "office"
        },
        "trigger": "motion.detected"
      }
    ]
  }
}
```

### `floor`

Golden case: `fixtures/dsl/purpose_trigger_floor_each/`.

```python
"""Golden case: purpose-specific trigger, floor target, behavior=each.

Mirrors fixtures/configs/automation_purpose_trigger_floor_device.json (first
trigger only; the device-target trigger is covered by purpose_trigger_device).
"""

from hassle import automation, floor, on, service, when


@automation(id="purpose_trigger_floor_each", alias="Purpose Trigger Floor Behavior Each")
def purpose_trigger_floor_each():
    when(on("battery.became_low", target=floor("upstairs"), behavior="each"))
    service("notify.mobile_app_kai", message="Device event detected")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:purpose_trigger_floor_each": {
    "actions": [
      {
        "action": "notify.mobile_app_kai",
        "data": {
          "message": "Device event detected"
        }
      }
    ],
    "alias": "Purpose Trigger Floor Behavior Each",
    "conditions": [],
    "id": "purpose_trigger_floor_each",
    "triggers": [
      {
        "behavior": "each",
        "target": {
          "floor_id": "upstairs"
        },
        "trigger": "battery.became_low"
      }
    ]
  }
}
```

### `label`

Golden case: `fixtures/dsl/purpose_trigger_label_all/`.

```python
"""Golden case: purpose-specific trigger, label target, behavior=all.

Mirrors fixtures/configs/automation_purpose_trigger_label_behavior_all.json.
"""

from hassle import automation, label, on, service, when


@automation(id="purpose_trigger_label_all", alias="Purpose Trigger Label Behavior All")
def purpose_trigger_label_all():
    when(on("opening.opened", target=label("security"), behavior="all"))
    service("siren.turn_on", target={"entity_id": "siren.garage_alarm"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:purpose_trigger_label_all": {
    "actions": [
      {
        "action": "siren.turn_on",
        "target": {
          "entity_id": "siren.garage_alarm"
        }
      }
    ],
    "alias": "Purpose Trigger Label Behavior All",
    "conditions": [],
    "id": "purpose_trigger_label_all",
    "triggers": [
      {
        "behavior": "all",
        "target": {
          "label_id": "security"
        },
        "trigger": "opening.opened"
      }
    ]
  }
}
```

### `device_id`

Golden case: `fixtures/dsl/purpose_trigger_device/`.

```python
"""Golden case: purpose-specific trigger, device_id target.

Mirrors the second trigger of
fixtures/configs/automation_purpose_trigger_floor_device.json.
"""

from hassle import automation, device_id, on, service, when


@automation(id="purpose_trigger_device", alias="Purpose Trigger Device Target")
def purpose_trigger_device():
    when(on("vacuum.returned_to_dock", target=device_id("aaaabbbbccccdddd1111222233334444")))
    service("notify.mobile_app_kai", message="Device event detected")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:purpose_trigger_device": {
    "actions": [
      {
        "action": "notify.mobile_app_kai",
        "data": {
          "message": "Device event detected"
        }
      }
    ],
    "alias": "Purpose Trigger Device Target",
    "conditions": [],
    "id": "purpose_trigger_device",
    "triggers": [
      {
        "target": {
          "device_id": "aaaabbbbccccdddd1111222233334444"
        },
        "trigger": "vacuum.returned_to_dock"
      }
    ]
  }
}
```

### `hours`

Golden case: `fixtures/dsl/helper_declarations/`.

```python
"""Golden case: helper declarations for all nine storage-collection domains.

Each declaration is a whole top-level object (DESIGN §5.7); the compiler must
land every one in CompileResult.objects under "<domain>:<id>". Declaring them
also returns an EntityRef usable elsewhere in the bundle.
"""

from hassle import (
    counter,
    input_boolean,
    input_button,
    input_datetime,
    input_number,
    input_select,
    input_text,
    schedule,
    timer,
)

input_boolean(id="guest_mode", name="Guest Mode", icon="mdi:account")
input_number(id="target_temp", name="Target Temp", min=10, max=30, step=0.5, mode="slider")
input_select(id="house_mode", name="House Mode", options=["home", "away", "night"])
input_text(id="last_message", name="Last Message", max=255)
input_datetime(id="wake_time", name="Wake Time", has_date=False, has_time=True)
input_button(id="run_scene", name="Run Scene")
counter(id="door_opens", name="Door Opens", initial=0, step=1)
timer(id="cooldown", name="Cooldown", duration="00:05:00")
schedule(id="heating_schedule", name="Heating Schedule")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "counter:door_opens": {
    "id": "door_opens",
    "initial": 0,
    "name": "Door Opens",
    "step": 1
  },
  "input_boolean:guest_mode": {
    "icon": "mdi:account",
    "id": "guest_mode",
    "name": "Guest Mode"
  },
  "input_button:run_scene": {
    "id": "run_scene",
    "name": "Run Scene"
  },
  "input_datetime:wake_time": {
    "has_date": false,
    "has_time": true,
    "id": "wake_time",
    "name": "Wake Time"
  },
  "input_number:target_temp": {
    "id": "target_temp",
    "max": 30,
    "min": 10,
    "mode": "slider",
    "name": "Target Temp",
    "step": 0.5
  },
  "input_select:house_mode": {
    "id": "house_mode",
    "name": "House Mode",
    "options": [
      "home",
      "away",
      "night"
    ]
  },
  "input_text:last_message": {
    "id": "last_message",
    "max": 255,
    "name": "Last Message"
  },
  "schedule:heating_schedule": {
    "id": "heating_schedule",
    "name": "Heating Schedule"
  },
  "timer:cooldown": {
    "duration": "00:05:00",
    "id": "cooldown",
    "name": "Cooldown"
  }
}
```

### `minutes`

Golden case: `fixtures/dsl/state_delay_service/`.

```python
"""Golden case: state trigger + delay + service call.

Exercises the one end-to-end trigger builder (`state(...).to(...)`), the first
action primitive (`delay`), and a service-call action with kwargs.
"""

from hassle import automation, delay, service, state, when


@automation(id="hall_light_on_motion", alias="Hallway: light on motion", mode="restart")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", entity_id="light.hallway", brightness_pct=60)
    delay(minutes=5)
    service("light.turn_off", entity_id="light.hallway")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:hall_light_on_motion": {
    "actions": [
      {
        "action": "light.turn_on",
        "data": {
          "brightness_pct": 60,
          "entity_id": "light.hallway"
        }
      },
      {
        "delay": {
          "minutes": 5
        }
      },
      {
        "action": "light.turn_off",
        "data": {
          "entity_id": "light.hallway"
        }
      }
    ],
    "alias": "Hallway: light on motion",
    "conditions": [],
    "id": "hall_light_on_motion",
    "mode": "restart",
    "triggers": [
      {
        "entity_id": "binary_sensor.hall_motion",
        "to": "on",
        "trigger": "state"
      }
    ]
  }
}
```

### `seconds`

Golden case: `fixtures/dsl/repeat_count/`.

```python
"""Golden case: repeat_count(n) -> HA's `repeat.count` action."""

from hassle import automation, delay, repeat_count, service, state, when


@automation(id="porch_repeat_count", alias="Porch repeat count")
def porch_repeat_count():
    when(state("button.test").to("pressed"))
    with repeat_count(3):
        service("light.toggle", target={"entity_id": "light.hallway"})
        delay(seconds=1)
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:porch_repeat_count": {
    "actions": [
      {
        "repeat": {
          "count": 3,
          "sequence": [
            {
              "action": "light.toggle",
              "target": {
                "entity_id": "light.hallway"
              }
            },
            {
              "delay": {
                "seconds": 1
              }
            }
          ]
        }
      }
    ],
    "alias": "Porch repeat count",
    "conditions": [],
    "id": "porch_repeat_count",
    "triggers": [
      {
        "entity_id": "button.test",
        "to": "pressed",
        "trigger": "state"
      }
    ]
  }
}
```

### `expr`

Golden case: `fixtures/dsl/template_expr_golden/`.

```python
"""Golden case: the template expression builder (DESIGN §5.4).

Exercises: `state(x).value` numeric coercion, comparisons/arithmetic/boolean ops
building nested Jinja, `expr(entity_ref)` shorthand, and `template("{{ raw }}")`
passthrough. The automation's actions carry the emitted Jinja strings as plain
service-call data so the golden captures the exact compiled text.
"""

from hassle import automation, expr, service, state, template, when


@automation(id="template_demo", alias="Template expression demo")
def template_demo():
    when(state("binary_sensor.motion").to("on"))
    service(
        "notify.mobile_app",
        # comparison: numeric coercion + `>` operator
        is_hot=state("sensor.outdoor_temp").value > 25,
        # arithmetic: subtraction on a numeric expr()
        target_minus_one=expr("input_number.target_temp") - 1,
        # arithmetic then comparison (nested expression tree)
        adjusted_over_limit=(state("sensor.outdoor_temp").value + 2) > 30,
        # boolean and/or across two comparisons
        hot_and_armed=(state("sensor.outdoor_temp").value > 25)
        & (state("input_boolean.armed").value.eq("on")),
        hot_or_cold=(state("sensor.outdoor_temp").value > 30)
        | (state("sensor.outdoor_temp").value < 0),
        # boolean not
        not_armed=~(state("input_boolean.armed").value.eq("on")),
        # raw passthrough
        raw_expr=template("{{ now().hour }}"),
    )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:template_demo": {
    "actions": [
      {
        "action": "notify.mobile_app",
        "data": {
          "adjusted_over_limit": "{{ (states('sensor.outdoor_temp') | float + 2) > 30 }}",
          "hot_and_armed": "{{ (states('sensor.outdoor_temp') | float > 25) and (states('input_boolean.armed') | float == 'on') }}",
          "hot_or_cold": "{{ (states('sensor.outdoor_temp') | float > 30) or (states('sensor.outdoor_temp') | float < 0) }}",
          "is_hot": "{{ states('sensor.outdoor_temp') | float > 25 }}",
          "not_armed": "{{ not (states('input_boolean.armed') | float == 'on') }}",
          "raw_expr": "{{ now().hour }}",
          "target_minus_one": "{{ states('input_number.target_temp') | float - 1 }}"
        }
      }
    ],
    "alias": "Template expression demo",
    "conditions": [],
    "id": "template_demo",
    "triggers": [
      {
        "entity_id": "binary_sensor.motion",
        "to": "on",
        "trigger": "state"
      }
    ]
  }
}
```

### `state_of`

Golden case: `fixtures/dsl/state_of_string_golden/`.

```python
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
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:string_state_demo": {
    "actions": [
      {
        "action": "notify.mobile_app",
        "data": {
          "dawn_or_dusk": "{{ (states('sensor.time_of_day') == 'dawn') or (states('sensor.time_of_day') == 'dusk') }}",
          "day_and_hot": "{{ (states('sensor.time_of_day') == 'day') and (states('sensor.outdoor_temp') | float > 25) }}",
          "is_daytime": "{{ states('sensor.time_of_day') == 'day' }}",
          "is_daytime_via_ref": "{{ states('sensor.time_of_day') == 'day' }}",
          "is_not_night": "{{ states('sensor.time_of_day') != 'night' }}",
          "is_transition": "{{ states('sensor.time_of_day') in ['dawn', 'dusk'] }}",
          "not_night": "{{ not (states('sensor.time_of_day') == 'night') }}",
          "raw_state": "{{ states('sensor.time_of_day') }}"
        }
      }
    ],
    "alias": "String state expression demo",
    "conditions": [],
    "id": "string_state_demo",
    "triggers": [
      {
        "entity_id": "binary_sensor.motion",
        "to": "on",
        "trigger": "state"
      }
    ]
  }
}
```

See also: `fixtures/dsl/beacon_area_composition/`

### `param`

Golden case: `fixtures/dsl/shared_script_call/`.

```python
"""Golden case: @shared_script compiles to a script object AND a call action
(DESIGN §5.6).

`flash_lights` becomes a real HA script (fields derived from the signature,
defaults -> field defaults) whose sequence references `param("times")` and
`param("brightness")` as runtime template reads. The caller automation's
action list gets a `script.turn_on`-style call action (matching the corpus
script-call shape), never a re-run of the body.
"""

from hassle import automation, param, service, shared_script, state, when


@shared_script(id="flash_lights", alias="Flash lights", icon="mdi:alarm-light")
def flash_lights(times: int = 3, brightness: int = 255):
    service(
        "light.turn_on",
        entity_id="light.all_downstairs",
        brightness=param("brightness"),
    )
    service("light.turn_off", entity_id="light.all_downstairs")


@automation(id="guest_arrived", alias="Guest arrived")
def guest_arrived():
    when(state("binary_sensor.guest_sensor").to("on"))
    flash_lights(times=5, brightness=128)
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:guest_arrived": {
    "actions": [
      {
        "action": "script.flash_lights",
        "data": {
          "brightness": 128,
          "times": 5
        }
      }
    ],
    "alias": "Guest arrived",
    "conditions": [],
    "id": "guest_arrived",
    "triggers": [
      {
        "entity_id": "binary_sensor.guest_sensor",
        "to": "on",
        "trigger": "state"
      }
    ]
  },
  "script:flash_lights": {
    "alias": "Flash lights",
    "fields": {
      "brightness": {
        "default": 255
      },
      "times": {
        "default": 3
      }
    },
    "icon": "mdi:alarm-light",
    "sequence": [
      {
        "action": "light.turn_on",
        "data": {
          "brightness": "{{ brightness }}",
          "entity_id": "light.all_downstairs"
        }
      },
      {
        "action": "light.turn_off",
        "data": {
          "entity_id": "light.all_downstairs"
        }
      }
    ]
  }
}
```

### `field_default`

Golden case: `fixtures/dsl/shared_script_field_default_typed/`.

```python
"""Golden case: `field_default(...)`
is the typed-default helper for a `@shared_script` signature parameter
annotated `TemplateExpr` -- the BODY-TRUE type (every field-named parameter
is a runtime template marker inside the body, never its declared Python
default's type). `field_default(value)` is the identity function AT RUNTIME
(the compiler's `inspect.signature(...)` introspection sees the real
declared default, e.g. the plain `str` `""` below, completely unchanged) but
is TYPED as returning `TemplateExpr`, so the parameter's own default
expression type-checks against its `TemplateExpr` annotation without the
self-inconsistent `tag: TemplateExpr = ""` a bare literal default would be.

Caller-side typing is unaffected either way (verified empirically): a
caller passing a plain literal
(`dismiss_tagged_notification(tag="guest_reminder")`) is unaffected by
whatever this signature's own annotations say -- `@shared_script`'s returned
caller wrapper is `(*args: Any, **kwargs: Any) -> None`, fully decoupled.
"""

from hassle import automation, field_default, service, shared_script, state, when
from hassle.compiler.templates import TemplateExpr


@shared_script(id="dismiss_tagged_notification_typed", alias="Dismiss tagged (typed)")
def dismiss_tagged_notification_typed(tag: TemplateExpr = field_default("")):
    # Body-true composition: `tag` is a TemplateExpr marker, so `.eq(...)`
    # type-checks correctly (a `str`-annotated `tag` would NOT: `str` has no
    # `.eq()` method, `reportAttributeAccessIssue`).
    service(
        "persistent_notification.dismiss",
        notification_id=tag,
    )


@automation(id="dismiss_tagged_reminder_typed", alias="Dismiss tagged reminder (typed)")
def dismiss_tagged_reminder_typed():
    when(state("input_boolean.guest_mode").to("off"))
    dismiss_tagged_notification_typed(tag="guest_reminder")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:dismiss_tagged_reminder_typed": {
    "actions": [
      {
        "action": "script.dismiss_tagged_notification_typed",
        "data": {
          "tag": "guest_reminder"
        }
      }
    ],
    "alias": "Dismiss tagged reminder (typed)",
    "conditions": [],
    "id": "dismiss_tagged_reminder_typed",
    "triggers": [
      {
        "entity_id": "input_boolean.guest_mode",
        "to": "off",
        "trigger": "state"
      }
    ]
  },
  "script:dismiss_tagged_notification_typed": {
    "alias": "Dismiss tagged (typed)",
    "fields": {
      "tag": {
        "default": ""
      }
    },
    "sequence": [
      {
        "action": "persistent_notification.dismiss",
        "data": {
          "notification_id": "{{ tag }}"
        }
      }
    ]
  }
}
```

### `sin`

Golden case: `fixtures/dsl/math_expr_reference/`.

```python
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
extension; docs/internals/dsl-extensions.md "Runtime-math expression surface").
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
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:math_expr_reference": {
    "actions": [
      {
        "variables": {
          "abs_value": "{{ delta | abs }}",
          "angle_from_slopes": "{{ atan2(dy, dx) }}",
          "epoch_seconds": "{{ as_timestamp(event_time) }}",
          "eulers_number": "{{ e }}",
          "full_turn": "{{ tau }}",
          "half_hour": "{{ timedelta(minutes=30) }}",
          "inverse_trig": "{{ asin(ratio) + acos(ratio) + atan(ratio) }}",
          "joined_label": "{{ 'Room ' ~ room_name ~ ' is ready' }}",
          "largest": "{{ [a, b, c] | max }}",
          "log_value": "{{ log(x) }}",
          "magnitude": "{{ sqrt(x * x + y * y) }}",
          "parsed_time": "{{ as_datetime(wakeup_time) }}",
          "six_thirty": "{{ today_at('06:30:00') }}",
          "smallest": "{{ [a, b, c] | min }}",
          "trig": "{{ sin(angle) + tan(angle) }}",
          "wakeup_plus_offset": "{{ today_at('06:30:00') + timedelta(minutes=30) }}"
        }
      }
    ],
    "alias": "Math expr reference",
    "conditions": [],
    "id": "math_expr_reference",
    "mode": "single",
    "triggers": [
      {
        "minutes": "/5",
        "trigger": "time_pattern"
      }
    ]
  }
}
```

### `cos`

Golden case: `fixtures/dsl/shade_tracks_sun/`.

```python
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
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:shade_tracks_sun": {
    "actions": [
      {
        "action": "cover.set_cover_position",
        "data": {
          "position": "{{ (100 * cos(state_attr('sun.sun', 'elevation') * pi / 180)) | round(0) }}"
        },
        "target": {
          "entity_id": "cover.living_room_shade"
        }
      }
    ],
    "alias": "Shade Tracks Sun",
    "conditions": [
      {
        "above": 0,
        "attribute": "elevation",
        "condition": "numeric_state",
        "entity_id": "sun.sun"
      }
    ],
    "id": "shade_tracks_sun",
    "mode": "single",
    "triggers": [
      {
        "minutes": "/5",
        "trigger": "time_pattern"
      }
    ]
  }
}
```

### `tan`

Golden case: `fixtures/dsl/math_expr_reference/`.

```python
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
extension; docs/internals/dsl-extensions.md "Runtime-math expression surface").
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
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:math_expr_reference": {
    "actions": [
      {
        "variables": {
          "abs_value": "{{ delta | abs }}",
          "angle_from_slopes": "{{ atan2(dy, dx) }}",
          "epoch_seconds": "{{ as_timestamp(event_time) }}",
          "eulers_number": "{{ e }}",
          "full_turn": "{{ tau }}",
          "half_hour": "{{ timedelta(minutes=30) }}",
          "inverse_trig": "{{ asin(ratio) + acos(ratio) + atan(ratio) }}",
          "joined_label": "{{ 'Room ' ~ room_name ~ ' is ready' }}",
          "largest": "{{ [a, b, c] | max }}",
          "log_value": "{{ log(x) }}",
          "magnitude": "{{ sqrt(x * x + y * y) }}",
          "parsed_time": "{{ as_datetime(wakeup_time) }}",
          "six_thirty": "{{ today_at('06:30:00') }}",
          "smallest": "{{ [a, b, c] | min }}",
          "trig": "{{ sin(angle) + tan(angle) }}",
          "wakeup_plus_offset": "{{ today_at('06:30:00') + timedelta(minutes=30) }}"
        }
      }
    ],
    "alias": "Math expr reference",
    "conditions": [],
    "id": "math_expr_reference",
    "mode": "single",
    "triggers": [
      {
        "minutes": "/5",
        "trigger": "time_pattern"
      }
    ]
  }
}
```

### `asin`

Golden case: `fixtures/dsl/math_expr_reference/`.

```python
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
extension; docs/internals/dsl-extensions.md "Runtime-math expression surface").
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
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:math_expr_reference": {
    "actions": [
      {
        "variables": {
          "abs_value": "{{ delta | abs }}",
          "angle_from_slopes": "{{ atan2(dy, dx) }}",
          "epoch_seconds": "{{ as_timestamp(event_time) }}",
          "eulers_number": "{{ e }}",
          "full_turn": "{{ tau }}",
          "half_hour": "{{ timedelta(minutes=30) }}",
          "inverse_trig": "{{ asin(ratio) + acos(ratio) + atan(ratio) }}",
          "joined_label": "{{ 'Room ' ~ room_name ~ ' is ready' }}",
          "largest": "{{ [a, b, c] | max }}",
          "log_value": "{{ log(x) }}",
          "magnitude": "{{ sqrt(x * x + y * y) }}",
          "parsed_time": "{{ as_datetime(wakeup_time) }}",
          "six_thirty": "{{ today_at('06:30:00') }}",
          "smallest": "{{ [a, b, c] | min }}",
          "trig": "{{ sin(angle) + tan(angle) }}",
          "wakeup_plus_offset": "{{ today_at('06:30:00') + timedelta(minutes=30) }}"
        }
      }
    ],
    "alias": "Math expr reference",
    "conditions": [],
    "id": "math_expr_reference",
    "mode": "single",
    "triggers": [
      {
        "minutes": "/5",
        "trigger": "time_pattern"
      }
    ]
  }
}
```

### `acos`

Golden case: `fixtures/dsl/math_expr_reference/`.

```python
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
extension; docs/internals/dsl-extensions.md "Runtime-math expression surface").
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
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:math_expr_reference": {
    "actions": [
      {
        "variables": {
          "abs_value": "{{ delta | abs }}",
          "angle_from_slopes": "{{ atan2(dy, dx) }}",
          "epoch_seconds": "{{ as_timestamp(event_time) }}",
          "eulers_number": "{{ e }}",
          "full_turn": "{{ tau }}",
          "half_hour": "{{ timedelta(minutes=30) }}",
          "inverse_trig": "{{ asin(ratio) + acos(ratio) + atan(ratio) }}",
          "joined_label": "{{ 'Room ' ~ room_name ~ ' is ready' }}",
          "largest": "{{ [a, b, c] | max }}",
          "log_value": "{{ log(x) }}",
          "magnitude": "{{ sqrt(x * x + y * y) }}",
          "parsed_time": "{{ as_datetime(wakeup_time) }}",
          "six_thirty": "{{ today_at('06:30:00') }}",
          "smallest": "{{ [a, b, c] | min }}",
          "trig": "{{ sin(angle) + tan(angle) }}",
          "wakeup_plus_offset": "{{ today_at('06:30:00') + timedelta(minutes=30) }}"
        }
      }
    ],
    "alias": "Math expr reference",
    "conditions": [],
    "id": "math_expr_reference",
    "mode": "single",
    "triggers": [
      {
        "minutes": "/5",
        "trigger": "time_pattern"
      }
    ]
  }
}
```

### `atan`

Golden case: `fixtures/dsl/math_expr_reference/`.

```python
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
extension; docs/internals/dsl-extensions.md "Runtime-math expression surface").
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
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:math_expr_reference": {
    "actions": [
      {
        "variables": {
          "abs_value": "{{ delta | abs }}",
          "angle_from_slopes": "{{ atan2(dy, dx) }}",
          "epoch_seconds": "{{ as_timestamp(event_time) }}",
          "eulers_number": "{{ e }}",
          "full_turn": "{{ tau }}",
          "half_hour": "{{ timedelta(minutes=30) }}",
          "inverse_trig": "{{ asin(ratio) + acos(ratio) + atan(ratio) }}",
          "joined_label": "{{ 'Room ' ~ room_name ~ ' is ready' }}",
          "largest": "{{ [a, b, c] | max }}",
          "log_value": "{{ log(x) }}",
          "magnitude": "{{ sqrt(x * x + y * y) }}",
          "parsed_time": "{{ as_datetime(wakeup_time) }}",
          "six_thirty": "{{ today_at('06:30:00') }}",
          "smallest": "{{ [a, b, c] | min }}",
          "trig": "{{ sin(angle) + tan(angle) }}",
          "wakeup_plus_offset": "{{ today_at('06:30:00') + timedelta(minutes=30) }}"
        }
      }
    ],
    "alias": "Math expr reference",
    "conditions": [],
    "id": "math_expr_reference",
    "mode": "single",
    "triggers": [
      {
        "minutes": "/5",
        "trigger": "time_pattern"
      }
    ]
  }
}
```

### `atan2`

Golden case: `fixtures/dsl/math_expr_reference/`.

```python
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
extension; docs/internals/dsl-extensions.md "Runtime-math expression surface").
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
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:math_expr_reference": {
    "actions": [
      {
        "variables": {
          "abs_value": "{{ delta | abs }}",
          "angle_from_slopes": "{{ atan2(dy, dx) }}",
          "epoch_seconds": "{{ as_timestamp(event_time) }}",
          "eulers_number": "{{ e }}",
          "full_turn": "{{ tau }}",
          "half_hour": "{{ timedelta(minutes=30) }}",
          "inverse_trig": "{{ asin(ratio) + acos(ratio) + atan(ratio) }}",
          "joined_label": "{{ 'Room ' ~ room_name ~ ' is ready' }}",
          "largest": "{{ [a, b, c] | max }}",
          "log_value": "{{ log(x) }}",
          "magnitude": "{{ sqrt(x * x + y * y) }}",
          "parsed_time": "{{ as_datetime(wakeup_time) }}",
          "six_thirty": "{{ today_at('06:30:00') }}",
          "smallest": "{{ [a, b, c] | min }}",
          "trig": "{{ sin(angle) + tan(angle) }}",
          "wakeup_plus_offset": "{{ today_at('06:30:00') + timedelta(minutes=30) }}"
        }
      }
    ],
    "alias": "Math expr reference",
    "conditions": [],
    "id": "math_expr_reference",
    "mode": "single",
    "triggers": [
      {
        "minutes": "/5",
        "trigger": "time_pattern"
      }
    ]
  }
}
```

### `sqrt`

Golden case: `fixtures/dsl/math_expr_reference/`.

```python
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
extension; docs/internals/dsl-extensions.md "Runtime-math expression surface").
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
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:math_expr_reference": {
    "actions": [
      {
        "variables": {
          "abs_value": "{{ delta | abs }}",
          "angle_from_slopes": "{{ atan2(dy, dx) }}",
          "epoch_seconds": "{{ as_timestamp(event_time) }}",
          "eulers_number": "{{ e }}",
          "full_turn": "{{ tau }}",
          "half_hour": "{{ timedelta(minutes=30) }}",
          "inverse_trig": "{{ asin(ratio) + acos(ratio) + atan(ratio) }}",
          "joined_label": "{{ 'Room ' ~ room_name ~ ' is ready' }}",
          "largest": "{{ [a, b, c] | max }}",
          "log_value": "{{ log(x) }}",
          "magnitude": "{{ sqrt(x * x + y * y) }}",
          "parsed_time": "{{ as_datetime(wakeup_time) }}",
          "six_thirty": "{{ today_at('06:30:00') }}",
          "smallest": "{{ [a, b, c] | min }}",
          "trig": "{{ sin(angle) + tan(angle) }}",
          "wakeup_plus_offset": "{{ today_at('06:30:00') + timedelta(minutes=30) }}"
        }
      }
    ],
    "alias": "Math expr reference",
    "conditions": [],
    "id": "math_expr_reference",
    "mode": "single",
    "triggers": [
      {
        "minutes": "/5",
        "trigger": "time_pattern"
      }
    ]
  }
}
```

### `log`

Golden case: `fixtures/dsl/math_expr_reference/`.

```python
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
extension; docs/internals/dsl-extensions.md "Runtime-math expression surface").
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
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:math_expr_reference": {
    "actions": [
      {
        "variables": {
          "abs_value": "{{ delta | abs }}",
          "angle_from_slopes": "{{ atan2(dy, dx) }}",
          "epoch_seconds": "{{ as_timestamp(event_time) }}",
          "eulers_number": "{{ e }}",
          "full_turn": "{{ tau }}",
          "half_hour": "{{ timedelta(minutes=30) }}",
          "inverse_trig": "{{ asin(ratio) + acos(ratio) + atan(ratio) }}",
          "joined_label": "{{ 'Room ' ~ room_name ~ ' is ready' }}",
          "largest": "{{ [a, b, c] | max }}",
          "log_value": "{{ log(x) }}",
          "magnitude": "{{ sqrt(x * x + y * y) }}",
          "parsed_time": "{{ as_datetime(wakeup_time) }}",
          "six_thirty": "{{ today_at('06:30:00') }}",
          "smallest": "{{ [a, b, c] | min }}",
          "trig": "{{ sin(angle) + tan(angle) }}",
          "wakeup_plus_offset": "{{ today_at('06:30:00') + timedelta(minutes=30) }}"
        }
      }
    ],
    "alias": "Math expr reference",
    "conditions": [],
    "id": "math_expr_reference",
    "mode": "single",
    "triggers": [
      {
        "minutes": "/5",
        "trigger": "time_pattern"
      }
    ]
  }
}
```

### `round_`

Golden case: `fixtures/dsl/shade_tracks_sun/`.

```python
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
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:shade_tracks_sun": {
    "actions": [
      {
        "action": "cover.set_cover_position",
        "data": {
          "position": "{{ (100 * cos(state_attr('sun.sun', 'elevation') * pi / 180)) | round(0) }}"
        },
        "target": {
          "entity_id": "cover.living_room_shade"
        }
      }
    ],
    "alias": "Shade Tracks Sun",
    "conditions": [
      {
        "above": 0,
        "attribute": "elevation",
        "condition": "numeric_state",
        "entity_id": "sun.sun"
      }
    ],
    "id": "shade_tracks_sun",
    "mode": "single",
    "triggers": [
      {
        "minutes": "/5",
        "trigger": "time_pattern"
      }
    ]
  }
}
```

### `abs_`

Golden case: `fixtures/dsl/math_expr_reference/`.

```python
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
extension; docs/internals/dsl-extensions.md "Runtime-math expression surface").
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
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:math_expr_reference": {
    "actions": [
      {
        "variables": {
          "abs_value": "{{ delta | abs }}",
          "angle_from_slopes": "{{ atan2(dy, dx) }}",
          "epoch_seconds": "{{ as_timestamp(event_time) }}",
          "eulers_number": "{{ e }}",
          "full_turn": "{{ tau }}",
          "half_hour": "{{ timedelta(minutes=30) }}",
          "inverse_trig": "{{ asin(ratio) + acos(ratio) + atan(ratio) }}",
          "joined_label": "{{ 'Room ' ~ room_name ~ ' is ready' }}",
          "largest": "{{ [a, b, c] | max }}",
          "log_value": "{{ log(x) }}",
          "magnitude": "{{ sqrt(x * x + y * y) }}",
          "parsed_time": "{{ as_datetime(wakeup_time) }}",
          "six_thirty": "{{ today_at('06:30:00') }}",
          "smallest": "{{ [a, b, c] | min }}",
          "trig": "{{ sin(angle) + tan(angle) }}",
          "wakeup_plus_offset": "{{ today_at('06:30:00') + timedelta(minutes=30) }}"
        }
      }
    ],
    "alias": "Math expr reference",
    "conditions": [],
    "id": "math_expr_reference",
    "mode": "single",
    "triggers": [
      {
        "minutes": "/5",
        "trigger": "time_pattern"
      }
    ]
  }
}
```

### `min_`

Golden case: `fixtures/dsl/math_expr_reference/`.

```python
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
extension; docs/internals/dsl-extensions.md "Runtime-math expression surface").
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
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:math_expr_reference": {
    "actions": [
      {
        "variables": {
          "abs_value": "{{ delta | abs }}",
          "angle_from_slopes": "{{ atan2(dy, dx) }}",
          "epoch_seconds": "{{ as_timestamp(event_time) }}",
          "eulers_number": "{{ e }}",
          "full_turn": "{{ tau }}",
          "half_hour": "{{ timedelta(minutes=30) }}",
          "inverse_trig": "{{ asin(ratio) + acos(ratio) + atan(ratio) }}",
          "joined_label": "{{ 'Room ' ~ room_name ~ ' is ready' }}",
          "largest": "{{ [a, b, c] | max }}",
          "log_value": "{{ log(x) }}",
          "magnitude": "{{ sqrt(x * x + y * y) }}",
          "parsed_time": "{{ as_datetime(wakeup_time) }}",
          "six_thirty": "{{ today_at('06:30:00') }}",
          "smallest": "{{ [a, b, c] | min }}",
          "trig": "{{ sin(angle) + tan(angle) }}",
          "wakeup_plus_offset": "{{ today_at('06:30:00') + timedelta(minutes=30) }}"
        }
      }
    ],
    "alias": "Math expr reference",
    "conditions": [],
    "id": "math_expr_reference",
    "mode": "single",
    "triggers": [
      {
        "minutes": "/5",
        "trigger": "time_pattern"
      }
    ]
  }
}
```

### `max_`

Golden case: `fixtures/dsl/math_expr_reference/`.

```python
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
extension; docs/internals/dsl-extensions.md "Runtime-math expression surface").
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
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:math_expr_reference": {
    "actions": [
      {
        "variables": {
          "abs_value": "{{ delta | abs }}",
          "angle_from_slopes": "{{ atan2(dy, dx) }}",
          "epoch_seconds": "{{ as_timestamp(event_time) }}",
          "eulers_number": "{{ e }}",
          "full_turn": "{{ tau }}",
          "half_hour": "{{ timedelta(minutes=30) }}",
          "inverse_trig": "{{ asin(ratio) + acos(ratio) + atan(ratio) }}",
          "joined_label": "{{ 'Room ' ~ room_name ~ ' is ready' }}",
          "largest": "{{ [a, b, c] | max }}",
          "log_value": "{{ log(x) }}",
          "magnitude": "{{ sqrt(x * x + y * y) }}",
          "parsed_time": "{{ as_datetime(wakeup_time) }}",
          "six_thirty": "{{ today_at('06:30:00') }}",
          "smallest": "{{ [a, b, c] | min }}",
          "trig": "{{ sin(angle) + tan(angle) }}",
          "wakeup_plus_offset": "{{ today_at('06:30:00') + timedelta(minutes=30) }}"
        }
      }
    ],
    "alias": "Math expr reference",
    "conditions": [],
    "id": "math_expr_reference",
    "mode": "single",
    "triggers": [
      {
        "minutes": "/5",
        "trigger": "time_pattern"
      }
    ]
  }
}
```

### `as_datetime`

Golden case: `fixtures/dsl/math_expr_reference/`.

```python
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
extension; docs/internals/dsl-extensions.md "Runtime-math expression surface").
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
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:math_expr_reference": {
    "actions": [
      {
        "variables": {
          "abs_value": "{{ delta | abs }}",
          "angle_from_slopes": "{{ atan2(dy, dx) }}",
          "epoch_seconds": "{{ as_timestamp(event_time) }}",
          "eulers_number": "{{ e }}",
          "full_turn": "{{ tau }}",
          "half_hour": "{{ timedelta(minutes=30) }}",
          "inverse_trig": "{{ asin(ratio) + acos(ratio) + atan(ratio) }}",
          "joined_label": "{{ 'Room ' ~ room_name ~ ' is ready' }}",
          "largest": "{{ [a, b, c] | max }}",
          "log_value": "{{ log(x) }}",
          "magnitude": "{{ sqrt(x * x + y * y) }}",
          "parsed_time": "{{ as_datetime(wakeup_time) }}",
          "six_thirty": "{{ today_at('06:30:00') }}",
          "smallest": "{{ [a, b, c] | min }}",
          "trig": "{{ sin(angle) + tan(angle) }}",
          "wakeup_plus_offset": "{{ today_at('06:30:00') + timedelta(minutes=30) }}"
        }
      }
    ],
    "alias": "Math expr reference",
    "conditions": [],
    "id": "math_expr_reference",
    "mode": "single",
    "triggers": [
      {
        "minutes": "/5",
        "trigger": "time_pattern"
      }
    ]
  }
}
```

### `as_timestamp`

Golden case: `fixtures/dsl/math_expr_reference/`.

```python
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
extension; docs/internals/dsl-extensions.md "Runtime-math expression surface").
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
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:math_expr_reference": {
    "actions": [
      {
        "variables": {
          "abs_value": "{{ delta | abs }}",
          "angle_from_slopes": "{{ atan2(dy, dx) }}",
          "epoch_seconds": "{{ as_timestamp(event_time) }}",
          "eulers_number": "{{ e }}",
          "full_turn": "{{ tau }}",
          "half_hour": "{{ timedelta(minutes=30) }}",
          "inverse_trig": "{{ asin(ratio) + acos(ratio) + atan(ratio) }}",
          "joined_label": "{{ 'Room ' ~ room_name ~ ' is ready' }}",
          "largest": "{{ [a, b, c] | max }}",
          "log_value": "{{ log(x) }}",
          "magnitude": "{{ sqrt(x * x + y * y) }}",
          "parsed_time": "{{ as_datetime(wakeup_time) }}",
          "six_thirty": "{{ today_at('06:30:00') }}",
          "smallest": "{{ [a, b, c] | min }}",
          "trig": "{{ sin(angle) + tan(angle) }}",
          "wakeup_plus_offset": "{{ today_at('06:30:00') + timedelta(minutes=30) }}"
        }
      }
    ],
    "alias": "Math expr reference",
    "conditions": [],
    "id": "math_expr_reference",
    "mode": "single",
    "triggers": [
      {
        "minutes": "/5",
        "trigger": "time_pattern"
      }
    ]
  }
}
```

### `today_at`

Golden case: `fixtures/dsl/math_expr_reference/`.

```python
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
extension; docs/internals/dsl-extensions.md "Runtime-math expression surface").
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
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:math_expr_reference": {
    "actions": [
      {
        "variables": {
          "abs_value": "{{ delta | abs }}",
          "angle_from_slopes": "{{ atan2(dy, dx) }}",
          "epoch_seconds": "{{ as_timestamp(event_time) }}",
          "eulers_number": "{{ e }}",
          "full_turn": "{{ tau }}",
          "half_hour": "{{ timedelta(minutes=30) }}",
          "inverse_trig": "{{ asin(ratio) + acos(ratio) + atan(ratio) }}",
          "joined_label": "{{ 'Room ' ~ room_name ~ ' is ready' }}",
          "largest": "{{ [a, b, c] | max }}",
          "log_value": "{{ log(x) }}",
          "magnitude": "{{ sqrt(x * x + y * y) }}",
          "parsed_time": "{{ as_datetime(wakeup_time) }}",
          "six_thirty": "{{ today_at('06:30:00') }}",
          "smallest": "{{ [a, b, c] | min }}",
          "trig": "{{ sin(angle) + tan(angle) }}",
          "wakeup_plus_offset": "{{ today_at('06:30:00') + timedelta(minutes=30) }}"
        }
      }
    ],
    "alias": "Math expr reference",
    "conditions": [],
    "id": "math_expr_reference",
    "mode": "single",
    "triggers": [
      {
        "minutes": "/5",
        "trigger": "time_pattern"
      }
    ]
  }
}
```

### `timedelta_`

Golden case: `fixtures/dsl/math_expr_reference/`.

```python
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
extension; docs/internals/dsl-extensions.md "Runtime-math expression surface").
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
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:math_expr_reference": {
    "actions": [
      {
        "variables": {
          "abs_value": "{{ delta | abs }}",
          "angle_from_slopes": "{{ atan2(dy, dx) }}",
          "epoch_seconds": "{{ as_timestamp(event_time) }}",
          "eulers_number": "{{ e }}",
          "full_turn": "{{ tau }}",
          "half_hour": "{{ timedelta(minutes=30) }}",
          "inverse_trig": "{{ asin(ratio) + acos(ratio) + atan(ratio) }}",
          "joined_label": "{{ 'Room ' ~ room_name ~ ' is ready' }}",
          "largest": "{{ [a, b, c] | max }}",
          "log_value": "{{ log(x) }}",
          "magnitude": "{{ sqrt(x * x + y * y) }}",
          "parsed_time": "{{ as_datetime(wakeup_time) }}",
          "six_thirty": "{{ today_at('06:30:00') }}",
          "smallest": "{{ [a, b, c] | min }}",
          "trig": "{{ sin(angle) + tan(angle) }}",
          "wakeup_plus_offset": "{{ today_at('06:30:00') + timedelta(minutes=30) }}"
        }
      }
    ],
    "alias": "Math expr reference",
    "conditions": [],
    "id": "math_expr_reference",
    "mode": "single",
    "triggers": [
      {
        "minutes": "/5",
        "trigger": "time_pattern"
      }
    ]
  }
}
```

### `var`

Golden case: `fixtures/dsl/math_expr_reference/`.

```python
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
extension; docs/internals/dsl-extensions.md "Runtime-math expression surface").
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
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:math_expr_reference": {
    "actions": [
      {
        "variables": {
          "abs_value": "{{ delta | abs }}",
          "angle_from_slopes": "{{ atan2(dy, dx) }}",
          "epoch_seconds": "{{ as_timestamp(event_time) }}",
          "eulers_number": "{{ e }}",
          "full_turn": "{{ tau }}",
          "half_hour": "{{ timedelta(minutes=30) }}",
          "inverse_trig": "{{ asin(ratio) + acos(ratio) + atan(ratio) }}",
          "joined_label": "{{ 'Room ' ~ room_name ~ ' is ready' }}",
          "largest": "{{ [a, b, c] | max }}",
          "log_value": "{{ log(x) }}",
          "magnitude": "{{ sqrt(x * x + y * y) }}",
          "parsed_time": "{{ as_datetime(wakeup_time) }}",
          "six_thirty": "{{ today_at('06:30:00') }}",
          "smallest": "{{ [a, b, c] | min }}",
          "trig": "{{ sin(angle) + tan(angle) }}",
          "wakeup_plus_offset": "{{ today_at('06:30:00') + timedelta(minutes=30) }}"
        }
      }
    ],
    "alias": "Math expr reference",
    "conditions": [],
    "id": "math_expr_reference",
    "mode": "single",
    "triggers": [
      {
        "minutes": "/5",
        "trigger": "time_pattern"
      }
    ]
  }
}
```

### `concat`

Golden case: `fixtures/dsl/math_expr_reference/`.

```python
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
extension; docs/internals/dsl-extensions.md "Runtime-math expression surface").
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
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:math_expr_reference": {
    "actions": [
      {
        "variables": {
          "abs_value": "{{ delta | abs }}",
          "angle_from_slopes": "{{ atan2(dy, dx) }}",
          "epoch_seconds": "{{ as_timestamp(event_time) }}",
          "eulers_number": "{{ e }}",
          "full_turn": "{{ tau }}",
          "half_hour": "{{ timedelta(minutes=30) }}",
          "inverse_trig": "{{ asin(ratio) + acos(ratio) + atan(ratio) }}",
          "joined_label": "{{ 'Room ' ~ room_name ~ ' is ready' }}",
          "largest": "{{ [a, b, c] | max }}",
          "log_value": "{{ log(x) }}",
          "magnitude": "{{ sqrt(x * x + y * y) }}",
          "parsed_time": "{{ as_datetime(wakeup_time) }}",
          "six_thirty": "{{ today_at('06:30:00') }}",
          "smallest": "{{ [a, b, c] | min }}",
          "trig": "{{ sin(angle) + tan(angle) }}",
          "wakeup_plus_offset": "{{ today_at('06:30:00') + timedelta(minutes=30) }}"
        }
      }
    ],
    "alias": "Math expr reference",
    "conditions": [],
    "id": "math_expr_reference",
    "mode": "single",
    "triggers": [
      {
        "minutes": "/5",
        "trigger": "time_pattern"
      }
    ]
  }
}
```

### `if_then`

Golden case: `fixtures/dsl/if_then_else/`.

```python
"""Golden case: if_then / else_then -> HA's `if`/`then`/`else` action.

Matches the shape of fixtures/configs/automation_if_then_else.json (a state
trigger, an `if` with a nested service call, and an else branch).
"""

from hassle import automation, else_then, if_then, service, state, when


@automation(id="thermostat_if_then", alias="Thermostat if/then/else")
def thermostat_if_then():
    when(state("sensor.temperature").to("above_25"))
    with if_then(state("sensor.temperature").is_("above_25")):
        service(
            "climate.set_temperature",
            target={"entity_id": "climate.living_room"},
            temperature=20,
        )
    with else_then():
        service(
            "climate.set_temperature",
            target={"entity_id": "climate.living_room"},
            temperature=22,
        )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:thermostat_if_then": {
    "actions": [
      {
        "else": [
          {
            "action": "climate.set_temperature",
            "data": {
              "temperature": 22
            },
            "target": {
              "entity_id": "climate.living_room"
            }
          }
        ],
        "if": [
          {
            "condition": "state",
            "entity_id": "sensor.temperature",
            "state": "above_25"
          }
        ],
        "then": [
          {
            "action": "climate.set_temperature",
            "data": {
              "temperature": 20
            },
            "target": {
              "entity_id": "climate.living_room"
            }
          }
        ]
      }
    ],
    "alias": "Thermostat if/then/else",
    "conditions": [],
    "id": "thermostat_if_then",
    "triggers": [
      {
        "entity_id": "sensor.temperature",
        "to": "above_25",
        "trigger": "state"
      }
    ]
  }
}
```

### `else_then`

Golden case: `fixtures/dsl/if_then_else/`.

```python
"""Golden case: if_then / else_then -> HA's `if`/`then`/`else` action.

Matches the shape of fixtures/configs/automation_if_then_else.json (a state
trigger, an `if` with a nested service call, and an else branch).
"""

from hassle import automation, else_then, if_then, service, state, when


@automation(id="thermostat_if_then", alias="Thermostat if/then/else")
def thermostat_if_then():
    when(state("sensor.temperature").to("above_25"))
    with if_then(state("sensor.temperature").is_("above_25")):
        service(
            "climate.set_temperature",
            target={"entity_id": "climate.living_room"},
            temperature=20,
        )
    with else_then():
        service(
            "climate.set_temperature",
            target={"entity_id": "climate.living_room"},
            temperature=22,
        )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:thermostat_if_then": {
    "actions": [
      {
        "else": [
          {
            "action": "climate.set_temperature",
            "data": {
              "temperature": 22
            },
            "target": {
              "entity_id": "climate.living_room"
            }
          }
        ],
        "if": [
          {
            "condition": "state",
            "entity_id": "sensor.temperature",
            "state": "above_25"
          }
        ],
        "then": [
          {
            "action": "climate.set_temperature",
            "data": {
              "temperature": 20
            },
            "target": {
              "entity_id": "climate.living_room"
            }
          }
        ]
      }
    ],
    "alias": "Thermostat if/then/else",
    "conditions": [],
    "id": "thermostat_if_then",
    "triggers": [
      {
        "entity_id": "sensor.temperature",
        "to": "above_25",
        "trigger": "state"
      }
    ]
  }
}
```

### `else_if`

Golden case: `fixtures/dsl/if_elseif_else/`.

```python
"""Golden case: if_then / else_if / else_then chain -> HA's `choose` action.

Multiple mutually-exclusive branches (`if` + one or more `else_if`) compile to
a `choose` action (HA has no native `elif`); the trailing `else_then` becomes
the `choose`'s `default`.
"""

from hassle import automation, else_if, else_then, if_then, service, state, when


@automation(id="climate_elseif", alias="Climate if/elif/else")
def climate_elseif():
    when(state("sensor.temperature").to("changed"))
    target = {"entity_id": "climate.living_room"}
    with if_then(state("sensor.temperature").is_("hot")):
        service("climate.set_temperature", target=target, temperature=18)
    with else_if(state("sensor.temperature").is_("cold")):
        service("climate.set_temperature", target=target, temperature=24)
    with else_then():
        service("climate.set_temperature", target=target, temperature=21)
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:climate_elseif": {
    "actions": [
      {
        "choose": [
          {
            "conditions": [
              {
                "condition": "state",
                "entity_id": "sensor.temperature",
                "state": "hot"
              }
            ],
            "sequence": [
              {
                "action": "climate.set_temperature",
                "data": {
                  "temperature": 18
                },
                "target": {
                  "entity_id": "climate.living_room"
                }
              }
            ]
          },
          {
            "conditions": [
              {
                "condition": "state",
                "entity_id": "sensor.temperature",
                "state": "cold"
              }
            ],
            "sequence": [
              {
                "action": "climate.set_temperature",
                "data": {
                  "temperature": 24
                },
                "target": {
                  "entity_id": "climate.living_room"
                }
              }
            ]
          }
        ],
        "default": [
          {
            "action": "climate.set_temperature",
            "data": {
              "temperature": 21
            },
            "target": {
              "entity_id": "climate.living_room"
            }
          }
        ]
      }
    ],
    "alias": "Climate if/elif/else",
    "conditions": [],
    "id": "climate_elseif",
    "triggers": [
      {
        "entity_id": "sensor.temperature",
        "to": "changed",
        "trigger": "state"
      }
    ]
  }
}
```

### `choose`

Golden case: `fixtures/dsl/choose_action/`.

```python
"""Golden case: choose() with when_() branches + default().

Matches fixtures/configs/automation_choose_action.json's stored shape: a list
of {conditions, sequence} branches plus a trailing `default` sequence.
"""

from hassle import automation, choose, service, state, when


@automation(id="bedroom_choose", alias="Bedroom choose")
def bedroom_choose():
    when(state("binary_sensor.motion").to("on"))
    with choose() as c:
        with c.when_(state("light.bedroom").is_("off")):
            service(
                "light.turn_on",
                target={"entity_id": "light.bedroom"},
                brightness=255,
            )
        with c.when_(state("light.bedroom").is_("on")):
            service("light.turn_off", target={"entity_id": "light.bedroom"})
        with c.default():
            service("light.toggle", target={"entity_id": "light.bedroom"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:bedroom_choose": {
    "actions": [
      {
        "choose": [
          {
            "conditions": [
              {
                "condition": "state",
                "entity_id": "light.bedroom",
                "state": "off"
              }
            ],
            "sequence": [
              {
                "action": "light.turn_on",
                "data": {
                  "brightness": 255
                },
                "target": {
                  "entity_id": "light.bedroom"
                }
              }
            ]
          },
          {
            "conditions": [
              {
                "condition": "state",
                "entity_id": "light.bedroom",
                "state": "on"
              }
            ],
            "sequence": [
              {
                "action": "light.turn_off",
                "target": {
                  "entity_id": "light.bedroom"
                }
              }
            ]
          }
        ],
        "default": [
          {
            "action": "light.toggle",
            "target": {
              "entity_id": "light.bedroom"
            }
          }
        ]
      }
    ],
    "alias": "Bedroom choose",
    "conditions": [],
    "id": "bedroom_choose",
    "triggers": [
      {
        "entity_id": "binary_sensor.motion",
        "to": "on",
        "trigger": "state"
      }
    ]
  }
}
```

### `repeat_count`

Golden case: `fixtures/dsl/repeat_count/`.

```python
"""Golden case: repeat_count(n) -> HA's `repeat.count` action."""

from hassle import automation, delay, repeat_count, service, state, when


@automation(id="porch_repeat_count", alias="Porch repeat count")
def porch_repeat_count():
    when(state("button.test").to("pressed"))
    with repeat_count(3):
        service("light.toggle", target={"entity_id": "light.hallway"})
        delay(seconds=1)
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:porch_repeat_count": {
    "actions": [
      {
        "repeat": {
          "count": 3,
          "sequence": [
            {
              "action": "light.toggle",
              "target": {
                "entity_id": "light.hallway"
              }
            },
            {
              "delay": {
                "seconds": 1
              }
            }
          ]
        }
      }
    ],
    "alias": "Porch repeat count",
    "conditions": [],
    "id": "porch_repeat_count",
    "triggers": [
      {
        "entity_id": "button.test",
        "to": "pressed",
        "trigger": "state"
      }
    ]
  }
}
```

See also: `fixtures/dsl/shared_script_repeat_count_marker/`

### `repeat_while`

Golden case: `fixtures/dsl/repeat_while/`.

```python
"""Golden case: repeat_while(cond) -> HA's `repeat.while` action.

The while condition is a `template(...)` condition — the corpus shape
UI-authored `repeat` loops carry (`condition: template`), so the golden mirrors
the real fixture shape rather than a placeholder state condition.
"""

from hassle import automation, repeat_while, service, state, template, when


@automation(id="repeat_while_counter", alias="Repeat while counter")
def repeat_while_counter():
    when(state("sensor.counter").to("changed"))
    with repeat_while(template("{{ states('input_number.counter') | int < 10 }}")):
        service("input_number.increment", target={"entity_id": "input_number.counter"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:repeat_while_counter": {
    "actions": [
      {
        "repeat": {
          "sequence": [
            {
              "action": "input_number.increment",
              "target": {
                "entity_id": "input_number.counter"
              }
            }
          ],
          "while": [
            {
              "condition": "template",
              "value_template": "{{ states('input_number.counter') | int < 10 }}"
            }
          ]
        }
      }
    ],
    "alias": "Repeat while counter",
    "conditions": [],
    "id": "repeat_while_counter",
    "triggers": [
      {
        "entity_id": "sensor.counter",
        "to": "changed",
        "trigger": "state"
      }
    ]
  }
}
```

### `repeat_until`

Golden case: `fixtures/dsl/repeat_until/`.

```python
"""Golden case: repeat_until(cond) -> HA's `repeat.until` action.

The until condition is a `template(...)` condition — the corpus shape
UI-authored `repeat` loops carry (`condition: template`), so the golden mirrors
the real fixture shape rather than a placeholder state condition.
"""

from hassle import automation, repeat_until, service, state, template, when


@automation(id="repeat_until_done", alias="Repeat until done")
def repeat_until_done():
    when(state("input_boolean.done").to("off"))
    with repeat_until(template("{{ is_state('input_boolean.done', 'on') }}")):
        service("input_boolean.turn_on", target={"entity_id": "input_boolean.done"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:repeat_until_done": {
    "actions": [
      {
        "repeat": {
          "sequence": [
            {
              "action": "input_boolean.turn_on",
              "target": {
                "entity_id": "input_boolean.done"
              }
            }
          ],
          "until": [
            {
              "condition": "template",
              "value_template": "{{ is_state('input_boolean.done', 'on') }}"
            }
          ]
        }
      }
    ],
    "alias": "Repeat until done",
    "conditions": [],
    "id": "repeat_until_done",
    "triggers": [
      {
        "entity_id": "input_boolean.done",
        "to": "off",
        "trigger": "state"
      }
    ]
  }
}
```

### `repeat_for_each`

Golden case: `fixtures/dsl/repeat_for_each/`.

```python
"""Golden case: repeat_for_each(items) -> HA's `repeat.for_each` action."""

from hassle import automation, repeat_for_each, service, state, when


@automation(id="lights_repeat_for_each", alias="Lights repeat for_each")
def lights_repeat_for_each():
    when(state("input_text.entities").to("changed"))
    with repeat_for_each(["light.bedroom", "light.kitchen", "light.hallway"]):
        service("light.turn_on", target={"entity_id": "{{ repeat.item }}"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:lights_repeat_for_each": {
    "actions": [
      {
        "repeat": {
          "for_each": [
            "light.bedroom",
            "light.kitchen",
            "light.hallway"
          ],
          "sequence": [
            {
              "action": "light.turn_on",
              "target": {
                "entity_id": "{{ repeat.item }}"
              }
            }
          ]
        }
      }
    ],
    "alias": "Lights repeat for_each",
    "conditions": [],
    "id": "lights_repeat_for_each",
    "triggers": [
      {
        "entity_id": "input_text.entities",
        "to": "changed",
        "trigger": "state"
      }
    ]
  }
}
```

### `parallel`

Golden case: `fixtures/dsl/parallel_action/`.

```python
"""Golden case: parallel() -> HA's `parallel` action.

Matches fixtures/configs/automation_parallel_action.json's shape: each
top-level action recorded in the body becomes its own one-action `sequence`
branch.
"""

from hassle import automation, parallel, service, state, when


@automation(id="guest_parallel", alias="Guest parallel")
def guest_parallel():
    when(state("binary_sensor.guest_arrived").to("on"))
    with parallel():
        service("light.turn_on", target={"entity_id": "light.hallway"})
        service("light.turn_on", target={"entity_id": "light.living_room"})
        service("script.greet_guest")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:guest_parallel": {
    "actions": [
      {
        "parallel": [
          {
            "sequence": [
              {
                "action": "light.turn_on",
                "target": {
                  "entity_id": "light.hallway"
                }
              }
            ]
          },
          {
            "sequence": [
              {
                "action": "light.turn_on",
                "target": {
                  "entity_id": "light.living_room"
                }
              }
            ]
          },
          {
            "sequence": [
              {
                "action": "script.greet_guest"
              }
            ]
          }
        ]
      }
    ],
    "alias": "Guest parallel",
    "conditions": [],
    "id": "guest_parallel",
    "triggers": [
      {
        "entity_id": "binary_sensor.guest_arrived",
        "to": "on",
        "trigger": "state"
      }
    ]
  }
}
```

### `wait_for`

Golden case: `fixtures/dsl/wait_for_trigger/`.

```python
"""Golden case: wait_for(trigger, timeout=, continue_on_timeout=) -> `wait_for_trigger`."""

from hassle import automation, service, state, wait_for, when


@automation(id="wait_for_door", alias="Wait for trigger")
def wait_for_door():
    when(state("button.start").to("on"))
    wait_for(
        state("binary_sensor.door").to("off"),
        timeout="00:10:00",
        continue_on_timeout=True,
    )
    service("notify.mobile_app", message="Wait completed")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:wait_for_door": {
    "actions": [
      {
        "continue_on_timeout": true,
        "timeout": "00:10:00",
        "wait_for_trigger": [
          {
            "entity_id": "binary_sensor.door",
            "to": "off",
            "trigger": "state"
          }
        ]
      },
      {
        "action": "notify.mobile_app",
        "data": {
          "message": "Wait completed"
        }
      }
    ],
    "alias": "Wait for trigger",
    "conditions": [],
    "id": "wait_for_door",
    "triggers": [
      {
        "entity_id": "button.start",
        "to": "on",
        "trigger": "state"
      }
    ]
  }
}
```

### `wait_template`

Golden case: `fixtures/dsl/wait_template/`.

```python
"""Golden case: wait_template(tmpl, timeout=) -> HA's `wait_template` action."""

from hassle import automation, service, state, wait_template, when


@automation(id="wait_template_hallway", alias="Wait template")
def wait_template_hallway():
    when(state("binary_sensor.motion").to("on"))
    wait_template(
        "{{ state_attr('light.hallway', 'brightness') > 100 }}",
        timeout="00:05:00",
    )
    service("light.turn_off", target={"entity_id": "light.hallway"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:wait_template_hallway": {
    "actions": [
      {
        "timeout": "00:05:00",
        "wait_template": "{{ state_attr('light.hallway', 'brightness') > 100 }}"
      },
      {
        "action": "light.turn_off",
        "target": {
          "entity_id": "light.hallway"
        }
      }
    ],
    "alias": "Wait template",
    "conditions": [],
    "id": "wait_template_hallway",
    "triggers": [
      {
        "entity_id": "binary_sensor.motion",
        "to": "on",
        "trigger": "state"
      }
    ]
  }
}
```

### `raw_trigger`

Golden case: `fixtures/dsl/raw_passthrough/`.

```python
"""Golden case: raw_trigger/raw_condition/raw_action passthrough (DESIGN §5.8).

The raw action is authored in legacy `service:` form to prove the containing
object's whole-body `normalize_ha` pass rewrites it to `action:`, exactly as
HA itself would on storage (docs/internals/ha-api-notes.md §10.1) -- the raw builders
themselves do not touch the dict.
"""

from hassle import automation, raw_action, raw_condition, raw_trigger


@automation(id="weird_device_trigger", alias="Weird device trigger thing")
def weird_device_trigger():
    raw_trigger({"platform": "device", "device_id": "abc123", "type": "turned_on"})
    raw_condition({"condition": "device", "device_id": "abc123", "type": "is_on"})
    raw_action({"service": "light.turn_on", "entity_id": "light.hallway"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:weird_device_trigger": {
    "actions": [
      {
        "action": "light.turn_on",
        "entity_id": "light.hallway"
      }
    ],
    "alias": "Weird device trigger thing",
    "conditions": [
      {
        "condition": "device",
        "device_id": "abc123",
        "type": "is_on"
      }
    ],
    "id": "weird_device_trigger",
    "triggers": [
      {
        "device_id": "abc123",
        "platform": "device",
        "type": "turned_on"
      }
    ]
  }
}
```

### `raw_condition`

Golden case: `fixtures/dsl/raw_passthrough/`.

```python
"""Golden case: raw_trigger/raw_condition/raw_action passthrough (DESIGN §5.8).

The raw action is authored in legacy `service:` form to prove the containing
object's whole-body `normalize_ha` pass rewrites it to `action:`, exactly as
HA itself would on storage (docs/internals/ha-api-notes.md §10.1) -- the raw builders
themselves do not touch the dict.
"""

from hassle import automation, raw_action, raw_condition, raw_trigger


@automation(id="weird_device_trigger", alias="Weird device trigger thing")
def weird_device_trigger():
    raw_trigger({"platform": "device", "device_id": "abc123", "type": "turned_on"})
    raw_condition({"condition": "device", "device_id": "abc123", "type": "is_on"})
    raw_action({"service": "light.turn_on", "entity_id": "light.hallway"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:weird_device_trigger": {
    "actions": [
      {
        "action": "light.turn_on",
        "entity_id": "light.hallway"
      }
    ],
    "alias": "Weird device trigger thing",
    "conditions": [
      {
        "condition": "device",
        "device_id": "abc123",
        "type": "is_on"
      }
    ],
    "id": "weird_device_trigger",
    "triggers": [
      {
        "device_id": "abc123",
        "platform": "device",
        "type": "turned_on"
      }
    ]
  }
}
```

### `raw_action`

Golden case: `fixtures/dsl/raw_passthrough/`.

```python
"""Golden case: raw_trigger/raw_condition/raw_action passthrough (DESIGN §5.8).

The raw action is authored in legacy `service:` form to prove the containing
object's whole-body `normalize_ha` pass rewrites it to `action:`, exactly as
HA itself would on storage (docs/internals/ha-api-notes.md §10.1) -- the raw builders
themselves do not touch the dict.
"""

from hassle import automation, raw_action, raw_condition, raw_trigger


@automation(id="weird_device_trigger", alias="Weird device trigger thing")
def weird_device_trigger():
    raw_trigger({"platform": "device", "device_id": "abc123", "type": "turned_on"})
    raw_condition({"condition": "device", "device_id": "abc123", "type": "is_on"})
    raw_action({"service": "light.turn_on", "entity_id": "light.hallway"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "automation:weird_device_trigger": {
    "actions": [
      {
        "action": "light.turn_on",
        "entity_id": "light.hallway"
      }
    ],
    "alias": "Weird device trigger thing",
    "conditions": [
      {
        "condition": "device",
        "device_id": "abc123",
        "type": "is_on"
      }
    ],
    "id": "weird_device_trigger",
    "triggers": [
      {
        "device_id": "abc123",
        "platform": "device",
        "type": "turned_on"
      }
    ]
  }
}
```

### `dashboard`

Golden case: `fixtures/dsl/dashboard_minimal_sections/`.

```python
"""Golden case: the smallest useful dashboard -- one sections view, one section.

`type=` defaults to `"sections"` and is materialized EXPLICITLY into the stored
config (docs/internals/dashboards-design.md §5.2).
"""

from hassle import dashboard, raw_card, section, view


@dashboard(
    url_path="home-main",
    title="Home",
    icon="mdi:home",
    show_in_sidebar=True,
    require_admin=False,
)
def home_main():
    with view(title="Overview", path="overview"), section():
        raw_card({"type": "markdown", "content": "Welcome home."})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:home-main": {
    "config": {
      "views": [
        {
          "path": "overview",
          "sections": [
            {
              "cards": [
                {
                  "content": "Welcome home.",
                  "type": "markdown"
                }
              ],
              "type": "grid"
            }
          ],
          "title": "Overview",
          "type": "sections"
        }
      ]
    },
    "meta": {
      "icon": "mdi:home",
      "require_admin": false,
      "show_in_sidebar": true,
      "title": "Home",
      "url_path": "home-main"
    }
  }
}
```

See also: `fixtures/dsl/dashboard_compile_time_loop/`, `fixtures/dsl/dashboard_default/`, `fixtures/dsl/dashboard_two_in_one_module/`

### `raw_dashboard`

Golden case: `fixtures/dsl/dashboard_raw_dashboard/`.

```python
"""Golden case: `@raw_dashboard` -- the top rung of the raw ladder.

The decorated function returns either the whole §3.2 envelope (`meta` +
`config`) or just a config dict, in which case the decorator's own `url_path=`
supplies the registry metadata. A returned `meta` dict MUST carry `url_path`
(§3.4's identity-sentinel guard) -- otherwise the envelope would silently key
as the DEFAULT dashboard.
"""

from hassle import raw_dashboard


@raw_dashboard(url_path="strategy-one")
def strategy_one():
    return {
        "meta": {
            "url_path": "strategy-one",
            "title": "Strategy",
            "icon": "mdi:auto-fix",
            "show_in_sidebar": True,
        },
        "config": {"strategy": {"type": "original-states"}},
    }


@raw_dashboard(url_path="config-only")
def config_only():
    return {"views": [{"title": "Only a config", "cards": []}]}
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:config-only": {
    "config": {
      "views": [
        {
          "cards": [],
          "title": "Only a config"
        }
      ]
    },
    "meta": {
      "url_path": "config-only"
    }
  },
  "dashboard:strategy-one": {
    "config": {
      "strategy": {
        "type": "original-states"
      }
    },
    "meta": {
      "icon": "mdi:auto-fix",
      "show_in_sidebar": true,
      "title": "Strategy",
      "url_path": "strategy-one"
    }
  }
}
```

### `view`

Golden case: `fixtures/dsl/dashboard_minimal_sections/`.

```python
"""Golden case: the smallest useful dashboard -- one sections view, one section.

`type=` defaults to `"sections"` and is materialized EXPLICITLY into the stored
config (docs/internals/dashboards-design.md §5.2).
"""

from hassle import dashboard, raw_card, section, view


@dashboard(
    url_path="home-main",
    title="Home",
    icon="mdi:home",
    show_in_sidebar=True,
    require_admin=False,
)
def home_main():
    with view(title="Overview", path="overview"), section():
        raw_card({"type": "markdown", "content": "Welcome home."})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:home-main": {
    "config": {
      "views": [
        {
          "path": "overview",
          "sections": [
            {
              "cards": [
                {
                  "content": "Welcome home.",
                  "type": "markdown"
                }
              ],
              "type": "grid"
            }
          ],
          "title": "Overview",
          "type": "sections"
        }
      ]
    },
    "meta": {
      "icon": "mdi:home",
      "require_admin": false,
      "show_in_sidebar": true,
      "title": "Home",
      "url_path": "home-main"
    }
  }
}
```

See also: `fixtures/dsl/dashboard_masonry/`, `fixtures/dsl/dashboard_panel/`, `fixtures/dsl/dashboard_sidebar/`

### `section`

Golden case: `fixtures/dsl/dashboard_minimal_sections/`.

```python
"""Golden case: the smallest useful dashboard -- one sections view, one section.

`type=` defaults to `"sections"` and is materialized EXPLICITLY into the stored
config (docs/internals/dashboards-design.md §5.2).
"""

from hassle import dashboard, raw_card, section, view


@dashboard(
    url_path="home-main",
    title="Home",
    icon="mdi:home",
    show_in_sidebar=True,
    require_admin=False,
)
def home_main():
    with view(title="Overview", path="overview"), section():
        raw_card({"type": "markdown", "content": "Welcome home."})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:home-main": {
    "config": {
      "views": [
        {
          "path": "overview",
          "sections": [
            {
              "cards": [
                {
                  "content": "Welcome home.",
                  "type": "markdown"
                }
              ],
              "type": "grid"
            }
          ],
          "title": "Overview",
          "type": "sections"
        }
      ]
    },
    "meta": {
      "icon": "mdi:home",
      "require_admin": false,
      "show_in_sidebar": true,
      "title": "Home",
      "url_path": "home-main"
    }
  }
}
```

See also: `fixtures/dsl/dashboard_visibility/`

### `badge`

Golden case: `fixtures/dsl/dashboard_badges/`.

```python
"""Golden case: view badges, both shapes.

`badge(entity_or_dict, **options)` records into the enclosing view's `badges`
list: an entity id (or `e.`-ref) builds the modern object form, a plain dict
passes through verbatim for legacy/unknown badge shapes
(docs/internals/dashboards-design.md §5.2, §2.2 item 6).
"""

from hassle import badge, dashboard, raw_card, section, view


@dashboard(url_path="badge-wall", title="Badges")
def badge_wall():
    with view(title="Overview", path="overview"):
        badge("sensor.outside_temp", name="Outside")
        badge("binary_sensor.front_door", extra={"show_state": False})
        badge({"type": "custom:legacy-badge", "entity": "sensor.legacy"})
        with section():
            raw_card({"type": "markdown", "content": "Badges above."})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:badge-wall": {
    "config": {
      "views": [
        {
          "badges": [
            {
              "entity": "sensor.outside_temp",
              "name": "Outside",
              "type": "entity"
            },
            {
              "entity": "binary_sensor.front_door",
              "show_state": false,
              "type": "entity"
            },
            {
              "entity": "sensor.legacy",
              "type": "custom:legacy-badge"
            }
          ],
          "path": "overview",
          "sections": [
            {
              "cards": [
                {
                  "content": "Badges above.",
                  "type": "markdown"
                }
              ],
              "type": "grid"
            }
          ],
          "title": "Overview",
          "type": "sections"
        }
      ]
    },
    "meta": {
      "title": "Badges",
      "url_path": "badge-wall"
    }
  }
}
```

### `raw_card`

Golden case: `fixtures/dsl/dashboard_raw_ladder/`.

```python
"""Golden case: the structural raw ladder (I3).

Granular escape hatches at every level, mirroring `raw_trigger`/`raw_action`:
an unknown CARD stays a `raw_card` inside a modelled section; a section whose
own keys are unmodelled is a whole `raw_section`; a view Hassle does not model
at all (a strategy view) is a whole `raw_view`. Never raw a parent merely
because a child rawed (docs/internals/dashboards-design.md §5.5).
"""

from hassle import dashboard, raw_card, raw_section, raw_view, section, view


@dashboard(url_path="raw-ladder", title="Raw ladder")
def raw_ladder():
    # Level 1: a third-party card, inside a fully modelled view + section.
    with view(title="Cards", path="cards"), section():
        raw_card({"type": "custom:bubble-card", "card_type": "button"})
    # Level 2: a section whose own keys are unmodelled.
    with view(title="Sections", path="sections"):
        raw_section(
            {
                "type": "grid",
                "column_span": 2,
                "invented_section_key": ["kept"],
                "cards": [{"type": "markdown", "content": "raw section"}],
            }
        )
    # Level 3: a whole view Hassle does not model (a strategy view).
    raw_view({"strategy": {"type": "original-states"}, "title": "Auto"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:raw-ladder": {
    "config": {
      "views": [
        {
          "path": "cards",
          "sections": [
            {
              "cards": [
                {
                  "card_type": "button",
                  "type": "custom:bubble-card"
                }
              ],
              "type": "grid"
            }
          ],
          "title": "Cards",
          "type": "sections"
        },
        {
          "path": "sections",
          "sections": [
            {
              "cards": [
                {
                  "content": "raw section",
                  "type": "markdown"
                }
              ],
              "column_span": 2,
              "invented_section_key": [
                "kept"
              ],
              "type": "grid"
            }
          ],
          "title": "Sections",
          "type": "sections"
        },
        {
          "strategy": {
            "type": "original-states"
          },
          "title": "Auto"
        }
      ]
    },
    "meta": {
      "title": "Raw ladder",
      "url_path": "raw-ladder"
    }
  }
}
```

See also: `fixtures/dsl/dashboard_compile_time_loop/`

### `raw_section`

Golden case: `fixtures/dsl/dashboard_raw_ladder/`.

```python
"""Golden case: the structural raw ladder (I3).

Granular escape hatches at every level, mirroring `raw_trigger`/`raw_action`:
an unknown CARD stays a `raw_card` inside a modelled section; a section whose
own keys are unmodelled is a whole `raw_section`; a view Hassle does not model
at all (a strategy view) is a whole `raw_view`. Never raw a parent merely
because a child rawed (docs/internals/dashboards-design.md §5.5).
"""

from hassle import dashboard, raw_card, raw_section, raw_view, section, view


@dashboard(url_path="raw-ladder", title="Raw ladder")
def raw_ladder():
    # Level 1: a third-party card, inside a fully modelled view + section.
    with view(title="Cards", path="cards"), section():
        raw_card({"type": "custom:bubble-card", "card_type": "button"})
    # Level 2: a section whose own keys are unmodelled.
    with view(title="Sections", path="sections"):
        raw_section(
            {
                "type": "grid",
                "column_span": 2,
                "invented_section_key": ["kept"],
                "cards": [{"type": "markdown", "content": "raw section"}],
            }
        )
    # Level 3: a whole view Hassle does not model (a strategy view).
    raw_view({"strategy": {"type": "original-states"}, "title": "Auto"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:raw-ladder": {
    "config": {
      "views": [
        {
          "path": "cards",
          "sections": [
            {
              "cards": [
                {
                  "card_type": "button",
                  "type": "custom:bubble-card"
                }
              ],
              "type": "grid"
            }
          ],
          "title": "Cards",
          "type": "sections"
        },
        {
          "path": "sections",
          "sections": [
            {
              "cards": [
                {
                  "content": "raw section",
                  "type": "markdown"
                }
              ],
              "column_span": 2,
              "invented_section_key": [
                "kept"
              ],
              "type": "grid"
            }
          ],
          "title": "Sections",
          "type": "sections"
        },
        {
          "strategy": {
            "type": "original-states"
          },
          "title": "Auto"
        }
      ]
    },
    "meta": {
      "title": "Raw ladder",
      "url_path": "raw-ladder"
    }
  }
}
```

### `raw_view`

Golden case: `fixtures/dsl/dashboard_raw_ladder/`.

```python
"""Golden case: the structural raw ladder (I3).

Granular escape hatches at every level, mirroring `raw_trigger`/`raw_action`:
an unknown CARD stays a `raw_card` inside a modelled section; a section whose
own keys are unmodelled is a whole `raw_section`; a view Hassle does not model
at all (a strategy view) is a whole `raw_view`. Never raw a parent merely
because a child rawed (docs/internals/dashboards-design.md §5.5).
"""

from hassle import dashboard, raw_card, raw_section, raw_view, section, view


@dashboard(url_path="raw-ladder", title="Raw ladder")
def raw_ladder():
    # Level 1: a third-party card, inside a fully modelled view + section.
    with view(title="Cards", path="cards"), section():
        raw_card({"type": "custom:bubble-card", "card_type": "button"})
    # Level 2: a section whose own keys are unmodelled.
    with view(title="Sections", path="sections"):
        raw_section(
            {
                "type": "grid",
                "column_span": 2,
                "invented_section_key": ["kept"],
                "cards": [{"type": "markdown", "content": "raw section"}],
            }
        )
    # Level 3: a whole view Hassle does not model (a strategy view).
    raw_view({"strategy": {"type": "original-states"}, "title": "Auto"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:raw-ladder": {
    "config": {
      "views": [
        {
          "path": "cards",
          "sections": [
            {
              "cards": [
                {
                  "card_type": "button",
                  "type": "custom:bubble-card"
                }
              ],
              "type": "grid"
            }
          ],
          "title": "Cards",
          "type": "sections"
        },
        {
          "path": "sections",
          "sections": [
            {
              "cards": [
                {
                  "content": "raw section",
                  "type": "markdown"
                }
              ],
              "column_span": 2,
              "invented_section_key": [
                "kept"
              ],
              "type": "grid"
            }
          ],
          "title": "Sections",
          "type": "sections"
        },
        {
          "strategy": {
            "type": "original-states"
          },
          "title": "Auto"
        }
      ]
    },
    "meta": {
      "title": "Raw ladder",
      "url_path": "raw-ladder"
    }
  }
}
```

### `CompileTimeBranchError`

Raised when a Python `if`/`bool()` is used on a runtime state expression (DESIGN §5.5) -- Python control flow runs at *compile* time, so a native branch on a live entity state would be baked in wrong. Fix: use `with if_then(expr):` / `with else_then():` instead, which compile to HA's `if`/`choose` action.

### `ConditionArgumentTypeError`

Raised when a condition-accepting entry point (`only_if`, `if_then`, `else_if`, `choose().when_`, `repeat_while`, `repeat_until`, `any_of`/`all_of`/`not_`) receives a plain Python `bool` instead of a condition-builder object -- almost always the classic `==`/`!=`-on-a-plain-value mistake. Fix: build a real condition, e.g. `entity.state == "on"` or `state(entity_id).is_("on")`, and pass that instead.

### `DanglingTemplateHelperDeclarationError`

Raised when `template_number`/`template_sensor`/`template_binary_sensor`/`template_select` is called with no `state=` (the decorator-form signal) but is never applied as a decorator over a function -- the call builds and registers nothing, so without this check it would compile clean with the object silently absent. Fix: either add `state=...` to make it a direct call-form declaration, or apply the call as `@template_number(...)` (etc.) over a zero-arg function that `return`s the state expression.

### `ElseWithoutIfError`

`with else_then():`/`with else_if(...):` used where the immediately preceding action in the same list isn't an `if_then`/`choose`/`else_if` block. Fix: move it directly after the block it belongs to.

### `InOperatorTrapError`

Raised by `entity.state in [...]` (entity-first conditions). Python's `in` always calls `bool()` on each element comparison to decide membership -- no overload can intercept this, so the natural `in` spelling can never build a real condition. Fix: use `entity.state.in_([...])` instead, which builds a real `state` condition with list (OR) membership.

### `InclusiveNumericBoundError`

Raised by `entity.state >= v` / `entity.state <= v` (entity-first conditions). Home Assistant's `numeric_state` condition only supports EXCLUSIVE bounds (`above`/`below`) -- there is no inclusive form to map `>=`/`<=` onto, so compiling one would silently produce a condition that is wrong right at the boundary value. Fix: use the exclusive `>`/`<` operator instead (the exact boundary value is excluded), or pick a value safely past it.

### `NoParamContextError`

`param(name)` called outside an active `@shared_script` body. Fix: only call `param(...)` inside the decorated function; use `var(name)` for a runtime `variables:` reference instead.

### `OnlyIfBlockCoverageError`

Raised when `with only_if(...):` is used but an action is recorded outside the block (before or after). Automation-level conditions gate *every* action, so a partial block would be visually misleading. Fix: move all actions inside the `with only_if(...):` block, or use the bare `only_if(...)` call form.

### `PythonMathMisuseError`

Python's stdlib `math.*` (or a bare `float()`/`int()`) called on a runtime `TemplateExpr`. Fix: use the matching `hassle` math builder (`sin`/`cos`/`sqrt`/... ) instead of `math.sin`/etc. -- `math.pi` as a *plain* Python constant is not a trap, it just folds into a literal.

### `SharedScriptParamMisuseError`

Python control flow/numeric coercion (`if`/`bool()`/`range()`/`int()`/`float()`/`round()`/`math.trunc()`) used on a `@shared_script` signature parameter (every field-named parameter is bound to its runtime `param(name)` marker when the body runs, regardless of its declared default). Fix: for a runtime count/value, use a runtime construct HA itself supports, e.g. `with repeat_count(times):` (accepts the marker directly, honoring whatever the caller passes); for a genuinely compile-time value, it was never a real HA field -- use a module-level constant or a `@macro` argument instead.

### `TemplateHelperDecoratorBodyError`

Raised when a `@template_number`/`@template_sensor`/`@template_binary_sensor`/`@template_select` decorator is applied to a function that doesn't fit the decorator-form contract: it must take zero parameters and `return` a `TemplateExpr`/`str` -- no declared parameters, no recording-verb calls (`service`/`when`/`only_if`/...), no other return type. Fix: remove the parameters, return a template expression built from the `hassle.compiler.templates`/`hassle.compiler.math_expr` surface (or a plain Jinja string), and do nothing else in the function body.

### `UnknownFieldError`

A `@shared_script` call-site kwarg is not among the script's declared `fields=` keys (when `fields=` is given explicitly, it is the superset source of truth even if the signature would otherwise accept the kwarg). Fix: add the field to `fields=`, or correct the call-site kwarg's spelling.

### `UnknownParamError`

`param(name)` named a field absent from the `@shared_script`'s signature. Fix: add `name` as a parameter of the decorated function, or correct the spelling.

## Card reference (`hassle.cards`)

Dashboard card builders live in the dedicated `hassle.cards` namespace, not in
`hassle.__all__` (docs/internals/dashboards-design.md §5.1 — HA card type names
like `area`/`calendar`/`button` collide with the frozen top-level surface). Every
built-in card type Hassle models gets its own section below, sourced from the
same `fixtures/dsl/dashboard_cards_*` golden fixtures `hassle-dev goldens`
verifies — pattern-match on these exactly like the constructs above.


### `c.entities`

Golden case: `fixtures/dsl/dashboard_cards_display_entities/`.

```python
"""Golden case: `c.entities` -- mixed varargs rows (`EntityRef`, `str`, a `dict` divider row)."""

from hassle import cards as c
from hassle import dashboard, section, view
from hassle.registry import entities as e


@dashboard(url_path="display-entities", title="Entities")
def display_entities():
    with view(title="Overview"), section():
        c.entities(
            e.light.kitchen,
            "light.living_room",
            {"type": "divider"},
            {"entity": "climate.office", "tap_action": {"action": "more-info"}},
            title="All lights",
            state_color=True,
        )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:display-entities": {
    "config": {
      "views": [
        {
          "sections": [
            {
              "cards": [
                {
                  "entities": [
                    "light.kitchen",
                    "light.living_room",
                    {
                      "type": "divider"
                    },
                    {
                      "entity": "climate.office",
                      "tap_action": {
                        "action": "more-info"
                      }
                    }
                  ],
                  "state_color": true,
                  "title": "All lights",
                  "type": "entities"
                }
              ],
              "type": "grid"
            }
          ],
          "title": "Overview",
          "type": "sections"
        }
      ]
    },
    "meta": {
      "title": "Entities",
      "url_path": "display-entities"
    }
  }
}
```

### `c.glance`

Golden case: `fixtures/dsl/dashboard_cards_display_glance/`.

```python
"""Golden case: `c.glance` -- the same rows convention as `c.entities`."""

from hassle import cards as c
from hassle import dashboard, section, view
from hassle.registry import entities as e


@dashboard(url_path="display-glance", title="Glance")
def display_glance():
    with view(title="Overview"), section():
        c.glance(
            e.sensor.outside_temp,
            e.sensor.outside_humidity,
            title="Outside",
            columns=2,
            show_name=False,
        )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:display-glance": {
    "config": {
      "views": [
        {
          "sections": [
            {
              "cards": [
                {
                  "columns": 2,
                  "entities": [
                    "sensor.outside_temp",
                    "sensor.outside_humidity"
                  ],
                  "show_name": false,
                  "title": "Outside",
                  "type": "glance"
                }
              ],
              "type": "grid"
            }
          ],
          "title": "Overview",
          "type": "sections"
        }
      ]
    },
    "meta": {
      "title": "Glance",
      "url_path": "display-glance"
    }
  }
}
```

### `c.tile`

Golden case: `fixtures/dsl/dashboard_cards_display_tile/`.

```python
"""Golden case: `c.tile` -- `features=`, plus both `tap_action` forms (§5.3).

`tap_action=` is a typed kwarg that widens to a verbatim `dict` ("dict
passthrough"); `icon_tap_action` is a real tile-card option Hassle leaves
undeclared on purpose, so it reaches the stored card only through `extra=`
("extra passthrough") -- both mechanisms exercised on the same card.
"""

from hassle import cards as c
from hassle import dashboard, section, view
from hassle.registry import entities as e


@dashboard(url_path="display-tile", title="Tile")
def display_tile():
    with view(title="Overview"), section():
        c.tile(
            e.climate.living_room,
            color="blue",
            vertical=True,
            features=[{"type": "climate-hvac-modes"}],
            tap_action={"action": "more-info"},
            extra={"icon_tap_action": {"action": "toggle"}},
        )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:display-tile": {
    "config": {
      "views": [
        {
          "sections": [
            {
              "cards": [
                {
                  "color": "blue",
                  "entity": "climate.living_room",
                  "features": [
                    {
                      "type": "climate-hvac-modes"
                    }
                  ],
                  "icon_tap_action": {
                    "action": "toggle"
                  },
                  "tap_action": {
                    "action": "more-info"
                  },
                  "type": "tile",
                  "vertical": true
                }
              ],
              "type": "grid"
            }
          ],
          "title": "Overview",
          "type": "sections"
        }
      ]
    },
    "meta": {
      "title": "Tile",
      "url_path": "display-tile"
    }
  }
}
```

### `c.entity`

Golden case: `fixtures/dsl/dashboard_cards_display_entity/`.

```python
"""Golden case: `c.entity` -- `attribute=`, plus an action passthrough."""

from hassle import cards as c
from hassle import dashboard, section, view
from hassle.registry import entities as e


@dashboard(url_path="display-entity", title="Entity")
def display_entity():
    with view(title="Overview"), section():
        c.entity(
            e.sensor.outside_temp,
            attribute="battery_level",
            name="Battery",
            icon="mdi:battery",
            hold_action={"action": "more-info"},
        )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:display-entity": {
    "config": {
      "views": [
        {
          "sections": [
            {
              "cards": [
                {
                  "attribute": "battery_level",
                  "entity": "sensor.outside_temp",
                  "hold_action": {
                    "action": "more-info"
                  },
                  "icon": "mdi:battery",
                  "name": "Battery",
                  "type": "entity"
                }
              ],
              "type": "grid"
            }
          ],
          "title": "Overview",
          "type": "sections"
        }
      ]
    },
    "meta": {
      "title": "Entity",
      "url_path": "display-entity"
    }
  }
}
```

### `c.button`

Golden case: `fixtures/dsl/dashboard_cards_display_button/`.

```python
"""Golden case: `c.button` -- `tap_action=` (the modern `perform-action` spelling)."""

from hassle import cards as c
from hassle import dashboard, section, view
from hassle.registry import entities as e


@dashboard(url_path="display-button", title="Button")
def display_button():
    with view(title="Overview"), section():
        c.button(
            entity=e.script.movie_time,
            name="Movie time",
            icon="mdi:movie",
            tap_action={"action": "perform-action", "perform_action": "script.movie_time"},
        )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:display-button": {
    "config": {
      "views": [
        {
          "sections": [
            {
              "cards": [
                {
                  "entity": "script.movie_time",
                  "icon": "mdi:movie",
                  "name": "Movie time",
                  "tap_action": {
                    "action": "perform-action",
                    "perform_action": "script.movie_time"
                  },
                  "type": "button"
                }
              ],
              "type": "grid"
            }
          ],
          "title": "Overview",
          "type": "sections"
        }
      ]
    },
    "meta": {
      "title": "Button",
      "url_path": "display-button"
    }
  }
}
```

See also: `fixtures/dsl/dashboard_cards_display_extra_roundtrip/`

### `c.heading`

Golden case: `fixtures/dsl/dashboard_cards_display_heading/`.

```python
"""Golden case: `c.heading` -- `heading_style=`, `badges=` (bare entity + verbatim dict)."""

from hassle import cards as c
from hassle import dashboard, section, view
from hassle.registry import entities as e


@dashboard(url_path="display-heading", title="Heading")
def display_heading():
    with view(title="Overview"), section():
        c.heading(
            heading="Living room",
            heading_style="title",
            icon="mdi:sofa",
            badges=[e.sensor.outside_temp, {"type": "state-label", "entity": "light.hall"}],
        )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:display-heading": {
    "config": {
      "views": [
        {
          "sections": [
            {
              "cards": [
                {
                  "badges": [
                    {
                      "entity": "sensor.outside_temp",
                      "type": "entity"
                    },
                    {
                      "entity": "light.hall",
                      "type": "state-label"
                    }
                  ],
                  "heading": "Living room",
                  "heading_style": "title",
                  "icon": "mdi:sofa",
                  "type": "heading"
                }
              ],
              "type": "grid"
            }
          ],
          "title": "Overview",
          "type": "sections"
        }
      ]
    },
    "meta": {
      "title": "Heading",
      "url_path": "display-heading"
    }
  }
}
```

### `c.alarm_panel`

Golden case: `fixtures/dsl/dashboard_cards_domain/`.

```python
"""Golden case: DB3c's domain card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/domain.py`: `alarm_panel`,
`area` (an AREA id, not an entity id), `light`, `thermostat`, `humidifier`,
`media_control`, `plant_status`, `todo_list`, `shopping_list` (the legacy
alias -- stays `"shopping-list"`, never upgraded to `todo-list`), and
`weather_forecast`.
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-domain", title="Domain")
def cards_domain():
    with view(title="Domain", type="masonry"):
        c.alarm_panel(
            "alarm_control_panel.home",
            name="Home Alarm",
            states=["arm_home", "arm_away"],
        )
        c.area(
            "living_room",
            navigation_path="/lovelace/living-room",
            show_camera=True,
            display_type="compact",
            alert_classes=["motion", "smoke"],
            sensor_classes=["temperature", "humidity"],
        )
        c.light("light.living_room", name="Living Room", icon="mdi:ceiling-light")
        c.thermostat("climate.living_room", features=[{"type": "climate-hvac-mode-select"}])
        c.humidifier("humidifier.living_room", features=[{"type": "humidifier-toggle"}])
        c.media_control("media_player.living_room")
        c.plant_status("plant.tomato", name="Tomato")
        c.todo_list("todo.groceries", title="Groceries", display_order="alphabetical")
        c.shopping_list(title="Shopping", display_order="alphabetical")
        c.weather_forecast(
            "weather.home",
            show_current=True,
            show_forecast=True,
            forecast_type="daily",
            name="Weather",
        )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-domain": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "entity": "alarm_control_panel.home",
              "name": "Home Alarm",
              "states": [
                "arm_home",
                "arm_away"
              ],
              "type": "alarm-panel"
            },
            {
              "alert_classes": [
                "motion",
                "smoke"
              ],
              "area": "living_room",
              "display_type": "compact",
              "navigation_path": "/lovelace/living-room",
              "sensor_classes": [
                "temperature",
                "humidity"
              ],
              "show_camera": true,
              "type": "area"
            },
            {
              "entity": "light.living_room",
              "icon": "mdi:ceiling-light",
              "name": "Living Room",
              "type": "light"
            },
            {
              "entity": "climate.living_room",
              "features": [
                {
                  "type": "climate-hvac-mode-select"
                }
              ],
              "type": "thermostat"
            },
            {
              "entity": "humidifier.living_room",
              "features": [
                {
                  "type": "humidifier-toggle"
                }
              ],
              "type": "humidifier"
            },
            {
              "entity": "media_player.living_room",
              "type": "media-control"
            },
            {
              "entity": "plant.tomato",
              "name": "Tomato",
              "type": "plant-status"
            },
            {
              "display_order": "alphabetical",
              "entity": "todo.groceries",
              "title": "Groceries",
              "type": "todo-list"
            },
            {
              "display_order": "alphabetical",
              "title": "Shopping",
              "type": "shopping-list"
            },
            {
              "entity": "weather.home",
              "forecast_type": "daily",
              "name": "Weather",
              "show_current": true,
              "show_forecast": true,
              "type": "weather-forecast"
            }
          ],
          "title": "Domain",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Domain",
      "url_path": "cards-domain"
    }
  }
}
```

### `c.area`

Golden case: `fixtures/dsl/dashboard_cards_domain/`.

```python
"""Golden case: DB3c's domain card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/domain.py`: `alarm_panel`,
`area` (an AREA id, not an entity id), `light`, `thermostat`, `humidifier`,
`media_control`, `plant_status`, `todo_list`, `shopping_list` (the legacy
alias -- stays `"shopping-list"`, never upgraded to `todo-list`), and
`weather_forecast`.
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-domain", title="Domain")
def cards_domain():
    with view(title="Domain", type="masonry"):
        c.alarm_panel(
            "alarm_control_panel.home",
            name="Home Alarm",
            states=["arm_home", "arm_away"],
        )
        c.area(
            "living_room",
            navigation_path="/lovelace/living-room",
            show_camera=True,
            display_type="compact",
            alert_classes=["motion", "smoke"],
            sensor_classes=["temperature", "humidity"],
        )
        c.light("light.living_room", name="Living Room", icon="mdi:ceiling-light")
        c.thermostat("climate.living_room", features=[{"type": "climate-hvac-mode-select"}])
        c.humidifier("humidifier.living_room", features=[{"type": "humidifier-toggle"}])
        c.media_control("media_player.living_room")
        c.plant_status("plant.tomato", name="Tomato")
        c.todo_list("todo.groceries", title="Groceries", display_order="alphabetical")
        c.shopping_list(title="Shopping", display_order="alphabetical")
        c.weather_forecast(
            "weather.home",
            show_current=True,
            show_forecast=True,
            forecast_type="daily",
            name="Weather",
        )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-domain": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "entity": "alarm_control_panel.home",
              "name": "Home Alarm",
              "states": [
                "arm_home",
                "arm_away"
              ],
              "type": "alarm-panel"
            },
            {
              "alert_classes": [
                "motion",
                "smoke"
              ],
              "area": "living_room",
              "display_type": "compact",
              "navigation_path": "/lovelace/living-room",
              "sensor_classes": [
                "temperature",
                "humidity"
              ],
              "show_camera": true,
              "type": "area"
            },
            {
              "entity": "light.living_room",
              "icon": "mdi:ceiling-light",
              "name": "Living Room",
              "type": "light"
            },
            {
              "entity": "climate.living_room",
              "features": [
                {
                  "type": "climate-hvac-mode-select"
                }
              ],
              "type": "thermostat"
            },
            {
              "entity": "humidifier.living_room",
              "features": [
                {
                  "type": "humidifier-toggle"
                }
              ],
              "type": "humidifier"
            },
            {
              "entity": "media_player.living_room",
              "type": "media-control"
            },
            {
              "entity": "plant.tomato",
              "name": "Tomato",
              "type": "plant-status"
            },
            {
              "display_order": "alphabetical",
              "entity": "todo.groceries",
              "title": "Groceries",
              "type": "todo-list"
            },
            {
              "display_order": "alphabetical",
              "title": "Shopping",
              "type": "shopping-list"
            },
            {
              "entity": "weather.home",
              "forecast_type": "daily",
              "name": "Weather",
              "show_current": true,
              "show_forecast": true,
              "type": "weather-forecast"
            }
          ],
          "title": "Domain",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Domain",
      "url_path": "cards-domain"
    }
  }
}
```

### `c.light`

Golden case: `fixtures/dsl/dashboard_cards_domain/`.

```python
"""Golden case: DB3c's domain card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/domain.py`: `alarm_panel`,
`area` (an AREA id, not an entity id), `light`, `thermostat`, `humidifier`,
`media_control`, `plant_status`, `todo_list`, `shopping_list` (the legacy
alias -- stays `"shopping-list"`, never upgraded to `todo-list`), and
`weather_forecast`.
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-domain", title="Domain")
def cards_domain():
    with view(title="Domain", type="masonry"):
        c.alarm_panel(
            "alarm_control_panel.home",
            name="Home Alarm",
            states=["arm_home", "arm_away"],
        )
        c.area(
            "living_room",
            navigation_path="/lovelace/living-room",
            show_camera=True,
            display_type="compact",
            alert_classes=["motion", "smoke"],
            sensor_classes=["temperature", "humidity"],
        )
        c.light("light.living_room", name="Living Room", icon="mdi:ceiling-light")
        c.thermostat("climate.living_room", features=[{"type": "climate-hvac-mode-select"}])
        c.humidifier("humidifier.living_room", features=[{"type": "humidifier-toggle"}])
        c.media_control("media_player.living_room")
        c.plant_status("plant.tomato", name="Tomato")
        c.todo_list("todo.groceries", title="Groceries", display_order="alphabetical")
        c.shopping_list(title="Shopping", display_order="alphabetical")
        c.weather_forecast(
            "weather.home",
            show_current=True,
            show_forecast=True,
            forecast_type="daily",
            name="Weather",
        )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-domain": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "entity": "alarm_control_panel.home",
              "name": "Home Alarm",
              "states": [
                "arm_home",
                "arm_away"
              ],
              "type": "alarm-panel"
            },
            {
              "alert_classes": [
                "motion",
                "smoke"
              ],
              "area": "living_room",
              "display_type": "compact",
              "navigation_path": "/lovelace/living-room",
              "sensor_classes": [
                "temperature",
                "humidity"
              ],
              "show_camera": true,
              "type": "area"
            },
            {
              "entity": "light.living_room",
              "icon": "mdi:ceiling-light",
              "name": "Living Room",
              "type": "light"
            },
            {
              "entity": "climate.living_room",
              "features": [
                {
                  "type": "climate-hvac-mode-select"
                }
              ],
              "type": "thermostat"
            },
            {
              "entity": "humidifier.living_room",
              "features": [
                {
                  "type": "humidifier-toggle"
                }
              ],
              "type": "humidifier"
            },
            {
              "entity": "media_player.living_room",
              "type": "media-control"
            },
            {
              "entity": "plant.tomato",
              "name": "Tomato",
              "type": "plant-status"
            },
            {
              "display_order": "alphabetical",
              "entity": "todo.groceries",
              "title": "Groceries",
              "type": "todo-list"
            },
            {
              "display_order": "alphabetical",
              "title": "Shopping",
              "type": "shopping-list"
            },
            {
              "entity": "weather.home",
              "forecast_type": "daily",
              "name": "Weather",
              "show_current": true,
              "show_forecast": true,
              "type": "weather-forecast"
            }
          ],
          "title": "Domain",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Domain",
      "url_path": "cards-domain"
    }
  }
}
```

See also: `fixtures/dsl/dashboard_cards_domain_extra/`

### `c.thermostat`

Golden case: `fixtures/dsl/dashboard_cards_domain/`.

```python
"""Golden case: DB3c's domain card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/domain.py`: `alarm_panel`,
`area` (an AREA id, not an entity id), `light`, `thermostat`, `humidifier`,
`media_control`, `plant_status`, `todo_list`, `shopping_list` (the legacy
alias -- stays `"shopping-list"`, never upgraded to `todo-list`), and
`weather_forecast`.
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-domain", title="Domain")
def cards_domain():
    with view(title="Domain", type="masonry"):
        c.alarm_panel(
            "alarm_control_panel.home",
            name="Home Alarm",
            states=["arm_home", "arm_away"],
        )
        c.area(
            "living_room",
            navigation_path="/lovelace/living-room",
            show_camera=True,
            display_type="compact",
            alert_classes=["motion", "smoke"],
            sensor_classes=["temperature", "humidity"],
        )
        c.light("light.living_room", name="Living Room", icon="mdi:ceiling-light")
        c.thermostat("climate.living_room", features=[{"type": "climate-hvac-mode-select"}])
        c.humidifier("humidifier.living_room", features=[{"type": "humidifier-toggle"}])
        c.media_control("media_player.living_room")
        c.plant_status("plant.tomato", name="Tomato")
        c.todo_list("todo.groceries", title="Groceries", display_order="alphabetical")
        c.shopping_list(title="Shopping", display_order="alphabetical")
        c.weather_forecast(
            "weather.home",
            show_current=True,
            show_forecast=True,
            forecast_type="daily",
            name="Weather",
        )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-domain": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "entity": "alarm_control_panel.home",
              "name": "Home Alarm",
              "states": [
                "arm_home",
                "arm_away"
              ],
              "type": "alarm-panel"
            },
            {
              "alert_classes": [
                "motion",
                "smoke"
              ],
              "area": "living_room",
              "display_type": "compact",
              "navigation_path": "/lovelace/living-room",
              "sensor_classes": [
                "temperature",
                "humidity"
              ],
              "show_camera": true,
              "type": "area"
            },
            {
              "entity": "light.living_room",
              "icon": "mdi:ceiling-light",
              "name": "Living Room",
              "type": "light"
            },
            {
              "entity": "climate.living_room",
              "features": [
                {
                  "type": "climate-hvac-mode-select"
                }
              ],
              "type": "thermostat"
            },
            {
              "entity": "humidifier.living_room",
              "features": [
                {
                  "type": "humidifier-toggle"
                }
              ],
              "type": "humidifier"
            },
            {
              "entity": "media_player.living_room",
              "type": "media-control"
            },
            {
              "entity": "plant.tomato",
              "name": "Tomato",
              "type": "plant-status"
            },
            {
              "display_order": "alphabetical",
              "entity": "todo.groceries",
              "title": "Groceries",
              "type": "todo-list"
            },
            {
              "display_order": "alphabetical",
              "title": "Shopping",
              "type": "shopping-list"
            },
            {
              "entity": "weather.home",
              "forecast_type": "daily",
              "name": "Weather",
              "show_current": true,
              "show_forecast": true,
              "type": "weather-forecast"
            }
          ],
          "title": "Domain",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Domain",
      "url_path": "cards-domain"
    }
  }
}
```

See also: `fixtures/dsl/dashboard_compile_time_loop/`

### `c.humidifier`

Golden case: `fixtures/dsl/dashboard_cards_domain/`.

```python
"""Golden case: DB3c's domain card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/domain.py`: `alarm_panel`,
`area` (an AREA id, not an entity id), `light`, `thermostat`, `humidifier`,
`media_control`, `plant_status`, `todo_list`, `shopping_list` (the legacy
alias -- stays `"shopping-list"`, never upgraded to `todo-list`), and
`weather_forecast`.
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-domain", title="Domain")
def cards_domain():
    with view(title="Domain", type="masonry"):
        c.alarm_panel(
            "alarm_control_panel.home",
            name="Home Alarm",
            states=["arm_home", "arm_away"],
        )
        c.area(
            "living_room",
            navigation_path="/lovelace/living-room",
            show_camera=True,
            display_type="compact",
            alert_classes=["motion", "smoke"],
            sensor_classes=["temperature", "humidity"],
        )
        c.light("light.living_room", name="Living Room", icon="mdi:ceiling-light")
        c.thermostat("climate.living_room", features=[{"type": "climate-hvac-mode-select"}])
        c.humidifier("humidifier.living_room", features=[{"type": "humidifier-toggle"}])
        c.media_control("media_player.living_room")
        c.plant_status("plant.tomato", name="Tomato")
        c.todo_list("todo.groceries", title="Groceries", display_order="alphabetical")
        c.shopping_list(title="Shopping", display_order="alphabetical")
        c.weather_forecast(
            "weather.home",
            show_current=True,
            show_forecast=True,
            forecast_type="daily",
            name="Weather",
        )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-domain": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "entity": "alarm_control_panel.home",
              "name": "Home Alarm",
              "states": [
                "arm_home",
                "arm_away"
              ],
              "type": "alarm-panel"
            },
            {
              "alert_classes": [
                "motion",
                "smoke"
              ],
              "area": "living_room",
              "display_type": "compact",
              "navigation_path": "/lovelace/living-room",
              "sensor_classes": [
                "temperature",
                "humidity"
              ],
              "show_camera": true,
              "type": "area"
            },
            {
              "entity": "light.living_room",
              "icon": "mdi:ceiling-light",
              "name": "Living Room",
              "type": "light"
            },
            {
              "entity": "climate.living_room",
              "features": [
                {
                  "type": "climate-hvac-mode-select"
                }
              ],
              "type": "thermostat"
            },
            {
              "entity": "humidifier.living_room",
              "features": [
                {
                  "type": "humidifier-toggle"
                }
              ],
              "type": "humidifier"
            },
            {
              "entity": "media_player.living_room",
              "type": "media-control"
            },
            {
              "entity": "plant.tomato",
              "name": "Tomato",
              "type": "plant-status"
            },
            {
              "display_order": "alphabetical",
              "entity": "todo.groceries",
              "title": "Groceries",
              "type": "todo-list"
            },
            {
              "display_order": "alphabetical",
              "title": "Shopping",
              "type": "shopping-list"
            },
            {
              "entity": "weather.home",
              "forecast_type": "daily",
              "name": "Weather",
              "show_current": true,
              "show_forecast": true,
              "type": "weather-forecast"
            }
          ],
          "title": "Domain",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Domain",
      "url_path": "cards-domain"
    }
  }
}
```

### `c.media_control`

Golden case: `fixtures/dsl/dashboard_cards_domain/`.

```python
"""Golden case: DB3c's domain card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/domain.py`: `alarm_panel`,
`area` (an AREA id, not an entity id), `light`, `thermostat`, `humidifier`,
`media_control`, `plant_status`, `todo_list`, `shopping_list` (the legacy
alias -- stays `"shopping-list"`, never upgraded to `todo-list`), and
`weather_forecast`.
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-domain", title="Domain")
def cards_domain():
    with view(title="Domain", type="masonry"):
        c.alarm_panel(
            "alarm_control_panel.home",
            name="Home Alarm",
            states=["arm_home", "arm_away"],
        )
        c.area(
            "living_room",
            navigation_path="/lovelace/living-room",
            show_camera=True,
            display_type="compact",
            alert_classes=["motion", "smoke"],
            sensor_classes=["temperature", "humidity"],
        )
        c.light("light.living_room", name="Living Room", icon="mdi:ceiling-light")
        c.thermostat("climate.living_room", features=[{"type": "climate-hvac-mode-select"}])
        c.humidifier("humidifier.living_room", features=[{"type": "humidifier-toggle"}])
        c.media_control("media_player.living_room")
        c.plant_status("plant.tomato", name="Tomato")
        c.todo_list("todo.groceries", title="Groceries", display_order="alphabetical")
        c.shopping_list(title="Shopping", display_order="alphabetical")
        c.weather_forecast(
            "weather.home",
            show_current=True,
            show_forecast=True,
            forecast_type="daily",
            name="Weather",
        )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-domain": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "entity": "alarm_control_panel.home",
              "name": "Home Alarm",
              "states": [
                "arm_home",
                "arm_away"
              ],
              "type": "alarm-panel"
            },
            {
              "alert_classes": [
                "motion",
                "smoke"
              ],
              "area": "living_room",
              "display_type": "compact",
              "navigation_path": "/lovelace/living-room",
              "sensor_classes": [
                "temperature",
                "humidity"
              ],
              "show_camera": true,
              "type": "area"
            },
            {
              "entity": "light.living_room",
              "icon": "mdi:ceiling-light",
              "name": "Living Room",
              "type": "light"
            },
            {
              "entity": "climate.living_room",
              "features": [
                {
                  "type": "climate-hvac-mode-select"
                }
              ],
              "type": "thermostat"
            },
            {
              "entity": "humidifier.living_room",
              "features": [
                {
                  "type": "humidifier-toggle"
                }
              ],
              "type": "humidifier"
            },
            {
              "entity": "media_player.living_room",
              "type": "media-control"
            },
            {
              "entity": "plant.tomato",
              "name": "Tomato",
              "type": "plant-status"
            },
            {
              "display_order": "alphabetical",
              "entity": "todo.groceries",
              "title": "Groceries",
              "type": "todo-list"
            },
            {
              "display_order": "alphabetical",
              "title": "Shopping",
              "type": "shopping-list"
            },
            {
              "entity": "weather.home",
              "forecast_type": "daily",
              "name": "Weather",
              "show_current": true,
              "show_forecast": true,
              "type": "weather-forecast"
            }
          ],
          "title": "Domain",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Domain",
      "url_path": "cards-domain"
    }
  }
}
```

### `c.plant_status`

Golden case: `fixtures/dsl/dashboard_cards_domain/`.

```python
"""Golden case: DB3c's domain card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/domain.py`: `alarm_panel`,
`area` (an AREA id, not an entity id), `light`, `thermostat`, `humidifier`,
`media_control`, `plant_status`, `todo_list`, `shopping_list` (the legacy
alias -- stays `"shopping-list"`, never upgraded to `todo-list`), and
`weather_forecast`.
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-domain", title="Domain")
def cards_domain():
    with view(title="Domain", type="masonry"):
        c.alarm_panel(
            "alarm_control_panel.home",
            name="Home Alarm",
            states=["arm_home", "arm_away"],
        )
        c.area(
            "living_room",
            navigation_path="/lovelace/living-room",
            show_camera=True,
            display_type="compact",
            alert_classes=["motion", "smoke"],
            sensor_classes=["temperature", "humidity"],
        )
        c.light("light.living_room", name="Living Room", icon="mdi:ceiling-light")
        c.thermostat("climate.living_room", features=[{"type": "climate-hvac-mode-select"}])
        c.humidifier("humidifier.living_room", features=[{"type": "humidifier-toggle"}])
        c.media_control("media_player.living_room")
        c.plant_status("plant.tomato", name="Tomato")
        c.todo_list("todo.groceries", title="Groceries", display_order="alphabetical")
        c.shopping_list(title="Shopping", display_order="alphabetical")
        c.weather_forecast(
            "weather.home",
            show_current=True,
            show_forecast=True,
            forecast_type="daily",
            name="Weather",
        )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-domain": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "entity": "alarm_control_panel.home",
              "name": "Home Alarm",
              "states": [
                "arm_home",
                "arm_away"
              ],
              "type": "alarm-panel"
            },
            {
              "alert_classes": [
                "motion",
                "smoke"
              ],
              "area": "living_room",
              "display_type": "compact",
              "navigation_path": "/lovelace/living-room",
              "sensor_classes": [
                "temperature",
                "humidity"
              ],
              "show_camera": true,
              "type": "area"
            },
            {
              "entity": "light.living_room",
              "icon": "mdi:ceiling-light",
              "name": "Living Room",
              "type": "light"
            },
            {
              "entity": "climate.living_room",
              "features": [
                {
                  "type": "climate-hvac-mode-select"
                }
              ],
              "type": "thermostat"
            },
            {
              "entity": "humidifier.living_room",
              "features": [
                {
                  "type": "humidifier-toggle"
                }
              ],
              "type": "humidifier"
            },
            {
              "entity": "media_player.living_room",
              "type": "media-control"
            },
            {
              "entity": "plant.tomato",
              "name": "Tomato",
              "type": "plant-status"
            },
            {
              "display_order": "alphabetical",
              "entity": "todo.groceries",
              "title": "Groceries",
              "type": "todo-list"
            },
            {
              "display_order": "alphabetical",
              "title": "Shopping",
              "type": "shopping-list"
            },
            {
              "entity": "weather.home",
              "forecast_type": "daily",
              "name": "Weather",
              "show_current": true,
              "show_forecast": true,
              "type": "weather-forecast"
            }
          ],
          "title": "Domain",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Domain",
      "url_path": "cards-domain"
    }
  }
}
```

### `c.todo_list`

Golden case: `fixtures/dsl/dashboard_cards_domain/`.

```python
"""Golden case: DB3c's domain card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/domain.py`: `alarm_panel`,
`area` (an AREA id, not an entity id), `light`, `thermostat`, `humidifier`,
`media_control`, `plant_status`, `todo_list`, `shopping_list` (the legacy
alias -- stays `"shopping-list"`, never upgraded to `todo-list`), and
`weather_forecast`.
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-domain", title="Domain")
def cards_domain():
    with view(title="Domain", type="masonry"):
        c.alarm_panel(
            "alarm_control_panel.home",
            name="Home Alarm",
            states=["arm_home", "arm_away"],
        )
        c.area(
            "living_room",
            navigation_path="/lovelace/living-room",
            show_camera=True,
            display_type="compact",
            alert_classes=["motion", "smoke"],
            sensor_classes=["temperature", "humidity"],
        )
        c.light("light.living_room", name="Living Room", icon="mdi:ceiling-light")
        c.thermostat("climate.living_room", features=[{"type": "climate-hvac-mode-select"}])
        c.humidifier("humidifier.living_room", features=[{"type": "humidifier-toggle"}])
        c.media_control("media_player.living_room")
        c.plant_status("plant.tomato", name="Tomato")
        c.todo_list("todo.groceries", title="Groceries", display_order="alphabetical")
        c.shopping_list(title="Shopping", display_order="alphabetical")
        c.weather_forecast(
            "weather.home",
            show_current=True,
            show_forecast=True,
            forecast_type="daily",
            name="Weather",
        )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-domain": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "entity": "alarm_control_panel.home",
              "name": "Home Alarm",
              "states": [
                "arm_home",
                "arm_away"
              ],
              "type": "alarm-panel"
            },
            {
              "alert_classes": [
                "motion",
                "smoke"
              ],
              "area": "living_room",
              "display_type": "compact",
              "navigation_path": "/lovelace/living-room",
              "sensor_classes": [
                "temperature",
                "humidity"
              ],
              "show_camera": true,
              "type": "area"
            },
            {
              "entity": "light.living_room",
              "icon": "mdi:ceiling-light",
              "name": "Living Room",
              "type": "light"
            },
            {
              "entity": "climate.living_room",
              "features": [
                {
                  "type": "climate-hvac-mode-select"
                }
              ],
              "type": "thermostat"
            },
            {
              "entity": "humidifier.living_room",
              "features": [
                {
                  "type": "humidifier-toggle"
                }
              ],
              "type": "humidifier"
            },
            {
              "entity": "media_player.living_room",
              "type": "media-control"
            },
            {
              "entity": "plant.tomato",
              "name": "Tomato",
              "type": "plant-status"
            },
            {
              "display_order": "alphabetical",
              "entity": "todo.groceries",
              "title": "Groceries",
              "type": "todo-list"
            },
            {
              "display_order": "alphabetical",
              "title": "Shopping",
              "type": "shopping-list"
            },
            {
              "entity": "weather.home",
              "forecast_type": "daily",
              "name": "Weather",
              "show_current": true,
              "show_forecast": true,
              "type": "weather-forecast"
            }
          ],
          "title": "Domain",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Domain",
      "url_path": "cards-domain"
    }
  }
}
```

### `c.shopping_list`

Golden case: `fixtures/dsl/dashboard_cards_domain/`.

```python
"""Golden case: DB3c's domain card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/domain.py`: `alarm_panel`,
`area` (an AREA id, not an entity id), `light`, `thermostat`, `humidifier`,
`media_control`, `plant_status`, `todo_list`, `shopping_list` (the legacy
alias -- stays `"shopping-list"`, never upgraded to `todo-list`), and
`weather_forecast`.
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-domain", title="Domain")
def cards_domain():
    with view(title="Domain", type="masonry"):
        c.alarm_panel(
            "alarm_control_panel.home",
            name="Home Alarm",
            states=["arm_home", "arm_away"],
        )
        c.area(
            "living_room",
            navigation_path="/lovelace/living-room",
            show_camera=True,
            display_type="compact",
            alert_classes=["motion", "smoke"],
            sensor_classes=["temperature", "humidity"],
        )
        c.light("light.living_room", name="Living Room", icon="mdi:ceiling-light")
        c.thermostat("climate.living_room", features=[{"type": "climate-hvac-mode-select"}])
        c.humidifier("humidifier.living_room", features=[{"type": "humidifier-toggle"}])
        c.media_control("media_player.living_room")
        c.plant_status("plant.tomato", name="Tomato")
        c.todo_list("todo.groceries", title="Groceries", display_order="alphabetical")
        c.shopping_list(title="Shopping", display_order="alphabetical")
        c.weather_forecast(
            "weather.home",
            show_current=True,
            show_forecast=True,
            forecast_type="daily",
            name="Weather",
        )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-domain": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "entity": "alarm_control_panel.home",
              "name": "Home Alarm",
              "states": [
                "arm_home",
                "arm_away"
              ],
              "type": "alarm-panel"
            },
            {
              "alert_classes": [
                "motion",
                "smoke"
              ],
              "area": "living_room",
              "display_type": "compact",
              "navigation_path": "/lovelace/living-room",
              "sensor_classes": [
                "temperature",
                "humidity"
              ],
              "show_camera": true,
              "type": "area"
            },
            {
              "entity": "light.living_room",
              "icon": "mdi:ceiling-light",
              "name": "Living Room",
              "type": "light"
            },
            {
              "entity": "climate.living_room",
              "features": [
                {
                  "type": "climate-hvac-mode-select"
                }
              ],
              "type": "thermostat"
            },
            {
              "entity": "humidifier.living_room",
              "features": [
                {
                  "type": "humidifier-toggle"
                }
              ],
              "type": "humidifier"
            },
            {
              "entity": "media_player.living_room",
              "type": "media-control"
            },
            {
              "entity": "plant.tomato",
              "name": "Tomato",
              "type": "plant-status"
            },
            {
              "display_order": "alphabetical",
              "entity": "todo.groceries",
              "title": "Groceries",
              "type": "todo-list"
            },
            {
              "display_order": "alphabetical",
              "title": "Shopping",
              "type": "shopping-list"
            },
            {
              "entity": "weather.home",
              "forecast_type": "daily",
              "name": "Weather",
              "show_current": true,
              "show_forecast": true,
              "type": "weather-forecast"
            }
          ],
          "title": "Domain",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Domain",
      "url_path": "cards-domain"
    }
  }
}
```

### `c.weather_forecast`

Golden case: `fixtures/dsl/dashboard_cards_domain/`.

```python
"""Golden case: DB3c's domain card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/domain.py`: `alarm_panel`,
`area` (an AREA id, not an entity id), `light`, `thermostat`, `humidifier`,
`media_control`, `plant_status`, `todo_list`, `shopping_list` (the legacy
alias -- stays `"shopping-list"`, never upgraded to `todo-list`), and
`weather_forecast`.
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-domain", title="Domain")
def cards_domain():
    with view(title="Domain", type="masonry"):
        c.alarm_panel(
            "alarm_control_panel.home",
            name="Home Alarm",
            states=["arm_home", "arm_away"],
        )
        c.area(
            "living_room",
            navigation_path="/lovelace/living-room",
            show_camera=True,
            display_type="compact",
            alert_classes=["motion", "smoke"],
            sensor_classes=["temperature", "humidity"],
        )
        c.light("light.living_room", name="Living Room", icon="mdi:ceiling-light")
        c.thermostat("climate.living_room", features=[{"type": "climate-hvac-mode-select"}])
        c.humidifier("humidifier.living_room", features=[{"type": "humidifier-toggle"}])
        c.media_control("media_player.living_room")
        c.plant_status("plant.tomato", name="Tomato")
        c.todo_list("todo.groceries", title="Groceries", display_order="alphabetical")
        c.shopping_list(title="Shopping", display_order="alphabetical")
        c.weather_forecast(
            "weather.home",
            show_current=True,
            show_forecast=True,
            forecast_type="daily",
            name="Weather",
        )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-domain": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "entity": "alarm_control_panel.home",
              "name": "Home Alarm",
              "states": [
                "arm_home",
                "arm_away"
              ],
              "type": "alarm-panel"
            },
            {
              "alert_classes": [
                "motion",
                "smoke"
              ],
              "area": "living_room",
              "display_type": "compact",
              "navigation_path": "/lovelace/living-room",
              "sensor_classes": [
                "temperature",
                "humidity"
              ],
              "show_camera": true,
              "type": "area"
            },
            {
              "entity": "light.living_room",
              "icon": "mdi:ceiling-light",
              "name": "Living Room",
              "type": "light"
            },
            {
              "entity": "climate.living_room",
              "features": [
                {
                  "type": "climate-hvac-mode-select"
                }
              ],
              "type": "thermostat"
            },
            {
              "entity": "humidifier.living_room",
              "features": [
                {
                  "type": "humidifier-toggle"
                }
              ],
              "type": "humidifier"
            },
            {
              "entity": "media_player.living_room",
              "type": "media-control"
            },
            {
              "entity": "plant.tomato",
              "name": "Tomato",
              "type": "plant-status"
            },
            {
              "display_order": "alphabetical",
              "entity": "todo.groceries",
              "title": "Groceries",
              "type": "todo-list"
            },
            {
              "display_order": "alphabetical",
              "title": "Shopping",
              "type": "shopping-list"
            },
            {
              "entity": "weather.home",
              "forecast_type": "daily",
              "name": "Weather",
              "show_current": true,
              "show_forecast": true,
              "type": "weather-forecast"
            }
          ],
          "title": "Domain",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Domain",
      "url_path": "cards-domain"
    }
  }
}
```

### `c.energy_date_selection`

Golden case: `fixtures/dsl/dashboard_cards_energy/`.

```python
"""Golden case: DB3c's Energy dashboard card family (§2.3, §5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/energy.py` -- all 12
built-in Energy cards. Ten of them are plain `{type, collection_key?}` shapes;
`energy_distribution` also takes `link_dashboard=`, and `energy_sankey` also
takes `title=` (see that module's docstring for the DB0 note on the latter).
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-energy", title="Energy")
def cards_energy():
    with view(title="Energy", type="masonry"):
        c.energy_date_selection(collection_key="energy_secondary")
        c.energy_usage_graph(collection_key="energy_secondary")
        c.energy_solar_graph(collection_key="energy_secondary")
        c.energy_gas_graph(collection_key="energy_secondary")
        c.energy_water_graph(collection_key="energy_secondary")
        c.energy_distribution(collection_key="energy_secondary", link_dashboard=True)
        c.energy_sources_table(collection_key="energy_secondary")
        c.energy_grid_neutrality_gauge(collection_key="energy_secondary")
        c.energy_solar_consumed_gauge(collection_key="energy_secondary")
        c.energy_carbon_consumed_gauge(collection_key="energy_secondary")
        c.energy_self_sufficiency_gauge(collection_key="energy_secondary")
        c.energy_sankey(collection_key="energy_secondary", title="Flows")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-energy": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "collection_key": "energy_secondary",
              "type": "energy-date-selection"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-usage-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-gas-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-water-graph"
            },
            {
              "collection_key": "energy_secondary",
              "link_dashboard": true,
              "type": "energy-distribution"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-sources-table"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-grid-neutrality-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-carbon-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-self-sufficiency-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "title": "Flows",
              "type": "energy-sankey"
            }
          ],
          "title": "Energy",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Energy",
      "url_path": "cards-energy"
    }
  }
}
```

### `c.energy_usage_graph`

Golden case: `fixtures/dsl/dashboard_cards_energy/`.

```python
"""Golden case: DB3c's Energy dashboard card family (§2.3, §5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/energy.py` -- all 12
built-in Energy cards. Ten of them are plain `{type, collection_key?}` shapes;
`energy_distribution` also takes `link_dashboard=`, and `energy_sankey` also
takes `title=` (see that module's docstring for the DB0 note on the latter).
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-energy", title="Energy")
def cards_energy():
    with view(title="Energy", type="masonry"):
        c.energy_date_selection(collection_key="energy_secondary")
        c.energy_usage_graph(collection_key="energy_secondary")
        c.energy_solar_graph(collection_key="energy_secondary")
        c.energy_gas_graph(collection_key="energy_secondary")
        c.energy_water_graph(collection_key="energy_secondary")
        c.energy_distribution(collection_key="energy_secondary", link_dashboard=True)
        c.energy_sources_table(collection_key="energy_secondary")
        c.energy_grid_neutrality_gauge(collection_key="energy_secondary")
        c.energy_solar_consumed_gauge(collection_key="energy_secondary")
        c.energy_carbon_consumed_gauge(collection_key="energy_secondary")
        c.energy_self_sufficiency_gauge(collection_key="energy_secondary")
        c.energy_sankey(collection_key="energy_secondary", title="Flows")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-energy": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "collection_key": "energy_secondary",
              "type": "energy-date-selection"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-usage-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-gas-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-water-graph"
            },
            {
              "collection_key": "energy_secondary",
              "link_dashboard": true,
              "type": "energy-distribution"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-sources-table"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-grid-neutrality-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-carbon-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-self-sufficiency-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "title": "Flows",
              "type": "energy-sankey"
            }
          ],
          "title": "Energy",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Energy",
      "url_path": "cards-energy"
    }
  }
}
```

### `c.energy_solar_graph`

Golden case: `fixtures/dsl/dashboard_cards_energy/`.

```python
"""Golden case: DB3c's Energy dashboard card family (§2.3, §5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/energy.py` -- all 12
built-in Energy cards. Ten of them are plain `{type, collection_key?}` shapes;
`energy_distribution` also takes `link_dashboard=`, and `energy_sankey` also
takes `title=` (see that module's docstring for the DB0 note on the latter).
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-energy", title="Energy")
def cards_energy():
    with view(title="Energy", type="masonry"):
        c.energy_date_selection(collection_key="energy_secondary")
        c.energy_usage_graph(collection_key="energy_secondary")
        c.energy_solar_graph(collection_key="energy_secondary")
        c.energy_gas_graph(collection_key="energy_secondary")
        c.energy_water_graph(collection_key="energy_secondary")
        c.energy_distribution(collection_key="energy_secondary", link_dashboard=True)
        c.energy_sources_table(collection_key="energy_secondary")
        c.energy_grid_neutrality_gauge(collection_key="energy_secondary")
        c.energy_solar_consumed_gauge(collection_key="energy_secondary")
        c.energy_carbon_consumed_gauge(collection_key="energy_secondary")
        c.energy_self_sufficiency_gauge(collection_key="energy_secondary")
        c.energy_sankey(collection_key="energy_secondary", title="Flows")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-energy": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "collection_key": "energy_secondary",
              "type": "energy-date-selection"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-usage-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-gas-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-water-graph"
            },
            {
              "collection_key": "energy_secondary",
              "link_dashboard": true,
              "type": "energy-distribution"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-sources-table"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-grid-neutrality-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-carbon-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-self-sufficiency-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "title": "Flows",
              "type": "energy-sankey"
            }
          ],
          "title": "Energy",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Energy",
      "url_path": "cards-energy"
    }
  }
}
```

### `c.energy_gas_graph`

Golden case: `fixtures/dsl/dashboard_cards_energy/`.

```python
"""Golden case: DB3c's Energy dashboard card family (§2.3, §5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/energy.py` -- all 12
built-in Energy cards. Ten of them are plain `{type, collection_key?}` shapes;
`energy_distribution` also takes `link_dashboard=`, and `energy_sankey` also
takes `title=` (see that module's docstring for the DB0 note on the latter).
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-energy", title="Energy")
def cards_energy():
    with view(title="Energy", type="masonry"):
        c.energy_date_selection(collection_key="energy_secondary")
        c.energy_usage_graph(collection_key="energy_secondary")
        c.energy_solar_graph(collection_key="energy_secondary")
        c.energy_gas_graph(collection_key="energy_secondary")
        c.energy_water_graph(collection_key="energy_secondary")
        c.energy_distribution(collection_key="energy_secondary", link_dashboard=True)
        c.energy_sources_table(collection_key="energy_secondary")
        c.energy_grid_neutrality_gauge(collection_key="energy_secondary")
        c.energy_solar_consumed_gauge(collection_key="energy_secondary")
        c.energy_carbon_consumed_gauge(collection_key="energy_secondary")
        c.energy_self_sufficiency_gauge(collection_key="energy_secondary")
        c.energy_sankey(collection_key="energy_secondary", title="Flows")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-energy": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "collection_key": "energy_secondary",
              "type": "energy-date-selection"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-usage-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-gas-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-water-graph"
            },
            {
              "collection_key": "energy_secondary",
              "link_dashboard": true,
              "type": "energy-distribution"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-sources-table"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-grid-neutrality-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-carbon-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-self-sufficiency-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "title": "Flows",
              "type": "energy-sankey"
            }
          ],
          "title": "Energy",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Energy",
      "url_path": "cards-energy"
    }
  }
}
```

### `c.energy_water_graph`

Golden case: `fixtures/dsl/dashboard_cards_energy/`.

```python
"""Golden case: DB3c's Energy dashboard card family (§2.3, §5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/energy.py` -- all 12
built-in Energy cards. Ten of them are plain `{type, collection_key?}` shapes;
`energy_distribution` also takes `link_dashboard=`, and `energy_sankey` also
takes `title=` (see that module's docstring for the DB0 note on the latter).
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-energy", title="Energy")
def cards_energy():
    with view(title="Energy", type="masonry"):
        c.energy_date_selection(collection_key="energy_secondary")
        c.energy_usage_graph(collection_key="energy_secondary")
        c.energy_solar_graph(collection_key="energy_secondary")
        c.energy_gas_graph(collection_key="energy_secondary")
        c.energy_water_graph(collection_key="energy_secondary")
        c.energy_distribution(collection_key="energy_secondary", link_dashboard=True)
        c.energy_sources_table(collection_key="energy_secondary")
        c.energy_grid_neutrality_gauge(collection_key="energy_secondary")
        c.energy_solar_consumed_gauge(collection_key="energy_secondary")
        c.energy_carbon_consumed_gauge(collection_key="energy_secondary")
        c.energy_self_sufficiency_gauge(collection_key="energy_secondary")
        c.energy_sankey(collection_key="energy_secondary", title="Flows")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-energy": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "collection_key": "energy_secondary",
              "type": "energy-date-selection"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-usage-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-gas-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-water-graph"
            },
            {
              "collection_key": "energy_secondary",
              "link_dashboard": true,
              "type": "energy-distribution"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-sources-table"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-grid-neutrality-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-carbon-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-self-sufficiency-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "title": "Flows",
              "type": "energy-sankey"
            }
          ],
          "title": "Energy",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Energy",
      "url_path": "cards-energy"
    }
  }
}
```

### `c.energy_distribution`

Golden case: `fixtures/dsl/dashboard_cards_energy/`.

```python
"""Golden case: DB3c's Energy dashboard card family (§2.3, §5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/energy.py` -- all 12
built-in Energy cards. Ten of them are plain `{type, collection_key?}` shapes;
`energy_distribution` also takes `link_dashboard=`, and `energy_sankey` also
takes `title=` (see that module's docstring for the DB0 note on the latter).
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-energy", title="Energy")
def cards_energy():
    with view(title="Energy", type="masonry"):
        c.energy_date_selection(collection_key="energy_secondary")
        c.energy_usage_graph(collection_key="energy_secondary")
        c.energy_solar_graph(collection_key="energy_secondary")
        c.energy_gas_graph(collection_key="energy_secondary")
        c.energy_water_graph(collection_key="energy_secondary")
        c.energy_distribution(collection_key="energy_secondary", link_dashboard=True)
        c.energy_sources_table(collection_key="energy_secondary")
        c.energy_grid_neutrality_gauge(collection_key="energy_secondary")
        c.energy_solar_consumed_gauge(collection_key="energy_secondary")
        c.energy_carbon_consumed_gauge(collection_key="energy_secondary")
        c.energy_self_sufficiency_gauge(collection_key="energy_secondary")
        c.energy_sankey(collection_key="energy_secondary", title="Flows")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-energy": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "collection_key": "energy_secondary",
              "type": "energy-date-selection"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-usage-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-gas-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-water-graph"
            },
            {
              "collection_key": "energy_secondary",
              "link_dashboard": true,
              "type": "energy-distribution"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-sources-table"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-grid-neutrality-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-carbon-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-self-sufficiency-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "title": "Flows",
              "type": "energy-sankey"
            }
          ],
          "title": "Energy",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Energy",
      "url_path": "cards-energy"
    }
  }
}
```

### `c.energy_sources_table`

Golden case: `fixtures/dsl/dashboard_cards_energy/`.

```python
"""Golden case: DB3c's Energy dashboard card family (§2.3, §5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/energy.py` -- all 12
built-in Energy cards. Ten of them are plain `{type, collection_key?}` shapes;
`energy_distribution` also takes `link_dashboard=`, and `energy_sankey` also
takes `title=` (see that module's docstring for the DB0 note on the latter).
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-energy", title="Energy")
def cards_energy():
    with view(title="Energy", type="masonry"):
        c.energy_date_selection(collection_key="energy_secondary")
        c.energy_usage_graph(collection_key="energy_secondary")
        c.energy_solar_graph(collection_key="energy_secondary")
        c.energy_gas_graph(collection_key="energy_secondary")
        c.energy_water_graph(collection_key="energy_secondary")
        c.energy_distribution(collection_key="energy_secondary", link_dashboard=True)
        c.energy_sources_table(collection_key="energy_secondary")
        c.energy_grid_neutrality_gauge(collection_key="energy_secondary")
        c.energy_solar_consumed_gauge(collection_key="energy_secondary")
        c.energy_carbon_consumed_gauge(collection_key="energy_secondary")
        c.energy_self_sufficiency_gauge(collection_key="energy_secondary")
        c.energy_sankey(collection_key="energy_secondary", title="Flows")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-energy": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "collection_key": "energy_secondary",
              "type": "energy-date-selection"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-usage-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-gas-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-water-graph"
            },
            {
              "collection_key": "energy_secondary",
              "link_dashboard": true,
              "type": "energy-distribution"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-sources-table"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-grid-neutrality-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-carbon-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-self-sufficiency-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "title": "Flows",
              "type": "energy-sankey"
            }
          ],
          "title": "Energy",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Energy",
      "url_path": "cards-energy"
    }
  }
}
```

### `c.energy_grid_neutrality_gauge`

Golden case: `fixtures/dsl/dashboard_cards_energy/`.

```python
"""Golden case: DB3c's Energy dashboard card family (§2.3, §5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/energy.py` -- all 12
built-in Energy cards. Ten of them are plain `{type, collection_key?}` shapes;
`energy_distribution` also takes `link_dashboard=`, and `energy_sankey` also
takes `title=` (see that module's docstring for the DB0 note on the latter).
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-energy", title="Energy")
def cards_energy():
    with view(title="Energy", type="masonry"):
        c.energy_date_selection(collection_key="energy_secondary")
        c.energy_usage_graph(collection_key="energy_secondary")
        c.energy_solar_graph(collection_key="energy_secondary")
        c.energy_gas_graph(collection_key="energy_secondary")
        c.energy_water_graph(collection_key="energy_secondary")
        c.energy_distribution(collection_key="energy_secondary", link_dashboard=True)
        c.energy_sources_table(collection_key="energy_secondary")
        c.energy_grid_neutrality_gauge(collection_key="energy_secondary")
        c.energy_solar_consumed_gauge(collection_key="energy_secondary")
        c.energy_carbon_consumed_gauge(collection_key="energy_secondary")
        c.energy_self_sufficiency_gauge(collection_key="energy_secondary")
        c.energy_sankey(collection_key="energy_secondary", title="Flows")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-energy": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "collection_key": "energy_secondary",
              "type": "energy-date-selection"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-usage-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-gas-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-water-graph"
            },
            {
              "collection_key": "energy_secondary",
              "link_dashboard": true,
              "type": "energy-distribution"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-sources-table"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-grid-neutrality-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-carbon-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-self-sufficiency-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "title": "Flows",
              "type": "energy-sankey"
            }
          ],
          "title": "Energy",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Energy",
      "url_path": "cards-energy"
    }
  }
}
```

### `c.energy_solar_consumed_gauge`

Golden case: `fixtures/dsl/dashboard_cards_energy/`.

```python
"""Golden case: DB3c's Energy dashboard card family (§2.3, §5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/energy.py` -- all 12
built-in Energy cards. Ten of them are plain `{type, collection_key?}` shapes;
`energy_distribution` also takes `link_dashboard=`, and `energy_sankey` also
takes `title=` (see that module's docstring for the DB0 note on the latter).
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-energy", title="Energy")
def cards_energy():
    with view(title="Energy", type="masonry"):
        c.energy_date_selection(collection_key="energy_secondary")
        c.energy_usage_graph(collection_key="energy_secondary")
        c.energy_solar_graph(collection_key="energy_secondary")
        c.energy_gas_graph(collection_key="energy_secondary")
        c.energy_water_graph(collection_key="energy_secondary")
        c.energy_distribution(collection_key="energy_secondary", link_dashboard=True)
        c.energy_sources_table(collection_key="energy_secondary")
        c.energy_grid_neutrality_gauge(collection_key="energy_secondary")
        c.energy_solar_consumed_gauge(collection_key="energy_secondary")
        c.energy_carbon_consumed_gauge(collection_key="energy_secondary")
        c.energy_self_sufficiency_gauge(collection_key="energy_secondary")
        c.energy_sankey(collection_key="energy_secondary", title="Flows")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-energy": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "collection_key": "energy_secondary",
              "type": "energy-date-selection"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-usage-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-gas-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-water-graph"
            },
            {
              "collection_key": "energy_secondary",
              "link_dashboard": true,
              "type": "energy-distribution"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-sources-table"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-grid-neutrality-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-carbon-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-self-sufficiency-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "title": "Flows",
              "type": "energy-sankey"
            }
          ],
          "title": "Energy",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Energy",
      "url_path": "cards-energy"
    }
  }
}
```

### `c.energy_carbon_consumed_gauge`

Golden case: `fixtures/dsl/dashboard_cards_energy/`.

```python
"""Golden case: DB3c's Energy dashboard card family (§2.3, §5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/energy.py` -- all 12
built-in Energy cards. Ten of them are plain `{type, collection_key?}` shapes;
`energy_distribution` also takes `link_dashboard=`, and `energy_sankey` also
takes `title=` (see that module's docstring for the DB0 note on the latter).
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-energy", title="Energy")
def cards_energy():
    with view(title="Energy", type="masonry"):
        c.energy_date_selection(collection_key="energy_secondary")
        c.energy_usage_graph(collection_key="energy_secondary")
        c.energy_solar_graph(collection_key="energy_secondary")
        c.energy_gas_graph(collection_key="energy_secondary")
        c.energy_water_graph(collection_key="energy_secondary")
        c.energy_distribution(collection_key="energy_secondary", link_dashboard=True)
        c.energy_sources_table(collection_key="energy_secondary")
        c.energy_grid_neutrality_gauge(collection_key="energy_secondary")
        c.energy_solar_consumed_gauge(collection_key="energy_secondary")
        c.energy_carbon_consumed_gauge(collection_key="energy_secondary")
        c.energy_self_sufficiency_gauge(collection_key="energy_secondary")
        c.energy_sankey(collection_key="energy_secondary", title="Flows")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-energy": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "collection_key": "energy_secondary",
              "type": "energy-date-selection"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-usage-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-gas-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-water-graph"
            },
            {
              "collection_key": "energy_secondary",
              "link_dashboard": true,
              "type": "energy-distribution"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-sources-table"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-grid-neutrality-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-carbon-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-self-sufficiency-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "title": "Flows",
              "type": "energy-sankey"
            }
          ],
          "title": "Energy",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Energy",
      "url_path": "cards-energy"
    }
  }
}
```

### `c.energy_self_sufficiency_gauge`

Golden case: `fixtures/dsl/dashboard_cards_energy/`.

```python
"""Golden case: DB3c's Energy dashboard card family (§2.3, §5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/energy.py` -- all 12
built-in Energy cards. Ten of them are plain `{type, collection_key?}` shapes;
`energy_distribution` also takes `link_dashboard=`, and `energy_sankey` also
takes `title=` (see that module's docstring for the DB0 note on the latter).
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-energy", title="Energy")
def cards_energy():
    with view(title="Energy", type="masonry"):
        c.energy_date_selection(collection_key="energy_secondary")
        c.energy_usage_graph(collection_key="energy_secondary")
        c.energy_solar_graph(collection_key="energy_secondary")
        c.energy_gas_graph(collection_key="energy_secondary")
        c.energy_water_graph(collection_key="energy_secondary")
        c.energy_distribution(collection_key="energy_secondary", link_dashboard=True)
        c.energy_sources_table(collection_key="energy_secondary")
        c.energy_grid_neutrality_gauge(collection_key="energy_secondary")
        c.energy_solar_consumed_gauge(collection_key="energy_secondary")
        c.energy_carbon_consumed_gauge(collection_key="energy_secondary")
        c.energy_self_sufficiency_gauge(collection_key="energy_secondary")
        c.energy_sankey(collection_key="energy_secondary", title="Flows")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-energy": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "collection_key": "energy_secondary",
              "type": "energy-date-selection"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-usage-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-gas-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-water-graph"
            },
            {
              "collection_key": "energy_secondary",
              "link_dashboard": true,
              "type": "energy-distribution"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-sources-table"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-grid-neutrality-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-carbon-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-self-sufficiency-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "title": "Flows",
              "type": "energy-sankey"
            }
          ],
          "title": "Energy",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Energy",
      "url_path": "cards-energy"
    }
  }
}
```

### `c.energy_sankey`

Golden case: `fixtures/dsl/dashboard_cards_energy/`.

```python
"""Golden case: DB3c's Energy dashboard card family (§2.3, §5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/energy.py` -- all 12
built-in Energy cards. Ten of them are plain `{type, collection_key?}` shapes;
`energy_distribution` also takes `link_dashboard=`, and `energy_sankey` also
takes `title=` (see that module's docstring for the DB0 note on the latter).
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-energy", title="Energy")
def cards_energy():
    with view(title="Energy", type="masonry"):
        c.energy_date_selection(collection_key="energy_secondary")
        c.energy_usage_graph(collection_key="energy_secondary")
        c.energy_solar_graph(collection_key="energy_secondary")
        c.energy_gas_graph(collection_key="energy_secondary")
        c.energy_water_graph(collection_key="energy_secondary")
        c.energy_distribution(collection_key="energy_secondary", link_dashboard=True)
        c.energy_sources_table(collection_key="energy_secondary")
        c.energy_grid_neutrality_gauge(collection_key="energy_secondary")
        c.energy_solar_consumed_gauge(collection_key="energy_secondary")
        c.energy_carbon_consumed_gauge(collection_key="energy_secondary")
        c.energy_self_sufficiency_gauge(collection_key="energy_secondary")
        c.energy_sankey(collection_key="energy_secondary", title="Flows")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-energy": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "collection_key": "energy_secondary",
              "type": "energy-date-selection"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-usage-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-gas-graph"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-water-graph"
            },
            {
              "collection_key": "energy_secondary",
              "link_dashboard": true,
              "type": "energy-distribution"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-sources-table"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-grid-neutrality-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-solar-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-carbon-consumed-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "type": "energy-self-sufficiency-gauge"
            },
            {
              "collection_key": "energy_secondary",
              "title": "Flows",
              "type": "energy-sankey"
            }
          ],
          "title": "Energy",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Energy",
      "url_path": "cards-energy"
    }
  }
}
```

### `c.vertical_stack`

Golden case: `fixtures/dsl/dashboard_cards_layout_vertical_stack/`.

```python
"""Golden case: `c.vertical_stack` -- title, `extra=` round-trip, two children.

docs/internals/dashboards-design.md §5.3: every builder takes `extra=`
verbatim passthrough; `unknown_option` here is not a typed `vertical_stack`
kwarg, so it must survive the compile untouched.
"""

from hassle import cards as c
from hassle import dashboard, raw_card, section, view

CARD_A = {"type": "markdown", "content": "one"}
CARD_B = {"type": "markdown", "content": "two"}


@dashboard(url_path="layout-vertical-stack", title="Vertical stack")
def layout_vertical_stack():
    with (
        view(title="Overview"),
        section(),
        c.vertical_stack(title="Two cards", extra={"unknown_option": 7}),
    ):
        raw_card(CARD_A)
        raw_card(CARD_B)
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:layout-vertical-stack": {
    "config": {
      "views": [
        {
          "sections": [
            {
              "cards": [
                {
                  "cards": [
                    {
                      "content": "one",
                      "type": "markdown"
                    },
                    {
                      "content": "two",
                      "type": "markdown"
                    }
                  ],
                  "title": "Two cards",
                  "type": "vertical-stack",
                  "unknown_option": 7
                }
              ],
              "type": "grid"
            }
          ],
          "title": "Overview",
          "type": "sections"
        }
      ]
    },
    "meta": {
      "title": "Vertical stack",
      "url_path": "layout-vertical-stack"
    }
  }
}
```

### `c.horizontal_stack`

Golden case: `fixtures/dsl/dashboard_cards_layout_horizontal_stack/`.

```python
"""Golden case: `c.horizontal_stack` -- no `title` option (unlike `vertical_stack`)."""

from hassle import cards as c
from hassle import dashboard, raw_card, section, view


@dashboard(url_path="layout-horizontal-stack", title="Horizontal stack")
def layout_horizontal_stack():
    with view(title="Overview"), section(), c.horizontal_stack():
        raw_card({"type": "markdown", "content": "left"})
        raw_card({"type": "markdown", "content": "right"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:layout-horizontal-stack": {
    "config": {
      "views": [
        {
          "sections": [
            {
              "cards": [
                {
                  "cards": [
                    {
                      "content": "left",
                      "type": "markdown"
                    },
                    {
                      "content": "right",
                      "type": "markdown"
                    }
                  ],
                  "type": "horizontal-stack"
                }
              ],
              "type": "grid"
            }
          ],
          "title": "Overview",
          "type": "sections"
        }
      ]
    },
    "meta": {
      "title": "Horizontal stack",
      "url_path": "layout-horizontal-stack"
    }
  }
}
```

### `c.grid`

Golden case: `fixtures/dsl/dashboard_cards_layout_nested_stacks/`.

```python
"""Golden case: containers nest three deep -- vertical -> horizontal -> grid.

Also the `c.grid(columns=, square=)` golden usage: NOT the same construct as
`section()` even though both store `{"type": "grid", ...}` -- position
disambiguates (§6.1.1).
"""

from hassle import cards as c
from hassle import dashboard, raw_card, section, view


@dashboard(url_path="layout-nested-stacks", title="Nested stacks")
def layout_nested_stacks():
    with (
        view(title="Overview"),
        section(),
        c.vertical_stack(),
        c.horizontal_stack(),
        c.grid(columns=2, square=True),
    ):
        raw_card({"type": "markdown", "content": "deepest"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:layout-nested-stacks": {
    "config": {
      "views": [
        {
          "sections": [
            {
              "cards": [
                {
                  "cards": [
                    {
                      "cards": [
                        {
                          "cards": [
                            {
                              "content": "deepest",
                              "type": "markdown"
                            }
                          ],
                          "columns": 2,
                          "square": true,
                          "type": "grid"
                        }
                      ],
                      "type": "horizontal-stack"
                    }
                  ],
                  "type": "vertical-stack"
                }
              ],
              "type": "grid"
            }
          ],
          "title": "Overview",
          "type": "sections"
        }
      ]
    },
    "meta": {
      "title": "Nested stacks",
      "url_path": "layout-nested-stacks"
    }
  }
}
```

### `c.conditional`

Golden case: `fixtures/dsl/dashboard_cards_layout_conditional/`.

```python
"""Golden case: `c.conditional` -- exactly one child card behind its conditions."""

from hassle import cards as c
from hassle import dashboard, raw_card, section, view
from hassle.cards import cond


@dashboard(url_path="layout-conditional", title="Conditional")
def layout_conditional():
    with (
        view(title="Overview"),
        section(),
        c.conditional(cond.state("input_boolean.guest_mode", "on")),
    ):
        raw_card({"type": "markdown", "content": "Guest mode is on."})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:layout-conditional": {
    "config": {
      "views": [
        {
          "sections": [
            {
              "cards": [
                {
                  "card": {
                    "content": "Guest mode is on.",
                    "type": "markdown"
                  },
                  "conditions": [
                    {
                      "condition": "state",
                      "entity": "input_boolean.guest_mode",
                      "state": "on"
                    }
                  ],
                  "type": "conditional"
                }
              ],
              "type": "grid"
            }
          ],
          "title": "Overview",
          "type": "sections"
        }
      ]
    },
    "meta": {
      "title": "Conditional",
      "url_path": "layout-conditional"
    }
  }
}
```

### `c.entity_filter`

Golden case: `fixtures/dsl/dashboard_cards_layout_entity_filter_with_child/`.

```python
"""Golden case: `c.entity_filter` WITH its presentation card."""

from hassle import cards as c
from hassle import dashboard, raw_card, section, view
from hassle.registry import entities as e


@dashboard(url_path="layout-entity-filter-with-child", title="Entity filter (with card)")
def layout_entity_filter_with_child():
    with (
        view(title="Overview"),
        section(),
        c.entity_filter(entities=[e.light.kitchen, e.light.living_room], state_filter=["on"]),
    ):
        raw_card({"type": "glance"})
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:layout-entity-filter-with-child": {
    "config": {
      "views": [
        {
          "sections": [
            {
              "cards": [
                {
                  "card": {
                    "type": "glance"
                  },
                  "entities": [
                    "light.kitchen",
                    "light.living_room"
                  ],
                  "state_filter": [
                    "on"
                  ],
                  "type": "entity-filter"
                }
              ],
              "type": "grid"
            }
          ],
          "title": "Overview",
          "type": "sections"
        }
      ]
    },
    "meta": {
      "title": "Entity filter (with card)",
      "url_path": "layout-entity-filter-with-child"
    }
  }
}
```

See also: `fixtures/dsl/dashboard_cards_layout_entity_filter_without_child/`

### `c.gauge`

Golden case: `fixtures/dsl/dashboard_cards_visual/`.

```python
"""Golden case: DB3b's visual/history/text card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/visual.py`: `gauge`,
`history_graph`, `statistics_graph`, `sensor`, `statistic`, `markdown`
(including a Jinja template `content=`, passed through verbatim -- HA renders
it, Hassle never inspects it), `clock`, `calendar`, `logbook`.
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-visual", title="Visual & History")
def cards_visual():
    with view(title="Visual", type="masonry"):
        c.gauge(
            "sensor.cpu_temp",
            name="CPU Temp",
            unit="°C",
            min=0,
            max=100,
            needle=True,
            severity={"green": 0, "yellow": 60, "red": 85},
        )
        c.history_graph(
            "sensor.cpu_temp",
            "sensor.living_room_temp",
            {"entity": "sensor.attic_temp", "name": "Attic"},
            title="Temperatures",
            hours_to_show=48,
            show_names=True,
        )
        c.statistics_graph(
            "sensor.energy_usage",
            title="Energy",
            stat_types=["mean", "max"],
            period="hour",
            days_to_show=7,
        )
        c.sensor(
            "sensor.cpu_temp",
            name="CPU",
            graph="line",
            detail=2,
            hours_to_show=24,
            unit="°C",
        )
        c.statistic(
            "sensor.energy_usage",
            name="Energy this month",
            stat_type="sum",
            period={"calendar": {"period": "month"}},
        )
        c.markdown(
            "## Status\n\nCurrent temp: {{ states('sensor.cpu_temp') }}°C",
            title="Status",
        )
        c.clock(clock_style="analog", show_seconds=True, time_format="24")
        c.calendar(
            "calendar.family",
            "calendar.work",
            initial_view="listWeek",
            title="Schedule",
        )
        c.logbook("sensor.cpu_temp", hours_to_show=12, title="Recent activity")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-visual": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "entity": "sensor.cpu_temp",
              "max": 100,
              "min": 0,
              "name": "CPU Temp",
              "needle": true,
              "severity": {
                "green": 0,
                "red": 85,
                "yellow": 60
              },
              "type": "gauge",
              "unit": "°C"
            },
            {
              "entities": [
                "sensor.cpu_temp",
                "sensor.living_room_temp",
                {
                  "entity": "sensor.attic_temp",
                  "name": "Attic"
                }
              ],
              "hours_to_show": 48,
              "show_names": true,
              "title": "Temperatures",
              "type": "history-graph"
            },
            {
              "days_to_show": 7,
              "entities": [
                "sensor.energy_usage"
              ],
              "period": "hour",
              "stat_types": [
                "mean",
                "max"
              ],
              "title": "Energy",
              "type": "statistics-graph"
            },
            {
              "detail": 2,
              "entity": "sensor.cpu_temp",
              "graph": "line",
              "hours_to_show": 24,
              "name": "CPU",
              "type": "sensor",
              "unit": "°C"
            },
            {
              "entity": "sensor.energy_usage",
              "name": "Energy this month",
              "period": {
                "calendar": {
                  "period": "month"
                }
              },
              "stat_type": "sum",
              "type": "statistic"
            },
            {
              "content": "## Status\n\nCurrent temp: {{ states('sensor.cpu_temp') }}°C",
              "title": "Status",
              "type": "markdown"
            },
            {
              "clock_style": "analog",
              "show_seconds": true,
              "time_format": "24",
              "type": "clock"
            },
            {
              "entities": [
                "calendar.family",
                "calendar.work"
              ],
              "initial_view": "listWeek",
              "title": "Schedule",
              "type": "calendar"
            },
            {
              "entities": [
                "sensor.cpu_temp"
              ],
              "hours_to_show": 12,
              "title": "Recent activity",
              "type": "logbook"
            }
          ],
          "title": "Visual",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Visual & History",
      "url_path": "cards-visual"
    }
  }
}
```

See also: `fixtures/dsl/dashboard_cards_visual_extra/`

### `c.history_graph`

Golden case: `fixtures/dsl/dashboard_cards_visual/`.

```python
"""Golden case: DB3b's visual/history/text card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/visual.py`: `gauge`,
`history_graph`, `statistics_graph`, `sensor`, `statistic`, `markdown`
(including a Jinja template `content=`, passed through verbatim -- HA renders
it, Hassle never inspects it), `clock`, `calendar`, `logbook`.
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-visual", title="Visual & History")
def cards_visual():
    with view(title="Visual", type="masonry"):
        c.gauge(
            "sensor.cpu_temp",
            name="CPU Temp",
            unit="°C",
            min=0,
            max=100,
            needle=True,
            severity={"green": 0, "yellow": 60, "red": 85},
        )
        c.history_graph(
            "sensor.cpu_temp",
            "sensor.living_room_temp",
            {"entity": "sensor.attic_temp", "name": "Attic"},
            title="Temperatures",
            hours_to_show=48,
            show_names=True,
        )
        c.statistics_graph(
            "sensor.energy_usage",
            title="Energy",
            stat_types=["mean", "max"],
            period="hour",
            days_to_show=7,
        )
        c.sensor(
            "sensor.cpu_temp",
            name="CPU",
            graph="line",
            detail=2,
            hours_to_show=24,
            unit="°C",
        )
        c.statistic(
            "sensor.energy_usage",
            name="Energy this month",
            stat_type="sum",
            period={"calendar": {"period": "month"}},
        )
        c.markdown(
            "## Status\n\nCurrent temp: {{ states('sensor.cpu_temp') }}°C",
            title="Status",
        )
        c.clock(clock_style="analog", show_seconds=True, time_format="24")
        c.calendar(
            "calendar.family",
            "calendar.work",
            initial_view="listWeek",
            title="Schedule",
        )
        c.logbook("sensor.cpu_temp", hours_to_show=12, title="Recent activity")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-visual": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "entity": "sensor.cpu_temp",
              "max": 100,
              "min": 0,
              "name": "CPU Temp",
              "needle": true,
              "severity": {
                "green": 0,
                "red": 85,
                "yellow": 60
              },
              "type": "gauge",
              "unit": "°C"
            },
            {
              "entities": [
                "sensor.cpu_temp",
                "sensor.living_room_temp",
                {
                  "entity": "sensor.attic_temp",
                  "name": "Attic"
                }
              ],
              "hours_to_show": 48,
              "show_names": true,
              "title": "Temperatures",
              "type": "history-graph"
            },
            {
              "days_to_show": 7,
              "entities": [
                "sensor.energy_usage"
              ],
              "period": "hour",
              "stat_types": [
                "mean",
                "max"
              ],
              "title": "Energy",
              "type": "statistics-graph"
            },
            {
              "detail": 2,
              "entity": "sensor.cpu_temp",
              "graph": "line",
              "hours_to_show": 24,
              "name": "CPU",
              "type": "sensor",
              "unit": "°C"
            },
            {
              "entity": "sensor.energy_usage",
              "name": "Energy this month",
              "period": {
                "calendar": {
                  "period": "month"
                }
              },
              "stat_type": "sum",
              "type": "statistic"
            },
            {
              "content": "## Status\n\nCurrent temp: {{ states('sensor.cpu_temp') }}°C",
              "title": "Status",
              "type": "markdown"
            },
            {
              "clock_style": "analog",
              "show_seconds": true,
              "time_format": "24",
              "type": "clock"
            },
            {
              "entities": [
                "calendar.family",
                "calendar.work"
              ],
              "initial_view": "listWeek",
              "title": "Schedule",
              "type": "calendar"
            },
            {
              "entities": [
                "sensor.cpu_temp"
              ],
              "hours_to_show": 12,
              "title": "Recent activity",
              "type": "logbook"
            }
          ],
          "title": "Visual",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Visual & History",
      "url_path": "cards-visual"
    }
  }
}
```

### `c.statistics_graph`

Golden case: `fixtures/dsl/dashboard_cards_visual/`.

```python
"""Golden case: DB3b's visual/history/text card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/visual.py`: `gauge`,
`history_graph`, `statistics_graph`, `sensor`, `statistic`, `markdown`
(including a Jinja template `content=`, passed through verbatim -- HA renders
it, Hassle never inspects it), `clock`, `calendar`, `logbook`.
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-visual", title="Visual & History")
def cards_visual():
    with view(title="Visual", type="masonry"):
        c.gauge(
            "sensor.cpu_temp",
            name="CPU Temp",
            unit="°C",
            min=0,
            max=100,
            needle=True,
            severity={"green": 0, "yellow": 60, "red": 85},
        )
        c.history_graph(
            "sensor.cpu_temp",
            "sensor.living_room_temp",
            {"entity": "sensor.attic_temp", "name": "Attic"},
            title="Temperatures",
            hours_to_show=48,
            show_names=True,
        )
        c.statistics_graph(
            "sensor.energy_usage",
            title="Energy",
            stat_types=["mean", "max"],
            period="hour",
            days_to_show=7,
        )
        c.sensor(
            "sensor.cpu_temp",
            name="CPU",
            graph="line",
            detail=2,
            hours_to_show=24,
            unit="°C",
        )
        c.statistic(
            "sensor.energy_usage",
            name="Energy this month",
            stat_type="sum",
            period={"calendar": {"period": "month"}},
        )
        c.markdown(
            "## Status\n\nCurrent temp: {{ states('sensor.cpu_temp') }}°C",
            title="Status",
        )
        c.clock(clock_style="analog", show_seconds=True, time_format="24")
        c.calendar(
            "calendar.family",
            "calendar.work",
            initial_view="listWeek",
            title="Schedule",
        )
        c.logbook("sensor.cpu_temp", hours_to_show=12, title="Recent activity")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-visual": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "entity": "sensor.cpu_temp",
              "max": 100,
              "min": 0,
              "name": "CPU Temp",
              "needle": true,
              "severity": {
                "green": 0,
                "red": 85,
                "yellow": 60
              },
              "type": "gauge",
              "unit": "°C"
            },
            {
              "entities": [
                "sensor.cpu_temp",
                "sensor.living_room_temp",
                {
                  "entity": "sensor.attic_temp",
                  "name": "Attic"
                }
              ],
              "hours_to_show": 48,
              "show_names": true,
              "title": "Temperatures",
              "type": "history-graph"
            },
            {
              "days_to_show": 7,
              "entities": [
                "sensor.energy_usage"
              ],
              "period": "hour",
              "stat_types": [
                "mean",
                "max"
              ],
              "title": "Energy",
              "type": "statistics-graph"
            },
            {
              "detail": 2,
              "entity": "sensor.cpu_temp",
              "graph": "line",
              "hours_to_show": 24,
              "name": "CPU",
              "type": "sensor",
              "unit": "°C"
            },
            {
              "entity": "sensor.energy_usage",
              "name": "Energy this month",
              "period": {
                "calendar": {
                  "period": "month"
                }
              },
              "stat_type": "sum",
              "type": "statistic"
            },
            {
              "content": "## Status\n\nCurrent temp: {{ states('sensor.cpu_temp') }}°C",
              "title": "Status",
              "type": "markdown"
            },
            {
              "clock_style": "analog",
              "show_seconds": true,
              "time_format": "24",
              "type": "clock"
            },
            {
              "entities": [
                "calendar.family",
                "calendar.work"
              ],
              "initial_view": "listWeek",
              "title": "Schedule",
              "type": "calendar"
            },
            {
              "entities": [
                "sensor.cpu_temp"
              ],
              "hours_to_show": 12,
              "title": "Recent activity",
              "type": "logbook"
            }
          ],
          "title": "Visual",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Visual & History",
      "url_path": "cards-visual"
    }
  }
}
```

### `c.sensor`

Golden case: `fixtures/dsl/dashboard_cards_visual/`.

```python
"""Golden case: DB3b's visual/history/text card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/visual.py`: `gauge`,
`history_graph`, `statistics_graph`, `sensor`, `statistic`, `markdown`
(including a Jinja template `content=`, passed through verbatim -- HA renders
it, Hassle never inspects it), `clock`, `calendar`, `logbook`.
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-visual", title="Visual & History")
def cards_visual():
    with view(title="Visual", type="masonry"):
        c.gauge(
            "sensor.cpu_temp",
            name="CPU Temp",
            unit="°C",
            min=0,
            max=100,
            needle=True,
            severity={"green": 0, "yellow": 60, "red": 85},
        )
        c.history_graph(
            "sensor.cpu_temp",
            "sensor.living_room_temp",
            {"entity": "sensor.attic_temp", "name": "Attic"},
            title="Temperatures",
            hours_to_show=48,
            show_names=True,
        )
        c.statistics_graph(
            "sensor.energy_usage",
            title="Energy",
            stat_types=["mean", "max"],
            period="hour",
            days_to_show=7,
        )
        c.sensor(
            "sensor.cpu_temp",
            name="CPU",
            graph="line",
            detail=2,
            hours_to_show=24,
            unit="°C",
        )
        c.statistic(
            "sensor.energy_usage",
            name="Energy this month",
            stat_type="sum",
            period={"calendar": {"period": "month"}},
        )
        c.markdown(
            "## Status\n\nCurrent temp: {{ states('sensor.cpu_temp') }}°C",
            title="Status",
        )
        c.clock(clock_style="analog", show_seconds=True, time_format="24")
        c.calendar(
            "calendar.family",
            "calendar.work",
            initial_view="listWeek",
            title="Schedule",
        )
        c.logbook("sensor.cpu_temp", hours_to_show=12, title="Recent activity")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-visual": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "entity": "sensor.cpu_temp",
              "max": 100,
              "min": 0,
              "name": "CPU Temp",
              "needle": true,
              "severity": {
                "green": 0,
                "red": 85,
                "yellow": 60
              },
              "type": "gauge",
              "unit": "°C"
            },
            {
              "entities": [
                "sensor.cpu_temp",
                "sensor.living_room_temp",
                {
                  "entity": "sensor.attic_temp",
                  "name": "Attic"
                }
              ],
              "hours_to_show": 48,
              "show_names": true,
              "title": "Temperatures",
              "type": "history-graph"
            },
            {
              "days_to_show": 7,
              "entities": [
                "sensor.energy_usage"
              ],
              "period": "hour",
              "stat_types": [
                "mean",
                "max"
              ],
              "title": "Energy",
              "type": "statistics-graph"
            },
            {
              "detail": 2,
              "entity": "sensor.cpu_temp",
              "graph": "line",
              "hours_to_show": 24,
              "name": "CPU",
              "type": "sensor",
              "unit": "°C"
            },
            {
              "entity": "sensor.energy_usage",
              "name": "Energy this month",
              "period": {
                "calendar": {
                  "period": "month"
                }
              },
              "stat_type": "sum",
              "type": "statistic"
            },
            {
              "content": "## Status\n\nCurrent temp: {{ states('sensor.cpu_temp') }}°C",
              "title": "Status",
              "type": "markdown"
            },
            {
              "clock_style": "analog",
              "show_seconds": true,
              "time_format": "24",
              "type": "clock"
            },
            {
              "entities": [
                "calendar.family",
                "calendar.work"
              ],
              "initial_view": "listWeek",
              "title": "Schedule",
              "type": "calendar"
            },
            {
              "entities": [
                "sensor.cpu_temp"
              ],
              "hours_to_show": 12,
              "title": "Recent activity",
              "type": "logbook"
            }
          ],
          "title": "Visual",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Visual & History",
      "url_path": "cards-visual"
    }
  }
}
```

### `c.statistic`

Golden case: `fixtures/dsl/dashboard_cards_visual/`.

```python
"""Golden case: DB3b's visual/history/text card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/visual.py`: `gauge`,
`history_graph`, `statistics_graph`, `sensor`, `statistic`, `markdown`
(including a Jinja template `content=`, passed through verbatim -- HA renders
it, Hassle never inspects it), `clock`, `calendar`, `logbook`.
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-visual", title="Visual & History")
def cards_visual():
    with view(title="Visual", type="masonry"):
        c.gauge(
            "sensor.cpu_temp",
            name="CPU Temp",
            unit="°C",
            min=0,
            max=100,
            needle=True,
            severity={"green": 0, "yellow": 60, "red": 85},
        )
        c.history_graph(
            "sensor.cpu_temp",
            "sensor.living_room_temp",
            {"entity": "sensor.attic_temp", "name": "Attic"},
            title="Temperatures",
            hours_to_show=48,
            show_names=True,
        )
        c.statistics_graph(
            "sensor.energy_usage",
            title="Energy",
            stat_types=["mean", "max"],
            period="hour",
            days_to_show=7,
        )
        c.sensor(
            "sensor.cpu_temp",
            name="CPU",
            graph="line",
            detail=2,
            hours_to_show=24,
            unit="°C",
        )
        c.statistic(
            "sensor.energy_usage",
            name="Energy this month",
            stat_type="sum",
            period={"calendar": {"period": "month"}},
        )
        c.markdown(
            "## Status\n\nCurrent temp: {{ states('sensor.cpu_temp') }}°C",
            title="Status",
        )
        c.clock(clock_style="analog", show_seconds=True, time_format="24")
        c.calendar(
            "calendar.family",
            "calendar.work",
            initial_view="listWeek",
            title="Schedule",
        )
        c.logbook("sensor.cpu_temp", hours_to_show=12, title="Recent activity")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-visual": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "entity": "sensor.cpu_temp",
              "max": 100,
              "min": 0,
              "name": "CPU Temp",
              "needle": true,
              "severity": {
                "green": 0,
                "red": 85,
                "yellow": 60
              },
              "type": "gauge",
              "unit": "°C"
            },
            {
              "entities": [
                "sensor.cpu_temp",
                "sensor.living_room_temp",
                {
                  "entity": "sensor.attic_temp",
                  "name": "Attic"
                }
              ],
              "hours_to_show": 48,
              "show_names": true,
              "title": "Temperatures",
              "type": "history-graph"
            },
            {
              "days_to_show": 7,
              "entities": [
                "sensor.energy_usage"
              ],
              "period": "hour",
              "stat_types": [
                "mean",
                "max"
              ],
              "title": "Energy",
              "type": "statistics-graph"
            },
            {
              "detail": 2,
              "entity": "sensor.cpu_temp",
              "graph": "line",
              "hours_to_show": 24,
              "name": "CPU",
              "type": "sensor",
              "unit": "°C"
            },
            {
              "entity": "sensor.energy_usage",
              "name": "Energy this month",
              "period": {
                "calendar": {
                  "period": "month"
                }
              },
              "stat_type": "sum",
              "type": "statistic"
            },
            {
              "content": "## Status\n\nCurrent temp: {{ states('sensor.cpu_temp') }}°C",
              "title": "Status",
              "type": "markdown"
            },
            {
              "clock_style": "analog",
              "show_seconds": true,
              "time_format": "24",
              "type": "clock"
            },
            {
              "entities": [
                "calendar.family",
                "calendar.work"
              ],
              "initial_view": "listWeek",
              "title": "Schedule",
              "type": "calendar"
            },
            {
              "entities": [
                "sensor.cpu_temp"
              ],
              "hours_to_show": 12,
              "title": "Recent activity",
              "type": "logbook"
            }
          ],
          "title": "Visual",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Visual & History",
      "url_path": "cards-visual"
    }
  }
}
```

### `c.markdown`

Golden case: `fixtures/dsl/dashboard_cards_visual/`.

```python
"""Golden case: DB3b's visual/history/text card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/visual.py`: `gauge`,
`history_graph`, `statistics_graph`, `sensor`, `statistic`, `markdown`
(including a Jinja template `content=`, passed through verbatim -- HA renders
it, Hassle never inspects it), `clock`, `calendar`, `logbook`.
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-visual", title="Visual & History")
def cards_visual():
    with view(title="Visual", type="masonry"):
        c.gauge(
            "sensor.cpu_temp",
            name="CPU Temp",
            unit="°C",
            min=0,
            max=100,
            needle=True,
            severity={"green": 0, "yellow": 60, "red": 85},
        )
        c.history_graph(
            "sensor.cpu_temp",
            "sensor.living_room_temp",
            {"entity": "sensor.attic_temp", "name": "Attic"},
            title="Temperatures",
            hours_to_show=48,
            show_names=True,
        )
        c.statistics_graph(
            "sensor.energy_usage",
            title="Energy",
            stat_types=["mean", "max"],
            period="hour",
            days_to_show=7,
        )
        c.sensor(
            "sensor.cpu_temp",
            name="CPU",
            graph="line",
            detail=2,
            hours_to_show=24,
            unit="°C",
        )
        c.statistic(
            "sensor.energy_usage",
            name="Energy this month",
            stat_type="sum",
            period={"calendar": {"period": "month"}},
        )
        c.markdown(
            "## Status\n\nCurrent temp: {{ states('sensor.cpu_temp') }}°C",
            title="Status",
        )
        c.clock(clock_style="analog", show_seconds=True, time_format="24")
        c.calendar(
            "calendar.family",
            "calendar.work",
            initial_view="listWeek",
            title="Schedule",
        )
        c.logbook("sensor.cpu_temp", hours_to_show=12, title="Recent activity")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-visual": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "entity": "sensor.cpu_temp",
              "max": 100,
              "min": 0,
              "name": "CPU Temp",
              "needle": true,
              "severity": {
                "green": 0,
                "red": 85,
                "yellow": 60
              },
              "type": "gauge",
              "unit": "°C"
            },
            {
              "entities": [
                "sensor.cpu_temp",
                "sensor.living_room_temp",
                {
                  "entity": "sensor.attic_temp",
                  "name": "Attic"
                }
              ],
              "hours_to_show": 48,
              "show_names": true,
              "title": "Temperatures",
              "type": "history-graph"
            },
            {
              "days_to_show": 7,
              "entities": [
                "sensor.energy_usage"
              ],
              "period": "hour",
              "stat_types": [
                "mean",
                "max"
              ],
              "title": "Energy",
              "type": "statistics-graph"
            },
            {
              "detail": 2,
              "entity": "sensor.cpu_temp",
              "graph": "line",
              "hours_to_show": 24,
              "name": "CPU",
              "type": "sensor",
              "unit": "°C"
            },
            {
              "entity": "sensor.energy_usage",
              "name": "Energy this month",
              "period": {
                "calendar": {
                  "period": "month"
                }
              },
              "stat_type": "sum",
              "type": "statistic"
            },
            {
              "content": "## Status\n\nCurrent temp: {{ states('sensor.cpu_temp') }}°C",
              "title": "Status",
              "type": "markdown"
            },
            {
              "clock_style": "analog",
              "show_seconds": true,
              "time_format": "24",
              "type": "clock"
            },
            {
              "entities": [
                "calendar.family",
                "calendar.work"
              ],
              "initial_view": "listWeek",
              "title": "Schedule",
              "type": "calendar"
            },
            {
              "entities": [
                "sensor.cpu_temp"
              ],
              "hours_to_show": 12,
              "title": "Recent activity",
              "type": "logbook"
            }
          ],
          "title": "Visual",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Visual & History",
      "url_path": "cards-visual"
    }
  }
}
```

### `c.clock`

Golden case: `fixtures/dsl/dashboard_cards_visual/`.

```python
"""Golden case: DB3b's visual/history/text card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/visual.py`: `gauge`,
`history_graph`, `statistics_graph`, `sensor`, `statistic`, `markdown`
(including a Jinja template `content=`, passed through verbatim -- HA renders
it, Hassle never inspects it), `clock`, `calendar`, `logbook`.
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-visual", title="Visual & History")
def cards_visual():
    with view(title="Visual", type="masonry"):
        c.gauge(
            "sensor.cpu_temp",
            name="CPU Temp",
            unit="°C",
            min=0,
            max=100,
            needle=True,
            severity={"green": 0, "yellow": 60, "red": 85},
        )
        c.history_graph(
            "sensor.cpu_temp",
            "sensor.living_room_temp",
            {"entity": "sensor.attic_temp", "name": "Attic"},
            title="Temperatures",
            hours_to_show=48,
            show_names=True,
        )
        c.statistics_graph(
            "sensor.energy_usage",
            title="Energy",
            stat_types=["mean", "max"],
            period="hour",
            days_to_show=7,
        )
        c.sensor(
            "sensor.cpu_temp",
            name="CPU",
            graph="line",
            detail=2,
            hours_to_show=24,
            unit="°C",
        )
        c.statistic(
            "sensor.energy_usage",
            name="Energy this month",
            stat_type="sum",
            period={"calendar": {"period": "month"}},
        )
        c.markdown(
            "## Status\n\nCurrent temp: {{ states('sensor.cpu_temp') }}°C",
            title="Status",
        )
        c.clock(clock_style="analog", show_seconds=True, time_format="24")
        c.calendar(
            "calendar.family",
            "calendar.work",
            initial_view="listWeek",
            title="Schedule",
        )
        c.logbook("sensor.cpu_temp", hours_to_show=12, title="Recent activity")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-visual": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "entity": "sensor.cpu_temp",
              "max": 100,
              "min": 0,
              "name": "CPU Temp",
              "needle": true,
              "severity": {
                "green": 0,
                "red": 85,
                "yellow": 60
              },
              "type": "gauge",
              "unit": "°C"
            },
            {
              "entities": [
                "sensor.cpu_temp",
                "sensor.living_room_temp",
                {
                  "entity": "sensor.attic_temp",
                  "name": "Attic"
                }
              ],
              "hours_to_show": 48,
              "show_names": true,
              "title": "Temperatures",
              "type": "history-graph"
            },
            {
              "days_to_show": 7,
              "entities": [
                "sensor.energy_usage"
              ],
              "period": "hour",
              "stat_types": [
                "mean",
                "max"
              ],
              "title": "Energy",
              "type": "statistics-graph"
            },
            {
              "detail": 2,
              "entity": "sensor.cpu_temp",
              "graph": "line",
              "hours_to_show": 24,
              "name": "CPU",
              "type": "sensor",
              "unit": "°C"
            },
            {
              "entity": "sensor.energy_usage",
              "name": "Energy this month",
              "period": {
                "calendar": {
                  "period": "month"
                }
              },
              "stat_type": "sum",
              "type": "statistic"
            },
            {
              "content": "## Status\n\nCurrent temp: {{ states('sensor.cpu_temp') }}°C",
              "title": "Status",
              "type": "markdown"
            },
            {
              "clock_style": "analog",
              "show_seconds": true,
              "time_format": "24",
              "type": "clock"
            },
            {
              "entities": [
                "calendar.family",
                "calendar.work"
              ],
              "initial_view": "listWeek",
              "title": "Schedule",
              "type": "calendar"
            },
            {
              "entities": [
                "sensor.cpu_temp"
              ],
              "hours_to_show": 12,
              "title": "Recent activity",
              "type": "logbook"
            }
          ],
          "title": "Visual",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Visual & History",
      "url_path": "cards-visual"
    }
  }
}
```

### `c.calendar`

Golden case: `fixtures/dsl/dashboard_cards_visual/`.

```python
"""Golden case: DB3b's visual/history/text card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/visual.py`: `gauge`,
`history_graph`, `statistics_graph`, `sensor`, `statistic`, `markdown`
(including a Jinja template `content=`, passed through verbatim -- HA renders
it, Hassle never inspects it), `clock`, `calendar`, `logbook`.
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-visual", title="Visual & History")
def cards_visual():
    with view(title="Visual", type="masonry"):
        c.gauge(
            "sensor.cpu_temp",
            name="CPU Temp",
            unit="°C",
            min=0,
            max=100,
            needle=True,
            severity={"green": 0, "yellow": 60, "red": 85},
        )
        c.history_graph(
            "sensor.cpu_temp",
            "sensor.living_room_temp",
            {"entity": "sensor.attic_temp", "name": "Attic"},
            title="Temperatures",
            hours_to_show=48,
            show_names=True,
        )
        c.statistics_graph(
            "sensor.energy_usage",
            title="Energy",
            stat_types=["mean", "max"],
            period="hour",
            days_to_show=7,
        )
        c.sensor(
            "sensor.cpu_temp",
            name="CPU",
            graph="line",
            detail=2,
            hours_to_show=24,
            unit="°C",
        )
        c.statistic(
            "sensor.energy_usage",
            name="Energy this month",
            stat_type="sum",
            period={"calendar": {"period": "month"}},
        )
        c.markdown(
            "## Status\n\nCurrent temp: {{ states('sensor.cpu_temp') }}°C",
            title="Status",
        )
        c.clock(clock_style="analog", show_seconds=True, time_format="24")
        c.calendar(
            "calendar.family",
            "calendar.work",
            initial_view="listWeek",
            title="Schedule",
        )
        c.logbook("sensor.cpu_temp", hours_to_show=12, title="Recent activity")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-visual": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "entity": "sensor.cpu_temp",
              "max": 100,
              "min": 0,
              "name": "CPU Temp",
              "needle": true,
              "severity": {
                "green": 0,
                "red": 85,
                "yellow": 60
              },
              "type": "gauge",
              "unit": "°C"
            },
            {
              "entities": [
                "sensor.cpu_temp",
                "sensor.living_room_temp",
                {
                  "entity": "sensor.attic_temp",
                  "name": "Attic"
                }
              ],
              "hours_to_show": 48,
              "show_names": true,
              "title": "Temperatures",
              "type": "history-graph"
            },
            {
              "days_to_show": 7,
              "entities": [
                "sensor.energy_usage"
              ],
              "period": "hour",
              "stat_types": [
                "mean",
                "max"
              ],
              "title": "Energy",
              "type": "statistics-graph"
            },
            {
              "detail": 2,
              "entity": "sensor.cpu_temp",
              "graph": "line",
              "hours_to_show": 24,
              "name": "CPU",
              "type": "sensor",
              "unit": "°C"
            },
            {
              "entity": "sensor.energy_usage",
              "name": "Energy this month",
              "period": {
                "calendar": {
                  "period": "month"
                }
              },
              "stat_type": "sum",
              "type": "statistic"
            },
            {
              "content": "## Status\n\nCurrent temp: {{ states('sensor.cpu_temp') }}°C",
              "title": "Status",
              "type": "markdown"
            },
            {
              "clock_style": "analog",
              "show_seconds": true,
              "time_format": "24",
              "type": "clock"
            },
            {
              "entities": [
                "calendar.family",
                "calendar.work"
              ],
              "initial_view": "listWeek",
              "title": "Schedule",
              "type": "calendar"
            },
            {
              "entities": [
                "sensor.cpu_temp"
              ],
              "hours_to_show": 12,
              "title": "Recent activity",
              "type": "logbook"
            }
          ],
          "title": "Visual",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Visual & History",
      "url_path": "cards-visual"
    }
  }
}
```

### `c.logbook`

Golden case: `fixtures/dsl/dashboard_cards_visual/`.

```python
"""Golden case: DB3b's visual/history/text card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/visual.py`: `gauge`,
`history_graph`, `statistics_graph`, `sensor`, `statistic`, `markdown`
(including a Jinja template `content=`, passed through verbatim -- HA renders
it, Hassle never inspects it), `clock`, `calendar`, `logbook`.
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-visual", title="Visual & History")
def cards_visual():
    with view(title="Visual", type="masonry"):
        c.gauge(
            "sensor.cpu_temp",
            name="CPU Temp",
            unit="°C",
            min=0,
            max=100,
            needle=True,
            severity={"green": 0, "yellow": 60, "red": 85},
        )
        c.history_graph(
            "sensor.cpu_temp",
            "sensor.living_room_temp",
            {"entity": "sensor.attic_temp", "name": "Attic"},
            title="Temperatures",
            hours_to_show=48,
            show_names=True,
        )
        c.statistics_graph(
            "sensor.energy_usage",
            title="Energy",
            stat_types=["mean", "max"],
            period="hour",
            days_to_show=7,
        )
        c.sensor(
            "sensor.cpu_temp",
            name="CPU",
            graph="line",
            detail=2,
            hours_to_show=24,
            unit="°C",
        )
        c.statistic(
            "sensor.energy_usage",
            name="Energy this month",
            stat_type="sum",
            period={"calendar": {"period": "month"}},
        )
        c.markdown(
            "## Status\n\nCurrent temp: {{ states('sensor.cpu_temp') }}°C",
            title="Status",
        )
        c.clock(clock_style="analog", show_seconds=True, time_format="24")
        c.calendar(
            "calendar.family",
            "calendar.work",
            initial_view="listWeek",
            title="Schedule",
        )
        c.logbook("sensor.cpu_temp", hours_to_show=12, title="Recent activity")
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-visual": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "entity": "sensor.cpu_temp",
              "max": 100,
              "min": 0,
              "name": "CPU Temp",
              "needle": true,
              "severity": {
                "green": 0,
                "red": 85,
                "yellow": 60
              },
              "type": "gauge",
              "unit": "°C"
            },
            {
              "entities": [
                "sensor.cpu_temp",
                "sensor.living_room_temp",
                {
                  "entity": "sensor.attic_temp",
                  "name": "Attic"
                }
              ],
              "hours_to_show": 48,
              "show_names": true,
              "title": "Temperatures",
              "type": "history-graph"
            },
            {
              "days_to_show": 7,
              "entities": [
                "sensor.energy_usage"
              ],
              "period": "hour",
              "stat_types": [
                "mean",
                "max"
              ],
              "title": "Energy",
              "type": "statistics-graph"
            },
            {
              "detail": 2,
              "entity": "sensor.cpu_temp",
              "graph": "line",
              "hours_to_show": 24,
              "name": "CPU",
              "type": "sensor",
              "unit": "°C"
            },
            {
              "entity": "sensor.energy_usage",
              "name": "Energy this month",
              "period": {
                "calendar": {
                  "period": "month"
                }
              },
              "stat_type": "sum",
              "type": "statistic"
            },
            {
              "content": "## Status\n\nCurrent temp: {{ states('sensor.cpu_temp') }}°C",
              "title": "Status",
              "type": "markdown"
            },
            {
              "clock_style": "analog",
              "show_seconds": true,
              "time_format": "24",
              "type": "clock"
            },
            {
              "entities": [
                "calendar.family",
                "calendar.work"
              ],
              "initial_view": "listWeek",
              "title": "Schedule",
              "type": "calendar"
            },
            {
              "entities": [
                "sensor.cpu_temp"
              ],
              "hours_to_show": 12,
              "title": "Recent activity",
              "type": "logbook"
            }
          ],
          "title": "Visual",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Visual & History",
      "url_path": "cards-visual"
    }
  }
}
```

### `c.iframe`

Golden case: `fixtures/dsl/dashboard_cards_media/`.

```python
"""Golden case: DB3b's media card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/media.py`: `iframe`,
`picture`, `picture_glance`, `picture_elements` (with an `elements=`
passthrough list, §5.3's "passthrough-in-v1" sub-vocabulary), `map` (with
`geo_location_sources=`).
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-media", title="Media")
def cards_media():
    with view(title="Media", type="masonry"):
        c.iframe(
            "https://example.com/panel",
            title="Panel",
            aspect_ratio="75%",
        )
        c.picture(
            "/local/floorplan.png",
            tap_action={"action": "navigate", "navigation_path": "/lovelace/floorplan"},
        )
        c.picture_glance(
            "light.hall",
            "lock.front_door",
            title="Entry",
            image="/local/entry.jpg",
            camera_image="camera.front_door",
        )
        c.picture_elements(
            "/local/floorplan.png",
            camera_image="camera.front_door",
            elements=[
                {
                    "type": "state-icon",
                    "entity": "light.hall",
                    "style": {"top": "20%", "left": "30%"},
                },
                {"type": "state-label", "entity": "sensor.cpu_temp"},
            ],
        )
        c.map(
            "device_tracker.phone",
            "person.alex",
            geo_location_sources=["all"],
            hours_to_show=6,
        )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-media": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "aspect_ratio": "75%",
              "title": "Panel",
              "type": "iframe",
              "url": "https://example.com/panel"
            },
            {
              "image": "/local/floorplan.png",
              "tap_action": {
                "action": "navigate",
                "navigation_path": "/lovelace/floorplan"
              },
              "type": "picture"
            },
            {
              "camera_image": "camera.front_door",
              "entities": [
                "light.hall",
                "lock.front_door"
              ],
              "image": "/local/entry.jpg",
              "title": "Entry",
              "type": "picture-glance"
            },
            {
              "camera_image": "camera.front_door",
              "elements": [
                {
                  "entity": "light.hall",
                  "style": {
                    "left": "30%",
                    "top": "20%"
                  },
                  "type": "state-icon"
                },
                {
                  "entity": "sensor.cpu_temp",
                  "type": "state-label"
                }
              ],
              "image": "/local/floorplan.png",
              "type": "picture-elements"
            },
            {
              "entities": [
                "device_tracker.phone",
                "person.alex"
              ],
              "geo_location_sources": [
                "all"
              ],
              "hours_to_show": 6,
              "type": "map"
            }
          ],
          "title": "Media",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Media",
      "url_path": "cards-media"
    }
  }
}
```

See also: `fixtures/dsl/dashboard_cards_media_extra/`

### `c.picture`

Golden case: `fixtures/dsl/dashboard_cards_media/`.

```python
"""Golden case: DB3b's media card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/media.py`: `iframe`,
`picture`, `picture_glance`, `picture_elements` (with an `elements=`
passthrough list, §5.3's "passthrough-in-v1" sub-vocabulary), `map` (with
`geo_location_sources=`).
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-media", title="Media")
def cards_media():
    with view(title="Media", type="masonry"):
        c.iframe(
            "https://example.com/panel",
            title="Panel",
            aspect_ratio="75%",
        )
        c.picture(
            "/local/floorplan.png",
            tap_action={"action": "navigate", "navigation_path": "/lovelace/floorplan"},
        )
        c.picture_glance(
            "light.hall",
            "lock.front_door",
            title="Entry",
            image="/local/entry.jpg",
            camera_image="camera.front_door",
        )
        c.picture_elements(
            "/local/floorplan.png",
            camera_image="camera.front_door",
            elements=[
                {
                    "type": "state-icon",
                    "entity": "light.hall",
                    "style": {"top": "20%", "left": "30%"},
                },
                {"type": "state-label", "entity": "sensor.cpu_temp"},
            ],
        )
        c.map(
            "device_tracker.phone",
            "person.alex",
            geo_location_sources=["all"],
            hours_to_show=6,
        )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-media": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "aspect_ratio": "75%",
              "title": "Panel",
              "type": "iframe",
              "url": "https://example.com/panel"
            },
            {
              "image": "/local/floorplan.png",
              "tap_action": {
                "action": "navigate",
                "navigation_path": "/lovelace/floorplan"
              },
              "type": "picture"
            },
            {
              "camera_image": "camera.front_door",
              "entities": [
                "light.hall",
                "lock.front_door"
              ],
              "image": "/local/entry.jpg",
              "title": "Entry",
              "type": "picture-glance"
            },
            {
              "camera_image": "camera.front_door",
              "elements": [
                {
                  "entity": "light.hall",
                  "style": {
                    "left": "30%",
                    "top": "20%"
                  },
                  "type": "state-icon"
                },
                {
                  "entity": "sensor.cpu_temp",
                  "type": "state-label"
                }
              ],
              "image": "/local/floorplan.png",
              "type": "picture-elements"
            },
            {
              "entities": [
                "device_tracker.phone",
                "person.alex"
              ],
              "geo_location_sources": [
                "all"
              ],
              "hours_to_show": 6,
              "type": "map"
            }
          ],
          "title": "Media",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Media",
      "url_path": "cards-media"
    }
  }
}
```

### `c.picture_glance`

Golden case: `fixtures/dsl/dashboard_cards_media/`.

```python
"""Golden case: DB3b's media card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/media.py`: `iframe`,
`picture`, `picture_glance`, `picture_elements` (with an `elements=`
passthrough list, §5.3's "passthrough-in-v1" sub-vocabulary), `map` (with
`geo_location_sources=`).
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-media", title="Media")
def cards_media():
    with view(title="Media", type="masonry"):
        c.iframe(
            "https://example.com/panel",
            title="Panel",
            aspect_ratio="75%",
        )
        c.picture(
            "/local/floorplan.png",
            tap_action={"action": "navigate", "navigation_path": "/lovelace/floorplan"},
        )
        c.picture_glance(
            "light.hall",
            "lock.front_door",
            title="Entry",
            image="/local/entry.jpg",
            camera_image="camera.front_door",
        )
        c.picture_elements(
            "/local/floorplan.png",
            camera_image="camera.front_door",
            elements=[
                {
                    "type": "state-icon",
                    "entity": "light.hall",
                    "style": {"top": "20%", "left": "30%"},
                },
                {"type": "state-label", "entity": "sensor.cpu_temp"},
            ],
        )
        c.map(
            "device_tracker.phone",
            "person.alex",
            geo_location_sources=["all"],
            hours_to_show=6,
        )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-media": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "aspect_ratio": "75%",
              "title": "Panel",
              "type": "iframe",
              "url": "https://example.com/panel"
            },
            {
              "image": "/local/floorplan.png",
              "tap_action": {
                "action": "navigate",
                "navigation_path": "/lovelace/floorplan"
              },
              "type": "picture"
            },
            {
              "camera_image": "camera.front_door",
              "entities": [
                "light.hall",
                "lock.front_door"
              ],
              "image": "/local/entry.jpg",
              "title": "Entry",
              "type": "picture-glance"
            },
            {
              "camera_image": "camera.front_door",
              "elements": [
                {
                  "entity": "light.hall",
                  "style": {
                    "left": "30%",
                    "top": "20%"
                  },
                  "type": "state-icon"
                },
                {
                  "entity": "sensor.cpu_temp",
                  "type": "state-label"
                }
              ],
              "image": "/local/floorplan.png",
              "type": "picture-elements"
            },
            {
              "entities": [
                "device_tracker.phone",
                "person.alex"
              ],
              "geo_location_sources": [
                "all"
              ],
              "hours_to_show": 6,
              "type": "map"
            }
          ],
          "title": "Media",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Media",
      "url_path": "cards-media"
    }
  }
}
```

### `c.picture_elements`

Golden case: `fixtures/dsl/dashboard_cards_media/`.

```python
"""Golden case: DB3b's media card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/media.py`: `iframe`,
`picture`, `picture_glance`, `picture_elements` (with an `elements=`
passthrough list, §5.3's "passthrough-in-v1" sub-vocabulary), `map` (with
`geo_location_sources=`).
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-media", title="Media")
def cards_media():
    with view(title="Media", type="masonry"):
        c.iframe(
            "https://example.com/panel",
            title="Panel",
            aspect_ratio="75%",
        )
        c.picture(
            "/local/floorplan.png",
            tap_action={"action": "navigate", "navigation_path": "/lovelace/floorplan"},
        )
        c.picture_glance(
            "light.hall",
            "lock.front_door",
            title="Entry",
            image="/local/entry.jpg",
            camera_image="camera.front_door",
        )
        c.picture_elements(
            "/local/floorplan.png",
            camera_image="camera.front_door",
            elements=[
                {
                    "type": "state-icon",
                    "entity": "light.hall",
                    "style": {"top": "20%", "left": "30%"},
                },
                {"type": "state-label", "entity": "sensor.cpu_temp"},
            ],
        )
        c.map(
            "device_tracker.phone",
            "person.alex",
            geo_location_sources=["all"],
            hours_to_show=6,
        )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-media": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "aspect_ratio": "75%",
              "title": "Panel",
              "type": "iframe",
              "url": "https://example.com/panel"
            },
            {
              "image": "/local/floorplan.png",
              "tap_action": {
                "action": "navigate",
                "navigation_path": "/lovelace/floorplan"
              },
              "type": "picture"
            },
            {
              "camera_image": "camera.front_door",
              "entities": [
                "light.hall",
                "lock.front_door"
              ],
              "image": "/local/entry.jpg",
              "title": "Entry",
              "type": "picture-glance"
            },
            {
              "camera_image": "camera.front_door",
              "elements": [
                {
                  "entity": "light.hall",
                  "style": {
                    "left": "30%",
                    "top": "20%"
                  },
                  "type": "state-icon"
                },
                {
                  "entity": "sensor.cpu_temp",
                  "type": "state-label"
                }
              ],
              "image": "/local/floorplan.png",
              "type": "picture-elements"
            },
            {
              "entities": [
                "device_tracker.phone",
                "person.alex"
              ],
              "geo_location_sources": [
                "all"
              ],
              "hours_to_show": 6,
              "type": "map"
            }
          ],
          "title": "Media",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Media",
      "url_path": "cards-media"
    }
  }
}
```

### `c.map`

Golden case: `fixtures/dsl/dashboard_cards_media/`.

```python
"""Golden case: DB3b's media card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/media.py`: `iframe`,
`picture`, `picture_glance`, `picture_elements` (with an `elements=`
passthrough list, §5.3's "passthrough-in-v1" sub-vocabulary), `map` (with
`geo_location_sources=`).
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-media", title="Media")
def cards_media():
    with view(title="Media", type="masonry"):
        c.iframe(
            "https://example.com/panel",
            title="Panel",
            aspect_ratio="75%",
        )
        c.picture(
            "/local/floorplan.png",
            tap_action={"action": "navigate", "navigation_path": "/lovelace/floorplan"},
        )
        c.picture_glance(
            "light.hall",
            "lock.front_door",
            title="Entry",
            image="/local/entry.jpg",
            camera_image="camera.front_door",
        )
        c.picture_elements(
            "/local/floorplan.png",
            camera_image="camera.front_door",
            elements=[
                {
                    "type": "state-icon",
                    "entity": "light.hall",
                    "style": {"top": "20%", "left": "30%"},
                },
                {"type": "state-label", "entity": "sensor.cpu_temp"},
            ],
        )
        c.map(
            "device_tracker.phone",
            "person.alex",
            geo_location_sources=["all"],
            hours_to_show=6,
        )
```

Compiles to (canonical IR / stored HA shape):

```json
{
  "dashboard:cards-media": {
    "config": {
      "views": [
        {
          "cards": [
            {
              "aspect_ratio": "75%",
              "title": "Panel",
              "type": "iframe",
              "url": "https://example.com/panel"
            },
            {
              "image": "/local/floorplan.png",
              "tap_action": {
                "action": "navigate",
                "navigation_path": "/lovelace/floorplan"
              },
              "type": "picture"
            },
            {
              "camera_image": "camera.front_door",
              "entities": [
                "light.hall",
                "lock.front_door"
              ],
              "image": "/local/entry.jpg",
              "title": "Entry",
              "type": "picture-glance"
            },
            {
              "camera_image": "camera.front_door",
              "elements": [
                {
                  "entity": "light.hall",
                  "style": {
                    "left": "30%",
                    "top": "20%"
                  },
                  "type": "state-icon"
                },
                {
                  "entity": "sensor.cpu_temp",
                  "type": "state-label"
                }
              ],
              "image": "/local/floorplan.png",
              "type": "picture-elements"
            },
            {
              "entities": [
                "device_tracker.phone",
                "person.alex"
              ],
              "geo_location_sources": [
                "all"
              ],
              "hours_to_show": 6,
              "type": "map"
            }
          ],
          "title": "Media",
          "type": "masonry"
        }
      ]
    },
    "meta": {
      "title": "Media",
      "url_path": "cards-media"
    }
  }
}
```
